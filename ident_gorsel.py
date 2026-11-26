"""Açılış (ident) görseli: karanlık sahne, ışık huzmesi, toz zerrecikleri, anahtar deliği, harf harf beliren 'SON TANIK'.
Kareleri numpy/Pillow ile üretir, ffmpeg'e boruyla verir (ses ve dalga formu make_ident içinde eklenir)."""
import math
import os
import random
import subprocess

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

GOLD = (201, 162, 75)
RED = (192, 57, 43)
WARM = (240, 232, 218)


def _radial_bg(W, H):
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.sqrt(((x - W * 0.5) / (W * 0.62)) ** 2 + ((y - H * 0.46) / (H * 0.7)) ** 2)
    v = np.clip(1 - d, 0, 1) ** 1.6
    base = np.stack([6 + 14 * v, 8 + 15 * v, 11 + 17 * v], axis=-1)
    return base


def _beam(W, H):
    """Üstten sola eğik yumuşak ışık huzmesi (gri değerli maske)."""
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    d.polygon([(int(W * 0.30), -40), (int(W * 0.46), -40), (int(W * 0.74), H + 40), (int(W * 0.26), H + 40)], fill=255)
    return np.asarray(m.filter(ImageFilter.GaussianBlur(90)), dtype=np.float32) / 255.0


def _keyhole(size):
    """Anahtar deliği: altın çerçeveli koyu siluet + parıltı. RGBA katman."""
    S = size * 3
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = S / 2, S * 0.40
    r = S * 0.20
    top = cy + r * 0.55
    slot = [(cx - S * 0.07, top), (cx + S * 0.07, top), (cx + S * 0.15, S * 0.90), (cx - S * 0.15, S * 0.90)]
    for width, col in ((22, GOLD + (255,)),):
        d.ellipse([cx - r - width, cy - r - width, cx + r + width, cy + r + width], fill=col)
        d.polygon([(slot[0][0] - width * 0.6, slot[0][1]), (slot[1][0] + width * 0.6, slot[1][1]),
                   (slot[2][0] + width, slot[2][1]), (slot[3][0] - width, slot[3][1])], fill=col)
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(3, 4, 6, 255))
    d.polygon(slot, fill=(3, 4, 6, 255))
    # içeriden sızan sıcak ışık
    glow_in = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow_in)
    gd.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], fill=(255, 200, 110, 110))
    gd.polygon([(cx - S * 0.025, top), (cx + S * 0.025, top), (cx + S * 0.07, S * 0.86), (cx - S * 0.07, S * 0.86)], fill=(255, 190, 100, 70))
    glow_in = glow_in.filter(ImageFilter.GaussianBlur(18))
    im = Image.alpha_composite(im, glow_in)
    halo = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse([cx - r - 26, cy - r - 26, cx + r + 26, cy + r + 26], fill=GOLD + (150,))
    hd.polygon([(slot[0][0] - 14, slot[0][1]), (slot[1][0] + 14, slot[1][1]), (slot[2][0] + 26, slot[2][1]), (slot[3][0] - 26, slot[3][1])], fill=GOLD + (150,))
    halo = halo.filter(ImageFilter.GaussianBlur(40))
    out = Image.alpha_composite(halo, im)
    return out.resize((size, size), Image.LANCZOS)


