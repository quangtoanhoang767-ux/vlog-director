"""混剪模式：杂志卡片风快剪，切点全部卡在音乐小节上。逐帧合成，原片只读。
效果：画面做成圆角卡片从侧边弹入（带回弹）+ 背景放大并铺白雾 + 小字/大标题/中文副标题逐个浮现；
      不足 1 小节的镜头全屏快切，带 RGB 分离；可选白闪；指定镜头混入原声（音乐自动压低）。
用法: python render_montage.py --project <工作目录> [镜头表.csv] [--out 名字.mp4]
        [--bpm 140] [--key 0] [--music 歌.mp3 --music-offset 秒] [--intro 2] [--end 3] [--preview 镜头序号]
镜头表格式见 references/montage_format.md。--preview 只渲染某个镜头存成 jpg，用来快速看效果。"""
import csv, re, subprocess, sys, time
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFilter
sys.path.insert(0, str(Path(__file__).parent))
import common as C
import music

cfg = C.load_config(); D = C.dirs(cfg); FF = C.ffmpeg(); SRC = C.source_map(cfg)
W, H, FPS, SR = 1920, 1080, 30, 48000          # 卡片布局按 1920×1080 设计
def arg(k, d): return type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
BPM = arg("--bpm", 140.0); BAR = 60 / BPM * 4
INTRO, END = arg("--intro", 2.0), arg("--end", 3.0)
LIST = next((Path(a) for a in sys.argv[1:] if a.endswith(".csv")), None) or max(D["edit"].glob("混剪镜头表*.csv"), key=lambda p: p.stat().st_mtime)
OUT = next((a for a in sys.argv if a.endswith(".mp4")), f"{cfg['title'] or '成片'}_混剪.mp4")

SHOTS = []
for r in csv.DictReader(open(LIST, encoding="utf-8-sig")):
    if r["片段"] not in SRC: sys.exit(f"镜头表里的片段 {r['片段']} 在原片里找不到")
    SHOTS.append((r["片段"], C.parse_tc(r["入点"]), float(r["小节"]), r.get("小字", ""), r.get("大标题", ""),
                  r.get("副标题", ""), r.get("标记", "")))
EV = [("intro", 0, round(INTRO * BAR * FPS), None)]; bar = INTRO
for s in SHOTS:
    EV.append(("shot", round(bar * BAR * FPS), round((bar + s[2]) * BAR * FPS), s)); bar += s[2]
EV.append(("end", round(bar * BAR * FPS), round((bar + END) * BAR * FPS), None))
TOTAL_BARS = bar + END; TOTAL = EV[-1][2]
print(f"{len(SHOTS)} 个镜头，{TOTAL_BARS:g} 小节 ≈ {TOTAL / FPS:.1f} 秒（{BPM:g} BPM）")

F = {k: C.font_path(cfg, k) for k in ("cn", "cn_bold", "latin_black", "serif_italic", "hand", "symbol")}
from PIL import ImageFont
def font(role, size):
    f = ImageFont.truetype(F[role], size)
    if role == "cn_bold" and "wght" in Path(F[role]).name:
        try: f.set_variation_by_name("Bold")
        except Exception: pass
    return f
def ease_back(x, k=1.35): x = min(max(x, 0), 1) - 1; return 1 + (k + 1) * x ** 3 + k * x ** 2
def ease_out(x): x = min(max(x, 0), 1); return 1 - (1 - x) ** 3

# ---------- 预先算好的图层：卡片圆角遮罩、阴影、白雾 ----------
CW, CH, RAD, CY, PAD = 1040, 560, 34, 262, 90
def rounded(w, h, r, ss=3):
    m = Image.new("L", (w * ss, h * ss), 0); ImageDraw.Draw(m).rounded_rectangle([0, 0, w * ss - 1, h * ss - 1], r * ss, fill=255)
    return np.asarray(m.resize((w, h), Image.LANCZOS), np.float32)[..., None] / 255
MASK = rounded(CW, CH, RAD)
sh = Image.new("L", (CW + 2 * PAD, CH + 2 * PAD), 0); ImageDraw.Draw(sh).rounded_rectangle([PAD, PAD, PAD + CW, PAD + CH], RAD, fill=255)
SHADOW = np.asarray(sh.filter(ImageFilter.GaussianBlur(32)), np.float32)[..., None] / 255 * 0.55
xs = np.linspace(0, 1, W, dtype=np.float32); ys = np.linspace(0, 1, H, dtype=np.float32)[:, None, None]
def smooth(a, b, x): t = np.clip((x - a) / (b - a), 0, 1); return t * t * (3 - 2 * t)
GL = (1 - smooth(0.26, 0.64, xs))[None, :, None] * np.ones((H, 1, 1), np.float32)
GL = np.clip(GL + 0.25 * (1 - smooth(0.0, 0.25, ys)) * (1 - smooth(0.4, 0.8, xs))[None, :, None], 0, 1)
GR = GL[:, ::-1].copy()


