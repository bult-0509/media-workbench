"""Local read/write dashboard for the QQ subtitle receiver queue."""
from __future__ import annotations

import json
import re
import shutil
import sqlite3
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import core

router = APIRouter(prefix="/api/inbox", dependencies=[Depends(lambda: core.require_module("inbox"))])

WORKFLOW_STATES = ("筹备", "配音", "剪辑", "校对", "已完成")
SECTIONS = ("开头", "正文", "结尾")


def active_issue(db) -> dict:
    row = db.execute("SELECT * FROM issue_projects WHERE active=1 ORDER BY created DESC LIMIT 1").fetchone()
    return dict(row) if row else {"id": "", "name": "未设期数"}


def queue_path() -> Path:
    configured = Path(core.CONFIG.get("subtitle_config", ""))
    if not configured.is_file():
        raise HTTPException(503, "QQ 接收服务配置未找到")
    try:
        settings = json.loads(configured.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(503, "QQ 接收服务配置无法读取") from exc
    path = configured.parent / "data" / "queue.sqlite3"
    if not path.is_file():
        raise HTTPException(503, "QQ 接收服务尚未建立接收队列")
    return path


def receiver_db() -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{queue_path().as_posix()}?mode=ro", uri=True, timeout=3)
    conn.row_factory = sqlite3.Row
    return conn


def receiver_write_db() -> sqlite3.Connection:
    conn = sqlite3.connect(queue_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def classify(stem: str) -> str:
    value = core.normalize(stem)
    if any(word in value for word in ("开头", "开场", "片头", "intro", "opening", "op")):
        return "开头"
    if any(word in value for word in ("结尾", "片尾", "尾声", "ending", "outro", "ed")):
        return "结尾"
    return "正文"


def safe_label(value: str) -> str:
    value = re.sub(r"[\\/:*?\"<>|\x00-\x1f]", "", value).strip()
    return value[:100]


def files_for(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    rows = conn.execute("SELECT kind,metadata,state,path,error FROM files WHERE job_id=? ORDER BY kind", (job_id,)).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            metadata = json.loads(item.pop("metadata") or "{}")
        except json.JSONDecodeError:
            metadata = {}
        item.update(name=metadata.get("name", ""), size=metadata.get("size", 0), file_id=metadata.get("file_id", ""),
                    inline=bool(metadata.get("inline_text")), source_message_id=metadata.get("source_message_id"))
        result.append(item)
    return result


def srt_status(job_id: str, state: str, files: list[dict]) -> dict:
    candidates = [queue_path().parent / "jobs" / job_id / "result.srt"]
    candidates.extend(Path(f["path"]).parent / "result.srt" for f in files if f.get("path"))
    output = next((path for path in candidates if path.is_file()), None)
    labels = {"waiting": "等待配对", "queued": "等待生成", "running": "正在生成 SRT", "sending": "正在回传 SRT",
              "sent": "已回传 SRT", "send_uncertain": "SRT 已生成，等待确认", "failed": "生成失败"}
    return {"stage": labels.get(state, state), "ready": bool(output), "path": str(output) if output else ""}


def receiver_status() -> dict:
    path = queue_path()
    now = time.time()
    return {"available": True, "queue_path": str(path), "updated": path.stat().st_mtime,
            "stale": now - path.stat().st_mtime > 300}


@router.get("/status")
def status():
    try:
        return receiver_status()
    except HTTPException as exc:
        return {"available": False, "detail": exc.detail}


@router.get("/items")
def items(limit: int = 80):
    limit = min(max(limit, 1), 200)
    with receiver_db() as queue, core.database() as local:
        rows = queue.execute("SELECT id,user_id,stem,state,created,updated,error FROM jobs ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
        assignments = {r["job_id"]: dict(r) for r in local.execute("SELECT * FROM inbox_assignments")}
        requests = {r["job_id"]: dict(r) for r in queue.execute("SELECT job_id,state,error FROM send_requests")}
        issue = active_issue(local)
        result = []
        for row in rows:
            item = dict(row)
            assignment = assignments.get(item["id"], {})
            item["section"] = assignment.get("section") or classify(item["stem"])
            item["project_id"] = assignment.get("project_id") or ""
            item["issue_id"] = assignment.get("issue_id") or (issue["id"] if item["created"] >= issue["created"] else "")
            item["display_name"] = assignment.get("display_name") or item["stem"]
            item["instruction"] = assignment.get("instruction") or ""
            item["files"] = files_for(queue, item["id"])
            item["srt"] = srt_status(item["id"], item["state"], item["files"])
            item["send_request"] = requests.get(item["id"], {})
            item["suggested_name"] = f"{item['section']} · {safe_label(item['display_name']) or '未命名'}"
            result.append(item)
    return {"items": result, "receiver": receiver_status(), "sections": SECTIONS, "active_issue": issue}


@router.get("/issues")
def issues():
    with core.database() as db:
        rows = [dict(row) for row in db.execute("SELECT * FROM issue_projects ORDER BY active DESC, number DESC, created DESC")]
        current = active_issue(db)
    return {"items": rows, "active": current}


class IssueCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=80)


@router.post("/issues")
def create_issue(body: IssueCreate):
    name = safe_label(body.name)
    match = re.search(r"(\d+)", name)
    number = int(match.group(1)) if match else None
    issue_id = f"issue-{int(time.time() * 1000)}"
    with core.database() as db:
        db.execute("UPDATE issue_projects SET active=0")
        db.execute("INSERT INTO issue_projects(id,name,number,active,created) VALUES(?,?,?,?,?)", (issue_id, name, number, 1, time.time()))
    return {"id": issue_id, "name": name}


@router.patch("/issues/{issue_id}/activate")
def activate_issue(issue_id: str):
    with core.database() as db:
        if not db.execute("SELECT 1 FROM issue_projects WHERE id=?", (issue_id,)).fetchone():
            raise HTTPException(404, "期数不存在")
        db.execute("UPDATE issue_projects SET active=0")
        db.execute("UPDATE issue_projects SET active=1 WHERE id=?", (issue_id,))
    return {"ok": True}


@router.get("/projects")
def project_workflow():
    with core.database() as db:
        stored = {row["project_id"]: dict(row) for row in db.execute("SELECT * FROM project_workflow")}
    output = []
    for project in core.projects():
        flow = stored.get(project["id"], {})
        output.append({**project, "state": flow.get("state", "筹备"), "instruction": flow.get("instruction", "")})
    return {"items": output, "states": WORKFLOW_STATES,
            "default_instruction": "收到同名音频与文案后生成无间隔 SRT；仅在工作群反馈接收、配对、完成或失败状态。"}


class ProjectUpdate(BaseModel):
    state: str
    instruction: str = Field("", max_length=1000)


@router.patch("/projects/{project_id}")
def update_project(project_id: str, body: ProjectUpdate):
    core.get_project(project_id)
    if body.state not in WORKFLOW_STATES:
        raise HTTPException(400, "项目状态无效")
    with core.database() as db:
        db.execute("INSERT INTO project_workflow(project_id,state,instruction,updated) VALUES(?,?,?,?) "
                   "ON CONFLICT(project_id) DO UPDATE SET state=excluded.state,instruction=excluded.instruction,updated=excluded.updated",
                   (project_id, body.state, body.instruction.strip(), time.time()))
    return {"ok": True}


class AssignmentUpdate(BaseModel):
    issue_id: str | None = None
    project_id: str | None = None
    section: str
    display_name: str = Field("", max_length=100)
    instruction: str = Field("", max_length=1000)


@router.patch("/items/{job_id}")
def update_assignment(job_id: str, body: AssignmentUpdate):
    if body.section not in SECTIONS:
        raise HTTPException(400, "文件段落只能是开头、正文或结尾")
    if body.project_id:
        core.get_project(body.project_id)
    label = safe_label(body.display_name)
    with receiver_write_db() as queue:
        job = queue.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "接收任务不存在")
        if label and label != job["stem"]:
            queue.execute("UPDATE jobs SET stem=?,updated=? WHERE id=?", (label, time.time(), job_id))
            script = queue.execute("SELECT file_id,metadata FROM files WHERE job_id=? AND kind='script'", (job_id,)).fetchone()
            if script:
                metadata = json.loads(script["metadata"] or "{}")
                metadata.update(stem=label, name=label + ".txt", auto_named=False)
                queue.execute("UPDATE files SET metadata=? WHERE file_id=?", (json.dumps(metadata, ensure_ascii=False), script["file_id"]))
            queue.commit()
    with core.database() as db:
        issue_id = body.issue_id or active_issue(db)["id"]
        if not db.execute("SELECT 1 FROM issue_projects WHERE id=?", (issue_id,)).fetchone():
            raise HTTPException(400, "期数不存在")
        db.execute("INSERT INTO inbox_assignments(job_id,project_id,section,display_name,instruction,updated,issue_id) VALUES(?,?,?,?,?,?,?) "
                   "ON CONFLICT(job_id) DO UPDATE SET project_id=excluded.project_id,section=excluded.section,display_name=excluded.display_name,instruction=excluded.instruction,updated=excluded.updated,issue_id=excluded.issue_id",
                   (job_id, body.project_id or "", body.section, label, body.instruction.strip(), time.time(), issue_id))
    return {"ok": True, "suggested_name": f"{body.section} · {label or '未命名'}"}


def editable_job(db: sqlite3.Connection, job_id: str):
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        raise HTTPException(404, "接收任务不存在")
    if job["state"] in {"running", "sending"}:
        raise HTTPException(409, "SRT 正在生成或回传，完成后再编辑或删除")
    return job


@router.get("/items/{job_id}/script")
def get_script(job_id: str):
    with receiver_db() as db:
        row = db.execute("SELECT path FROM files WHERE job_id=? AND kind='script'", (job_id,)).fetchone()
    if not row or not row["path"] or not Path(row["path"]).is_file():
        raise HTTPException(404, "文案文件尚未下载")
    try:
        content = Path(row["path"]).read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        content = Path(row["path"]).read_text(encoding="gb18030")
    return {"content": content}


class ScriptUpdate(BaseModel):
    content: str = Field(..., min_length=1, max_length=50000)


@router.put("/items/{job_id}/script")
def update_script(job_id: str, body: ScriptUpdate):
    content = body.content.replace("\r\n", "\n").strip()
    if not content or "\x00" in content:
        raise HTTPException(400, "文案不能为空或包含无效字符")
    with receiver_write_db() as db:
        editable_job(db, job_id)
        row = db.execute("SELECT file_id,path,metadata FROM files WHERE job_id=? AND kind='script'", (job_id,)).fetchone()
        if not row or not row["path"]:
            raise HTTPException(404, "文案文件尚未下载")
        path = Path(row["path"])
        jobs_root = queue_path().parent / "jobs"
        try:
            path.resolve().relative_to(jobs_root.resolve())
        except ValueError as exc:
            raise HTTPException(403, "文案位置无效") from exc
        path.write_text(content, encoding="utf-8", newline="")
        metadata = json.loads(row["metadata"] or "{}")
        if metadata.get("inline_text") is not None:
            metadata["inline_text"] = content
        db.execute("UPDATE files SET metadata=? WHERE file_id=?", (json.dumps(metadata, ensure_ascii=False), row["file_id"]))
        db.execute("UPDATE jobs SET updated=? WHERE id=?", (time.time(), job_id))
        db.commit()
    return {"ok": True, "length": len(content)}


class PairRequest(BaseModel):
    job_ids: list[str] = Field(min_length=2, max_length=2)


@router.post("/pair")
def pair_items(body: PairRequest):
    first, second = body.job_ids
    if first == second:
        raise HTTPException(400, "请选择两项不同的文件")
    with receiver_write_db() as db:
        jobs = {row["id"]: row for row in db.execute("SELECT * FROM jobs WHERE id IN (?,?)", (first, second))}
        if len(jobs) != 2:
            raise HTTPException(404, "选择的接收任务不存在")
        if any(job["state"] in {"running", "sending", "sent"} for job in jobs.values()):
            raise HTTPException(409, "已生成或发送的任务不能重新配对")
        types = {job_id: {r["kind"] for r in db.execute("SELECT kind FROM files WHERE job_id=?", (job_id,))} for job_id in jobs}
        script_id = next((job_id for job_id, kinds in types.items() if "script" in kinds and "audio" not in kinds), None)
        audio_id = next((job_id for job_id, kinds in types.items() if "audio" in kinds and "script" not in kinds), None)
        if not script_id or not audio_id:
            raise HTTPException(400, "请选择一份仅含文案的任务和一份仅含配音的任务")
        db.execute("UPDATE files SET job_id=? WHERE job_id=? AND kind='audio'", (script_id, audio_id))
        db.execute("DELETE FROM audio_choices WHERE job_id=?", (audio_id,))
        db.execute("DELETE FROM jobs WHERE id=?", (audio_id,))
        ready = db.execute("SELECT COUNT(DISTINCT kind) FROM files WHERE job_id=? AND state='downloaded'", (script_id,)).fetchone()[0] == 2
        db.execute("UPDATE jobs SET state=?,error='',updated=? WHERE id=?", ("queued" if ready else "waiting", time.time(), script_id))
        db.commit()
    with core.database() as db:
        db.execute("DELETE FROM inbox_assignments WHERE job_id=?", (audio_id,))
    return {"ok": True, "job_id": script_id, "queued": ready}


@router.post("/items/{job_id}/send")
def request_send(job_id: str):
    with receiver_write_db() as db:
        job = db.execute("SELECT id,state FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise HTTPException(404, "接收任务不存在")
        if job["state"] in {"running", "sending"}:
            raise HTTPException(409, "SRT 正在生成或发送")
        files = [dict(row) for row in db.execute("SELECT path FROM files WHERE job_id=?", (job_id,))]
        if not srt_status(job_id, job["state"], files)["ready"]:
            raise HTTPException(400, "SRT 尚未生成")
        now = time.time()
        db.execute("INSERT INTO send_requests(job_id,state,created,updated,error) VALUES(?,'pending',?,?, '') "
                   "ON CONFLICT(job_id) DO UPDATE SET state='pending',updated=excluded.updated,error=''", (job_id, now, now))
        db.commit()
    return {"ok": True, "state": "pending"}


@router.delete("/items/{job_id}")
def delete_item(job_id: str):
    with receiver_write_db() as db:
        editable_job(db, job_id)
        files = [dict(row) for row in db.execute("SELECT path FROM files WHERE job_id=?", (job_id,))]
        db.execute("DELETE FROM files WHERE job_id=?", (job_id,))
        db.execute("DELETE FROM jobs WHERE id=?", (job_id,))
        db.commit()
    with core.database() as db:
        db.execute("DELETE FROM inbox_assignments WHERE job_id=?", (job_id,))
    jobs_root = (queue_path().parent / "jobs").resolve()
    for path in {Path(f["path"]).parent for f in files if f.get("path")}:
        try:
            path.resolve().relative_to(jobs_root)
            shutil.rmtree(path, ignore_errors=True)
        except ValueError:
            continue
    return {"ok": True}
