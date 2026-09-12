from __future__ import annotations

import json
import re
import subprocess
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import core

router = APIRouter(prefix="/api/subtitles", dependencies=[Depends(lambda: core.require_module("subtitles"))])
WORKER = threading.Semaphore(1)


def process(job_id: str, audio: Path, script: Path, project_id: str, relative: str):
    try:
        with WORKER:
            core.update_job(job_id, status="running", progress=5)
            processor = Path(core.CONFIG["subtitle_processor"])
            config = Path(core.CONFIG["subtitle_config"])
            if not processor.is_file() or not config.is_file():
                raise ValueError("现有字幕处理器配置未找到，请在设置中检查安装位置")
            output = audio.parent / f"{audio.stem}.srt"
            with (audio.parent / "processing.log").open("w", encoding="utf-8") as log:
                result = subprocess.run([core.CONFIG["python"], str(processor), "--audio", str(audio), "--script", str(script), "--output", str(output), "--config", str(config)],
                    cwd=processor.parent, stdout=log, stderr=subprocess.STDOUT, timeout=3600,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode or not output.is_file():
                failure=audio.parent/'failure.txt'
                detail=failure.read_text(encoding='utf-8',errors='replace').strip()[:240] if failure.is_file() else '可查看此任务的本地处理日志'
                raise ValueError("字幕对齐未完成："+detail)
            # Processor validates wording and alignment. Verify gapless timing again before publication.
            pairs = re.findall(r"(\d\d:\d\d:\d\d,\d\d\d) --> (\d\d:\d\d:\d\d,\d\d\d)", output.read_text(encoding="utf-8-sig"))
            if not pairs or any(a >= b for a, b in pairs) or any(pairs[i][1] != pairs[i + 1][0] for i in range(len(pairs) - 1)):
                raise ValueError("字幕时间校验未通过，未写入视频项目")
            destination, _ = core.resolve_destination(project_id, "subtitle", relative)
            saved = core.copy_into(output, destination)
            core.update_job(job_id, status="succeeded", progress=100, result=[saved])
    except Exception as exc:
        core.update_job(job_id, status="failed", error=str(getattr(exc, "detail", exc)))


@router.get("/status")
def status():
    return {"available": Path(core.CONFIG["subtitle_processor"]).is_file() and Path(core.CONFIG["subtitle_config"]).is_file(),
            "formats": "WAV / MP3 / M4A / AAC / FLAC / OGG / OPUS / WMA", "note": "沿用本机音频对齐能力，输出直接保存到所选项目"}


@router.post("/jobs")
async def create(project_id: str = Form(...), relative: str = Form("auto"), audio: UploadFile = File(...), script: UploadFile = File(...)):
    core.resolve_destination(project_id, "subtitle", relative)
    if Path(audio.filename or "").suffix.lower() not in core.EXTENSIONS["audio"] or Path(script.filename or "").suffix.lower() != ".txt":
        raise HTTPException(400, "请选择音频文件和 TXT 文案")
    job_id = core.create_job("subtitles", Path(audio.filename).stem + " · 字幕", {"project_id": project_id, "relative": relative})
    folder = core.DATA_DIR / "subtitle-jobs" / job_id
    folder.mkdir(parents=True)
    paths = []
    try:
        for upload, limit in [(audio, 512 * 1024 * 1024), (script, 2 * 1024 * 1024)]:
            path = folder / core.safe_filename(upload.filename)
            length = 0
            with path.open("xb") as handle:
                while chunk := await upload.read(1024 * 1024):
                    length += len(chunk)
                    if length > limit:
                        raise ValueError("文件过大：音频上限 512 MB，TXT 上限 2 MB")
                    handle.write(chunk)
            paths.append(path)
        threading.Thread(target=process, args=(job_id, *paths, project_id, relative), daemon=True).start()
        return {"job_id": job_id}
    except Exception as exc:
        core.update_job(job_id, status="failed", error=str(exc))
        raise HTTPException(400, str(exc))
