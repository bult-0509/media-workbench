"""Bilibili video preview, search and BBDown jobs for the local material desk."""
from __future__ import annotations

import json
import re
import subprocess
import threading
import time
import uuid
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import unquote, urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import core

router = APIRouter(prefix="/api/videos", dependencies=[Depends(lambda: core.require_module("videos"))])
BVID_RE = re.compile(r"^BV[1-9A-HJ-NP-Za-km-z]{10}$", re.I)
SPACE_RE = re.compile(r"(?:space\.bilibili\.com/)(\d+)", re.I)
NETWORK_LOCK = threading.Semaphore(2)
DOWNLOAD_LOCK = threading.Semaphore(1)
PREVIEW_CACHE: dict[str, tuple[float, dict]] = {}


def normalize_bvid(value: str) -> str:
    value = value.strip()
    if value[:2].casefold() == "bv":
        value = "BV" + value[2:]
    if not BVID_RE.fullmatch(value):
        raise HTTPException(400, "请输入完整的 BV 号，例如 BV1xx411c7mD")
    return value


def bili_json(url: str, params: dict) -> dict:
    try:
        with NETWORK_LOCK, httpx.Client(timeout=18, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com/"}) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            value = response.json()
    except Exception as exc:
        raise HTTPException(502, "B 站暂时无法连接，请稍后重试") from exc
    if not isinstance(value, dict) or value.get("code") != 0:
        raise HTTPException(404, str(value.get("message") if isinstance(value, dict) else "未找到该视频"))
    return value.get("data") or {}


def video_info(bvid: str) -> dict:
    bvid = normalize_bvid(bvid)
    cached = PREVIEW_CACHE.get(bvid)
    if cached and time.time() - cached[0] < 300:
        return cached[1]
    data = bili_json("https://api.bilibili.com/x/web-interface/view", {"bvid": bvid})
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    item = {
        "bvid": bvid, "title": str(data.get("title") or bvid),
        "owner": str(owner.get("name") or ""),
        "cover": str(data.get("pic") or ""),
        "duration": int(data.get("duration") or 0),
        "description": str(data.get("desc") or ""),
        "url": f"https://www.bilibili.com/video/{bvid}",
    }
    PREVIEW_CACHE[bvid] = (time.time(), item)
    return item


def queue_items() -> list[dict]:
    with core.database() as db:
        rows = db.execute("SELECT * FROM video_download_stack ORDER BY created DESC").fetchall()
    return [dict(row) for row in rows]


@router.get("/preview/{bvid}")
def preview(bvid: str):
    return video_info(bvid)


@router.get("/stack")
def stack():
    return {"items": queue_items()}


class VideoItem(BaseModel):
    bvid: str = Field(min_length=12, max_length=16)


@router.post("/stack")
def add_to_stack(body: VideoItem):
    item = video_info(body.bvid)
    item_id = uuid.uuid4().hex
    now = time.time()
    with core.database() as db:
        old = db.execute("SELECT id FROM video_download_stack WHERE bvid=?", (item["bvid"],)).fetchone()
        if old:
            return {"item": next(v for v in queue_items() if v["id"] == old["id"]), "already_exists": True}
        db.execute("""INSERT INTO video_download_stack
                   (id,bvid,title,owner,cover,duration,description,status,error,created,updated)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                   (item_id, item["bvid"], item["title"], item["owner"], item["cover"], item["duration"], item["description"], "ready", "", now, now))
    return {"item": next(v for v in queue_items() if v["id"] == item_id), "already_exists": False}


@router.delete("/stack/{item_id}")
def remove_from_stack(item_id: str):
    with core.database() as db:
        cursor = db.execute("DELETE FROM video_download_stack WHERE id=?", (item_id,))
    if not cursor.rowcount:
        raise HTTPException(404, "下载栈中没有这个视频")
    return {"ok": True}


def author_mid(homepage: str) -> str:
    parsed = urlparse(homepage.strip())
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(400, "请输入 B 站个人主页链接")
    match = SPACE_RE.search(unquote(homepage))
    if not match:
        raise HTTPException(400, "链接中没有识别到 B 站用户主页 ID")
    return match.group(1)


@router.get("/smart-search")
def smart_search(homepage: str, q: str):
    q = q.strip()
    if not q or len(q) > 100:
        raise HTTPException(400, "请输入要查找的视频标题")
    mid = author_mid(homepage)
    data = bili_json("https://api.bilibili.com/x/space/arc/search", {"mid": mid, "pn": 1, "ps": 50, "keyword": q, "order": "pubdate"})
    vlist = (data.get("list") or {}).get("vlist") or []
    needle = q.casefold()
    items = []
    for row in vlist:
        title = re.sub(r"<[^>]+>", "", str(row.get("title") or ""))
        desc = str(row.get("description") or "")
        bvid = str(row.get("bvid") or "")
        if not BVID_RE.fullmatch(bvid):
            continue
        haystack = f"{title} {desc}".casefold()
        score = max(SequenceMatcher(None, needle, title.casefold()).ratio(), SequenceMatcher(None, needle, haystack).ratio())
        if needle in haystack:
            score = max(score, 0.92)
        items.append({
            "bvid": bvid, "title": title or bvid, "owner": str(row.get("author") or ""),
            "cover": str(row.get("pic") or ""), "duration": int(row.get("length_seconds") or 0),
            "description": desc, "score": round(score, 3),
            "url": f"https://www.bilibili.com/video/{bvid}",
        })
    return {"items": sorted(items, key=lambda item: (-item["score"], item["title"]))[:20], "author_id": mid}


class DownloadRequest(BaseModel):
    project_id: str
    item_ids: list[str] = Field(min_length=1, max_length=20)


def update_stack(item_id: str, *, status: str, error: str = ""):
    with core.database() as db:
        db.execute("UPDATE video_download_stack SET status=?,error=?,updated=? WHERE id=?", (status, error, time.time(), item_id))


def download_one(job_id: str, item: dict, project_id: str, position: int, total: int) -> dict:
    destination, _ = core.resolve_destination(project_id, "video", "auto")
    executable = Path(core.CONFIG.get("bbdown", "")).resolve()
    if not executable.is_file():
        raise RuntimeError("未找到 BBDown.exe，请在素材台设置中检查 BBDown 路径")
    staging = core.DATA_DIR / 'video-downloads' / job_id / item['id']
    staging.mkdir(parents=True, exist_ok=True)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = [
        str(executable), item["url"] if item.get("url") else f"https://www.bilibili.com/video/{item['bvid']}",
        "--work-dir", str(staging),
        "--ffmpeg-path", str(Path(core.CONFIG["ffmpeg"]).resolve()),
        "--skip-cover", "--skip-subtitle", "--hide-streams",
        "--file-pattern", "<videoTitle> [<bvid>]",
    ]
    # BBDown defaults to descending quality and bitrate. A partial priority list
    # would incorrectly put 1080P ahead of available 4K and 1440P streams.
    completed = subprocess.run(command, cwd=executable.parent, capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=60 * 60, creationflags=flags)
    (staging / 'download.log').write_text(completed.stdout + '\n' + completed.stderr, encoding='utf-8')
    if completed.returncode:
        detail = (completed.stderr or completed.stdout or "BBDown 下载失败").strip()
        raise RuntimeError(detail[-700:])
    after = [p for p in staging.rglob('*') if p.is_file() and p.suffix.lower() in {".mp4", ".mkv", ".flv", ".webm"}]
    if not after:
        raise RuntimeError("BBDown 未产出可识别的视频或音频文件")
    saved = []
    for path in after:
        info = core.media_info(path)
        streams = info.get('streams', [])
        video = next((s for s in streams if s.get('codec_type') == 'video'), None)
        if not video or not any(s.get('codec_type') == 'audio' for s in streams):
            raise RuntimeError('下载文件未包含完整的视频与音频，未写入项目')
        result = core.copy_into(path, destination)
        result.update(width=video.get('width'), height=video.get('height'))
        saved.append(result)
        path.unlink()
    core.update_job(job_id, progress=int((position + 1) / total * 100))
    return {**saved[0], "name": item["title"], "bvid": item["bvid"], "status": "downloaded", "files": saved}


def download_worker(job_id: str, project_id: str, items: list[dict]):
    completed = []
    try:
        with DOWNLOAD_LOCK:
            core.update_job(job_id, status="running", progress=1)
            for index, item in enumerate(items):
                update_stack(item["id"], status="downloading")
                try:
                    result = download_one(job_id, item, project_id, index, len(items))
                    completed.append(result)
                    core.update_job(job_id, result=completed)
                    update_stack(item["id"], status="done")
                except Exception as exc:
                    update_stack(item["id"], status="failed", error=str(exc))
                    raise
            core.update_job(job_id, status="succeeded", progress=100, result=completed)
            from modules.library import rescan_if_idle
            rescan_if_idle()
    except Exception as exc:
        core.update_job(job_id, status="failed", error=str(getattr(exc, "detail", exc)), result=completed)


@router.post("/download")
def download(body: DownloadRequest):
    core.get_project(body.project_id)
    items = [item for item in queue_items() if item["id"] in set(body.item_ids)]
    if len(items) != len(set(body.item_ids)):
        raise HTTPException(404, "下载栈中的视频已变化，请刷新后重试")
    busy = [item["title"] for item in items if item["status"] == "downloading"]
    if busy:
        raise HTTPException(409, "所选视频正在下载")
    for item in items:
        update_stack(item["id"], status="queued")
    job_id = core.create_job("videos", f"下载 {len(items)} 个视频", {"project_id": body.project_id, "item_ids": body.item_ids})
    threading.Thread(target=download_worker, args=(job_id, body.project_id, items), daemon=True).start()
    return {"job_id": job_id}
