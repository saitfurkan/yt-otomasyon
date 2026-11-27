"""Wikimedia Commons'tan lisansı uygun GERÇEK yer/nesne fotoğrafları (stadyum, şehir, belge, harita...).
Kişi fotoğrafı çekilmez: sorguları senaryo yazarı yer/nesne olarak verir, ayrıca portre/kişi kategorileri elenir.
Her görselin atıfı (yazar, lisans, bağlantı) toplanır ve video açıklamasına yazılır."""
import html
import json
import os
import re
import time
import urllib.parse
import urllib.request

UA = "SonTanikBot/1.0 (https://github.com/saitfurkan/yt-otomasyon; belgesel kanali) python-urllib"
API = "https://commons.wikimedia.org/w/api.php"
OK_LIC = ("cc by", "cc-by", "cc0", "public domain", "pd", "cc zero", "attribution")
BAD_WORDS = ("portrait", "headshot", "posing", "selfie", "interview", "press conference", "signing", "autograph", "close-up of")


def _get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            return urllib.request.urlopen(req, timeout=60).read()
        except Exception:
            time.sleep(2 * (i + 1))
    return None


def _clean(t):
    return html.unescape(re.sub(r"<[^>]+>", "", t or "")).strip()


def search(query, limit=14, min_w=2400, person=False):
    q = urllib.parse.urlencode({
        "action": "query", "format": "json", "generator": "search", "gsrsearch": f"{query} filetype:bitmap",
        "gsrnamespace": "6", "gsrlimit": str(limit), "prop": "imageinfo",
        "iiprop": "url|size|mime|extmetadata", "iiurlwidth": "3840"})
    raw = _get(API + "?" + q)
    if not raw:
        return []
    pages = (json.loads(raw).get("query") or {}).get("pages") or {}
    out = []
    for p in pages.values():
        ii = (p.get("imageinfo") or [{}])[0]
        if ii.get("mime") not in ("image/jpeg", "image/png") or ii.get("width", 0) < (1000 if person else min_w):
            continue
        if not person and ii["width"] < ii.get("height", 0) * 1.15:            # yatay kadraj
            continue
        md = ii.get("extmetadata") or {}
        lic = _clean((md.get("LicenseShortName") or {}).get("value", ""))
        title = p.get("title", "")
        cats = _clean((md.get("Categories") or {}).get("value", "")).lower()
        desc = _clean((md.get("ImageDescription") or {}).get("value", "")).lower()
        blob = (title + " " + cats + " " + desc).lower()
        if not any(k in lic.lower() for k in OK_LIC):
            continue
        if person:
            full = re.sub(r"\s+", " ", query.lower()).strip()
            if not re.sub(r"^file:", "", title.lower()).strip().startswith(full):   # dosya adı kişinin tam adıyla başlamıyorsa (grup fotoğrafı, başka kişi) alınmaz
                continue
        elif any(b in blob for b in BAD_WORDS):
            continue
        out.append({"title": title, "url": ii.get("thumburl") or ii["url"], "page": ii.get("descriptionurl", ""),
                    "author": _clean((md.get("Artist") or {}).get("value", "")) or "Bilinmiyor", "license": lic,
                    "w": ii["width"], "index": p.get("index", 99)})
    out.sort(key=lambda x: (x["index"], -x["w"]))
    return out


