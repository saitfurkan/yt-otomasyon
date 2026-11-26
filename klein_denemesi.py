import base64, json, os, urllib.request, urllib.error, uuid
acc, tok = os.environ["CF_ACCOUNT_ID"].strip(), os.environ["CF_API_TOKEN"].strip()
P = ("two adults in a dark apartment staring at a phone showing a huge bank balance, graphic novel noir illustration, "
     "bold ink lines, dramatic chiaroscuro, limited palette black warm grey deep red-orange, painterly, cinematic, no text")
os.makedirs("ornekler", exist_ok=True)
def call(model, mode):
    url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/{model}"
    if mode == "json":
        data = json.dumps({"prompt": P, "steps": 20 if "dev" in model else 4}).encode(); ct = "application/json"
    else:
        b = uuid.uuid4().hex
        parts = {"prompt": P, "width": "1024", "height": "1024"}
        data = b"".join(f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in parts.items()) + f"--{b}--\r\n".encode()
        ct = f"multipart/form-data; boundary={b}"
    req = urllib.request.Request(url, data=data, method="POST", headers={"Authorization": f"Bearer {tok}", "Content-Type": ct})
    r = json.load(urllib.request.urlopen(req, timeout=180))
    return base64.b64decode(r["result"]["image"])
for model in ("black-forest-labs/flux-2-klein-4b", "black-forest-labs/flux-2-klein-9b", "leonardo/lucid-origin", "leonardo/phoenix-1.0"):
    for mode in ("json", "multipart"):
        try:
            img = call(model, mode)
            open(f"ornekler/{model.split('/')[1]}.jpg", "wb").write(img)
            print("OK", model, mode, len(img)); break
        except urllib.error.HTTPError as e:
            print("HATA", model, mode, e.code, e.read().decode()[:160])
        except Exception as e:
            print("HATA", model, mode, str(e)[:160])