def cjk(s): return any(ord(c) > 0x2E80 for c in s)
def is_sym(c): return 0x2190 <= ord(c) <= 0x2BFF                  # 箭头、✓✗、★ 等：中文和英文字体大多没有


def runs(text, role, size):
    """按字切成 (文字, 字体) 小段：符号用符号字体，其余用指定字体。返回小段列表和总宽度。"""
    out = []
    for c in text:
        r = "symbol" if is_sym(c) else role
        if out and out[-1][1] == r: out[-1][0] += c
        else: out.append([c, r])
    segs = [(t, font(r, size)) for t, r in out]
    return segs, sum(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(t, font=f) for t, f in segs)


def draw_runs(d, x, y, segs, fill):
    for t, f in segs:
        d.text((x, y), t, font=f, fill=fill); x += d.textlength(t, font=f)


def text_layer(s, side):
    small, big, sub = s[3], s[4], s[5]
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    cx = 75 + CW // 2 if side == "L" else W - 75 - CW // 2
    if small:
        segs, w = runs(small, "cn" if cjk(small) else "serif_italic", 34)
        draw_runs(d, cx - w / 2, 188, segs, (30, 30, 30, 255))
        d.line([(cx - 60, 238), (cx + 60, 238)], fill=(30, 30, 30, 160), width=2)
    tx = 75 + 340 if side == "L" else W - 75 - 340
    if big:
        role = "cn_bold" if cjk(big) or any(ord(c) > 0xFF and not is_sym(c) for c in big) else "latin_black"
        fs = 104
        while True:
            segs, w = runs(big, role, fs)
            if w < 820 or fs < 50: break
            fs -= 4
        draw_runs(d, tx if side == "L" else tx - w, 846, segs, (12, 12, 12, 255))
    if sub:
        segs, w = runs(sub, "cn", 36)
        draw_runs(d, tx if side == "L" else tx - w, 968, segs, (40, 40, 40, 255))
    a = np.asarray(img, np.float32); return a[..., :3], a[..., 3:] / 255


def frames(fid, a, n):
    """从原片按 1920 宽解码（4K 素材缩下来，卡片和背景都够清晰）"""
    src = SRC[fid]; w0, h0, *_ = C.probe(src)
    rot = C.rotation_args(src, D["proxy"] / f"{fid}.mp4")
    ow, oh = (h0, w0) if not rot and abs(C.rotation_angle(src)) == 90 else (w0, h0)   # ffmpeg 会按旋转标记自动转正
    h = round(oh * W / ow / 2) * 2
    p = subprocess.Popen([FF, "-v", "error", *rot, "-ss", f"{a:.3f}", "-i", str(src), "-t", f"{n / FPS + 0.5:.3f}",
                          "-vf", f"scale={W}:{h}:flags=bicubic,eq=brightness=0.025:contrast=1.02:saturation=1.08,fps={FPS}",
                          "-pix_fmt", "rgb24", "-f", "rawvideo", "-"], stdout=subprocess.PIPE)
    last = np.zeros((h, W, 3), np.uint8)
    for _ in range(n):
        buf = p.stdout.read(W * h * 3)
        if len(buf) == W * h * 3: last = np.frombuffer(buf, np.uint8).reshape(h, W, 3)
        yield last
    p.kill()


def crop_resize(img, cx, cy, cw, ch, ow, oh):
    l, t = min(max(cx - cw / 2, 0), img.width - cw), min(max(cy - ch / 2, 0), img.height - ch)
    return np.asarray(img.resize((ow, oh), Image.BILINEAR, box=(l, t, l + cw, t + ch)), np.float32)


def paste(dst, src, al, x, y):
    h_, w_ = al.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w_, W), min(y + h_, H)
    if x1 <= x0 or y1 <= y0: return
    sl = (slice(y0 - y, y1 - y), slice(x0 - x, x1 - x)); dl = (slice(y0, y1), slice(x0, x1)); A = al[sl]
    dst[dl] = dst[dl] * (1 - A) + (src[sl] if src is not None else 0) * A


