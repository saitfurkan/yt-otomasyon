"""Telegram'dan sesleri alır, videoyu üretir, YouTube'a zamanlanmış yükler.
Komutlar (sadece sen yazarsın):
  /senaryo 01-samsun-16-milyar   -> hangi senaryo (hazir/ klasöründeki dosya adı)
  (sonra sesli mesaj(lar)ı gönder)
  /bitti                         -> üretimi başlatır
  /ident  (sesli mesaja yanıt/altyazı olarak 'ident' yaz) -> açılış sesini kaydeder
Durum tutmaz: Telegram güncellemeleri /bitti işlenene kadar bekletilir."""
import datetime
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request

import video_pipeline as vp

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}"
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, "_work")


def tg(method, **params):
    data = urllib.parse.urlencode(params).encode()
    with urllib.request.urlopen(urllib.request.Request(f"{API}/{method}", data=data), timeout=60) as r:
        return json.load(r)["result"]


SES = os.path.join(HERE, ".ses")


def keep_voices(files, sid):
    """Sesleri (özel) Actions önbelleğinde sakla: video hatalıysa yeniden söylemen gerekmez (/tekrar)."""
    shutil.rmtree(SES, ignore_errors=True)
    os.makedirs(SES)
    for i, f in enumerate(files):
        shutil.copy(f, os.path.join(SES, f"in{i:03d}"))
    open(os.path.join(SES, "sid.txt"), "w").write(sid)


def LATEST():
    fs = sorted(f for f in os.listdir(os.path.join(HERE, "hazir")) if f.endswith(".md"))
    return fs[-1][:-3] if fs else ""


def say(chat, text):
    try:
        tg("sendMessage", chat_id=chat, text=text[:3900])
    except Exception as e:
        print("mesaj gönderilemedi:", e)


def fetch_file(file_id, dest):
    info = tg("getFile", file_id=file_id)
    url = f"https://api.telegram.org/file/bot{TOKEN}/{info['file_path']}"
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    return dest


def audio_of(msg):
    for k in ("voice", "audio"):
        if k in msg:
            return msg[k]["file_id"]
    d = msg.get("document")
    if d and (d.get("mime_type", "").startswith("audio") or d.get("file_name", "").lower().endswith((".m4a", ".mp3", ".wav", ".ogg", ".aac"))):
        return d["file_id"]
    return None


def next_slot(n):
    """n. video için yayın zamanı: yarın 16:00 UTC (19:00 Türkiye) + n gün."""
    d = datetime.datetime.utcnow().date() + datetime.timedelta(days=1 + n)
    return datetime.datetime(d.year, d.month, d.day, 16, 0).strftime("%Y-%m-%dT%H:%M:%SZ")


