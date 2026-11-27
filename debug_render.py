"""Saklı seslerle (özel önbellek) deneme üretimi; YÜKLEME YOK. Örnek kareleri 'kareler' dalına kaydeder."""
import os, shutil, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import video_pipeline as vp
SES = os.path.join(HERE, ".ses")
sid = open(os.path.join(SES, "sid.txt")).read().strip()
spath = os.path.join(HERE, "hazir", sid if sid.endswith(".md") else sid + ".md")
WORK = os.path.join(HERE, "_work")
shutil.rmtree(WORK, ignore_errors=True); os.makedirs(WORK)
files = []
for i, f in enumerate(sorted(x for x in os.listdir(SES) if x.startswith("in"))):
    shutil.copy(os.path.join(SES, f), os.path.join(WORK, f"in{i}")); files.append(os.path.join(WORK, f"in{i}"))
ident = os.path.join(HERE, "assets", "ident.wav")
info = vp.render_all(spath, files, ident if os.path.exists(ident) else None, os.path.join(WORK, "out"), os.path.join(WORK, "w"))
print("QA:", info.get("qa"))
os.makedirs("kareler_out", exist_ok=True)
d = vp.duration(info["video"])
n = 0
t = 5.0
while t < d - 2 and n < 40:
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", info["video"], "-vframes", "1", "-vf", "scale=960:-2",
                    f"kareler_out/ana_{int(t):04d}.jpg"])
    t += max(12, d / 36); n += 1
for k, s in enumerate(info["shorts"], 1):
    sd = vp.duration(s["file"])
    for j, t in enumerate((1, sd * 0.4, sd * 0.8)):
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", s["file"], "-vframes", "1", "-vf", "scale=360:-2",
                        f"kareler_out/short{k}_{j}.jpg"])
shutil.copy(info["thumbnail"], "kareler_out/kapak.jpg")
