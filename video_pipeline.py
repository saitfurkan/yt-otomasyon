"""Son Tanık: ses + senaryo -> tam video (kanca + ident + ana içerik + altyazı + filigran),
kapak resmi ve Shorts. Sadece ffmpeg, Pillow ve (kelime zamanları için) faster-whisper kullanır.
Dışarıya bağlanan yerler: Pexels (görüntü), Gemini (arama kelimeleri, isteğe bağlı)."""
import difflib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_SANS = "DejaVu Sans"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
_FD = os.path.join(HERE, "fonts")
FONT_HEAD = os.path.join(_FD, "Anton-Regular.ttf") if os.path.exists(os.path.join(_FD, "Anton-Regular.ttf")) else FONT_BOLD_PATH
FONT_LABEL = os.path.join(_FD, "BebasNeue-Regular.ttf") if os.path.exists(os.path.join(_FD, "BebasNeue-Regular.ttf")) else FONT_BOLD_PATH
FONT_ELEGANT = os.path.join(_FD, "AbrilFatface-Regular.ttf") if os.path.exists(os.path.join(_FD, "AbrilFatface-Regular.ttf")) else FONT_SERIF_BOLD
IDENT_SECONDS = 6.6
UA = "Mozilla/5.0 (X11; Linux x86_64)"
GENERIC_QUERIES = [
    "dark city night aerial", "courthouse exterior", "stack of documents desk", "bank building exterior",
    "counting cash money", "rain on window night", "police car lights night", "smartphone screen close up",
    "empty corridor office", "newspaper headlines", "gavel judge", "city street night traffic",
    "stock market screen", "handcuffs close up", "lawyer office documents", "security camera"]


def log(*a):
    print(*a, flush=True)


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError("komut hatası: " + " ".join(cmd[:6]) + " ...\n" + (r.stderr or "")[-1500:])
    return r


def duration(path):
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path])
    return float(r.stdout.strip())


def tr_lower(s):
    return s.replace("İ", "i").replace("I", "ı").lower()


def norm_word(w):
    return re.sub(r"[^\w]", "", tr_lower(w))


# ------------------------------------------------------------------ senaryo
def parse_script(path):
    txt = open(path, encoding="utf-8").read()
    meta = {}
    for key in ("BAŞLIK", "KAPAK", "AÇIKLAMA", "ETİKETLER"):
        m = re.search(rf"^{key}:\s*(.+)$", txt, re.M)
        if m:
            meta[key] = m.group(1).strip()
    if "BAŞLIK" not in meta:
        m = re.search(r"^# Senaryo:\s*(.+)$", txt, re.M)
        meta["BAŞLIK"] = re.sub(r"\s*\(Son Tanık\)\s*$", "", m.group(1)).strip() if m else "Son Tanık"
    m = re.search(r"## OKUMA METNİ\s*\n(.*?)(?=\n## |\Z)", txt, re.S)
    body = m.group(1) if m else txt
    paras = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    hook_n = 1
    clean = []
    for i, p in enumerate(paras):
        if p.startswith("[SON TANIK"):
            hook_n = len(clean)
            continue
        p = re.sub(r"\[duraklama\]", "", p)
        p = re.sub(r"\s+", " ", p).strip()
        if p:
            clean.append(p)
    return meta, clean, max(1, hook_n)


# ------------------------------------------------------------------ ses
def clean_voice(inputs, out_wav):
    """Parçaları birleştirir, gürültüyü azaltır, uzun sessizlikleri kısaltır, ses seviyesini sabitler."""
    args = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for f in inputs:
        args += ["-i", f]
    n = len(inputs)
    pre = "".join(f"[{i}:a]aresample=44100,aformat=channel_layouts=mono[a{i}];" for i in range(n))
    cat = "".join(f"[a{i}]" for i in range(n)) + f"concat=n={n}:v=0:a=1[c];"
    chain = ("[c]highpass=f=75,lowpass=f=12000,afftdn=nf=-28,"
             "acompressor=threshold=-20dB:ratio=3:attack=5:release=90:makeup=3,"
             "silenceremove=start_periods=1:start_threshold=-48dB:stop_periods=-1:"
             "stop_duration=1.1:stop_threshold=-48dB:stop_silence=0.4,"
             "loudnorm=I=-16:TP=-1.5:LRA=11[o]")
    run(args + ["-filter_complex", pre + cat + chain, "-map", "[o]", "-ar", "44100", "-ac", "1", out_wav])
    return out_wav


def transcribe(wav, prompt=""):
    """faster-whisper ile kelime zamanları: [(kelime, başlangıç, bitiş)]."""
    from faster_whisper import WhisperModel
    model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-f", "f32le", "-ac", "1", "-ar", "16000", "-"],
                         capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, dtype=np.float32)
    segs, _ = model.transcribe(audio, language="tr", word_timestamps=True, vad_filter=True,
                               initial_prompt=prompt[:400] or None, beam_size=5)
    words = []
    for s in segs:
        for w in (s.words or []):
            words.append((w.word.strip(), float(w.start), float(w.end)))
    return words


# ------------------------------------------------------------------ hizalama
def align(script_words, whisper_words, total):
    """Her senaryo kelimesine (başlangıç, bitiş) saniyesi verir. Eşleşmeyenler aradaki
    eşleşmelerden doğrusal ara değerle bulunur."""
    sw_ = [norm_word(w) for w in script_words]
    ww_ = [norm_word(w[0]) for w in whisper_words]
    sm = difflib.SequenceMatcher(None, sw_, ww_, autojunk=False)
    start = [None] * len(sw_)
    end = [None] * len(sw_)
    for i, j, n in sm.get_matching_blocks():
        for k in range(n):
            start[i + k] = whisper_words[j + k][1]
            end[i + k] = whisper_words[j + k][2]
    # kenarlar
    first = next((i for i, v in enumerate(start) if v is not None), None)
    if first is None:       # hiç eşleşme yok: kelimeleri eşit dağıt
        step = total / max(1, len(sw_))
        return [(i * step, (i + 1) * step) for i in range(len(sw_))]
    t0 = whisper_words[0][1] if whisper_words else 0.0
    t1 = whisper_words[-1][2] if whisper_words else total
    known = [(i, start[i], end[i]) for i in range(len(sw_)) if start[i] is not None]
    known = [(-1, t0, t0)] + known + [(len(sw_), t1, t1)]
    out = [None] * len(sw_)
    for a, b in zip(known, known[1:]):
        (ia, _, ea), (ib, sb, _) = a, b
        gap = ib - ia - 1
        for k in range(gap):
            s = ea + (sb - ea) * k / (gap + 0)
            e = ea + (sb - ea) * (k + 1) / (gap + 0)
            out[ia + 1 + k] = (s, max(e, s + 0.05))
    for i in range(len(sw_)):
        if start[i] is not None:
            out[i] = (start[i], end[i])
    return out


