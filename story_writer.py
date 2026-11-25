"""Geçmişten bugüne hikâye senaryosu (güncel haber modülünden AYRI).
Kaynaklar: Vikipedi (TR/EN) + Bing Haber aramaları. Çıktı: story/ klasörü."""
import json, os, re, sys, time, urllib.parse, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import script_writer as sw

STORY_SECTIONS = [
    ("KANCA", "Videonun ilk 10-20 saniyesi, TEK PARAGRAF, 35-55 kelime. Konuya özel yeni, kısa, sert bir söz (birinci tekil kişiyle, genel adalet/para/hırs hükmü), sonra şaşırtıcı somut bir rakam ya da merak uyandıran soru. Şiirli imge yok. Hikâyenin sonunu verme. Sonuna [duraklama] koy.", 45, False),
    ("BAŞLANGIÇ", "Hikâyenin başı: kim, nerede, hangi koşullarda, ne zaman. Sahneyi somut olgularla kur, kişiyi tanıt (kimdi, ne iş yapardı). Tarihleri ver.", 320, True),
    ("KIRILMA", "Her şeyi değiştiren fikir, karar ya da olay. Nasıl çalıştığını ya da nasıl ters gittiğini adım adım, sade anlat. Rakamlar ve tarihler olgulardan.", 360, True),
    ("PARA VE ADIMLAR", "Para nereden geldi, nereye gitti, kimler vardı, hangi hamleler yapıldı. Rakamlarla, sırayla. Önceki bölümü tekrar etme.", 360, True),
    ("YÜKSELİŞ YA DA ÇÖKÜŞ", "Hikâyenin zirvesi ve çöküşü ya da yükselişi. Dönüm noktaları, tepkiler, ortaya çıkış anı.", 320, True),
    ("HESAP VE SONUÇ", "Hukuki ya da kurumsal sonuç: kararlar, cezalar, tazminatlar, itirazlar, taraflar ne dedi. Kesinleşmemiş her şeyi 'iddia', 'mahkemeye göre' diye kaynağa bağla. Furkan olarak adalet/eşitlik üzerinden keskin ama olguya dayalı bir yorum yap.", 300, True),
    ("BUGÜN", "Bugün ne durumda, ne değişti, bu hikâye bize ne öğretiyor (ders vaaz gibi olmasın, tek net cümle). Önceki bölümleri tekrar etme.", 220, True),
    ("KAPANIŞ", "Bu hikâyeye özel, iki kelimeyle cevaplanabilecek TEK bir soru sor (A mı B mi, biliyor muydunuz). Kişi hakkında 'suçlu mu' diye sorma. Metnin son cümlesi birebir: Artık son tanık sizsiniz. Özet ve abone daveti yok.", 60, False),
]

