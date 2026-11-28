"""En yeni senaryoyu (ya da SENARYO ortam değişkenindeki dosyayı) Telegram sohbetine gönderir."""
import os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import telegram_intake as ti
import video_pipeline as vp
cid = open(os.path.join(HERE, ".chat", "id")).read().strip()
name = os.environ.get("SENARYO", "").strip() or ti.LATEST()
sp = os.path.join(HERE, "hazir", name if name.endswith(".md") else name + ".md")
meta, paras, hook = vp.parse_script(sp, digits=True)
ti.say(cid, f"Senaryo: {meta.get('BAŞLIK', name)}\nAşağıdaki metni sırayla sesli mesaj olarak gönder, bitince /bitti yaz. (Açılış cümlesini ayrıca okuma, otomatik eklenir.)")
for n, p in enumerate(paras, 1):
    ti.say(cid, f"{n}/{len(paras)}\n{p}")
print("gönderildi:", name, len(paras))