# ------------------------------------------------------------------ altyazı
def ass_time(t):
    t = max(0.0, t)
    h, m = int(t // 3600), int(t % 3600 // 60)
    return f"{h}:{m:02d}:{t % 60:05.2f}"


def build_subtitles(words, times, ass_path, shift_after=None, shift=0.0, t_from=0.0, t_to=1e9,
                    vertical=False, offset=0.0):
    """words: senaryo kelimeleri, times: (s,e). Metin senaryodan gelir, zaman sesten."""
    W, H = (1080, 1920) if vertical else (1920, 1080)
    size = 78 if vertical else 56
    marg = 520 if vertical else 125
    maxc = 22 if vertical else 40
    head = (f"[Script Info]\nScriptType: v4.00+\nPlayResX: {W}\nPlayResY: {H}\nWrapStyle: 2\n\n"
            "[V4+ Styles]\nFormat: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
            "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding\n"
            f"Style: Default,{FONT_SANS},{size},&H00FFFFFF,&H000000FF,&H00000000,&H64000000,1,0,0,0,100,100,0,0,1,"
            f"4,1,2,60,60,{marg},1\n\n[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n")
    lines, cur, cs = [], [], None
    for w, (s, e) in zip(words, times):
        if e < t_from or s > t_to:
            continue
        if not cur:
            cs = s
        cur.append((w, s, e))
        txt = " ".join(x[0] for x in cur)
        if len(txt) >= maxc * 2 - 6 or (re.search(r"[.!?]$", w) and len(txt) > 14) or (len(txt) > maxc and w.endswith(",")):
            lines.append(cur)
            cur = []
    if cur:
        lines.append(cur)
    events = []
    for i, ln in enumerate(lines):
        s = ln[0][1]
        e = ln[-1][2]
        if i + 1 < len(lines):
            e = min(max(e, s + 0.9), lines[i + 1][0][1] + 0.05)
        else:
            e = max(e, s + 0.9)
        txt = " ".join(x[0] for x in ln)
        if len(txt) > maxc:     # iki satır
            mid = len(txt) // 2
            cut = txt.rfind(" ", 0, mid + 6)
            cut = cut if cut > 8 else txt.find(" ", mid)
            if cut > 0:
                txt = txt[:cut] + "\\N" + txt[cut + 1:]
        txt = txt.replace("{", "(").replace("}", ")")

        def sh(t):
            t = t - offset
            if shift_after is not None and t >= shift_after:
                t += shift
            return t
        if shift_after is not None and s < shift_after:
            e = min(e, shift_after)
        events.append(f"Dialogue: 0,{ass_time(sh(s))},{ass_time(sh(e))},Default,,0,0,0,,{txt}")
    with open(ass_path, "w", encoding="utf-8") as f:
        f.write(head + "\n".join(events) + "\n")
    return ass_path


# ------------------------------------------------------------------ görüntü (Pexels)
def gemini_queries(paragraphs):
    """Her paragraf için 2 İngilizce Pexels arama cümlesi. Gemini yoksa genel liste."""
    try:
        sys.path.insert(0, HERE)
        import script_writer as sw
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("anahtar yok")
        models = sw.model_candidates(key)
        models = sorted(models, key=lambda m: "lite" not in m)
        listing = "\n".join(f"{i + 1}. {p[:220]}" for i, p in enumerate(paragraphs))
        prompt = (
            "Aşağıdaki Türkçe YouTube senaryosunun her paragrafı için, stok video sitesinde (Pexels) aranacak "
            "2 İngilizce arama cümlesi yaz. Sinematik, koyu tonlu, soyut ve atmosferik görüntüler tercih et "
            "(şehir geceleri, belgeler, bina cepheleri, ekranlar, yağmur, para, koridorlar, eller). "
            "Gerçek kişi, marka ya da logo gerektiren cümle yazma. Her cümle 2-4 kelime olsun.\n\n"
            f"{listing}\n\nSadece JSON: {{\"queries\": [[\"a\",\"b\"], ...]}} (paragraf sayısı kadar liste)")
        _, data = sw.generate(key, models, prompt, json_out=True, temperature=0.4, max_tokens=3000)
        qs = data.get("queries", [])
        out = []
        for i in range(len(paragraphs)):
            q = [x for x in (qs[i] if i < len(qs) else []) if isinstance(x, str) and x.strip()]
            out.append(q[:2] or random.sample(GENERIC_QUERIES, 2))
        return out
    except Exception as e:
        log(f"   [arama kelimeleri varsayılan] {str(e)[:100]}")
        return [random.sample(GENERIC_QUERIES, 2) for _ in paragraphs]


STYLE = ("graphic novel noir illustration, bold ink lines, dramatic chiaroscuro lighting, limited palette of black, warm grey "
         "and deep red-orange accents, stylized illustrated adult characters, painterly texture, cinematic wide composition, "
         "no text, no letters, no numbers, no logos, no signature")
AI_STATE = {"used": 0, "dead": False}


def ai_scene_prompts(paragraphs):
    """Her paragraf için 3 İngilizce sahne tarifi (yapay zeka görseli için). Başarısızsa None."""
    try:
        sys.path.insert(0, HERE)
        import script_writer as sw
        key = os.environ.get("GEMINI_API_KEY", "").strip()
        if not key:
            return None
        models = sorted(sw.model_candidates(key), key=lambda m: "lite" not in m)
        out = []
        for i in range(0, len(paragraphs), 12):
            chunk = paragraphs[i:i + 12]
            listing = "\n".join(f"{j + 1}. {p[:400]}" for j, p in enumerate(chunk))
            prompt = (
                "Aşağıdaki Türkçe belgesel anlatımının her paragrafı için, anlatılan şeyi BİREBİR gösteren 3 farklı "
                "İngilizce sahne tarifi yaz (görsel üretim yapay zekası için). Somut ol: mekân, nesne, ışık, eylem "
                "(ör. 'a bank employee's empty desk at night with a glowing computer screen showing a long row of "
                "numbers'). Gerçek kişileri, ünlüleri, marka ve logoları, yazı içeren nesneleri anlatma; insanlar "
                "gerekiyorsa arkadan, siluet ya da uzaktan göster. Karakterler her zaman yetişkin olsun (çocuk ya da genç gösterme). "
                "Her tarif tek cümle, 15-30 kelime.\n\n"
                f"{listing}\n\nSadece JSON: {{\"scenes\": [[\"a\",\"b\",\"c\"], ...]}} ({len(chunk)} liste)")
            _, data = sw.generate(key, models, prompt, json_out=True, temperature=0.5, max_tokens=6000)
            sc = data.get("scenes", [])
            for j in range(len(chunk)):
                q = [x for x in (sc[j] if j < len(sc) else []) if isinstance(x, str) and len(x) > 10]
                out.append(q[:3])
        return out
    except Exception as e:
        log(f"   [sahne tarifleri alınamadı] {str(e)[:120]}")
        return None


def cf_image(prompt, orientation, dest):
    """Cloudflare Workers AI (FLUX.1 schnell) ile görsel üretir. Kota/hata olursa None."""
    acc = os.environ.get("CF_ACCOUNT_ID", "").strip()
    tok = os.environ.get("CF_API_TOKEN", "").strip()
    if not acc or not tok or AI_STATE["dead"] or AI_STATE["used"] >= int(os.environ.get("AI_IMAGE_MAX", "100")):
        return None
    import base64
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    w, h = (1280, 720) if orientation == "landscape" else (720, 1280)
    for attempt, extra in enumerate(({},)):
        body = {"prompt": (prompt + ", " + STYLE)[:1900], "steps": 6}
        body.update(extra)
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": f"Bearer {tok}", "Content-Type": "application/json", "User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                res = json.load(r)
            img = base64.b64decode(res["result"]["image"])
            with open(dest, "wb") as f:
                f.write(img)
            AI_STATE["used"] += 1
            return dest
        except urllib.error.HTTPError as e:
            msg = e.read().decode("utf-8", "ignore")[:200]
            if e.code in (429, 402, 403) or "neurons" in msg.lower() or "limit" in msg.lower():
                log(f"   [AI görsel kotası doldu] {e.code} {msg[:100]}")
                AI_STATE["dead"] = True
                return None
            log(f"   [AI görsel hata] {e.code} {msg[:100]}")
        except Exception as e:
            log(f"   [AI görsel hata] {str(e)[:100]}")
    return None


def ai_clips(scenes, orientation, workdir, tag, need):
    out = []
    for i, sc in enumerate((scenes or [])[:need]):
        p = cf_image(sc, orientation, os.path.join(workdir, f"ai_{tag}_{i}.png"))
        if p:
            out.append({"path": p, "duration": 999, "still": True})
    return out


def mix_clips(scenes, queries, orientation, workdir, tag, d, used, search):
    """Paragraf süresine göre yapay zeka görselleri ve stok videoyu dönüşümlü dizer (hareket + konu bağı)."""
    per = 8.0
    total_n = max(1, round(d / per))
    n_ai = total_n if scenes else 0
    ai = ai_clips(scenes, orientation, workdir, tag, n_ai)
    vids = fetch_clips(queries, orientation, workdir, used, need=max(1, total_n - len(ai)) if len(ai) < total_n else 0, search=search)
    out = []
    for i in range(max(len(ai), len(vids))):
        if i < len(vids):
            out.append(vids[i])
        if i < len(ai):
            out.append(ai[i])
    return out


def pexels_search(query, orientation, key):
    url = ("https://api.pexels.com/videos/search?" + urllib.parse.urlencode(
        {"query": query, "orientation": orientation, "size": "medium", "per_page": 12}))
    req = urllib.request.Request(url, headers={"Authorization": key, "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.load(r)
    out = []
    for v in data.get("videos", []):
        files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and f.get("width")]
        if orientation == "portrait":
            ok = [f for f in files if f["height"] >= 1280]
            ok.sort(key=lambda f: f["height"])
        else:
            ok = [f for f in files if f["width"] >= 1280]
            ok.sort(key=lambda f: f["width"])
        if ok and 4 <= (v.get("duration") or 0) <= 60:
            out.append({"id": v["id"], "url": ok[0]["link"], "duration": v.get("duration", 10)})
    return out


def pixabay_search(query, orientation, key):
    url = "https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"key": key, "q": query[:100], "per_page": 20})
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=40) as r:
        data = json.load(r)
    out = []
    for v in data.get("hits", []):
        pick = None
        for size in ("medium", "small", "large"):
            f = (v.get("videos") or {}).get(size) or {}
            if f.get("url") and f.get("width"):
                ok = f["height"] >= 1280 if orientation == "portrait" else f["width"] >= 1280
                is_portrait = f["height"] > f["width"]
                if ok and is_portrait == (orientation == "portrait"):
                    pick = f
                    break
        if pick and 4 <= (v.get("duration") or 0) <= 60:
            out.append({"id": "pb%s" % v["id"], "url": pick["url"], "duration": v.get("duration", 10)})
    return out


def stock_search(query, orientation, key):
    """Pexels anahtarı varsa Pexels, yoksa Pixabay."""
    if os.environ.get("PEXELS_API_KEY", "").strip():
        return pexels_search(query, orientation, os.environ["PEXELS_API_KEY"].strip())
    return pixabay_search(query, orientation, os.environ.get("PIXABAY_API_KEY", "").strip())


def download(url, dest):
    if os.path.exists(dest):
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def fetch_clips(queries, orientation, workdir, used, need=3, search=None):
    search = search or stock_search
    key = os.environ.get("PEXELS_API_KEY", "").strip() or os.environ.get("PIXABAY_API_KEY", "").strip()
    clips = []
    for q in queries + random.sample(GENERIC_QUERIES, 3):
        if len(clips) >= need:
            break
        try:
            res = search(q, orientation, key)
        except Exception as e:
            log(f"   [pexels hata] {q}: {str(e)[:80]}")
            continue
        random.shuffle(res)
        for v in res:
            if v["id"] in used:
                continue
            try:
                p = download(v["url"], os.path.join(workdir, f"px_{v['id']}.mp4"))
            except Exception as e:
                log(f"   [indirilemedi] {v['id']}: {str(e)[:60]}")
                continue
            used.add(v["id"])
            clips.append({"path": p, "duration": duration(p)})
            if len(clips) >= need:
                break
    if not clips and used:          # yeni klip kalmadıysa eskileri tekrar kullan
        used_copy = set()
        return fetch_clips(queries, orientation, workdir, used_copy, need, search)
    return clips


MONTHS = "ocak|şubat|mart|nisan|mayıs|haziran|temmuz|ağustos|eylül|ekim|kasım|aralık"


def key_caption(text):
    """Paragraftan ekrana yazılacak kısa künye: tarih ya da büyük rakam."""
    m = re.search(rf"\b(\d{{1,2}}\s+)?({MONTHS})\s+(\d{{4}})", text, re.I)
    if m:
        return tr_upper(m.group(0))
    m = re.search(r"\b(\d[\d.,]*)\s+(milyar|milyon|bin)\s*(lira|dolar|euro|TL|\w+)?", text, re.I)
    if m:
        return tr_upper(m.group(1) + " " + m.group(2) + (" " + m.group(3) if m.group(3) else ""))
    m = re.search(r"\b(19|20)\d{2}\b", text)
    if m:
        return m.group(0)
    return None


def key_counter(text):
    m = re.search(r"\b(\d{1,3})\s+(milyar|milyon|bin)\b\s*(lira|dolar|euro|TL)?", text, re.I)
    if m and "," not in text[m.start():m.end() + 1]:
        return ("sayac", int(m.group(1)), tr_upper((m.group(2) + (" " + m.group(3) if m.group(3) else ""))))
    return None


def tr_upper(s):
    return s.replace("i", "İ").replace("ı", "I").upper()


def grade_filter(W, H, each, idx=0, caption=None, letterbox=True, still=False, geom=None):
    """Belgesel görünümü: yavaş kamera hareketi, renk düzeltme, film greni, sinema bantları, künye yazısı."""
    zoom = 1.14
    ww, hh = int(W * zoom), int(H * zoom)
    mode = idx % 4
    xe = ["(iw-ow)*t/%f" % each, "(iw-ow)*(1-t/%f)" % each, "(iw-ow)/2", "(iw-ow)/2"][mode]
    ye = ["(ih-oh)/2", "(ih-oh)/2", "(ih-oh)*t/%f" % each, "(ih-oh)*(1-t/%f)" % each][mode]
    if still:      # kare çizimi baştan sona tarayan kamera: tüm kompozisyon görünür
        if W > H:
            sc, xe, ye = f"scale={W}:-2:flags=lanczos,unsharp=5:5:0.8:3:3:0.0", "0", ("(ih-oh)*t/%f" % each) if idx % 2 == 0 else ("(ih-oh)*(1-t/%f)" % each)
        else:
            sc, ye, xe = f"scale=-2:{H}:flags=lanczos,unsharp=5:5:0.8:3:3:0.0", "0", ("(iw-ow)*t/%f" % each) if idx % 2 == 0 else ("(iw-ow)*(1-t/%f)" % each)
    else:
        sc = f"scale={ww}:{hh}:force_original_aspect_ratio=increase"
    head = geom if geom else f"{sc},crop={W}:{H}:x='{xe}':y='{ye}'"
    f = (f"{head},setsar=1,fps=30,"
         "eq=brightness=-0.05:saturation=0.85:contrast=1.1,"
         "colorbalance=rs=-0.04:bs=0.07:rh=0.07:bh=-0.05,vignette=PI/4.5,noise=alls=5:allf=t")
    if letterbox and W > H:
        bar = int(H * 0.095)
        f += f",drawbox=x=0:y=0:w=iw:h={bar}:color=black@1:t=fill,drawbox=x=0:y={H - bar}:w=iw:h={bar}:color=black@1:t=fill"
    if isinstance(caption, tuple):       # animasyonlu sayaç: ("sayac", sayı, birim)
        _, num, unit = caption
        size = 150 if W > H else 130
        y = int(H * 0.38)
        suffix = (" " + unit).replace("'", "").replace(":", "\\:")
        f += (f",drawtext=fontfile={FONT_HEAD}:text='%{{eif\\:min({num}\\,trunc(t/1.5*{num}))\\:d}}{suffix}':"
              f"fontsize={size}:fontcolor=0xE6B800:x=(w-text_w)/2:y={y}:box=1:boxcolor=black@0.55:boxborderw=34:"
              "shadowcolor=black@0.9:shadowx=4:shadowy=4:"
              "alpha='if(lt(t,0.3),0,if(lt(t,0.6),(t-0.3)/0.3,if(lt(t,3.6),1,max(0,(4.0-t)/0.4))))'")
    elif caption:
        cap = caption.replace("'", "").replace(":", "\\:")
        size = 58 if W > H else 70
        y = int(H * 0.15) if W > H else int(H * 0.2)
        f += (f",drawbox=x=60:y={y - 8}:w=10:h={size + 16}:color=0xE6B800@1:t=fill:enable='between(t,0.5,4.2)',"
              f"drawtext=fontfile={FONT_LABEL}:text='{cap}':fontsize={int(size * 1.35)}:fontcolor=white:"
              f"x=86:y={y}:shadowcolor=black@0.8:shadowx=3:shadowy=3:"
              "alpha='if(lt(t,0.5),0,if(lt(t,0.9),(t-0.5)/0.4,if(lt(t,3.8),1,max(0,(4.2-t)/0.4))))'")
    f += f",fade=t=in:st=0:d=0.35,fade=t=out:st={max(0.0, each - 0.35):.2f}:d=0.35,format=yuv420p"
    return f


def render_visual(clips, total, out_path, W, H, workdir, tag, caption=None):
    """Süre kadar klibi belgesel tonuyla birleştirir (ses yok). clips boşsa koyu animasyonlu zemin."""
    parts = []
    if not clips:
        base = f"gradients=s={W}x{H}:c0=0x0b0d12:c1=0x1b2433:speed=0.01:d={total:.2f}:r=30"
        vf = f"noise=alls=5:allf=t,format=yuv420p"
        if caption:
            cap = caption.replace("'", "").replace(":", "\\:")
            vf = f"drawtext=fontfile={FONT_BOLD_PATH}:text='{cap}':fontsize=64:fontcolor=white:x=86:y=h*0.15," + vf
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", base, "-vf", vf,
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p", out_path])
        return out_path
    any_still = any(c.get("still") for c in clips)
    n = len(clips) if any_still else max(1, math.ceil(total / 6.0))
    each = total / n
    specs = []
    for i in range(n):
        c = clips[i % len(clips)]
        if c.get("still") and each >= 3.0:        # her çizim iki plan: önce tarama, sonra yakın plan (kesme hissi)
            specs.append((c, each * 0.55, "pan"))
            specs.append((c, each * 0.45, "punch"))
        else:
            specs.append((c, each, "pan"))
    for i, (c, dur, kind) in enumerate(specs):
        p = os.path.join(workdir, f"seg_{tag}_{i}.mp4")
        cap = caption if i == 0 else None
        if kind == "punch":
            fx, fy = random.choice([0.28, 0.5, 0.72]), random.choice([0.3, 0.5, 0.7])
            N = max(2, int(dur * 30))
            if W > H:
                g = (f"scale=3200:-2:flags=lanczos,unsharp=5:5:0.8:3:3:0.0,crop=3200:1800:0:(ih-1800)*{fy},zoompan=z='1+0.4*on/{N}':"
                     f"x='{fx}*(iw-iw/zoom)':y='{fy}*(ih-ih/zoom)':d={N}:s={W}x{H}:fps=30")
            else:
                g = (f"scale=-2:3200:flags=lanczos,unsharp=5:5:0.8:3:3:0.0,crop=1800:3200:(iw-1800)*{fx}:0,zoompan=z='1+0.4*on/{N}':"
                     f"x='{fx}*(iw-iw/zoom)':y='{fy}*(ih-ih/zoom)':d={N}:s={W}x{H}:fps=30")
            vf = grade_filter(W, H, dur, i, cap, geom=g)
            src = ["-i", c["path"]]
        else:
            vf = grade_filter(W, H, dur, i + random.randint(0, 3), cap, still=bool(c.get("still")))
            if c.get("still"):
                src = ["-loop", "1", "-framerate", "30", "-i", c["path"]]
            else:
                room = max(0.0, c["duration"] - dur - 0.2)
                ss = random.uniform(0, room) if room > 0 else 0.0
                src = ["-stream_loop", "-1", "-ss", f"{ss:.2f}", "-i", c["path"]]
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + src +
            ["-t", f"{dur:.3f}", "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", p])
        parts.append(p)
    lst = os.path.join(workdir, f"list_{tag}.txt")
    with open(lst, "w") as f:
        f.write("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
         "-c", "copy", out_path])
    return out_path


