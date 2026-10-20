"""Locución 100 % local y gratuita, castellano de España, apta para uso comercial.
Modelo: Piper VITS es_ES «davefx» (dataset CC0) + fonemas espeak-ng.
Naturalidad:
  - cada frase se sintetiza aparte, con pausas de lectura reales (coma, punto, pregunta, dos puntos) y ligera variación;
  - fonemas por cláusula (palabras átonas sin acento, alófonos naturales) y números compuestos ligados
    («setentaicuatro», «veintemil») con un solo acento principal;
  - ruido de síntesis bajo (noise_scale 0,42–0,55) y penalización de tomas con siseo;
  - VITS es estocástico: se generan N tomas por frase y se elige la de entonación más viva sin artefactos
    (desviación de F0 en semitonos alta, pocos saltos de octava, sin cortes);
  - ritmo variable: el gancho y la pregunta final más pausados; el cuerpo, a ritmo de presentador;
  - las preguntas se refuerzan con un final ascendente del propio modelo («?»).
Uso: python3 pvoice.py <id> [velocidad] [tomas]
Salida: /home/claude/work/voz/<id>.mp3 (ya procesada), voz/<id>.wav y /home/claude/work/words/<id>.json (tiempos por palabra)
"""
import sys, json, re, subprocess, importlib
import numpy as np, onnxruntime as rt
from scipy.io import wavfile
DEBUG = False
USE_ASR = True
NOISE = (0.42, 0.55); NOISE_NUM = (0.4, 0.5)   # ruido de síntesis de VITS (más alto = más vivo, más bajo = más limpio y algo más plano)
USE_ASR_NOMBRES = True   # elige la toma en la que Whisper entiende los nombres extranjeros (si Whisper está instalado)
TARGET_SPREAD = None   # si se fija (semitonos), se prefiere entonación firme de presentador en vez de la más movida
ASR_REPORT = []
SEGS = []   # (texto de la frase, audio) de la última ejecución, para revisarlas con asr.py
# Cadena de audio (15/10/2026, 2.ª versión; Jocs: «sigue habiendo un poco de ruido metálico de fondo»): sin reducción de ruido
# por FFT (afftdn dejaba «ruido musical», un pitido metálico entre palabras), sin puerta (cortaba colas) y sin eco corto
# (18–31 ms coloreaba la voz como un filtro de peine). La voz de VITS ya sale limpia: solo ecualización, de-esser suave
# y compresión. La versión anterior está en /mnt/project-files/mejoras/2026-10-15/pvoice_v3_anterior.py.
# Micro de estudio de radio (20/10, aprobado por Jocs): graves cálidos, presencia, agudos suaves
FX = ("aresample=44100:resampler=soxr,highpass=f=70:p=2,lowshelf=f=160:g=5,equalizer=f=420:t=q:w=1.2:g=-2.5,"
      "equalizer=f=3500:t=q:w=1.2:g=2,highshelf=f=7000:g=-2")
D = "/home/claude/tts"; WORK = "/home/claude/work"
ESPEAK = [f"{D}/espeak/bin/espeak-ng", "-q", "-v", "es", "--ipa"]
# Palabras inglesas: se pronuncian en inglés correcto (fonemas en-us de espeak-ng). Clave en minúsculas y sin puntuación.
ENGLISH = {"fox": "Fox", "news": "News", "break": "break", "sprint": "sprint", "pole": "pole", "truth": "Truth", "social": "Social", "the": "The", "new": "New", "york": "York", "times": "Times", "openai": "Open AI",
           "financial": "Financial", "wall": "Wall", "street": "Street", "nvidia": "Nvidia", "micron": "Micron", "bloomberg": "Bloomberg",
           "nasdaq": "Nasdaq", "dow": "Dow", "jones": "Jones", "axios": "Axios", "reuters": "Reuters", "google": "Google",
           "microsoft": "Microsoft", "apple": "Apple", "amazon": "Amazon", "meta": "Meta", "tesla": "Tesla", "white": "White", "house": "House",
           "washington": "Washington", "post": "Post", "journal": "Journal", "goldman": "Goldman", "sachs": "Sachs",
           "morgan": "Morgan", "stanley": "Stanley", "jp": "JP", "s&p": "S and P", "midterms": "midterms", "chatgpt": "ChatGPT", "anthropic": "Anthropic", "trump": "Trump",
           "spacex": "Space X", "starlink": "Starlink", "league": "League", "netflix": "Netflix", "iphone": "iPhone", "black": "Black", "friday": "Friday", "premier": "Premier", "white": "White"}
# Palabras inglesas escritas como las dice un presentador español (15/10/2026, Jocs: «White House y Elon Musk suenan mal aún»).
# Mandan sobre ENGLISH: así la voz solo usa fonemas castellanos, con su acento y entonación naturales.
# Palabra inglesa nueva → añádela AQUÍ con su pronunciación española (acento escrito en la sílaba fuerte).
# 16/10/2026: elegidas entre 2–6 variantes cada una por lo bien que las entiende Whisper «small» (laboratorio en LEEME.md).
INGLES_ES = {"silver": "sílver", "rail": "réil", "white": "guáit", "house": "jáus", "wall": "uol", "street": "estrít", "elon": "ílon", "musk": "másk", "league": "líg",
             "news": "niús", "fox": "fóx", "truth": "trúz", "social": "sóchal", "new": "niú", "york": "yórk", "times": "táims",
             "post": "póust", "washington": "guásinton", "google": "gúguel", "apple": "ápel", "microsoft": "máicrosoft",
             "amazon": "ámason", "nvidia": "envídia", "bloomberg": "blúmberg", "goldman": "góldman", "sachs": "sáks",
             "stanley": "éstanli", "jones": "yóuns", "dow": "dáu", "nasdaq": "násdak", "reuters": "róiters", "openai": "óupen ei ái",
             "chatgpt": "chat ge pe té", "midterms": "mídterms", "break": "bréik", "pole": "póul", "sprint": "esprínt",
             "starlink": "estárlink", "spacex": "espéis ex", "black": "blák", "friday": "fráidei", "premier": "prémier",
             "netflix": "nétflix", "iphone": "ái fon", "financial": "fainánchal", "journal": "yérnal", "anthropic": "antrópic",
             "jp": "yei pi", "s&p": "ese an pi", "the": "de", "max": "max", "bellingham": "bélingam", "verstappen": "verstápen", "meta": "méta", "tesla": "tésla", "morgan": "mórgan", "micron": "máicron", "axios": "áxios", "trump": "trámp", "zuckerberg": "súkerberg", "bezos": "bésos", "altman": "áltman", "swift": "suíft", "jensen": "yénsen", "huang": "juáng", "harris": "járis", "kamala": "kámala", "lewis": "lúis", "bitcoin": "bitcóin", "keir": "kíer", "starmer": "estármer", "downing": "dáunin", "bowl": "bol", "james": "yéims", "jeff": "yef", "newsmax": "níusmax", "carney": "cárni", "keith": "kíz", "wilson": "uílson", "danielle": "daniél", "smith": "esmíz"}
