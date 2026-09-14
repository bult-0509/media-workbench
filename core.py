"""Local-only shared capabilities: files, project routes, database and copy jobs."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import sqlite3
import subprocess
import threading
import time
import unicodedata
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("MEDIA_DESK_DATA", APP_DIR / "data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG = json.loads(Path(os.environ.get("MEDIA_DESK_CONFIG", APP_DIR / "config.json")).read_text(encoding="utf-8"))
TOKEN = secrets.token_urlsafe(32)
COPY_LOCK = threading.Lock()
CONFIG_LOCK = threading.RLock()
VIDEO_ROOT = Path(CONFIG["video_root"]).resolve()
PROJECTS_ROOT = Path(CONFIG["projects_root"]).resolve()
DB_PATH = DATA_DIR / "catalog.sqlite3"

EXTENSIONS = {
    "video": {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"},
    "audio": {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".aif", ".aiff"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"},
}


def kind_of(path: Path) -> str | None:
    return next((kind for kind, exts in EXTENSIONS.items() if path.suffix.lower() in exts), None)


def ident(value: str | Path) -> str:
    return hashlib.sha256(str(value).casefold().encode("utf-8")).hexdigest()[:24]


def normalize(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold().strip()


def confined(path: Path, root: Path, *, exists: bool = True) -> Path:
    """Resolve junctions/symlinks before checking; callers never accept arbitrary paths."""
    candidate, base = path.resolve(), root.resolve()
    try:
        candidate.relative_to(base)
    except ValueError:
        raise HTTPException(403, "文件位置超出已连接的目录")
    if exists and not candidate.exists():
        raise HTTPException(404, "文件或目录已不存在，请刷新索引")
    return candidate


def source_configs() -> list[dict]:
    with CONFIG_LOCK:
        sources = [{**dict(s), "managed": True} for s in CONFIG["sources"]]
    with database() as db:
        sources += [{'id': 'series-' + r['id'], 'name': r['name'] + ' · 共享素材', 'path': r['shared_path'], "managed": False}
                    for r in db.execute('SELECT * FROM project_series')]
    return sources


def add_source(path: str, name: str = "") -> dict:
    root = confined(Path(path), VIDEO_ROOT)
    if not root.is_dir():
        raise HTTPException(400, "请选择一个存在的文件夹")
    with CONFIG_LOCK:
        configured = [dict(s) for s in CONFIG["sources"]]
        for source in configured:
            existing = Path(source["path"]).resolve()
            try:
                root.relative_to(existing)
                raise HTTPException(409, "该文件夹已经包含在现有来源中")
            except ValueError:
                pass
            try:
                existing.relative_to(root)
                raise HTTPException(409, "该文件夹包含现有来源，请选择更具体的文件夹")
            except ValueError:
                pass
        source = {"id": "local-" + ident(root), "name": (name.strip() or root.name)[:80], "path": str(root)}
        if any(item["id"] == source["id"] for item in configured):
            raise HTTPException(409, "这个来源已经添加")
        CONFIG["sources"].append(source)
        save_config()
    return {**source, "managed": True}


def remove_source(source_id: str) -> None:
    with CONFIG_LOCK:
        before = [dict(s) for s in CONFIG["sources"]]
        remaining = [s for s in before if s["id"] != source_id]
        if len(remaining) == len(before):
            raise HTTPException(404, "只能移除手动管理的素材来源")
        CONFIG["sources"] = remaining
        save_config()
    with database() as db:
        db.execute("DELETE FROM assets WHERE source_id=?", (source_id,))


def indexed_source_configs() -> list[dict]:
    """All configured sources plus project media folders shown in the material desk."""
    sources = source_configs()
    for project in projects():
        if project.get("shared"):
            continue
        sources.append({"id": "project-" + project["id"], "name": project["name"] + " · 项目素材", "path": project["path"], "hidden": True})
    return sources


def save_config() -> None:
    with CONFIG_LOCK:
        destination = Path(os.environ.get("MEDIA_DESK_CONFIG", APP_DIR / "config.json"))
        temp = destination.with_suffix(".pending")
        temp.write_text(json.dumps(CONFIG, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, destination)


@contextmanager
def database():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with database() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript("""
        CREATE TABLE IF NOT EXISTS assets (
          id TEXT PRIMARY KEY, path TEXT UNIQUE, source_id TEXT, title TEXT,
          kind TEXT, extension TEXT, size INTEGER, modified REAL, relative TEXT,
          collection TEXT, search_text TEXT, tags TEXT DEFAULT '', favorite INTEGER DEFAULT 0,
          duration REAL, width INTEGER, height INTEGER, scanned INTEGER DEFAULT 0,
          use_count INTEGER NOT NULL DEFAULT 0, last_used REAL
        );
        CREATE INDEX IF NOT EXISTS asset_filter ON assets(source_id,kind,scanned);
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY, module TEXT, status TEXT, progress INTEGER DEFAULT 0,
          title TEXT, created REAL, updated REAL, payload TEXT, result TEXT, error TEXT
        );
        CREATE TABLE IF NOT EXISTS routes (
          project_id TEXT, category TEXT, relative TEXT, PRIMARY KEY(project_id,category)
        );
        CREATE TABLE IF NOT EXISTS preferences (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS project_series (
          id TEXT PRIMARY KEY, name TEXT NOT NULL COLLATE NOCASE UNIQUE, shared_path TEXT NOT NULL, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_series_members (
          project_id TEXT PRIMARY KEY, series_id TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS inbox_assignments (
          job_id TEXT PRIMARY KEY, project_id TEXT, section TEXT NOT NULL DEFAULT '正文',
          display_name TEXT DEFAULT '', instruction TEXT DEFAULT '', updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS project_workflow (
          project_id TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT '筹备', instruction TEXT DEFAULT '', updated REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS issue_projects (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, number INTEGER, active INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL
        );
        CREATE TABLE IF NOT EXISTS video_download_stack (
          id TEXT PRIMARY KEY, bvid TEXT UNIQUE NOT NULL, title TEXT NOT NULL, owner TEXT DEFAULT '',
          cover TEXT DEFAULT '', duration INTEGER DEFAULT 0, description TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'ready', error TEXT DEFAULT '', created REAL NOT NULL, updated REAL NOT NULL
        );
        """)
        columns = {row["name"] for row in db.execute("PRAGMA table_info(inbox_assignments)")}
        if "issue_id" not in columns:
            db.execute("ALTER TABLE inbox_assignments ADD COLUMN issue_id TEXT DEFAULT ''")
        asset_columns = {row["name"] for row in db.execute("PRAGMA table_info(assets)")}
        if "use_count" not in asset_columns:
            db.execute("ALTER TABLE assets ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0")
        if "last_used" not in asset_columns:
            db.execute("ALTER TABLE assets ADD COLUMN last_used REAL")
        db.execute("""CREATE TABLE IF NOT EXISTS asset_usage (
          id INTEGER PRIMARY KEY AUTOINCREMENT, asset_id TEXT NOT NULL, used_at REAL NOT NULL,
          scope TEXT NOT NULL, project_id TEXT DEFAULT ''
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS asset_usage_asset_time ON asset_usage(asset_id, used_at DESC)")
        if not db.execute("SELECT 1 FROM issue_projects LIMIT 1").fetchone():
            db.execute("INSERT INTO issue_projects(id,name,number,active,created) VALUES('issue-53','烂活音游 53',53,1,?)", (time.time(),))
        db.execute("UPDATE jobs SET status='failed',error='上次运行中断，可以重新提交；已完成的文件不会覆盖',updated=? WHERE status IN ('queued','running')", (time.time(),))


def record_asset_uses(asset_ids: list[str], *, scope: str, project_id: str = "") -> None:
    """Persist one use per unique asset when a native cross-app drag is started."""
    ids = list(dict.fromkeys(asset_ids))
    if not ids:
        return
    now = time.time()
    with database() as db:
        for asset_id in ids:
            db.execute("UPDATE assets SET use_count=use_count+1,last_used=? WHERE id=?", (now, asset_id))
            db.execute("INSERT INTO asset_usage(asset_id,used_at,scope,project_id) VALUES(?,?,?,?)",
                       (asset_id, now, scope, project_id))


def require_module(module: str):
    if not CONFIG.get("modules", {}).get(module, False):
        raise HTTPException(403, "此模块已停用，可在设置中开启")


def get_asset(asset_id: str) -> dict:
    with database() as db:
        row = db.execute("SELECT * FROM assets WHERE id=? AND scanned=1", (asset_id,)).fetchone()
    if not row:
        raise HTTPException(404, "素材不存在，请刷新索引")
    asset = dict(row)
    source = next((s for s in indexed_source_configs() if s["id"] == asset["source_id"]), None)
    if not source:
        raise HTTPException(404, "素材来源已断开")
    confined(Path(asset["path"]), confined(Path(source["path"]), VIDEO_ROOT))
    return asset


STANDARD_PROJECT_FOLDERS = ("视频", "音频", "图片", "封面")


def is_standard_project(path: Path) -> bool:
    return path.is_dir() and all((path / name).is_dir() for name in STANDARD_PROJECT_FOLDERS)


def projects() -> list[dict]:
    excluded = {Path(s["path"]).resolve() for s in source_configs()}
    output = []
    if not PROJECTS_ROOT.exists():
        return output
    for path in PROJECTS_ROOT.iterdir():
        if not path.is_dir() or path.resolve() in excluded or path.name.startswith("."):
            continue
        if not (is_standard_project(path) or "【" in path.name or path.name == "2025视频合集"):
            continue
        try:
            resolved = confined(path, PROJECTS_ROOT)
            output.append({"id": ident(path), "name": path.name, "path": str(resolved),
                           "modified": path.stat().st_mtime,
                           "archived": path.name.startswith(("√", "×"))})
        except (OSError, HTTPException):
            continue
    with database() as db:
        membership = {r['project_id']: r['series_id'] for r in db.execute('SELECT * FROM project_series_members')}
        series = [dict(r) for r in db.execute('SELECT * FROM project_series')]
    names = {s['id']: s['name'] for s in series}
    for project in output:
        sid = membership.get(project['id'], '')
        project.update(series_id=sid if sid in names else '', series_name=names.get(sid, ''), shared=False)
    for group in series:
        try:
            path = confined(Path(group['shared_path']), PROJECTS_ROOT)
            output.append({'id': ident(path), 'name': '共享素材', 'path': str(path),
                           'modified': group['created'], 'archived': False, 'shared': True,
                           'series_id': group['id'], 'series_name': group['name']})
        except (OSError, HTTPException):
            continue
    return sorted(output, key=lambda p: (p.get('shared', False), p["archived"], -p["modified"], p["name"]))


def create_standard_project(name: str) -> dict:
    name = safe_filename(name)
    if not name or name.startswith("."):
        raise HTTPException(400, "请输入有效的项目名称")
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)
    target = confined(PROJECTS_ROOT / name, PROJECTS_ROOT, exists=False)
    if target.exists():
        raise HTTPException(409, "同名项目已存在")
    try:
        target.mkdir()
        for folder in STANDARD_PROJECT_FOLDERS:
            (target / folder).mkdir()
    except Exception:
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        raise
    LAYOUT_CACHE.update(at=0, value=None)
    return {"id": ident(target), "name": target.name, "path": str(target),
            "modified": target.stat().st_mtime, "archived": False}


def get_project(project_id: str) -> Path:
    project = next((p for p in projects() if p["id"] == project_id), None)
    if not project:
        raise HTTPException(404, "请选择有效的视频项目")
    return confined(Path(project["path"]), PROJECTS_ROOT)


def folders(project: Path) -> list[dict]:
    results = [{"relative": ".", "label": "项目根目录"}]
    for current, dirs, _ in os.walk(project, followlinks=False):
        current_path = Path(current)
        try:
            depth = len(current_path.relative_to(project).parts)
        except ValueError:
            continue
        dirs[:] = sorted(d for d in dirs if not d.startswith(".") and d not in {"node_modules", "__pycache__"})
        if depth >= 3:
            dirs[:] = []
        for name in dirs:
            candidate = current_path / name
            try:
                confined(candidate, project)
            except HTTPException:
                continue
            rel = str(candidate.relative_to(project))
            results.append({"relative": rel, "label": rel})
    return results


def category_for(asset: dict) -> str:
    value = normalize(asset.get("relative", "") + " " + asset.get("collection", ""))
    if asset["kind"] == "audio":
        return "music" if asset.get("source_id") == "bgm" or "bgm" in value else "audio"
    if asset["kind"] == "image" and any(t in value for t in ["表情", "meme"]):
        return "meme"
    return asset["kind"]


ROUTE_NAMES = {
    "video": ["视频素材", "视频", "素材"],
    "audio": ["音效", "音频", "声音", "audio"],
    "music": ["bgm", "背景音乐", "配乐", "音乐", "音频"],
    "image": ["图片", "图层", "图片素材", "image", "pic", "表情包"],
    "meme": ["表情包", "表情", "图片", "图层"],
    "subtitle": ["字幕", "srt", "文案"],
}

LAYOUT_CACHE = {"at": 0, "value": None}


def learn_layouts(force=False) -> dict:
    """Use actual file locations in the ten most recently modified video projects."""
    if not force and time.time() - LAYOUT_CACHE["at"] < 120 and LAYOUT_CACHE["value"]:
        return LAYOUT_CACHE["value"]
    recent = sorted((p for p in projects() if not p.get('shared')), key=lambda p: -p["modified"])[:10]
    profiles = {}
    global_counts = {}
    for project in recent:
        root = Path(project["path"])
        counts = {}
        total = 0
        for current, dirs, files in os.walk(root, followlinks=False):
            current_path = Path(current)
            relative = str(current_path.relative_to(root))
            depth = len(current_path.relative_to(root).parts)
            dirs[:] = [d for d in dirs if not d.startswith((".", "_")) and d not in {"node_modules", "tmp", "dist", "public", "src", "out"}]
            if depth >= 2:
                dirs[:] = []
            for filename in files:
                if filename.startswith("."):
                    continue
                path = current_path / filename
                kind = "subtitle" if path.suffix.lower() == ".srt" else kind_of(path)
                if not kind:
                    continue
                try:
                    confined(path, root)
                except HTTPException:
                    continue
                if kind == "audio" and any(n in normalize(relative) for n in ["bgm", "音乐", "配乐"]):
                    kind = "music"
                if kind == "image" and "表情" in relative:
                    kind = "meme"
                counts.setdefault(kind, {})[relative] = counts.get(kind, {}).get(relative, 0) + 1
                total += 1
        profiles[project["id"]] = {"name": project["name"], "counts": counts, "files": total}
        # Each recent project casts one vote per category, not each file.
        for category, locations in counts.items():
            best = max(locations, key=locations.get)
            global_counts.setdefault(category, {})[best] = global_counts.get(category, {}).get(best, 0) + 1
    value = {"recent": recent, "profiles": profiles, "habits": {cat: sorted(locs.items(), key=lambda p: -p[1]) for cat, locs in global_counts.items()}}
    LAYOUT_CACHE.update(at=time.time(), value=value)
    return value


def resolve_destination(project_id: str, category: str, relative: str = "auto") -> tuple[Path, str]:
    project = get_project(project_id)
    available = folders(project)
    if relative != "auto":
        if relative not in {f["relative"] for f in available}:
            raise HTTPException(400, "只能选择项目中已有的目录")
        return confined(project / relative, project), "手动选择"
    if is_standard_project(project):
        standard_destinations = {
            "video": "视频", "audio": "音频", "music": "音频",
            "image": "图片", "meme": "图片", "cover": "封面",
        }
        folder = standard_destinations.get(category)
        if folder:
            return confined(project / folder, project), "项目标准目录"
    with database() as db:
        saved = db.execute("SELECT relative FROM routes WHERE project_id=? AND category=?", (project_id, category)).fetchone()
    if saved and saved["relative"] in {f["relative"] for f in available}:
        return confined(project / saved["relative"], project), "已记住的位置"
    learned = learn_layouts()
    locations = learned["profiles"].get(project_id, {}).get("counts", {}).get(category, {})
    available_names = {f["relative"] for f in available}
    # Prefer semantically appropriate folders in this project before a generic
    # image/video histogram (e.g. never put meme pictures inside a portrait album).
    names = ROUTE_NAMES.get(category, [])
    matches = []
    for folder in available[1:]:
        name = normalize(Path(folder["relative"]).name).strip("【】[]_- ")
        for priority, word in enumerate(names):
            if name == word or (len(word) > 2 and word in name):
                matches.append((priority, len(Path(folder["relative"]).parts), folder["relative"]))
                break
    if matches:
        chosen = sorted(matches)[0][2]
        count = locations.get(chosen, 0)
        return confined(project / chosen, project), f"沿用此项目的目录习惯" + (f" · 已有 {count} 个同类文件" if count else "")
    if locations.get(".", 0):
        return project, f"沿用此项目根目录 · 已有 {locations['.']} 个同类文件"
    for relative, votes in learned["habits"].get(category, []):
        if relative in available_names and (relative == "." or normalize(Path(relative).name).strip("【】[] ") in ROUTE_NAMES.get(category, [])):
            return confined(project / relative, project), f"参考最近项目 · {votes} 个项目采用此位置"
    return project, "按近期项目习惯保留在根目录，可手动调整"


def digest_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def media_info(path: Path) -> dict:
    executable = Path(CONFIG["ffmpeg"])
    probe = executable.with_name("ffprobe.exe")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if probe.is_file():
        result = subprocess.run([str(probe), "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)], capture_output=True, timeout=20, creationflags=flags)
        return json.loads(result.stdout)
    result = subprocess.run([str(executable), "-nostdin", "-hide_banner", "-i", str(path)], capture_output=True, timeout=20, creationflags=flags)
    text = result.stderr.decode("utf-8", errors="replace")
    streams = []
    for line in text.splitlines():
        for kind in ["Audio", "Video"]:
            match = re.search(kind + r":\s*([\w]+)", line)
            if match:
                item = {"codec_type": kind.lower(), "codec_name": match.group(1)}
                dims = re.search(r", (\d{2,5})x(\d{2,5})(?:[ ,])", line)
                if dims:
                    item.update(width=int(dims[1]), height=int(dims[2]))
                streams.append(item)
    length = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", text)
    duration = int(length[1]) * 3600 + int(length[2]) * 60 + float(length[3]) if length else 0
    container = re.search(r"Input #0, (.+?), from", text)
    return {"streams": streams, "format": {"duration": duration, "format_name": container[1] if container else ""}}


def safe_filename(name: str) -> str:
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    if len(clean) > 180:
        suffix = Path(clean).suffix[:16]
        clean = clean[:180-len(suffix)] + suffix
    if not clean or clean.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *[f"COM{i}" for i in range(10)], *[f"LPT{i}" for i in range(10)]}:
        clean = "素材_" + clean
    return clean


def copy_into(source: Path, destination: Path, name: str | None = None, progress=None) -> dict:
    """Copy, hash and publish atomically, never replacing an existing user file."""
    destination = confined(destination, PROJECTS_ROOT)
    source = source.resolve()
    filename = safe_filename(name or source.name)
    with COPY_LOCK:
        original = destination / filename
        if original.exists() and (original.resolve() == source or (
            original.stat().st_size == source.stat().st_size and digest_file(original) == digest_file(source)
        )):
            return {"path": str(original), "name": original.name, "status": "already_exists", "size": original.stat().st_size, "sha256": digest_file(original)}
        stem, suffix = Path(filename).stem, Path(filename).suffix
        candidate = original
        count = 1
        while candidate.exists():
            candidate = destination / f"{stem} ({count}){suffix}"
            count += 1
        temp = destination / f".素材台-{secrets.token_hex(8)}.part"
        source_stat = source.stat()
        copied, digest = 0, hashlib.sha256()
        try:
            with source.open("rb") as src, temp.open("xb") as dst:
                while chunk := src.read(1024 * 1024):
                    dst.write(chunk)
                    copied += len(chunk)
                    digest.update(chunk)
                    if progress:
                        progress(min(98, int(copied / max(source_stat.st_size, 1) * 98)))
                dst.flush()
                os.fsync(dst.fileno())
            after = source.stat()
            if after.st_size != source_stat.st_size or after.st_mtime_ns != source_stat.st_mtime_ns:
                raise RuntimeError("源文件在复制期间发生变化，请完成编辑后重试")
            if digest_file(temp) != digest.hexdigest():
                raise RuntimeError("文件校验失败，未保存结果")
            # On Windows rename refuses an existing destination. No replace/overwrite.
            while True:
                try:
                    os.rename(temp, candidate)
                    break
                except FileExistsError:
                    candidate = destination / f"{stem} ({count}){suffix}"
                    count += 1
            return {"path": str(candidate), "name": candidate.name, "status": "copied", "size": copied, "sha256": digest.hexdigest()}
        finally:
            if temp.exists():
                temp.unlink()


def create_job(module: str, title: str, payload: dict) -> str:
    job_id = secrets.token_hex(12)
    with database() as db:
        db.execute("INSERT INTO jobs(id,module,status,title,created,updated,payload) VALUES(?,?,?,?,?,?,?)",
                   (job_id, module, "queued", title, time.time(), time.time(), json.dumps(payload, ensure_ascii=False)))
    return job_id


def update_job(job_id: str, **fields):
    allowed = {"status", "progress", "result", "error"}
    values = {k: json.dumps(v, ensure_ascii=False) if k == "result" else v for k, v in fields.items() if k in allowed}
    values["updated"] = time.time()
    with database() as db:
        db.execute("UPDATE jobs SET " + ",".join(f"{k}=?" for k in values) + " WHERE id=?", [*values.values(), job_id])


def run_copy(job_id: str, asset_ids: list[str], project_id: str, relative: str):
    completed = []
    try:
        update_job(job_id, status="running")
        for index, asset_id in enumerate(asset_ids):
            asset = get_asset(asset_id)
            destination, _ = resolve_destination(project_id, category_for(asset), relative)
            result = copy_into(Path(asset["path"]), destination, progress=lambda p: update_job(job_id, progress=int((index + p / 100) / len(asset_ids) * 100)))
            completed.append(result)
            update_job(job_id, result=completed, progress=int((index + 1) / len(asset_ids) * 100))
        update_job(job_id, status="succeeded", progress=100, result=completed)
    except Exception as exc:
        update_job(job_id, status="failed", error=str(getattr(exc, "detail", exc)), result=completed)


init_db()
