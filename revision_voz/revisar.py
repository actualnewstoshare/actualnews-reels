"""Revisa Shorts publicados: Whisper sobre el audio real vs VOICE del guion. Uso: python3 revisar.py <dir_fecha> [...]"""
import sys, os, glob, re, subprocess, importlib.util, difflib, numpy as np
sys.path.insert(0, "/home/claude/tts"); sys.path.insert(0, "/home/claude/work")
import asr
from scipy.io import wavfile
def voice_of(py):
    spec = importlib.util.spec_from_file_location("g_" + os.path.basename(py)[:-3], py); m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m); return m.VOICE
def cortes(x, sr, L=22):
    env = np.convolve(np.abs(x), np.ones(int(.05 * sr)) / int(.05 * sr), "same"); pts = [0]
    while len(x) - pts[-1] > L * sr:
        a = pts[-1] + int((L - 6) * sr); b = pts[-1] + int(L * sr); pts.append(a + int(np.argmin(env[a:b])))
    return pts + [len(x)]
out = []
for d in sys.argv[1:]:
    for py in sorted(glob.glob(f"{d}/s*.py")):
        cid = os.path.basename(py)[:-3]; mp4s = glob.glob(f"{d}/*.mp4")
        try: V = voice_of(py)
        except Exception as e: print("sin VOICE", py, e); continue
        # mp4 del guion: el que comparte la hora (s0800 -> short_0800)
        h = re.sub(r"\D", "", cid.split("_")[0]); cand = [m for m in mp4s if f"_{h}_" in os.path.basename(m) or (cid.startswith("sem") and "semana_" in m)]
        if not cand: print("sin mp4", py); continue
        w = f"/tmp/rev_{cid}.wav"; subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", cand[0], "-ac", "1", "-ar", "16000", w], check=True)
        sr, x = wavfile.read(w); x = x.astype(np.float32); pts = cortes(x, sr); fs = []
        for i in range(len(pts) - 1):
            f = f"/tmp/rev_{cid}_{i}.wav"; wavfile.write(f, sr, x[pts[i]:pts[i + 1]].astype(np.int16)); fs.append(f)
        hyp = " ".join(asr.transcribe(fs)); [os.remove(f) for f in fs + [w]]
        a = asr.norm(V).split(); b = asr.norm(hyp).split()
        sm = difflib.SequenceMatcher(None, a, b); fallos = []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal": continue
            ctx = " ".join(a[max(0, i1 - 3):i1]); fallos.append(f"   [{op}] …{ctx} «{' '.join(a[i1:i2])}» → oído «{' '.join(b[j1:j2])}»")
        line = f"## {d.split('/')[-1]} {cid}: parecido {sm.ratio():.3f}, {len(fallos)} diferencias"
        print(line); out.append(line)
        for f in fallos: print(f); out.append(f)
open("/home/claude/lab/rev/informe.txt", "w").write("\n".join(out))
