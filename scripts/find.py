"""在所有转写里搜关键词，列出片段 ID 和时间码。用户说「那个说 xxx 的镜头」时用它定位。
用法: python find.py --project <工作目录> 关键词 [关键词2 ...]   （多个词 = 任一命中）"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg)
words = [a for a in sys.argv[1:] if not a.startswith("--") and Path(a).resolve() != cfg["_dir"]]
n = 0
for f in sorted(D["transcripts"].glob("*.json")):
    for s in json.loads(f.read_text(encoding="utf-8"))["segments"]:
        if any(w.lower() in s["text"].lower() for w in words):
            print(f"{f.stem}  {C.tc(s['start'])}–{C.tc(s['end'])}  {s['text']}"); n += 1
print(f"共 {n} 处")
