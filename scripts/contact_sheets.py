"""抽帧拼图：每隔 N 秒取一帧，5×4 拼成一张带时间码的缩略图（默认一张 = 60 秒素材）。可断点续跑。
用法:
  python contact_sheets.py --project <工作目录> [--step 3]
  python contact_sheets.py --project <目录> --strip <片段ID> <开始秒> <结束秒> [间隔秒]
        把某一小段按更密的间隔拼成一条，用来细看（选入点、认人、看表情）"""
import subprocess, sys
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg); FF = C.ffmpeg()
FONT = C.load_font(cfg, "cn", 18)
T, COLS, ROWS = 256, 5, 4
STEP = float(sys.argv[sys.argv.index("--step") + 1]) if "--step" in sys.argv else 3.0


def grab(path, step, a=0.0, b=None):
    vf = f"fps=1/{step},scale={T}:{T}:force_original_aspect_ratio=decrease,pad={T}:{T}:(ow-iw)/2:(oh-ih)/2"
    cmd = [FF, "-v", "error", "-ss", str(a)] + (["-to", str(b)] if b else []) + \
          ["-i", str(path), "-map", "0:v:0", "-vf", vf, "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    x = np.frombuffer(subprocess.run(cmd, capture_output=True).stdout, np.uint8)
    return x.reshape(-1, T, T, 3) if x.size else np.zeros((0, T, T, 3), np.uint8)


def fmt(s): return f"{int(s // 60):02d}:{s % 60:04.1f}" if s % 1 else f"{int(s // 60):02d}:{int(s % 60):02d}"


if "--strip" in sys.argv:
    k = sys.argv.index("--strip"); fid, a, b = sys.argv[k + 1], float(sys.argv[k + 2]), float(sys.argv[k + 3])
    st = float(sys.argv[k + 4]) if len(sys.argv) > k + 4 and not sys.argv[k + 4].startswith("--") else 1.0
    fr = grab(D["proxy"] / f"{fid}.mp4", st, a, b)
    cols = min(8, max(1, len(fr))); rows = (len(fr) + cols - 1) // cols
    im = Image.new("RGB", (cols * T, rows * T), "black"); d = ImageDraw.Draw(im)
    for j, f in enumerate(fr):
        x, y = (j % cols) * T, (j // cols) * T; im.paste(Image.fromarray(f), (x, y))
        d.rectangle([x, y, x + 74, y + 22], fill="black"); d.text((x + 3, y + 1), fmt(a + j * st), fill="yellow", font=FONT)
    out = D["sheets"] / f"_strip_{fid}_{a:g}_{b:g}.jpg"; im.save(out, quality=85); print(out); sys.exit()

files = sorted(D["proxy"].glob("*.mp4"))
if cfg.get("include"): files = [f for f in files if any(k in f.name for k in cfg["include"])]
for f in files:
    if any(D["sheets"].glob(f"{f.stem}__*.jpg")): continue
    fr = grab(f, STEP); per = COLS * ROWS
    for k in range(0, max(len(fr), 1), per):
        sheet = Image.new("RGB", (COLS * T, ROWS * T + 30), "black"); d = ImageDraw.Draw(sheet)
        d.text((6, 4), f"{f.stem}   {fmt(k * STEP)}–{fmt(min(len(fr), k + per) * STEP)}", fill="yellow", font=FONT)
        for j, img in enumerate(fr[k:k + per]):
            x, y = (j % COLS) * T, 30 + (j // COLS) * T
            sheet.paste(Image.fromarray(img), (x, y))
            d.rectangle([x, y, x + 62, y + 22], fill="black"); d.text((x + 3, y + 1), fmt((k + j) * STEP), fill="white", font=FONT)
        sheet.save(D["sheets"] / f"{f.stem}__{k // per:03d}.jpg", quality=80)
    print(f.stem, len(fr), "帧", flush=True)
print("DONE")
