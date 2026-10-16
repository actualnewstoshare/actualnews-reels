"""Motor de Shorts estilo telediario (basado en plantilla_shorts: build.py + news.py + music.py).
Uso: python3 engine.py <modulo_short> test|render|mux
"""
import sys, math, os, json, re, subprocess, importlib
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy.signal import butter, lfilter
from scipy.io import wavfile

W, H, FPS = 1080, 1920, 30
def _font(name, fallback):   # Poppins (setup.sh la instala en /usr/share o en /home/claude/work/fonts); si no está, DejaVu
    for d in ("/usr/share/fonts/truetype/google-fonts", "/home/claude/work/fonts"):
        if os.path.exists(f"{d}/{name}"): return f"{d}/{name}"
    print(f"AVISO: falta {name}; uso {fallback}"); return fallback
FB = _font("Poppins-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
FR = _font("Poppins-Regular.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
WORK = "/home/claude/work"; OUT = "/mnt/user-data/outputs"
WHITE = (255, 255, 255); RED = (255, 95, 95); GREEN = (110, 230, 150); BLUE = (120, 200, 255); ORANGE = (255, 150, 60)
YEL = (255, 214, 64); NAVY = (14, 20, 38); GREY = (150, 150, 165)
TAIL = 0.35  # sin cortinilla final: el último fotograma enlaza con el primero (bucle infinito)
TAIL_PUENTE = 0.10  # si el guion acaba en frase-puente sin punto («…por eso todos comentan que»), casi sin pausa: empalma con la primera frase
FOLLOW_AT = 0.45  # «SÍGUENOS» en la esquina, bajo el logo, a mitad del Short (fracción de la duración)
_fc = {}
def F(p, s):
    s = max(8, int(s))
    if (p, s) not in _fc: _fc[(p, s)] = ImageFont.truetype(p, s)
    return _fc[(p, s)]
def ease(x):
    x = max(0.0, min(1.0, x)); return 1 - (1 - x) ** 3
def wrap(txt, font, maxw):
    words = txt.split(); lines = []; cur = ""
    for w in words:
        t = (cur + " " + w).strip()
        if font.getlength(t) <= maxw: cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    return lines
def A(c, a): return tuple(c[:3]) + (int(max(0, min(255, a))),)

# ======================= visuals (área útil y≈640-1290) =======================
def v_title(d, tl, du, ac, label, sub, fs=150, **_):
    cx, cy = 540, 960; p = ease(tl / 0.5)
    for k in range(3):
        ph = ((tl * 0.55) + k / 3) % 1; r = 150 + ph * 240
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=A(ac, 200 * (1 - ph) * p), width=6)
    R = int(230 * p); d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(0, 0, 0, 175), outline=A(ac, 255), width=7)
    f = F(FB, fs * p)
    while f.getlength(label) > 400 and f.size > 20: f = F(FB, f.size - 6)
    if p > 0.2:
        d.text((cx, cy - 20), label, font=f, fill=A(WHITE, 255 * p), anchor="mm")
        d.text((cx, cy + 115 * p), sub, font=F(FB, 34 * p), fill=A(ac, 255 * p), anchor="mm")

def v_card(d, tl, du, ac, tag, text, note=None, **_):
    p = ease(tl / 0.45); off = (1 - p) * 400
    lines = wrap(text, F(FB, 60), 860); h = 150 + len(lines) * 76 + (70 if note else 0); y0 = 960 - h / 2 + off
    d.rounded_rectangle([60, y0, 1020, y0 + h], radius=30, fill=(0, 0, 0, int(170 * p)), outline=A(ac, 255 * p), width=4)
    tw = F(FB, 38).getlength(tag) + 50
    d.rounded_rectangle([100, y0 + 35, 100 + tw, y0 + 100], radius=30, fill=A(ac, 255 * p))
    d.text((125, y0 + 67), tag, font=F(FB, 38), fill=A(NAVY, 255 * p), anchor="lm")
    for j, l in enumerate(lines): d.text((100, y0 + 150 + j * 76), l, font=F(FB, 60), fill=A(WHITE, 255 * p), anchor="lm")
    if note:
        yy = y0 + 150 + len(lines) * 76 + 30; r = 13 + 5 * math.sin(tl * 5)
        d.ellipse([112 - r, yy - r, 112 + r, yy + r], fill=A(RED, 255 * p))
        d.text((150, yy), note, font=F(FR, 38), fill=A(WHITE, 255 * p), anchor="lm")

def v_quote(d, tl, du, ac, who, text, src, **_):
    p = ease(tl / 0.45)
    lines = wrap("«" + text + "»", F(FB, 62), 840); h = 170 + len(lines) * 80 + 60; y0 = 960 - h / 2
    d.rounded_rectangle([60, y0, 1020, y0 + h], radius=30, fill=(250, 250, 252, int(240 * p)))
    d.rectangle([60, y0 + 30, 72, y0 + h - 30], fill=A(ac, 255 * p))
    d.text((110, y0 + 60), who, font=F(FB, 42), fill=A(NAVY, 255 * p), anchor="lm")
    d.text((110, y0 + 108), src, font=F(FR, 32), fill=A((90, 95, 110), 255 * p), anchor="lm")
    n = sum(len(l) for l in lines); shown = int(n * ease((tl - 0.3) / 1.6)); c = 0
    for j, l in enumerate(lines):
        part = l[:max(0, shown - c)]; c += len(l)
        d.text((110, y0 + 190 + j * 80), part, font=F(FB, 62), fill=A(NAVY, 255 * p), anchor="lm")

def v_versus(d, tl, du, ac, left, right, **_):
    for k, (tag, big, txt, col) in enumerate([left, right]):
        p = ease((tl - 0.15 - 0.3 * k) / 0.5); off = (1 - p) * (-420 if k == 0 else 420); x = 60 if k == 0 else 580
        d.rounded_rectangle([x + off, 720, x + 440 + off, 1200], radius=30, fill=(0, 0, 0, int(170 * p)), outline=A(col, 255 * p), width=4)
        d.text((x + off + 220, 785), tag, font=F(FB, 40), fill=A(col, 255 * p), anchor="mm")
        if big:
            f = F(FB, 120)
            while f.getlength(big) > 400: f = F(FB, f.size - 6)
            d.text((x + off + 220, 920), big, font=f, fill=A(WHITE, 255 * p), anchor="mm")
        for j, l in enumerate(wrap(txt, F(FB, 42), 390)):
            d.text((x + off + 220, (1030 if big else 880) + j * 56), l, font=F(FB, 42), fill=A(WHITE, 255 * p), anchor="mm")
    q = ease((tl - 0.8) / 0.4)
    if q > 0:
        r = int(58 * q); d.ellipse([540 - r, 960 - r, 540 + r, 960 + r], fill=A(WHITE, 255)); d.text((540, 960), "VS", font=F(FB, 46 * q + 2), fill=(10, 10, 10, 255), anchor="mm")

