"""长片模式：按剪辑表（CSV）出片。原片只读。
  - 画面：原片按镜头裁成目标画幅（方形/竖屏素材取景偏上），统一帧率、轻微提饱和
  - 同期声：每个镜头自动把说话的部分拉到差不多的音量
  - 配乐：用户的音乐文件（循环铺满），或 music.py 合成的三段循环；
          只有两档固定音量——有人说话时低、没人说话超过 2.5 秒才升高，切换缓慢，不会忽大忽小
  - 字幕：对白按转写时间对齐；字卡、强调字、片名
用法: python render_long.py --project <工作目录> [剪辑表.csv] [--out 成片名.mp4] [--audio-only]
剪辑表格式见 references/edl_format.md"""
import csv, json, re, shutil, subprocess, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import common as C
import music

cfg = C.load_config(); D = C.dirs(cfg); FF = C.ffmpeg()
W, H, FPS = cfg["output"]["width"], cfg["output"]["height"], cfg["output"]["fps"]; SR = 48000
EDL = next((Path(a) for a in sys.argv[1:] if a.endswith(".csv")), None) or max(D["edit"].glob("剪辑表*.csv"), key=lambda p: p.stat().st_mtime)
OUT = next((a for a in sys.argv if a.endswith(".mp4")), f"{cfg['title'] or '成片'}_长片.mp4")
SRC = C.source_map(cfg); ENC = C.video_encoder()
R = D["edit"]; SEG = D["cache"]
print("剪辑表:", EDL)

# ---------- 1. 镜头表（时长按帧取整，保证音画对齐） ----------
shots, t = [], 0.0
for r in csv.DictReader(open(EDL, encoding="utf-8-sig")):
    f = (r.get("片段") or "").strip()
    card = f in ("", "—", "-", "黑场", "字卡")
    a = 0.0 if card else C.parse_tc(r["入点"])
    b = a + float(r.get("时长") or 3) if card else C.parse_tc(r["出点"])
    if not card and f not in SRC: sys.exit(f"第 {r.get('#')} 行：片段 {f} 在原片里找不到")
    nf = max(1, int(round((b - a) * FPS))); d = nf / FPS
    shots.append(dict(n=r.get("#", ""), sec=r.get("段落", ""), file=None if card else f, a=a, b=a + d, nf=nf, d=d, t=t,
                      snd=r.get("声音", "同期声"), sub=r.get("字幕", ""), style=(r.get("音乐") or "").strip()))
    t += d
TOTAL = t; print(f"{len(shots)} 个镜头，总长 {C.tc(TOTAL)}")


# ---------- 2. 视频片段（按内容缓存，改剪辑表只重渲变了的镜头） ----------
def crop_vf(src, fid):
    w, h, *_ = C.probe(src)
    if not w: return f"scale={W}:{H}"
    if not C.rotation_args(src, D["proxy"] / f"{fid}.mp4") and abs(C.rotation_angle(src)) == 90: w, h = h, w
    if w / h < W / H:          # 素材比目标「高」：裁上下，取景偏上
        return f"crop=iw:'iw*{H}/{W}':0:'(ih-iw*{H}/{W})*{cfg['crop_y']}'"
    return f"crop='ih*{W}/{H}':ih:'(iw-ih*{W}/{H})/2':0"


def key(s):
    return f"black_{s['nf']}" if s["file"] is None or "黑场" in s["snd"] else f"{s['file']}_{s['a']:.2f}_{s['nf']}_{W}x{H}"


