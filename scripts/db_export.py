"""把素材数据库（analysis/db/*.jsonl，每行一个片段）检查一遍并导出成表格：
  selects/素材数据库_全部.csv   selects/S级素材.csv   selects/A级素材.csv
用 Excel / WPS / Numbers 都能直接打开（UTF-8 带 BOM，中文不乱码）。
用法: python db_export.py --project <工作目录>"""
import csv, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg)
COLS = [("grade", "等级"), ("id", "ID"), ("file", "片段"), ("start", "开始"), ("end", "结束"), ("date", "日期"),
        ("clock", "拍摄时刻"), ("place", "地点"), ("people", "人物"), ("visual", "画面内容"), ("event", "发生事件"),
        ("quotes", "重要对话"), ("reaction", "人物反应"), ("mood", "情绪"), ("funny", "搞笑"), ("story", "故事价值"),
        ("broll", "空镜"), ("transition", "转场"), ("opener", "可当开头"), ("ending", "可当结尾"),
        ("video_q", "画质"), ("audio_q", "音质"), ("score.person", "人物分"), ("score.story", "故事分"),
        ("score.funny", "搞笑分"), ("score.emotion", "情绪分"), ("score.visual", "画面分"), ("score.rarity", "稀缺分"),
        ("score.overall", "综合分"), ("tags", "标签"), ("notes", "备注/伏笔")]
REQUIRED = ["id", "file", "start", "end", "event", "grade", "score"]
srcs = C.source_map(cfg)

rows, problems = [], []
for f in sorted(D["db"].glob("*.jsonl")):
    for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip(): continue
        try: r = json.loads(line)
        except json.JSONDecodeError as e: problems.append(f"{f.name}:{n} 不是合法 JSON：{e}"); continue
        miss = [k for k in REQUIRED if k not in r]
        if miss: problems.append(f"{f.name}:{n} 缺字段 {miss}")
        if r.get("file") not in srcs: problems.append(f"{f.name}:{n} 片段 {r.get('file')} 在原片里找不到")
        if r.get("grade") not in ("S", "A", "B", "C"): problems.append(f"{f.name}:{n} 等级应为 S/A/B/C：{r.get('grade')}")
        rows.append(r)


def cell(r, k):
    v = r
    for p in k.split("."): v = v.get(p, "") if isinstance(v, dict) else ""
    if isinstance(v, bool): return "是" if v else ""
    if isinstance(v, list): return "、".join(map(str, v))
    return v


order = {"S": 0, "A": 1, "B": 2, "C": 3}
rows.sort(key=lambda r: (order.get(r.get("grade"), 9), -(r.get("score", {}).get("overall") or 0), r.get("id", "")))
for name, keep in (("素材数据库_全部.csv", None), ("S级素材.csv", "S"), ("A级素材.csv", "A")):
    with open(D["selects"] / name, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh); w.writerow([c for _, c in COLS])
        for r in rows:
            if keep is None or r.get("grade") == keep: w.writerow([cell(r, k) for k, _ in COLS])
cnt = {g: sum(r.get("grade") == g for r in rows) for g in "SABC"}
print(f"{len(rows)} 个片段  S {cnt['S']} / A {cnt['A']} / B {cnt['B']} / C {cnt['C']}  → {D['selects']}")
covered = {r.get("file") for r in rows}
left = [k for k in srcs if k not in covered]
if left: print(f"还有 {len(left)} 个原片没建档：{', '.join(left[:10])}{' …' if len(left) > 10 else ''}")
for p in problems: print("  [!!] " + p)
