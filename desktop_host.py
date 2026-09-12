"""Launch the dedicated native host; accepts only a known project and mode."""
import os
import subprocess
from fastapi import APIRouter,HTTPException
from pydantic import BaseModel
import core

router=APIRouter(prefix='/api/desktop')
DESKTOP=core.APP_DIR/'desktop'
EXECUTABLE=DESKTOP/'runtime'/'electron.exe'


class OpenWindow(BaseModel):
    project_id:str
    compact:bool=True


@router.get('/status')
def status():
    return {'available':EXECUTABLE.is_file(),'compact_size':[420,620]}


@router.post('/open')
def launch(body:OpenWindow):
    core.get_project(body.project_id)
    if not EXECUTABLE.is_file():raise HTTPException(503,'桌面窗口组件未安装')
    env=dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE',None)
    args=[str(EXECUTABLE),str(DESKTOP),'--project='+body.project_id]
    if body.compact:args.append('--mini')
    subprocess.Popen(args,cwd=DESKTOP,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),
                     stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return {'ok':True}
