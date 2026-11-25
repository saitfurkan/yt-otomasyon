#!/usr/bin/env python3
"""Adım 1 - Konu seçici.

Türkçe haber kaynaklarını (RSS) tarar, haberleri "suç + para + devlet/güç +
merak" ölçütlerine göre puanlar, aynı olayı anlatan haberleri tek konuda toplar
ve en güçlü konuları topics.json ve topics.md dosyalarına yazar.

Sadece Python standart kütüphanesini kullanır (kurulum gerekmez).

Kullanım:
    python topic_picker.py            # gerçek kaynaklardan tara
    python topic_picker.py --demo     # internetsiz, örnek veriyle dene
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

# Not: Bazı adresler zamanla değişebilir. Çalışmayan kaynak atlanır ve
# raporda "HATA" olarak görünür; o zaman adresi birlikte güncelleriz.
FEEDS = {
    "AA": "https://www.aa.com.tr/tr/rss/default?cat=guncel",
    "NTV": "https://www.ntv.com.tr/gundem.rss",
    "Hürriyet": "https://www.hurriyet.com.tr/rss/gundem",
    "Cumhuriyet": "https://www.cumhuriyet.com.tr/rss/son_dakika.xml",
    "BirGün": "https://www.birgun.net/rss/home",
    "TRT Haber": "https://www.trthaber.com/sondakika.rss",
    "CNN Türk": "https://www.cnnturk.com/feed/rss/all/news",
    "Habertürk": "https://www.haberturk.com/rss",
    # Genişletilmiş kaynaklar (çalışmayan adres atlanır, raporda HATA olarak görünür)
    "BBC Türkçe": "https://feeds.bbci.co.uk/turkce/rss.xml",
    "DW Türkçe": "https://rss.dw.com/rdf/rss-tur-all",
    "T24": "https://t24.com.tr/rss",
    "Medyascope": "https://medyascope.tv/feed/",
    "Euronews TR": "https://tr.euronews.com/rss",
    "Sözcü": "https://www.sozcu.com.tr/feeds-rss-category-gundem",
    "Milliyet": "https://www.milliyet.com.tr/rss/rssnew/gundemrss.xml",
    "Sabah": "https://www.sabah.com.tr/rss/gundem.xml",
    "Bianet": "https://bianet.org/biamag.rss",
}

MAX_AGE_HOURS = 72   # en fazla kaç saat öncesine ait haberler
TOP_N = 10           # kaç konu listelensin

# (anahtar kelime parçası, puan). Kelime parçası olduğu için ekleri de yakalar.
CRIME = [
    ("cinayet", 4), ("öldürül", 3), ("şüpheli ölüm", 5), ("soruşturma", 3),
    ("gözaltı", 3), ("tutuklan", 3), ("operasyon", 2), ("dolandırıcı", 3),
    ("kara para", 4), ("aklama", 4), ("rüşvet", 4), ("yolsuzluk", 4),
    ("kayyum", 3), ("iddianame", 3), ("mahkum", 2), ("hapis", 2),
    ("firari", 3), ("kayıp", 2), ("soygun", 3), ("çete", 3), ("örgüt", 3),
    ("kaçakçılık", 3), ("uyuşturucu", 2), ("kumar", 2), ("bahis", 2), ("şike", 3),
]
MONEY = [
    ("milyar", 3), ("milyon", 2), ("holding", 2), ("banka", 1), ("fon", 2),
    ("vurgun", 4), ("zimmet", 4), ("hortum", 4), ("el konul", 3), ("mal varlığı", 2),
]
POWER = [
    ("savcılık", 2), ("başsavcı", 2), ("masak", 3), ("tmsf", 3), ("spk", 2),
    ("bakan", 1), ("belediye", 1), ("emniyet", 1), ("kaymakam", 1),
]
MYSTERY = [
    ("sır", 1), ("iz sürül", 2), ("ortaya çıktı", 2), ("şok", 2), ("ifşa", 2),
    ("kan donduran", 3), ("kamera kaydı", 2), ("itiraf", 3),
]
# Konu dışı / ilgi çekmeyen haberleri aşağı çek
NOISE = [
    ("burç", -8), ("hava durumu", -8), ("kampanya", -6), ("katalog", -8),
    ("maç", -5), ("dizi", -4), ("magazin", -6), ("ara tatil", -8),
    ("deprem listesi", -8), ("son depremler", -8), ("kur ", -3), ("altın fiyat", -6),
    ("meclis", -4), ("grup toplantısı", -6), ("bütçe görüşme", -5),
    ("milletvekili", -2), ("seçim", -3), ("kutlama", -6),
    ("çekiliş", -10), ("loto", -10), ("piyango", -10), ("on numara", -10),
    ("reyting", -8), ("akaryakıt", -8), ("benzin", -6), ("motorin", -6),
    ("sonuçları açıklandı", -6), ("günün en çok", -8), ("bugün ne oldu", -8),
]
# Siyasi hassasiyet işareti (puanı etkilemez, sana "dikkat" notu düşer)
SENSITIVE = ["chp", "akp", "mhp", "dem parti", "cumhurbaşkan", "muhalefet", "iktidar"]

MONTHS = set("ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık".split())
STOP = set("için ile ama fakat çok daha gibi olan oldu olarak sonra önce bir bu şu "
           "ve ya de da ki mi mı mu mü ne nasıl neden kadar göre hakkında üzerine".split())


def tr_lower(s: str) -> str:
    return s.replace("İ", "i").replace("I", "ı").lower()


def clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_feed(xml_bytes: bytes):
    items = []
    root = ET.fromstring(xml_bytes)
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        d = {"title": "", "link": "", "summary": "", "date": None}
        for ch in el:
            t = ch.tag.split("}")[-1]
            if t == "title":
                d["title"] = clean(ch.text)
            elif t == "link":
                d["link"] = (ch.text or ch.attrib.get("href", "")).strip()
            elif t in ("description", "summary", "content"):
                d["summary"] = clean(ch.text)
            elif t in ("pubDate", "published", "updated", "date"):
                d["date"] = parse_date(ch.text)
        if d["title"]:
            items.append(d)
    return items


def parse_date(s):
    if not s:
        return None
    try:
        dt = parsedate_to_datetime(s)
    except Exception:
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def fetch_all():
    items, errors = [], []
    for name, url in FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                got = parse_feed(r.read())
            for g in got:
                g["source"] = name
            items.extend(got)
            print(f"[OK]   {name}: {len(got)} haber")
        except Exception as e:  # kaynak çalışmıyorsa atla
            errors.append(f"{name}: {e}")
            print(f"[HATA] {name}: {e}")
    return items, errors


def score_item(item):
    text = tr_lower(item["title"] + " " + item["summary"])
    score, reasons = 0, []
    for label, group in (("suç", CRIME), ("para", MONEY), ("güç", POWER),
                         ("merak", MYSTERY), ("gürültü", NOISE)):
        pts = sum(w for k, w in group if k in text)
        if pts:
            score += pts
            reasons.append(f"{label}:{pts:+d}")
    if re.search(r"\b\d{2,}\b", item["title"]):
        score += 1
        reasons.append("rakam:+1")
    sensitive = any(re.search(r"(?<![a-zçğıöşü0-9])" + re.escape(k), text)
                    for k in SENSITIVE)
    return score, reasons, sensitive


def tokens(title):
    words = re.findall(r"[a-zçğıöşü0-9]+", tr_lower(title))
    return {w[:6] for w in words
            if (len(w) >= 4 or (w.isdigit() and len(w) >= 3))
            and w not in STOP and w not in MONTHS
            and not re.fullmatch(r"20\d\d", w)}


def same_story(a, b):
    """İki başlık aynı olayı mı anlatıyor?"""
    shared = a & b
    if len(shared) < 2:
        return False
    jac = len(shared) / len(a | b)
    big_number = any(t.isdigit() for t in shared)  # ortak büyük rakam güçlü işaret
    return (jac >= 0.4 or len(shared) >= 4
            or (len(shared) >= 3 and jac >= 0.3)
            or (big_number and jac >= 0.1))


def build_topics(items):
    now = datetime.now(timezone.utc)
    fresh = []
    for it in items:
        if it["date"] and now - it["date"] > timedelta(hours=MAX_AGE_HOURS):
            continue
        it["score"], it["reasons"], it["sensitive"] = score_item(it)
        it["tok"] = tokens(it["title"])
        fresh.append(it)

    fresh.sort(key=lambda x: x["score"], reverse=True)
    clusters = []
    for it in fresh:
        for c in clusters:
            if same_story(it["tok"], c["first_tok"]):
                c["items"].append(it)
                break
        else:
            clusters.append({"items": [it], "tok": set(it["tok"]),
                             "first_tok": set(it["tok"])})

    topics = []
    for c in clusters:
        its = c["items"]
        sources = sorted({i["source"] for i in its})
        total = max(i["score"] for i in its) + 3 * min(len(sources) - 1, 3)
        newest = max((i["date"] for i in its if i["date"]), default=None)
        if newest and now - newest < timedelta(hours=24):
            total += 2
        best = max(its, key=lambda i: i["score"])
        topics.append({
            "score": total,
            "title": best["title"],
            "sources": sources,
            "links": [{"source": i["source"], "url": i["link"],
                       "title": i["title"], "summary": i["summary"][:500]}
                      for i in its][:6],
            "reasons": best["reasons"],
            "sensitive": any(i["sensitive"] for i in its),
            "single_source": len(sources) < 2,
            "newest": newest.isoformat() if newest else None,
        })
    topics.sort(key=lambda t: t["score"], reverse=True)
    return topics[:TOP_N]


def demo_items():
    now = datetime.now(timezone.utc)
    rows = [
        ("AA", "[DEMO] Büyük dolandırıcılık operasyonu: 40 şüpheli gözaltına alındı"),
        ("NTV", "[DEMO] Dolandırıcılık operasyonunda 40 gözaltı, milyonluk vurgun iddiası"),
        ("Hürriyet", "[DEMO] Meclis'te bütçe görüşmeleri sürüyor"),
        ("Cumhuriyet", "[DEMO] Hafta sonu hava durumu: sıcaklıklar düşüyor"),
        ("TRT Haber", "[DEMO] Holdinge kayyum atandı, savcılık soruşturma başlattı"),
    ]
    return [{"title": t, "link": "https://example.com", "summary": "",
             "date": now - timedelta(hours=3), "source": s} for s, t in rows]


def choose(topics):
    """Sistemin kendi seçimi: en az 2 kaynakta geçen en yüksek puanlı konu."""
    for t in topics:
        if not t["single_source"] and t["score"] > 0:
            return t
    return None


def write_outputs(topics, errors):
    selected = choose(topics)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    with open("topics.json", "w", encoding="utf-8") as f:
        json.dump({"generated": stamp, "errors": errors,
                   "selected": selected, "topics": topics},
                  f, ensure_ascii=False, indent=2)
    lines = [f"# Konu adayları ({stamp})", ""]
    if selected:
        lines += [f"**SİSTEMİN SEÇTİĞİ KONU:** {selected['title']}", ""]
    for n, t in enumerate(topics, 1):
        flag = "  ⚠️ siyasi hassasiyet: metni dikkatle kontrol et" if t["sensitive"] else ""
        if t["single_source"]:
            flag += "  ⚠️ tek kaynak: başka kaynaktan doğrulanmadan video yapılmaz"
        lines.append(f"## {n}. {t['title']}  (puan: {t['score']}){flag}")
        lines.append(f"- Kaynaklar: {', '.join(t['sources'])}")
        lines.append(f"- Puan nedenleri: {', '.join(t['reasons']) or '-'}")
        for l in t["links"]:
            lines.append(f"- {l['source']}: {l['url']}")
        lines.append("")
    if errors:
        lines += ["## Çalışmayan kaynaklar", *[f"- {e}" for e in errors]]
    with open("topics.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    if "--demo" in sys.argv:
        items, errors = demo_items(), []
    else:
        items, errors = fetch_all()
    topics = build_topics(items)
    write_outputs(topics, errors)
    print(f"\n{len(topics)} konu yazıldı -> topics.md / topics.json")


if __name__ == "__main__":
    main()
