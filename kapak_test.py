"""Kanalın en son yüklenen videosuna kapak koymayı dener, YouTube'un tam cevabını yazar."""
import json, os, sys, urllib.request, urllib.error
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import youtube_upload as yu
tok = yu.access_token()
H = {"Authorization": f"Bearer {tok}"}
def get(url):
    return json.load(urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=40))
ch = get("https://www.googleapis.com/youtube/v3/channels?part=contentDetails,status&mine=true")["items"][0]
print("KANAL DURUM", json.dumps(ch.get("status"), ensure_ascii=False))
pl = ch["contentDetails"]["relatedPlaylists"]["uploads"]
items = get(f"https://www.googleapis.com/youtube/v3/playlistItems?part=snippet&maxResults=5&playlistId={pl}")["items"]
for it in items:
    print("VIDEO", it["snippet"]["resourceId"]["videoId"], it["snippet"]["title"][:60])
vid = items[0]["snippet"]["resourceId"]["videoId"]
rq = urllib.request.Request(f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                            data=open("ornekler/kapak_son.jpg", "rb").read(), method="POST",
                            headers={**H, "Content-Type": "image/jpeg"})
try:
    r = urllib.request.urlopen(rq, timeout=60)
    print("KAPAK TAMAM", r.status)
except urllib.error.HTTPError as e:
    print("KAPAK HATA", e.code, e.read().decode()[:600])