def v_bars(d, tl, du, ac, items, maxv, t0=0.2, step=0.35, unit="%", note=None, **_):
    n = len(items); bh = 92; gap = 40; y0 = 960 - (n * bh + (n - 1) * gap) / 2 - (30 if note else 0)
    for i, it in enumerate(items):
        name, val, col = it[:3]; sub = it[3] if len(it) > 3 else None
        y = y0 + i * (bh + gap); p = ease((tl - t0 - step * i) / 0.9)
        d.text((70, y + bh / 2), name, font=F(FB, 46), fill=A(WHITE, 255), anchor="lm")
        x0, x1 = 270, 870; d.rounded_rectangle([x0, y, x1, y + bh], radius=20, fill=(255, 255, 255, 35))
        if p > 0:
            d.rounded_rectangle([x0, y, x0 + max(40, (x1 - x0) * val / maxv * p), y + bh], radius=20, fill=A(col, 255))
        s = f"{val * p:.1f}".replace(".", ",") + unit
        d.text((1015, y + bh / 2), s, font=F(FB, 50), fill=A(col, 255), anchor="rm")
        if sub and p > 0.9: d.text((x0 + 20, y + bh / 2), sub, font=F(FB, 34), fill=A(NAVY, 255 * ease((p - 0.9) / 0.1)), anchor="lm")
    if note and tl >= note[1]:
        q = ease((tl - note[1]) / 0.4); yy = y0 + n * (bh + gap) + 10
        d.rounded_rectangle([90, yy, 990, yy + 80], radius=22, fill=(0, 0, 0, int(190 * q)), outline=A(ac, 255 * q), width=3)
        d.text((540, yy + 40), note[0], font=F(FB, 38), fill=A(WHITE, 255 * q), anchor="mm")

def v_fromto(d, tl, du, ac, a_lab, a_val, b_lab, b_val, col, foot=None, **_):
    p = ease(tl / 0.5)
    d.text((250, 790), a_lab, font=F(FB, 40), fill=A(GREY, 255 * p), anchor="mm")
    d.text((250, 930), a_val, font=F(FB, 170), fill=A(WHITE, 200 * p), anchor="mm")
    q = ease((tl - 0.6) / 0.6)
    if q > 0:
        x = 410 + 100 * q; d.line([410, 930, x, 930], fill=A(col, 255), width=14)
        d.polygon([(x + 30, 930), (x - 10, 900), (x - 10, 960)], fill=A(col, 255))
    r = ease((tl - 1.0) / 0.5)
    if r > 0:
        d.text((800, 790), b_lab, font=F(FB, 40), fill=A(col, 255 * r), anchor="mm")
        f = F(FB, 150 + 30 * (1 - r))
        while f.getlength(b_val) > 420: f = F(FB, f.size - 6)
        d.text((800, 930), b_val, font=f, fill=A(col, 255 * r), anchor="mm")
    if foot and tl > 1.4:
        s = ease((tl - 1.4) / 0.4); d.rounded_rectangle([140, 1080, 940, 1170], radius=45, fill=A(col, 235 * s))
        d.text((540, 1125), foot, font=F(FB, 44), fill=A(NAVY, 255 * s), anchor="mm")

def hemi_positions(n, rows, R0, R1, cx, cy):
    radii = [R0 + (R1 - R0) * k / (rows - 1) for k in range(rows)]
    tot = sum(radii); counts = [max(1, round(n * r / tot)) for r in radii]; counts[-1] += n - sum(counts)
    pts = []
    for r, c in zip(radii, counts):
        for j in range(c):
            a = math.pi * (1 - j / (c - 1)) if c > 1 else math.pi / 2
            pts.append((a, cx + r * math.cos(a), cy - r * math.sin(a)))
    pts.sort(key=lambda p: -round(p[0], 3)); return pts
_HP = {}
def v_hemi(d, tl, du, ac, n, rows, groups, r0, reveal, dot, R0=200, R1=440, cy=1130, big=None, majority=None, **_):
    key = (n, rows, R0, R1, cy)
    if key not in _HP: _HP[key] = hemi_positions(n, rows, R0, R1, 540, cy)
    pts = _HP[key]; col_of = []
    for gi, (c, col, _) in enumerate(groups): col_of += [gi] * c
    cnt = [0] * len(groups)
    for i, (_, x, y) in enumerate(pts):
        ti = r0 + i / n * reveal; g = col_of[i] if i < len(col_of) else len(groups) - 1
        if tl >= ti:
            cnt[g] += 1; s = 0.55 + 0.45 * ease((tl - ti) / 0.25); rr = dot * s
            d.ellipse([x - rr, y - rr, x + rr, y + rr], fill=A(groups[g][1], 255))
        else: d.ellipse([x - dot * .5, y - dot * .5, x + dot * .5, y + dot * .5], fill=(255, 255, 255, 45))
    d.rectangle([60, cy + 18, 1020, cy + 22], fill=(255, 255, 255, 60))
    if majority:  # marca de mayoría absoluta (176) en el arco
        m, t = majority; q = ease((tl - t) / 0.4)
        if q > 0:
            a = math.pi * (1 - m / n); x0, y0 = 540 + (R0 - 40) * math.cos(a), cy - (R0 - 40) * math.sin(a); x1, y1 = 540 + (R1 + 45) * math.cos(a), cy - (R1 + 45) * math.sin(a)
            d.line([x0, y0, x1, y1], fill=A(YEL, 255 * q), width=6)
            d.text((x1, y1 - 30), f"Mayoría: {m}", font=F(FB, 36), fill=A(YEL, 255 * q), anchor="mm")
    if big:
        val, lab = big; tot = sum(cnt[:2])
        d.text((540, cy + 85), str(tot), font=F(FB, 100), fill=A(WHITE, 255), anchor="mm")
        d.text((540, cy + 150), lab, font=F(FR, 32), fill=A(WHITE, 230), anchor="mm")

