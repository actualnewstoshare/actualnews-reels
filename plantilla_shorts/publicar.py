#!/usr/bin/env python3
"""Publica un Short de principio a fin con UNA sola orden (15/10/2026, hilo de mejoras: menos uso del plan, mismo resultado).

  python3 publicar.py <mp4_local> <ficha.md> --dry-run    # comprueba todo sin subir nada (segundos)
  python3 publicar.py <mp4_local> <ficha.md> --ig-video <mp4_corto_local>   # experimento 26/10–01/11, días de variante B:
                                                          # YouTube sube <mp4_local> e Instagram el corte corto (25–30 s)
  python3 publicar.py <mp4_local> <ficha.md>              # publica; lánzalo con la herramienta Bash en segundo plano
                                                          # (run_in_background, timeout 7200000) y espera a que acabe.
                                                          # Si faltan más de ~110 min para la hora, sale con «relanzar» (código 3):
                                                          # se vuelve a lanzar la misma orden y sigue donde estaba, sin duplicar.

Hace, en este orden, lo mismo que SUBIR_YOUTUBE.md + SUBIR_INSTAGRAM.md, sin que la sesión tenga que vigilar nada:
 1. Comprueba el MP4 (copia local, no la de /mnt/project-files; 50–60 s) y la ficha (título ≤ 60 car., sin emojis,
    lista válida, hora futura, días de la semana coherentes con el día de publicación).
 2. YouTube: si ya hay un vídeo del canal con el mismo título subido en las últimas 12 h, NO sube otro (evita duplicados al
    relanzar) y sigue con ese. Si no, sube UNA vez, lo añade a la lista y vigila el procesado. Si a los 20 min sigue sin
    procesar, con duración 0 o en «failed»/«rejected», lo borra y sube UNA vez más la misma copia local (decisión de Jocs, 11/10).
 3. Instagram: si ya hay un Reel con ese título en las últimas 12 h, no publica otro. Si no, espera a la hora de «## 4. Programar»
    y publica Reel + historia (con los reintentos seguros de instagram_upload.py) y limpia GitHub.
 4. Publica la pregunta A/B de «## 5. Comentario fijado» como comentario: en Instagram al momento y en YouTube en cuanto el
    vídeo es público. No repite si se relanza (Jocs, 19/10/2026).
 5. Enlace al último vídeo largo (Jocs, 27/10/2026): la primera línea de la descripción del Short en YouTube anuncia el
    último vídeo largo público del canal. La API no deja poner el «vídeo relacionado» de los Shorts (lo único clicable):
    RESULTADO trae «vincular_en_studio» con la página del Short en YouTube Studio para ponerlo a mano. Si no hay vídeo
    largo o la consulta falla, el Short se sube igual, sin esa línea.
 6. Guarda una «foto» de métricas (metricas.py) para la revisión del domingo.
Al final imprime una línea «RESULTADO: {...}» con los enlaces y lo que haya fallado: con eso se escribe el mensaje final.
Antes de lanzarlo, la sesión tiene que haber añadido el repositorio con add_repo (paso 0 de SUBIR_INSTAGRAM.md).
"""
import json, os, re, subprocess, sys, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import youtube_upload as yt
import instagram_upload as ig

# 15/10/2026 (rutina de las 20:30): lanzado desde la carpeta compartida, el proceso perdió su directorio de trabajo al
# resincronizarse la carpeta y git falló («Unable to read current working directory»). Se trabaja siempre desde una carpeta local.
for _d in (os.environ.get("WORK", "/home/claude/work"), "/tmp"):
    if os.path.isdir(_d):
        os.chdir(_d); break
# La herramienta Bash corta los procesos en segundo plano a las 2 h: si falta más para la hora del Reel, publicar.py espera
# hasta ~110 min, sale con «relanzar» y la rutina lo vuelve a lanzar (no duplica nada: YouTube y el Reel tienen guardas).
LIMITE_S = 110 * 60
INICIO = time.time()

DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
LISTAS = ("nacional", "internacional", "bolsillo", "expertos", "deportes", "asamblea")


def log(*a):
    print(time.strftime("%H:%M:%S"), *a); sys.stdout.flush()


def duracion(video):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", video],
                                capture_output=True, text=True).stdout or 0)


