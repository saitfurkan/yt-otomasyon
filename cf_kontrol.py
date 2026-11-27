import base64, json, os, urllib.request, urllib.error
acc, tok = os.environ["CF_ACCOUNT_ID"].strip(), os.environ["CF_API_TOKEN"].strip()
H = {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}
def get(url):
    return urllib.request.urlopen(urllib.request.Request(url, headers=H), timeout=60).read().decode()
try:
    print("TOKEN", get("https://api.cloudflare.com/client/v4/user/tokens/verify")[:200])
except Exception as e:
    print("TOKEN HATA", str(e)[:150])
try:
    print("HESAP", get(f"https://api.cloudflare.com/client/v4/accounts/{acc}")[:300])
except Exception as e:
    print("HESAP HATA", str(e)[:150])
for model in ("black-forest-labs/flux-1-schnell", "bytedance/stable-diffusion-xl-lightning"):
    try:
        req = urllib.request.Request(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/{model}",
                                     data=json.dumps({"prompt": "a lighthouse at night, ink illustration", "steps": 1} if "flux" in model else {"prompt": "a lighthouse"}).encode(),
                                     headers=H, method="POST")
        r = urllib.request.urlopen(req, timeout=120)
        print("OK", model, r.status, len(r.read()))
    except urllib.error.HTTPError as e:
        print("HATA", model, e.code, e.read().decode()[:300], dict(e.headers).get("retry-after"))
    except Exception as e:
        print("HATA", model, str(e)[:200])
