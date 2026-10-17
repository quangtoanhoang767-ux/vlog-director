"""所有脚本共用：读项目配置、找 ffmpeg、选视频编码器、找字体。

项目配置是工作目录下的 project.json（setup_check.py 会生成模板）。
脚本都接受 --project <工作目录>，不给就用当前目录。
"""
import json, os, re, shutil, subprocess, sys
from functools import lru_cache
from pathlib import Path

# Windows 控制台默认 GBK，打印越南语/泰语等会崩；没有 stdout（pythonw）时也别崩
for _s in ("stdout", "stderr"):
    _f = getattr(sys, _s)
    if _f is None:
        setattr(sys, _s, open(os.devnull, "w", encoding="utf-8"))
    elif hasattr(_f, "reconfigure"):
        _f.reconfigure(encoding="utf-8", errors="replace")

SKILL_DIR = Path(__file__).resolve().parent.parent
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".mts", ".m2ts", ".insv"}
PROXY_EXT = {".lrf", ".lrv"}     # 大疆 LRF、GoPro/Insta360 LRV：相机自带的低清预览

DEFAULT_CONFIG = {
    "source_dir": "",                      # 原片目录（只读，脚本绝不写入）
    "include": [],                         # 只处理文件名含这些关键字的（测试用），空 = 全部
    "language": "zh",                      # 主要说话语言；混杂多国语言也写主语言
    "transcribe_prompt": "以下是几个朋友出去玩时的聊天，普通话，简体中文。",
    "whisper_model": "auto",               # auto：有 N 卡用 large-v3，否则 small
    "title": "",                           # 片名（混剪片头、片尾用）
    "subtitle": "",                        # 片头第二行，如路线或日期
    "end_text": "",                        # 片尾手写字，如「下次见」；和 title 都有时片尾两行：片名在上
    "route": [],                           # 混剪片头改成路线逐个蹦出，如 ["上海", "河内", "芽庄"]，每 2 拍出一个
    "date": "",                            # 配合 route，第 4 拍淡入的一行小字，如 "2026.9.26 — 10.3"
    "output": {"width": 1920, "height": 1080, "fps": 30},
    "crop_y": 0.42,                        # 方形/竖屏素材裁 16:9 时取景偏上的比例（人脸多在中上部）
    "fonts": {},                           # 可覆盖：cn / cn_bold / latin_black / serif_italic / hand / symbol
}


def project_dir(argv=None):
    argv = sys.argv if argv is None else argv
    if "--project" in argv:
        return Path(argv[argv.index("--project") + 1]).resolve()
    return Path.cwd().resolve()


def load_config(pdir=None):
    pdir = Path(pdir or project_dir())
    p = pdir / "project.json"
    if not p.exists():
        sys.exit(f"找不到 {p}。先运行 setup_check.py --project {pdir} 生成模板，填好 source_dir。")
    cfg = json.loads(p.read_text(encoding="utf-8"))
    out = json.loads(json.dumps(DEFAULT_CONFIG))
    for k, v in cfg.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict): out[k].update(v)
        else: out[k] = v
    out["_dir"] = pdir
    return out


def dirs(cfg):
    """工作目录的固定结构"""
    d = cfg["_dir"]
    res = {k: d / v for k, v in {
        "proxy": "proxy", "transcripts": "analysis/transcripts", "sheets": "analysis/sheets",
        "db": "analysis/db", "selects": "selects", "edit": "edit", "cache": "edit/_cache",
        "out": "output", "music": "edit/music", "fonts": "fonts"}.items()}
    for p in res.values(): p.mkdir(parents=True, exist_ok=True)
    return res


def sources(cfg):
    """原片列表（按文件名排序）。相机预览文件不算原片。"""
    src = Path(cfg["source_dir"])
    if not src.is_dir(): sys.exit(f"source_dir 不存在：{src}")
    files = sorted((p for p in src.rglob("*") if p.suffix.lower() in VIDEO_EXT and not p.name.startswith("._")),
                   key=lambda p: p.name)
    if cfg.get("include"):
        files = [p for p in files if any(k in p.name for k in cfg["include"])]
    return files


def source_map(cfg):
    """文件名主干（不含扩展名）→ 原片路径。整个项目用主干当片段 ID。"""
    return {p.stem: p for p in sources(cfg)}


# ---------- ffmpeg ----------
@lru_cache(None)
def ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe: return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("没有 ffmpeg。运行：pip install imageio-ffmpeg（或自己装 ffmpeg 并加入 PATH）")


def probe(path):
    """返回 (宽, 高, 时长秒, 是否带旋转标记, 是否有音轨)。用 ffmpeg -i 的输出解析，免装 ffprobe。"""
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="ignore").stderr
    m = re.search(r"Video:.*?, (\d{2,5})x(\d{2,5})", err)
    w, h = (int(m.group(1)), int(m.group(2))) if m else (0, 0)
    d = re.search(r"Duration: (\d+):(\d+):([\d.]+)", err)
    dur = int(d.group(1)) * 3600 + int(d.group(2)) * 60 + float(d.group(3)) if d else 0.0
    return w, h, dur, "rotation of" in err, "Audio:" in err


