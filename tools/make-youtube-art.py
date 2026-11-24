#!/usr/bin/env python3
"""Pictures of the YouTube app (resources/lib/youtube_app.py): eight invented scenes for the demo's thumbnails, the
plate a card shows when a video has none, the rounded-corner mask of a thumbnail, the focus ring, the pill, the
logo mark (and the same mark at 256 x 180 for the launch splash), the seven section icons and the strips (length pill and watched bar of a card, one picture per card).

Dev tool, needs python3-pil, python3-numpy; uses the helpers of make-launcher-art.py.
Usage: python3 tools/make-youtube-art.py <repo path>
Deterministic; only the files named here are written (make-launcher-art.py is not run again). Released under CC0 1.0.
The sizes here are the skin's (script-media-stick-youtube.xml): a thumbnail is CARD_W x CARD_H, 16:9.
"""
import importlib.util
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

if len(sys.argv) < 2:
    sys.exit(__doc__)
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("make_launcher_art", os.path.join(HERE, "make-launcher-art.py"))
art = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(art)          # its main() only runs as a script
sys.path.insert(0, art.BASE)
from resources.lib import youtube_cards as cards   # noqa: E402  (needs no Kodi)

DEMO = os.path.join(art.BASE, "resources", "media", "demo")
CARD_W, CARD_H, RADIUS = 352, 198, 12  # the thumbnail on screen, and the radius of its corners
STRIP_H = 52                           # the strip picture's height: the pill's 34 and the bar's 6, at the picture's foot
PILL_H, PILL_INSET, PILL_RADIUS, BAR_H = 34, 10, 8, 6
THUMB_W, THUMB_H = 384, 216            # a demo thumbnail (scaled to the card by Kodi)
SS = 2                                 # scenes are drawn at twice the size and scaled down
COLOURS = 128                          # a palette picture is a fraction of the size of a full-colour one
RED, DARK, TRACK = (255, 0, 0), (0, 0, 0), (255, 255, 255)
LIVE_RED = (204, 0, 0)
BG = (15, 15, 15)


# ---- the scenes: one per channel of the demo -------------------------------------------------