def wiki_text(lang, title):
    url = (f"https://{lang}.wikipedia.org/w/api.php?action=query&prop=extracts&explaintext=1"
           f"&redirects=1&format=json&titles={urllib.parse.quote(title)}")
    req = urllib.request.Request(url, headers={"User-Agent": sw.UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    pages = list(data.get("query", {}).get("pages", {}).values())
    if not pages or "missing" in pages[0] or not (pages[0].get("extract") or "").strip():
        # başlık tutmadıysa Vikipedi aramasındaki ilk sonucu al
        surl = (f"https://{lang}.wikipedia.org/w/api.php?action=query&list=search&srlimit=1&format=json&srsearch="
                f"{urllib.parse.quote(title)}")
        with urllib.request.urlopen(urllib.request.Request(surl, headers={"User-Agent": sw.UA}), timeout=30) as r:
            hit = (json.load(r).get("query", {}).get("search") or [{}])[0].get("title")
        if not hit or hit == title:
            return ""
        return wiki_text(lang, hit)
    for p in pages:
        t = p.get("extract") or ""
        t = re.sub(r"\n==+ *(See also|References|External links|Further reading|Notes|Kaynakça|Dış bağlantılar|Ayrıca bakınız)[\s\S]*$", "", t)
        return re.sub(r"\n==+ *([^=\n]+?) *==+\n", r"\n\1\n", t).strip()
    return ""

def bing(query, mkt, known):
    url = ("https://www.bing.com/news/search?format=rss&mkt=%s&q=%s" % (mkt, urllib.parse.quote(query)))
    req = urllib.request.Request(url, headers={"User-Agent": sw.UA})
    import xml.etree.ElementTree as ET
    with urllib.request.urlopen(req, timeout=25) as r:
        xml = r.read()
    out = []
    for it in ET.fromstring(xml).iter("item"):
        link = (it.findtext("link") or "").strip()
        real = (urllib.parse.parse_qs(urllib.parse.urlparse(link).query).get("url") or [link])[0]
        host = urllib.parse.urlparse(real).netloc.lower()
        if not real.startswith("http") or real in known or "bing.com" in host or any(b in host for b in sw.BAD_HOSTS):
            continue
        known.add(real); out.append((real, host.replace("www.", "")))
    return out[:6]

def build_sources(story):
    arts, known = [], set()
    for lang, title in story["wiki"]:
        try:
            t = wiki_text(lang, title)
        except Exception as e:
            sw.log(f"   [vikipedi hata] {lang}:{title}: {str(e)[:80]}"); continue
        if sw.count_words(t) >= 150:
            arts.append({"source": f"Vikipedi ({lang}): {title}", "url": f"https://{lang}.wikipedia.org/wiki/{urllib.parse.quote(title.replace(' ', '_'))}", "text": t[:14000]})
            sw.log(f"   [vikipedi ok] {lang}:{title}: {sw.count_words(t)} kelime")
    terms = [x.lower() for x in story["terms"]]
    total = sum(len(a["text"]) for a in arts)
    for q, mkt in story["queries"]:
        try:
            links = bing(q, mkt, known)
        except Exception as e:
            sw.log(f"   [bing hata] {q}: {str(e)[:80]}"); continue
        for url, host in links:
            if total > sw.TOTAL_CHARS - 4000 or len(arts) >= 16:
                break
            try:
                text = sw.fetch_article(url)
            except Exception as e:
                continue
            if sw.count_words(text) < 200 or not any(t in text.lower() for t in terms):
                continue
            arts.append({"source": host, "url": url, "text": text[:8000]}); total += min(len(text), 8000)
            sw.log(f"   [haber ok] {host}: {sw.count_words(text)} kelime")
    return arts

def extract_all(key, models, topic, arts):
    """Her kaynaktan ayrı olgu çıkarır (tek çağrıda uzun metinlerden az olgu geliyor)."""
    facts, seen, model = [], set(), models[0]
    for a in arts:
        try:
            model, fs = sw.extract_facts(key, models, topic, [a])
            models = [model] + [m for m in models if m != model]
        except sw.GenerationFailed as e:
            if isinstance(e, sw.QuotaExceeded):
                raise
            sw.log(f"   [olgu çıkarılamadı] {a['source']}: {str(e)[:80]}")
            continue
        n = 0
        for f in fs:
            k = re.sub(r"\W+", "", f["olgu"].lower())[:70]
            if k in seen:
                continue
            seen.add(k); facts.append(f); n += 1
        sw.log(f"   {a['source']}: +{n} olgu")
        time.sleep(sw.PAUSE)
    return model, facts[:110]


def main():
    only = os.environ.get("STORY_ID", "").strip()
    with open(os.path.join(HERE, "stories.json"), encoding="utf-8") as f:
        stories = json.load(f)
    os.makedirs(os.path.join(HERE, "story"), exist_ok=True)
    os.chdir(os.path.join(HERE, "story"))
    done = {h.get("id") for h in sw.load_history()}
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sw.write_error("GEMINI_API_KEY bulunamadı."); sys.exit(1)
    todo = [s for s in stories if (s["id"] == only if only else s["id"] not in done)]
    if not todo:
        sw.write_error("İşlenecek hikâye kalmadı."); sys.exit(1)
    try:
        models = sw.model_candidates(key)
    except sw.GenerationFailed as e:
        sw.write_error(str(e)); sys.exit(1)
    sw.SECTIONS[:] = STORY_SECTIONS
    notes = []
    for st in todo[:3]:
        topic = {"title": st["title"]}
        sw.log(f"\nHikâye: {st['title']}")
        arts = build_sources(st)
        total = sum(sw.count_words(a["text"]) for a in arts)
        sw.log(f"   toplam kaynak: {len(arts)} metin, {total} kelime")
        if len(arts) < 2 or total < 1500:
            notes.append(f"'{st['title']}': yeterli kaynak yok"); continue
        try:
            model, facts = extract_all(key, models, topic, arts)
            models = [model] + [m for m in models if m != model]
            sw.log(f"   {len(facts)} olgu çıkarıldı")
            if len(facts) < sw.MIN_FACTS:
                raise sw.GenerationFailed(f"yalnızca {len(facts)} olgu")
            time.sleep(sw.PAUSE)
            models, script = sw.write_sections(key, models, topic, facts)
            script = sw.finalize_script(key, models, script, facts)
            time.sleep(sw.PAUSE)
            try:
                meta = sw.make_meta(key, models, topic, script, facts)
            except sw.GenerationFailed as e:
                if isinstance(e, sw.QuotaExceeded): raise
                meta = {"title_options": [st["title"]], "shorts": [], "description": "", "tags": [], "thumbnail_text": "", "risk_notes": []}
        except sw.GenerationFailed as e:
            notes.append(f"'{st['title']}': {e}")
            if isinstance(e, sw.QuotaExceeded): break
            continue
        bad_nums, bad_names = sw.unverified(script, arts)
        meta["hook"] = script.split("\n\n")[0].strip()
        warns = list(sw.PIPE_WARNINGS); sw.PIPE_WARNINGS.clear()
        if sw.PIPE_DROPPED:
            warns.append(f"{len(sw.PIPE_DROPPED)} cümle olgu listesinde karşılığı olmadığı için silindi.")
        sw.write_report(topic, arts, facts, meta, script, models[0], bad_nums, bad_names, warns)
        sw.PIPE_DROPPED.clear()
        h = sw.load_history(); h.append({"id": st["id"], "title": st["title"], "date": time.strftime("%Y-%m-%d")})
        json.dump(h[-80:], open("history.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        sw.log(f"\nTAMAM: story/script_latest.md ({sw.count_words(script)} kelime)")
        return
    sw.write_error("Hikâye yazılamadı:\n\n- " + "\n- ".join(notes or ["bilinmeyen neden"])); sys.exit(1)

if __name__ == "__main__":
    main()