def rotation_angle(path):
    err = subprocess.run([ffmpeg(), "-hide_banner", "-i", str(path)], capture_output=True, text=True,
                         encoding="utf-8", errors="ignore").stderr
    m = re.search(r"rotation of (-?[\d.]+)", err)
    return round(float(m.group(1))) if m else 0


@lru_cache(None)
def video_encoder():
    """优先硬件编码：N 卡 nvenc → 苹果 videotoolbox → Intel qsv → CPU libx264"""
    for enc, args in (("h264_nvenc", ["-preset", "p5", "-cq", "20"]),
                      ("h264_videotoolbox", ["-q:v", "65"]),
                      ("h264_qsv", ["-global_quality", "21"])):
        r = subprocess.run([ffmpeg(), "-v", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
                            "-c:v", enc, "-f", "null", "-"], capture_output=True)
        if r.returncode == 0: return ["-c:v", enc, *args]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "19"]


def rotation_args(src, proxy=None):
    """少数相机会给原片写错的旋转标记（画面本来是正的）。代理没有标记、原片有，就以代理为准不旋转。"""
    if proxy is None or not Path(proxy).exists(): return []
    return ["-noautorotate"] if probe(src)[3] and not probe(proxy)[3] else []


# ---------- 字体 ----------
FONT_URLS = {   # 全部是 SIL Open Font License，可免费商用、可再分发
    "cn":           "https://github.com/google/fonts/raw/main/ofl/notosanssc/NotoSansSC%5Bwght%5D.ttf",
    "latin_black":  "https://github.com/google/fonts/raw/main/ofl/archivoblack/ArchivoBlack-Regular.ttf",
    "serif_italic": "https://github.com/google/fonts/raw/main/ofl/librebaskerville/LibreBaskerville-Italic.ttf",
    "hand":         "https://github.com/google/fonts/raw/main/ofl/longcang/LongCang-Regular.ttf",
    "symbol":       "https://github.com/google/fonts/raw/main/ofl/notosanssymbols2/NotoSansSymbols2-Regular.ttf",
}
SYSTEM_FONTS = {   # 有系统字体就先用系统的，省得下载
    "cn": ["C:/Windows/Fonts/msyh.ttc", "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"],
    "cn_bold": ["C:/Windows/Fonts/msyhbd.ttc", "/System/Library/Fonts/PingFang.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"],
    "latin_black": ["C:/Windows/Fonts/ariblk.ttf", "/System/Library/Fonts/Supplemental/Arial Black.ttf"],
    "serif_italic": ["C:/Windows/Fonts/georgiai.ttf", "/System/Library/Fonts/Supplemental/Georgia Italic.ttf"],
    "symbol": ["C:/Windows/Fonts/seguisym.ttf", "/System/Library/Fonts/Apple Symbols.ttf"],
}


def font_path(cfg, role, download=True):
    """按角色找字体：配置里指定的 > 工作目录 fonts/ 里下载好的 > 系统自带 > 现场下载开源字体"""
    if cfg.get("fonts", {}).get(role) and Path(cfg["fonts"][role]).exists():
        return cfg["fonts"][role]
    url_role = "cn" if role == "cn_bold" else role
    local = dirs(cfg)["fonts"] / Path(FONT_URLS.get(url_role, "x")).name.replace("%5B", "[").replace("%5D", "]")
    if url_role in FONT_URLS and local.exists(): return str(local)
    for p in SYSTEM_FONTS.get(role, []):
        if Path(p).exists(): return p
    if url_role in FONT_URLS and download:
        import urllib.request
        print(f"下载开源字体 {local.name} …", flush=True)
        urllib.request.urlretrieve(FONT_URLS[url_role], local)
        return str(local)
    sys.exit(f"找不到字体：{role}。在 project.json 的 fonts.{role} 里填一个字体文件路径。")


def load_font(cfg, role, size):
    from PIL import ImageFont
    f = ImageFont.truetype(font_path(cfg, role), size)
    if role == "cn_bold" and "wght" in Path(f.path).name:        # 思源黑体是可变字重，粗体要单独设置
        try: f.set_variation_by_name("Bold")
        except Exception: pass
    return f


# ---------- 小工具 ----------
def box(x, k):
    """长度 k 的居中移动平均（和 np.convolve(x, ones(k)/k, 'same') 一样，但用累积和，k 再大也是线性时间）"""
    import numpy as np
    k = max(1, int(k)); x = np.asarray(x, np.float64)
    c = np.concatenate([[0.0], np.cumsum(np.pad(x, (k // 2, k - 1 - k // 2), mode="constant"))])
    return ((c[k:] - c[:-k]) / k).astype(np.float32)



def tc(sec):
    m, s = divmod(max(0.0, float(sec)), 60)
    return f"{int(m):02d}:{s:05.2f}"


def parse_tc(t):
    """'mm:ss.xx' / 'hh:mm:ss' / 秒数 → 秒"""
    t = str(t).strip()
    if ":" not in t: return float(t)
    parts = [float(x) for x in t.split(":")]
    s = 0.0
    for p in parts: s = s * 60 + p
    return s