# Siglas y nombres españoles con pronunciación fija
RESPELL = {"giorgia": "yórya", "garcía": "garzía", "cellnex": "célnex", "arcelormittal": "arcelormítal", "pp": "pepé", "psoe": "pesóe", "vox": "bóks", "ibex": "íbex", "fed": "fed", "ser": "ser",
           "ceuta": "céuta", "mohamed": "mojamed", "mohammed": "mojamed", "leclerc": "leclér", "verstappen": "verstápen", "hutíes": "jutíes", "ipc": "ipecé", "lagarde": "lagárd", "haaland": "jáland", "gravenberch": "grávenberj", "cherki": "cherkí", "anfield": "ánfild", "antonelli": "antonéli", "jordan": "yórdan", "bardella": "bardelá", "brent": "brént", "putin": "pútin", "kiev": "kíef", "masters": "másters", "zizou": "zisú", "vacherot": "vacheró", "tsitsipas": "tsitsípas", "lehecka": "léjechka", "tommy": "tómi", "paul": "pol", "taylor": "téilor", "jiri": "yíri", "efe": "éfe", "woltemade": "vóltemade", "muani": "muáni", "keita": "kéita", "asvel": "asvél", "davidovich": "dabídobich",
           # 19/10/2026 (s1700): nombres franceses como los dice un presentador español
           "lecornu": "lecorniú", "louvre": "lúvre", "laurent": "lorán", "sébastien": "sebastián", "emmanuel": "emanuel", "macron": "macrón", "euronews": "euroniús", "nuñez": "núñez",
           # 15/10/2026: nombres frecuentes en noticias, como los dice un presentador español (misma voz davefx)
           "netanyahu": "netaniáju", "biden": "báiden", "musk": "mask", "elon": "ílon", "powell": "páuel", "starmer": "stármer", "jinping": "yinpín",
           "mbappé": "embapé", "mbappe": "embapé", "bellingham": "bélingam", "hamilton": "jámilton", "norris": "nóris", "sinner": "síner",
           "djokovic": "yókovich", "lebron": "lebrón", "doncic": "dónchich", "zelenski": "selénski", "zelensky": "selénski", "vinícius": "binísius",
           "medvedev": "medbédef", "zverev": "sbérev", "piastri": "piástri", "leclerc": "leclér", "kane": "kéin", "kim": "kim", "jong": "yong", "ruud": "rud", "casper": "cásper", "daniil": "daníil"}   # Ceuta: Whisper oía «Celta» (prueba 10/10)
