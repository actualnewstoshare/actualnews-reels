#!/usr/bin/env python3
"""Sube un Short a YouTube (API de datos v3) con título, descripción, etiquetas,
lista de reproducción y hora de publicación. Solo biblioteca estándar.

Credenciales: SOLO por variables de entorno del entorno en la nube (nunca en
archivos del proyecto ni en el chat):
  YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN
Lista: «## 7. Lista» de la ficha o --playlist (nacional | internacional | economia, o nombre/id exacto).
Opcional: YT_PLAYLIST como lista por defecto.

Uso:
  python3 youtube_upload.py check                       # prueba credenciales, canal y listas
  python3 youtube_upload.py upload <video.mp4> <ficha.md|meta.json> [--dry-run]
  python3 youtube_upload.py estado <id_video>             # uploadStatus, procesado y duración
  python3 youtube_upload.py miniatura <id_video> <img.jpg>  # miniatura propia (vídeo largo semanal; requiere canal verificado)
  python3 youtube_upload.py comentario <id_video> <ficha.md>  # publica «## 5. Comentario fijado» (vídeo largo, una vez público)
  python3 youtube_upload.py borrar <id_video>             # borra un vídeo propio (solo el atascado, ver SUBIR_YOUTUBE.md)
         [--privacy public|private|unlisted] [--at "2026-10-10 13:00"] [--playlist NOMBRE|ID]

Hora: --at (hora de Madrid). Si no se da, se toma de la sección «Programar» de
la ficha. Si la hora ya pasó o no hay hora, se publica al momento con --privacy
(por defecto public). Programar exige subir como privado con publishAt (lo hace solo).

meta.json (alternativa a la ficha): {"title", "description", "tags": [...],
 "publish_at": "AAAA-MM-DD HH:MM", "playlist", "pinned_comment"}
"""
import json, os, re, sys, urllib.request, urllib.parse, urllib.error
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")
API = "https://www.googleapis.com/youtube/v3"
UPLOAD = "https://www.googleapis.com/upload/youtube/v3/videos"
CATEGORY_NEWS = "25"  # Noticias y política


def die(msg):
    print("ERROR:", msg); sys.exit(1)


def token():
    need = ["YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN"]
    miss = [k for k in need if not os.environ.get(k)]
    if miss:
        die("faltan variables de entorno: " + ", ".join(miss))
    env = lambda k: os.environ[k].strip().strip('"\'').strip()  # tolera comillas/espacios al pegar
    data = urllib.parse.urlencode({
        "client_id": env("YT_CLIENT_ID"),
        "client_secret": env("YT_CLIENT_SECRET"),
        "refresh_token": env("YT_REFRESH_TOKEN"),
        "grant_type": "refresh_token"}).encode()
    try:
        r = urllib.request.urlopen("https://oauth2.googleapis.com/token", data, timeout=30)
    except urllib.error.HTTPError as e:
        die(f"Google rechazó las credenciales ({e.code}): {e.read().decode()[:300]}")
    return json.load(r)["access_token"]


def call(tok, method, url, body=None, headers=None, raw=False):
    h = {"Authorization": "Bearer " + tok}
    if body is not None and not isinstance(body, bytes):
        body = json.dumps(body).encode(); h["Content-Type"] = "application/json; charset=UTF-8"
    h.update(headers or {})
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    try:
        r = urllib.request.urlopen(req, timeout=600)
    except urllib.error.HTTPError as e:
        die(f"{method} {url.split('?')[0]} → {e.code}: {e.read().decode()[:500]}")
    return r if raw else json.load(r)


