import argparse, json, os
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--python", required=True)
p.add_argument("--ffmpeg", required=True)
p.add_argument("--bbdown", required=True)
a = p.parse_args()
app = Path(__file__).resolve().parent
config = json.loads((app / "config.template.json").read_text(encoding="utf8"))
home = Path(os.environ.get("USERPROFILE", str(Path.home())))
root = home / "Desktop" / "素材台工作区"
library, projects = root / "素材库", root / "视频项目"
library.mkdir(parents=True, exist_ok=True)
projects.mkdir(parents=True, exist_ok=True)
config.update(python=str(Path(a.python).resolve()), ffmpeg=str(Path(a.ffmpeg).resolve()),
              bbdown=str(Path(a.bbdown).resolve()), video_root=str(root),
              projects_root=str(projects),
              sources=[{"id": "local-library", "name": "我的素材库", "path": str(library)}])
(app / "config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
print(root)
