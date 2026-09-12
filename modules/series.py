"""Series organize existing projects without moving their files."""
import re
import os
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
import core

router = APIRouter(prefix='/api/series')
LOCK = threading.RLock()


def groups():
    with core.database() as db:
        return [{**dict(r), 'shared_project_id': core.ident(Path(r['shared_path']))}
                for r in db.execute('SELECT * FROM project_series ORDER BY created,name')]


def get_group(series_id):
    group = next((s for s in groups() if s['id'] == series_id), None)
    if not group:
        raise HTTPException(404, '系列不存在，请刷新后重试')
    return group


def sync_shared_files(project_id):
    """Index only this small shared directory; never scan all creator media here."""
    group = next((s for s in groups() if s['shared_project_id'] == project_id), None)
    if not group:
        return
    root = core.confined(Path(group['shared_path']), core.PROJECTS_ROOT)
    rows = []
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        for name in files:
            path = Path(current) / name
            kind = core.kind_of(path)
            if not kind:
                continue
            try:
                path = core.confined(path, root)
                stat = path.stat()
            except (OSError, HTTPException):
                continue
            rel = path.relative_to(root)
            rows.append((core.ident(path), str(path), 'series-' + group['id'], path.stem, kind,
                         path.suffix.lower(), stat.st_size, stat.st_mtime, str(rel),
                         rel.parts[0] if len(rel.parts)>1 else group['name'], core.normalize(f"{path.stem} {rel} {group['name']}")))
    with core.database() as db:
        db.execute('UPDATE assets SET scanned=0 WHERE source_id=?', ('series-' + group['id'],))
        db.executemany('''INSERT INTO assets(id,path,source_id,title,kind,extension,size,modified,relative,collection,search_text,scanned)
          VALUES(?,?,?,?,?,?,?,?,?,?,?,1) ON CONFLICT(id) DO UPDATE SET source_id=excluded.source_id,
          size=excluded.size,modified=excluded.modified,scanned=1''', rows)
        for row in rows:
            db.execute('''INSERT OR IGNORE INTO stack_items SELECT ?,?,? WHERE NOT EXISTS
              (SELECT 1 FROM stack_hidden WHERE project_id=? AND asset_id=?)''',
                       (project_id,row[0],row[7],project_id,row[0]))


def validate_name(name):
    name = name.strip()
    if not name or len(name) > 80:
        raise HTTPException(400, '请输入 1–80 字的系列名称')
    return name


class SeriesCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


@router.get('')
def listing():
    return {'series': groups(), 'projects': core.projects(), 'sources': core.source_configs()}


@router.post('')
def create(body: SeriesCreate):
    name = validate_name(body.name)
    with LOCK:
        if any(s['name'].casefold() == name.casefold() for s in groups()):
            raise HTTPException(409, '已有同名系列')
        sid = uuid.uuid4().hex
        directory = core.confined(core.PROJECTS_ROOT / '系列共享素材' / (core.safe_filename(name) + '-' + sid[:6]), core.PROJECTS_ROOT, exists=False)
        directory.mkdir(parents=True, exist_ok=False)
        for folder in core.STANDARD_PROJECT_FOLDERS:
            (directory / folder).mkdir()
        with core.database() as db:
            db.execute('INSERT INTO project_series VALUES(?,?,?,?)', (sid, name, str(directory), time.time()))
        return get_group(sid)


@router.patch('/{series_id}')
def rename(series_id: str, body: SeriesCreate):
    name = validate_name(body.name)
    with LOCK:
        get_group(series_id)
        if any(s['id'] != series_id and s['name'].casefold() == name.casefold() for s in groups()):
            raise HTTPException(409, '已有同名系列')
        with core.database() as db:
            db.execute('UPDATE project_series SET name=? WHERE id=?', (name, series_id))
    return get_group(series_id)


class Membership(BaseModel):
    project_ids: list[str] = Field(min_length=1, max_length=500)
    series_id: str = ''


@router.post('/membership')
def assign(body: Membership):
    with LOCK:
        if body.series_id:
            get_group(body.series_id)
        valid = {p['id'] for p in core.projects() if not p.get('shared')}
        if not set(body.project_ids) <= valid:
            raise HTTPException(400, '只能整理现有的单期项目')
        with core.database() as db:
            for pid in set(body.project_ids):
                db.execute('DELETE FROM project_series_members WHERE project_id=?', (pid,))
                if body.series_id:
                    db.execute('INSERT INTO project_series_members VALUES(?,?)', (pid, body.series_id))
    return listing()


def infer_existing():
    """One-time conservative migration: repeated identical titles + numeric suffix."""
    with LOCK:
        with core.database() as db:
            if db.execute("SELECT 1 FROM preferences WHERE key='series-initialized'").fetchone():
                return
        matches = {}
        for project in core.projects():
            if project.get('shared') or project.get('series_id'):
                continue
            title = project['name'].lstrip('√×- ').strip('【】 ')
            match = re.fullmatch(r'(.+?)[\s_-]*(?:第\s*)?(\d+)(?:\s*期)?', title)
            if match:
                matches.setdefault(match[1].strip(), []).append(project['id'])
        for name, ids in matches.items():
            if len(ids) < 2:
                continue
            group = next((s for s in groups() if s['name'] == name), None) or create(SeriesCreate(name=name))
            assign(Membership(project_ids=ids, series_id=group['id']))
        with core.database() as db:
            db.execute("INSERT OR REPLACE INTO preferences VALUES('series-initialized','1')")