# Deportes y nombres extranjeros frecuentes (16/10/2026, Jocs: «Juventus y Balaídos lo ha dicho mal; seguir mejorando la naturalidad»):
# como los dice un narrador de la televisión española, escritos con ortografía castellana y el acento en la sílaba fuerte.
# Nombre nuevo → añádelo aquí; si solo sale en un Short, mejor en PRON = {"Nombre": "pronunciación"} dentro del guion.
DEPORTES = {
    # clubes
    "juventus": "yubéntus", "juve": "yúbe", "inter": "ínter", "milan": "milán", "napoli": "nápoli", "lazio": "lácio",
    "bayern": "báyern", "leverkusen": "léberkusen", "dortmund": "dórmund", "leipzig": "láipsig", "stuttgart": "estútgart",
    "eintracht": "áintraj", "schalke": "chálke", "hoffenheim": "jófenjaim", "gladbach": "gládbaj",
    "liverpool": "líberpul", "manchester": "mánchester", "city": "síti", "united": "yunáited", "chelsea": "chélsi",
    "tottenham": "tótenam", "newcastle": "niucásel", "aston": "áston", "everton": "éberton", "brighton": "bráiton",
    "fulham": "fúlam", "brentford": "bréntford", "west": "uést", "ham": "jam", "bournemouth": "bórnmuz", "nottingham": "nótingam",
    "forest": "fórest", "crystal": "crístal", "palace": "pálas", "celtic": "séltic", "rangers": "réinyers",
    "ajax": "áyax", "feyenoord": "féyenord", "galatasaray": "galatasarái", "fenerbahce": "fenerbáche", "besiktas": "besiktás",
    "psg": "pe ese yé", "saint-germain": "san yermán", "saint-gilloise": "san yiluás", "union": "unión", "anderlecht": "ánderlej",
    "lille": "lil", "lyon": "lión", "rennes": "ren", "shakhtar": "sájtar", "zagreb": "ságreb", "bodo": "bódo", "glimt": "glimt",
    "young": "yang", "boys": "bóis", "qarabag": "karabáj", "ferencvaros": "férenkvaros", "partizan": "pártisan",
    "olympiacos": "olimpiacós", "olympiakos": "olimpiacós", "paok": "páok", "salzburg": "sálsburg",
    # estadios
    "anfield": "ánfild", "trafford": "tráford", "wembley": "uémbli", "allianz": "álians", "etihad": "etijád",
    "stamford": "estámford", "montjuic": "montyuíc", "signal": "sígnal", "iduna": "idúna",
    # fútbol: jugadores y entrenadores
    "raphinha": "rafíña", "lewandowski": "lebandóski", "kylian": "kílian", "vinicius": "binísius", "jude": "yud",
    "tchouameni": "chuaméni", "rudiger": "rúdiguer", "courtois": "curtuá", "militao": "militáo", "modric": "módrich",
    "kroos": "crós", "ancelotti": "anchelóti", "xabi": "chábi", "frenkie": "frénki", "kounde": "kundé", "joan": "yoán",
    "szczesny": "chésni", "stegen": "estéguen", "griezmann": "griésman", "sorloth": "sórlot", "oblak": "óblak",
    "giuliano": "yuliáno", "lenglet": "langlé", "gallagher": "gálager", "williams": "uíliams", "barrenetxea": "barrenechéa",
    "salah": "salá", "bruyne": "bráine", "foden": "fóden", "klopp": "clop", "slot": "eslót", "odegaard": "ódegard",
    "rice": "ráis", "palmer": "pálmer", "kompany": "kompáni", "wirtz": "virts", "neuer": "nóier", "kimmich": "kímij",
    "muller": "múler", "thuram": "turám", "leao": "leáo", "pulisic": "púlisich", "dembele": "dembelé",
    "kvaratskhelia": "kvarachélia", "osimhen": "osímen", "vlahovic": "vlajóvich", "yildiz": "yíldis", "conceicao": "consesáo",
    "guler": "gúler", "gundogan": "gúndogan", "calhanoglu": "chalanólu", "lukaku": "lukáku", "joao": "yoáo",
    "haaland": "jáland", "kane": "kéin", "musiala": "musiála", "gyokeres": "yókeres", "isak": "ísak", "ekitike": "equitiqué", "ekitiké": "equitiqué", "dembélé": "dembelé", "tchouaméni": "chuaméni",
    # tenis, motor y baloncesto
    "fritz": "frits", "draper": "dréiper", "rune": "rúne", "ruud": "rud", "minaur": "miñáur", "rublev": "rúblef",
    "khachanov": "jachánof", "shelton": "chélton", "tiafoe": "tiafó", "mensik": "ménsik", "swiatek": "suiátek",
    "sabalenka": "sabalénka", "gauff": "gof", "rybakina": "ribakína", "wimbledon": "uímbledon", "roland": "rolán",
    "garros": "garós", "open": "óupen", "wells": "uéls", "indian": "índian", "gea": "yeá", "arthur": "ártur", "sekou": "sekú", "jannik": "yánik", "bridge": "brich", "wuhan": "uján", "zverev": "sbéref",
    "russell": "rásel", "mclaren": "macláren", "bull": "bul", "lawson": "lóson", "gasly": "gásli", "ocon": "ocón",
    "stroll": "estról", "albon": "álbon", "hulkenberg": "júlkenberg", "bearman": "bírman", "martin": "mártin",
    "curry": "cúrri", "jokic": "yókich", "antetokounmpo": "antetokúnmpo", "giannis": "yánis", "wembanyama": "uembañáma",
    "hezonja": "jesónia", "campazzo": "campáso", "shanghai": "shangái", "shanghái": "shangái",
}
RESPELL.update(DEPORTES)
# Fonemas a mano (IPA de espeak) para lo que la ortografía castellana no puede marcar.
# Balaídos: la voz juntaba «a-í» en diptongo («Baláidos», Whisper oía «Valleidos»); la í larga separa el hiato.
FONEMAS = {"balaídos": "balaˈiːðos", "balaidos": "balaˈiːðos",
           "shanghái": "tʃanˈɡaːi", "shanghai": "tʃanˈɡaːi",   # con «sh» y «ŋg» Whisper oía «Sendai»
           "zverev": "θβˈeɾef",
           # 20/10/2026 (revisión de los Shorts del 16 al 20): «EFE» se oía «ece» o «es»; con la f larga se oye bien
           "efe": "ˈefːe", "hamás": "xːamˈas", "hamas": "xːamˈas", "hezbolá": "xːesβolˈa", "hezbola": "xːesβolˈa", "feijóo": "fːejxˈoo", "feijoo": "fːejxˈoo",
           # 16/10/2026 (Jocs: «la palabra céntimo hay que mejorarla»): la é tónica, algo más larga, para que no se pierda el esdrújulo
           "céntimos": "θˈeːntimos", "céntimo": "θˈeːntimo", "centimos": "θˈeːntimos", "centimo": "θˈeːntimo"}                                   # «Sbérev» se oía «suére»; con θ inicial, «Sberest»
# Letras que no existen en castellano: espeak-ng se las saltaba («Modrić» → «modrik») o las leía mal.
PLIEGA = str.maketrans({"ś": "s", "ą": "a", "ę": "e", "ń": "n", "ź": "z", "ż": "z", "č": "c", "ć": "c", "š": "s", "ž": "z", "đ": "d", "ø": "o", "ö": "o", "œ": "oe", "ä": "a", "å": "a",
                        "ł": "l", "ğ": "g", "ş": "s", "ı": "i", "ã": "a", "õ": "o", "ë": "e", "ï": "i", "ý": "y", "ř": "r",
                        "ő": "o", "ű": "u", "ç": "c", "à": "a", "â": "a", "ê": "e", "è": "e", "î": "i", "ì": "i", "ô": "o",
                        "ò": "o", "û": "u", "ù": "u", "ß": "ss", "ü": "u"})
SONIDO = str.maketrans({"ś": "s", "ą": "a", "ę": "e", "ń": "n", "ź": "s", "ż": "s", "č": "ch", "ć": "ch", "š": "s", "ž": "s", "đ": "d", "ø": "o", "ö": "o", "œ": "e", "ä": "e", "å": "o",
                        "ł": "l", "ğ": "", "ş": "s", "ı": "i", "ã": "a", "õ": "o", "ë": "e", "ï": "i", "ý": "i", "ř": "r",
                        "ő": "o", "ű": "u", "ç": "s", "à": "a", "â": "a", "ê": "e", "è": "e", "î": "i", "ì": "i", "ô": "o",
                        "ò": "o", "û": "u", "ù": "u", "ß": "s"})