# --- mapa esquemático del Golfo (de news.py) ---
PX0, PY0, PX1, PY1 = 60, 650, 1020, 1270
LAT = lambda la: PY0 + (30.5 - la) * 40
LON = lambda lo: PX0 + (lo - 40) * 40
WATER = [
 [(54.0,16.0),(54.1,17.0),(55.5,17.8),(56.8,18.6),(57.8,19.2),(58.6,20.4),(59.6,21.6),(59.8,22.5),(58.6,23.6),(57.4,23.9),(56.7,24.4),
  (56.35,25.1),(56.45,26.0),(56.35,26.4),(56.15,26.2),(56.0,25.8),(55.3,25.3),(54.4,24.5),(53.0,24.1),(52.0,24.0),(51.6,24.3),(51.6,25.3),
  (51.3,26.1),(50.9,25.6),(50.8,24.8),(50.5,25.6),(50.1,26.4),(49.6,27.0),(48.9,27.7),(48.4,28.4),(48.0,29.3),(48.4,29.9),(48.9,30.2),
  (49.5,30.0),(50.2,29.2),(50.8,28.9),(51.4,27.9),(52.6,27.4),(53.6,26.8),(54.8,26.5),(55.6,26.7),(56.3,27.2),(57.0,26.8),(57.3,25.8),
  (57.8,25.6),(59.5,25.4),(61.6,25.2),(64.5,25.3),(64.5,16.0)],
 [(39.0,16.0),(42.8,16.0),(42.6,16.9),(41.5,18.5),(40.6,19.8),(39.0,21.6)],
]
LABELS = [("IRÁN",54.2,29.3,34,False),("ARABIA SAUDÍ",45.0,22.2,34,False),("OMÁN",57.0,21.2,30,False),("EAU",54.0,23.4,26,False),
          ("QATAR",51.2,24.4,22,False),("YEMEN",47.0,18.0,28,False),("IRAK",46.0,30.0,26,False),
          ("Golfo Pérsico",51.6,27.2,28,True),("Golfo de Omán",59.2,24.4,28,True),("Mar Arábigo",61.0,20.0,30,True)]
_MAP = None
def map_image():
    global _MAP
    if _MAP is not None: return _MAP
    pw, ph = PX1 - PX0, PY1 - PY0; S = 2
    im = Image.new("RGBA", (pw * S, ph * S), (58, 62, 70, 255)); d = ImageDraw.Draw(im)
    tx = lambda lo, la: ((LON(lo) - PX0) * S, (LAT(la) - PY0) * S)
    for poly in WATER:
        P = [tx(*p) for p in poly]; d.polygon(P, fill=(20, 46, 82, 255)); d.line(P + [P[0]], fill=(150, 190, 230, 200), width=3)
    for lo in range(40, 65, 4): d.line([tx(lo, 31), tx(lo, 15)], fill=(255, 255, 255, 22), width=2)
    for la in range(16, 31, 3): d.line([tx(39, la), tx(65, la)], fill=(255, 255, 255, 22), width=2)
    for nm, lo, la, sz, water in LABELS:
        d.text(tx(lo, la), nm, font=F(FR if water else FB, sz * S), fill=(170, 205, 240, 200) if water else (235, 235, 235, 150), anchor="mm")
    d.text((pw * S - 24 * S, ph * S - 24 * S), "Mapa esquemático · trazado aproximado", font=F(FR, 22 * S), fill=(255, 255, 255, 120), anchor="rm")
    im = im.resize((pw, ph), Image.LANCZOS)
    mask = Image.new("L", (pw, ph), 0); ImageDraw.Draw(mask).rounded_rectangle([0, 0, pw - 1, ph - 1], radius=26, fill=255)
    im.putalpha(mask); _MAP = im; return im
def v_map(d, tl, du, ac, markers, stats=None, layer=None, **_):
    layer.alpha_composite(map_image(), (PX0, PY0))
    d.rounded_rectangle([PX0, PY0, PX1, PY1], radius=26, outline=(255, 255, 255, 90), width=2)
    for m in markers:
        if tl < m["t0"]: continue
        x, y = LON(m["lon"]), LAT(m["lat"]); u = tl - m["t0"]; p = ease(u / 0.4); big = m.get("big", 1)
        for k in range(3):
            ph = ((u * 0.8) + k / 3) % 1; r = (14 + ph * 70) * big
            d.ellipse([x - r, y - r, x + r, y + r], outline=A(m["color"], 230 * (1 - ph)), width=4)
        r = int(11 * big * p); d.ellipse([x - r, y - r, x + r, y + r], fill=A(m["color"], 255))
        ox = m.get("ox", 22); f = F(FB, 38); tw = f.getlength(m["name"]); bx = x + ox if ox > 0 else x + ox - tw
        d.rounded_rectangle([bx - 10, y - 56, bx + tw + 10, y - 6], radius=10, fill=(0, 0, 0, int(180 * p)))
        d.text((bx, y - 31), m["name"], font=f, fill=A(WHITE, 255 * p), anchor="lm")
    for i, (num, lab, col, t0) in enumerate(stats or []):
        p = ease((tl - t0) / 0.5)
        if p <= 0: continue
        x0 = 100 + i * 300
        d.rounded_rectangle([x0, 1060, x0 + 280, 1240], radius=22, fill=(0, 0, 0, int(210 * p)), outline=A(col, 255 * p), width=3)
        d.text((x0 + 140, 1125), num, font=F(FB, 76), fill=A(col, 255 * p), anchor="mm")
        d.text((x0 + 140, 1200), lab, font=F(FR, 32), fill=A(WHITE, 255 * p), anchor="mm")

def v_big(d, tl, du, ac, value, dec, label, barlab, scale, prefix="", suffix="", badge=None, d0=0.0, col=None, **_):
    col = col or ac; q = ease((tl - d0) / 1.2); v = value * q; s = f"{v:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    f = F(FB, 180)
    while f.getlength(prefix + s + suffix) > 940: f = F(FB, f.size - 8)
    d.text((540, 900), prefix + s + suffix, font=f, fill=A(WHITE, 255), anchor="mm")
    d.rounded_rectangle([100, 1020, 980, 1058], radius=19, fill=(255, 255, 255, 50))
    d.rounded_rectangle([100, 1020, 100 + max(40, 880 * min(1, v / scale)), 1058], radius=19, fill=A(col, 255))
    d.text((540, 1110), label, font=F(FB, 46), fill=A(WHITE, 255), anchor="mm")
    d.text((540, 1170), barlab, font=F(FR, 36), fill=A(col, 255), anchor="mm")
    if badge and tl > d0 + 1.0:
        p = ease((tl - d0 - 1.0) / 0.4); bw = F(FB, 50).getlength(badge[0]) + 60
        d.rounded_rectangle([990 - bw, 700, 990, 775], radius=38, fill=A(badge[1], 255 * p))
        d.text((990 - bw / 2, 737), badge[0], font=F(FB, 50), fill=A((10, 10, 10), 255 * p), anchor="mm")

