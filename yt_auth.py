"""Tek seferlik: YouTube izni için cihaz kodu akışı. Kodu Telegram'dan gönderir, onayı bekler,
refresh token'ı yine Telegram'dan (senin özel sohbetine) gönderir."""
import json, os, time, urllib.error, urllib.parse, urllib.request

TOKEN = os.environ["TELEGRAM_BOT_TOKEN"].strip()
CID, CSEC = os.environ["YT_CLIENT_ID"].strip(), os.environ["YT_CLIENT_SECRET"].strip()


def tg(method, **p):
    data = urllib.parse.urlencode(p).encode()
    with urllib.request.urlopen(urllib.request.Request(f"https://api.telegram.org/bot{TOKEN}/{method}", data=data), timeout=60) as r:
        return json.load(r)["result"]


def post(url, **p):
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=urllib.parse.urlencode(p).encode()), timeout=40) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read().decode())


ups = tg("getUpdates", timeout=0)
chats = [u["message"]["chat"]["id"] for u in ups if "message" in u]
if not chats:
    raise SystemExit("Önce Telegram'da bota herhangi bir mesaj yaz (örnek: merhaba), sonra bu işi tekrar çalıştır.")
chat = chats[-1]
dc = post("https://oauth2.googleapis.com/device/code", client_id=CID,
          scope="https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube")
if "device_code" not in dc:
    tg("sendMessage", chat_id=chat, text="Google hatası: " + json.dumps(dc)[:500])
    raise SystemExit(dc)
tg("sendMessage", chat_id=chat, text=f"YouTube izni için: google.com/device adresine git, bu kodu yaz: {dc['user_code']}\n"
   "Kanalının hesabıyla giriş yap ve izin ver. 15 dakikan var.")
end = time.time() + 900
while time.time() < end:
    time.sleep(max(5, dc.get("interval", 5)))
    r = post("https://oauth2.googleapis.com/token", client_id=CID, client_secret=CSEC, device_code=dc["device_code"],
             grant_type="urn:ietf:params:oauth:grant-type:device_code")
    if "refresh_token" in r:
        tg("sendMessage", chat_id=chat, text="Tamam! Bu kodu GitHub'da YT_REFRESH_TOKEN adıyla secret olarak ekle:")
        tg("sendMessage", chat_id=chat, text=r["refresh_token"])
        print("token gönderildi")
        break
    if r.get("error") not in ("authorization_pending", "slow_down"):
        tg("sendMessage", chat_id=chat, text="Hata: " + json.dumps(r)[:400])
        raise SystemExit(r)
else:
    tg("sendMessage", chat_id=chat, text="Süre doldu, işi tekrar çalıştır.")