# ------------------------------------------------------------------ ident
def make_ident(ident_voice, out_mp4, out_wav, workdir):
    """Karanlık ekran, yankılı ses, dalga formu -> 'SON TANIK' + sentetik vuruş. ident_voice yoksa sadece vuruş."""
    D = IDENT_SECONDS
    voice = os.path.join(workdir, "ident_voice.wav")
    if ident_voice and os.path.exists(ident_voice):
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ident_voice, "-af",
             "highpass=f=100,deesser=i=0.4:m=0.5:f=0.5,equalizer=f=150:t=q:w=1:g=2,"
             "acompressor=threshold=-20dB:ratio=2:attack=10:release=200,volume=2.2,"
             "alimiter=limit=0.8:attack=5:release=60,afade=t=in:d=0.04,apad", "-t", "4.4", "-ar", "44100", "-ac", "1", voice])
    else:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=r=44100:cl=mono", "-t", "4.4", voice])
    hit = os.path.join(workdir, "ident_hit.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=f=48:d=1.8", "-f", "lavfi", "-i", "anoisesrc=d=1.8:c=brown:a=0.5",
         "-filter_complex",
         "[0:a]afade=t=out:st=0.05:d=1.7,volume=1.4[s];[1:a]lowpass=f=300,afade=t=out:st=0:d=0.9[n];"
         "[s][n]amix=inputs=2:duration=longest,adelay=4300|4300,apad,aresample=44100[o]",
         "-map", "[o]", "-t", f"{D}", hit])
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voice, "-i", hit, "-filter_complex",
         "[0:a]apad=whole_dur=%s[v];[v][1:a]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[o]" % D,
         "-map", "[o]", "-t", f"{D}", "-ar", "44100", out_wav])
    import ident_gorsel
    base = os.path.join(workdir, "ident_base.mp4")
    ident_gorsel.render_ident_base(base, D, 4.3, FONT_ELEGANT)
    fc = ("[1:a]showwaves=s=1300x150:mode=cline:rate=30:colors=0xF0E8DA@0.9,format=yuva420p,"
          "fade=t=out:st=3.8:d=0.5:alpha=1[w];[0:v][w]overlay=(W-w)/2:905:shortest=0,"
          f"noise=alls=7:allf=t,fade=t=out:st={D - 0.3}:d=0.3,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", base, "-i", out_wav, "-filter_complex", fc, "-map", "[v]",
         "-t", f"{D}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
         "-maxrate", "6M", "-bufsize", "12M", out_mp4])
    return out_mp4, out_wav


