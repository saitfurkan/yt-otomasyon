import base64, json, os, urllib.request, urllib.error
key = os.environ["GEMINI_API_KEY"].strip()
P = ("two adults in a dark apartment staring at a phone showing a huge bank balance, graphic novel noir illustration, "
     "bold ink lines, dramatic chiaroscuro, limited palette black warm grey deep red-orange, painterly, cinematic wide, no text")
os.makedirs("ornekler", exist_ok=True)
def post(url, body):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=180))
try:
    r = json.load(urllib.request.urlopen(f"https://generativelanguage.googleapis.com/v1beta/models?key={key}&pageSize=200", timeout=60))
    names = [m["name"] for m in r.get("models", []) if "image" in m["name"] or "imagen" in m["name"]]
    print("MODELLER", names)
except Exception as e:
    print("LISTE HATA", str(e)[:200]); names = []
for m in names:
    short = m.split("/")[-1]
    try:
        if "imagen" in short:
            r = post(f"https://generativelanguage.googleapis.com/v1beta/{m}:predict?key={key}",
                     {"instances": [{"prompt": P}], "parameters": {"sampleCount": 1, "aspectRatio": "16:9"}})
            b = r["predictions"][0]["bytesBase64Encoded"]
        else:
            r = post(f"https://generativelanguage.googleapis.com/v1beta/{m}:generateContent?key={key}",
                     {"contents": [{"parts": [{"text": P}]}], "generationConfig": {"responseModalities": ["TEXT", "IMAGE"]}})
            b = next(p["inlineData"]["data"] for p in r["candidates"][0]["content"]["parts"] if "inlineData" in p)
        open(f"ornekler/gem_{short}.png", "wb").write(base64.b64decode(b))
        print("OK", short)
    except urllib.error.HTTPError as e:
        print("HATA", short, e.code, e.read().decode()[:220].replace("\n", " "))
    except Exception as e:
        print("HATA", short, str(e)[:160])