def v_timeline(d, tl, du, ac, events, **_):
    # 16/10/2026 (Jocs: «muy poco espacio entre "semana pasada" y "esta semana"»): cada fecha cabe en su columna con 40 px de aire;
    # si no cabe, la letra baja hasta 46 px y, si aún no cabe, pasa a dos líneas.
    n = len(events); xs = [190, 540, 890][:n] if n == 3 else [270, 810]; colw = (310 if n == 3 else 480)
    g = ease(tl / (0.5 * n + 0.8)); d.line([100, 950, 100 + 880 * g, 950], fill=(255, 255, 255, 120), width=6)
    for (date, txt, t0, hl), x in zip(events, xs):
        p = ease((tl - t0) / 0.5)
        if p <= 0: continue
        c = ac if hl else WHITE; r = int(24 * p)
        d.ellipse([x - r, 950 - r, x + r, 950 + r], fill=A(c, 255))
        fs = 62
        while fs > 46 and F(FB, fs).getlength(date) > colw: fs -= 2
        lines = [date] if F(FB, fs).getlength(date) <= colw else wrap(date, F(FB, fs), colw)
        for j, l in enumerate(lines): d.text((x, 860 - (len(lines) - 1 - j) * (fs + 8) + (1 - p) * 30), l, font=F(FB, fs), fill=A(c, 255 * p), anchor="mm")
        for j, l in enumerate(wrap(txt, F(FR, 36), colw)): d.text((x, 1010 + j * 46), l, font=F(FR, 36), fill=A(WHITE, 255 * p), anchor="mm")

def v_board(d, tl, du, ac, rows, **_):
    """Pantalla de cotizaciones: (nombre, valor, cambio_txt, sube_bool)"""
    y0 = 960 - len(rows) * 120 / 2
    for i, (nm, val, ch, up) in enumerate(rows):
        p = ease((tl - 0.15 - 0.25 * i) / 0.4); y = y0 + i * 120; off = (1 - p) * 300
        col = GREEN if up else RED
        d.rounded_rectangle([60 + off, y, 1020 + off, y + 100], radius=18, fill=(0, 0, 0, int(175 * p)), outline=A(col, 160 * p), width=2)
        d.text((95 + off, y + 50), nm, font=F(FB, 42), fill=A(WHITE, 255 * p), anchor="lm")
        d.text((700 + off, y + 50), val, font=F(FB, 42), fill=A(WHITE, 255 * p), anchor="rm")
        tri = [(745 + off, y + 64), (775 + off, y + 64), (760 + off, y + 36)] if up else [(745 + off, y + 36), (775 + off, y + 36), (760 + off, y + 64)]
        d.polygon(tri, fill=A(col, 255 * p)); d.text((990 + off, y + 50), ch, font=F(FB, 42), fill=A(col, 255 * p), anchor="rm")

def v_cta(d, tl, du, ac, msg, **_):
    p = ease(tl / 0.5); s = 1 + 0.04 * math.sin(tl * 4); cx, cy = 540, 930; w, h = int(760 * s * p), int(420 * s * p)
    if p < 0.05: return
    d.rounded_rectangle([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], radius=60, fill=A(WHITE, 255 * p))
    d.polygon([(cx - 90, cy + h / 2 - 4), (cx - 30, cy + h / 2 - 4), (cx - 120, cy + h / 2 + 80)], fill=A(WHITE, 255 * p))
    d.text((cx, cy - 40), "¿?", font=F(FB, 200 * p + 2), fill=(10, 10, 10, 255), anchor="mm")
    d.text((cx, cy + 130 * p), msg, font=F(FB, 44 * p + 2), fill=(10, 10, 10, 255), anchor="mm")

def v_photo(d, tl, du, ac, layer=None, **k):
    """Escena de imagen real a pantalla completa: sin gráfico encima (solo rótulo y subtítulos)."""
    return

VIS = dict(photo=v_photo, title=v_title, card=v_card, quote=v_quote, versus=v_versus, bars=v_bars, fromto=v_fromto, hemi=v_hemi, map=v_map,
           big=v_big, timeline=v_timeline, board=v_board, cta=v_cta)

# ======================= timing =======================
def load_words(cfg):
    p = f"{WORK}/words/{cfg['id']}.json"
    if os.path.exists(p): return [tuple(w) for w in json.load(open(p))], True
    # timing provisional: ritmo medido en la voz de Hugo López (≈3 palabras/s)
    ws = cfg["voice"].split(); t = 0.0; out = []
    for w in ws:
        dur = max(0.05, 0.066 * len(w.strip(".,:;?¿!¡…")) - 0.04)
        if w[-1] in ".?!:": dur += 0.6
        elif w[-1] in ",…": dur += 0.3
        out.append((w, round(t, 3), round(t + dur, 3))); t += dur + 0.075
    k = 0.836  # calibrado con la voz real del Short 1 (33,68 s)
    return [(w, round(a * k, 3), round(b * k, 3)) for w, a, b in out], False

def parse_caps(cfg, words):
    """cfg['caps']: frases separadas por ' / '; tokens {texto|n} consumen n palabras habladas."""
    phrases = []; wi = 0
    for ph in cfg["caps"].split(" / "):
        toks = []
        for m in re.finditer(r"\{([^}|]+)\|(\d+)\}|(\S+)", ph):
            disp, n = (m.group(1), int(m.group(2))) if m.group(1) else (m.group(3), 1)
            a = words[wi][1]; b = words[wi + n - 1][2]; toks.append((disp, a, b)); wi += n
        phrases.append(toks)
    assert wi == len(words), f"subtítulos consumen {wi} palabras, la voz tiene {len(words)}"
    return phrases

def timings(cfg, words):
    puente = cfg["voice"].rstrip()[-1] not in ".?!…"
    starts = cfg["scene_words"]; n = len(starts); total = round(words[-1][2] + (TAIL_PUENTE if puente else TAIL), 3)
    b = [0.0] + [(words[starts[i] - 1][2] + words[starts[i]][1]) / 2 for i in range(1, n)] + [total]
    return [(b[i], b[i + 1] - b[i]) for i in range(n)], total

