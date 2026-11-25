#!/usr/bin/env python3
"""Adım 2 - Senaryo yazıcı (Son Tanık).

Akış:
  1) topics.json içindeki "sistemin seçtiği konu"nun haber metinlerini indirir.
  2) Metinlerden SADECE yazılı olguları çıkarır (uydurmayı engeller).
  3) Senaryoyu bölüm bölüm, yalnızca bu olgulardan, Furkan'ın tarzında yazar.
  4) Çok kısaysa uzatır, yapay zekâ kalıplarını temizler.
  5) 3 Shorts parçası, başlık, açıklama, etiket üretir.
  6) Sayı ve özel isimleri kaynaklarla otomatik karşılaştırır.
Sonuç: script_latest.md (okunacak metin), script_latest.json, scripts/TARİH.md

Sadece Python standart kütüphanesi. Gizli anahtar: GEMINI_API_KEY.
Kullanım:
    python script_writer.py
    python script_writer.py --sources-only   # sadece haber metni okuma testi
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser

API = "https://generativelanguage.googleapis.com/v1beta"
UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/124.0 Safari/537.36")

MIN_WORDS = 900           # bunun altı uyarı olarak raporlanır (şişirme yapılmaz)
MIN_SOURCE_WORDS = 800    # kaynak malzeme bunun altındaysa konu atlanır
MIN_FACTS = 12
MAX_ARTICLES = 6
PER_ARTICLE_CHARS = 7000
TOTAL_CHARS = 60000
MAX_EXTRA = 8             # arka plan için aranıp okunacak ek makale sayısı
BAD_HOSTS = ("youtube", "youtu.be", "twitter", "x.com", "instagram", "facebook",
             "tiktok", "t.me", "pinterest", "reddit")
MAX_TOPICS_TRIED = 4
PAUSE = 5                 # çağrılar arası bekleme (saniye), ücretsiz limit için

BANNED = [
    "bu videoda", "sonuç olarak", "önemle belirtmek", "özetle", "kısacası",
    "günümüzde", "çok yönlü", "derinlemesine", "gelin bakalım", "birincisi",
    "ikincisi", "üçüncüsü", "unutulmamalıdır", "bu bağlamda", "söz konusu",
    "sonuç itibarıyla", "dikkat çekici bir şekilde", "derler", "çorap söküğü",
    "son perde", "faturayı kesti", "terazisi başka", "ben furkan",
    "kirli ilişki", "karanlığ", "pırıltılı", "taşları yerinden", "koridor",
    "aynı hizada", "ışıkların",
]

CELEB = ["ünlü", "şarkıcı", "oyuncu", "magazin", "fenomen", "sunucu", "futbolcu"]

POLITICAL = ["imamoğlu", "erdoğan", "özgür özel", "bahçeli", "kılıçdaroğlu",
             "mansur yavaş", "demirtaş", "chp", "akp", "mhp", "dem parti",
             "cumhurbaşkan", "muhalefet", "iktidar", "milletvekili", "seçim"]

SYSTEM = """Sen "Son Tanık" adlı Türkçe YouTube suç ve ceza kanalının yazarısın. Metni kanalın sahibi Furkan kendi sesiyle okuyacak. Metin Furkan'ın ağzından, birinci tekil kişiyle ("ben") çıkmış gibi yazılır.

FURKAN'IN ANLATIM TARZI
- Metin, konuya özel ve her videoda yeni kurulmuş kısa, sert, hükmeden bir sözle açılır. Söz birinci tekil kişiyle, kendi cümlesi gibi çıkar ("derim", "bilirim" ya da doğrudan hüküm). Örnek kalıp: "Taşa kazınan silgiyle silinmez." Bu örneği ya da bilinen atasözlerini KOPYALAMA, konuya uygun yeni bir söz kur. "Derler", "denir" gibi başkasından aktaran kalıplar yok.
- Söz, Furkan'ın genel adalet/hukuk hükmü olsun. Olayın içindeki bir kişinin sözünü ya da durumunu kendi sözün gibi söyleme ("kendi cezamın bedelini ödetmem" gibi olay kahramanının ağzından konuşma yasak). Kendini tanıtma. "Ben Furkan", "hoş geldiniz", "kanalıma" gibi giriş yok. Kanal tanıtımını video kendi ayrı bölümünde yapıyor.
- Kısa, doğrudan cümleler. Konuşma dili. Haber spikeri gibi değil, olayı bilen ve içi yanan mahalle abisi gibi. "Bak", "düşünsene", "inanması zor ama", "yani" gibi sözleri tüm metinde en fazla 2-3 kez kullan, yoksa yapay durur.
- Güçlü bir adalet duygusu: kim, kime, ne yaptı, hesap verecek mi? Ama bunu ima ile değil, olgularla kur. "Acaba terazi mi şaştı?" gibi örtülü suçlamalar yasak.
- Uzun bir cümleden sonra kısa bir cümle. Ara sıra tek kelimelik cümle.
- Nefes ve vurgu yerlerine [duraklama] yaz (tüm metinde 8-12 kez).
- Rakamları rakamla yaz (130, 245 gibi), okurken kolay olsun.
- İSİM POLİTİKASI: Çok sayıda şüpheli varsa isim listesi ASLA okuma. En fazla 3 isim ver: yalnızca ülke çapında tanınan ve en az 3 kaynakta geçen kişiler. Diğerleri için "aralarında iş insanları, yönetmen, organizatör de var" gibi tanım kullan. Özel kişilerin adı yok.
- YARGI YÜKLÜ SÖZ YOK: "kirli", "karanlık", "pırıltılı", "ışıkların arkası", "ağır iddialar örtülemez" gibi suçu önceden kabul ettiren ya da şiirli doldurma sözler yasak. "Bence" yalnızca süreç ve adalet işleyişi hakkında olur, bir kişinin suçlu olup olmadığı hakkında asla; tüm metinde en fazla 2 kez.
- VAAZ YOK: "Kanun karşısında herkes eşittir" türü genel adalet konuşması tüm metinde en fazla BİR kez, tek cümle. "Adliye koridorları", "ışıklar", "şöhret" gibi aynı imgeyi tekrar tekrar kurma.
- SAYI FARKLARI: Gözaltı sayıları saatlere göre değişir. Kaynaklar farklı sayı veriyorsa "çelişki" deme; "sayı gün içinde 19'dan 24'e yükseldi" gibi her kaynağın verdiği sayıyı olgu olarak ver.
- ASLA TEKRAR ETME: Bir olgu metinde yalnızca bir kez anlatılır. Daha önce anlatılmış bir rakamı, tarihi ya da olayı yeni bir bölümde yeniden anlatma. Malzeme azsa metin kısa kalsın, şişirme.

