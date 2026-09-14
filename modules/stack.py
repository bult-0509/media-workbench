"""A project-scoped collection of local file references, independent of copying."""
from pathlib import Path
import time

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
import core
from modules.series import sync_shared_files

router=APIRouter(prefix='/api/stack',dependencies=[Depends(lambda:core.require_module('stack'))])
with core.database() as db:
    db.execute('''CREATE TABLE IF NOT EXISTS stack_items (
        project_id TEXT, asset_id TEXT, added REAL,
        PRIMARY KEY(project_id,asset_id))''')
    db.execute('CREATE TABLE IF NOT EXISTS stack_hidden (project_id TEXT, asset_id TEXT, PRIMARY KEY(project_id,asset_id))')


def shared_scope(project_id):
    projects = core.projects()
    project = next((p for p in projects if p['id'] == project_id), None)
    if not project:
        raise HTTPException(404, '请选择有效的视频项目')
    if project.get('shared') or not project.get('series_id'):
        return None
    return next((p['id'] for p in projects if p.get('shared') and p['series_id'] == project['series_id']), None)


class Items(BaseModel):
    asset_ids:list[str]=Field(min_length=1,max_length=200)


@router.get('/{project_id}')
def listing(project_id:str, sort: str = 'modified', order: str = 'desc'):
    core.get_project(project_id)
    shared_id = shared_scope(project_id)
    sync_shared_files(shared_id or project_id)
    with core.database() as db:
        rows=db.execute('''SELECT s.project_id AS owner_project_id,s.asset_id,s.added,a.title,a.path,a.kind,a.extension,a.size,
            a.collection,a.modified,a.use_count,a.last_used FROM stack_items s LEFT JOIN assets a ON s.asset_id=a.id
            WHERE s.project_id=? OR (s.project_id=? AND NOT EXISTS
              (SELECT 1 FROM stack_hidden h WHERE h.project_id=? AND h.asset_id=s.asset_id))
            ORDER BY (s.project_id=?) DESC,s.added,s.asset_id''',(project_id,shared_id,project_id,project_id)).fetchall()
    result=[]
    seen=set()
    for row in rows:
        item=dict(row)
        if item['asset_id'] in seen:continue
        seen.add(item['asset_id'])
        item['is_shared']=item['owner_project_id'] != project_id
        try:core.get_asset(item['asset_id']);item['available']=True
        except (HTTPException,OSError):item['available']=False
        item['title']=item['title'] or '素材已移除'
        result.append(item)
    sorters = {'modified': lambda item: item.get('modified') or 0, 'size': lambda item: item.get('size') or 0,
               'uses': lambda item: (item.get('use_count') or 0, item.get('last_used') or 0),
               'type': lambda item: ((item.get('kind') or ''), (item.get('extension') or ''), item['title'].casefold()),
               'name': lambda item: item['title'].casefold()}
    if sort not in sorters or order not in {'asc', 'desc'}:
        raise HTTPException(400, '不支持的排序方式')
    result.sort(key=sorters[sort], reverse=order == 'desc')
    return {'items':result,'count':len(result),'shared_project_id':shared_id}


@router.post('/{project_id}/items')
def add(project_id:str,body:Items):
    core.get_project(project_id)
    ids=list(dict.fromkeys(body.asset_ids))
    for asset_id in ids:core.get_asset(asset_id)
    with core.database() as db:
        for offset,asset_id in enumerate(ids):
            db.execute('DELETE FROM stack_hidden WHERE project_id=? AND asset_id=?',(project_id,asset_id))
            db.execute('INSERT OR IGNORE INTO stack_items VALUES(?,?,?)',(project_id,asset_id,time.time()+offset/10000))
    return listing(project_id)


@router.delete('/{project_id}/items/{asset_id}')
def remove(project_id:str,asset_id:str):
    core.get_project(project_id)
    with core.database() as db:
        db.execute('DELETE FROM stack_items WHERE project_id=? AND asset_id=?',(project_id,asset_id))
        db.execute('INSERT OR IGNORE INTO stack_hidden VALUES(?,?)',(project_id,asset_id))
    return {'ok':True}


@router.delete('/{project_id}/items')
def clear(project_id:str):
    core.get_project(project_id)
    items=listing(project_id)['items']
    with core.database() as db:
        db.execute('DELETE FROM stack_items WHERE project_id=?',(project_id,))
        for item in items:
            db.execute('INSERT OR IGNORE INTO stack_hidden VALUES(?,?)',(project_id,item['asset_id']))
    return {'ok':True}


@router.post('/{project_id}/restore-shared')
def restore_shared(project_id:str):
    core.get_project(project_id)
    with core.database() as db:
        db.execute('DELETE FROM stack_hidden WHERE project_id=?',(project_id,))
    return listing(project_id)


@router.post('/{project_id}/drag')
def drag(project_id:str,body:Items):
    core.get_project(project_id)
    ids=list(dict.fromkeys(body.asset_ids))
    if len(ids)>30:raise HTTPException(400,'每次最多拖出 30 份素材')
    files=[]
    available = {item['asset_id'] for item in listing(project_id)['items']}
    with core.database() as db:
        for asset_id in ids:
            if asset_id not in available:
                raise HTTPException(403,'只能拖出当前项目素材栈中的文件')
            asset=core.get_asset(asset_id)
            path=Path(asset['path'])
            if not path.is_file():raise HTTPException(404,'素材已移动，请重新扫描')
            files.append(str(path.resolve()))
    core.record_asset_uses(ids, scope='stack', project_id=project_id)
    return {'files':files}
