import time, os, urllib.parse, urllib.request, urllib.error
P = ("two adults in a dark apartment staring at a phone showing a huge bank balance, graphic novel noir illustration, "
     "bold ink lines, dramatic chiaroscuro, limited palette black warm grey deep red-orange, painterly, cinematic, no text")
os.makedirs("ornekler", exist_ok=True)
for name, url in (
    ("poll_flux", "https://image.pollinations.ai/prompt/" + urllib.parse.quote(P) + "?model=flux&width=1280&height=720&nologo=true&seed=3"),
    ("poll_turbo", "https://image.pollinations.ai/prompt/" + urllib.parse.quote(P) + "?model=turbo&width=1280&height=720&nologo=true&seed=3"),
):
  for deneme in range(6):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        data = urllib.request.urlopen(req, timeout=180).read()
        open(f"ornekler/{name}.jpg", "wb").write(data)
        print("OK", name, len(data), data[:4])
        break
    except urllib.error.HTTPError as e:
        print("HATA", name, e.code, e.read()[:120])
        import time; time.sleep(50)
    except Exception as e:
        print("HATA", name, str(e)[:200]); break