def make_watermark(path, w=150):
    """Köşe filigranı: göz + ses çubukları (yarı saydam)."""
    from PIL import Image, ImageDraw
    SS = 4
    W, H = w * SS, int(w * 0.5 * SS) + 8 * SS
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy, ww, hh = W / 2, H / 2, W - 8 * SS, (W - 8 * SS) * 0.5
    pts = lambda: ([(cx + (-1 + 2 * i / 200) * ww / 2, cy - (1 - (-1 + 2 * i / 200) ** 2) ** 0.9 * hh / 2) for i in range(201)]
                   + [(cx + (-1 + 2 * i / 200) * ww / 2, cy + (1 - (-1 + 2 * i / 200) ** 2) ** 0.9 * hh / 2) for i in range(200, -1, -1)])
    d.polygon(pts(), fill=(255, 255, 255, 255))
    t = 3.2 * SS
    inner = Image.new("L", (W, H), 0)
    ImageDraw.Draw(inner).polygon([(cx + (x - cx) * (1 - 2 * t * 1.6 / ww), cy + (y - cy) * (1 - 2 * t * 1.2 / hh)) for x, y in pts()], fill=255)
    im.paste((0, 0, 0, 0), mask=inner)
    d = ImageDraw.Draw(im)
    bw, gap = ww * 0.055, ww * 0.105
    for k, f in enumerate((0.28, 0.5, 0.82, 0.5, 0.28)):
        x = cx + (k - 2) * gap
        ph = f * hh * 0.9 / 2
        d.rounded_rectangle([x - bw / 2, cy - ph, x + bw / 2, cy + ph], radius=bw / 2,
                            fill=(214, 40, 40, 255) if k == 2 else (255, 255, 255, 255))
    im = im.resize((W // SS, H // SS), Image.LANCZOS)
    a = im.getchannel("A").point(lambda v: int(v * 0.65))
    im.putalpha(a)
    im.save(path)
    return path


# ------------------------------------------------------------------ kapak
def make_thumbnail(frame_png, text, out_jpg, tag="DOSYA", keep_color=False):
    """Kapak: güçlü çizim, Anton başlık, altın vurgu, kırmızı bant, anahtar deliği imzası, ince çerçeve."""
    from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont, ImageOps
    W, H = 1280, 720
    GOLD, RED, CREAM = (232, 190, 70), (205, 36, 36), (248, 244, 234)
    if frame_png and os.path.exists(frame_png):
        im = Image.open(frame_png).convert("RGB")
        r = max(W / im.width, H / im.height) * 1.05
        im = im.resize((int(im.width * r), int(im.height * r)), Image.LANCZOS)
        x0 = (im.width - W) // 2
        x0 = min(im.width - W, x0 + min(90, x0))
        y0 = int((im.height - H) * 0.3) if keep_color else (im.height - H) // 2
        im = im.crop((x0, y0, x0 + W, y0 + H))
    else:
        im = Image.new("RGB", (W, H), (22, 22, 26))
    if keep_color:
        im = ImageEnhance.Contrast(ImageEnhance.Color(im).enhance(1.15)).enhance(1.15)
        im = ImageEnhance.Brightness(im).enhance(1.08).convert("RGBA")
    else:
        g = ImageOps.autocontrast(ImageOps.grayscale(im), cutoff=2)
        im = ImageOps.colorize(ImageEnhance.Contrast(g).enhance(1.25), black=(6, 6, 9), mid=(70, 62, 58), white=(236, 226, 208)).convert("RGBA")
    sh = Image.new("RGBA", (W, H))
    sd = ImageDraw.Draw(sh)
    for x in range(W):
        sd.line([(x, 0), (x, H)], fill=(3, 3, 5, int(245 * max(0.0, 1 - x / (W * 0.72)) ** 1.0)))
    for y in range(H):
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(150 * (y / H) ** 3)))
    im = Image.alpha_composite(im, sh)
    d = ImageDraw.Draw(im)
    words = text.replace("i", "İ").replace("ı", "I").upper().split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 15 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    lines = lines[:3]
    size = {1: 250, 2: 215, 3: 150}.get(len(lines), 130)
    font = ImageFont.truetype(FONT_HEAD, size)
    while size > 90 and max(d.textlength(l, font=font) for l in lines) > 760:
        size -= 6
        font = ImageFont.truetype(FONT_HEAD, size)
    lh = int(size * 1.0)
    total_h = len(lines) * lh
    y = (H - total_h) // 2 + 50
    # başlığın altına yumuşak karartma
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rectangle([30, y - 20, 840, y + total_h + 40], fill=(0, 0, 0, 120))
    im = Image.alpha_composite(im, glow.filter(ImageFilter.GaussianBlur(40)))
    d = ImageDraw.Draw(im)
    for i, ln in enumerate(lines):
        col = GOLD if i == len(lines) - 1 else CREAM
        d.text((72 + 6, y + 7), ln, font=font, fill=(0, 0, 0, 255))
        d.text((72, y), ln, font=font, fill=col)
        y += lh
    d.rectangle([72, y + 26, 72 + 210, y + 34], fill=RED)
    # imza
    kx, ky, kr = 100, 96, 19
    d.ellipse([kx - kr, ky - kr, kx + kr, ky + kr], fill=CREAM)
    d.polygon([(kx - kr * 0.5, ky + kr * 0.5), (kx + kr * 0.5, ky + kr * 0.5), (kx + kr * 0.95, ky + 58), (kx - kr * 0.95, ky + 58)], fill=CREAM)
    d.ellipse([kx - 7, ky - 7, kx + 7, ky + 7], fill=RED)
    d.text((142, 64), "SON TANIK", font=ImageFont.truetype(FONT_LABEL, 62), fill=CREAM)
    d.text((144, 118), tag, font=ImageFont.truetype(FONT_LABEL, 34), fill=GOLD)
    d.rectangle([22, 22, W - 22, H - 22], outline=(232, 190, 70, 130), width=2)
    im.convert("RGB").save(out_jpg, quality=94)
    return out_jpg