class Scene:
    """A picture drawn at SS times the size: a gradient to start with, shapes and glows on top."""

    def __init__(self, stops):
        self.w, self.h = THUMB_W * SS, THUMB_H * SS
        column = art.ramp(np.linspace(0, 1, self.h, dtype=np.float32), stops)
        self.img = Image.fromarray(np.broadcast_to(column[:, None, :], (self.h, self.w, 3)).astype(np.uint8)).convert("RGBA")
        self.rng = np.random.default_rng(len(stops) * 7 + int(stops[0][1][0]))

    def xy(self, x, y):
        return x * self.w, y * self.h

    def paint(self, draw_on, blur=0.0):
        """draw_on(ImageDraw, scene) draws on a transparent layer that is blurred and put over the picture."""
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        draw_on(ImageDraw.Draw(layer), self)
        self.img.alpha_composite(layer.filter(ImageFilter.GaussianBlur(blur * SS)) if blur else layer)

    def glow(self, x, y, radius, colour, strength=1.0):
        yy, xx = np.mgrid[0:self.h, 0:self.w].astype(np.float32)
        a = np.clip(1 - np.hypot(xx - x * self.w, yy - y * self.h) / (radius * self.h), 0, 1) ** 2 * strength
        arr = np.zeros((self.h, self.w, 4), np.uint8)
        arr[..., :3], arr[..., 3] = colour, a * 255
        self.img.alpha_composite(Image.fromarray(arr))

    def save(self, n):
        pic = self.img.convert("RGB").resize((THUMB_W, THUMB_H), Image.LANCZOS)
        pic = pic.quantize(COLOURS, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
        pic.save(art.track(os.path.join(DEMO, f"yt-thumb-{n}.png")), optimize=True)


def workshop(s):
    """Planks, a circular saw blade, a curl of shavings."""
    def planks(d, s):
        for i in range(4):
            y0, tone = i * 0.25, int(s.rng.integers(-14, 14))
            d.rectangle([0, y0 * s.h, s.w, (y0 + 0.25) * s.h], fill=(150 + tone, 102 + tone, 62 + tone, 255))
            for _ in range(26):
                gy = (y0 + s.rng.random() * 0.25) * s.h
                x0 = s.rng.random() * s.w
                d.line([x0, gy, x0 + s.rng.random() * s.w * 0.6, gy + 2], fill=(96, 62, 34, 70), width=2 * SS)
            d.line([0, y0 * s.h, s.w, y0 * s.h], fill=(40, 24, 14, 255), width=3 * SS)

    def blade(d, s):
        cx, cy = s.xy(0.66, 0.5)
        r = 0.36 * s.h
        teeth = [(cx + (r * (1.12 if k % 2 else 1.0)) * np.cos(np.pi * k / 22), cy + (r * (1.12 if k % 2 else 1.0)) * np.sin(np.pi * k / 22))
                 for k in range(44)]
        d.polygon(teeth, fill=(176, 184, 194, 255))
        d.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55], outline=(120, 128, 140, 255), width=3 * SS)
        d.ellipse([cx - r * 0.14, cy - r * 0.14, cx + r * 0.14, cy + r * 0.14], fill=(52, 56, 64, 255))
        for k in range(4):
            a = k * np.pi / 2 + 0.3
            d.ellipse([cx + 0.7 * r * np.cos(a) - 9 * SS, cy + 0.7 * r * np.sin(a) - 9 * SS,
                       cx + 0.7 * r * np.cos(a) + 9 * SS, cy + 0.7 * r * np.sin(a) + 9 * SS], fill=(70, 76, 86, 255))

    def shadow(d, s):
        cx, cy = s.xy(0.68, 0.56)
        d.ellipse([cx - 0.4 * s.h, cy - 0.4 * s.h, cx + 0.4 * s.h, cy + 0.4 * s.h], fill=(0, 0, 0, 150))

    def curls(d, s):
        for k in range(5):
            x, y = s.xy(0.08 + 0.05 * k, 0.78 - 0.03 * (k % 2))
            d.arc([x, y, x + 60 * SS, y + 40 * SS], 20, 330, fill=(236, 206, 150, 255), width=3 * SS)

    s.paint(planks)
    s.paint(shadow, blur=10)
    s.paint(blade)
    s.paint(curls)
    s.glow(0.2, 0.1, 0.8, (255, 214, 150), 0.45)


def kitchen(s):
    """A plate of pasta with tomatoes and basil, steam above."""
    def table(d, s):
        d.rectangle([0, 0.58 * s.h, s.w, s.h], fill=(176, 118, 74, 255))
        for k in range(1, 6):
            d.line([0, (0.58 + 0.08 * k) * s.h, s.w, (0.58 + 0.08 * k) * s.h], fill=(120, 76, 46, 255), width=2 * SS)

    def plate(d, s):
        cx, cy = s.xy(0.5, 0.64)
        for r, c in ((0.40, (0, 0, 0, 90)), (0.37, (244, 242, 236, 255)), (0.30, (226, 222, 212, 255))):
            d.ellipse([cx - r * s.h * 1.5, cy - r * s.h * 0.62, cx + r * s.h * 1.5, cy + r * s.h * 0.62], fill=c)
        for k in range(26):
            w, h = (0.30 - 0.008 * k) * s.h * 1.2, (0.30 - 0.008 * k) * s.h * 0.5
            d.arc([cx - w, cy - h - 4 * k, cx + w, cy + h - 4 * k], 10 * k, 200 + 10 * k, fill=(238, 196, 92, 255), width=3 * SS)
        for k in range(7):
            x, y = cx + (k - 3) * 0.075 * s.h * 1.4, cy - 0.08 * s.h + 0.05 * s.h * (k % 3)
            d.ellipse([x - 22 * SS, y - 22 * SS, x + 22 * SS, y + 22 * SS], fill=(204, 48, 38, 255))
            d.ellipse([x - 12 * SS, y - 16 * SS, x - 4 * SS, y - 9 * SS], fill=(240, 130, 110, 255))
        for k in range(4):
            x, y = cx + (k - 1.5) * 0.12 * s.h, cy - 0.18 * s.h
            d.polygon([(x, y), (x + 26 * SS, y - 14 * SS), (x + 44 * SS, y + 6 * SS), (x + 18 * SS, y + 18 * SS)], fill=(54, 140, 70, 255))

    def steam(d, s):
        for k in range(5):
            x, y = s.xy(0.34 + 0.08 * k, 0.34 - 0.04 * (k % 2))
            d.ellipse([x - 24 * SS, y - 60 * SS, x + 24 * SS, y + 60 * SS], fill=(255, 255, 255, 70))

    s.paint(table)
    s.paint(plate)
    s.paint(steam, blur=14)
    s.glow(0.5, 0.0, 0.9, (255, 170, 100), 0.5)


