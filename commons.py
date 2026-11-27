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


def search(query, limit=14, min_w=2400):
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
        if ii.get("mime") not in ("image/jpeg", "image/png") or ii.get("width", 0) < min_w:
            continue
        if ii["width"] < ii.get("height", 0) * 1.15:            # yatay kadraj
            continue
        md = ii.get("extmetadata") or {}
        lic = _clean((md.get("LicenseShortName") or {}).get("value", ""))
        title = p.get("title", "")
        cats = _clean((md.get("Categories") or {}).get("value", "")).lower()
        desc = _clean((md.get("ImageDescription") or {}).get("value", "")).lower()
        blob = (title + " " + cats + " " + desc).lower()
        if not any(k in lic.lower() for k in OK_LIC):
            continue
        if any(b in blob for b in BAD_WORDS) or "people" in cats.split("|")[0:0]:
            continue
        out.append({"title": title, "url": ii.get("thumburl") or ii["url"], "page": ii.get("descriptionurl", ""),
                    "author": _clean((md.get("Artist") or {}).get("value", "")) or "Bilinmiyor", "license": lic,
                    "w": ii["width"], "index": p.get("index", 99)})
    out.sort(key=lambda x: (x["index"], -x["w"]))
    return out


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


if __name__ == "__main__":
    import sys
    out = fetch(sys.argv[1:], "ornekler/commons", 2)
    for q, v in out.items():
        print(q, len(v))
        for x in v:
            print("  ", x["credit"][:200])