# ======================= estudio / chrome =======================
def make_bg(cfg):
    Hh = H + 400; y = np.linspace(0, 1, Hh)[:, None, None]
    c1 = np.array(cfg["c1"], float); c2 = np.array(cfg["c2"], float); arr = (c1 * (1 - y) + c2 * y) * np.ones((1, W, 1))
    yy, xx = np.mgrid[0:Hh, 0:W]; ac = np.array(cfg["ac"], float)
    for (bx, by, br, st) in [(200, 500, 520, .18), (900, 1300, 620, .16), (600, 2000, 500, .12)]:
        arr = arr + np.exp(-(((xx - bx) ** 2 + (yy - by) ** 2) / (2 * br ** 2)))[:, :, None] * ac * st
    base = np.clip(arr, 0, 255).astype(np.float32)
    dk = base * 0.55 + np.array(NAVY, np.float32) * 0.45
    for off, st in [(0, .10), (700, .07), (1500, .09)]:   # luces de plató
        band = np.exp(-(((xx * 0.6 + yy * 0.8 - 600 - off) % 2200 - 300) ** 2) / (2 * 140 ** 2)); dk += band[:, :, None] * 255 * st
    img = Image.fromarray(np.clip(dk, 0, 255).astype(np.uint8)).convert("RGBA"); d = ImageDraw.Draw(img)
    for y_ in range(0, Hh, 36):
        for x in range(18 if (y_ // 36) % 2 else 0, W, 36): d.ellipse([x - 1.6, y_ - 1.6, x + 1.6, y_ + 1.6], fill=(255, 255, 255, 18))
    return img
def make_vignette():
    yy, xx = np.mgrid[0:H, 0:W]; r = np.sqrt(((xx - W / 2) / (W * 0.75)) ** 2 + ((yy - H / 2) / (H * 0.62)) ** 2)
    v = np.zeros((H, W, 4), np.uint8); v[..., 3] = (np.clip((r - 0.55) * 1.6, 0, 1) * 170).astype(np.uint8); return Image.fromarray(v, "RGBA")
def make_grain(n=6):
    rng = np.random.default_rng(3); out = []
    for _ in range(n):
        g = rng.integers(0, 255, (H // 2, W // 2), dtype=np.uint8); a = np.full((H // 2, W // 2), 16, np.uint8)
        out.append(Image.fromarray(np.dstack([g, g, g, a]), "RGBA").resize((W, H), Image.NEAREST))
    return out
def load_media(cfg, i):
    """Foto (media/<id>_s<i>.jpg/png/webp) o vídeo (media/<id>_s<i>.mp4) de la escena i, con su crédito (.json de media.py)."""
    base = f"{WORK}/media/{cfg['id']}_s{i}"; credit = ""
    if os.path.exists(base + ".json"):
        try: credit = json.load(open(base + ".json")).get("credit", "")
        except Exception: pass
    if os.path.exists(base + ".mp4"):   # vídeo real: fotogramas 1080x1920 a 30 fps en disco (poca memoria)
        fd = f"{WORK}/vframes/{cfg['id']}_s{i}"; os.makedirs(fd, exist_ok=True)
        if not os.listdir(fd):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", base + ".mp4", "-t", "8", "-an", "-vf",
                            "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,fps=30", "-q:v", "3", f"{fd}/%04d.jpg"], check=True)
        n = len(os.listdir(fd))
        if n: return {"vid": fd, "n": n, "credit": credit}
    for ext in ("jpg", "jpeg", "png", "webp"):
        p = f"{base}.{ext}"
        if os.path.exists(p):
            im = Image.open(p).convert("RGB"); s = max(W * 1.12 / im.width, H * 1.12 / im.height)
            return {"img": im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS), "credit": credit}
    return None

def strap(d, tl, cfg, sc):
    ac = cfg["ac"]; p = ease((tl - 0.05) / 0.45); off = (1 - p) * -700
    kf = F(FB, 36); kw = kf.getlength(sc["k"]) + 44
    d.rectangle([40 + off, 205, 40 + off + kw, 257], fill=A(ac, 255)); d.text((62 + off, 231), sc["k"], font=kf, fill=A(NAVY, 255), anchor="lm")
    hf = F(FB, 62); lines = wrap(sc["h"], hf, 930); q = ease((tl - 0.15) / 0.45); off2 = (1 - q) * -900; top = 257; bh = len(lines) * 74 + 30
    d.rectangle([40 + off2, top, 1040 + off2, top + bh], fill=(250, 250, 252, 245)); d.rectangle([40 + off2, top, 52 + off2, top + bh], fill=A(ac, 255))
    for j, l in enumerate(lines): d.text((76 + off2, top + 15 + j * 74), l, font=hf, fill=A(NAVY, 255))

def chrome(fr, t, total, cfg):
    d = ImageDraw.Draw(fr, "RGBA"); ac = cfg["ac"]
    d.rectangle([0, 0, W * t / total, 12], fill=WHITE)
    lab = cfg["label"]; lf = F(FB, 34); lw = lf.getlength(lab) + 50; lc = (210, 30, 40) if lab == "ÚLTIMA HORA" else (ac if cfg.get("label_ac") else (210, 30, 40))
    d.rectangle([40, 92, 40 + lw, 150], fill=lc); d.text((40 + lw / 2, 121), lab, font=lf, fill=WHITE if lc == (210, 30, 40) else NAVY, anchor="mm")
    tf = F(FB, 30); d.rectangle([40 + lw, 92, 40 + lw + tf.getlength(cfg["tag"]) + 44, 150], fill=(0, 0, 0, 170))
    d.text((62 + lw, 121), cfg["tag"], font=tf, fill=ac, anchor="lm"); d.text((905, 121), cfg["date"], font=F(FB, 30), fill=WHITE, anchor="rm")
    if LOGO.get("bug") is not None: fr.paste(LOGO["bug"], (924, 38), LOGO["bug"])
    y0 = 1470; d.rectangle([0, y0, W, y0 + 64], fill=(8, 12, 26, 235))
    txt = "   ·   ".join(cfg["ticker"]) + "   ·   "; tf = F(FB, 32); tw = tf.getlength(txt); x = 230 - (t * 150) % tw
    while x < W: d.text((x, y0 + 32), txt, font=tf, fill=WHITE, anchor="lm"); x += tw
    d.rectangle([0, y0, 210, y0 + 64], fill=(210, 30, 40)); d.text((105, y0 + 32), "TITULARES", font=F(FB, 30), fill=WHITE, anchor="mm")
    for j, l in enumerate(wrap("Fuentes: " + cfg["sources"], F(FR, 26), 1000)[:2]): d.text((40, 1560 + j * 34), l, font=F(FR, 26), fill=(190, 190, 190))
    follow_badge(fr, d, t, total)

def follow_badge(fr, d, t, total):
    """«SÍGUENOS» en la esquina superior derecha, bajo el logo, 3 s a mitad del vídeo (nunca al final: el Short va en bucle)."""
    t0 = max(6.0, total * FOLLOW_AT); u = t - t0
    if not (0 <= u < 3.0): return
    p = min(ease(u / 0.3), ease((3.0 - u) / 0.3)); f = F(FB, 30); txt = "SÍGUENOS"; w = f.getlength(txt) + 70
    x1 = 1046 + (1 - p) * (w + 20); x0 = x1 - w; y0, y1 = 166, 202
    d.rounded_rectangle([x0, y0, x1, y1], radius=18, fill=(210, 30, 40, int(240 * p)))
    cx, cy = x0 + 26, (y0 + y1) / 2   # punto blanco que late, como un botón de suscripción
    r = 7 + 2 * math.sin(u * 9); d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(255, 255, 255, int(255 * p)))
    d.text((x0 + 44, cy), txt, font=f, fill=(255, 255, 255, int(255 * p)), anchor="lm")
    ph = (u * 0.8) % 1; rr = 64 + ph * 16   # anillo que llama la atención sobre el logo
    d.ellipse([986 - rr, 100 - rr, 986 + rr, 100 + rr], outline=(255, 255, 255, int(170 * (1 - ph) * p)), width=4)