def lake(s):
    """A calm lake at sunset: sun, its reflection, dark shore with pines."""
    s.glow(0.5, 0.5, 0.7, (255, 214, 160), 0.8)

    def water(d, s):
        d.rectangle([0, 0.55 * s.h, s.w, s.h], fill=(96, 118, 150, 255))
        for k in range(46):
            y = (0.56 + 0.44 * k / 46) * s.h
            half = (0.07 + 0.2 * (k / 46) ** 0.8) * s.w * (0.5 + 0.5 * s.rng.random())
            d.line([s.w * 0.5 - half, y, s.w * 0.5 + half, y], fill=(255, 214, 150, int(220 - 3.8 * k)), width=2 * SS)

    def shore(d, s):
        pts = [(0, 0.56 * s.h)]
        for k in range(1, 40):
            pts.append((k / 39 * s.w, (0.55 - 0.05 * np.sin(k * 0.7) ** 2 - 0.02 * (k % 3 == 0)) * s.h))
        d.polygon(pts + [(s.w, 0.57 * s.h), (s.w, 0.6 * s.h), (0, 0.6 * s.h)], fill=(34, 52, 66, 255))
        for k in range(16):
            x = (0.03 + 0.065 * k + 0.02 * (k % 3)) * s.w
            h = (0.10 + 0.07 * ((k * 5) % 4) / 3) * s.h
            d.polygon([(x - 0.02 * s.w, 0.57 * s.h), (x, 0.57 * s.h - h), (x + 0.02 * s.w, 0.57 * s.h)], fill=(26, 42, 54, 255))

    def sun(d, s):
        x, y = s.xy(0.5, 0.5)
        d.ellipse([x - 0.06 * s.h, y - 0.06 * s.h, x + 0.06 * s.h, y + 0.06 * s.h], fill=(255, 246, 214, 255))

    s.paint(sun)
    s.paint(water)
    s.paint(shore)


