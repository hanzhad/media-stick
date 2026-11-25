#!/usr/bin/env python3
"""Pictures of the SWEET.TV app (resources/lib/sweettv_app.py): the favourite star, the small round chip, the 21
progress bars of the channel cards and the 21 long ones of the preview, and the placeholder logos of the demo.

Dev tool, needs python3-pil, python3-numpy, fonts-roboto; uses the helpers of make-launcher-art.py.
Usage: python3 tools/make-sweettv-art.py <repo path>
Deterministic; only the files named here are written (make-launcher-art.py is not run again). Released under CC0 1.0.
"""
import importlib.util
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if len(sys.argv) < 2:
    sys.exit(__doc__)
HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("make_launcher_art", os.path.join(HERE, "make-launcher-art.py"))
art = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(art)          # its main() only runs as a script

DEMO = os.path.join(art.BASE, "resources", "media", "demo")
BARS = (("bar", 220), ("pbar", 640))   # script-media-stick-sweettv.xml draws them 220 x 6 (a card) and 640 x 6 (the preview)
BAR_H, STEPS = 6, 20
CHIP = 48                              # the round chip: a 9-slice with border 24 (badges and buttons are at least 48 high)
LOGO_W, LOGO_H, SS = 512, 256, 4       # shown 640 wide in the preview, so not smaller


def make_star():
    ic = art.Icon()
    pts = []
    for k in range(10):
        r = 44 if k % 2 == 0 else 19
        a = np.radians(-90 + 36 * k)
        pts.append((48 + r * np.cos(a), 50 + r * np.sin(a)))
    ic.d.polygon([(x * ic.S, y * ic.S) for x, y in pts], fill=255)
    ic.line(pts + [pts[0]], 5)         # rounds the corners
    art.save_rgba(os.path.join(art.MEDIA, 'icon-star.png'), ic.result())


def make_chip():
    art.save_rgba(os.path.join(art.MEDIA, 'sweettv-chip.png'), art.rr_mask((CHIP, CHIP), (0, 0, CHIP, CHIP), CHIP / 2))


def make_bars():
    """A track at 28% and the part gone through at full: tinted by the skin."""
    for name, bar_w in BARS:
        track = art.rr_mask((bar_w, BAR_H), (0, 0, bar_w, BAR_H), BAR_H / 2) * 0.28
        for step in range(STEPS + 1):
            width = round(bar_w * step / STEPS)
            done = art.rr_mask((bar_w, BAR_H), (0, 0, width, BAR_H), min(BAR_H / 2, width / 2)) if width else 0 * track
            art.save_rgba(os.path.join(art.MEDIA, f'sweettv-{name}-{step:02d}.png'), np.maximum(track, done))


def font(name, size):
    return ImageFont.truetype(os.path.join(art.FONTS, name), size)


def fitted(text, name, width, height):
    size = height
    while size > 8 and (font(name, size).getlength(text) > width or font(name, size).getbbox(text)[3] > height * 1.2):
        size -= 2
    return font(name, size)


# (text, font, plate colour or None, text colour, plate shape): invented marks, not anyone's logo
LOGOS = [("N24", 'Roboto-Black.ttf', (28, 88, 196), (255, 255, 255), 'round'),
         ("ARENA", 'Roboto-Bold.ttf', None, (255, 200, 64), 'bar'),
         ("kids", 'Roboto-Black.ttf', (255, 138, 40), (255, 255, 255), 'pill'),
         ("MIX", 'Roboto-Black.ttf', (136, 64, 200), (255, 255, 255), 'circle'),
         ("SPORT 1", 'Roboto-Bold.ttf', (20, 152, 108), (255, 255, 255), 'round'),
         ("cinema", 'Roboto-Light.ttf', None, (232, 232, 238), 'bar'),
         ("LIVE", 'Roboto-Black.ttf', (206, 48, 60), (255, 255, 255), 'pill'),
         ("TV+", 'Roboto-Black.ttf', None, (255, 255, 255), 'ring'),
         ("DOC", 'Roboto-Black.ttf', (38, 120, 150), (255, 255, 255), 'round'),
         ("Музика", 'Roboto-Bold.ttf', None, (255, 130, 170), 'bar'),
         ("PLANET", 'Roboto-Bold.ttf', (30, 30, 52), (120, 220, 255), 'pill'),
         ("HD", 'Roboto-Black.ttf', (240, 190, 40), (30, 30, 30), 'circle')]


def make_logo(n, spec):
    text, face, plate, ink, shape = spec
    w, h = LOGO_W * SS, LOGO_H * SS
    im = Image.new('RGBA', (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = 20 * SS
    if shape in ('round', 'pill'):
        d.rounded_rectangle((pad, pad, w - pad, h - pad), (h // 2 if shape == 'pill' else 44 * SS) - pad // 2, fill=plate)
    elif shape == 'circle':
        side = h - 2 * pad
        d.ellipse(((w - side) // 2, pad, (w + side) // 2, pad + side), fill=plate)
    elif shape == 'ring':
        side = h - 2 * pad
        d.ellipse(((w - side) // 2, pad, (w + side) // 2, pad + side), outline=ink, width=14 * SS)
    elif shape == 'bar':
        d.rounded_rectangle((pad * 3, h - pad * 2, w - pad * 3, h - pad * 2 + 10 * SS), 4 * SS, fill=ink)
    box_w = {'circle': 0.30, 'ring': 0.30}.get(shape, 0.66) * w
    f = fitted(text, face, box_w, int(h * (0.42 if shape in ('bar',) else 0.46)))
    cy = h * (0.45 if shape == 'bar' else 0.5)
    d.text((w / 2, cy), text, font=f, fill=ink, anchor='mm')
    im = im.resize((LOGO_W, LOGO_H), Image.LANCZOS)
    im.save(art.track(os.path.join(DEMO, f'logo-{n}.png')), optimize=True)



def make_masks():
    """Exact-size 12px rounded-corner diffuse masks for 5x2 poster cards and 4x3 wide cards."""
    specs = (
        ("sweettv-poster-mask.png", 328, 356, 12),
        ("sweettv-wide-mask.png", 420, 206, 12),
    )
    for name, w, h, radius in specs:
        alpha = np.clip(art.rr_mask((w, h), (0, 0, w, h), radius) * 255, 0, 255).astype(np.uint8)
        arr = np.full((h, w, 4), 255, dtype=np.uint8)
        arr[..., 3] = alpha
        Image.fromarray(arr, "RGBA").save(art.track(os.path.join(art.MEDIA, name)), optimize=True)


def main():
    for d in (art.MEDIA, DEMO):
        os.makedirs(d, exist_ok=True)
    make_star()
    make_chip()
    make_bars()
    make_masks()
    for n, spec in enumerate(LOGOS, 1):
        make_logo(n, spec)
    for p in art.WRITTEN:
        print('%9d  %s' % (os.path.getsize(p), os.path.relpath(p, art.BASE)))


if __name__ == '__main__':
    main()