# ---------- ficha.md ----------
def section(md, n):
    m = re.search(rf"^## {n}\..*?$\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def parse_ficha(path):
    md = open(path, encoding="utf-8").read()
    t = re.search(r"\*\*(.+?)\*\*", section(md, 1))
    if not t:
        die("la ficha no tiene título en negrita en «## 1. Título»")
    desc = section(md, 2)
    # Sin líneas de fuentes ni de créditos en la descripción (dan sensación de IA): las fuentes van en «## 8. Fuentes»
    # de la ficha, que no se publica, y el crédito de las imágenes ya sale en pequeño sobre el vídeo (basta para CC BY)
    desc = re.sub(r"(?im)^\s*[-*·]?\s*(\*\*)?(fuentes?|créditos?|imágenes?|imagen|fotos?|vídeos?|video)(\*\*)?\s*:.*\n?", "", desc)
    desc = re.sub(r"\n{3,}", "\n\n", desc).strip()
    tags = [x.strip() for x in section(md, 3).replace("\n", ",").split(",") if x.strip()]
    # Títulos sin emojis (regla del canal): se quitan aunque la ficha los traiga
    title = re.sub(r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2B00-\u2BFF\uFE0F\u200D]", "", t.group(1))
    title = re.sub(r"\s{2,}", " ", title).strip()
    meta = {"title": title, "description": desc, "tags": tags,
            "pinned_comment": section(md, 5) or None,
            "dato_util": section(md, 9) or None}  # «## 9. Dato útil» (opcional): primera línea del texto del Reel
    lista = section(md, 7)  # «## 7. Lista»: Política nacional / Internacional / Economía
    if lista:
        meta["playlist"] = lista.splitlines()[0].strip("*· ")
    prog = section(md, 4)
    iso = re.search(r"(20\d{2})-(\d{2})-(\d{2})\D+(\d{1,2}):(\d{2})", prog)
    if iso:
        meta["publish_at"] = f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)} {int(iso.group(4)):02d}:{iso.group(5)}"
        return meta
    d = re.search(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?", prog)
    h = re.search(r"(\d{1,2}):(\d{2})", prog)
    if d and h:
        y = re.search(r"\b(20\d{2})\b", md)  # año real, no el «0800» del id
        year = d.group(3) or (y.group(1) if y else str(datetime.now(MADRID).year))
        meta["publish_at"] = f"{year}-{int(d.group(2)):02d}-{int(d.group(1)):02d} {int(h.group(1)):02d}:{h.group(2)}"
    return meta


def load_meta(path):
    if path.endswith(".json"):
        return json.load(open(path, encoding="utf-8"))
    return parse_ficha(path)


def clean_tags(tags):
    # YouTube: máximo 500 caracteres en total contando comas y comillas de las que llevan espacio.
    out, total = [], 0
    for t in tags:
        t = t.replace("<", "").replace(">", "").strip()
        cost = len(t) + (2 if " " in t else 0) + (1 if out else 0)
        if len(out) >= 15:   # 19/10/2026: más de 15 etiquetas no ayuda en Shorts y puede tomarse como relleno (normas de spam)
            break
        if t and total + cost <= 500:
            out.append(t); total += cost
    return out


# ---------- listas ----------
def playlists(tok):
    res, page = [], ""
    while True:
        r = call(tok, "GET", f"{API}/playlists?part=snippet&mine=true&maxResults=50&pageToken={page}")
        res += [(p["id"], p["snippet"]["title"]) for p in r.get("items", [])]
        page = r.get("nextPageToken")
        if not page:
            return res


def resolve_playlist(tok, want):
    if not want:
        return None
    lists = playlists(tok)
    for pid, title in lists:
        if want in (pid, title) or want.lower() == title.lower():
            return pid
    # Coincidencia parcial sin tildes: «politica», «internacional», «economia»
    words = set(_plain(want).split())  # por palabras: «nacional» no casa con «internacional»
    hits = [pid for pid, title in lists if words <= set(_plain(title).split())]
    if len(hits) == 1:
        return hits[0]
    die(f"no encuentro una única lista para «{want}»: " + "; ".join(t for _, t in lists))


def _plain(s):
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s.lower()) if unicodedata.category(c) != "Mn")


# ---------- comandos ----------
def check():
    tok = token()
    ch = call(tok, "GET", f"{API}/channels?part=snippet,status&mine=true")["items"]
    if not ch:
        die("la cuenta autorizada no tiene canal de YouTube")
    print("Canal:", ch[0]["snippet"]["title"], ch[0]["id"])
    print("Listas:")
    for pid, title in playlists(tok):
        print(f"  {pid}  {title}")
    print("OK: credenciales válidas")