def captions(d, t, phrases):
    """Subtítulos palabra a palabra: frase visible, palabra hablada resaltada."""
    for toks in phrases:
        if toks[0][1] - 0.05 <= t < toks[-1][2] + 0.25:
            sz = 58; f = F(FB, sz); sp = f.getlength(" ")
            while sum(f.getlength(x[0]) for x in toks) + sp * (len(toks) - 1) > 900: sz -= 4; f = F(FB, sz); sp = f.getlength(" ")
            tw = sum(f.getlength(x[0]) for x in toks) + sp * (len(toks) - 1); x = 540 - tw / 2; y = 1370
            p = 1.0 if toks[0][1] < 0.1 else ease((t - toks[0][1] + 0.05) / 0.12)
            d.rounded_rectangle([x - 30, 1318, x + tw + 30, 1422], radius=26, fill=(0, 0, 0, int(205 * p)))
            for (w, a, b) in toks:
                ww = f.getlength(w); cur = a <= t < b + 0.06; said = t >= a
                if cur: d.rounded_rectangle([x - 8, y - sz * 0.62, x + ww + 8, y + sz * 0.62], radius=12, fill=(255, 214, 64, 255))
                d.text((x, y), w, font=f, fill=(NAVY + (255,)) if cur else ((255, 255, 255, int(255 * p)) if said else (255, 255, 255, int(150 * p))), anchor="lm")
                x += ww + sp
            break

LOGO = {}
def load_logo():
    """media/logo.png o media/logo.jpg (se recorta en círculo). En el proyecto está en logo_b64.txt."""
    if LOGO: return
    for p in (f"{WORK}/media/logo.png", f"{WORK}/media/logo.jpg"):
        if os.path.exists(p):
            im = Image.open(p).convert("RGBA").resize((600, 600), Image.LANCZOS)
            m = Image.new("L", (600, 600), 0); ImageDraw.Draw(m).ellipse([3, 3, 597, 597], fill=255); im.putalpha(m)
            LOGO["bug"] = im.resize((124, 124), Image.LANCZOS); LOGO["big"] = im; return

class Ctx: pass
def build_ctx(cfg):
    load_logo(); c = Ctx(); c.bg = make_bg(cfg); c.vig = make_vignette(); c.grain = make_grain()
    c.media = {i: m for i in range(len(cfg["scenes"])) if (m := load_media(cfg, i)) is not None}
    sh = np.zeros((H, W, 4), np.uint8); sh[..., :3] = NAVY; sh[..., 3] = 125; c.shade = Image.fromarray(sh, "RGBA")
    sh2 = np.zeros((H, W, 4), np.uint8); sh2[..., :3] = NAVY; sh2[..., 3] = 40; c.shade_light = Image.fromarray(sh2, "RGBA"); return c

def render_frame(cfg, ctx, tm, total, t, phrases):
    si = len(tm) - 1
    for i, (st, du) in enumerate(tm):
        if st <= t < st + du: si = i; break
    st, du = tm[si]; sc = cfg["scenes"][si]; tl = t - st; ac = cfg["ac"]
    oy = int(200 + 150 * math.sin(t * 0.35)); fr = ctx.bg.crop((0, oy, W, oy + H)).copy()
    media = ctx.media.get(si); vname, vkw = sc["v"]
    if vname == "photo" and media is None: vname, vkw = vkw.get("alt", ("title", {}))   # sin imagen: gráfico de reserva
    sc = dict(sc, v=(vname, {k: v for k, v in vkw.items() if k != "alt"}))
    if media is not None:
        if "vid" in media:   # vídeo real, con avance lento
            k = min(media["n"] - 1, int(tl * FPS)); m = Image.open(f"{media['vid']}/{k + 1:04d}.jpg").convert("RGB")
            z = 1 + 0.03 * (tl / du); m = m.resize((int(W * z) + 1, int(H * z) + 1), Image.BILINEAR)
        else:                # foto real con efecto Ken Burns
            z = 1 + 0.06 * (tl / du); m = media["img"].resize((int(W * z) + 1, int(H * z) + 1), Image.BILINEAR)
        cx = (m.width - W) // 2; cy = (m.height - H) // 2; fr.paste(m.crop((cx, cy, cx + W, cy + H)).convert("RGBA"), (0, 0))
        fr.alpha_composite(ctx.shade_light if vname == "photo" else ctx.shade)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    tv = tl + (1.2 if si == 0 else 0)
    name, kw = sc["v"]; VIS[name](d, tv, du, ac, layer=layer, **kw)
    z = 1 + 0.035 * (tl / du)   # avance lento de cámara
    if z > 1.001:
        lw, lh = int(W * z), int(H * z); L = layer.resize((lw, lh), Image.BILINEAR); ox, oyy = int((lw - W) * 0.5), int((lh - H) * 0.52)
        layer = L.crop((ox, oyy, ox + W, oyy + H)); d = ImageDraw.Draw(layer)
    zp = ease(tl / 0.18)  # zoom de golpe al entrar en escena
    if si > 0 and zp < 1:
        s = 1.06 - 0.06 * zp; lw, lh = int(W * s), int(H * s); L = layer.resize((lw, lh), Image.BILINEAR); ox, oyy = (lw - W) // 2, (lh - H) // 2
        layer = L.crop((ox, oyy, ox + W, oyy + H)); d = ImageDraw.Draw(layer)
    strap(d, tl + (1.0 if si == 0 else 0), cfg, sc); captions(d, t, phrases)
    ga = max(0.0, min(1, tl / 0.15 if si > 0 else 1, (du - tl) / 0.15 if si < len(tm) - 1 else 1))
    if ga < 1: layer.putalpha(layer.getchannel("A").point([int(i * ga) for i in range(256)]))
    fr.alpha_composite(layer); fr.alpha_composite(ctx.vig); fr.alpha_composite(ctx.grain[int(t * FPS) % len(ctx.grain)])
    ct = credit_text(media.get("credit", "")) if media is not None else ""
    if ct:   # crédito obligatorio SOLO en CC BY / CC BY-SA: pequeño y discreto (autor y licencia), sin «Imagen:» ni fuente
        dc = ImageDraw.Draw(fr); cf = F(FR, 16)
        while cf.getlength(ct) > 700 and len(ct) > 20: ct = ct[:-2]
        dc.text((41, 1297), ct, font=cf, fill=(0, 0, 0, 90), anchor="ls"); dc.text((40, 1296), ct, font=cf, fill=(230, 230, 230, 140), anchor="ls")
    fr = fr.convert("RGB"); chrome(fr, t, total, cfg); return fr

