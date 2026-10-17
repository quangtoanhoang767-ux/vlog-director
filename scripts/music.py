"""程序合成的无版权配乐（用户没有指定音乐时用）。
  python music.py --project <目录> vlog [--bpm 124] [--key 0]
        长片用：三条等长、节拍对齐的 8 小节循环 verse / chorus / light（大调、轻快），
        存到 edit/music/vlog_*.npy，并各出一个试听 wav。
  python music.py --project <目录> montage --bars 70 [--drop 20] [--key 0] [--bpm 140]
        混剪用：一整首电子乐（小调、侧链泵感），段落按小节数自动排。montage.py 会直接调用 make_montage()。
--key 是移调半音数（-5～+6），给不同的片子换个调，听起来就不是同一首。"""
import sys, wave
from pathlib import Path
import numpy as np

SR = 48000
rng = np.random.default_rng(7)
def hz(m): return 440 * 2 ** ((m - 69) / 12)
def env(n, a, d, s=0.0):
    t = np.arange(n) / SR
    return np.minimum(1, t / max(a, 1e-4)) * (s + (1 - s) * np.exp(-t / d))
def place(buf, sig, t, g=1.0, pan=0.0):
    i = int(round(t * SR))
    if i < 0 or i >= len(buf): return
    sig = sig[: len(buf) - i]
    if sig.ndim == 1:
        buf[i:i + len(sig), 0] += sig * g * np.sqrt(0.5 * (1 - pan)); buf[i:i + len(sig), 1] += sig * g * np.sqrt(0.5 * (1 + pan))
    else: buf[i:i + len(sig)] += sig * g

# ---------- 打击乐 ----------
def kick(punch=1.5):
    n = int(0.4 * SR); t = np.arange(n) / SR
    x = np.sin(2 * np.pi * np.cumsum(45 + 140 * np.exp(-t / 0.025)) / SR) * np.exp(-t / 0.18)
    return np.tanh(x * punch)
def clap():
    n = int(0.3 * SR); t = np.arange(n) / SR
    x = rng.standard_normal(n); x = x - np.convolve(x, np.ones(30) / 30, "same")
    e = sum(np.exp(-np.maximum(t - d, 0) / 0.008) * (t >= d) for d in (0, 0.01, 0.02)) * 0.4 + np.exp(-t / 0.09) * (t >= 0.02)
    return x * e * 0.8
def hat(open_=False):
    n = int((0.15 if open_ else 0.04) * SR); t = np.arange(n) / SR
    x = rng.standard_normal(n); x = x - np.convolve(x, np.ones(3) / 3, "same")
    return x * np.exp(-t / (0.05 if open_ else 0.012)) * 0.45
def shaker():
    n = int(0.08 * SR); t = np.arange(n) / SR
    x = rng.standard_normal(n); x = x - np.convolve(x, np.ones(3) / 3, "same")
    return x * np.sin(np.pi * t / t[-1]) * 0.25

# ---------- 音色 ----------
_KS = {}
def guitar(m, dur=0.9):
    """Karplus-Strong 拨弦（木吉他 / 尤克里里感）"""
    if (m, dur) in _KS: return _KS[(m, dur)]
    p = int(SR / hz(m)); n = int(dur * SR); buf = rng.uniform(-1, 1, p); out = np.empty(n)
    for i in range(n):
        out[i] = buf[i % p]; buf[i % p] = 0.996 * 0.5 * (out[i] + buf[(i + 1) % p])
    _KS[(m, dur)] = out * env(n, 0.002, dur * 0.6); return _KS[(m, dur)]
def saw(f, n, det=0.0):
    t = np.arange(n) / SR; return 2 * ((f * (1 + det) * t + rng.random()) % 1) - 1
