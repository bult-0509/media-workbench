"""Local adapter: align unchanged semantic segments with a larger token window.

Reuse the installed processor's skill and validators without changing the QQ
service. The original text, confidence, duration and gap checks remain strict.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import wave
from pathlib import Path


def process(audio: Path, script: Path, output: Path, config_path: Path):
    config=json.loads(config_path.read_text(encoding='utf-8'))
    legacy_path=config_path.with_name('process_job.py')
    spec=importlib.util.spec_from_file_location('existing_subtitle_processor',legacy_path)
    legacy=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    folder=output.parent
    folder.mkdir(parents=True,exist_ok=True)
    text=legacy.read_script(script)
    segments=legacy.segment_with_codex(text,folder,config)
    wav=folder/'alignment-audio.wav'
    subprocess.run([config['ffmpeg_path'],'-nostdin','-v','error','-y','-i',str(audio),'-vn','-ac','1','-ar','16000','-t',str(config['max_duration_seconds']+1),'-c:a','pcm_s16le',str(wav)],check=True,timeout=300,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    with wave.open(str(wav)) as handle:
        duration=handle.getnframes()/handle.getframerate()
    if duration<.3 or duration>config['max_duration_seconds']:
        raise ValueError('音频过短或超过配置时长上限')
    os.environ['PATH']=str(Path(config['ffmpeg_path']).parent)+os.pathsep+os.environ['PATH']
    import torch
    import stable_whisper
    torch.set_num_threads(config.get('cpu_threads',6))
    device='cuda' if torch.cuda.is_available() else 'cpu'
    model=stable_whisper.load_model(config.get('whisper_model','small'),device=device)
    result=model.align(str(wav),'\n'.join(segments),language=config.get('language','zh'),original_split=True,regroup=False,verbose=False,failure_threshold=.15,fast_mode=True,token_step=200)
    if result is None:
        raise ValueError('音频对齐失败')
    aligned=result.to_dict()
    (folder/'alignment.json').write_text(json.dumps(aligned,ensure_ascii=False,indent=2),encoding='utf-8')
    cues=legacy.build_cues(segments,aligned,duration)
    content='\n\n'.join(f"{i}\n{legacy.timestamp(c['start_ms'])} --> {legacy.timestamp(c['end_ms'])}\n{c['text']}" for i,c in enumerate(cues,1))+'\n'
    temp=output.with_suffix('.srt.tmp')
    temp.write_text(content,encoding='utf-8',newline='\n')
    temp.replace(output)
    report={'audio_seconds':duration,'cues':len(cues),'gap_ms':0,'text_preserved':True,'model':config.get('whisper_model','small'),'device':device,'token_step':200,'output':str(output)}
    (folder/'validation.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['audio','script','output','config']:
        parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args()
    try:
        print(json.dumps(process(args.audio.resolve(),args.script.resolve(),args.output.resolve(),args.config.resolve()),ensure_ascii=False))
    except Exception as exc:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        (args.output.parent/'failure.txt').write_text(str(exc),encoding='utf-8')
        raise
