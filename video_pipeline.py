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
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_SANS = "DejaVu Sans"
FONT_BOLD_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSansCondensed-Bold.ttf"
FONT_SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
IDENT_SECONDS = 5.5
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
    segs, _ = model.transcribe(wav, language="tr", word_timestamps=True, vad_filter=True,
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
    marg = 520 if vertical else 80
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


def download(url, dest):
    if os.path.exists(dest):
        return dest
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def fetch_clips(queries, orientation, workdir, used, need=3, search=pexels_search):
    key = os.environ.get("PEXELS_API_KEY", "").strip()
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


def grade_filter(W, H):
    return (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps=30,"
            "eq=brightness=-0.07:saturation=0.72:contrast=1.1,vignette=PI/5,format=yuv420p")


def render_visual(clips, total, out_path, W, H, workdir, tag):
    """Süre kadar klibi koyu tonla birleştirir (ses yok). clips boşsa koyu animasyonlu zemin."""
    parts = []
    if not clips:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             f"gradients=s={W}x{H}:c0=0x0b0d12:c1=0x1b2433:speed=0.01:d={total:.2f}:r=30",
             "-c:v", "libx264", "-preset", "ultrafast", "-crf", "24", "-pix_fmt", "yuv420p", out_path])
        return out_path
    n = max(1, math.ceil(total / 7.0))
    each = total / n
    for i in range(n):
        c = clips[i % len(clips)]
        room = max(0.0, c["duration"] - each - 0.2)
        ss = random.uniform(0, room) if room > 0 else 0.0
        p = os.path.join(workdir, f"seg_{tag}_{i}.mp4")
        vf = grade_filter(W, H)
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-stream_loop", "-1", "-ss", f"{ss:.2f}",
             "-i", c["path"], "-t", f"{each:.3f}", "-an", "-vf", vf, "-c:v", "libx264",
             "-preset", "ultrafast", "-crf", "24", p])
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
             "highpass=f=80,lowpass=f=6500,afftdn=nf=-30,loudnorm=I=-19:TP=-2,"
             "aecho=0.8:0.88:70|140|230:0.45|0.3|0.18,apad", "-t", "3.2", "-ar", "44100", "-ac", "1", voice])
    else:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
             "anullsrc=r=44100:cl=mono", "-t", "3.2", voice])
    hit = os.path.join(workdir, "ident_hit.wav")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
         "-f", "lavfi", "-i", "sine=f=48:d=1.8", "-f", "lavfi", "-i", "anoisesrc=d=1.8:c=brown:a=0.5",
         "-filter_complex",
         "[0:a]afade=t=out:st=0.05:d=1.7,volume=1.4[s];[1:a]lowpass=f=300,afade=t=out:st=0:d=0.9[n];"
         "[s][n]amix=inputs=2:duration=longest,adelay=3200|3200,apad,aresample=44100[o]",
         "-map", "[o]", "-t", f"{D}", hit])
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", voice, "-i", hit, "-filter_complex",
         "[0:a]apad=whole_dur=%s[v];[v][1:a]amix=inputs=2:duration=longest:normalize=0,alimiter=limit=0.95[o]" % D,
         "-map", "[o]", "-t", f"{D}", "-ar", "44100", out_wav])
    fc = ("[0:a]showwaves=s=1400x260:mode=cline:rate=30:colors=0xFFFFFF@0.95,format=yuva420p,"
          "fade=t=out:st=2.7:d=0.6:alpha=1[w];"
          f"color=c=0x050608:s=1920x1080:d={D}:r=30[bg];[bg][w]overlay=(W-w)/2:(H-h)/2:shortest=0,"
          f"drawtext=fontfile={FONT_SERIF_BOLD}:text='SON TANIK':fontsize=150:fontcolor=white:"
          "x=(w-text_w)/2:y=(h-text_h)/2-10:alpha='if(lt(t,3.1),0,min(1,(t-3.1)/0.5))',"
          f"drawbox=x=(iw-300)/2:y=ih/2+95:w=300:h=4:color=0xC0392B@1:t=fill:"
          "enable='gte(t,3.4)',format=yuv420p[v]")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", out_wav, "-filter_complex", fc, "-map", "[v]",
         "-t", f"{D}", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", out_mp4])
    return out_mp4, out_wav