RARAS = re.compile(r"[śąęńźżčćšžđøöœäåłğşıãõëïýřőűçàâêîôûèìòùß]|(?<!g)ü")
VOCAL = "aeiouáéíóú"; TILDE = str.maketrans("aeiou", "áéíóú")
def plegar(w):
    """Clave de búsqueda sin letras extranjeras: «Modrić» → «modric», «Ødegaard» → «odegaard» (la «ü» de «pingüino» se queda)."""
    return re.sub(r"(?<!g)ü", "u", w).translate(PLIEGA) if RARAS.search(w) else w
def adaptar(w):
    """Nombre extranjero que no está en los diccionarios → cómo lo leería un presentador español."""
    if not RARAS.search(w) and not re.search(r"tx|sch|ck|([bdfgkmptvzs])\1", w): return w
    s = w
    m = re.search(r"([ij]?)(ić|ič)$", s)
    if m:   # eslavos: «Jokić» → «yókich», «Modrić» → «módrich»: acento en la sílaba anterior a «-ich»
        base = s[:m.start(2)]; s = (("y" + base[1:]) if base.startswith("j") else base) + "ich"
        if not re.search("[áéíóú]", base):
            k = max((i for i, c in enumerate(base) if c in VOCAL), default=-1)
            if k >= 0: s = s[:k] + s[k].translate(TILDE) + s[k + 1:]
    s = re.sub(r"(?<!g)ü", "u", s).translate(SONIDO)
    s = s.replace("tx", "ch").replace("sch", "ch").replace("ck", "k")
    return re.sub(r"([bdfgkmptvzs])\1", r"\1", s)
# Pistas para avisar de nombres extranjeros que aún no tienen pronunciación fijada
PISTAS = re.compile(r"w|sh|th|ph|tz|oo|ee|ou|ae|([bdfgkmptvzs])\1|[^aeiouáéíóúnlrsdzy]$|" + RARAS.pattern)
# Siglas, marcas, países y nombres (20/10/2026, Jocs: «añade diccionario de cómo pronunciar siglas y demás; revisa TODO: nombres,
# marcas, países»). SIGLAS solo se aplica si la palabra va en mayúsculas en el guion («UE», no «ue»), salvo las unidades.
# Siglas que espeak lee bien (OTAN, ONU, IVA, PIB, BCE, FMI, DGT, CNMV, BOE, CIS, DANA, ERTE…) no hace falta ponerlas.
SIGLAS = {"ue": "u e", "eeuu": "estados unidos", "smi": "ese eme i", "irpf": "i erre pe éfe", "ugt": "u ge té",
          "ccoo": "comisiones obreras", "erc": "e erre cé", "atp": "a te pé", "wta": "uve doble te a", "ong": "o ene gé",
          "acs": "a ce ése", "iag": "i a gé", "ia": "i a", "iu": "izquierda unida", "oms": "o eme ése", "ocde": "o ce de e",
          "ap": "a pé", "bbc": "be be cé", "cnn": "ce ene éne", "ok": "okéi", "f1": "fórmula uno", "motogp": "moto ge pé",
          "es-alert": "es alért", "eta": "éta", "ee.uu": "estados unidos", "ceo": "ceo", "ttip": "te te i pé", "sareb": "saréb",
          "cepyme": "cepíme", "ela": "éla", "lab": "lab", "cnt": "ce ene té", "cgt": "ce ge té", 
          "okdiario": "okéi diario", "laliga": "la liga", "bmw": "be eme uve doble", "byd": "bi uai di", "hbo": "ache be o",
          "tve": "te uve e", "rtve": "erre te uve e", "psg": "pe ese yé", "ume": "úme", "ine": "íne", "efe": "éfe"}
UNIDADES = {"mwh": "megavatio hora", "kwh": "kilovatio hora", "gwh": "gigavatio hora"}
# Marcas, países, ciudades y personas que espeak lee a la castellana pero mal (o la tele dice de otra forma)
NOMBRES = {
    # marcas y empresas
    "instagram": "ínstagram", "tiktok": "tíktok", "youtube": "yutúb", "whatsapp": "guatsáp", "facebook": "féisbuk",
    "twitter": "tuíter", "spotify": "espótifai", "uber": "úber", "airbnb": "erbiénbi", "playstation": "pléisteichon",
    "xbox": "équis box", "disney": "dísni", "samsung": "sámsung", "huawei": "juawéi",
    "xiaomi": "shaomí", "shein": "shéin", "temu": "témiu", "lidl": "lídel", "carrefour": "carrefúr", "ryanair": "ráianer",
    "easyjet": "ísiyet", "vueling": "buélin", "ouigo": "uígo", "volkswagen": "folsvágen", "naturgy": "náturyi",
    "vodafone": "bodafón", "orange": "oránch", "pfizer": "fáiser", "boeing": "bóing", "airbus": "érbus", "intel": "íntel",
    "blackrock": "blákrok", "paypal": "péipal", "mastercard": "mástercar", "revolut": "révolut", "gemini": "yémini",
    "copilot": "cópailot", "android": "ándroid", "windows": "güíndous", "ipad": "áipad", "gmail": "yiméil", "eurosport": "éurospor",
    "euronews": "éuroniús", "rosneft": "rosnéft", "bizum": "bísum", "glovo": "glóbo", "wallapop": "guálapop",
    # palabras inglesas habituales en noticias
    "podcast": "pódcast", "streaming": "estrímin", "influencer": "inflúenser", "influencers": "inflúensers", "startup": "estártap",
    "marketing": "márketin", "online": "onláin", "software": "sófguer", "hacker": "jáker", "hackers": "jákers", "ranking": "ránkin",
    "show": "chou", "reality": "riáliti", "trailer": "tráiler", "smartphone": "esmárfon", "selfie": "sélfi", "hashtag": "jáshtag",
    "email": "ímeil", "link": "link", "like": "láik", "look": "luk", "fake": "féik", "big": "big", "tech": "tec",
    "brexit": "bréxit", "silicon": "sílicon", "valley": "báli", "hollywood": "jóliwud", "halloween": "jalouín", "cyber": "sáiber",
    "monday": "mándei", "grammy": "grámi", "emmy": "émi", "wifi": "uifi", "wi-fi": "uifi", "bluetooth": "blútuz", "chip": "chip",
    "lobby": "lóbi", "boom": "bum", "crack": "crac", "sprint": "esprínt", "thriller": "zríler", "fan": "fan",
    # países, regiones y ciudades
    "texas": "téjas", "oklahoma": "oclajóma", "ohio": "ojáio", "oregon": "oregón", "manhattan": "manjátan", "brooklyn": "brúclin",
    "seattle": "siátel", "hawaii": "jawái", "hawái": "jawái", "hamás": "jamás", "hamas": "jamás", "hezbolá": "jesbolá",
    "hizbulá": "jisbulá", "pyongyang": "pionyáng", "hong": "jong", "kong": "kong", "xi": "si", "generalitat": "yeneralitát",
    "massachusetts": "masachúsets", "michigan": "míchigan", "wisconsin": "uiscónsin", "pensilvania": "pensilbánia",
    # personas
    "vance": "báns", "hegseth": "jégset", "leavitt": "lébit", "bessent": "bésent", "merz": "mérts", "scholz": "chólts",
    "milei": "miléi", "erdogan": "erdogán", "leyen": "láien", "rutte": "rúte", "jamenei": "jameneí", "adam": "ádam",
    "mourinho": "muríño", "aemet": "aemét", "djene": "yené", "feijóo": "feiyóo", "feijoo": "feiyóo", "giorgia": "yórya",
}
RESPELL.update(NOMBRES)
# Palabras extranjeras: sus frases van algo más despacio y se elige la toma en la que se entienden
EXTRANJERAS = (set(ENGLISH) | set(INGLES_ES) | set(RESPELL)) - {"pp", "psoe", "vox", "ibex", "fed", "ser", "ipc", "efe", "the", "new", "post",
               "social", "black", "break", "pole", "max", "kim", "jong", "brent", "masters", "putin", "kiev", "ceuta", "jordan", "paul", "tommy"}