def comprobar(video, ficha, ig_video=None):
    errores, avisos = [], []
    if ig_video:   # corte corto solo para el Reel (experimento aprobado por Jocs el 18/10/2026)
        if "/mnt/project-files/" in os.path.abspath(ig_video):
            errores.append("usa la copia LOCAL del corte corto para Instagram, no la de /mnt/project-files")
        if not os.path.isfile(ig_video):
            errores.append(f"no existe {ig_video}")
        elif not 25 <= duracion(ig_video) <= 30.5:
            avisos.append(f"el corte para Instagram dura {duracion(ig_video):.1f} s (experimento: 25–30 s)")
    if "/mnt/project-files/" in os.path.abspath(video):
        errores.append("usa la copia LOCAL del MP4 (/mnt/user-data/outputs o /home/claude/work): la de /mnt/project-files cambia tras copiarla")
    if not os.path.isfile(video):
        errores.append(f"no existe {video}")
    else:
        d = duracion(video)
        if not 50 <= d <= 60.5:
            avisos.append(f"el vídeo dura {d:.1f} s (regla: 50–60 s)")
    meta = yt.parse_ficha(ficha)
    t = meta.get("title", "")
    if not t: errores.append("la ficha no tiene título en negrita en «## 1. Título»")
    if len(t) > 60: avisos.append(f"título de {len(t)} caracteres (máximo 60)")
    for linea in meta.get("description", "").splitlines():   # relleno de palabras clave (normas de spam de YouTube, 19/10/2026)
        if not linea.lstrip().startswith("#") and linea.count(",") >= 5 and len(linea.split()) / (linea.count(",") + 1) < 3:
            errores.append(f"la descripción tiene una línea que es una lista de palabras clave («{linea[:60]}…»): escríbela como frase normal")
    if (meta.get("playlist") or "").lower() not in LISTAS:
        errores.append(f"«## 7. Lista» = «{meta.get('playlist')}»; tiene que ser una de: {', '.join(LISTAS)}")
    at = meta.get("publish_at")
    if not at:
        errores.append("falta la fecha y hora en «## 4. Programar»")
    else:
        when = datetime.strptime(at, "%Y-%m-%d %H:%M").replace(tzinfo=yt.MADRID)
        if when < datetime.now(yt.MADRID) - timedelta(minutes=5):
            avisos.append(f"la hora de «## 4. Programar» ({at}) ya pasó: se publicará al momento")
        hoy = DIAS[when.weekday()]
        txt = (t + " " + meta.get("description", "")).lower()
        otros = sorted({d for d in DIAS if re.search(rf"\b(del|este|esta|hoy)\s+{d}\b", txt) and d != hoy})
        if otros:
            errores.append(f"se publica el {hoy} {when.day} y el título o la descripción dicen «{', '.join(otros)}» (regla de fecha)")
    return meta, errores, avisos