def render_shot(s, n, out):
    flag = s[6]; full = s[2] < 1; side = "R" if "r" in flag else "L"
    tl = None if full else text_layer(s, side)
    for i, fr in enumerate(frames(s[0], s[1], n)):
        t = i / FPS; u = i / max(1, n - 1); img = Image.fromarray(fr); sh_, sw_ = fr.shape[:2]
        cy = sh_ * (cfg["crop_y"] + 0.03 if sh_ > sw_ * 0.7 else 0.5)
        punch = 0.07 * np.exp(-t / 0.12)
        if full:                                                  # 全屏快切：推近 + RGB 分离
            z = 1.16 - 0.10 * u + punch
            o = crop_resize(img, sw_ / 2, cy, W / z, H / z, W, H)
            k = int(10 * np.exp(-t / 0.1))
            if k: o[:, :, 0] = np.roll(o[:, :, 0], k, 1); o[:, :, 2] = np.roll(o[:, :, 2], -k, 1)
        else:
            z = 1.12 + 0.08 * u + punch
            bg = crop_resize(img, sw_ * (0.42 if side == "L" else 0.58), cy, W / z, H / z, W, H)
            o = bg + (255 - bg) * (GL if side == "L" else GR)
            cz = 1.0 + 0.05 * u; ch_ = min(sh_, sw_ * CH / CW) / cz; cw_ = ch_ * CW / CH
            card = crop_resize(img, sw_ / 2, cy, cw_, ch_, CW, CH)
            e = ease_back(t / 0.42); sc = 0.9 + 0.1 * ease_out(t / 0.42)
            x_end = 75 if side == "L" else W - 75 - CW
            x = int(round((-CW - 120 if side == "L" else W + 120) * (1 - e) + x_end * e))
            if sc < 0.999:
                cwi, chi = int(CW * sc), int(CH * sc)
                card = np.asarray(Image.fromarray(card.astype(np.uint8)).resize((cwi, chi), Image.BILINEAR), np.float32)
                m = np.asarray(Image.fromarray((MASK[..., 0] * 255).astype(np.uint8)).resize((cwi, chi)), np.float32)[..., None] / 255
                shd = np.asarray(Image.fromarray((SHADOW[..., 0] * 255).astype(np.uint8)).resize((cwi + 2 * PAD, chi + 2 * PAD)), np.float32)[..., None] / 255
                x += (CW - cwi) // 2; y = CY + (CH - chi) // 2
            else: m, shd, y = MASK, SHADOW, CY
            paste(o, None, shd, x - PAD + 14, y - PAD + 22); paste(o, card, m, x, y)
            ta = ease_out((t - 0.15) / 0.3)                       # 文字延迟 0.15 秒上浮淡入
            if ta > 0:
                rgb, al = tl; dy = int(28 * (1 - ta))
                if dy: rgb = np.roll(rgb, dy, 0); al = np.roll(al, dy, 0)
                o = o * (1 - al * ta) + rgb * al * ta
        if "f" in flag:
            fl = 0.9 * np.exp(-t / 0.09)
            if fl > 0.01: o = o + (255 - o) * fl
        out.write(np.clip(o, 0, 255).astype(np.uint8).tobytes())


def render_title(n, out, lines):
    base = Image.new("RGB", (W, H), "black"); d = ImageDraw.Draw(base)
    for txt, role, size, y, col in lines:
        if not txt: continue
        f = font(role, size); w = d.textlength(txt, font=f); d.text(((W - w) / 2, y), txt, font=f, fill=col)
    arr = np.asarray(base, np.float32)
    for i in range(n):
        t = i / FPS; a = ease_out((t - 0.2) / 0.7) * (1 - ease_out((t - (n / FPS - 0.5)) / 0.5))
        out.write((arr * a).astype(np.uint8).tobytes())


def render_route(n, out, words, date):
    """路线片头：每 2 拍蹦出一个地名（硬切，卡在鼓点上），第 4 拍淡入日期"""
    beat = BAR / 4; fb = font("cn_bold", 84); fs = font("serif_italic", 36)
    for i in range(n):
        t = i / FPS; img = Image.new("RGB", (W, H), "black"); d = ImageDraw.Draw(img)
        txt = "  →  ".join(words[:min(len(words), int(t / (beat * 2)) + 1)]); w = d.textlength(txt, font=fb)
        d.text(((W - w) / 2, H / 2 - 80), txt, font=fb, fill="white")
        if date and t > beat * 4:
            al = int(255 * ease_out((t - beat * 4) / 0.5)); w2 = d.textlength(date, font=fs)
            d.text(((W - w2) / 2, H / 2 + 40), date, font=fs, fill=(al, al, al))
        out.write(np.asarray(img).tobytes())


