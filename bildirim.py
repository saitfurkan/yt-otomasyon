"""Günlük hatırlatma: bekleyen (henüz sesi alınmamış) senaryo varsa Telegram'dan haber verir."""
import json
import os
import sys
import urllib.parse
import urllib.request

import video_pipeline as vp

HERE = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def main():
    cid_file = os.path.join(HERE, ".chat", "id")
    if not TOKEN or not os.path.exists(cid_file):
        print("sohbet kimliği henüz yok, atlandı")
        return
    chat = open(cid_file).read().strip()
    read = lambda n: open(os.path.join(HERE, "assets", n)).read().split() if os.path.exists(os.path.join(HERE, "assets", n)) else []
    done, told = read("bitenler.txt"), read("bildirim.txt")
    scripts = sorted(f[:-3] for f in os.listdir(os.path.join(HERE, "hazir")) if f.endswith(".md"))
    pending = [s for s in scripts if s not in done]
    if not pending:
        print("bekleyen senaryo yok")
        return
    sid = pending[0]
    meta, paras, _ = vp.parse_script(os.path.join(HERE, "hazir", sid + ".md"))
    minutes = round(sum(len(p.split()) for p in paras) / 150)
    if sid in told:
        text = f"Hatırlatma: \"{meta['BAŞLIK']}\" senaryosu seni bekliyor (okuması ~{minutes} dk). Hazır olduğunda /senaryo yaz."
    else:
        text = (f"Yeni senaryo hazır: \"{meta['BAŞLIK']}\" (okuması ~{minutes} dk).\n"
                "Müsait olduğunda /senaryo yaz, metni sana göndereyim; okuyup sesli mesaj at, sonda /bitti yaz.")
    data = urllib.parse.urlencode({"chat_id": chat, "text": text}).encode()
    urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/sendMessage", data=data), timeout=60).read()
    if sid not in told:
        os.makedirs(os.path.join(HERE, "assets"), exist_ok=True)
        open(os.path.join(HERE, "assets", "bildirim.txt"), "a").write(sid + "\n")
    print("bildirim gönderildi:", sid)


if __name__ == "__main__":
    main()
