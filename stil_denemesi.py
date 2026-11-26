import base64, json, os, urllib.request, urllib.error
acc, tok = os.environ["CF_ACCOUNT_ID"].strip(), os.environ["CF_API_TOKEN"].strip()
url = f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell"
styles = {
 "noir": "graphic novel noir illustration, bold ink lines, dramatic chiaroscuro, limited palette of black, warm grey and deep red accents, stylized illustrated characters, painterly texture, cinematic composition",
 "gouache": "editorial illustration in the style of a serious investigative documentary poster, gouache and ink, muted earth tones with one red accent, stylized faceless figures, strong silhouettes, grainy paper texture",
 "foto": "cinematic documentary photograph, dramatic low-key lighting, muted colors, 35mm film grain, shallow depth of field, realistic",
}
scenes = {
 "a": "two young brothers in a small apartment at night staring at a phone screen showing a huge bank balance, shocked, their faces lit by the blue light",
 "b": "a lone bank employee leaving an empty glass office tower at dawn while rows of glowing computer screens show endless numbers",
}
os.makedirs("ornekler", exist_ok=True)
for sk, st in styles.items():
    for ck, sc in scenes.items():
        body = {"prompt": f"{sc}, {st}, no text, no letters, no logos", "steps": 6}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
              headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"})
        try:
            r = json.load(urllib.request.urlopen(req, timeout=120))
            open(f"ornekler/{sk}_{ck}.jpg", "wb").write(base64.b64decode(r["result"]["image"]))
            print("ok", sk, ck)
        except urllib.error.HTTPError as e:
            print("hata", sk, ck, e.code, e.read().decode()[:150])