def main():
    if not TOKEN:
        print("TELEGRAM_BOT_TOKEN yok")
        return
    ups = tg("getUpdates", timeout=0, allowed_updates=json.dumps(["message"]))
    msgs = [(u["update_id"], u["message"]) for u in ups if "message" in u]
    if not msgs:
        print("yeni mesaj yok")
        return
    # günlük hatırlatma için sohbet kimliğini sakla (depoya yazılmaz, Actions önbelleğinde tutulur)
    os.makedirs(os.path.join(HERE, ".chat"), exist_ok=True)
    open(os.path.join(HERE, ".chat", "id"), "w").write(str(msgs[-1][1]["chat"]["id"]))
    # ident kaydı
    last_id = msgs[-1][0]
    ident_done = False
    ident_idx = set()
    for i, (uid, m) in enumerate(msgs):
        if (m.get("text") or "").strip().lower().lstrip("/") in ("ident", "ıdent", "i̇dent") and i > 0 and audio_of(msgs[i - 1][1]):
            ident_idx.add(i - 1)
    for i, (uid, m) in enumerate(msgs):
        cap = (m.get("caption") or m.get("text") or "").lower()
        fid = audio_of(m)
        if fid and ("ident" in cap or i in ident_idx):
            os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
            fetch_file(fid, os.path.join(HERE, "assets", "ident_raw"))
            vp.run(["ffmpeg", "-y", "-loglevel", "error", "-i", os.path.join(HERE, "assets", "ident_raw"),
                    "-ar", "44100", "-ac", "1", os.path.join(HERE, "assets", "ident.wav")])
            os.remove(os.path.join(HERE, "assets", "ident_raw"))
            say(m["chat"]["id"], "Açılış sesi kaydedildi. Bundan sonra her videoda kullanılacak.")
            ident_done = True
    # /senaryo yazılınca okuma metnini sohbete gönder (bir kez)
    sidx = [i for i, (_, m) in enumerate(msgs) if re.match(r"/senaryo(\s+\S+)?\s*$", (m.get("text") or "").strip(), re.I)]
    if sidx:
        uid_s, m_s = msgs[sidx[-1]]
        stfile = os.path.join(HERE, "assets", "gonderildi.txt")
        done = open(stfile).read().split() if os.path.exists(stfile) else []
        if str(uid_s) not in done:
            sid_s = (re.match(r"/senaryo\s+(\S+)", m_s["text"].strip(), re.I) or [None, LATEST()])[1]
            sp = os.path.join(HERE, "hazir", sid_s if sid_s.endswith(".md") else sid_s + ".md")
            if os.path.exists(sp):
                meta_s, paras_s, hook_s = vp.parse_script(sp)
                chat_s = m_s["chat"]["id"]
                say(chat_s, f"Senaryo: {meta_s.get('BAŞLIK', sid_s)}\nAşağıdaki metni sırayla sesli mesaj olarak gönder, "
                            "bitince /bitti yaz. (Açılış cümlesini ayrıca okuma, otomatik eklenir.)")
                for n_, p_ in enumerate(paras_s, 1):
                    say(chat_s, f"{n_}/{len(paras_s)}\n{p_}")
                os.makedirs(os.path.dirname(stfile), exist_ok=True)
                open(stfile, "a").write(str(uid_s) + "\n")
    # son /bitti
    idx = [i for i, (_, m) in enumerate(msgs) if (m.get("text") or "").strip().lower().startswith(("/bitti", "/tekrar"))]
    if not idx:
        if ident_done:
            tg("getUpdates", offset=last_id + 1)
        print("/bitti yok, bekleniyor")
        return
    end = idx[-1]
    start = 0
    sid = None
    repeat = (msgs[end][1].get("text") or "").strip().lower().startswith("/tekrar")
    if repeat:
        chat = msgs[end][1]["chat"]["id"]
        sf = os.path.join(SES, "sid.txt")
        if not os.path.exists(sf):
            say(chat, "Saklı ses bulamadım (önbellek temizlenmiş olabilir). /senaryo ile baştan gönder.")
            tg("getUpdates", offset=msgs[end][0] + 1)
            return
        sid = open(sf).read().strip()
        start = end
    for i in range(end if not repeat else -1, -1, -1):
        t = (msgs[i][1].get("text") or "").strip()
        mm = re.match(r"/senaryo(?:\s+(\S+))?\s*$", t, re.I)
        if mm:
            start, sid = i, (mm.group(1) or LATEST())
            break
    chat = msgs[end][1]["chat"]["id"]
    if not sid:
        say(chat, "Önce /senaryo ve dosya adını yaz. Örnek: /senaryo 01-samsun-16-milyar")
        tg("getUpdates", offset=msgs[end][0] + 1)
        return
    spath = os.path.join(HERE, "hazir", sid if sid.endswith(".md") else sid + ".md")
    if not os.path.exists(spath):
        say(chat, f"hazir/{sid}.md bulunamadı. Dosya adını kontrol et.")
        tg("getUpdates", offset=msgs[end][0] + 1)
        return
    if repeat:
        voices = sorted(f for f in os.listdir(SES) if f.startswith("in"))
    else:
        voices = [audio_of(m) for j, (_, m) in enumerate(msgs[start:end], start) if audio_of(m) and j not in ident_idx and "ident" not in (m.get("caption") or "").lower()]
    if not voices:
        say(chat, "Ses bulamadım. Sesli mesajları /senaryo ile /bitti arasında gönder.")
        tg("getUpdates", offset=msgs[end][0] + 1)
        return
    say(chat, f"{len(voices)} ses aldım. Video hazırlanıyor, yaklaşık 30-40 dakika sürer.")
    shutil.rmtree(WORK, ignore_errors=True)
    os.makedirs(WORK)
    if repeat:
        files = []
        for i, f in enumerate(voices):
            shutil.copy(os.path.join(SES, f), os.path.join(WORK, f"in{i}"))
            files.append(os.path.join(WORK, f"in{i}"))
    else:
        files = [fetch_file(f, os.path.join(WORK, f"in{i}")) for i, f in enumerate(voices)]
        keep_voices(files, sid)
    ident = os.path.join(HERE, "assets", "ident.wav")
    out = os.path.join(WORK, "out")
    try:
        info = vp.render_all(spath, files, ident if os.path.exists(ident) else None, out, os.path.join(WORK, "w"))
    except Exception as e:
        say(chat, "Video üretiminde hata oldu: " + str(e)[-600:] + "\nTekrar denemek için /senaryo, sesler ve /bitti'yi yeniden gönder.")
        tg("getUpdates", offset=msgs[end][0] + 1)
        raise
    tg("getUpdates", offset=msgs[end][0] + 1)          # işlendi
    if info.get("kontrol"):
        say(chat, "Okuma kontrolü:\n" + info["kontrol"])
    qa = info.get("qa") or {}
    say(chat, "Kalite kontrol: " + ("TAMAM" if qa.get("ok") else "SORUNLU") + f" | ses {qa.get('ses_db')} dB, "
              f"ses-görüntü farkı {qa.get('fark_sn')} sn, altyazı kayması medyan {qa.get('kayma_medyan')} sn"
        + ("\n" + "\n".join(qa.get("notlar", [])) if qa.get("notlar") else ""))
    if not qa.get("ok"):
        say(chat, "Video hatalı göründüğü için YouTube'a YÜKLEMEDİM. Sorunu düzeltip /tekrar yazarsan aynı seslerle yeniden üretirim.")
        return
    os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
    open(os.path.join(HERE, "assets", "bitenler.txt"), "a").write(os.path.basename(spath)[:-3] + "\n")
    meta = info["meta"]
    title = meta["BAŞLIK"]
    desc = meta.get("AÇIKLAMA") or (title + "\n\nSon Tanık: karar verilmeden önce, son sözü tanık söyler.")
    if info.get("credits"):
        desc += "\n\nGörseller (Wikimedia Commons):\n" + "\n".join(info["credits"])
    tags = [t.strip() for t in meta.get("ETİKETLER", "son tanık,gerçek hikaye,belgesel").split(",") if t.strip()]
    if all(os.environ.get(k) for k in ("YT_CLIENT_ID", "YT_CLIENT_SECRET", "YT_REFRESH_TOKEN")):
        import youtube_upload as yu
        lines = []
        try:
            vid = yu.upload(info["video"], title, desc, tags, publish_at=next_slot(0), thumb=info["thumbnail"])
            lines.append(f"Ana video yüklendi (zamanlandı): https://youtu.be/{vid}")
            for n, s in enumerate(info["shorts"], 1):
                sv = yu.upload(s["file"], f"{s['hint']}... #Shorts"[:95], desc + "\n#Shorts", tags + ["shorts"],
                               publish_at=next_slot(n))
                lines.append(f"Short {n}: https://youtu.be/{sv}")
            say(chat, "\n".join(lines) + "\nYouTube Studio'dan kontrol edebilirsin.")
        except Exception as e:
            say(chat, "\n".join(lines) + "\nYouTube yükleme hatası: " + str(e)[:500])
            raise
    else:
        say(chat, "Video hazır ama YouTube anahtarları yok, yüklenmedi.")


if __name__ == "__main__":
    main()