def upload(video, metapath, dry=False, privacy="public", at=None, playlist=None):
    if not os.path.isfile(video):
        die("no existe " + video)
    meta = load_meta(metapath)
    title = meta["title"][:100]
    desc = meta.get("description", "")[:5000].replace("<", "‹").replace(">", "›")
    when = at or meta.get("publish_at")
    status = {"privacyStatus": privacy, "selfDeclaredMadeForKids": False,
              "embeddable": True, "license": "youtube"}
    if when:
        dt = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=MADRID)
        if dt > datetime.now(MADRID):
            status.update(privacyStatus="private",
                          publishAt=dt.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%SZ"))
        else:
            print(f"Aviso: la hora {when} ya pasó; se publica al momento como {privacy}")
    body = {"snippet": {"title": title, "description": desc, "tags": clean_tags(meta.get("tags", [])),
                        "categoryId": CATEGORY_NEWS, "defaultLanguage": "es",
                        "defaultAudioLanguage": "es-ES"},
            "status": status}
    pl = playlist or meta.get("playlist") or os.environ.get("YT_PLAYLIST")
    if dry:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        print("Lista:", pl or "(ninguna)", "· Vídeo:", video, os.path.getsize(video), "bytes")
        return
    tok = token()
    pid = resolve_playlist(tok, pl)
    # Lee el vídeo una sola vez y usa ese tamaño: si la carpeta compartida reescribe el MP4 entre
    # getsize() y read(), YouTube recibía más bytes de los anunciados (400, 11/10/2026).
    with open(video, "rb") as f:
        data = f.read()
    size = len(data)
    init = call(tok, "POST", f"{UPLOAD}?uploadType=resumable&part=snippet,status", body,
                {"X-Upload-Content-Type": "video/mp4", "X-Upload-Content-Length": str(size)}, raw=True)
    loc = init.headers["Location"]
    v = call(tok, "PUT", loc, data, {"Content-Type": "video/mp4"})
    vid = v["id"]
    print("Subido:", f"https://youtube.com/shorts/{vid}", "· estado:", v["status"].get("privacyStatus"),
          "· publishAt:", v["status"].get("publishAt", "-"), "· uploadStatus:", v["status"].get("uploadStatus"))
    if v["status"].get("privacyStatus") == "private" and status["privacyStatus"] == "public":
        print("AVISO: YouTube lo dejó en privado (proyecto de API sin auditar).")
    if pid:
        call(tok, "POST", f"{API}/playlistItems?part=snippet",
             {"snippet": {"playlistId": pid, "resourceId": {"kind": "youtube#video", "videoId": vid}}})
        print("Añadido a la lista", pid)
    print(json.dumps({"video_id": vid, "url": f"https://youtube.com/shorts/{vid}", "watch": f"https://youtube.com/watch?v={vid}",
                      "privacy": v["status"].get("privacyStatus"),
                      "publish_at": v["status"].get("publishAt")}, ensure_ascii=False))
    return vid


def comentar(tok, vid, texto):
    """Publica la pregunta A/B de «## 5. Comentario fijado» como comentario del canal (Jocs, 19/10/2026: más comentarios
    = más empuje del feed). La API no deja fijarlo. Cuesta 50 unidades de cuota; no repite si ya está."""
    hilos = call(tok, "GET", f"{API}/commentThreads?part=snippet&videoId={vid}&maxResults=50")
    for h in hilos.get("items", []):
        if h["snippet"]["topLevelComment"]["snippet"].get("textOriginal", "").strip() == texto.strip():
            print("YouTube: la pregunta ya estaba publicada"); return "ya estaba"
    r = call(tok, "POST", f"{API}/commentThreads?part=snippet",
             {"snippet": {"videoId": vid, "topLevelComment": {"snippet": {"textOriginal": texto}}}})
    print("YouTube: pregunta publicada como comentario", r.get("id"))
    return r.get("id")


def miniatura(vid, img):
    """thumbnails.set (50 unidades). Si el canal no está verificado por teléfono, YouTube responde 403 y el vídeo
    se queda con la miniatura automática: no es un error grave."""
    tok = token(); data = open(img, "rb").read()
    r = call(tok, "POST", f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}", data,
             {"Content-Type": "image/jpeg" if img.lower().endswith((".jpg", ".jpeg")) else "image/png"})
    print("Miniatura puesta:", json.dumps(r.get("items", r), ensure_ascii=False)[:200])


def estado(vid):
    tok = token()
    it = call(tok, "GET", f"{API}/videos?part=status,processingDetails,contentDetails&id={vid}")["items"]
    if not it:
        die(f"no existe el vídeo {vid} (o no es de este canal)")
    v = it[0]
    print(json.dumps({"id": vid, "uploadStatus": v["status"].get("uploadStatus"),
                      "processingStatus": (v.get("processingDetails") or {}).get("processingStatus"),
                      "duration": (v.get("contentDetails") or {}).get("duration"),
                      "privacy": v["status"].get("privacyStatus"), "publishAt": v["status"].get("publishAt")}))


def borrar(vid):
    tok = token()
    call(tok, "DELETE", f"{API}/videos?id={vid}", raw=True)
    print("Borrado:", vid)


if __name__ == "__main__":
    a = sys.argv[1:]
    if not a or a[0] not in ("check", "upload", "estado", "borrar", "miniatura", "comentario"):
        print(__doc__); sys.exit(1)
    if a[0] == "check":
        check()
    elif a[0] == "miniatura":
        if len(a) != 3:
            die("uso: miniatura <id_video> <img.jpg>")
        miniatura(a[1], a[2])
    elif a[0] == "comentario":
        # 19/10/2026 (vídeo largo semanal): publicar.py no se usa con el vídeo largo y no había forma de publicar
        # «## 5. Comentario fijado» desde la línea de órdenes. Uso: comentario <id_video> <ficha.md>
        if len(a) != 3:
            die("uso: comentario <id_video> <ficha.md>")
        txt = load_meta(a[2]).get("pinned_comment")
        if not txt:
            die("la ficha no tiene «## 5. Comentario fijado»: no se publica nada")
        comentar(token(), a[1], txt)
    elif a[0] in ("estado", "borrar"):
        if len(a) != 2:
            die(f"uso: {a[0]} <id_video>")
        (estado if a[0] == "estado" else borrar)(a[1])
    else:
        opts = {"dry": "--dry-run" in a}
        for k in ("privacy", "at", "playlist"):
            if f"--{k}" in a:
                opts[k] = a[a.index(f"--{k}") + 1]
        pos = [x for x in a[1:] if not x.startswith("--") and x not in opts.values()]
        if len(pos) < 2:
            die("uso: upload <video.mp4> <ficha.md|meta.json>")
        upload(pos[0], pos[1], **opts)
