"""GD source is isolated from the local library; network failure never blocks it."""
from __future__ import annotations

import ipaddress
import json
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import core

router = APIRouter(prefix="/api/music", dependencies=[Depends(lambda: core.require_module("music"))])
API = "https://music-api.gdstudio.xyz/api.php"
SOURCES = {"netease", "kuwo", "tencent"}
NETWORK_LOCK = threading.Semaphore(1)
SEARCH_CACHE = {}


def api_request(params: dict):
    try:
        with NETWORK_LOCK, httpx.Client(timeout=18, follow_redirects=False) as client:
            result = client.get(API, params=params)
            result.raise_for_status()
            return result.json()
    except Exception:
        raise HTTPException(502, "音乐来源暂时无法连接。可以打开 GD 音乐台，或使用本地音乐曲库。")


@router.get("/search")
def search(q: str = "", source: str = "netease"):
    if source not in SOURCES:
        raise HTTPException(400, "不支持此音乐来源")
    if not q.strip() or len(q) > 100:
        return {"items": []}
    key = (q.strip(), source)
    if key in SEARCH_CACHE and time.time() - SEARCH_CACHE[key][0] < 300:
        return {"items": SEARCH_CACHE[key][1]}
    result = api_request({"types": "search", "source": source, "name": q.strip(), "count": 15, "pages": 1})
    if not isinstance(result, list):
        raise HTTPException(502, "音乐来源没有返回有效结果，可以稍后重试")
    items = [{"id": str(i.get("id", "")), "name": str(i.get("name", "未命名")), "artist": " / ".join(i.get("artist", [])) if isinstance(i.get("artist"), list) else str(i.get("artist", "")), "album": str(i.get("album", "")), "source": source} for i in result[:15] if i.get("id")]
    if len(SEARCH_CACHE) > 100:
        SEARCH_CACHE.clear()
    SEARCH_CACHE[key] = (time.time(), items)
    return {"items": items}


class Track(BaseModel):
    id: str = Field(max_length=120)
    source: str = "netease"
    name: str = Field("音乐", max_length=160)
    artist: str = Field("", max_length=120)


class MusicSave(Track):
    project_id: str
    relative: str = "auto"
    rights_confirmed: bool = False


def remote_url(track: Track) -> str:
    if track.source not in SOURCES:
        raise HTTPException(400, "不支持此来源")
    result = api_request({"types": "url", "source": track.source, "id": track.id, "br": 320})
    url = result.get("url") if isinstance(result, dict) else None
    if not url:
        raise HTTPException(404, "来源暂未提供这首音乐的可用文件")
    check_url(url)
    return url


def check_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(400, "音乐地址无效")
    if parsed.port not in {None, 80, 443}:
        raise HTTPException(400, "音乐地址端口不受支持")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
            raise ValueError()
    except Exception:
        raise HTTPException(400, "音乐来源地址不可访问")


@router.post("/preview")
def preview(track: Track):
    return {"url": remote_url(track)}


def download_job(job_id: str, body: MusicSave):
    temp = core.DATA_DIR / f"music-{job_id}.download"
    try:
        core.update_job(job_id, status="running")
        destination, _ = core.resolve_destination(body.project_id, "music", body.relative)
        url = remote_url(body)
        with httpx.Client(timeout=httpx.Timeout(60, connect=15), follow_redirects=False) as client:
            for _ in range(4):
                check_url(url)
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        from urllib.parse import urljoin
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    response.raise_for_status()
                    size = int(response.headers.get("content-length", "0"))
                    if size > 512 * 1024 * 1024:
                        raise ValueError("文件超过 512 MB 上限")
                    received = 0
                    with temp.open("xb") as handle:
                        for chunk in response.iter_bytes(1024 * 256):
                            received += len(chunk)
                            if received > 512 * 1024 * 1024:
                                raise ValueError("文件超过下载上限")
                            handle.write(chunk)
                            core.update_job(job_id, progress=min(85, int(received / max(size, 1) * 85)) if size else 20)
                    break
            else:
                raise ValueError("音乐来源重定向过多")
        info = core.media_info(temp)
        audio = next((s for s in info.get("streams", []) if s.get("codec_type") == "audio"), None)
        if not audio:
            raise ValueError("来源返回的不是有效音频，未写入项目")
        codec = audio.get("codec_name", "")
        container = info.get("format", {}).get("format_name", "")
        suffix = {"mp3": ".mp3", "flac": ".flac", "aac": ".aac", "ogg": ".opus" if codec == "opus" else ".ogg", "wav": ".wav", "aiff": ".aiff", "asf": ".wma"}.get(container)
        if any(value in container.split(',') for value in ['mov', 'mp4', 'm4a']):
            suffix = '.m4a'
        if not suffix:
            raise ValueError("来源返回了暂不支持的音频封装，未写入项目")
        name = core.safe_filename(f"{body.artist + ' - ' if body.artist else ''}{body.name}{suffix}")
        saved = core.copy_into(temp, destination, name)
        core.update_job(job_id, status="succeeded", progress=100, result=[saved])
        from modules.library import rescan_if_idle
        rescan_if_idle()
    except Exception as exc:
        core.update_job(job_id, status="failed", error=str(getattr(exc, "detail", exc)))
    finally:
        if temp.exists():
            temp.unlink()


@router.post("/save")
def save(body: MusicSave):
    if not body.rights_confirmed:
        raise HTTPException(403, "请先确认拥有音乐的下载及计划使用授权")
    core.resolve_destination(body.project_id, "music", body.relative)
    job_id = core.create_job("music", body.name, body.model_dump())
    threading.Thread(target=download_job, args=(job_id, body), daemon=True).start()
    return {"job_id": job_id}