def _title_letters(font_path, text, size, tracking, W, y_center):
    """Her harf için ayrı RGBA katman (tam kare boyutunda) + parıltı katmanı."""
    font = ImageFont.truetype(font_path, size)
    widths = [font.getlength(c) for c in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = (W - total) / 2
    layers = []
    for c, w in zip(text, widths):
        lay = Image.new("RGBA", (W, int(size * 2.2)), (0, 0, 0, 0))
        if c != " ":
            ImageDraw.Draw(lay).text((x, size * 0.45), c, font=font, fill=WARM + (255,))
        glow = lay.filter(ImageFilter.GaussianBlur(22))
        glow = Image.merge("RGBA", (glow.split()[0], glow.split()[1], glow.split()[2],
                                    glow.split()[3].point(lambda a: int(a * 0.8))))
        layers.append((lay, glow))
        x += w + tracking
    return layers, int(y_center - size * 1.1)


def _paste_rgba(canvas, layer, xy, alpha=1.0, add=False):
    """canvas: float32 HxWx3 dizisi; layer: RGBA PIL. Bölgeye alfa ile karıştırır (add=True ise toplayarak)."""
    x, y = xy
    lw, lh = layer.size
    H, W = canvas.shape[:2]
    x0, y0, x1, y1 = max(0, x), max(0, y), min(W, x + lw), min(H, y + lh)
    if x1 <= x0 or y1 <= y0 or alpha <= 0:
        return
    sub = np.asarray(layer.crop((x0 - x, y0 - y, x1 - x, y1 - y)), dtype=np.float32)
    a = sub[..., 3:4] / 255.0 * alpha
    if add:
        canvas[y0:y1, x0:x1] += sub[..., :3] * a
    else:
        canvas[y0:y1, x0:x1] = canvas[y0:y1, x0:x1] * (1 - a) + sub[..., :3] * a


def render_ident_base(out_mp4, D, hit_t, font_path, W=1920, H=1080, fps=30, seed=7):
    """hit_t: vuruşun/başlığın geldiği an (sn)."""
    rnd = random.Random(seed)
    bg = _radial_bg(W, H)
    beam = _beam(W, H)
    ksize = 330
    key = _keyhole(ksize)
    kpos = ((W - ksize) // 2, 150)
    letters, ly = _title_letters(font_path, "SON TANIK", 150, 34, W, 760)
    motes = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), vx=rnd.uniform(-9, 9), vy=rnd.uniform(-22, -5),
                  r=rnd.uniform(1.2, 4.2), ph=rnd.uniform(0, 6.28), sp=rnd.uniform(0.6, 1.8), b=rnd.uniform(0.25, 0.9))
             for _ in range(110)]
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out_mp4],
        stdin=subprocess.PIPE)
    n = int(round(D * fps))
    for i in range(n):
        t = i / fps
        f = bg.copy()
        # ışık huzmesi: yavaş salınım + hafif nefes
        sway = int(math.sin(t * 0.55) * 70)
        b = np.roll(beam, sway, axis=1)
        k = 0.075 + 0.025 * math.sin(t * 1.3)
        if t > hit_t:
            k += 0.10 * max(0.0, 1 - (t - hit_t) / 0.9)
        f += b[..., None] * np.array([255, 226, 170], np.float32) * k
        # anahtar deliği: sessizce belirir, vuruşta parlar
        if t < hit_t:
            ka = max(0.0, min(1.0, (t - 0.6) / 3.0)) * 0.55
        else:
            ka = 0.9 + 0.1 * max(0.0, 1 - (t - hit_t) / 0.5)
        _paste_rgba(f, key, kpos, ka)
        # toz zerrecikleri (yarım çözünürlükte çizilip büyütülür)
        dust = Image.new("RGB", (W // 2, H // 2), (0, 0, 0))
        dd = ImageDraw.Draw(dust)
        for m in motes:
            x = (m["x"] + m["vx"] * t) % W
            y = (m["y"] + m["vy"] * t) % H
            tw = 0.5 + 0.5 * math.sin(t * m["sp"] + m["ph"])
            lum = int(255 * m["b"] * (0.25 + 0.75 * tw))
            r = m["r"] / 2
            dd.ellipse([x / 2 - r, y / 2 - r, x / 2 + r, y / 2 + r], fill=(lum, int(lum * 0.9), int(lum * 0.72)))
        dust = dust.filter(ImageFilter.GaussianBlur(1.1)).resize((W, H), Image.BILINEAR)
        f += np.asarray(dust, dtype=np.float32) * 0.55
        # başlık: harf harf, yukarı süzülerek
        for j, (lay, glow) in enumerate(letters):
            ts = hit_t + 0.07 * j
            a = max(0.0, min(1.0, (t - ts) / 0.45))
            if a <= 0:
                continue
            e = 1 - (1 - a) ** 3
            dy = int((1 - e) * 26)
            _paste_rgba(f, glow, (0, ly + dy), e * 0.9, add=True)
            _paste_rgba(f, lay, (0, ly + dy), e)
        # altın çizgi: ortadan iki yana açılır, ortasında kırmızı nokta
        la = max(0.0, min(1.0, (t - (hit_t + 0.55)) / 0.7))
        if la > 0:
            e = 1 - (1 - la) ** 3
            half = int(230 * e)
            y0 = 872
            f[y0:y0 + 3, W // 2 - half:W // 2 + half] = np.array(GOLD, np.float32)
            if e > 0.9:
                f[y0 - 4:y0 + 7, W // 2 - 5:W // 2 + 6] = np.array(RED, np.float32)
        # vuruş parlaması
        if t >= hit_t:
            f += 38 * max(0.0, 1 - (t - hit_t) / 0.3)
        img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
        # yavaş yaklaşma
        z = 1.0 + 0.05 * (t / D)
        cw, ch = int(W / z), int(H / z)
        x0, y0 = (W - cw) // 2, (H - ch) // 2
        img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BICUBIC)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()
    return out_mp4
