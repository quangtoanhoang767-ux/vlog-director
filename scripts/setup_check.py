"""环境检查 + 生成项目配置模板。
用法: python setup_check.py --project <工作目录> [--source <原片目录>]
检查：Python 依赖、ffmpeg、视频编码器、N 卡（语音转写用）、硬盘空间、字体。不改动原片。"""
import importlib, json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as C

pdir = C.project_dir(); pdir.mkdir(parents=True, exist_ok=True)
cfg_path = pdir / "project.json"
if not cfg_path.exists():
    tpl = dict(C.DEFAULT_CONFIG)
    if "--source" in sys.argv: tpl["source_dir"] = str(Path(sys.argv[sys.argv.index("--source") + 1]).resolve())
    cfg_path.write_text(json.dumps(tpl, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已生成配置模板：{cfg_path}")

ok = True
def line(good, text):
    global ok
    ok &= good
    print(("  [OK] " if good else "  [!!] ") + text)

print("== Python 依赖")
for mod, pip in (("numpy", "numpy"), ("PIL", "pillow"), ("faster_whisper", "faster-whisper")):
    try: importlib.import_module(mod); line(True, pip)
    except ImportError: line(False, f"{pip} 没装：pip install {pip}")

print("== ffmpeg")
try:
    ff = C.ffmpeg(); line(True, ff)
    enc = C.video_encoder()[1]
    line(True, f"视频编码器：{enc}" + ("（CPU 编码，会慢一些）" if enc == "libx264" else "（硬件编码）"))
except SystemExit as e:
    line(False, str(e))

print("== 显卡（语音转写）")
smi = shutil.which("nvidia-smi")
if smi:
    out = subprocess.run([smi, "--query-gpu=name,memory.total", "--format=csv,noheader"], capture_output=True, text=True).stdout.strip()
    line(True, f"N 卡：{out}。转写用 large-v3 模型（最准）")
    if sys.platform == "win32":
        for mod, pip in (("nvidia.cublas", "nvidia-cublas-cu12"), ("nvidia.cudnn", "nvidia-cudnn-cu12")):
            try: importlib.import_module(mod)
            except ImportError: line(False, f"Windows 上 GPU 转写还需要：pip install {pip}")
else:
    print("  [--] 没检测到 N 卡：转写会用 CPU 和较小的模型，1 小时素材大约要 1 小时，准确率略低")

cfg = C.load_config(pdir)
print("== 素材")
src = Path(cfg["source_dir"]) if cfg["source_dir"] else None
if not src or not src.is_dir():
    line(False, f"project.json 里的 source_dir 还没填或不存在：{cfg['source_dir'] or '（空）'}")
else:
    files = C.sources(cfg)
    total = sum(p.stat().st_size for p in files)
    proxies = sum(1 for p in files if any(p.with_suffix(s).exists() or p.with_suffix(s.upper()).exists() for s in C.PROXY_EXT))
    line(bool(files), f"{len(files)} 个视频，{total / 1e9:.1f} GB；其中 {proxies} 个带相机自带的低清预览（可直接当代理）")
    free = shutil.disk_usage(pdir).free
    need = (len(files) - proxies) * 0.2e9 + 3e9          # 粗估：转代理每个约 0.2 GB + 缓存
    line(free > need, f"工作目录剩余 {free / 1e9:.0f} GB（估计需要 {need / 1e9:.0f} GB）")

print("== 字体")
for role in ("cn", "cn_bold", "latin_black", "serif_italic", "hand", "symbol"):
    try: line(True, f"{role}: {C.font_path(cfg, role)}")
    except SystemExit as e: line(False, str(e))
print("\n全部就绪" if ok else "\n有 [!!] 的项需要先处理")