def supersaw(notes, dur, bright=1.0):
    n = int(dur * SR); x = np.zeros((n, 2))
    for m in notes:
        for k, d in enumerate((-0.012, -0.007, -0.003, 0, 0.003, 0.007, 0.012)):
            s = saw(hz(m), n, d); pan = (k - 3) / 3 * 0.8
            x[:, 0] += s * np.sqrt(0.5 * (1 - pan)); x[:, 1] += s * np.sqrt(0.5 * (1 + pan))
    k = max(1, int((0.12 + 0.6 * (1 - bright)) * 20)); ker = np.ones(k) / k
    x = np.stack([np.convolve(x[:, 0], ker, "same"), np.convolve(x[:, 1], ker, "same")], 1)
    return x * env(n, 0.01, dur, 0.85)[:, None] / (len(notes) * 4)
def pluck(m, dur=0.35):
    n = int(dur * SR); t = np.arange(n) / SR; f = hz(m)
    x = np.sign(np.sin(2 * np.pi * f * t)) * 0.4 + np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)
    return np.convolve(x, np.ones(6) / 6, "same") * env(n, 0.002, 0.09)
def bass(m, dur, sustain=0.9):
    n = int(dur * SR); t = np.arange(n) / SR; f = hz(m)
    x = np.sin(2 * np.pi * f * t) + 0.25 * np.tanh(3 * np.sin(2 * np.pi * f * t))
    return x * env(n, 0.003, dur, sustain) * np.minimum(1, (n - np.arange(n)) / 300)