class Pipe:
    """--preview 用：把一个镜头的若干帧收下来存成图"""
    def __init__(self): self.buf = []
    def write(self, b): self.buf.append(b)


if "--preview" in sys.argv:
    k = int(arg("--preview", 1)); typ, f0, f1, s = EV[k]; p = Pipe(); render_shot(s, f1 - f0, p)
    pick = [p.buf[min(len(p.buf) - 1, j)] for j in (3, 12, len(p.buf) // 2)]
    im = Image.new("RGB", (W * 3 // 2, H // 2))
    for j, b in enumerate(pick): im.paste(Image.frombuffer("RGB", (W, H), b).resize((W // 2, H // 2)), (j * W // 2, 0))
    out = D["edit"] / f"_preview_{k}.jpg"; im.save(out, quality=85); print(out); sys.exit()

# ---------- 音频：配乐 + 指定镜头的原声 ----------
N = int(TOTAL / FPS * SR)
mf = arg("--music", "")
if mf:
    raw = subprocess.run([FF, "-v", "error", "-ss", str(arg("--music-offset", 0.0)), "-i", mf, "-ac", "2", "-ar", str(SR),
                          "-f", "f32le", "-"], capture_output=True).stdout
    bgm = np.frombuffer(raw, np.float32).reshape(-1, 2)[:N].copy()
    if len(bgm) < N: bgm = np.vstack([bgm, np.zeros((N - len(bgm), 2), np.float32)])
    fo = int(2 * SR); bgm[-fo:] *= np.linspace(1, 0, fo)[:, None]
else:
    print("合成配乐 …", flush=True)
    bgm, secs = music.make_montage(TOTAL_BARS, key=int(arg("--key", 0)), bpm=BPM, outro=END)
    bgm = bgm[:N]
voc = np.zeros_like(bgm); g = np.ones(len(bgm), np.float32)
for typ, f0, f1, s in EV:
    if typ != "shot" or "v" not in s[6]: continue
    raw = subprocess.run([FF, "-v", "error", "-ss", f"{s[1]:.3f}", "-t", f"{(f1 - f0) / FPS:.3f}", "-i", str(D["proxy"] / f"{s[0]}.mp4"),
                          "-ac", "2", "-ar", str(SR), "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).reshape(-1, 2).copy()
    if not len(x): continue
    x *= min(8.0, 0.22 / np.sqrt(np.percentile(x.mean(1) ** 2, 95) + 1e-9))
    k = min(len(x) // 3, int(0.04 * SR)); w = np.linspace(0, 1, k)[:, None]; x[:k] *= w; x[-k:] *= w[::-1]
    i0 = int(f0 / FPS * SR); voc[i0:i0 + len(x)] += x[: len(voc) - i0]
    g[i0:int(f1 / FPS * SR)] = 0.3                                # 有原声的镜头：音乐固定压到 30%
k = int(0.15 * SR); g = C.box(np.pad(g, k, mode="edge"), k)[k:-k]
mix = (np.tanh((bgm * g[:, None] + voc) * 1.05) / 1.05).astype(np.float32)
af = D["edit"] / "_montage_mix.f32"; af.write_bytes(mix.tobytes())

# ---------- 逐帧合成 → 编码 ----------
t0 = time.time(); out = D["out"] / OUT
enc = subprocess.Popen([FF, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                        "-f", "f32le", "-ar", str(SR), "-ac", "2", "-i", str(af), *C.video_encoder(), "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "256k", "-shortest", "-movflags", "+faststart", str(out)], stdin=subprocess.PIPE)
for k, (typ, f0, f1, s) in enumerate(EV):
    if typ == "intro":
        if cfg.get("route"): render_route(f1 - f0, enc.stdin, cfg["route"], cfg.get("date", ""))
        else: render_title(f1 - f0, enc.stdin, [(cfg["title"], "hand", 170, 330, "white"), (cfg["subtitle"], "cn", 44, 590, (200, 200, 200))])
    elif typ == "end":
        if cfg["end_text"] and cfg["title"]:
            render_title(f1 - f0, enc.stdin, [(cfg["title"], "hand", 150, 330, "white"), (cfg["end_text"], "hand", 104, 560, "white")])
        else: render_title(f1 - f0, enc.stdin, [(cfg["end_text"] or cfg["title"], "hand", 140, 360, "white")])
    else: render_shot(s, f1 - f0, enc.stdin)
    print(f"\r{k + 1}/{len(EV)}  {time.time() - t0:.0f}s", end="", flush=True)
enc.stdin.close(); enc.wait(); af.unlink()
print(f"\n完成 {out}  {TOTAL / FPS:.1f}s")
