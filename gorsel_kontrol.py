"""Senaryo 02 için çekilen fotoğrafları ve müzik adaylarını ornekler/ altına yazar (gözle kontrol)."""
import os, sys, shutil
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import commons, video_pipeline as vp
from PIL import Image
meta, paras, hook_n = vp.parse_script("hazir/02-kumarbaz-futbol-kulubu.md")
spec = []
for hdr, person in (("GÖRSELLER", False), ("KİŞİLER", True)):
    for part in (meta.get(hdr) or "").split(";"):
        if part.strip():
            k, _, q = part.partition("=")
            spec.append((k.strip(), (q or k).strip(), person))
res = commons.fetch_map(spec, "_gk", per_query=3)
os.makedirs("ornekler/gk", exist_ok=True)
for k, items in res.items():
    for i, it in enumerate(items):
        im = Image.open(it["path"]); im.thumbnail((640, 360)); im.save(f"ornekler/gk/{k.replace(' ', '_')}_{i}.jpg", quality=80)
        print("FOTO", k, i, it["credit"][:200])
c = commons.music_search(sum(map(ord, meta["BAŞLIK"])))
for x in c[:15]:
    print("MUZIK", x[0], x[1][:80], x[3], x[4], x[5])
