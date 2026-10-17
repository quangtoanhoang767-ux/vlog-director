"""语音转写 + 响度曲线：每个片段一个 JSON（每句话的起止时间、文字、置信度；每 0.5 秒一个音量值）。
已转过的自动跳过，可断点续跑。
用法:
  python transcribe.py --project <工作目录>                 全部转写
  python transcribe.py --project <目录> --recheck <片段ID> <开始秒> <结束秒> [语言]
        不带提示词重新听一段，用来核实关键台词（见 references/pitfalls.md 第 1 条）"""
import json, os, site, subprocess, sys, time
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
import common as C

cfg = C.load_config(); D = C.dirs(cfg); FF = C.ffmpeg()
os.environ.setdefault("HF_HOME", str(cfg["_dir"] / ".models"))
for sp in site.getsitepackages():          # Windows：让 ctranslate2 找到 pip 装的 cuBLAS/cuDNN
    for sub in ("nvidia/cublas/bin", "nvidia/cudnn/bin"):
        p = Path(sp) / sub
        if p.exists() and hasattr(os, "add_dll_directory"):
            os.add_dll_directory(str(p)); os.environ["PATH"] = str(p) + os.pathsep + os.environ["PATH"]
from faster_whisper import WhisperModel


def model():
    gpu = False
    try:
        import ctranslate2; gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception: pass
    name = cfg["whisper_model"] if cfg["whisper_model"] != "auto" else ("large-v3" if gpu else "small")
    print(f"Whisper {name} on {'GPU' if gpu else 'CPU'}", flush=True)
    return WhisperModel(name, device="cuda" if gpu else "cpu", compute_type="float16" if gpu else "int8")


def load_audio(path, a=None, b=None):
    cmd = [FF, "-v", "error"] + (["-ss", str(a), "-to", str(b)] if a is not None else []) + \
          ["-i", str(path), "-map", "0:a:0?", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"]
    raw = subprocess.run(cmd, capture_output=True).stdout
    return np.frombuffer(raw, np.int16).astype(np.float32) / 32768.0


def loudness(a, hop=8000):
    n = len(a) // hop
    if n == 0: return []
    r = np.sqrt((a[:n * hop].reshape(n, hop) ** 2).mean(1) + 1e-10)
    return [round(float(x), 1) for x in 20 * np.log10(r)]


if "--recheck" in sys.argv:
    k = sys.argv.index("--recheck"); fid, a, b = sys.argv[k + 1], float(sys.argv[k + 2]), float(sys.argv[k + 3])
    langs = [sys.argv[k + 4]] if len(sys.argv) > k + 4 and not sys.argv[k + 4].startswith("--") else [None, cfg["language"], "en"]
    audio = load_audio(D["proxy"] / f"{fid}.mp4", a, b); m = model()
    for lang in langs:      # 不带提示词：模型不会被「中文」暗示带偏，外语会按原样听写
        segs, info = m.transcribe(audio, language=lang, beam_size=5, condition_on_previous_text=False)
        print(f"== 指定语言 {lang} → 识别为 {info.language} ({info.language_probability:.2f})")
        for s in segs: print(f"  {a + s.start:7.1f}  {s.text.strip()}")
    sys.exit()

files = sorted(D["proxy"].glob("*.mp4"))
if cfg.get("include"): files = [f for f in files if any(k in f.name for k in cfg["include"])]
todo = [f for f in files if not (D["transcripts"] / f"{f.stem}.json").exists()]
print(f"{len(files)} 个代理，待转写 {len(todo)} 个", flush=True)
m = model() if todo else None
for i, f in enumerate(todo, 1):
    t0 = time.time(); audio = load_audio(f); dur = len(audio) / 16000; out = []
    if dur > 1:
        segs, info = m.transcribe(audio, beam_size=5, vad_filter=True, initial_prompt=cfg["transcribe_prompt"] or None,
                                  language=None, condition_on_previous_text=False,
                                  vad_parameters={"min_silence_duration_ms": 500})
        for s in segs:
            out.append({"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip(),
                        "no_speech": round(s.no_speech_prob, 3), "logprob": round(s.avg_logprob, 3)})
    rec = {"file": f.stem, "duration": round(dur, 2), "segments": out, "loudness_db_0.5s": loudness(audio)}
    (D["transcripts"] / f"{f.stem}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    print(f"[{i}/{len(todo)}] {f.stem}  {dur:.0f}s → {len(out)} 句  ({time.time() - t0:.0f}s)", flush=True)
print("DONE")