ESPEAK_EN = [f"{D}/espeak/bin/espeak-ng", "-q", "-v", "en-us", "--ipa"]
# La voz davefx solo aprendió los fonemas del castellano: los ingleses que no existen en castellano (ɹ, æ, ʌ, ə, h, v, z…)
# le llegaban como símbolos que nunca oyó y salían sonidos raros (queja de Jocs, 12/10/2026). Se pasan al fonema castellano
# más cercano, como pronuncia un presentador español («Wall Street» → «guól estrít», «White House» → «uáit jáus»).
EN2ES = [("dʒ", "ʝ"), ("ɚ", "eɾ"), ("ɝ", "eɾ"), ("ɹ", "ɾ"), ("æ", "a"), ("ɐ", "a"), ("ɑ", "a"), ("ʌ", "a"), ("ɔ", "o"),
         ("ə", "e"), ("ɛ", "e"), ("ɜ", "e"), ("ɪ", "i"), ("ᵻ", "i"), ("ʊ", "u"), ("ː", ""), ("h", "x"), ("v", "b"),
         ("z", "s"), ("ʒ", "ʝ"), ("ɫ", "l"), ("ʔ", "")]
def ipa_en(text):
    out = subprocess.run(ESPEAK_EN, input=text, capture_output=True, text=True).stdout
    out = re.sub("[_\u035c\u0361]", "", " ".join(out.split()))
    out = re.sub(r"(?<!t)ʃ", "s", out)          # «sh» suelto → s (Washington → uásinton); «ch» (tʃ) se queda
    for a, b in EN2ES: out = out.replace(a, b)
    out = re.sub(r"(?<=[dlnstk])ie(?=\s|$)", "ia", out)   # Nvidia → enbidia
    out = re.sub(r"(^|\s)([ˈˌ]?)s([ptk])", r"\1\2es\3", out)   # «Street», «Starlink», «sprint»: e- de apoyo, como en castellano
    return out
# Lo que en un informativo español se dice en castellano (16/10/2026): cambia también en los subtítulos, que salen de este texto.
TRADUCIR = [(r"\b[Ll]a [Ww]hite [Hh]ouse\b", "la Casa Blanca"), (r"\b[Ww]hite [Hh]ouse\b", "Casa Blanca"),
            (r"\b(the )?[Pp]entagon\b", "Pentágono"), (r"\b[Ff]ederal [Rr]eserve\b", "Reserva Federal"),
            (r"\b[Ff]ormula (1|[Oo]ne)\b", "Fórmula 1"), (r"\b[Gg]rand [Pp]rix\b", "Gran Premio"),
            # precios como en la tele: «uno con ochenta y nueve euros» (misma cantidad de palabras: los subtítulos no se descuadran)
            (r"\b(\w+) coma (\w+(?: y \w+)?) (euros|céntimos)\b", r"\1 con \2 \3"),
            (r"\bEE\.UU\.(?=\s+[A-ZÁÉÍÓÚ¿¡]|\s*$)", "EEUU."), (r"\bEE\.UU\.", "EEUU")]   # «EE.UU.» no corta la frase
# Ritmo de presentador (16/10/2026, Jocs: «ajustar más las velocidades… que parezca un presentador de verdad»):
# - cada noticia arranca un poco más aguda y con una pausa antes (el «reinicio» de tono de los informativos);
# - la última frase de cada noticia cierra algo más grave; el resto varía muy poco (±0,2 semitonos);
# - frases cortas, cifras y nombres extranjeros, algo más despacio; frases largas, algo más ligeras.
CAMBIO_TEMA = ("en deportes", "en economía", "en política", "en el mundo", "y en ", "además", "mientras tanto", "por otro lado",
               "en otro orden", "y ahora", "también", "por su parte", "fuera de", "ya en ", "y fuera", "en fútbol", "en tenis",
               "en fórmula", "en baloncesto", "y por último", "por último", "en europa", "en estados unidos", "en españa", "y mientras")
def cambio_tema(frase):
    f = frase.lower().lstrip("¿¡")
    return any(f.startswith(m) for m in CAMBIO_TEMA)
def tono(a, st):
    """Sube o baja el tono «st» semitonos (remuestreo de alta calidad; el tempo se compensa al sintetizar)."""
    if abs(st) < 0.05: return a
    from scipy.signal import resample_poly
    r = 2 ** (st / 12); up = 1000; down = int(round(up * r))
    return resample_poly(a, up, down).astype(np.float32)
