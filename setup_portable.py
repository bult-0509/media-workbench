import argparse
import json
import os
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--python", required=True)
p.add_argument("--ffmpeg", required=True)
p.add_argument("--bbdown", required=True)
a = p.parse_args()

app = Path(__file__).resolve().parent
config_path = app / "config.json"

config = json.loads((app / "config.template.json").read_text(encoding="utf8"))
existing = {}
if config_path.is_file():
    try:
        existing = json.loads(config_path.read_text(encoding="utf8"))
    except (OSError, json.JSONDecodeError):
        existing = {}
config.update(existing)


def usable(key: str) -> bool:
    value = str(config.get(key) or "").strip()
    return bool(value) and Path(value).is_file()


for key, value in (("python", a.python), ("ffmpeg", a.ffmpeg), ("bbdown", a.bbdown)):
    if not usable(key):
        config[key] = str(Path(value).resolve())

home = Path(os.environ.get("USERPROFILE", str(Path.home())))
root = Path(str(config.get("video_root") or "").strip() or home / "Desktop" / "素材台工作区")
projects = Path(str(config.get("projects_root") or "").strip() or root / "视频项目")
projects.mkdir(parents=True, exist_ok=True)
config["video_root"] = str(root)
config["projects_root"] = str(projects)
if not config.get("sources"):
    library = root / "素材库"
    library.mkdir(parents=True, exist_ok=True)
    config["sources"] = [{"id": "local-library", "name": "我的素材库", "path": str(library)}]

config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf8")

print(root)
if existing:
    print("已保留 config.json 中原有的设置，仅补全缺失项。")