def credit_text(c):
    """«Autor / licencia / fuente» → «© Autor, CC BY 4.0» solo si la licencia obliga a citar (CC BY, CC BY-SA).
    CC0, dominio público, Pexels, Pixabay y NASA no lo exigen: no se pinta nada."""
    parts = [x.strip() for x in (c or "").split(" / ")]
    lic = next((x for x in parts if re.search(r"\bCC[ -]?BY", x, re.I)), "")
    if not lic or re.search(r"CC0|dominio p|public domain|pexels|pixabay", c, re.I): return ""
    return f"© {parts[0]}, {lic}" if parts[0] != lic else lic

# ======================= música original =======================
SR = 44100
def midi(n): return 440 * 2 ** ((n - 69) / 12)
CH = {"Am": [(45, [57, 60, 64]), (41, [53, 57, 60]), (48, [55, 60, 64]), (43, [55, 59, 62])],
      "Dm": [(38, [50, 53, 57]), (34, [53, 58, 62]), (43, [50, 55, 58]), (45, [52, 57, 61])],
      "Em": [(40, [52, 55, 59]), (36, [52, 55, 60]), (43, [50, 55, 59]), (38, [50, 54, 57])]}
def _f(x, fc, kind, o=2): b, a = butter(o, fc / (SR / 2) if not isinstance(fc, list) else [f / (SR / 2) for f in fc], kind); return lfilter(b, a, x)
def saw(f, t, det):
    y = np.zeros_like(t)
    for k in range(1, 9): y += np.sin(2 * np.pi * f * k * (1 + det) * t) / k
    return y
def make_music(cfg, tm, total, path):
    T = total; n = int(T * SR); t = np.arange(n) / SR; rng = np.random.default_rng(7); prog = CH[cfg["key"]]; clen = 4.8
    pad = np.zeros(n); bass = np.zeros(n)
    for ci in range(int(T / clen) + 2):
        s = ci * clen; root, notes = prog[ci % 4]; i0 = int(s * SR); i1 = min(n, int((s + clen + 1.2) * SR))
        if i0 >= n: break
        tt = t[i0:i1] - s; env = np.minimum(1, tt / 1.4) * np.clip((clen + 1.2 - tt) / 1.2, 0, 1); seg = np.zeros_like(tt)
        for m in notes: f = midi(m); seg += saw(f, tt, 0.0) + saw(f, tt, 0.004) + saw(f, tt, -0.004)
        pad[i0:i1] += seg * env
        bass[i0:i1] += np.sin(2 * np.pi * midi(root) * tt) * np.clip(1 - (tt % 0.6) / 0.6, 0.15, 1) * np.minimum(1, tt / 0.3) * np.clip((clen - tt) / 0.4, 0, 1) * (tt < clen)
    pad = _f(pad, 950, "low"); pad /= np.max(np.abs(pad)) + 1e-9; bass /= np.max(np.abs(bass)) + 1e-9
    hat = np.zeros(n)
    for k in range(int(T / 0.3)):
        i = int(k * 0.3 * SR); L = int(0.04 * SR)
        if i + L < n: hat[i:i + L] += _f(rng.standard_normal(L), 6000, "high") * np.exp(-np.arange(L) / (0.008 * SR)) * (1.0 if k % 2 == 0 else 0.5)
    hat /= np.max(np.abs(hat)) + 1e-9; fx = np.zeros(n)
    for (st, du) in tm[1:]:   # golpe sonoro en cada cambio de escena
        i = int(st * SR); L = int(0.5 * SR)
        if i + L >= n: continue
        x = _f(rng.standard_normal(L), [500, 5000], "band") * np.sin(np.pi * np.arange(L) / L) ** 2; x /= np.max(np.abs(x)) + 1e-9
        fx[i:i + L] += np.sin(2 * np.pi * 55 * np.arange(L) / SR) * np.exp(-np.arange(L) / (0.18 * SR))   # solo el golpe grave
    # 16/10/2026 (Jocs: «sigue habiendo un poco de ruido metálico de fondo»; elegida «música limpia» a ciegas): sin platillo cada
    # 0,3 s, sin soplido de ruido en los cambios de escena y sin el retardo de 12 ms entre canales (en mono sonaba a filtro metálico).
    mix = 0.38 * pad + 0.32 * bass + 0.22 * fx; dl = 0
    st_ = np.stack([mix, np.roll(mix, dl)], 1) * (np.minimum(1, t / 0.04) * np.clip((T - t) / 0.25, 0, 1))[:, None]
    st_ = st_ / np.max(np.abs(st_)) * 0.30; wavfile.write(path, SR, (st_ * 32767).astype(np.int16))