def space(s):
    """Stars, a nebula, a ringed planet and a moon."""
    s.glow(0.25, 0.3, 0.7, (150, 50, 160), 0.45)
    s.glow(0.8, 0.8, 0.8, (40, 90, 190), 0.4)

    def stars(d, s):
        for _ in range(240):
            x, y, r = s.rng.random() * s.w, s.rng.random() * s.h, (0.6 + 1.6 * s.rng.random() ** 3) * SS
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 255, 255, int(120 + 135 * s.rng.random())))

    def ring(d, s, back):
        cx, cy = s.xy(0.66, 0.54)
        d.arc([cx - 0.62 * s.h, cy - 0.16 * s.h, cx + 0.62 * s.h, cy + 0.16 * s.h], 180 if back else 0, 360 if back else 180,
              fill=(232, 208, 176, 255), width=7 * SS)

    def planet(d, s):
        cx, cy, r = *s.xy(0.66, 0.54), 0.27 * s.h
        yy, xx = np.mgrid[0:s.h, 0:s.w].astype(np.float32)
        dx, dy = (xx - cx) / r, (yy - cy) / r
        inside = dx ** 2 + dy ** 2
        z = np.sqrt(np.clip(1 - inside, 0, 1))
        light = np.clip(-0.5 * dx - 0.55 * dy + 0.65 * z, 0, 1) ** 0.9
        bands = 0.5 + 0.5 * np.sin(dy * 9 + 2 * np.sin(dx * 2))
        base = np.array([70, 40, 52], np.float32) * (1 - light[..., None]) + np.array([236, 164, 104], np.float32) * light[..., None]
        base = base * (0.88 + 0.12 * bands[..., None])
        edge = np.clip((1 - np.sqrt(inside)) * r / 1.5, 0, 1)
        arr = np.dstack([base, edge * 255]).astype(np.uint8)
        s.img.alpha_composite(Image.fromarray(arr))

    def moon(d, s):
        x, y = s.xy(0.17, 0.3)
        d.ellipse([x - 0.06 * s.h, y - 0.06 * s.h, x + 0.06 * s.h, y + 0.06 * s.h], fill=(214, 216, 228, 255))
        d.ellipse([x - 0.02 * s.h, y - 0.04 * s.h, x + 0.015 * s.h, y - 0.005 * s.h], fill=(170, 172, 190, 255))

    s.paint(stars)
    s.paint(lambda d, sc: ring(d, sc, True))
    planet(None, s)
    s.paint(lambda d, sc: ring(d, sc, False))
    s.paint(moon)


def trail(s):
    """Mountains, a road to the horizon with its dashes, pines."""
    s.glow(0.8, 0.22, 0.6, (255, 244, 214), 0.9)

    def mountains(d, s):
        for base, top, colour in ((0.56, 0.22, (126, 150, 190, 255)), (0.58, 0.34, (70, 104, 124, 255))):
            pts = [(0, base * s.h)]
            for k in range(1, 30):
                x = k / 29
                pts.append((x * s.w, (top + (base - top) * (0.5 + 0.5 * np.cos(x * 9 + top * 20)) ** 1.5) * s.h))
            d.polygon(pts + [(s.w, base * s.h)], fill=colour)
        d.rectangle([0, 0.56 * s.h, s.w, s.h], fill=(84, 132, 78, 255))

    def road(d, s):
        d.polygon([(0.485 * s.w, 0.56 * s.h), (0.515 * s.w, 0.56 * s.h), (0.86 * s.w, s.h), (0.14 * s.w, s.h)], fill=(96, 98, 106, 255))
        for k in range(7):
            t0, t1 = (k / 7) ** 1.8, ((k + 0.5) / 7) ** 1.8
            y0, y1 = (0.56 + 0.44 * t0) * s.h, (0.56 + 0.44 * t1) * s.h
            w0, w1 = 0.002 + 0.014 * t0, 0.002 + 0.014 * t1
            d.polygon([((0.5 - w0) * s.w, y0), ((0.5 + w0) * s.w, y0), ((0.5 + w1) * s.w, y1), ((0.5 - w1) * s.w, y1)], fill=(236, 232, 214, 255))
        for side in (-1, 1):
            for k in range(6):
                t = (k / 6) ** 1.6
                x, y, h = (0.5 + side * (0.05 + 0.5 * t)) * s.w, (0.56 + 0.4 * t) * s.h, (0.04 + 0.34 * t) * s.h
                d.polygon([(x - h * 0.22, y), (x, y - h), (x + h * 0.22, y)], fill=(28, 70, 48, 255))

    s.paint(mountains)
    s.paint(road)


