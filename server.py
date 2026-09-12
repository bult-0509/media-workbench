from __future__ import annotations

import importlib
import json
import os
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

import core
from modules import series

FEATURES = {"library": "素材库", "stack": "素材栈", "videos": "视频下载", "music": "音乐", "subtitles": "字幕", "inbox": "文件接收"}


@asynccontextmanager
async def lifespan(app):
    series.infer_existing()
    if core.CONFIG["modules"].get("library") and (core.APP_DIR / "modules" / "library.py").is_file():
        from modules.library import scan_now
        threading.Thread(target=scan_now, daemon=True).start()
    yield


app = FastAPI(title="素材台 · 本地工作台", docs_url=None, redoc_url=None, lifespan=lifespan)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver"])
from desktop_host import router as desktop_router
app.include_router(desktop_router)
app.include_router(series.router)


@app.middleware("http")
async def local_only(request: Request, call_next):
    host = request.client.host if request.client else ""
    if host not in {"127.0.0.1", "::1", "testclient"}:
        return JSONResponse({"detail": "仅允许本机访问"}, status_code=403)
    origin = request.headers.get("origin")
    expected = {f"http://127.0.0.1:{core.CONFIG['port']}", f"http://localhost:{core.CONFIG['port']}", "http://testserver"}
    if origin and origin not in expected:
        return JSONResponse({"detail": "不允许跨站请求"}, status_code=403)
    if request.headers.get("sec-fetch-site") == "cross-site":
        return JSONResponse({"detail": "不允许跨站访问本地文件"}, status_code=403)
    if request.method in {"POST", "PATCH", "PUT", "DELETE"} and request.headers.get("x-workbench-token") != core.TOKEN:
        return JSONResponse({"detail": "页面会话已更新，请刷新后重试"}, status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


for module_id in FEATURES:
    if (core.APP_DIR / "modules" / f"{module_id}.py").is_file():
        app.include_router(importlib.import_module(f"modules.{module_id}").router)


@app.get("/api/health")
def health():
    return {"app": "local-media-workbench", "status": "ok", "pid": os.getpid()}


@app.get("/api/bootstrap")
def bootstrap():
    return {"token": core.TOKEN, "name": core.CONFIG["name"], "video_root": str(core.VIDEO_ROOT),
            "projects_root": str(core.PROJECTS_ROOT), "projects": core.projects(), "series": series.groups(), "sources": core.source_configs(),
            "modules": [{"id": m, "name": name, "enabled": core.CONFIG["modules"].get(m, False), "installed": (core.APP_DIR / "modules" / f"{m}.py").exists()} for m, name in FEATURES.items()]}



class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    series_id: str = ''


@app.post("/api/projects")
def create_project(body: ProjectCreate):
    if body.series_id:
        series.get_group(body.series_id)
    project = core.create_standard_project(body.name.strip())
    if body.series_id:
        series.assign(series.Membership(project_ids=[project['id']], series_id=body.series_id))
    return next(p for p in core.projects() if p['id'] == project['id'])


@app.get("/api/projects/{project_id}/folders")
def project_folders(project_id: str):
    return {"folders": core.folders(core.get_project(project_id))}


@app.get("/api/layouts")
def layouts():
    return core.learn_layouts()


class DestinationRequest(BaseModel):
    project_id: str
    asset_id: str | None = None
    category: str = "video"
    relative: str = "auto"


@app.post("/api/destination")
def destination(body: DestinationRequest):
    if body.asset_id:
        core.require_module("library")
    asset = core.get_asset(body.asset_id) if body.asset_id else None
    category = core.category_for(asset) if asset else body.category
    directory, reason = core.resolve_destination(body.project_id, category, body.relative)
    filename = Path(asset["path"]).name if asset else ""
    return {"directory": str(directory), "path": str(directory / filename), "reason": reason, "category": category}


class RouteRequest(BaseModel):
    project_id: str
    category: str
    relative: str


@app.post("/api/routes")
def remember_route(body: RouteRequest):
    core.resolve_destination(body.project_id, body.category, body.relative)
    with core.database() as db:
        db.execute("INSERT OR REPLACE INTO routes(project_id,category,relative) VALUES(?,?,?)", (body.project_id, body.category, body.relative))
    return {"ok": True}


class CopyRequest(BaseModel):
    asset_ids: list[str] = Field(min_length=1, max_length=30)
    project_id: str
    relative: str = "auto"


@app.post("/api/save")
def save_assets(body: CopyRequest):
    core.require_module("library")
    for asset_id in body.asset_ids:
        asset = core.get_asset(asset_id)
        core.resolve_destination(body.project_id, core.category_for(asset), body.relative)
    job_id = core.create_job("library", f"保存 {len(body.asset_ids)} 项素材", body.model_dump())
    threading.Thread(target=core.run_copy, args=(job_id, body.asset_ids, body.project_id, body.relative), daemon=True).start()
    return {"job_id": job_id}


@app.get("/api/jobs")
def jobs():
    with core.database() as db:
        rows = db.execute("SELECT * FROM jobs ORDER BY created DESC LIMIT 60").fetchall()
    output = []
    for row in rows:
        value = dict(row)
        value["payload"] = json.loads(value["payload"] or "{}")
        value["result"] = json.loads(value["result"] or "[]")
        output.append(value)
    return {"items": output}


class OpenRequest(BaseModel):
    project_id: str | None = None
    asset_id: str | None = None
    job_id: str | None = None


@app.post("/api/open-folder")
def open_folder(body: OpenRequest):
    if body.project_id:
        path = core.get_project(body.project_id)
    elif body.asset_id:
        core.require_module("library")
        path = Path(core.get_asset(body.asset_id)["path"]).parent
    elif body.job_id:
        with core.database() as db:
            job = db.execute("SELECT result FROM jobs WHERE id=?", (body.job_id,)).fetchone()
        results = json.loads(job["result"] or "[]") if job else []
        if not results:
            raise HTTPException(404, "任务还没有已保存文件")
        path = core.confined(Path(results[0]["path"]).parent, core.PROJECTS_ROOT)
    else:
        path = core.VIDEO_ROOT
    os.startfile(str(path))
    return {"ok": True}


class SourceCreate(BaseModel):
    path: str = Field(min_length=1, max_length=1000)
    name: str = Field("", max_length=80)


@app.post("/api/sources")
def create_source(body: SourceCreate):
    core.require_module("library")
    source = core.add_source(body.path, body.name)
    from modules.library import rescan_if_idle
    rescan_if_idle()
    return source


@app.delete("/api/sources/{source_id}")
def delete_source(source_id: str):
    core.require_module("library")
    core.remove_source(source_id)
    return {"ok": True}


class ModuleRequest(BaseModel):
    enabled: bool


@app.patch("/api/modules/{module_id}")
def toggle_module(module_id: str, body: ModuleRequest):
    if module_id not in FEATURES:
        raise HTTPException(404, "没有这个模块")
    with core.CONFIG_LOCK:
        core.CONFIG["modules"][module_id] = body.enabled
        core.save_config()
    return {"ok": True}


@app.get("/")
def home():
    return FileResponse(core.APP_DIR / "static" / "index.html")


app.mount("/static", StaticFiles(directory=core.APP_DIR / "static"), name="static")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(core.CONFIG["port"]), log_level="warning")
