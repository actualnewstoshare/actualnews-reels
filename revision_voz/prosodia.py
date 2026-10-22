"""Ritmo, pausas y entonación de la voz (prueba gratuita de la semana, 22/10/2026).
Uso: python3 prosodia.py <guion.py> [...]  -> sintetiza con el pvoice de producción (como la rutina) y mide cada frase:
sílabas por segundo, variación de tono (desviación en semitonos) y pausas internas largas."""
import sys, os, re, shutil, json, numpy as np, librosa
sys.path.insert(0, "/home/claude/work"); sys.path.insert(0, "/home/claude/tts")
import pvoice
pvoice.USE_ASR = False
def silabas(t):
    t = re.sub(r"[^a-záéíóúüñ ]", " ", t.lower()); n = 0
    for w in t.split(): n += max(1, len(re.findall(r"[aeiouáéíóúü]+", w)) + len(re.findall(r"[aeo][aeo]|[aeo][áéó]|[áéó][aeo]|[íú][aeo]|[aeo][íú]", w)))
    return n
res = []
for py in sys.argv[1:]:
    cid = os.path.basename(py)[:-3]; shutil.copy(py, f"/home/claude/work/{cid}.py")
    pvoice.main(cid, 1.06, 8)
    for txt, a in pvoice.SEGS:
        sr = pvoice.SR; dur = len(a) / sr
        rms = librosa.feature.rms(y=a, frame_length=512, hop_length=128)[0]; sil = rms < 0.02 * rms.max()
        # pausas internas > 0,18 s (no al principio ni al final)
        runs = []; c = 0
        for v in sil[5:-5]:
            if v: c += 1
            else:
                if c * 128 / sr > 0.18: runs.append(c * 128 / sr)
                c = 0
        f0, vf, _ = librosa.pyin(a, fmin=70, fmax=300, sr=sr, frame_length=1024)
        f0 = f0[~np.isnan(f0)]; st = float(np.std(12 * np.log2(f0 / np.median(f0)))) if len(f0) > 10 else 0.0
        hab = dur - sum(runs); r = silabas(txt) / max(hab, 0.1)
        res.append(dict(short=cid, frase=txt, sps=round(r, 2), tono_st=round(st, 2), pausas=len(runs), dur=round(dur, 2)))
json.dump(res, open("prosodia.json", "w"), ensure_ascii=False, indent=0)
sps = [x["sps"] for x in res]; st = [x["tono_st"] for x in res]
print(f"frases {len(res)} | sílabas/s media {np.mean(sps):.2f} (p10 {np.percentile(sps,10):.2f}, p90 {np.percentile(sps,90):.2f}) | tono {np.mean(st):.2f} st")
for x in res:
    flags = []
    if x["sps"] > 7.2: flags.append("rápida")
    if x["sps"] < 4.2: flags.append("lenta")
    if x["tono_st"] < 1.3: flags.append("plana")
    if x["pausas"]: flags.append(f"{x['pausas']} pausa(s) dentro")
    if flags: print(f"  {x['short']}: {', '.join(flags)} | {x['sps']} síl/s, {x['tono_st']} st | {x['frase']}")