VDIR = f"{D}/vits-piper-es_ES-davefx-medium"
CONF = json.load(open(f"{VDIR}/es_ES-davefx-medium.onnx.json")); PID = CONF["phoneme_id_map"]; SR = CONF["audio"]["sample_rate"]
sess = rt.InferenceSession(f"{VDIR}/es_ES-davefx-medium.onnx", providers=["CPUExecutionProvider"])

NUM = set("""uno una un dos tres cuatro cinco seis siete ocho nueve diez once doce trece catorce quince dieciséis diecisiete dieciocho diecinueve
veinte veintiuno veintiuna veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete veintiocho veintinueve treinta cuarenta cincuenta
sesenta setenta ochenta noventa cien ciento doscientos trescientos cuatrocientos quinientos seiscientos setecientos ochocientos novecientos
doscientas trescientas cuatrocientas quinientas seiscientas setecientas ochocientas novecientas mil millón millones""".split())
TENS = set("treinta cuarenta cincuenta sesenta setenta ochenta noventa".split())
UNITS = set("uno una un dos tres cuatro cinco seis siete ocho nueve".split())
TEENS = set("diez once doce trece catorce quince dieciséis diecisiete dieciocho diecinueve veinte veintiuno veintidós veintitrés veinticuatro veinticinco veintiséis veintisiete veintiocho veintinueve".split())
def isnum(w): return w.lower().strip("¿?¡!.,:;…") in NUM

def ipa(text):
    out = subprocess.run(ESPEAK, input=text, capture_output=True, text=True).stdout
    return re.sub(r"[_͜͡]", "", " ".join(out.split()))

def synth(ph, speed=1.0, noise=0.5, noise_w=0.85):
    ids = PID["^"] + PID["_"]
    for c in ph:
        if c in PID: ids += PID[c] + PID["_"]
    ids += PID["$"]
    a = sess.run(None, {"input": np.array([ids], np.int64), "input_lengths": np.array([len(ids)], np.int64),
                        "scales": np.array([noise, 1.0 / speed, noise_w], np.float32)})[0]
    return np.asarray(a).ravel().astype(np.float32)

def f0_track(a, fr=0.02, lo=70, hi=300):
    n = int(SR * fr); hop = n // 2; out = []
    for i in range(0, len(a) - 2 * n, hop):
        x = a[i:i + 2 * n] - a[i:i + 2 * n].mean()
        if np.sqrt(np.mean(x ** 2)) < 0.02: out.append(np.nan); continue
        c = np.correlate(x, x, "full")[len(x) - 1:]; c /= c[0] + 1e-9
        l0, l1 = int(SR / hi), int(SR / lo); k = l0 + np.argmax(c[l0:l1])
        out.append(SR / k if c[k] > 0.45 else np.nan)
    return np.array(out)

def score(a):
    f = f0_track(a); v = f[~np.isnan(f)]
    if len(v) < 8: return -9
    st = 12 * np.log2(v / np.median(v)); jumps = np.mean(np.abs(np.diff(st)) > 5)
    spread = np.std(st); clip = np.mean(np.abs(a) > 0.98)
    S = np.abs(np.fft.rfft(a * np.hanning(len(a)))) ** 2; fq = np.fft.rfftfreq(len(a), 1 / SR)
    hiss = S[fq > 6000].sum() / (S.sum() + 1e-9)
    lively = -abs(spread - TARGET_SPREAD) if TARGET_SPREAD else min(spread, 4.5)
    return lively - 12 * jumps - 50 * clip - 60 * hiss   # entonación viva, sin saltos ni siseo

def trim(a, thr=0.008):
    """Quita el silencio de los extremos sin comerse el final de la última palabra (antes cortaba a 18 ms y las «s» finales
    quedaban secas); con fundidos cortos para que no haya «clic» al empalmar frases (15/10/2026)."""
    env = np.convolve(np.abs(a), np.ones(240) / 240, "same"); idx = np.where(env > thr)[0]
    if len(idx) == 0: return a
    a = a[max(0, idx[0] - 200): idx[-1] + int(0.06 * SR)].copy()
    fi, fo = int(0.004 * SR), int(0.025 * SR)
    a[:fi] *= np.linspace(0, 1, fi); a[-fo:] *= np.linspace(1, 0, fo)
    return a

def pronuncia(lw, w, pron={}):
    """Cómo se dice una palabra: guion (PRON) > fonemas a mano > inglés a la española > diccionarios > letras extranjeras adaptadas."""
    if lw in pron:
        v = pron[lw]; return "⟪" + v.strip("/") + "⟫" if v.startswith("/") else v
    if lw in UNIDADES: return UNIDADES[lw]
    if lw in SIGLAS and sum(c.isupper() for c in w) >= 2 and lw not in FONEMAS: return SIGLAS[lw]
    if lw in FONEMAS: return "⟪" + FONEMAS[lw] + "⟫"
    if lw in INGLES_ES: return INGLES_ES[lw]
    if lw in ENGLISH: return "⟦" + ENGLISH[lw] + "⟧"
    if lw in RESPELL: return RESPELL[lw]
    f = plegar(lw)
    if f != lw and f in RESPELL: return RESPELL[f]
    if f != lw and f in INGLES_ES: return INGLES_ES[f]
    a = adaptar(lw)
    return a if a != lw else w