# ------------------------------------------------------------------ ana akış
def make_ambient(seconds, out_wav, seed=0):
    """Telifsiz, sentezlenmiş karanlık fon: alçak drone + rüzgâr + yavaş kalp atışı. Konuşmanın altında kısık durur."""
    d = f"{seconds + 2:.2f}"
    fc = ("[0:a]volume=0.5[d1];[1:a]volume=0.32[d2];[2:a]volume=0.22[d3];"
          "[3:a]lowpass=f=420,highpass=f=60,tremolo=f=0.15:d=0.8,volume=0.9[wind];"
          "[4:a]lowpass=f=140,apulsator=hz=1.05:amount=0.9:mode=sine,volume=0.55[beat];"
          "[d1][d2][d3][wind][beat]amix=inputs=5:duration=longest:normalize=0,"
          "lowpass=f=900,aecho=0.7:0.6:900|1700:0.3|0.2,volume=1.6[o]")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", f"sine=f=55:d={d}", "-f", "lavfi", "-i", f"sine=f=82.5:d={d}",
         "-f", "lavfi", "-i", f"sine=f=110.4:d={d}", "-f", "lavfi", "-i", f"anoisesrc=d={d}:c=pink:a=0.4:seed={seed + 7}",
         "-f", "lavfi", "-i", f"sine=f=48:d={d}", "-filter_complex", fc, "-map", "[o]", "-ar", "44100", "-ac", "1", out_wav])
    return out_wav