def vseg(s):
    out = SEG / f"{key(s)}.mp4"
    if out.exists(): return out
    enc = [*ENC, "-pix_fmt", "yuv420p", "-an", "-frames:v", str(s["nf"]), "-r", str(FPS)]
    if s["file"] is None or "黑场" in s["snd"]:
        cmd = [FF, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=black:s={W}x{H}:r={FPS}", *enc, str(out)]
    else:
        src = SRC[s["file"]]
        vf = f"{crop_vf(src, s['file'])},scale={W}:{H}:flags=lanczos,fps={FPS},eq=saturation=1.08:contrast=1.03"
        cmd = [FF, "-v", "error", "-y", *C.rotation_args(src, D["proxy"] / f"{s['file']}.mp4"),
               "-ss", f"{s['a']:.3f}", "-i", str(src), "-vf", vf, *enc, str(out)]
    subprocess.run(cmd, check=True)
    return out


# ---------- 3. 音频 ----------
def aread(path, a, d):
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{a:.3f}", "-t", f"{d:.3f}", "-i", str(path), "-map", "0:a:0?",
                          "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2); n = int(round(d * SR))
    if len(x) < n: x = np.vstack([x, np.zeros((n - len(x), 2), np.float32)])
    return x[:n].copy()


def level(x):
    """把同期声里有内容的部分拉到约 -20 dBFS，增益限制在 -6～+14 dB"""
    if len(x) < SR // 10: return x
    m = x.mean(1); hop = SR // 20; k = len(m) // hop
    act = np.percentile(np.sqrt((m[:k * hop].reshape(k, hop) ** 2).mean(1) + 1e-12), 90)
    return x * np.clip(0.1 / max(act, 1e-5), 0.5, 5.0)


def ramp(x, ms=15):
    n = min(len(x) // 2, int(SR * ms / 1000))
    if n > 0: w = np.linspace(0, 1, n, dtype=np.float32)[:, None]; x[:n] *= w; x[-n:] *= w[::-1]
    return x


N = int(round(TOTAL * SR))
dia = np.zeros((N, 2), np.float32); mute = np.zeros(N, np.float32); style = np.empty(N, "<U6"); style[:] = "verse"
STYLES = ("verse", "chorus", "light")
for k, s in enumerate(shots):
    i0 = int(round(s["t"] * SR)); n = min(int(round(s["d"] * SR)), N - i0); snd = s["snd"]
    if s["file"] and "静音" not in snd:
        x = level(aread(D["proxy"] / f"{s['file']}.mp4", s["a"], s["d"]))[:n]
        if "同期声" not in snd: x *= 0.3                      # 纯配乐镜头：现场声压低当环境音
        dia[i0:i0 + n] += ramp(x)
    style[i0:i0 + n] = s["style"] if s["style"] in STYLES else ("chorus" if k / len(shots) > 0.3 and k / len(shots) < 0.8 else "verse")
    if "BGM全停" in snd.replace(" ", "") or "黑场" in snd or k == len(shots) - 1: mute[i0:i0 + n] = 1
    elif "BGM停" in snd.replace(" ", ""): mute[i0 + n - int(1.3 * SR):i0 + n] = 1      # 只在镜头最后 1.3 秒留白

# 配乐来源：用户文件（循环）或合成
mfile = (cfg.get("music") or {}).get("long") if isinstance(cfg.get("music"), dict) else None
if mfile:
    raw = subprocess.run([FF, "-v", "error", "-i", mfile, "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    one = np.frombuffer(raw, np.float32).reshape(-1, 2); one = one / np.sqrt((one ** 2).mean() + 1e-12)
    bgm = one[np.arange(N) % len(one)].astype(np.float32)
else:
    loops = {}
    for st in STYLES:
        p = D["music"] / f"vlog_{st}.npy"
        if not p.exists():
            print("合成配乐 …"); [np.save(D["music"] / f"vlog_{k}.npy", v) for k, v in music.make_loops().items()]
        loops[st] = np.load(p); loops[st] = loops[st] / np.sqrt((loops[st] ** 2).mean())
    idx = np.arange(N) % len(loops["verse"]); bgm = np.zeros((N, 2), np.float32)
    for st, arr in loops.items():                      # 节拍对齐的三条循环，段落之间 1 秒交叉淡化
        w = C.box(style == st, SR)
        bgm += arr[idx] * w[:, None]

# 两档音量：说话 -34 dBFS / 不说话 -23 dBFS
talk = np.zeros(N, bool); sync = np.zeros(N, bool)
for s in shots:
    if not s["file"] or "同期声" not in s["snd"]: continue
    sync[int(s["t"] * SR):int((s["t"] + s["d"]) * SR)] = True
    tj = D["transcripts"] / f"{s['file']}.json"
    if not tj.exists(): continue
    for g in json.loads(tj.read_text(encoding="utf-8"))["segments"]:
        if g["no_speech"] > 0.6 or g["end"] <= s["a"] or g["start"] >= s["b"]: continue
        i = int((s["t"] + max(0, g["start"] - s["a"])) * SR); j = int((s["t"] + min(s["d"], g["end"] - s["a"])) * SR)
        talk[max(0, i - SR // 2):j + SR // 2] = True
win = SR // 2
loud = np.sqrt(C.box(dia.mean(1) ** 2, win) + 1e-10) > 0.035
talk |= loud & sync                                   # 笑声、尖叫这种没转写出来的响声也算「有人在说」
hop = SR // 10; tk = talk[: N // hop * hop].reshape(-1, hop).any(1); gap = 0
for k in range(len(tk)):                              # 2.5 秒以内的空隙填平：句子之间音乐不冒上来
    if tk[k]:
        if 0 < gap <= 25: tk[k - gap:k] = True
        gap = 0
    else: gap += 1
lvl = np.pad(np.where(np.repeat(tk, hop), 10 ** (-34 / 20), 10 ** (-23 / 20)).astype(np.float32), (0, N - len(tk) * hop), mode="edge")
lvl = C.box(lvl, 1.2 * SR)
duck = lvl * (1 - C.box(mute, 0.15 * SR))
mix = np.tanh((dia + bgm * duck[:, None]) * 1.1) / 1.1
(R / "_mix.f32").write_bytes(mix.astype(np.float32).tobytes())
print(f"混音完成  峰值 {float(np.abs(mix).max()):.2f}")


# ---------- 4. 字幕 ----------
fcn = C.font_path(cfg, "cn_bold"); FDIR = R / "_fonts"; FDIR.mkdir(exist_ok=True)
if not (FDIR / Path(fcn).name).exists(): shutil.copy(fcn, FDIR)
from PIL import ImageFont
FAM = ImageFont.truetype(fcn, 20).getname()[0]
AW, AH = 1280, round(1280 * H / W)
def ts(x): x = max(0, x); return f"{int(x // 3600)}:{int(x % 3600 // 60):02d}:{x % 60:05.2f}"
def clean(s): return re.sub(r"[\s，。！？、…—,.!?「」『』（）()·：:]", "", s)
ev = []
for s in shots:
    parts = [p.strip() for p in s["sub"].split("｜") if p.strip()]; lines = []
    for p in parts:
        m = re.match(r"【(.+?)】(.*)", p)
        if not m: lines.append(p); continue
        kind, txt = m.group(1), m.group(2).strip()
        if kind == "片名": ev.append((s["t"] + 0.5, s["t"] + s["d"], "Title", txt or cfg["title"]))
        elif kind == "强调字": ev.append((s["t"] + 0.8, s["t"] + s["d"], "Big", txt))
        else: ev.append((s["t"], s["t"] + (min(s["d"], 3.0) if s["file"] else s["d"]), "Card", txt))
    if not lines: continue
    times = [None] * len(lines)
    tj = D["transcripts"] / f"{s['file']}.json" if s["file"] else None
    if tj and tj.exists():                           # 每句字幕去转写里找最像的那句，用它的开始时间
        segs = [g for g in json.loads(tj.read_text(encoding="utf-8"))["segments"] if g["end"] > s["a"] and g["start"] < s["b"]]
        last = s["a"]
        for j, ln in enumerate(lines):
            c = set(clean(ln)); best, bs = None, 0
            for g in segs:
                if g["end"] <= last - 0.3: continue
                sc = len(c & set(clean(g["text"]))) / max(1, len(c))
                if sc > bs: best, bs = g, sc
            if best is not None and bs >= 0.5: times[j] = max(best["start"], s["a"]) - s["a"]; last = best["start"]
    known = [(-1, 0.0)] + [(j, x) for j, x in enumerate(times) if x is not None] + [(len(lines), s["d"])]
    for j in range(len(lines)):                      # 对不上的按前后已知时间线性插值
        if times[j] is None:
            lo = max(k for k in known if k[0] < j); hi = min(k for k in known if k[0] > j)
            times[j] = lo[1] + (hi[1] - lo[1]) * (j - lo[0]) / (hi[0] - lo[0])
    for j in range(len(lines)):
        a = s["t"] + max(0, min(times[j], s["d"] - 0.6))
        b = s["t"] + (min(times[j + 1], s["d"]) if j + 1 < len(lines) else s["d"])
        ev.append((a, max(b, a + 0.7), "Dia", lines[j]))
sty = lambda name, size, col, align, outline, sp=0: f"Style: {name},{FAM},{size},{col},&H00FFFFFF,&H00202020,&H64000000,1,0,0,0,100,100,{sp},0,1,{outline},1,{align},40,40,{42 if align == 2 else 40},1"
ass = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {AW}", f"PlayResY: {AH}", "WrapStyle: 0", "", "[V4+ Styles]",
       "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
       sty("Dia", 40, "&H00FFFFFF", 2, 2.6), sty("Card", 34, "&H00FFFFFF", 8, 2, 2), sty("Big", 96, "&H0000E6FF", 5, 4, 4),
       sty("Title", 64, "&H00FFFFFF", 5, 0, 6), "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
FAD = "{\\fad(200,200)}"
for a, b, st, txt in sorted(ev):
    ass.append(f"Dialogue: 0,{ts(a)},{ts(b)},{st},,0,0,0,,{FAD if st != 'Dia' else ''}{txt}")
(R / "_subs.ass").write_text("\n".join(ass) + "\n", encoding="utf-8")
print(f"字幕 {len(ev)} 条（字体 {FAM}）")
if "--audio-only" in sys.argv: sys.exit()

# ---------- 5. 片段 → 拼接 → 合成 ----------
for k, s in enumerate(shots, 1):
    vseg(s); print(f"\r画面片段 {k}/{len(shots)}", end="", flush=True)
print()
(R / "_list.txt").write_text("".join(f"file '{SEG.name}/{key(s)}.mp4'\n" for s in shots), encoding="utf-8")
subprocess.run([FF, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(R / "_list.txt"), "-c", "copy",
                str(R / "_video.mp4")], check=True)
out = D["out"] / OUT
subprocess.run([FF, "-v", "error", "-y", "-i", "_video.mp4", "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", "_mix.f32",
                "-vf", "ass=_subs.ass:fontsdir=_fonts", *ENC, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart", str(out)], cwd=R, check=True)
print("完成", out)