def mux(cfg):
    nm = cfg["id"]; vid = f"{WORK}/silent_{nm}.mp4"; mus = f"{WORK}/music_{nm}.wav"; voz = f"{WORK}/voz/{nm}.mp3"
    has = os.path.exists(voz); out = f"{OUT}/{cfg['out']}{'' if has else '_SIN_VOZ'}.mp4"
    enc = ["-c:v", "libx264", "-preset", "medium", "-b:v", "4800k", "-maxrate", "5500k", "-bufsize", "11000k", "-pix_fmt", "yuv420p", "-r", "30", "-movflags", "+faststart", "-c:a", "aac", "-b:a", "192k", "-ar", "44100"]
    if has:
        fc = ("[2:a]aformat=sample_rates=44100:channel_layouts=stereo,apad,volume=1.15,asplit=2[v][sc];[1:a]volume=1.0[m0];"
              "[m0][sc]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=350[m];[m][v]amix=inputs=2:duration=first:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", vid, "-i", mus, "-i", voz, "-filter_complex", fc, "-map", "0:v", "-map", "[a]"] + enc + ["-shortest", out]
    else:
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", vid, "-i", mus, "-filter_complex", "[1:a]loudnorm=I=-14:TP=-1.5:LRA=11,aresample=44100[a]", "-map", "0:v", "-map", "[a]"] + enc + ["-shortest", out]
    subprocess.run(cmd, check=True); return out, has

def check_loop(cfg):
    """El Short va en bucle: la última frase NO puede repetir la primera (se oiría dos veces seguidas al volver a empezar)."""
    ss = [x.strip(" ¿¡").lower() for x in re.split(r"(?<=[.?!])\s+", cfg["voice"].strip()) if x.strip()]
    if len(ss) > 1 and re.sub(r"\W", "", ss[0]) == re.sub(r"\W", "", ss[-1]):
        print("AVISO BUCLE: la última frase repite la primera. Cámbiala por una frase-puente sin punto que se complete con la primera "
              "(p. ej. «… Por eso todos comentan que» → «Trump promete no atacar Irán.»).")
    elif cfg["voice"].rstrip()[-1] in ".?!…":
        print("AVISO BUCLE: el guion acaba en punto; lo ideal es una frase-puente sin punto que empalme con la primera frase.")

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["ENE", "FEB", "MAR", "ABR", "MAY", "JUN", "JUL", "AGO", "SEP", "OCT", "NOV", "DIC"]
def check_date(cfg):
    """Fecha del día que se CUENTA (Jocs, 12/10/2026: un Pitido final del domingo no puede decir «lunes»).
    Es el día de hoy en Madrid; entre las 00:00 y las 05:59 se toma el día anterior (un render de deportes que pase de
    medianoche sigue contando la jornada de ayer). Corrige sola la fecha de la cabecera y avisa de días de la semana
    del guion o de los rótulos que no cuadren con ese día."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    now = datetime.now(ZoneInfo("Europe/Madrid")); day = (now - timedelta(days=1)) if now.hour < 6 else now
    hoy = DIAS[day.weekday()]; ayer = DIAS[(day.weekday() - 1) % 7]
    label = f"{hoy[:3].upper().replace('MIÉ', 'MIÉ').replace('SÁB', 'SÁB')} {day.day} {MESES[day.month - 1]} {day.year}"
    if cfg.get("date", "").strip().upper() != label:
        if cfg.get("date"): print(f"FECHA corregida en la cabecera: «{cfg['date']}» → «{label}» (día que se cuenta: {hoy} {day.day})")
        cfg["date"] = label
    textos = [cfg.get("voice", ""), cfg.get("caps", "")] + [str(sc.get("k", "")) + " " + str(sc.get("h", "")) for sc in cfg.get("scenes", [])]
    raro = set()
    for t in textos:
        for m in re.finditer(r"\b(este|esta|hoy|el|del|este pasado)\s+(lunes|martes|miércoles|jueves|viernes|sábado|domingo)\b", t.lower()):
            if m.group(2) not in (hoy, ayer) and not m.group(1).startswith("el"): raro.add(m.group(0))
        for m in re.finditer(r"\b(lunes|martes|miércoles|jueves|viernes|sábado|domingo)\b", t.lower()):
            if m.group(1) not in (hoy, ayer): raro.add(m.group(1))
    if raro:
        print(f"AVISO FECHA: hoy se cuenta el {hoy} {day.day}; el guion o los rótulos dicen {', '.join(sorted(raro))}. "
              f"Compruébalo: si es una cita futura, vale («el próximo martes»); si habla de hoy, corrígelo.")
    return day

def main(mod, mode):
    cfg = importlib.import_module(mod).CFG; check_loop(cfg); check_date(cfg); words, real = load_words(cfg); phrases = parse_caps(cfg, words); tm, total = timings(cfg, words); ctx = build_ctx(cfg)
    print(cfg["id"], "voz real" if real else "timing PROVISIONAL", "escenas", [round(x[1], 2) for x in tm], "total", total)
    if mode == "test":
        for i, (st, du) in enumerate(tm):
            for frac, tag in ((0.85, ""),):
                render_frame(cfg, ctx, tm, total, st + du * frac, phrases).save(f"{WORK}/test_{cfg['id']}_{i}.png")
        return
    if mode in ("render", "all"):
        make_music(cfg, tm, total, f"{WORK}/music_{cfg['id']}.wav")
        p = subprocess.Popen(["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-",
                              "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p", f"{WORK}/silent_{cfg['id']}.mp4"], stdin=subprocess.PIPE)
        for f in range(int(total * FPS)): p.stdin.write(render_frame(cfg, ctx, tm, total, f / FPS + 1e-6, phrases).tobytes())
        p.stdin.close(); p.wait()
        srt = []
        for k, toks in enumerate(phrases, 1):
            def ts(x): return f"{int(x // 3600):02}:{int(x % 3600 // 60):02}:{int(x % 60):02},{int(round((x % 1) * 1000)) % 1000:03}"
            srt.append(f"{k}\n{ts(toks[0][1])} --> {ts(toks[-1][2])}\n{' '.join(x[0] for x in toks)}\n")
        open(f"{OUT}/{cfg['out']}.srt", "w").write("\n".join(srt))
    out, has = mux(cfg); print("->", out, "con voz" if has else "sin voz", "media en escenas:", sorted(ctx.media))

if __name__ == "__main__":
    sys.path.insert(0, WORK); main(sys.argv[1], sys.argv[2])
