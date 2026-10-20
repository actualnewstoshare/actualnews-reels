"""Nota de calidad de voz gratuita y local: DNSMOS (Microsoft, P.835/P.808). Uso: python3 dnsmos.py audio1 [audio2 ...]
SIG = limpieza y naturalidad de la voz, BAK = fondo (ruido, zumbidos), OVRL = global, P808 = nota global estilo encuesta. Escala 1–5."""
import sys, subprocess, numpy as np, librosa, onnxruntime as ort, os
D = os.path.dirname(os.path.abspath(__file__)) + "/dnsmos"; FS = 16000; L = 9.01
s1 = ort.InferenceSession(f"{D}/sig_bak_ovr.onnx", providers=["CPUExecutionProvider"]); s2 = ort.InferenceSession(f"{D}/model_v8.onnx", providers=["CPUExecutionProvider"])
P = (np.poly1d([-0.08397278, 1.22083953, 0.0052439]), np.poly1d([-0.13166888, 1.60915514, -0.39604546]), np.poly1d([-0.06766283, 1.11546468, 0.04602535]))
def load(f):
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", f, "-ac", "1", "-ar", str(FS), "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(r, np.float32).copy()
def nota(f):
    a = load(f); n = int(L * FS)
    while len(a) < n: a = np.append(a, a)
    out = []
    for i in range(int(np.floor(len(a) / FS) - L) + 1):
        seg = a[i * FS: i * FS + n]
        if len(seg) < n: continue
        sig, bak, ovr = s1.run(None, {"input_1": seg[None, :].astype(np.float32)})[0][0]
        mel = librosa.feature.melspectrogram(y=seg[:-160], sr=FS, n_fft=321, hop_length=160, n_mels=120)
        mel = ((librosa.power_to_db(mel, ref=np.max) + 40) / 40).T
        p808 = s2.run(None, {"input_1": mel[None].astype(np.float32)})[0][0][0]
        out.append((P[0](sig), P[1](bak), P[2](ovr), p808))
    return np.mean(out, 0)
if __name__ == "__main__":
    for f in sys.argv[1:]:
        s, b, o, p = nota(f); print(f"SIG {s:.2f}  BAK {b:.2f}  OVRL {o:.2f}  P808 {p:.2f}  {os.path.basename(f)}")