def to_canvas(src, dst, W=3840, H=2160):
    """Her fotoğrafı ekranı tam dolduran 16:9 kareye çevirir: 16:9'a yakınsa doldur-kırp, değilse bulanık arka plan + ortada tam kadraj."""
    from PIL import Image, ImageFilter
    im = Image.open(src).convert("RGB")
    r = im.width / im.height
    def cover(img):
        s = max(W / img.width, H / img.height)
        img = img.resize((int(img.width * s) + 1, int(img.height * s) + 1), Image.LANCZOS)
        x, y = (img.width - W) // 2, (img.height - H) // 2
        return img.crop((x, y, x + W, y + H))
    if 1.4 <= r <= 2.4:
        out = cover(im)
    else:
        bg = cover(im.resize((max(8, im.width // 8), max(8, im.height // 8)))).filter(ImageFilter.GaussianBlur(30))
        bg = Image.eval(bg, lambda v: int(v * 0.55))
        s = min(W * 0.94 / im.width, H * 0.94 / im.height)
        fg = im.resize((int(im.width * s), int(im.height * s)), Image.LANCZOS)
        out = bg.copy()
        out.paste(fg, ((W - fg.width) // 2, (H - fg.height) // 2))
    out.save(dst, quality=93)
    return dst


def fetch_map(spec, workdir, per_query=2):
    """spec: [(anahtar, sorgu, kişi_mi)]. Dönüş: {anahtar: [ {path, credit} ]} (16:9 tuvallere çevrilmiş)."""
    res = {}
    os.makedirs(workdir, exist_ok=True)
    for key, q, person in spec:
        got = []
        for it in search(q, person=person):
            if len(got) >= per_query:
                break
            data = _get(it["url"])
            if not data or len(data) < 30000:
                continue
            base = os.path.join(workdir, re.sub(r"[^a-z0-9]+", "_", (key + "_" + q).lower())[:40] + f"_{len(got)}")
            try:
                open(base + "_raw.jpg", "wb").write(data)
                to_canvas(base + "_raw.jpg", base + ".jpg")
            except Exception:
                continue
            got.append({"path": base + ".jpg", "credit": f"Görsel: {it['author'][:45]}, {it['license']}, {it['page']}"})
            time.sleep(1)
        res.setdefault(key, []).extend(got)
    return res


def fetch(queries, workdir, per_query=3):
    """queries: ['Brentford Community Stadium', ...]. Dönüş: {sorgu: [ {path, credit} ]}"""
    res = {}
    os.makedirs(workdir, exist_ok=True)
    for q in queries:
        got = []
        for k, it in enumerate(search(q)):
            if len(got) >= per_query:
                break
            data = _get(it["url"])
            if not data or len(data) < 40000:
                continue
            path = os.path.join(workdir, re.sub(r"[^a-z0-9]+", "_", q.lower())[:30] + f"_{len(got)}.jpg")
            with open(path, "wb") as f:
                f.write(data)
            got.append({"path": path, "credit": f"{re.sub(r'^File:', '', it['title'])} — {it['author'][:60]}, {it['license']}, {it['page']}"})
            time.sleep(1)
        res[q] = got
    return res


MUSIC_QUERIES = ["dark ambient", "cinematic ambient", "suspense soundtrack", "Scott Buckley", "Kevin MacLeod dark", "Rafael Krux", "Alexander Nakarada"]
MUSIC_GOOD = ("dark", "ambient", "suspense", "cinematic", "creepy", "drone", "tension", "noir", "mystery", "shadow", "silence", "night")
MUSIC_BAD = ("trance", "rock", "dance", "happy", "carefree", "party", "voice", "album", "hour", "lo-fi", "dubstep", "metal", "funk", "polka", "jazz", "cyberpunk")


def music_search(seed=0):
    """Wikimedia Commons'tan CC BY / CC0 / kamu malı, 100-700 sn'lik karanlık/sinematik fon müziği adayları."""
    import random
    cands, seen = [], set()
    for q in MUSIC_QUERIES:
        p = urllib.parse.urlencode({"action": "query", "format": "json", "generator": "search", "gsrsearch": f"{q} filetype:audio",
                                    "gsrnamespace": "6", "gsrlimit": "25", "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata"})
        raw = _get(API + "?" + p)
        if not raw:
            continue
        for pg in ((json.loads(raw).get("query") or {}).get("pages") or {}).values():
            ii = (pg.get("imageinfo") or [{}])[0]
            md = ii.get("extmetadata") or {}
            lic = _clean((md.get("LicenseShortName") or {}).get("value", ""))
            title = pg.get("title", "")
            dur, size = ii.get("duration", 0) or 0, ii.get("size", 0) or 0
            low = (title + " " + lic).lower()
            if title in seen or not (100 <= dur <= 700) or size > 30_000_000:
                continue
            if "sa" in re.split(r"[ -]", lic.lower()):          # paylaşım-aynı-lisans (SA) elenir
                continue
            if not any(k in lic.lower() for k in ("cc by", "cc0", "public domain")):
                continue
            if any(b in low for b in MUSIC_BAD):
                continue
            score = sum(1 for g in MUSIC_GOOD if g in low)
            seen.add(title)
            cands.append((score, title, ii["url"], dur, lic, _clean((md.get("Artist") or {}).get("value", ""))[:60], ii.get("descriptionurl", "")))
    rnd = random.Random(seed)
    rnd.shuffle(cands)
    cands.sort(key=lambda x: -x[0])
    return cands


def _concat_bed(seq, seconds, out_wav):
    import subprocess
    ins = []
    for w in seq:
        ins += ["-i", w]
    n = len(seq)
    if n == 1:
        fc = "[0:a]anull[m]"
    else:
        fc = "[0:a][1:a]acrossfade=d=6:c1=tri:c2=tri[x1];"
        for i in range(2, n):
            fc += f"[x{i - 1}][{i}:a]acrossfade=d=6:c1=tri:c2=tri[x{i}];"
        fc = fc + f"[x{n - 1}]anull[m]"
    fc += ";[m]loudnorm=I=-22:TP=-3:LRA=7,afade=t=in:d=2[o]"
    r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"] + ins + ["-filter_complex", fc, "-map", "[o]", "-t", f"{seconds + 6:.1f}",
                        "-ar", "44100", "-ac", "1", out_wav], capture_output=True, text=True)
    if r.returncode != 0:
        print("müzik birleştirilemedi:", r.stderr[-300:])
        return False
    return True


def music_bed(seconds, out_wav, workdir, seed=0):
    """Fon müziği yatağı: birkaç parçayı çapraz geçişle uç uca ekler, gerekirse döngüye alır. (wav_yolu, [atıflar]) ya da (None, [])."""
    import subprocess
    cands = music_search(seed)
    got, total = [], 0.0
    for score, title, url, dur, lic, artist, page in cands:
        if total >= seconds + 20 or len(got) >= 6:
            break
        data = _get(url)
        if not data or len(data) < 200000:
            continue
        ext = os.path.splitext(url.split("?")[0])[1] or ".ogg"
        f = os.path.join(workdir, f"muzik_{len(got)}{ext}")
        open(f, "wb").write(data)
        w = os.path.join(workdir, f"muzik_{len(got)}.wav")
        r = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", f, "-vn", "-ac", "1", "-ar", "44100", w])
        if r.returncode != 0 or not os.path.exists(w):
            continue
        got.append((w, dur, f"Müzik: {re.sub(r'^File:', '', title)[:60]} — {artist[:40] or 'Bilinmiyor'}, {lic}, {page}"))
        total += dur - 6
    if not got:
        return None, []
    seq, t = [], 0.0
    while t < seconds + 8:
        for w, dur, _ in got:
            seq.append(w)
            t += dur - 6
            if t >= seconds + 8:
                break
    if not _concat_bed(seq, seconds, out_wav):
        return None, []
    return out_wav, [x[2] for x in got]


if __name__ == "__main__":
    import sys
    out = fetch(sys.argv[1:], "ornekler/commons", 2)
    for q, v in out.items():
        print(q, len(v))
        for x in v:
            print("  ", x["credit"][:200])
