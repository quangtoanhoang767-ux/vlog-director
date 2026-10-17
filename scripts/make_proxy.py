"""生成代理（低清工作副本）：优先直接复制相机自带的预览文件（大疆 .LRF、GoPro/Insta360 .LRV），
没有就用 ffmpeg 转一份 720p。原片只读。可断点续跑。
用法: python make_proxy.py --project <工作目录>"""
import json, shutil, subprocess, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg); FF = C.ffmpeg()
log = []
files = C.sources(cfg)
for i, src in enumerate(files, 1):
    dst = D["proxy"] / f"{src.stem}.mp4"
    if dst.exists() and dst.stat().st_size > 0:
        continue
    tmp = dst.with_suffix(".part")
    cam = next((src.with_suffix(e) for e in (".LRF", ".lrf", ".LRV", ".lrv") if src.with_suffix(e).exists()), None)
    how = "camera"
    if cam is not None:
        shutil.copyfile(cam, tmp)
        w, h, dur, _, has_a = C.probe(tmp)
        if w == 0 or dur == 0 or C.probe(src)[4] and not has_a:      # 预览文件坏了或没声音：改用转码
            tmp.unlink(); cam = None
    if cam is None:
        how = "ffmpeg"
        # 4K/10-bit 原片用 CPU 解码很慢：有硬件就用硬件解码 + 硬件编码，失败再退回纯 CPU
        enc = C.video_encoder()
        base = ["-map", "0:v:0", "-map", "0:a:0?", "-vf", "scale=-2:720,format=yuv420p", "-r", "25",
                "-c:a", "aac", "-b:a", "160k", "-f", "mp4", str(tmp)]
        r = subprocess.run([FF, "-v", "error", "-y", "-hwaccel", "auto", "-i", str(src), *enc, *base])
        if r.returncode != 0:
            subprocess.run([FF, "-v", "error", "-y", "-i", str(src), "-c:v", "libx264", "-preset", "veryfast",
                            "-crf", "23", *base], check=True)
    tmp.replace(dst)
    log.append({"file": src.stem, "proxy": how})
    print(f"[{i}/{len(files)}] {how:6s} {src.name}", flush=True)
(D["proxy"] / "_proxy_log.json").write_text(json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
print("DONE", len(files), "个代理就绪")