def main(cid, speed=1.06, takes=6):
    mod = importlib.import_module(cid); text = getattr(mod, "VOICE", None)
    if text is None: text = " ".join(w[0] for w in json.load(open(f"{WORK}/words_el/{cid}.json")))
    for a, b in TRADUCIR:                     # lo que un presentador español dice en castellano
        text = re.sub(a, b, text)
    words = text.split(); sents = []; cur = []
    for i, w in enumerate(words):
        cur.append(i)
        if w[-1] in ".?!:" or i == len(words) - 1: sents.append(cur); cur = []
    # Frases largas (más de 14 palabras), por grupos de respiración separados en las comas (mín. 6 palabras): VITS
    # atropellaba las frases largas y Whisper las entendía peor (0,81 → 0,86 en la frase de Woltemade, 16/10/2026).
    grupos = []; cont = []; largo = []
    for s in sents:
        parts = [[]]
        for k, i in enumerate(s):
            parts[-1].append(i)
            if len(s) > 14 and words[i].endswith(",") and len(parts[-1]) >= 6 and len(s) - k - 1 >= 4: parts.append([])
        parts = [g for g in parts if g]
        for k, g in enumerate(parts): grupos.append(g); cont.append(k > 0); largo.append(len(s))
    sents = grupos
    frases = [" ".join(words[i] for i in s) for s in sents]
    inicio = [si == 0 or (not cont[si] and cambio_tema(fr)) for si, fr in enumerate(frases)]          # empieza noticia
    fin = [si + 1 < len(sents) and inicio[si + 1] for si in range(len(sents))]    # cierra noticia
    # PRON = {"Nombre": "pronunciación"} en el guion: nombres de ese Short (mandan sobre los diccionarios; entre /…/, fonemas de espeak)
    pron = {k.lower(): v for k, v in getattr(mod, "PRON", {}).items()}; avisos = set()
    SEGS.clear(); plan = []; rng = np.random.default_rng(11); audio = []; t = 0.0; timing = []
    for si, s in enumerate(sents):
        spoken = []; wph = []
        for j, i in enumerate(s):
            w = words[i]; lw = w.lower().strip("¿?¡!.,:;…«»\"“”'()")
            punct = "".join(ch for ch in w if ch in ",.:;?!…")
            sp = pronuncia(lw, w, pron)
            if sp is w and lw[:1].isalpha() and w[:1].isupper() and j > 0 and PISTAS.search(lw): avisos.add(w.strip("¿?¡!.,:;…«»\"“”'()"))
            core = sp.strip("¿?¡!.,:;…«»\"“”'()").replace("¿", "").replace("¡", "")
            nxt = words[s[j + 1]].lower().strip("¿?¡!.,:;…") if j + 1 < len(s) else ""
            prv = words[s[j - 1]].lower().strip("¿?¡!.,:;…") if j > 0 else ""
            nx2 = words[s[j + 2]].lower().strip("¿?¡!.,:;…") if j + 2 < len(s) else ""
            glue = ""
            if lw in TENS and nxt == "y" and nx2 in UNITS and not punct: glue = "i"        # setenta y cuatro -> setentaicuatro
            elif lw == "y" and prv in TENS and nxt in UNITS: core = ""                      # la «y» ya va pegada
            elif (lw in UNITS or lw in TEENS or lw in TENS) and nxt == "mil" and not punct: glue = "+"   # veinte mil -> veintemil
            if lw in ("dos", "tres", "seis") and prv == "y" and j >= 2 and words[s[j - 2]].lower() in TENS:
                core = {"dos": "dós", "tres": "trés", "seis": "séis"}[lw] + core[len(lw):]   # treintaitrés, con acento final
            spoken.append((core, glue, punct)); wph.append(max(1, len(core)) + (3 if punct else 0))
        txt = ""
        for core, glue, punct in spoken:
            if not core: continue
            txt += core + ("" if glue == "+" else glue) + ("" if glue else punct + " ")
        clauses = re.split(r"([,.:;?!…])", txt); ph = ""
        for k in range(0, len(clauses), 2):
            c = clauses[k].strip(); pu = clauses[k + 1] if k + 1 < len(clauses) else ""
            if c:
                c = c.replace("⟧ ⟦", " ")          # nombres ingleses de varias palabras, de una vez
                eng = re.findall(r"⟦[^⟧]*⟧|⟪[^⟫]*⟫", c)   # ⟦inglés⟧ y ⟪fonemas a mano⟫, en orden
                es = ipa(re.sub(r"⟦[^⟧]*⟧|⟪[^⟫]*⟫", "tatata", c))  # el castellano se fonemiza con su contexto completo
                for e in eng: es = re.sub(r"[ˈˌ]?t[ˈˌ]?a[ˈˌ]?t[ˈˌ]?a[ˈˌ]?t[ˈˌ]?a", lambda _m, e=e: ipa_en(e[1:-1]) if e[0] == "⟦" else e[1:-1], es, count=1)
                seg = [es]
                ph += " ".join(seg) + pu.replace("…", ",").replace(";", ",") + " "
        ph = ph.strip()
        # Sinalefa (20/10/2026, Jocs: «fallos enlazando palabras»): vocal igual al final y al principio de dos palabras seguidas
        # se dice una sola vez, algo más larga («deja la alcaldía» → «dejalaːlcaldía»; antes se oía «deja al arca el día»).
        ph = re.sub(r"([aeiouɛɔ]) ([ˈˌ]?)\1(?!ː)", r"\2\1ː", ph)
        if cont[si]: ph = re.sub(r"^ˌ", "ˈ", ph)   # grupo que empieza tras una coma («hasta…»): primera palabra con su acento, sin tragársela
        if DEBUG: print(ph)
        q = words[s[-1]].endswith("?")
        # con cifras, ritmo más regular (menos variación de duración entre sílabas): los números salían a trompicones (Jocs, 12/10/2026)
        nums = sum(isnum(words[i]) for i in s) >= 2
        ext = [w for w in (words[i].lower().strip("¿?¡!.,:;…") for i in s) if w in EXTRANJERAS or w in pron or plegar(w) in EXTRANJERAS
               or w in FONEMAS or adaptar(w) != w]
        f = 0.93 if si == 0 or q else 1.0                      # gancho y pregunta, más pausados
        f *= min(1.04, max(0.95, 0.97 + 0.005 * (largo[si] - 10)))   # frase corta, más despacio; larga, más ligera
        # cifras y nombres extranjeros, que se entiendan; los precios y porcentajes, más pausados aún (16/10/2026, Jocs: «el "hasta"
        # antes del 1,89 € del diésel casi no se escucha, demasiado atropellado»: iba a 6,7 sílabas/s)
        precio = nums and any(words[i].lower().strip("¿?¡!.,:;…") in ("euros", "euro", "céntimos", "ciento", "dólares") for i in s)
        f *= (0.88 if precio else 0.95 if nums else 1.0) * (0.97 if ext else 1.0)
        st = 0.5 if inicio[si] else (-0.4 if fin[si] and not q else float(rng.uniform(-0.2, 0.2)))
        r = 2 ** (st / 12)
        nw = (0.6, 0.72) if nums else (0.8, 0.95); ns = NOISE_NUM if nums else NOISE
        takes_ = [trim(tono(synth(ph, speed * f / r * rng.uniform(0.98, 1.02), noise=rng.uniform(*ns), noise_w=rng.uniform(*nw)), st))
                  for _ in range(takes)]
        plan.append((s, wph, takes_, ext))
    if avisos: print("  ⚠ nombres que pueden sonar mal (añádelos a PRON del guion o a DEPORTES/RESPELL):", ", ".join(sorted(avisos)))
    choice = []
    if USE_ASR_NOMBRES and not USE_ASR and any(p[3] for p in plan):
        # Frases con nombres extranjeros: de las tomas, la que Whisper entiende con el nombre bien escrito (16/10/2026).
        # Si Whisper no está instalado, se elige como siempre.
        try:
            import asr, os, unicodedata
            def pl(t):
                t = unicodedata.normalize("NFD", t.lower()); return "".join(c for c in t if c.isalnum() or c == " ")
            files = []
            for pi, (s, wph, tk, ext) in enumerate(plan):
                if ext:
                    for ti, a in enumerate(tk):
                        fn = f"/tmp/pv_n_{pi}_{ti}.wav"; wavfile.write(fn, SR, (a / (np.abs(a).max() + 1e-9) * 0.9 * 32767).astype(np.int16)); files.append(fn)
            hyp = iter(asr.transcribe(files))
            for s, wph, tk, ext in plan:
                if not ext: choice.append(max(tk, key=score)); continue
                txt = " ".join(words[i] for i in s)
                sc = [(sum(pl(e) in pl(h) for e in ext), round(asr.sim(txt, h)[0], 2), score(a), a) for a, h in ((a, next(hyp)) for a in tk)]
                best = max(sc, key=lambda x: (x[0], x[1], x[2])); choice.append(best[3])
                print(f"  nombres {best[0]}/{len(ext)} en la mejor de {len(tk)} tomas: {' '.join(ext)}")
            for fn in files: os.remove(fn)
        except Exception as e:
            print("Whisper no disponible para elegir tomas con nombres:", e); choice = []
    if choice:
        pass
    elif USE_ASR:
        import asr, os
        files = []
        for pi, (s, wph, tk, _) in enumerate(plan):
            for ti, a in enumerate(tk):
                f = f"/tmp/pv_take_{pi}_{ti}.wav"; wavfile.write(f, SR, (a / (np.abs(a).max() + 1e-9) * 0.9 * 32767).astype(np.int16)); files.append(f)
        hyp = iter(asr.transcribe(files)); report = []
        for s, wph, tk, _ in plan:
            txt = " ".join(words[i] for i in s); scored = []
            for a in tk:
                r, ea, eb = asr.sim(txt, next(hyp)); scored.append((round(r, 2), score(a), a, eb))
            best = max(scored, key=lambda x: (x[0], x[1])); choice.append(best[2]); report.append((best[0], txt, best[3]))
        for f in files: os.remove(f)
        ASR_REPORT.clear(); ASR_REPORT.extend(report)
        print("inteligibilidad media (Whisper):", round(float(np.mean([r[0] for r in report])), 3))
        for r, txt, got in report:
            if r < 0.9: print(f"  ⚠ {r:.2f} | {txt}\n          | oído: {got}")
    else:
        choice = [max(tk, key=score) for s, wph, tk, _ in plan]
    for si, ((s, wph, tk, _), a) in enumerate(zip(plan, choice)):
        SEGS.append((" ".join(words[i] for i in s), a)); dur = len(a) / SR; lead = 0.03; usable = dur - lead - 0.08; tot = sum(wph); c = 0
        for i, n in zip(s, wph):
            a0 = t + lead + usable * c / tot; c += n; a1 = t + lead + usable * c / tot
            timing.append([words[i], round(a0, 3), round(a1 - 0.03, 3)])
        last = words[s[-1]][-1]
        # pausas de presentador: más cortas que antes (0,34 s tras punto) para que el texto fluya (Jocs, 12/10/2026)
        pause = {"?": 0.38, ".": 0.28, "!": 0.28, ":": 0.2}.get(last, 0.16) + rng.uniform(-0.03, 0.03)
        if si == 0 and last in ".!": pause += 0.06           # el titular se deja respirar
        if si + 1 < len(plan) and inicio[si + 1] and last in ".!?": pause += 0.18   # antes de la siguiente noticia
        audio.append(a); audio.append(np.zeros(int(pause * SR), np.float32)); t += dur + pause
    full = np.concatenate(audio[:-1]); full = full / (np.max(np.abs(full)) + 1e-9) * 0.89
    wavfile.write(f"{WORK}/voz/{cid}.wav", SR, (full * 32767).astype(np.int16))
    json.dump(timing, open(f"{WORK}/words/{cid}.json", "w"), ensure_ascii=False)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", f"{WORK}/voz/{cid}.wav", "-af", FX, "-ac", "1", "-b:a", "192k", f"{WORK}/voz/{cid}.mp3"], check=True)
    print(cid, "dur", round(len(full) / SR, 2), "palabras", len(timing))

if __name__ == "__main__":
    # python3 pvoice.py <id> [velocidad=1.0] [tomas=8] [voz=davefx | em_alex]
    # VOZ DEL CANAL: Piper «davefx» (la de la tanda de las 12:18 del 9/10, elegida por el usuario). Kokoro queda como alternativa.
    sys.path.insert(0, WORK); sys.path.insert(0, D)
    voice = sys.argv[4] if len(sys.argv) > 4 else "davefx"
    if voice == "davefx":
        USE_ASR = False          # misma elección de tomas que la versión aprobada (entonación viva, sin siseo)
    else:
        import kokoro_backend; kokoro_backend.install(sys.modules[__name__], voice)
    main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 1.0, int(sys.argv[3]) if len(sys.argv) > 3 else 8)
