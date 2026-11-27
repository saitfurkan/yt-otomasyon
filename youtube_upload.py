"""YouTube Data API v3: refresh-token ile giriş, kaynaklı (resumable) yükleme, kapak ve zamanlama.
Gizli anahtarlar sadece ortam değişkenlerinden okunur: YT_CLIENT_ID, YT_CLIENT_SECRET, YT_REFRESH_TOKEN."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def access_token():
    data = urllib.parse.urlencode({
        "client_id": os.environ["YT_CLIENT_ID"], "client_secret": os.environ["YT_CLIENT_SECRET"],
        "refresh_token": os.environ["YT_REFRESH_TOKEN"], "grant_type": "refresh_token"}).encode()
    with urllib.request.urlopen(urllib.request.Request("https://oauth2.googleapis.com/token", data=data), timeout=40) as r:
        return json.load(r)["access_token"]


THUMB_ERR = {"msg": ""}


def upload(path, title, description, tags, publish_at=None, shorts=False, thumb=None, category="25"):
    tok = access_token()
    status = {"privacyStatus": "private" if publish_at else "public", "selfDeclaredMadeForKids": False}
    if publish_at:
        status["publishAt"] = publish_at          # ISO 8601, örn. 2026-11-29T16:00:00Z
    body = {"snippet": {"title": title[:100], "description": description[:4900], "tags": tags[:15],
                        "categoryId": category, "defaultLanguage": "tr", "defaultAudioLanguage": "tr"},
            "status": status}
    size = os.path.getsize(path)
    req = urllib.request.Request(
        "https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status",
        data=json.dumps(body).encode(), method="POST",
        headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json; charset=UTF-8",
                 "X-Upload-Content-Length": str(size), "X-Upload-Content-Type": "video/mp4"})
    with urllib.request.urlopen(req, timeout=60) as r:
        loc = r.headers["Location"]
    chunk = 8 * 1024 * 1024
    sent = 0
    with open(path, "rb") as f:
        while sent < size:
            data = f.read(chunk)
            end = sent + len(data) - 1
            for attempt in range(5):
                try:
                    rq = urllib.request.Request(loc, data=data, method="PUT", headers={
                        "Content-Length": str(len(data)), "Content-Range": f"bytes {sent}-{end}/{size}"})
                    with urllib.request.urlopen(rq, timeout=300) as r:
                        res = json.load(r)
                        vid = res["id"]
                        break
                except urllib.error.HTTPError as e:
                    if e.code == 308:
                        vid = None
                        break
                    if attempt == 4:
                        raise
                    time.sleep(3 * (attempt + 1))
            sent += len(data)
    if thumb and vid:
        try:
            rq = urllib.request.Request(
                f"https://www.googleapis.com/upload/youtube/v3/thumbnails/set?videoId={vid}",
                data=open(thumb, "rb").read(), method="POST",
                headers={"Authorization": f"Bearer {tok}", "Content-Type": "image/jpeg"})
            urllib.request.urlopen(rq, timeout=60).read()
            THUMB_ERR["msg"] = ""
        except Exception as e:
            THUMB_ERR["msg"] = str(e)[:150]
            print("kapak yüklenemedi:", str(e)[:150])
    return vid


if __name__ == "__main__":
    print(upload(sys.argv[1], "test", "test", [], None))