def stage(s):
    """Spotlights, haze, silhouettes of three players."""
    def cones(d, s):
        for x0, x1, tone in ((0.18, 0.12, (255, 70, 160)), (0.5, 0.5, (255, 200, 90)), (0.82, 0.9, (70, 210, 255))):
            d.polygon([((x0 - 0.02) * s.w, 0), ((x0 + 0.02) * s.w, 0), ((x1 + 0.17) * s.w, 0.86 * s.h), ((x1 - 0.17) * s.w, 0.86 * s.h)],
                      fill=(*tone, 120))

    def floor(d, s):
        d.ellipse([0.05 * s.w, 0.8 * s.h, 0.95 * s.w, 1.0 * s.h], fill=(255, 190, 130, 110))

    def players(d, s):
        for x, h in ((0.28, 0.46), (0.5, 0.5), (0.72, 0.44)):
            cx, base = x * s.w, 0.93 * s.h
            d.ellipse([cx - 0.035 * s.h, base - h * s.h, cx + 0.035 * s.h, base - h * s.h + 0.07 * s.h], fill=(8, 6, 12, 255))
            d.polygon([(cx - 0.07 * s.h, base - h * s.h + 0.09 * s.h), (cx + 0.07 * s.h, base - h * s.h + 0.09 * s.h),
                       (cx + 0.1 * s.h, base), (cx - 0.1 * s.h, base)], fill=(8, 6, 12, 255))
        d.rectangle([0, 0.93 * s.h, s.w, s.h], fill=(8, 6, 12, 255))

    s.paint(cones, blur=14)
    s.paint(floor, blur=16)
    s.paint(players)


def garden(s):
    """Leaves, tomatoes, a sunflower, soft light."""
    def bokeh(d, s):
        for _ in range(16):
            x, y, r = s.rng.random() * s.w, s.rng.random() * 0.6 * s.h, (14 + 30 * s.rng.random()) * SS
            d.ellipse([x - r, y - r, x + r, y + r], fill=(255, 238, 150, 60))

    def leaves(d, s):
        for k in range(9):
            cx, cy = s.xy(0.06 + 0.12 * k, 0.78 - 0.1 * (k % 3))
            ang = (-0.9 + 0.22 * k) % np.pi
            length, width = (0.34 + 0.06 * (k % 3)) * s.h, 0.11 * s.h
            pts = [(cx + length * t * np.cos(ang) - width * np.sin(np.pi * t) * np.sin(ang) * sign,
                    cy - length * t * np.sin(ang) - width * np.sin(np.pi * t) * np.cos(ang) * sign)
                   for sign in (1, -1) for t in (np.linspace(0, 1, 12) if sign == 1 else np.linspace(1, 0, 12))]
            d.polygon(pts, fill=(34 + 8 * (k % 3), 110 + 14 * (k % 3), 54, 255))
            d.line([cx, cy, cx + length * np.cos(ang), cy - length * np.sin(ang)], fill=(120, 190, 110, 255), width=2 * SS)

    def fruit(d, s):
        for x, y, r in ((0.3, 0.7, 0.09), (0.4, 0.78, 0.075), (0.2, 0.8, 0.07)):
            cx, cy, rr = x * s.w, y * s.h, r * s.h
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], fill=(210, 46, 36, 255))
            d.ellipse([cx - rr * 0.6, cy - rr * 0.7, cx - rr * 0.2, cy - rr * 0.4], fill=(248, 150, 130, 255))
            d.polygon([(cx, cy - rr * 0.9), (cx + rr * 0.4, cy - rr * 1.1), (cx + rr * 0.15, cy - rr * 0.7)], fill=(40, 120, 50, 255))
        fx, fy = s.xy(0.76, 0.42)
        for k in range(16):
            a = k * np.pi / 8
            d.ellipse([fx + 0.12 * s.h * np.cos(a) - 0.05 * s.h, fy + 0.12 * s.h * np.sin(a) - 0.05 * s.h,
                       fx + 0.12 * s.h * np.cos(a) + 0.05 * s.h, fy + 0.12 * s.h * np.sin(a) + 0.05 * s.h], fill=(250, 196, 30, 255))
        d.ellipse([fx - 0.1 * s.h, fy - 0.1 * s.h, fx + 0.1 * s.h, fy + 0.1 * s.h], fill=(96, 56, 24, 255))

    s.paint(bokeh, blur=6)
    s.paint(leaves)
    s.paint(fruit)


