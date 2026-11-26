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


def _keyhole_line(size):
    """Sadece ince altın çizgili anahtar deliği (dolgusuz, zarif)."""
    S = size * 4
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy, r = S / 2, S * 0.38, S * 0.19
    top = cy + r * 0.6
    w = max(6, S // 60)
    d.arc([cx - r, cy - r, cx + r, cy + r], 128, 412, fill=GOLD + (255,), width=w)
    pts = [(cx - S * 0.075, top - 6), (cx - S * 0.16, S * 0.92), (cx + S * 0.16, S * 0.92), (cx + S * 0.075, top - 6)]
    d.line([pts[0], pts[1], pts[2], pts[3]], fill=GOLD + (255,), width=w, joint="curve")
    glow = im.filter(ImageFilter.GaussianBlur(S * 0.03))
    out = Image.alpha_composite(glow, im)
    return out.resize((size, size), Image.LANCZOS)


def render_ident_base(out_mp4, D, hit_t, font_path, W=1920, H=1080, fps=30, seed=7):
    """Elit sürüm: simsiyah sahne, ince altın çizgi, harfleri ortadan açılan Cinzel başlık, altın parıltı geçişi."""
    rnd = random.Random(seed)
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    dist = np.sqrt(((x - W * 0.5) / (W * 0.55)) ** 2 + ((y - H * 0.5) / (H * 0.6)) ** 2)
    glow_map = np.clip(1 - dist, 0, 1) ** 2.2
    text = "SON TANIK"
    size = 132
    font = ImageFont.truetype(font_path, size)
    try:
        font.set_variation_by_axes([600])
    except Exception:
        pass
    widths = [font.getlength(c) for c in text]
    ty = 600
    glyphs = []
    for c in text:
        lay = Image.new("RGBA", (int(size * 1.4), int(size * 1.7)), (0, 0, 0, 0))
        if c != " ":
            ImageDraw.Draw(lay).text((size * 0.1, size * 0.1), c, font=font, fill=WARM + (255,))
        glyphs.append(lay)
    t_final, t_start = 52.0, 6.0
    def positions(track):
        total = sum(widths) + track * (len(text) - 1)
        xs, x0 = [], (W - total) / 2
        for w_ in widths:
            xs.append(x0)
            x0 += w_ + track
        return xs
    final_xs = positions(t_final)
    mask = Image.new("L", (W, H), 0)
    for lay, gx in zip(glyphs, final_xs):
        mask.paste(lay.split()[3], (int(gx - size * 0.1), ty), lay.split()[3])
    mask_np = np.asarray(mask, dtype=np.float32) / 255.0
    key = _keyhole_line(150)
    motes = [dict(x=rnd.uniform(0, W), y=rnd.uniform(0, H), vy=rnd.uniform(-14, -4), vx=rnd.uniform(-5, 5),
                  r=rnd.uniform(1.0, 2.8), ph=rnd.uniform(0, 6.28), sp=rnd.uniform(0.5, 1.4), b=rnd.uniform(0.25, 0.7))
             for _ in range(45)]
    p = subprocess.Popen(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
         "-r", str(fps), "-i", "-", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "17", "-pix_fmt", "yuv420p", out_mp4],
        stdin=subprocess.PIPE)
    gold = np.array(GOLD, np.float32)
    n = int(round(D * fps))
    for i in range(n):
        t = i / fps
        f = np.zeros((H, W, 3), np.float32)
        f += glow_map[..., None] * np.array([7, 7, 9], np.float32)
        # vuruştan sonra başlığın arkasında sıcak bir ışık nefesi
        if t > hit_t:
            k = min(1.0, (t - hit_t) / 0.8) * (0.7 + 0.3 * math.sin((t - hit_t) * 1.6))
            gm = np.clip(1 - np.sqrt(((x - W * 0.5) / (W * 0.30)) ** 2 + ((y - 640) / 180.0) ** 2), 0, 1) ** 2
            f += gm[..., None] * np.array([70, 52, 28], np.float32) * k
        # ince altın çizgi: ortadan açılır, ses boyunca durur
        la = max(0.0, min(1.0, (t - 0.5) / 1.6))
        if t >= hit_t:
            la = max(0.0, 1 - (t - hit_t) / 0.35)
        if la > 0:
            e = 1 - (1 - la) ** 3 if t < hit_t else la
            half = int(520 * (1 - (1 - min(1.0, (t - 0.5) / 1.6)) ** 3)) if t < hit_t else 520
            f[538:541, W // 2 - half:W // 2 + half] = gold * (0.75 if t < hit_t else 0.75 * la)
        # toz
        dust = Image.new("RGB", (W // 2, H // 2), (0, 0, 0))
        dd = ImageDraw.Draw(dust)
        for m in motes:
            xx = (m["x"] + m["vx"] * t) % W
            yy = (m["y"] + m["vy"] * t) % H
            tw = 0.5 + 0.5 * math.sin(t * m["sp"] + m["ph"])
            lum = int(255 * m["b"] * (0.2 + 0.8 * tw))
            r = m["r"] / 2
            dd.ellipse([xx / 2 - r, yy / 2 - r, xx / 2 + r, yy / 2 + r], fill=(lum, int(lum * 0.9), int(lum * 0.7)))
        dust = dust.filter(ImageFilter.GaussianBlur(1.0)).resize((W, H), Image.BILINEAR)
        f += np.asarray(dust, dtype=np.float32) * 0.40
        # başlık: harfler ortadan dışa doğru belirir, aralık genişler
        if t >= hit_t:
            e_track = min(1.0, (t - hit_t) / 1.0)
            e_track = 1 - (1 - e_track) ** 3
            xs = positions(t_start + (t_final - t_start) * e_track)
            mid = (len(text) - 1) / 2
            tl = Image.new("L", (W, H), 0)
            for j, (lay, gx) in enumerate(zip(glyphs, xs)):
                ts = hit_t + 0.10 * abs(j - mid)
                a = max(0.0, min(1.0, (t - ts) / 0.55))
                if a <= 0 or text[j] == " ":
                    continue
                ea = 1 - (1 - a) ** 2
                al = lay.split()[3].point(lambda v, ea=ea: int(v * ea))
                tl.paste(al, (int(gx - size * 0.1), ty), al)
            tl_np = np.asarray(tl, dtype=np.float32) / 255.0
            glow = np.asarray(tl.filter(ImageFilter.GaussianBlur(26)), dtype=np.float32) / 255.0
            f += glow[..., None] * np.array([120, 92, 48], np.float32) * 0.55
            f = f * (1 - tl_np[..., None]) + np.array(WARM, np.float32) * tl_np[..., None]
            # altın folyo parıltısı: eğik bir ışık bandı başlığın üstünden geçer
            ts0 = hit_t + 1.05
            if t > ts0:
                pos = -300 + (t - ts0) / 1.1 * (W + 600)
                band = np.exp(-(((x + 0.45 * (y - ty)) - pos) / 90.0) ** 2)
                f += (band * tl_np)[..., None] * np.array([255, 214, 130], np.float32) * 0.9
            # anahtar deliği ve alt çizgi
            ka = max(0.0, min(1.0, (t - (hit_t + 0.25)) / 0.7))
            _paste_rgba(f, key, ((W - 150) // 2, 380), ka * 0.95)
            lb = max(0.0, min(1.0, (t - (hit_t + 0.6)) / 0.7))
            if lb > 0:
                eb = 1 - (1 - lb) ** 3
                half = int(260 * eb)
                f[828:830, W // 2 - half:W // 2 + half] = gold
                if eb > 0.95:
                    f[823:836, W // 2 - 6:W // 2 + 7] = np.array(RED, np.float32)
            if t < hit_t + 0.3:
                f += 26 * (1 - (t - hit_t) / 0.3)
        img = Image.fromarray(np.clip(f, 0, 255).astype(np.uint8))
        z = 1.0 + 0.04 * (t / D)
        cw, ch = int(W / z), int(H / z)
        x0, y0 = (W - cw) // 2, (H - ch) // 2
        img = img.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.BICUBIC)
        p.stdin.write(img.tobytes())
    p.stdin.close()
    p.wait()
    return out_mp4