def yt_existente(tok, titulo):
    """Vídeo del canal con el mismo título subido en las últimas 12 h (para no duplicar si se relanza)."""
    up = yt.call(tok, "GET", yt.API + "/channels?part=contentDetails&mine=true")["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    r = yt.call(tok, "GET", yt.API + f"/playlistItems?part=snippet&maxResults=10&playlistId={up}")
    lim = datetime.now(timezone.utc) - timedelta(hours=12)
    for it in r.get("items", []):
        sn = it["snippet"]
        if sn["title"].strip() == titulo.strip() and datetime.fromisoformat(sn["publishedAt"].replace("Z", "+00:00")) > lim:
            return sn["resourceId"]["videoId"]


def yt_estado(tok, vid):
    it = yt.call(tok, "GET", yt.API + f"/videos?part=status,processingDetails,contentDetails&id={vid}")["items"]
    if not it: return "desaparecido", ""
    v = it[0]
    return (v["status"].get("uploadStatus"), (v.get("processingDetails") or {}).get("processingStatus"),
            (v.get("contentDetails") or {}).get("duration") or "")


def yt_esperar(tok, vid, minutos=20):
    fin = time.time() + minutos * 60
    while time.time() < fin:
        e = yt_estado(tok, vid)
        if e[0] in ("failed", "rejected", "deleted", "desaparecido"): return False, e
        if e[0] == "processed" and e[2] not in ("", "P0D", "PT0S"): return True, e
        time.sleep(60)
    return False, yt_estado(tok, vid)


def largo(tok, res):
    """Último vídeo largo público, para la primera línea de la descripción. Nunca para la subida si falla."""
    try:
        l = yt.ultimo_largo(tok)
    except (SystemExit, Exception) as e:
        log("Vídeo largo: no se pudo consultar; el Short va sin la línea del vídeo largo:", e); return None
    if not l:
        log("Vídeo largo: el canal aún no tiene ninguno público; el Short va sin esa línea"); return None
    res["video_largo"] = l["url"]
    log("Vídeo largo que anuncia el Short:", l["titulo"], l["url"])
    return yt.cabecera_largo(l)


def youtube(video, ficha, res):
    tok = yt.token()
    titulo = yt.parse_ficha(ficha)["title"]
    vid = yt_existente(tok, titulo)
    cab = None
    if vid:
        log("YouTube: ya hay un vídeo con este título de las últimas 12 h; no subo otro:", vid)
    else:
        cab = largo(tok, res)
        vid = yt.upload(video, ficha, cabecera=cab)
    ok, e = yt_esperar(tok, vid)
    if not ok:
        log(f"YouTube: el vídeo {vid} no se procesa bien ({e}); lo borro y subo UNA vez más la copia local")
        try: yt.call(tok, "DELETE", yt.API + f"/videos?id={vid}", raw=True)
        except SystemExit: pass
        vid = yt.upload(video, ficha, cabecera=cab); res["youtube_sustituido"] = True
        ok, e = yt_esperar(tok, vid)
    res.update(youtube=f"https://youtube.com/shorts/{vid}", youtube_ok=ok, youtube_estado=" / ".join(map(str, e)))
    if res.get("video_largo"):   # el «vídeo relacionado» (clicable) solo se puede poner a mano en Studio
        res["vincular_en_studio"] = f"https://studio.youtube.com/video/{vid}/edit"
    log("YouTube:", res["youtube"], "procesado" if ok else f"PROBLEMA {e}")


def ig_existente(titulo):
    uid, tok = ig.creds()
    r = ig.call(tok, "GET", f"{ig.GRAPH}/{uid}/media", {"fields": "id,caption,timestamp,permalink,media_product_type", "limit": 10})
    lim = datetime.now(timezone.utc) - timedelta(hours=12)
    for m in r.get("data", []):
        cap = (m.get("caption") or "").split("\n")[0].strip("* ")
        if m.get("media_product_type") == "REELS" and cap == titulo.strip() and \
           datetime.fromisoformat(m["timestamp"].replace("+0000", "+00:00")) > lim:
            return m["permalink"], m["id"]


class Relanzar(Exception):
    pass


def instagram(video, ficha, res):
    meta = yt.parse_ficha(ficha); titulo = meta["title"]
    ya = ig_existente(titulo)
    if ya:
        log("Instagram: ya hay un Reel con este título de las últimas 12 h; no publico otro:", ya[0])
        res["reel"], res["reel_id"] = ya; return
    if meta.get("publish_at"):
        hora = datetime.strptime(meta["publish_at"], "%Y-%m-%d %H:%M").replace(tzinfo=yt.MADRID).timestamp()
        tope = INICIO + LIMITE_S
        if hora - 240 > tope:      # ig.upload empieza ~3 min antes de la hora
            espera = max(0, tope - time.time())
            log(f"Instagram: faltan {int((hora - time.time()) // 60)} min para el Reel; espero {int(espera // 60)} min y salgo para que la rutina me relance (límite de 2 h de Bash)")
            time.sleep(espera)
            raise Relanzar()
    r = ig.upload(video, ficha, wait=True, story=True) or {}
    res["reel"] = r.get("reel"); res["reel_id"] = r.get("reel_id"); res["historia"] = r.get("historia")


def natural(t):
    """Jocs, 19/10/2026: los «🅰️ … · 🅱️ …» quedan artificiales. Si una ficha aún los trae, se reescriben como una pregunta
    normal: «Albiol quiere ser diputado y alcalde. 🅰️ Puede con los dos · 🅱️ Debería elegir uno» →
    «Albiol quiere ser diputado y alcalde. ¿Puede con los dos o debería elegir uno?»."""
    m = re.match(r"(.*?)\s*🅰️?\s*(.+?)\s*[·|/-]?\s*🅱️?\s*(.+)$", t, re.S)
    if not m:
        return t
    pre, a, b = (x.strip(" .·") for x in m.groups())
    comunes = {"que", "debería", "deberían", "puede", "pueden", "esperar", "seguir", "sí", "no", "más", "menos", "mejor", "solo",
               "hay", "faltan", "es", "son", "el", "la", "los", "las", "un", "una", "por", "con", "sin", "subir", "bajar"}
    if b.split()[0].lower() in comunes:   # «… o debería elegir uno», pero «… o Alejandro Davidovich»
        b = b[:1].lower() + b[1:]
    q = f"¿{a} o {b}?"
    if pre.endswith("?") and not re.search(r"\b(o|u)\b", pre):   # «¿Qué prefieres?» + opciones: sobra la primera pregunta
        pre = ""
    return (pre + (". " if pre and not pre.endswith(("?", ".", "!")) else " ") + q).strip() if pre else q


def comentarios(video, ficha, res):
    """Pregunta A/B como comentario en los dos sitios. Si falla, el vídeo ya está publicado: solo se avisa."""
    meta = yt.parse_ficha(ficha)
    texto = natural(re.sub(r"\*\*|__", "", meta.get("pinned_comment") or "").strip())
    if not texto:
        log("Comentario: la ficha no trae «## 5. Comentario fijado»; no se publica nada"); return
    if res.get("reel_id"):
        uid, tok = ig.creds()
        for intento in (1, 2):   # 19/10/2026 14:00: el comentario no salió justo tras publicar y a mano sí; se reintenta al minuto
            try:
                res["comentario_ig"] = bool(ig.comentar(uid, tok, res["reel_id"], texto)); break
            except SystemExit:
                res["comentario_ig"] = False
                log(f"Comentario de Instagram: falló (intento {intento}/2, ver arriba); el Reel no se toca")
                if intento == 1: time.sleep(60)
    vid = (res.get("youtube") or "").rsplit("/", 1)[-1]
    at = meta.get("publish_at")
    if not vid or not res.get("youtube_ok"):
        return
    when = datetime.strptime(at, "%Y-%m-%d %H:%M").replace(tzinfo=yt.MADRID) if at else datetime.now(yt.MADRID)
    espera = (when - datetime.now(yt.MADRID)).total_seconds() + 90   # comentar un vídeo aún privado da error
    if espera > 15 * 60:
        log(f"Comentario de YouTube: faltan {int(espera // 60)} min para que sea público; no se publica"); res["comentario_yt"] = False; return
    if espera > 0:
        log(f"Comentario de YouTube: espero {int(espera)} s a que el vídeo sea público"); time.sleep(espera)
    try:
        res["comentario_yt"] = bool(yt.comentar(yt.token(), vid, texto))
    except SystemExit:
        res["comentario_yt"] = False; log("Comentario de YouTube: falló (ver arriba); el vídeo no se toca")


def main():
    a = sys.argv[1:]
    ig_video = None
    if "--ig-video" in a:
        i = a.index("--ig-video"); ig_video = a[i + 1] if i + 1 < len(a) else ""; del a[i:i + 2]
    pos = [x for x in a if not x.startswith("--")]
    if len(pos) != 2:
        print(__doc__); sys.exit(1)
    video, ficha = pos
    meta, errores, avisos = comprobar(video, ficha, ig_video)
    for x in avisos: log("AVISO:", x)
    for x in errores: log("ERROR:", x)
    if errores:
        print("RESULTADO:", json.dumps({"ok": False, "errores": errores}, ensure_ascii=False)); sys.exit(1)
    if "--dry-run" in a:
        yt.check(); res = {}; yt.upload(video, ficha, dry=True, cabecera=largo(yt.token(), res))
        ig.check(); ig.upload(ig_video or video, ficha, dry=True, wait=True)
        print("RESULTADO:", json.dumps({"ok": True, "dry_run": True, "avisos": avisos}, ensure_ascii=False)); return
    res = {"avisos": avisos}
    for paso in (youtube, instagram, comentarios):
        try:
            paso(ig_video or video if paso is instagram else video, ficha, res)
        except Relanzar:
            res.update(ok=False, relanzar=True, aviso="Vuelve a lanzar EXACTAMENTE la misma orden en segundo plano: YouTube ya está y no se duplica.")
            print("RESULTADO:", json.dumps(res, ensure_ascii=False)); sys.exit(3)
        except SystemExit as e:
            res[f"error_{paso.__name__}"] = f"falló (ver el registro de arriba): {e}"
            log(f"{paso.__name__}: ERROR, sigo con lo demás")
    try:
        import metricas; metricas.foto()
    except BaseException as e:
        log("métricas: no se pudo guardar la foto:", e)
    res["ok"] = bool(res.get("youtube_ok") and res.get("reel"))
    print("RESULTADO:", json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main()