def city(s):
    """A skyline at dusk with lit windows and a moon."""
    s.glow(0.5, 1.0, 0.9, (255, 150, 120), 0.8)

    def moon(d, s):
        x, y = s.xy(0.8, 0.22)
        d.ellipse([x - 0.08 * s.h, y - 0.08 * s.h, x + 0.08 * s.h, y + 0.08 * s.h], fill=(255, 244, 226, 255))

    def skyline(d, s):
        x = -0.01
        while x < 1.0:
            w, h = 0.05 + 0.06 * s.rng.random(), 0.2 + 0.4 * s.rng.random() ** 1.5
            d.rectangle([x * s.w, (1 - h) * s.h, (x + w) * s.w, s.h], fill=(22, 14, 40, 255))
            for wy in np.arange(1 - h + 0.04, 0.97, 0.06):
                for wx in np.arange(x + 0.008, x + w - 0.012, 0.016):
                    if s.rng.random() < 0.45:
                        d.rectangle([wx * s.w, wy * s.h, (wx + 0.008) * s.w, (wy + 0.03) * s.h], fill=(255, 214, 120, 255))
            x += w + 0.004

    s.paint(moon)
    s.paint(skyline)


SCENES = [(workshop, [(0, (120, 78, 44)), (1, (70, 44, 26))]), (kitchen, [(0, (92, 40, 28)), (1, (44, 20, 18))]),
          (lake, [(0, (70, 80, 140)), (0.5, (250, 178, 140)), (0.56, (255, 220, 180)), (1, (60, 80, 110))]),
          (space, [(0, (6, 8, 26)), (1, (22, 22, 62))]), (trail, [(0, (60, 120, 200)), (0.6, (190, 226, 246)), (1, (190, 226, 246))]),
          (stage, [(0, (14, 8, 26)), (1, (34, 14, 40))]), (garden, [(0, (52, 108, 62)), (1, (16, 50, 30))]),
          (city, [(0, (34, 20, 84)), (0.55, (170, 70, 130)), (1, (252, 150, 116))])]


# ---- the pieces of the screen ----------------------------------------------------------------

def rgba(alpha, colour):
    arr = np.zeros(alpha.shape + (4,), np.uint8)
    arr[..., :3], arr[..., 3] = colour, np.clip(np.rint(alpha * 255), 0, 255)
    return Image.fromarray(arr)


def save(img, name, colours=0):
    path = art.track(os.path.join(art.MEDIA, name))
    if colours:
        img = img.quantize(colours, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE)
    img.save(path, optimize=True)


def make_nothumb():
    """What a card shows for a video without a picture: a plate lighter than the page, with a play mark in a ring
    (it must read as "no picture", not as an empty tile). Rounded by the skin's mask, like a thumbnail."""
    w, h, ss = CARD_W, CARD_H, 4
    im = Image.new("RGB", (w * ss, h * ss), (42, 42, 46))
    d = ImageDraw.Draw(im)
    cx, cy, r = w * ss / 2, h * ss / 2, 26 * ss
    d.ellipse([cx - 1.9 * r, cy - 1.9 * r, cx + 1.9 * r, cy + 1.9 * r], outline=(86, 86, 94), width=3 * ss)
    d.polygon([(cx - r * 0.55, cy - r * 0.85), (cx - r * 0.55, cy + r * 0.85), (cx + r * 0.95, cy)], fill=(120, 120, 130))
    im.resize((w, h), Image.LANCZOS).quantize(16, dither=Image.Dither.NONE).save(art.track(os.path.join(art.MEDIA, "youtube-nothumb.png")), optimize=True)


