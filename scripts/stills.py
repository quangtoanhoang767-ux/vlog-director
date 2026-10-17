"""从原片截高清图（朋友圈九宫格、封面、文章配图）：每个时刻前后各取几帧，挑最清晰的一张，按比例裁好。
用法: python stills.py --project <工作目录> 截图清单.csv [--ratio 1:1|4:5|16:9]
截图清单.csv 列：名字, 片段, 时间, 裁切中心X(0-1，可空), 裁切中心Y(0-1，可空)
输出：output/截图/<名字>.jpg 和一张总览图。"""
import csv, subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageEnhance
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg); FF = C.ffmpeg(); SRC = C.source_map(cfg)
LIST = next(Path(a) for a in sys.argv[1:] if a.endswith(".csv"))
rw, rh = map(int, (sys.argv[sys.argv.index("--ratio") + 1] if "--ratio" in sys.argv else "1:1").split(":"))
OUT = D["out"] / "截图"; OUT.mkdir(exist_ok=True)
FONT = C.load_font(cfg, "cn", 18)


def sharp(a):
    g = a.mean(2); return float(np.var(g[1:-1, 1:-1] * 4 - g[:-2, 1:-1] - g[2:, 1:-1] - g[1:-1, :-2] - g[1:-1, 2:]))


thumbs = []
for r in csv.DictReader(open(LIST, encoding="utf-8-sig")):
    fid = r["片段"]; t = C.parse_tc(r["时间"]); src = SRC[fid]
    rot = C.rotation_args(src, D["proxy"] / f"{fid}.mp4"); best = None
    for dt in np.linspace(-0.6, 0.6, 7):                    # 运动相机抖动大，前后找最不糊的一帧
        raw = subprocess.run([FF, "-v", "error", *rot, "-ss", f"{max(0, t + dt):.2f}", "-i", str(src), "-frames:v", "1",
                              "-vf", "scale=960:-2", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True).stdout
        if not raw: continue
        s = sharp(np.frombuffer(raw, np.uint8).reshape(-1, 960, 3).astype(np.float32))
        if best is None or s > best[0]: best = (s, max(0, t + dt))
    png = OUT / f"_{r['名字']}.png"
    subprocess.run([FF, "-v", "error", "-y", *rot, "-ss", f"{best[1]:.2f}", "-i", str(src), "-frames:v", "1", str(png)], check=True)
    im = Image.open(png).convert("RGB"); png.unlink()
    w, h = im.size; cw = min(w, h * rw / rh); ch = cw * rh / rw
    cx = float(r.get("裁切中心X") or 0.5) * w; cy = float(r.get("裁切中心Y") or 0.5) * h
    l = min(max(cx - cw / 2, 0), w - cw); tp = min(max(cy - ch / 2, 0), h - ch)
    im = im.crop((round(l), round(tp), round(l + cw), round(tp + ch)))
    im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.1)).enhance(1.04)
    im.save(OUT / f"{r['名字']}.jpg", quality=95)
    thumbs.append((r["名字"], im.resize((360, round(360 * rh / rw)))))
    print(r["名字"], f"@{best[1]:.2f}s", im.size, flush=True)

cols = 6; th = thumbs[0][1].height if thumbs else 360
sheet = Image.new("RGB", (cols * 360, ((len(thumbs) + cols - 1) // cols) * (th + 30)), "white"); d = ImageDraw.Draw(sheet)
for i, (n, im) in enumerate(thumbs):
    x, y = (i % cols) * 360, (i // cols) * (th + 30); sheet.paste(im, (x, y + 30)); d.text((x + 6, y + 4), n, fill="black", font=FONT)
sheet.save(OUT / "_总览.jpg", quality=85); print("完成", OUT)