def mix_ambient(voice_wav, ambient_wav, out_wav, quiet_from=None, quiet_to=None):
    """Sesi fonla birleştirir; konuşma varken fon otomatik kısılır (sidechain). quiet aralığında fon yok (ident)."""
    amb = "[1:a]volume=0.55"
    if quiet_from is not None:
        amb += f",volume=enable='between(t,{quiet_from:.2f},{quiet_to:.2f})':volume=0"
        amb += f",afade=t=in:st={quiet_to:.2f}:d=3"
    amb += "[amb];"
    fc = (amb + "[amb][0:a]sidechaincompress=threshold=0.02:ratio=8:attack=20:release=400[duck];"
          "[0:a][duck]amix=inputs=2:duration=first:normalize=0,alimiter=limit=0.95[o]")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voice_wav, "-i", ambient_wav,
         "-filter_complex", fc, "-map", "[o]", "-ar", "44100", "-ac", "1", out_wav])
    return out_wav


def pick_shorts(paras, para_times, hook_n, count=3, lo=30.0, hi=58.0):
    """(başlangıç_paragraf, bitiş_paragraf) pencereleri: kanca ile başlayan 1, sonra 'bence/derim' yoğun yerler."""
    wins = []
    # 1) kanca penceresi
    i, j = 0, 0
    while j < len(paras) and para_times[j][1] - para_times[0][0] < hi:
        j += 1
    wins.append((0, max(0, j - 1)))
    # 2) puanlı pencereler
    cands = []
    for a in range(hook_n, len(paras)):
        b = a
        while b + 1 < len(paras) and para_times[b][1] - para_times[a][0] < lo:
            b += 1
        span = para_times[b][1] - para_times[a][0]
        if span < 18 or span > hi:
            continue
        txt = " ".join(paras[a:b + 1]).lower()
        score = 3 * len(re.findall(r"\bbence\b|\bderim\b|işte mesele|bilirim", txt)) + len(re.findall(r"\d", txt)) / 6
        cands.append((score, a, b))
    cands.sort(reverse=True)
    for _, a, b in cands:
        if len(wins) >= count:
            break
        if all(b < x or a > y for x, y in wins):
            wins.append((a, b))
    return wins[:count]