def make_shapes():
    save(rgba(art.rr_mask((CARD_W, CARD_H), (0, 0, CARD_W, CARD_H), RADIUS), (255, 255, 255)), "youtube-mask.png")
    save(rgba(art.rr_mask((64, 64), (0, 0, 64, 64), 32), (255, 255, 255)), "youtube-pill.png")
    ring = art.rr_mask((64, 64), (0, 0, 64, 64), 18) * (1 - art.rr_mask((64, 64), (4, 4, 60, 60), 14))
    save(rgba(ring, (255, 255, 255)), "youtube-ring.png")
    mark = Image.new("RGBA", (64 * 8, 45 * 8), (0, 0, 0, 0))
    d = ImageDraw.Draw(mark)
    d.rounded_rectangle([0, 0, 64 * 8 - 1, 45 * 8 - 1], 13 * 8, fill=(255, 0, 0, 255))
    d.polygon([(26 * 8, 13 * 8), (26 * 8, 32 * 8), (43 * 8, 22.5 * 8)], fill=(255, 255, 255, 255))
    save(mark.resize((64, 45), Image.LANCZOS), "youtube-mark.png")
    make_splash_mark()


def make_splash_mark():
    """The mark of the launch splash, drawn again at 4 times the top bar's size (256 x 180, shown at that size, one picture
    pixel to one screen pixel on a 1080p screen), not the small one stretched."""
    ss, unit = 4, 4
    scale = ss * unit
    mark = Image.new("RGBA", (64 * scale, 45 * scale), (0, 0, 0, 0))
    d = ImageDraw.Draw(mark)
    d.rounded_rectangle([0, 0, 64 * scale - 1, 45 * scale - 1], 13 * scale, fill=(255, 0, 0, 255))
    d.polygon([(26 * scale, 13 * scale), (26 * scale, 32 * scale), (43 * scale, 22.5 * scale)], fill=(255, 255, 255, 255))
    save(mark.resize((64 * unit, 45 * unit), Image.LANCZOS), "youtube-splash.png")


def make_strip(style, width, bar):
    """The foot of a thumbnail: the length pill at the right and the watched bar along the bottom; the bar follows
    the thumbnail's rounded corners."""
    img = Image.new("RGBA", (CARD_W, STRIP_H), (0, 0, 0, 0))
    if style != cards.NONE:
        pill = art.rr_mask((CARD_W, STRIP_H), (CARD_W - PILL_INSET - width, 8, CARD_W - PILL_INSET, 8 + PILL_H), PILL_RADIUS)
        img.alpha_composite(rgba(pill * (0.8 if style == cards.DARK else 1.0), DARK if style == cards.DARK else LIVE_RED))
    if bar:
        corners = art.rr_mask((CARD_W, CARD_H), (0, 0, CARD_W, CARD_H), RADIUS)[CARD_H - STRIP_H:, :]
        rows = np.zeros((STRIP_H, CARD_W), np.float32)
        rows[STRIP_H - BAR_H:, :] = 1.0
        done = np.zeros_like(rows)
        done[:, :int(round(CARD_W * bar / 100))] = 1.0
        img.alpha_composite(rgba(rows * corners * 0.35, TRACK))
        img.alpha_composite(rgba(rows * done * corners, RED))
    save(img, f"youtube-strip-{cards.strip_key(style, width, bar)}.png", 16)


# Each icon: a function drawing white on a 40 x 40 grid (x 10 supersampled); `cut` shapes are taken out again.
def icon_home(d, cut):
    d.polygon([(3, 19), (20, 3), (37, 19), (33, 19), (33, 36), (7, 36), (7, 19)], fill=255)
    cut.rectangle([16, 25, 24, 36], fill=255)