YAPAY ZEKÂ KOKUSU YASAK
Şunları ASLA kullanma: "Bu videoda", "sonuç olarak", "özetle", "kısacası", "önemle belirtmek gerekir", "günümüzde", "çok yönlü", "derinlemesine", "gelin bakalım", "birincisi/ikincisi/üçüncüsü" sıralamaları, "söz konusu", "bu bağlamda". Emoji, madde işareti, markdown başlığı, uzun tire (—) yok. Her paragrafı aynı kalıpla bitirme. Metni özetleyen kapanış paragrafı yazma. "Peki ama..." kalıbını her bölümde kullanma.

KESİN HUKUKİ VE ETİK KURALLAR
- Sadece sana verilen OLGULAR listesindeki bilgileri kullan. Listede olmayan isim, rakam, tarih, sözcük, diyalog, iç düşünce UYDURMA. Emin değilsen yazma.
- Haber metinlerini kopyalama, olguları kendi cümlelerinle anlat.
- Soruşturma ve dava aşamasındaki kişiler için hüküm verme. "İddia ediliyor", "savcılığa göre", "soruşturma kapsamında", "gözaltına alındı", "tutuklandı" gibi olgusal dil kullan. Mahkûmiyet kesinleşmedikçe "suçlu" deme. Olgularda varsa ilgililerin açıklamasını ve savunmasını da aktar.
- Kaynaklar aynı olgu için açıkça farklı bilgi veriyorsa ikisini de ver. Farklı tarihler farklı olay adımlarına ait olabilir; emin değilsen "çelişiyor" deme, her kaynağın ne aktardığını tek tek söyle ya da konuyu atla.
- "Dikkat çeken gelişme", "şüpheli şekilde", "tesadüf mü" gibi yönlendirici ifadeler yok. Kurum kararlarını (HSK atamaları vb.) yorumsuz, olgu olarak ver.
- Çocukların ve mağdurların kimliğini, ayrıntılı şiddet tasvirini verme. Çocuk şüpheli ya da mağdur varsa isim yok. Kamu görevlisi ya da tanınmış kişi olmayan özel kişilerde isim yerine tanım kullan ("bir iş insanı").
- Kişilere hakaret, aşağılama, kanıtsız suçlama yok. Öfke olguya ve işleyişe yönelir. Furkan'ın yorumu "bence" diye açıkça ayrılır, kısa tutulur, olgu gibi sunulmaz.
- Siyasi taraf tutma yok: iktidar da muhalefet de aynı dille anlatılır.
- "Her yerde örgüt var", "hepsi aynı çete" gibi genellemeleri olgu gibi söyleme."""

FACT_SYSTEM = ("Sen titiz bir haber editörüsün. Görevin yalnızca kaynak metinlerde "
               "açıkça yazan olguları çıkarmak. Yorum, tahmin, çıkarım, uydurma yok.")

SECTIONS = [
    ("KANCA", "Videonun ilk 10-20 saniyesi, TEK PARAGRAF, 35-55 kelime. Önce konuya özel yeni, kısa, sert bir söz (birinci tekil kişiyle). Sonra şaşırtıcı bir rakam ya da merak uyandıran bir soruyla bitir. Şiirli imgeler (ışık, karanlık, taş, perde) kullanma; somut bir olgudan ya da rakamdan başla. Haberin özetini ya da sonucunu verme. Kendini tanıtma. Paragrafın sonuna [duraklama] koy.", 45, False),
    ("OLAY", "Ne oldu? Kronolojik, sahneyi kur. Kim, ne zaman, nerede. Bir kırılma noktası olsun.", 400, True),
    ("GEÇMİŞ VE BAĞLAM", "Buraya nasıl gelindi? Dosyanın önceki aşamaları, ilgili kişilerin bu dosyadaki rolü, daha önceki duruşmalar, operasyonlar ya da kararlar. Kronolojik anlat. Olay bölümünde geçenleri tekrar etme, yalnızca geçmişe ait olgulardan yaz.", 450, True),
    ("PARA VE İLİŞKİLER", "Rakamlar, kurumlar, kim kiminle bağlantılı (sadece olgulardaki kadar). Her iddiayı 'savcılığa göre' gibi kaynağa bağla. Olay bölümünde anlatılanları tekrar etme, yalnızca yeni olguları ver.", 400, True),
    ("SORUŞTURMA VE SÜREÇ", "Savcılık ve mahkemeler ne yapmış, hangi adımlar atılmış, ne bekleniyor. Önceki bölümlerde geçmeyen olgulardan anlat.", 400, True),
    ("TARAFLAR VE NEDEN ÖNEMLİ", "Taraflar ne diyor (resmi açıklama, savunma, karşı görüş). Sonra sıradan insana etkisi. Yeni olgu yoksa kısa tut.", 250, True),
    ("KAPANIŞ", "Önce tek cümleyle sıradaki gelişmeyi söyle. Sonra izleyiciye bu dosyaya özel, iki kelimeyle cevaplanabilecek TEK bir soru sor (örnek biçimler: dosyada en çok hangi nokta cevapsız kaldı, bu detayı biliyor musunuz, A mı B mi). Dava sürüyorsa 'suçlu mu' diye ASLA sorma. Metnin son cümlesi birebir şu olsun: Artık son tanık sizsiniz. Abone ol daveti ve özet yok.", 70, False),
]

META_SCHEMA = """Sadece şu JSON nesnesini döndür:
{
  "title_options": ["3 başlık, her biri en fazla 65 karakter, merak uyandırır ama yalan vaat etmez"],
  "shorts": [
    {"hook": "ilk cümle, izleyiciyi tutan kanca", "text": "30-45 saniyelik dikey video metni, 80-110 kelime, ilk cümlesi hook ile aynı, tek başına anlaşılır, SENARYODAKİ olgulara dayalı", "bolum": "senaryonun hangi bölümünden"}
  ],
  "description": "YouTube açıklaması: 3-4 cümle özet + 'Bilgiler haber kaynaklarına dayanır. Soruşturmalar sürüyor, kimse mahkûm edilene kadar suçsuz sayılır.' notu",
  "tags": ["10-15 etiket"],
  "thumbnail_text": "küçük resim için 2-4 kelimelik vurucu yazı",
  "risk_notes": ["Furkan'ın okurken dikkat etmesi gereken hukuken hassas cümleler, kısa kısa"]
}
"shorts" tam 3 öğe içersin. Short metinlerinde kendini tanıtma ve abone ol daveti yok. Olayın bir kişisinden alıntı yaparken ismini ve tırnağı kullan (Haluk Levent mahkemede şunu söyledi: \"...\"); anlatıcı o kişiymiş gibi birinci tekil kişiyle konuşma. Senaryodaki yasak kalıplar ve yargı yüklü sözler Shorts için de yasak, \"koridor\" \"ışıklar\" gibi doldurma imgeler yok."""


# ---------------------------------------------------------------- yardımcılar
def today_tr():
    aylar = ["Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz",
             "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık"]
    d = datetime.now(timezone.utc)
    return f"{d.day} {aylar[d.month - 1]} {d.year}"


DATE_RULE = ("BUGÜNÜN TARİHİ: {d}. 'Bu yıl', 'geçen yıl', 'dün', 'geçen ay' gibi göreli "
             "tarihleri bu tarihe göre MUTLAK tarihe çevir (ör. bugün 2026 ise 'geçen yıl' = 2025, "
             "'bu yıl 4 Nisan' = 4 Nisan 2026). Göreli ifade ile yıl numarası aynı tarihi "
             "gösteriyorsa bu bir çelişki DEĞİLDİR, tek tarih olarak yaz.")


def log(*a):
    print(*a, flush=True)


def tr_lower(s):
    return s.replace("İ", "i").replace("I", "ı").lower()


def count_words(text):
    text = re.sub(r"\[duraklama\]", " ", text, flags=re.I)
    return len(re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", text))


STOP = set("için ile ama fakat çok daha gibi olan oldu olarak sonra önce bir bu şu "
           "ve ya de da ki mi mı mu mü ne nasıl neden kadar göre hakkında üzerine".split())
MONTHS = set("ocak şubat mart nisan mayıs haziran temmuz ağustos eylül ekim kasım aralık".split())


def story_tokens(title):
    ws = re.findall(r"[a-zçğıöşü0-9]+", tr_lower(title))
    return {w[:6] for w in ws
            if (len(w) >= 4 or (w.isdigit() and len(w) >= 3))
            and w not in STOP and w not in MONTHS and not re.fullmatch(r"20\d\d", w)}


def same_story(a, b):
    shared = a & b
    if len(shared) < 2:
        return False
    jac = len(shared) / len(a | b)
    big = any(t.isdigit() for t in shared)
    return (jac >= 0.4 or len(shared) >= 4
            or (len(shared) >= 3 and jac >= 0.3) or (big and jac >= 0.1))


# ---------------------------------------------------------- haber metni okuma
class ArticleParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "nav", "footer", "aside", "form", "header"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.article = 0
        self.in_p = False
        self.cur = []
        self.all_p = []
        self.art_p = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.skip += 1
        elif tag == "article":
            self.article += 1
        elif tag == "p" and not self.skip:
            self.in_p, self.cur = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP:
            self.skip = max(0, self.skip - 1)
        elif tag == "article":
            self.article = max(0, self.article - 1)
        elif tag == "p" and self.in_p:
            self.in_p = False
            text = re.sub(r"\s+", " ", "".join(self.cur)).strip()
            if text:
                self.all_p.append(text)
                if self.article:
                    self.art_p.append(text)

    def handle_data(self, data):
        if self.in_p and not self.skip:
            self.cur.append(data)


BOILER = ("tüm hakları", "çerez", "©", "abone ol", "bültene", "gizlilik politikası",
          "kvkk", "tıklayın", "whatsapp")


def extract_article(html_text):
    p = ArticleParser()
    try:
        p.feed(html_text)
    except Exception:
        pass
    paras = p.art_p if sum(len(x) for x in p.art_p) > 600 else p.all_p
    out, seen = [], set()
    for t in paras:
        low = t.lower()
        if len(t) < 50 or any(b in low for b in BOILER) or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return "\n\n".join(out)


def fetch_article(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept-Language": "tr-TR,tr;q=0.9",
        "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=25) as r:
        raw = r.read()
        ctype = r.headers.get_content_charset() or "utf-8"
    head = raw[:3000].decode("ascii", "ignore")
    m = re.search(r"charset=['\"]?([\w-]+)", head, re.I)
    enc = (m.group(1) if m else ctype) or "utf-8"
    try:
        text = raw.decode(enc, "replace")
    except LookupError:
        text = raw.decode("utf-8", "replace")
    return extract_article(text)


def gather(topic):
    arts, seen = [], set()
    for l in topic.get("links", []):
        url = l.get("url")
        if not url or url in seen or len(arts) >= MAX_ARTICLES:
            continue
        seen.add(url)
        text, how = "", ""
        try:
            text = fetch_article(url)
            how = "tam metin"
        except Exception as e:
            log(f"   [okunamadı] {l.get('source')}: {e}")
        if count_words(text) < 80:
            # RSS özetine geri dön (kısa ama gerçek kaynak)
            summ = (l.get("summary") or "").strip()
            if count_words(summ) >= 15:
                text, how = f"{l.get('title', '')}. {summ}", "yalnız özet"
            else:
                log(f"   [atlandı] {l.get('source')}: metin alınamadı")
                continue
        log(f"   [ok] {l.get('source')}: {count_words(text)} kelime ({how})")
        arts.append({"source": l.get("source", "?"), "url": url,
                     "text": text[:PER_ARTICLE_CHARS]})
    out, total = [], 0
    for a in arts:
        room = TOTAL_CHARS - total
        if room < 800:
            break
        a["text"] = a["text"][:room]
        total += len(a["text"])
        out.append(a)
    return out


# --------------------------------------------------------------------- Gemini
class ApiError(Exception):
    def __init__(self, code, body):
        super().__init__(f"HTTP {code}: {body}")
        self.code, self.body = code, body


class Blocked(Exception):
    pass


class GenerationFailed(Exception):
    pass


class QuotaExceeded(GenerationFailed):
    pass


def http(method, url, key, payload=None, timeout=300):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={
        "Content-Type": "application/json", "x-goog-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace")[:500])
    except (urllib.error.URLError, TimeoutError) as e:
        raise ApiError(0, str(e))


def model_candidates(key):
    forced = os.environ.get("GEMINI_MODEL", "").strip()
    if forced:
        return [forced]
    try:
        data = http("GET", f"{API}/models?pageSize=200", key, timeout=60)
    except ApiError as e:
        if e.code in (400, 401, 403):
            raise GenerationFailed(
                "API anahtarı geçersiz ya da yetkisiz görünüyor "
                f"({e.code}). Anahtarı aistudio.google.com'dan yenileyip "
                "GitHub Secrets'taki GEMINI_API_KEY'i güncelle.")
        return ["gemini-flash-latest", "gemini-2.5-flash", "gemini-2.0-flash"]
    bad = ("image", "tts", "live", "audio", "embedding", "robotics", "computer",
           "vision", "learnlm", "imagen", "veo", "native", "aqa")
    names = []
    for m in data.get("models", []):
        if "generateContent" in m.get("supportedGenerationMethods", []):
            n = m["name"].split("/", 1)[-1]
            if n.startswith("gemini") and not any(b in n for b in bad):
                names.append(n)

    def ver(n):
        m = re.match(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0.0

    def desc(items):
        return sorted(items, key=ver, reverse=True)

    g0 = [n for n in names if n == "gemini-flash-latest"]
    g1 = desc([n for n in names if re.match(r"^gemini-[\d.]+-flash(-\d+)?$", n)])
    g2 = desc([n for n in names if "flash" in n and "lite" not in n
               and n not in g0 and n not in g1])
    g3 = desc([n for n in names if "flash-lite" in n])
    g4 = desc([n for n in names if "pro" in n])
    out = []
    for n in g0 + g1 + g2 + g3 + g4:
        if n not in out:
            out.append(n)
    return out[:6] or ["gemini-flash-latest", "gemini-2.5-flash"]


def extract_text(resp):
    pf = resp.get("promptFeedback", {})
    if pf.get("blockReason"):
        raise Blocked(f"engellendi: {pf.get('blockReason')}")
    cands = resp.get("candidates") or []
    if not cands:
        raise Blocked("boş yanıt")
    c = cands[0]
    parts = c.get("content", {}).get("parts", [])
    text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
    if not text.strip():
        raise Blocked(f"metin yok (finishReason={c.get('finishReason')})")
    return text


def parse_json(text):
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        return json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a >= 0 and b > a:
            return json.loads(t[a:b + 1])
        raise


def generate(key, models, prompt, system=SYSTEM, json_out=False,
             temperature=0.85, max_tokens=8192):
    """Modelleri sırayla dener. (kullanılan_model, metin ya da sözlük) döndürür.
    Kota (429) dolmuşsa o modeli bekletmeden atlar; hepsinde kota doluysa
    QuotaExceeded fırlatır (boşuna dakikalarca beklemez)."""
    last = "bilinmeyen hata"
    quota_models, tried = 0, 0
    for model in models:
        tried += 1
        hit_quota = False
        for attempt in range(3):
            cfg = {"temperature": temperature, "maxOutputTokens": max_tokens}
            if json_out:
                cfg["responseMimeType"] = "application/json"
            payload = {"systemInstruction": {"parts": [{"text": system}]},
                       "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": cfg}
            try:
                resp = http("POST", f"{API}/models/{model}:generateContent",
                            key, payload)
                text = extract_text(resp)
                return model, (parse_json(text) if json_out else text.strip())
            except Blocked as e:
                last = f"{model}: {e}"
                log(f"   [{model}] {e}")
                break
            except ValueError:
                last = f"{model}: JSON okunamadı"
                log(f"   [{model}] JSON okunamadı, tekrar deneniyor")
                continue
            except ApiError as e:
                last = f"{model}: {e}"
                log(f"   [{model}] {str(e)[:160]}")
                if e.code == 429:
                    hit_quota = True
                    break  # bu modelin kotası dolu, sıradakine geç
                if e.code in (0, 500, 502, 503, 504) and attempt < 2:
                    time.sleep(20 * (attempt + 1))
                    continue
                break
        if hit_quota:
            quota_models += 1
    if tried and quota_models == tried:
        raise QuotaExceeded(
            "Gemini ücretsiz kotası dolmuş görünüyor (tüm modellerde 429). "
            "Kota her gün sıfırlanır (Türkiye saatiyle yaklaşık 10:00). "
            "Aynı gün içinde çok sayıda deneme yapıldıysa yarın tekrar çalıştır.")
    raise GenerationFailed(last)


def grounded_links(resp):
    """Google Arama destekli yanıttan kaynak bağlantılarını çıkarır."""
    out = []
    for c in resp.get("candidates") or []:
        gm = c.get("groundingMetadata") or {}
        for ch in gm.get("groundingChunks") or []:
            w = ch.get("web") or {}
            if w.get("uri"):
                out.append({"url": w["uri"], "title": w.get("title", "")})
    return out


def search_sources(key, models, topic, known_urls):
    """Gemini'nin Google Arama özelliğiyle konunun arka planını anlatan ek haber
    sayfalarını bulur. Olguları BURADAN almayız, sadece bağlantıları alırız; olgular
    yine sayfanın kendi metninden çıkarılır. Hata olursa boş liste döner."""
    prompt = (
        f"Şu haberin arka planını Türkçe haber kaynaklarında ara: {topic['title']}\n"
        "Olayın önceki aşamalarını, ilgili kişilerin bu dosyadaki rolünü, önceki "
        "duruşmaları ya da operasyonları ve davanın nasıl başladığını bul. "
        "Kısa bir özet yaz.")
    for model in models[:3]:
        payload = {"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                   "tools": [{"google_search": {}}],
                   "generationConfig": {"temperature": 0.2, "maxOutputTokens": 1500}}
        try:
            resp = http("POST", f"{API}/models/{model}:generateContent", key, payload, timeout=120)
        except Exception as e:
            log(f"   [arka plan araması: {model}] {str(e)[:120]}")
            continue
        links, seen = [], set(known_urls)
        for l in grounded_links(resp):
            host = (l["title"] or l["url"]).lower()
            if l["url"] in seen or any(b in host for b in BAD_HOSTS):
                continue
            seen.add(l["url"])
            links.append(l)
        if links:
            return links[:MAX_EXTRA]
        log(f"   [arka plan araması: {model}] kaynak bulunamadı")
    return []


def add_background(key, models, topic, arts):
    """Arka plan sayfalarını okuyup mevcut kaynaklara ekler."""
    try:
        links = search_sources(key, models, topic, [a["url"] for a in arts])
    except Exception as e:
        log(f"   [arka plan araması hata] {e}")
        return arts
    total = sum(len(a["text"]) for a in arts)
    added = 0
    for l in links:
        if total > TOTAL_CHARS - 1500:
            break
        try:
            text = fetch_article(l["url"])
        except Exception as e:
            log(f"   [arka plan okunamadı] {l['title'] or l['url'][:50]}: {str(e)[:80]}")
            continue
        if count_words(text) < 150:
            continue
        name = (l["title"] or "arka plan").strip()
        text = text[:min(PER_ARTICLE_CHARS, TOTAL_CHARS - total)]
        arts.append({"source": name, "url": l["url"], "text": text, "background": True})
        total += len(text)
        added += 1
        log(f"   [arka plan ok] {name}: {count_words(text)} kelime")
    log(f"   arka plan: {added} ek makale eklendi")
    return arts


# ---------------------------------------------------------- senaryo üretimi
def sources_block(arts):
    return "\n\n".join(
        f"[{i}] KAYNAK: {a['source']} | {a['url']}\n{a['text']}"
        for i, a in enumerate(arts, 1))


def extract_facts(key, models, topic, arts):
    prompt = (
        f"KONU: {topic['title']}\n\nAşağıdaki haber metinleri aynı olayı anlatıyor. "
        "Yalnızca kaynaklarda AÇIKÇA yazan olguları çıkar: kim, ne, ne zaman, nerede, "
        "kaç kişi, kaç lira, hangi kurum, kim ne açıkladı, kim ne dedi. Her olgu tek "
        "cümle olsun. Yalnızca AYNI olgu için kaynaklar açıkça farklı rakam ya da isim veriyorsa çelişkiyi ayrı olgu olarak yaz; farklı tarihler farklı olay adımlarına ait olabilir, çelişki ilan etme. Kaynaklarda geçen arka plan bilgilerini de (önceki olaylar, kurumlar, yasal çerçeve) olgu olarak ekle. "
        "Haberin merkezindeki kişilerin durumunu anlamak için gereken bağlamı da olgu olarak çıkar (kişi neden orada, neden tutuklu ya da yargılanıyor, hangi davanın parçası). En az 15 olgu çıkar (kaynak yeterliyse). Çok sayıda şüpheli ismi varsa tek olguda 'diğer şüpheliler' diye özetle, yalnızca en tanınan 3 ismi ayrı yaz; özel kişilerin adını yazma. Uydurma, yorum, tahmin ekleme.\n"
        + DATE_RULE.format(d=today_tr()) + "\n"
        'Çıktı: {"facts":[{"olgu":"...","kaynaklar":["NTV","Hürriyet"]}]}\n\n'
        + sources_block(arts))
    model, data = generate(key, models, prompt, system=FACT_SYSTEM, json_out=True,
                           temperature=0.1, max_tokens=12000)
    facts = []
    for f in data.get("facts", []):
        if isinstance(f, str):
            facts.append({"olgu": f, "kaynaklar": []})
        elif isinstance(f, dict) and f.get("olgu"):
            k = f.get("kaynaklar") or []
            facts.append({"olgu": str(f["olgu"]),
                          "kaynaklar": [k] if isinstance(k, str) else list(k)})
    return model, facts


def facts_text(facts):
    return "\n".join(
        f"- {f['olgu']} (kaynak: {', '.join(f['kaynaklar']) or '?'})" for f in facts)


def write_sections(key, models, topic, facts):
    ft = facts_text(facts)
    scale = max(0.5, min(1.0, len(facts) / 25.0))
    parts, so_far = [], ""
    for name, brief, words, scalable in SECTIONS:
        words = int(words * scale) if scalable else words
        prompt = (
            f"KONU: {topic['title']}\n{DATE_RULE.format(d=today_tr())}\n\nOLGULAR (sadece bunları kullan):\n{ft}\n\n"
            "Şu ana kadar yazılan metin (burada anlatılan hiçbir olguyu, rakamı ya da "
            "tarihi yeniden anlatma, akışı sürdür):\n"
            f"{so_far[-7000:] or '(henüz yok, ilk bölümü yazıyorsun)'}\n\n"
            f'ŞİMDİ YAZ: "{name}" bölümü. Görev: {brief}\n'
            f"Yaklaşık {words} kelime. Sadece okunacak metni yaz. Başlık, açıklama, "
            "kaynak notu, bölüm adı ekleme.")
        model, text = generate(key, models, prompt, temperature=0.9)
        models = [model] + [m for m in models if m != model]
        text = clean_script(text)
        parts.append(text)
        so_far += "\n" + text
        log(f"   {name}: {count_words(text)} kelime")
        time.sleep(PAUSE)
    return models, "\n\n".join(parts)


def clean_script(s):
    s = s.replace("—", ", ").replace("–", ", ")
    s = re.sub(r"[*#]+", "", s)
    s = re.sub(r"\[\s*duraklama\s*\]", "[duraklama]", s, flags=re.I)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def banned_found(s):
    low = tr_lower(s)
    return sorted({b for b in BANNED
                   if re.search(r"(?<![a-zçğıöşü])" + re.escape(b), low)})


LOADED = ["suçlu", "katil", "hırsız", "sahtekar", "sahtekâr", "azılı", "rezil"]


def loaded_found(s):
    low = tr_lower(s)
    return sorted({w for w in LOADED
                   if re.search(r"(?<![a-zçğıöşü])" + w + r"(?![a-zçğıöşü])", low)})


def has_name_list(s):
    """Arka arkaya 5+ özel ismin virgülle sıralandığı isim listesi var mı?"""
    nm = r"[A-ZÇĞİÖŞÜ][\wçğıöşüâîû’']+(?: [A-ZÇĞİÖŞÜ][\wçğıöşüâîû’']+)*"
    return bool(re.search(r"(?:" + nm + r", ){4,}" + nm, s))


def revise(key, models, script, instruction, facts):
    prompt = (
        f"{instruction}\n\nOLGULAR (yeni bilgi eklerken yalnızca bunları kullan):\n"
        f"{facts_text(facts)}\n\nMEVCUT SENARYO:\n{script}\n\n"
        'Çıktı: sadece {"script": "düzeltilmiş senaryonun tamamı"} JSON nesnesi. '
        "Aynı üslubu, [duraklama] işaretlerini ve hukuki dil kurallarını koru.")
    model, data = generate(key, models, prompt, json_out=True,
                           temperature=0.7, max_tokens=20000)
    s = data.get("script", "")
    return s if isinstance(s, str) and count_words(s) > 200 else script


def split_sentences(text):
    t = re.sub(r"\[duraklama\]", " ", text)
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+|\n+", t) if x.strip()]


def repeats(script):
    """Daha önce anlatılmış bir cümleyi büyük oranda tekrar eden cümleleri bulur."""
    seen, out = [], []
    for sent in split_sentences(script):
        tok = {w[:5] for w in re.findall(r"[a-zçğıöşü0-9]+", tr_lower(sent)) if len(w) >= 4}
        if len(tok) < 5:
            continue
        for old in seen:
            if len(tok & old) / min(len(tok), len(old)) >= 0.65:
                out.append(sent)
                break
        seen.append(tok)
    return out


def drop_self_intro(s):
    s = re.sub(r"(?:^|(?<=[.!?]\s))[^.!?\n]*\bBen Furkan\b[^.!?\n]*[.!?]?\s*", "", s)
    return s.strip()


def finalize_script(key, models, script, facts):
    script = drop_self_intro(clean_script(script))
    for _ in range(2):
        rp = repeats(script)
        if len(rp) < 2:
            break
        log(f"   {len(rp)} tekrar eden cümle bulundu, temizleniyor")
        script = drop_self_intro(clean_script(revise(
            key, models, script,
            "Bu senaryoda aynı bilgi birden fazla kez anlatılıyor. Aşağıdaki cümleler daha "
            "önce anlatılanı tekrar ediyor: bunları SİL (yerine yeni bilgi ekleyemiyorsan "
            "boş bırak, metin kısalsın). İlk anlatımı koru, akışın bozulmadığından emin ol. "
            "Metnin ilk paragrafını (kanca) ve son cümlesini ('Artık son tanık sizsiniz.') "
            "aynen koru.\n\nTEKRAR EDEN CÜMLELER:\n- " + "\n- ".join(rp[:25]), facts)))
        time.sleep(PAUSE)
    bf = banned_found(script)
    if bf:
        log(f"   yasak kalıplar bulundu: {bf}")
        script = drop_self_intro(clean_script(revise(
            key, models, script,
            "Şu ifadeleri içeren cümleleri doğal, konuşma dilinde yeniden yaz (başkasından "
            "aktaran 'derler' kalıbı yerine birinci tekil kişiyle kendi sözünü kur): "
            f"{', '.join(bf)}. Metnin geri kalanını olduğu gibi bırak.", facts)))
    if not script.rstrip().endswith("Artık son tanık sizsiniz."):
        script = script.rstrip() + "\n\nArtık son tanık sizsiniz."
    return script


def make_meta(key, models, topic, script, facts):
    prompt = (
        f"KONU: {topic['title']}\n\nOLGULAR:\n{facts_text(facts)}\n\n"
        f"SENARYO:\n{script}\n\n" + META_SCHEMA)
    model, data = generate(key, models, prompt, json_out=True,
                           temperature=0.8, max_tokens=8000)
    return data


def unverified(script, arts):
    allow = {"Furkan", "Tanık", "Son"}
    for a in arts:
        allow.update(re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşü]+", a["source"]))
    """Senaryodaki sayı ve özel isimlerden kaynaklarda geçmeyenleri bulur."""
    src = " ".join(a["text"] for a in arts)
    src_nums = {re.sub(r"[.,]", "", n) for n in re.findall(r"\d[\d.,]*\d|\d", src)}
    nums = {re.sub(r"[.,]", "", n) for n in re.findall(r"\d[\d.,]*\d|\d", script)}
    bad_nums = sorted(n for n in nums if len(n) >= 2 and n not in src_nums)

    stems = {tr_lower(w)[:5] for w in re.findall(r"[A-Za-zÇĞİÖŞÜçğıöşüâîû]+", src)}
    bad_names = set()
    for m in re.finditer(r"[A-ZÇĞİÖŞÜ][a-zçğıöşüâîû]+(?:['’][a-zçğıöşü]+)?", script):
        before = script[:m.start()].rstrip()
        if not before or before[-1] in ".!?:\n\"“”‘’]":
            continue
        base = re.split(r"['’]", m.group(0))[0]
        if base in allow:
            continue
        if len(base) >= 4 and tr_lower(base)[:5] not in stems:
            bad_names.add(base)
    return bad_nums, sorted(bad_names)


# --------------------------------------------------------------- çıktı yazma
def write_report(topic, arts, facts, meta, script, model, bad_nums, bad_names, warnings):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    words = count_words(script)
    minutes = round(words / 140)
    titles = meta.get("title_options") or [topic["title"]]
    L = [f"# Senaryo: {titles[0]}", "",
         f"- Konu: {topic['title']}",
         f"- Tarih: {today} | Kelime: {words} (yaklaşık {minutes} dk okuma) | Model: {model}",
         "- Durum: **Okumadan önce aşağıdaki 'KONTROL ET' bölümüne 2 dakika ayır.**", ""]
    if warnings:
        L += ["## Uyarılar", *[f"- {w}" for w in warnings], ""]
    L += ["## Başlık önerileri", *[f"{i}. {t}" for i, t in enumerate(titles, 1)], "",
          f"Küçük resim yazısı: {meta.get('thumbnail_text', '')}", "",
          "## KANCA (videonun ilk 10-20 saniyesi)", "", meta.get("hook", ""), "",
          "## OKUMA METNİ (kanca dahil, baştan sona)", "", script, "", "## Shorts parçaları", ""]
    for i, s in enumerate(meta.get("shorts") or [], 1):
        L += [f"### Short {i} ({s.get('bolum', '')})", f"Kanca: {s.get('hook', '')}", "",
              s.get("text", ""), ""]
    L += ["## Açıklama", "", meta.get("description", ""), "",
          "Etiketler: " + ", ".join(t for t in (meta.get("tags") or []) if "furkan" not in t.lower()), "",
          "## KONTROL ET", ""]
    for r in meta.get("risk_notes") or []:
        L.append(f"- Hukuken hassas: {r}")
    if bad_nums:
        L.append("- Kaynaklarda **bulunamayan sayılar**: " + ", ".join(bad_nums))
    if bad_names:
        L.append("- Kaynaklarda **bulunamayan özel isimler**: " + ", ".join(bad_names))
    if not (meta.get("risk_notes") or bad_nums or bad_names):
        L.append("- Otomatik kontrol bir sorun bulmadı (yine de bir göz at).")
    L += ["", "### Kullanılan olgular", facts_text(facts), "", "## Kaynaklar"]
    for i, a in enumerate(arts, 1):
        L.append(f"[{i}] {a['source']}: {a['url']}")
    md = "\n".join(L) + "\n"

    os.makedirs("scripts", exist_ok=True)
    with open("script_latest.md", "w", encoding="utf-8") as f:
        f.write(md)
    with open(f"scripts/{today}.md", "w", encoding="utf-8") as f:
        f.write(md)
    out = dict(meta)
    out.update({"script": script, "topic": topic["title"], "model": model,
                "words": words, "minutes": minutes, "date": today,
                "facts": facts, "unverified_numbers": bad_nums,
                "unverified_names": bad_names,
                "sources": [{"source": a["source"], "url": a["url"]} for a in arts]})
    with open("script_latest.json", "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    if os.path.exists("script_error.md"):
        os.remove("script_error.md")


def write_error(msg):
    for old in ("script_latest.md", "script_latest.json"):  # eski sonuç kafa karıştırmasın
        if os.path.exists(old):
            os.remove(old)
    with open("script_error.md", "w", encoding="utf-8") as f:
        f.write("# Senaryo yazılamadı\n\n" + msg + "\n")
    log("HATA:", msg)


def load_history():
    try:
        with open("history.json", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def candidates(tdata, history):
    out, seen = [], set()
    pool = ([tdata["selected"]] if tdata.get("selected") else []) + tdata.get("topics", [])
    used = [set(h.get("tok", [])) for h in history]
    def political(t):
        low = tr_lower(t["title"])
        return bool(t.get("sensitive")) or any(p in low for p in POLITICAL)

    def celeb(t):
        low = tr_lower(t["title"])
        return any(c in low for c in CELEB)

    # siyasi ve magazin konuları sona (önce ciddi suç/para/devlet dosyaları)
    pool = sorted(pool, key=lambda t: 1 if (political(t) or celeb(t)) else 0)
    for t in pool:
        if t["title"] in seen or t.get("single_source") or t.get("score", 0) <= 0:
            continue
        seen.add(t["title"])
        tok = story_tokens(t["title"])
        if any(same_story(tok, u) for u in used):
            log(f"   [atlandı: daha önce işlendi] {t['title'][:70]}")
            continue
        out.append(t)
    return out


def main():
    sources_only = "--sources-only" in sys.argv
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key and not sources_only:
        write_error("GEMINI_API_KEY bulunamadı. GitHub > Settings > Secrets and "
                    "variables > Actions bölümünde GEMINI_API_KEY adıyla ekli olmalı.")
        sys.exit(1)
    try:
        with open("topics.json", encoding="utf-8") as f:
            tdata = json.load(f)
    except Exception as e:
        write_error(f"topics.json okunamadı: {e}. Önce konu taraması çalışmalı.")
        sys.exit(1)

    history = load_history()
    cands = candidates(tdata, history)
    if not cands:
        write_error("Uygun konu yok (hepsi tek kaynaklı, düşük puanlı ya da daha önce işlenmiş).")
        sys.exit(1)

    try:
        models = None if sources_only else model_candidates(key)
    except GenerationFailed as e:
        write_error(str(e))
        sys.exit(1)
    if models:
        log("Denenecek modeller:", ", ".join(models))
    notes = []
    for topic in cands[:MAX_TOPICS_TRIED]:
        log(f"\nKonu: {topic['title']}")
        arts = gather(topic)
        total = sum(count_words(a["text"]) for a in arts)
        distinct = len({a["source"] for a in arts})
        log(f"   toplam kaynak: {len(arts)} makale, {distinct} site, {total} kelime")
        if models and len(arts) >= 2 and distinct >= 2:
            arts = add_background(key, models, topic, arts)
            total = sum(count_words(a["text"]) for a in arts)
            log(f"   arka plan dahil toplam: {len(arts)} makale, {total} kelime")
        if len(arts) < 2 or distinct < 2 or total < MIN_SOURCE_WORDS:
            notes.append(f"'{topic['title'][:60]}': yeterli kaynak metni okunamadı "
                         f"({len(arts)} makale, {total} kelime)")
            continue
        if sources_only:
            log("   kaynak okuma testi başarılı")
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        try:
            model, facts = extract_facts(key, models, topic, arts)
            models = [model] + [m for m in models if m != model]
            log(f"   {len(facts)} olgu çıkarıldı")
            if len(facts) < MIN_FACTS:
                raise GenerationFailed(f"yalnızca {len(facts)} olgu çıkarılabildi")
            time.sleep(PAUSE)
            models, script = write_sections(key, models, topic, facts)
            script = finalize_script(key, models, script, facts)
            time.sleep(PAUSE)
            meta = make_meta(key, models, topic, script, facts)
        except GenerationFailed as e:
            notes.append(f"'{topic['title'][:60]}': {e}")
            if "API anahtarı" in str(e) or isinstance(e, QuotaExceeded):
                break
            continue
        bad_nums, bad_names = unverified(script, arts)
        meta["hook"] = script.split("\n\n")[0].strip()
        warnings = []
        if count_words(script) < MIN_WORDS:
            warnings.append(f"Senaryo hedeften kısa kaldı ({count_words(script)} kelime). "
                            "Konunun malzemesi sınırlı olabilir.")
        if topic.get("sensitive"):
            warnings.append("Siyasi hassasiyet işaretli konu: metni özellikle dikkatle oku.")
        for i, sh in enumerate(meta.get("shorts") or [], 1):
            bad = banned_found(sh.get("text", "")) + loaded_found(sh.get("text", ""))
            if bad:
                warnings.append(f"Short {i} metninde sorunlu kalıp var: {', '.join(sorted(set(bad)))}")
        left = banned_found(script)
        if left:
            warnings.append("Metinde yasak kalıplar kaldı, elle düzelt: " + ", ".join(left))
        lw = loaded_found(script)
        if lw:
            warnings.append("Yargı yüklü kelime geçiyor (" + ", ".join(lw) +
                            "). Mahkûmiyet kesinleşmediyse bu cümleyi değiştir.")
        if has_name_list(script):
            warnings.append("Metinde isim listesi var. Özel kişilerin adlarını çıkar, "
                            "en fazla 3 tanınmış isim kalsın.")
        if any(a for a in arts if count_words(a["text"]) < 120):
            warnings.append("Bazı kaynaklarda yalnızca kısa özet okunabildi.")
        write_report(topic, arts, facts, meta, script, models[0],
                     bad_nums, bad_names, warnings)
        history.append({"date": today, "title": topic["title"],
                        "tok": sorted(story_tokens(topic["title"]))})
        with open("history.json", "w", encoding="utf-8") as f:
            json.dump(history[-60:], f, ensure_ascii=False, indent=1)
        log(f"\nTAMAM: script_latest.md yazıldı ({count_words(script)} kelime, model {models[0]})")
        return
    write_error("Hiçbir konu için senaryo üretilemedi:\n\n- " + "\n- ".join(notes or ["bilinmeyen neden"]))
    sys.exit(1)


if __name__ == "__main__":
    main()
