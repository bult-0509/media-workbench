from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import core

router = APIRouter(prefix="/api/library", dependencies=[Depends(lambda: core.require_module("library"))])
SCAN = {"running": False, "count": 0, "last_scan": None, "error": None, "pending": False}
SCAN_LOCK = threading.Lock()
MEDIA_LOCK = threading.Semaphore(2)
CACHE = core.DATA_DIR / "previews"
CACHE.mkdir(exist_ok=True)


def scan_now():
    if not SCAN_LOCK.acquire(blocking=False):
        return
    SCAN.update(running=True, count=0, error=None, pending=False)
    try:
        seen = set()
        rows = []
        for source in core.indexed_source_configs():
            root = Path(source["path"])
            if not root.exists():
                continue
            core.confined(root, core.VIDEO_ROOT)
            for current, dirs, filenames in os.walk(root, followlinks=False):
                dirs[:] = [d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__", "Backup"}]
                for name in filenames:
                    path = Path(current) / name
                    kind = core.kind_of(path)
                    if not kind:
                        continue
                    try:
                        resolved = core.confined(path, root)
                        if str(resolved).casefold() in seen:
                            continue
                        stat = path.stat()
                    except (OSError, HTTPException):
                        continue
                    seen.add(str(resolved).casefold())
                    relative = path.relative_to(root)
                    collection = relative.parts[0] if len(relative.parts) > 1 else source["name"]
                    searchable = core.normalize(f"{path.stem} {relative} {source['name']}")
                    if "memes_video" in searchable:
                        searchable += " 美式鬼畜 鬼畜 梗 搞笑"
                    rows.append((core.ident(resolved), str(resolved), source["id"], path.stem, kind, path.suffix.lower(), stat.st_size,
                                 stat.st_mtime, str(relative), collection, searchable))
                    SCAN["count"] = len(rows)
        valid_sources = {source["id"] for source in core.indexed_source_configs()}
        rows = [row for row in rows if row[2] in valid_sources]
        with core.database() as db:
            db.execute("UPDATE assets SET scanned=0")
            db.executemany("""INSERT INTO assets(id,path,source_id,title,kind,extension,size,modified,relative,collection,search_text,scanned)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET
              source_id=excluded.source_id,kind=excluded.kind,extension=excluded.extension,size=excluded.size,
              modified=excluded.modified,relative=excluded.relative,collection=excluded.collection,
              search_text=excluded.search_text,scanned=1""", rows)
        SCAN.update(last_scan=time.time())
        core.learn_layouts(force=True)
    except Exception as exc:
        SCAN["error"] = str(exc)
    finally:
        rerun = SCAN["pending"]
        SCAN["running"] = False
        SCAN_LOCK.release()
        if rerun:
            threading.Thread(target=scan_now, daemon=True).start()


def rescan_if_idle():
    if SCAN["running"]:
        SCAN["pending"] = True
    else:
        threading.Thread(target=scan_now, daemon=True).start()


@router.post("/scan")
def rescan():
    threading.Thread(target=scan_now, daemon=True).start()
    return SCAN


@router.get("/scan")
def scan_status():
    return SCAN


@router.get("/assets")
def list_assets(q: str = "", kind: str = "", source: str = "", collection: str = "", favorite: bool = False,
                sort: str = "modified", order: str = "desc",
                page: int = Query(1, ge=1), limit: int = Query(36, ge=1, le=80)):
    where, params = ["scanned=1"], []
    for column, value in [("kind", kind), ("source_id", source), ("collection", collection)]:
        if value:
            where.append(f"{column}=?")
            params.append(value)
    if favorite:
        where.append("favorite=1")
    for token in core.normalize(q)[:200].split():
        escaped = token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(search_text || ' ' || lower(title) || ' ' || lower(tags)) LIKE ? ESCAPE '\\'")
        params.append("%" + escaped + "%")
    clause = " AND ".join(where)
    columns = {"modified": "modified", "size": "size", "type": "kind, extension", "name": "title COLLATE NOCASE"}
    if sort not in columns or order not in {"asc", "desc"}:
        raise HTTPException(400, "不支持的排序方式")
    direction = order.upper()
    sort_sql = ", ".join(f"{column} {direction}" for column in columns[sort].split(", "))
    with core.database() as db:
        count = db.execute("SELECT COUNT(*) FROM assets WHERE " + clause, params).fetchone()[0]
        rows = db.execute("SELECT * FROM assets WHERE " + clause + f" ORDER BY {sort_sql}, id LIMIT ? OFFSET ?", [*params, limit, (page - 1) * limit]).fetchall()
    return {"items": [dict(row) for row in rows], "total": count, "page": page, "pages": max(1, (count + limit - 1) // limit)}


@router.get("/stats")
def stats():
    with core.database() as db:
        by_kind = {r["kind"]: r["n"] for r in db.execute("SELECT kind,COUNT(*) n FROM assets WHERE scanned=1 GROUP BY kind")}
        by_source = {r["source_id"]: r["n"] for r in db.execute("SELECT source_id,COUNT(*) n FROM assets WHERE scanned=1 GROUP BY source_id")}
        collections = [dict(r) for r in db.execute("SELECT collection,source_id,COUNT(*) n FROM assets WHERE scanned=1 GROUP BY collection,source_id ORDER BY n DESC")]
        fav = db.execute("SELECT COUNT(*) FROM assets WHERE favorite=1 AND scanned=1").fetchone()[0]
    return {"total": sum(by_kind.values()), "kinds": by_kind, "sources": by_source, "collections": collections, "favorites": fav, "scan": SCAN}


class Metadata(BaseModel):
    title: str | None = Field(None, max_length=300)
    tags: str | None = Field(None, max_length=1000)
    favorite: bool | None = None


@router.patch("/assets/{asset_id}")
def metadata(asset_id: str, body: Metadata):
    core.get_asset(asset_id)
    fields = body.model_dump(exclude_none=True)
    if fields:
        with core.database() as db:
            db.execute("UPDATE assets SET " + ",".join(f"{k}=?" for k in fields) + " WHERE id=?", [*fields.values(), asset_id])
    return core.get_asset(asset_id)


def ffmpeg() -> str:
    path = Path(core.CONFIG["ffmpeg"])
    if not path.is_file():
        raise HTTPException(503, "FFmpeg 未找到，请检查设置")
    return str(path)


@router.get("/assets/{asset_id}/metadata")
def inspect_media(asset_id: str):
    asset = core.get_asset(asset_id)
    if asset["duration"] is not None or asset["kind"] == "image":
        return asset
    try:
        info = core.media_info(Path(asset["path"]))
        video = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), {})
        duration = float(info.get("format", {}).get("duration", 0))
        with core.database() as db:
            db.execute("UPDATE assets SET duration=?,width=?,height=? WHERE id=?", (duration, video.get("width"), video.get("height"), asset_id))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return core.get_asset(asset_id)


@router.get("/assets/{asset_id}/file")
def asset_file(asset_id: str):
    asset = core.get_asset(asset_id)
    return FileResponse(asset["path"], content_disposition_type="inline", filename=Path(asset["path"]).name)


@router.get("/assets/{asset_id}/thumb")
def thumbnail(asset_id: str):
    asset = core.get_asset(asset_id)
    if asset["kind"] == "audio":
        raise HTTPException(404, "音频无缩略图")
    cache = CACHE / f"{asset_id}-{int(asset['modified'])}.jpg"
    if not cache.exists():
        with MEDIA_LOCK:
            if not cache.exists():
                try:
                    if asset["kind"] == "image":
                        from PIL import Image, ImageOps
                        with Image.open(asset["path"]) as img:
                            img = ImageOps.exif_transpose(img)
                            img.thumbnail((640, 400))
                            img.convert("RGB").save(cache, "JPEG", quality=80)
                    else:
                        result = subprocess.run([ffmpeg(), "-hide_banner", "-loglevel", "error", "-threads", "1", "-i", asset["path"],
                           "-frames:v", "1", "-vf", "thumbnail=12,scale=640:400:force_original_aspect_ratio=decrease", "-threads", "1", "-y", str(cache)],
                           capture_output=True, timeout=20, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                        if result.returncode:
                            raise ValueError("无法生成预览")
                except Exception:
                    if cache.exists():
                        cache.unlink()
                    raise HTTPException(422, "当前文件无法生成封面，仍可保存原件")
    return FileResponse(cache, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


class DragItems(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=30)


@router.post("/drag")
def drag_files(body: DragItems):
    files = []
    for asset_id in list(dict.fromkeys(body.asset_ids)):
        asset = core.get_asset(asset_id)
        path = Path(asset["path"])
        if not path.is_file():
            raise HTTPException(404, "素材已移动，请重新扫描")
        files.append(str(path.resolve()))
    return {"files": files}