def lead(m, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    ph = np.cumsum(hz(m) * (1 + 0.006 * np.sin(2 * np.pi * 6 * t) * np.minimum(1, t / 0.2))) / SR
    x = np.sin(2 * np.pi * ph) + 0.5 * np.sin(4 * np.pi * ph) + 0.25 * np.sign(np.sin(2 * np.pi * ph))
    return x * env(n, 0.005, dur, 0.6) * np.minimum(1, (n - np.arange(n)) / 500)


def finish(x, n_fade_in=0.02):
    x[: int(n_fade_in * SR)] *= np.linspace(0, 1, int(n_fade_in * SR))[:, None]
    x = np.tanh(x * 1.3) / 1.3
    return (x / (np.abs(x).max() + 1e-9) * 0.9).astype(np.float32)


# ================= 长片：三条循环 =================
def make_loops(bpm=124, key=0):
    """G 大调 I-V-vi-IV，8 小节。verse=轻鼓扫弦，chorus=全编制加旋律，light=沙锤分解和弦"""
    beat = 60 / bpm; bar = 4 * beat; e8 = beat / 2; n = int(round(8 * bar * SR))
    chords = [[55, 59, 62, 67], [50, 54, 57, 62], [52, 55, 59, 64], [48, 52, 55, 60]] * 2
    roots = [43, 38, 40, 36] * 2
    mel = [[71, 74, 74, 76, 74, None, 71, 69], [69, 71, 69, 66, 69, None, None, None],
           [71, 74, 76, 79, 76, 74, 71, None], [72, 71, 69, 67, 69, None, None, None]] * 2
    out = {}
    for style in ("verse", "chorus", "light"):
        buf = np.zeros((n, 2))
        for b in range(8):
            t0 = b * bar; ch = [m + key for m in chords[b]]; r = roots[b] + key
            for q in range(4):
                tq = t0 + q * beat
                if style == "chorus" or (style == "verse" and q in (0, 2)): place(buf, kick(1.0), tq, 0.9 if style == "chorus" else 0.75)
                if style != "light" and q in (1, 3): place(buf, clap(), tq, 0.5, 0.05)
                if style == "chorus": place(buf, hat(True), tq + e8, 0.35, 0.3)
                if style == "verse": place(buf, hat(), tq, 0.3, 0.3); place(buf, hat(), tq + e8, 0.25, 0.3)
                if style == "light": place(buf, shaker(), tq, 0.6, 0.4); place(buf, shaker(), tq + e8, 0.45, 0.4)
            if style == "chorus":
                for e in range(8): place(buf, bass(r if e % 4 != 3 else r + 7, e8 * 0.9, 0.3), t0 + e * e8, 0.55)
            elif style == "verse":
                for q in range(4): place(buf, bass(r, beat * 0.8, 0.3), t0 + q * beat, 0.5)
            else: place(buf, bass(r, bar * 0.9, 0.3), t0, 0.35)
            if style != "light":
                for k, x in enumerate([0, 1, 1.5, 2.5, 3, 3.5] if style == "chorus" else [0, 1.5, 2, 3, 3.5]):
                    notes = ch[::-1] if k % 2 else ch
                    for j, m in enumerate(notes): place(buf, guitar(m + 12, 0.8), t0 + x * beat + j * 0.012, 0.2 if style == "chorus" else 0.17, -0.3 + 0.2 * j)
            else:
                for e, m in enumerate([ch[0], ch[1], ch[2], ch[3], ch[2], ch[1], ch[2], ch[3]]):
                    place(buf, guitar(m + 12, 1.1), t0 + e * e8, 0.32, -0.2 + 0.05 * e)
            if style == "chorus":
                for e, m in enumerate(mel[b]):
                    if m is None: continue
                    ln = 1
                    while e + ln < 8 and mel[b][e + ln] is None and ln < 3: ln += 1
                    place(buf, lead(m + key, e8 * ln * 0.95), t0 + e * e8, 0.2, 0.1)
        out[style] = finish(buf, 0.0)
    return out


# ================= 混剪：整首 =================
PROG = [[57, 60, 64], [53, 57, 60], [48, 52, 55], [55, 59, 62]]      # Am F C G
ROOT = [45, 41, 48, 43]
HOOK = [(0, 76, 2), (2, 79, 2), (4, 81, 3), (8, 79, 2), (10, 76, 2), (12, 74, 4),
        (16, 72, 2), (18, 74, 2), (20, 76, 3), (24, 79, 2), (26, 77, 2), (28, 76, 4),
        (32, 76, 2), (34, 79, 2), (36, 81, 3), (40, 84, 2), (42, 83, 2), (44, 81, 4),
        (48, 79, 2), (50, 81, 2), (52, 79, 2), (54, 76, 2), (56, 74, 4), (60, 76, 4)]


def montage_sections(total, drop=None, intro=2, outro=3):
    """自动排段落：intro → verse → build(2) → drop → [长片再回到 verse2 带旋律 → 第二次 drop] → outro(静音尾巴)"""
    end0 = total - outro
    drop = drop or min(max(intro + 6, round(total * 0.28)), end0 - 4)
    secs = [("intro", 0, intro), ("verse", intro, drop - 2), ("build", drop - 2, drop)]
    if end0 - drop > 30:                    # 够长：中间插一段喘气的 verse2，再来一次 drop
        mid = drop + (end0 - drop) // 2
        secs += [("drop", drop, mid - 4), ("verse2", mid - 4, mid + 6), ("drop", mid + 6, end0)]
    else:
        secs += [("drop", drop, end0)]
    secs += [("end", end0, total)]
    return [s for s in secs if s[2] > s[1]], drop


def make_montage(total_bars, drop=None, key=0, bpm=140, outro=3):
    beat = 60 / bpm; bar = 4 * beat; s16 = beat / 4
    n = int(round(total_bars * bar * SR)); nb = int(np.ceil(total_bars))
    secs, drop = montage_sections(total_bars, drop, outro=outro)
    def sec(b): return next((name for name, a, z in secs if a <= b < z), "end")
    prog = [[m + key for m in c] for c in PROG]; root = [r + key for r in ROOT]
    mus = np.zeros((n, 2)); drm = np.zeros((n, 2)); pump = np.ones(n)
    end0 = next(a for name, a, z in secs if name == "end")
    for b in range(nb):
        t0 = b * bar; st = sec(b); ch = prog[b % 4]; r = root[b % 4]; full = st == "drop"
        if st == "end":
            if b == int(np.ceil(end0)): place(mus, supersaw([m + 12 for m in prog[0]], (total_bars - end0) * bar, 0.2), t0, 0.5)
            continue
        for q in range(4):
            tq = t0 + q * beat
            if st in ("verse", "verse2", "drop", "build"):
                place(drm, kick(), tq, 0.95 if full else 0.75)
                i = int(tq * SR); w = min(int(0.22 * SR), n - i)
                if w > 0: pump[i:i + w] = np.minimum(pump[i:i + w], 1 - (0.75 if full else 0.45) * np.exp(-np.arange(w) / (0.06 * SR)))
            if st in ("verse", "verse2", "drop") and q in (1, 3): place(drm, clap(), tq, 0.6)
            if full: place(drm, hat(True), tq + beat / 2, 0.35, 0.3)
            if st in ("verse", "verse2"):
                for e in (0, 2): place(drm, hat(), tq + e * s16, 0.3, 0.3)
        if st == "build":
            k0 = (b - (drop - 2)) * 16
            for e in range(16):
                if e % (2 if k0 == 0 else 1) == 0: place(drm, clap(), t0 + e * s16, 0.25 + 0.4 * (k0 + e) / 32)
        if full: place(mus, supersaw([m + 12 for m in ch], bar * 0.98, 1.0), t0, 0.9)
        elif st in ("verse", "verse2"):
            for e in range(8):
                for m in ch: place(mus, pluck(m + 12 + (12 if e % 2 else 0), 0.3), t0 + e * beat / 2, 0.16, -0.3 + 0.2 * (e % 4))
        elif st == "build": place(mus, supersaw([m + 12 for m in ch], bar * 0.98, 0.3 + 0.35 * (b - drop + 2)), t0, 0.7)
        else: place(mus, supersaw([m + 12 for m in ch], bar * 0.98, 0.15), t0, 0.55)
        if full:
            for e in range(8): place(mus, bass(r - 12 + (12 if e % 2 else 0), beat / 2 * 0.9), t0 + e * beat / 2, 0.5)
        elif st in ("verse", "verse2", "build"):
            for q in range(4): place(mus, bass(r - 12, beat * 0.85), t0 + q * beat, 0.45)
        if full or st == "verse2":
            for pos, m, ln in HOOK:
                if pos // 16 == (b - drop) % 4: place(mus, lead(m + key, ln * s16 * 0.95), t0 + (pos % 16) * s16, 0.22 if full else 0.13, 0.1)
    m_ = int(2 * bar * SR); t = np.arange(m_) / SR                     # build 的上升噪声
    noise = rng.standard_normal(m_); place(mus, (noise - np.convolve(noise, np.ones(50) / 50, "same")) * (t / t[-1]) ** 2 * 0.35, (drop - 2) * bar)
    for name, a, z in secs:                                            # 每次 drop 和结尾的下落音
        if name in ("drop", "end"):
            m_ = int(1.2 * SR); t = np.arange(m_) / SR
            place(mus, np.sin(2 * np.pi * np.cumsum(120 * np.exp(-t / 0.3) + 40) / SR) * np.exp(-t / 0.5) * 0.7, a * bar)
    x = mus * pump[:, None] * 0.8 + drm * 0.7
    fe = int(end0 * bar * SR); x[fe:] *= np.exp(-np.arange(n - fe) / (1.6 * SR))[:, None]
    return finish(x), secs


def save_wav(path, x):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(x, -1, 1) * 32767).astype(np.int16).tobytes())


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent))
    import common as C
    cfg = C.load_config(); M = C.dirs(cfg)["music"]
    def arg(k, d): return type(d)(sys.argv[sys.argv.index(k) + 1]) if k in sys.argv else d
    if "vlog" in sys.argv:
        for st, x in make_loops(arg("--bpm", 124), arg("--key", 0)).items():
            np.save(M / f"vlog_{st}.npy", x); save_wav(M / f"vlog_{st}_试听.wav", np.tile(x, (2, 1)))
            print(st, f"{len(x) / SR:.2f}s")
    elif "montage" in sys.argv:
        x, secs = make_montage(arg("--bars", 70), arg("--drop", 0) or None, arg("--key", 0), arg("--bpm", 140))
        np.save(M / "montage.npy", x); save_wav(M / "montage_试听.wav", x)
        print(f"{len(x) / SR:.1f}s", secs)
    else: print(__doc__)
