"""Gerçek ortamda deneme: Samsun senaryosunun ilk bölümünü espeak ile seslendirir, tüm hattı çalıştırır."""
import os, subprocess, sys
import video_pipeline as vp
meta, paras, hook_n = vp.parse_script("hazir/02-kumarbaz-futbol-kulubu.md")
keep = paras[:hook_n + 5]
body = "\n\n".join(keep[:hook_n]) + "\n\n[SON TANIK AÇILIŞ SESİ]\n\n" + "\n\n".join(keep[hook_n:])
open("_selftest.md", "w", encoding="utf-8").write(
    f"# Senaryo: {meta['BAŞLIK']}\nKAPAK: İKİ ADAM, TEK KURAL\nGÖRSELLER: {meta.get('GÖRSELLER','')}\n\n## OKUMA METNİ\n\n{body}\n")
open("_selftest.txt", "w", encoding="utf-8").write(" ".join(keep))
subprocess.run(["espeak-ng", "-v", "tr", "-s", "150", "-f", "_selftest.txt", "-w", "_selftest.wav"], check=True)
info = vp.render_all("_selftest.md", ["_selftest.wav"], None, "_out", "_work", shorts_count=1)
print("SONUC", info["minutes"], "dk", [s["file"] for s in info["shorts"]], "ai_kullanilan", vp.AI_STATE)
