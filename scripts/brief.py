"""给一个片段出「速读卡」：时长、拼图文件、带时间码的对白、音量突然变大的位置（多半是在笑或尖叫）。
建数据库时每个片段先看这张卡，再看拼图。
用法: python brief.py --project <工作目录> <片段ID或关键字> [...]"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg)
keys = [a for a in sys.argv[1:] if not a.startswith("--") and a != str(cfg["_dir"]) and Path(a).resolve() != cfg["_dir"]]
HALLU = ("订阅", "点赞", "字幕", "感谢观看", "Thank you for watching", "subscribe", "Hãy đăng ký")
for f in sorted(D["transcripts"].glob("*.json")):
    if keys and not any(k in f.stem for k in keys): continue
    r = json.loads(f.read_text(encoding="utf-8"))
    sheets = sorted(D["sheets"].glob(f"{r['file']}__*.jpg"))
    print(f"\n### {r['file']}  时长 {C.tc(r['duration'])}  拼图 {len(sheets)} 张: {', '.join(s.name for s in sheets[:6])}{' …' if len(sheets) > 6 else ''}")
    for s in r["segments"]:
        flag = ""
        if s["no_speech"] > 0.6: flag = "  [可能不是人声]"
        elif any(h in s["text"] for h in HALLU): flag = "  [疑似幻听：对着音乐或噪音编出来的]"
        elif s["logprob"] < -1.0: flag = "  [听不清]"
        print(f"  {C.tc(s['start'])}–{C.tc(s['end'])}  {s['text']}{flag}")
    if not r["segments"]: print("  （没有人声）")
    L = r["loudness_db_0.5s"]
    if L:
        base = sorted(L)[len(L) // 2]
        peaks = [i * 0.5 for i, v in enumerate(L) if v > base + 15 and (i == 0 or L[i - 1] <= base + 15)]
        if peaks: print("  音量突增：" + "  ".join(C.tc(p) for p in peaks[:20]))