# ------------------------------------------------------------------ kapak
def make_thumbnail(frame_png, text, out_jpg):
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    W, H = 1280, 720
    if frame_png and os.path.exists(frame_png):
        im = Image.open(frame_png).convert("RGB")
        r = max(W / im.width, H / im.height)
        im = im.resize((int(im.width * r), int(im.height * r)))
        im = im.crop(((im.width - W) // 2, (im.height - H) // 2, (im.width - W) // 2 + W, (im.height - H) // 2 + H))
    else:
        im = Image.new("RGB", (W, H), (14, 16, 22))
    im = im.filter(ImageFilter.GaussianBlur(1.2))
    over = Image.new("RGBA", (W, H))
    d = ImageDraw.Draw(over)
    for x in range(W):
        a = int(215 * (1 - x / W) ** 0.8) + 25
        d.line([(x, 0), (x, H)], fill=(0, 0, 0, min(235, a)))
    im = Image.alpha_composite(im.convert("RGBA"), over).convert("RGB")
    d = ImageDraw.Draw(im)
    words = text.upper().split()
    lines, cur = [], ""
    for w in words:
        if len(cur) + len(w) + 1 > 12 and cur:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + " " + w).strip()
    if cur:
        lines.append(cur)
    lines = lines[:4]
    size = 150 if len(lines) <= 2 else 118
    font = ImageFont.truetype(FONT_BOLD_PATH, size)
    y = (H - len(lines) * (size + 8)) // 2 - 10
    for i, ln in enumerate(lines):
        col = (255, 214, 10) if i == len(lines) - 1 else (255, 255, 255)
        x = 60
        for dx in range(-6, 7, 3):
            for dy in range(-6, 7, 3):
                d.text((x + dx, y + dy), ln, font=font, fill=(0, 0, 0))
        d.text((x, y), ln, font=font, fill=col)
        y += size + 8
    tag = ImageFont.truetype(FONT_BOLD_PATH, 40)
    d.rectangle([0, H - 86, 360, H], fill=(192, 57, 43))
    d.text((24, H - 76), "SON TANIK", font=tag, fill=(255, 255, 255))
    im.save(out_jpg, quality=90)
    return out_jpg


# ------------------------------------------------------------------ ana akış
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


def render_all(script_path, voice_files, ident_voice, outdir, workdir, search=pexels_search,
               transcribe_fn=None, shorts_count=3):
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
         "-ar", "44100", "-ac", "1", cat])

    # görüntüler
    queries = gemini_queries(paras)
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
            clips = fetch_clips(queries[k], "landscape", workdir, used, need=3, search=search)
            nonlocal first_clip
            if clips and first_clip is None:
                first_clip = clips[0]["path"]
            p = os.path.join(workdir, f"{tag}_{k}.mp4")
            render_visual(clips, d, p, 1920, 1080, workdir, f"{tag}{k}")
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
    wm = (f"drawtext=fontfile={FONT_BOLD_PATH}:text='SON TANIK':fontsize=30:fontcolor=white@0.55:"
          f"x=w-text_w-36:y=30:enable='gte(t,{t_main_start:.2f})'")
    final = os.path.join(outdir, "video.mp4")
    ass_esc = ass.replace("\\", "/").replace(":", "\\:")
    run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", video_full, "-i", cat,
         "-vf", f"ass='{ass_esc}',{wm}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", final])
    log(f"Video hazır: {duration(final) / 60:.1f} dk")

    # kapak
    frame = os.path.join(workdir, "frame.png")
    if first_clip:
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-ss", "1", "-i", first_clip, "-vframes", "1", frame])
    cover_text = meta.get("KAPAK") or meta["BAŞLIK"].split(":")[0]
    thumb = make_thumbnail(frame if os.path.exists(frame) else None, cover_text, os.path.join(outdir, "kapak.jpg"))

    # shorts
    shorts = []
    for n, (a, b) in enumerate(pick_shorts(paras, ptimes, hook_n, shorts_count), 1):
        t0, t1 = ptimes[a][0], ptimes[b][1]
        sdir = os.path.join(workdir, f"s{n}")
        os.makedirs(sdir, exist_ok=True)
        swav = os.path.join(sdir, "a.wav")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", wav, "-ss", f"{t0:.3f}", "-to", f"{t1:.3f}",
             "-af", "afade=t=in:d=0.05,afade=t=out:st=%.2f:d=0.4" % max(0, t1 - t0 - 0.4), swav])
        parts = []
        for k in range(a, b + 1):
            d = ptimes[k][1] - ptimes[k][0]
            if d < 0.3:
                continue
            clips = fetch_clips(queries[k], "portrait", workdir, used, need=2, search=search)
            p = os.path.join(sdir, f"p{k}.mp4")
            render_visual(clips, d, p, 1080, 1920, workdir, f"s{n}_{k}")
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
        wms = (f"drawtext=fontfile={FONT_BOLD_PATH}:text='SON TANIK':fontsize=44:fontcolor=white@0.6:"
               "x=(w-text_w)/2:y=120")
        run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", sv, "-i", swav,
             "-vf", f"ass='{sa}',{wms}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
             "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", out])
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