def render_all(script_path, voice_files, ident_voice, outdir, workdir, search=None,
               transcribe_fn=None, shorts_count=3):
    outdir, workdir = os.path.abspath(outdir), os.path.abspath(workdir)
    os.makedirs(outdir, exist_ok=True)
    os.makedirs(workdir, exist_ok=True)
    meta, paras, hook_n = parse_script(script_path)
    log(f"Senaryo: {len(paras)} paragraf, kanca {hook_n} paragraf")
    wav = clean_voice(voice_files, os.path.join(workdir, "voice.wav"))
    total = duration(wav)
    log(f"Temiz ses: {total:.0f} sn")
    words_all = [w for p in paras for w in p.split()]
    wh = (transcribe_fn or transcribe)(wav, " ".join(words_all[:60]))
    log(f"Whisper: {len(wh)} kelime")
    times = align(words_all, wh, total)
    # paragraf zamanları
    idx, para_idx = 0, []
    for p in paras:
        n = len(p.split())
        para_idx.append((idx, idx + n - 1))
        idx += n
    ptimes = []
    for k, (a, b) in enumerate(para_idx):
        s = times[a][0] if k else 0.0
        e = times[b][1]
        ptimes.append([s, e])
    for k in range(1, len(ptimes)):          # birbirine bitişik, boşluk ortadan bölünür
        mid = (ptimes[k - 1][1] + ptimes[k][0]) / 2
        ptimes[k - 1][1] = mid
        ptimes[k][0] = mid
    ptimes[-1][1] = total
    t_hook = ptimes[hook_n - 1][1]
    log(f"Kanca bitişi: {t_hook:.1f} sn")

    # ses parçaları
    hook_wav, main_wav = os.path.join(workdir, "hook.wav"), os.path.join(workdir, "main.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-t", f"{t_hook:.3f}", hook_wav])
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-ss", f"{t_hook:.3f}", main_wav])
    ident_mp4, ident_wav = make_ident(ident_voice, os.path.join(workdir, "ident.mp4"),
                                      os.path.join(workdir, "ident.wav"), workdir)
    cat = os.path.join(workdir, "audio_full.wav")
    lst = os.path.join(workdir, "alist.txt")
    with open(lst, "w") as f:
        f.write("".join(f"file '{p}'\n" for p in (hook_wav, ident_wav, main_wav)))
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst,
         "-ar", "44100", "-ac", "1", os.path.join(workdir, "audio_dry.wav")])
    try:
        amb = make_ambient(duration(os.path.join(workdir, "audio_dry.wav")), os.path.join(workdir, "ambient.wav"))
        mix_ambient(os.path.join(workdir, "audio_dry.wav"), amb, cat, t_hook, t_hook + IDENT_SECONDS)
    except Exception as e:
        log(f"   [fon sesi eklenemedi] {str(e)[:150]}")
        shutil.copy(os.path.join(workdir, "audio_dry.wav"), cat)

    # görüntüler
    queries = gemini_queries(paras)
    scenes = ai_scene_prompts(paras) if os.environ.get("CF_API_TOKEN") else None
    used = set()
    seg_files, first_clip = [], None
    hook_video = os.path.join(workdir, "hook_v.mp4")
    main_video = os.path.join(workdir, "main_v.mp4")

    def visuals_for(plist, out, tag):
        parts = []
        for k in plist:
            d = ptimes[k][1] - ptimes[k][0]
            if d < 0.3:
                continue
            nonlocal first_clip
            clips = mix_clips(scenes[k] if scenes else None, queries[k], "landscape", workdir, f"{tag}{k}", d, used, search)
            if clips and first_clip is None:
                first_clip = clips[0]["path"]
            p = os.path.join(workdir, f"{tag}_{k}.mp4")
            render_visual(clips, d, p, 1920, 1080, workdir, f"{tag}{k}", key_counter(paras[k]) or key_caption(paras[k]))
            parts.append(p)
            log(f"   paragraf {k + 1}/{len(paras)}: {d:.0f} sn, {len(clips)} klip")
        lf = os.path.join(workdir, f"v_{tag}.txt")
        with open(lf, "w") as f:
            f.write("".join(f"file '{p}'\n" for p in parts))
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lf,
             "-c", "copy", out])

    visuals_for(range(0, hook_n), hook_video, "h")
    visuals_for(range(hook_n, len(paras)), main_video, "m")
    ident_silent = os.path.join(workdir, "ident_silent.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", ident_mp4, "-an", "-c", "copy", ident_silent])
    vlist = os.path.join(workdir, "vlist.txt")
    with open(vlist, "w") as f:
        f.write("".join(f"file '{p}'\n" for p in (hook_video, ident_silent, main_video)))
    video_full = os.path.join(workdir, "video_full.mp4")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", vlist,
         "-c", "copy", video_full])

    # altyazı + filigran + son birleştirme
    ass = build_subtitles(words_all, times, os.path.join(workdir, "subs.ass"),
                          shift_after=t_hook - 0.01, shift=IDENT_SECONDS)
    t_main_start = t_hook + IDENT_SECONDS
    final = os.path.join(outdir, "video.mp4")
    ass_esc = ass.replace("\\", "/").replace(":", "\\:")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_full, "-i", cat,
         "-vf", f"ass='{ass_esc}'", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
         "-maxrate", "9M", "-bufsize", "18M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", final])
    log(f"Video hazır: {duration(final) / 60:.1f} dk")

    # kapak
    frame = os.path.join(workdir, "frame.png")
    if first_clip and first_clip.endswith(".png"):
        shutil.copy(first_clip, frame)
    elif first_clip:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", first_clip, "-vframes", "1", frame])
    cover_text = meta.get("KAPAK") or meta["BAŞLIK"].split(":")[0]
    tpath, tcolor = (frame if os.path.exists(frame) else None), False
    if scenes and scenes[0] and os.environ.get("CF_API_TOKEN"):
        tp = cf_image(scenes[0][0] + ", one dramatic stylized adult character in close-up on the right side of the frame, "
                      "large dark empty space on the left", "landscape", os.path.join(workdir, "thumb_ai.png"))
        if tp:
            tpath, tcolor = tp, True
    thumb = make_thumbnail(tpath, cover_text, os.path.join(outdir, "kapak.jpg"), keep_color=tcolor)

    # shorts
    shorts = []
    for n, (a, b) in enumerate(pick_shorts(paras, ptimes, hook_n, shorts_count), 1):
        t0, t1 = ptimes[a][0], ptimes[b][1]
        sdir = os.path.join(workdir, f"s{n}")
        os.makedirs(sdir, exist_ok=True)
        swav = os.path.join(sdir, "a.wav")
        sdry = os.path.join(sdir, "a_dry.wav")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
             "-af", "afade=t=in:d=0.05,afade=t=out:st=%.2f:d=0.4" % max(0, t1 - t0 - 0.4), sdry])
        try:
            mix_ambient(sdry, make_ambient(t1 - t0, os.path.join(sdir, "amb.wav"), n), swav)
        except Exception as e:
            log(f"   [short fon sesi eklenemedi] {str(e)[:120]}")
            shutil.copy(sdry, swav)
        parts = []
        for k in range(a, b + 1):
            d = ptimes[k][1] - ptimes[k][0]
            if d < 0.3:
                continue
            clips = mix_clips(scenes[k] if scenes else None, queries[k], "portrait", workdir, f"s{n}p{k}", d, used, search)
            p = os.path.join(sdir, f"p{k}.mp4")
            render_visual(clips, d, p, 1080, 1920, workdir, f"s{n}_{k}", key_counter(paras[k]) or key_caption(paras[k]))
            parts.append(p)
        lf = os.path.join(sdir, "l.txt")
        with open(lf, "w") as f:
            f.write("".join(f"file '{p}'\n" for p in parts))
        sv = os.path.join(sdir, "v.mp4")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lf, "-c", "copy", sv])
        sass = build_subtitles(words_all, times, os.path.join(sdir, "s.ass"), t_from=t0, t_to=t1,
                               vertical=True, offset=t0)
        out = os.path.join(outdir, f"short{n}.mp4")
        sa = sass.replace("\\", "/").replace(":", "\\:")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", sv, "-i", swav,
             "-vf", f"ass='{sa}'", "-map", "0:v", "-map", "1:a", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
             "-maxrate", "5M", "-bufsize", "10M", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out])
        first = " ".join(paras[a].split()[:9])
        shorts.append({"file": out, "from": round(t0, 1), "to": round(t1, 1), "hint": first})
        log(f"   short{n}: {t1 - t0:.0f} sn")
    info = {"video": final, "thumbnail": thumb, "shorts": shorts, "meta": meta,
            "minutes": round(duration(final) / 60, 1)}
    json.dump(info, open(os.path.join(outdir, "info.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return info


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print("kullanım: video_pipeline.py senaryo.md çıktı_klasörü ses1 [ses2 ...] [--ident dosya]")
        sys.exit(1)
    args = sys.argv[1:]
    ident = None
    if "--ident" in args:
        i = args.index("--ident")
        ident = args[i + 1]
        del args[i:i + 2]
    render_all(args[0], args[2:], ident, args[1], os.path.join(args[1], "work"))