def icon_subs(d, cut):
    d.rounded_rectangle([11, 5, 29, 8], 1.5, fill=255)
    d.rounded_rectangle([7, 11, 33, 14.5], 1.5, fill=255)
    d.rounded_rectangle([4, 18, 36, 36], 4, fill=255)
    cut.polygon([(16, 22), (16, 32), (26, 27)], fill=255)


def icon_clock(d, cut):
    d.ellipse([4, 4, 36, 36], fill=255)
    cut.ellipse([7.5, 7.5, 32.5, 32.5], fill=255)
    d.line([20, 11, 20, 21, 27, 25], fill=255, width=3, joint="curve")


def icon_history(d, cut):
    d.arc([5, 5, 35, 35], 110, 400, fill=255, width=3)
    d.polygon([(2, 15), (12, 8), (13, 20)], fill=255)
    d.line([20, 12, 20, 21, 26, 25], fill=255, width=3, joint="curve")


def icon_lists(d, cut):
    for y, x1 in ((8, 26), (17, 26), (26, 17)):
        d.rounded_rectangle([4, y, x1, y + 3], 1.5, fill=255)
    d.polygon([(25, 21), (25, 35), (37, 28)], fill=255)


def icon_trend(d, cut):
    d.polygon([(21, 2), (26, 10), (33, 17), (35, 25), (31, 33), (24, 38), (16, 38), (9, 33), (5, 25), (8, 17), (13, 21), (15, 12)], fill=255)
    cut.polygon([(20, 22), (25, 28), (25, 33), (20, 36), (15, 33), (15, 28)], fill=255)


def icon_search(d, cut):
    d.ellipse([4, 4, 28, 28], fill=255)
    cut.ellipse([8, 8, 24, 24], fill=255)
    d.line([25, 25, 35, 35], fill=255, width=4)
    d.ellipse([33, 33, 37, 37], fill=255)


ICONS = {"rec": icon_home, "subs": icon_subs, "later": icon_clock, "history": icon_history, "lists": icon_lists,
         "trend": icon_trend, "search": icon_search}


def make_icon(key, draw_icon, ss=10):
    alpha, cut = Image.new("L", (40 * ss, 40 * ss), 0), Image.new("L", (40 * ss, 40 * ss), 0)

    class Scaled:                      # the shapes are given on the 40 grid; this scales them up
        def __init__(self, d):
            self.d = d

        def __getattr__(self, name):
            def call(xy, *a, **k):
                flat = np.array(xy, np.float32).reshape(-1) * ss
                if "width" in k:
                    k["width"] = int(k["width"] * ss)
                if name == "rounded_rectangle" and a:
                    a = (a[0] * ss,) + a[1:]
                return getattr(self.d, name)(list(flat), *a, **k)
            return call
    draw_icon(Scaled(ImageDraw.Draw(alpha)), Scaled(ImageDraw.Draw(cut)))
    a = np.asarray(alpha, np.float32) * (1 - np.asarray(cut, np.float32) / 255.0)
    pic = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).resize((40, 40), Image.LANCZOS)
    save(rgba(np.asarray(pic, np.float32) / 255.0, (255, 255, 255)), f"youtube-icon-{key}.png")


def main():
    for d in (art.MEDIA, DEMO):
        os.makedirs(d, exist_ok=True)
    for n, (scene, stops) in enumerate(SCENES, 1):
        s = Scene(stops)
        scene(s)
        s.save(n)
    make_nothumb()
    make_shapes()
    for key, draw_icon in ICONS.items():
        make_icon(key, draw_icon)
    for variant in cards.strip_variants():
        make_strip(*variant)
    for p in art.WRITTEN:
        print('%9d  %s' % (os.path.getsize(p), os.path.relpath(p, art.BASE)))


if __name__ == '__main__':
    main()
