#!/usr/bin/env python3
"""Procedural art for script.media-stick.home (textures, icons, app cards, wallpapers).

Dev tool, needs python3-pil, python3-numpy, fonts-roboto.
Usage: python3 tools/make-launcher-art.py <repo path>
Pure Pillow + numpy, deterministic (fixed seeds). Output is released under CC0 1.0.
The contact sheet goes to <repo>/.art/contact.png (kept out of git).
"""
import os
import sys

import numpy as np
from PIL import Image, ImageDraw, ImageFont

if len(sys.argv) < 2:
    sys.exit(__doc__)
REPO = sys.argv[1]
ART = os.path.join(REPO, '.art')
FONTS = '/usr/share/fonts/truetype/roboto/unhinted/RobotoTTF'
BASE = os.path.join(REPO, 'device', 'kodi-addons', 'script.media-stick.home')
MEDIA = os.path.join(BASE, 'resources', 'skins', 'default', 'media')
APPS = os.path.join(BASE, 'resources', 'media', 'apps')
WALL = os.path.join(BASE, 'resources', 'wallpapers')

W, H = 1920, 1080
YY = np.arange(H, dtype=np.float32)[:, None]
XX = np.arange(W, dtype=np.float32)[None, :]
WRITTEN = []


# ---------------------------------------------------------------- generic helpers

def smooth(t):
    t = np.clip(t, 0, 1)
    return t * t * (3 - 2 * t)


def lerp(a, b, t):
    return np.asarray(a, np.float32) * (1 - t) + np.asarray(b, np.float32) * t


def ramp(t, stops):
    p = [s[0] for s in stops]
    return np.stack([np.interp(t, p, [s[1][c] for s in stops]) for c in range(3)], -1).astype(np.float32)


def track(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    WRITTEN.append(path)
    return path


def rr_mask(size, box, radius, width=None, ss=4):
    """Anti-aliased rounded rect coverage (float 0..1). box = (x0, y0, x1, y1), x1/y1 exclusive."""
    w, h = size
    im = Image.new('L', (w * ss, h * ss), 0)
    x0, y0, x1, y1 = box
    kw = {'fill': 255} if width is None else {'outline': 255, 'width': int(round(width * ss))}
    ImageDraw.Draw(im).rounded_rectangle(
        (x0 * ss, y0 * ss, x1 * ss - 1, y1 * ss - 1), radius * ss, **kw)
    return np.asarray(im.resize((w, h), Image.BOX), np.float32) / 255.0


def conv_axis(a, k, axis, mode='constant'):
    r = len(k) // 2
    pad = [(r, r) if i == axis else (0, 0) for i in range(a.ndim)]
    p = np.pad(a, pad, mode=mode)
    out = np.zeros_like(a)
    for i, kv in enumerate(k):
        sl = [slice(None)] * a.ndim
        sl[axis] = slice(i, i + a.shape[axis])
        out += kv * p[tuple(sl)]
    return out


def gblur(a, sigma):
    r = int(sigma * 3) + 1
    k = np.exp(-0.5 * (np.arange(-r, r + 1) / sigma) ** 2)
    k = (k / k.sum()).astype(np.float32)
    return conv_axis(conv_axis(a, k, 0), k, 1)


def edge_fade(n, width):
    d = np.minimum(np.arange(n), np.arange(n)[::-1]) + 0.5
    f = smooth(d / width)
    return f[:, None] * f[None, :]


def save_rgba(path, alpha, color=(255, 255, 255), dither=None):
    a = alpha * 255.0
    if dither is not None:
        a = a + dither.uniform(-0.5, 0.5, a.shape)
    a = np.clip(np.rint(a), 0, 255).astype(np.uint8)
    arr = np.zeros(a.shape + (4,), np.uint8)
    arr[..., :3] = color
    arr[..., 3] = a
    Image.fromarray(arr).save(track(path))


# ---------------------------------------------------------------- A. UI textures

def make_textures():
    d = MEDIA
    save_rgba(os.path.join(d, 'white.png'), np.ones((16, 16), np.float32))
    save_rgba(os.path.join(d, 'card-mask.png'), rr_mask((256, 256), (0, 0, 256, 256), 30))

    ring = rr_mask((160, 160), (18, 18, 142, 142), 34, width=5)
    inside = rr_mask((160, 160), (23, 23, 137, 137), 29)
    glow = np.clip(gblur(ring, 7.0) * 2.4, 0, 0.85) * (1 - inside) * edge_fade(160, 18)
    save_rgba(os.path.join(d, 'card-glow.png'), np.maximum(ring, glow))

    body = rr_mask((160, 160), (40, 46, 120, 126), 30)
    shadow = np.clip(gblur(body, 14.0) * 0.55, 0, 0.55) * edge_fade(160, 12)
    save_rgba(os.path.join(d, 'card-shadow.png'), shadow, (0, 0, 0))

    rng = np.random.default_rng(7)
    t = (np.arange(512) / 511.0)[:, None] * np.ones((1, 16))
    save_rgba(os.path.join(d, 'gradient-bottom.png'), 0.88 * t ** 2.2, (0, 0, 0), rng)
    t = (np.arange(256) / 255.0)[:, None] * np.ones((1, 16))
    save_rgba(os.path.join(d, 'gradient-top.png'), 0.55 * (1 - smooth(t)) ** 1.3, (0, 0, 0), rng)
    t = (np.arange(512) / 511.0)[None, :] * np.ones((16, 1))
    save_rgba(os.path.join(d, 'gradient-left.png'), 0.7 * (1 - smooth(t)) ** 1.4, (0, 0, 0), rng)
    save_rgba(os.path.join(d, 'pill.png'), rr_mask((96, 96), (0, 0, 96, 96), 48))


class Icon:
    """96x96 icon drawn at 4x in 96-unit coordinates."""
    S = 4

    def __init__(self):
        self.im = Image.new('L', (96 * self.S, 96 * self.S), 0)
        self.d = ImageDraw.Draw(self.im)

    def line(self, pts, w=7):
        s = self.S
        p = [(x * s, y * s) for x, y in pts]
        self.d.line(p, fill=255, width=int(w * s), joint='curve')
        r = w * s / 2
        for x, y in p:
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=255)

    def arc(self, c, r, a0, a1, w=7):
        angs = np.radians(np.linspace(a0, a1, max(8, int(abs(a1 - a0) / 2))))
        self.line([(c[0] + r * np.cos(a), c[1] + r * np.sin(a)) for a in angs], w)

    def circle(self, c, r, w=7):
        s = self.S
        ro = (r + w / 2) * s
        self.d.ellipse((c[0] * s - ro, c[1] * s - ro, c[0] * s + ro, c[1] * s + ro),
                       outline=255, width=int(w * s))

    def disc(self, c, r):
        s = self.S
        self.d.ellipse(((c[0] - r) * s, (c[1] - r) * s, (c[0] + r) * s, (c[1] + r) * s), fill=255)

    def rrect(self, box, rad, w=None):
        s = self.S
        x0, y0, x1, y1 = box
        kw = {'fill': 255} if w is None else {'outline': 255, 'width': int(w * s)}
        self.d.rounded_rectangle((x0 * s, y0 * s, x1 * s - 1, y1 * s - 1), rad * s, **kw)

    def result(self):
        return np.asarray(self.im.resize((96, 96), Image.BOX), np.float32) / 255.0


def gear_points():
    pts = []
    for k in range(8):
        c = k * 45.0
        for a, r in ((c - 12, 25), (c - 8, 32), (c + 8, 32), (c + 12, 25), (c + 19, 25), (c + 26, 25)):
            pts.append((48 + r * np.cos(np.radians(a)), 48 + r * np.sin(np.radians(a))))
    pts.append(pts[0])
    return pts


def make_icons():
    def save(name, ic):
        save_rgba(os.path.join(MEDIA, name), ic.result())

    ic = Icon(); ic.circle((40, 40), 22); ic.line([(56, 56), (80, 80)], 8); save('icon-search.png', ic)

    ic = Icon()
    for j in range(3):
        for i in range(3):
            x, y = 12 + i * 27, 12 + j * 27
            ic.rrect((x, y, x + 18, y + 18), 5)
    save('icon-apps.png', ic)

    ic = Icon(); ic.rrect((26, 12, 70, 84), 10, 7); ic.disc((48, 73), 3.6); save('icon-phone.png', ic)

    ic = Icon(); ic.line(gear_points(), 6); ic.circle((48, 48), 10, 6); save('icon-settings.png', ic)

    ic = Icon(); ic.arc((48, 52), 28, -50, 230); ic.line([(48, 16), (48, 46)]); save('icon-power.png', ic)

    ic = Icon()
    for y in (28, 48, 68):
        ic.line([(18, y), (78, y)])
    save('icon-menu.png', ic)

    ic = Icon()
    for r in (20, 38, 56):
        ic.arc((48, 77), r, -130, -50)
    ic.disc((48, 77), 5.5)
    save('icon-wifi.png', ic)

    ic = Icon()
    ic.rrect((34, 12, 62, 32), 5, 7); ic.rrect((12, 64, 36, 84), 5, 7); ic.rrect((60, 64, 84, 84), 5, 7)
    ic.line([(48, 32), (48, 46)]); ic.line([(24, 46), (72, 46)])
    ic.line([(24, 46), (24, 64)]); ic.line([(72, 46), (72, 64)])
    save('icon-ethernet.png', ic)

    ic = Icon(); ic.line([(60, 16), (34, 48), (60, 80)], 8); save('icon-chevron-left.png', ic)


# ---------------------------------------------------------------- B. app cards, C. add-on icon

def text_width(text, font, trk):
    if trk == 0:
        return font.getlength(text)
    return sum(font.getlength(c) for c in text) + trk * font.size * (len(text) - 1)


def draw_text_block(im, lines, color, target, maxsize, gap):
    """lines = [(text, fontfile, tracking_em)] centred on the 512 square, each fitted to `target` px."""
    prepared = []
    for text, ff, trk in lines:
        w100 = text_width(text, ImageFont.truetype(os.path.join(FONTS, ff), 100), trk)
        size = int(min(maxsize, target / w100 * 100))
        font = ImageFont.truetype(os.path.join(FONTS, ff), size)
        bb = font.getbbox(text, anchor='ls')
        prepared.append((text, font, trk, text_width(text, font, trk), bb[1], bb[3]))
    total = sum(p[5] - p[4] for p in prepared) + gap * (len(prepared) - 1)
    y = 256 - total / 2
    d = ImageDraw.Draw(im)
    for text, font, trk, wd, t, b in prepared:
        x, base = 256 - wd / 2, y - t
        if trk == 0:
            d.text((x, base), text, font=font, fill=color, anchor='ls')
        else:
            for ch in text:
                d.text((x, base), ch, font=font, fill=color, anchor='ls')
                x += font.getlength(ch) + trk * font.size
        y += (b - t) + gap


def make_card(name, c0, c1, lines, fg, target=400, maxsize=190, gap=26, seed=0):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    t = ((xx + yy) / 1022.0)[..., None]
    img = lerp(c0, c1, t)
    r = np.hypot(xx - 110, yy - 70) / 620.0
    img = img + 255 * 0.08 * (np.clip(1 - r, 0, 1) ** 2)[..., None]
    img = img + rng.uniform(-0.5, 0.5, img.shape)
    im = Image.fromarray(np.clip(np.rint(img), 0, 255).astype(np.uint8))
    draw_text_block(im, lines, fg, target, maxsize, gap)
    im.save(track(os.path.join(APPS, name)))


def make_cards():
    make_card('netflix.png', (22, 22, 22), (0, 0, 0), [('NETFLIX', 'Roboto-Black.ttf', 0.04)],
              (229, 9, 20), target=420, seed=1)
    make_card('disney.png', (11, 30, 91), (18, 56, 201), [('Disney+', 'Roboto-Bold.ttf', 0)],
              (255, 255, 255), target=420, seed=2)
    make_card('prime.png', (0, 168, 225), (15, 121, 175),
              [('prime', 'Roboto-Bold.ttf', 0), ('video', 'Roboto-Bold.ttf', 0)],
              (255, 255, 255), target=360, maxsize=170, gap=30, seed=3)
    make_card('max.png', (0, 43, 231), (91, 31, 214),
              [('HBO', 'Roboto-Black.ttf', 0.02), ('Max', 'Roboto-Black.ttf', 0.02)],
              (255, 255, 255), target=360, maxsize=190, gap=30, seed=4)


def make_addon_icon():
    S = 256
    tile = rr_mask((S, S), (0, 0, S, S), 52)
    y = np.arange(S) / S
    sky = ramp(y, [(0, (28, 42, 100)), (0.3, (86, 68, 160)), (0.5, (212, 118, 146)),
                   (0.62, (250, 176, 118)), (1, (250, 176, 118))])[:, None, :]
    a = (1 - smooth((y - 0.42) / 0.38))[:, None, None]
    img = np.zeros((S, S, 3), np.float32) + np.array((16, 20, 27), np.float32)
    img = img * (1 - a) + sky * a
    yy, xx = np.mgrid[0:S, 0:S].astype(np.float32)
    g = np.exp(-(((xx - 128) / 80) ** 2 + ((yy - 150) / 46) ** 2))[..., None]
    img = img + g * np.array((255, 190, 120), np.float32) * 0.35 * a
    cols = [(232, 236, 246), (120, 170, 255), (255, 184, 108)]
    for i, c in enumerate(cols):
        y0 = 164 - (12 if i == 1 else 0)
        x0 = 32 + i * 68
        m = (rr_mask((S, S), (x0, y0, x0 + 56, y0 + 56), 13) * 0.96)[..., None]
        img = img * (1 - m) + np.array(c, np.float32) * m
    arr = np.zeros((S, S, 4), np.uint8)
    arr[..., :3] = np.clip(np.rint(img), 0, 255)
    arr[..., 3] = np.clip(np.rint(tile * 255), 0, 255)
    Image.fromarray(arr).save(track(os.path.join(BASE, 'icon.png')))


def make_extra_media():
    """pill-80 (9-slice border 40) and the neutral app-fallback card."""
    save_rgba(os.path.join(MEDIA, 'pill-80.png'), rr_mask((80, 80), (0, 0, 80, 80), 40))
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:512, 0:512].astype(np.float32)
    img = lerp((64, 68, 78), (30, 33, 40), ((xx + yy) / 1022.0)[..., None])
    r = np.hypot(xx - 110, yy - 70) / 620.0
    img = img + 255 * 0.05 * (np.clip(1 - r, 0, 1) ** 2)[..., None]
    size, gap = 112, 28
    x0 = 256 - size - gap / 2
    glyph = np.zeros((512, 512), np.float32)
    for j in range(2):
        for i in range(2):
            bx, by = x0 + i * (size + gap), x0 + j * (size + gap)
            ring = 14 if (i, j) == (1, 0) else None
            glyph = np.maximum(glyph, rr_mask((512, 512), (bx, by, bx + size, by + size), 26, width=ring))
    img = img + (np.array((205, 210, 220), np.float32) - img) * (glyph * 0.88)[..., None]
    img = img + rng.uniform(-0.5, 0.5, img.shape)
    Image.fromarray(np.clip(np.rint(img), 0, 255).astype(np.uint8)).save(
        track(os.path.join(MEDIA, 'app-fallback.png')))


# ---------------------------------------------------------------- D. wallpaper toolkit

def noise1d(rng, period, n=W):
    m = int(n / period) + 3
    v = rng.random(m)
    x = np.arange(n) / period
    i = x.astype(int)
    f = smooth(x - i)
    return (v[i] * (1 - f) + v[i + 1] * f).astype(np.float32)


def fbm1d(rng, period, octaves=7, pers=0.5, ridged=0.0):
    tot = np.zeros(W, np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        if period / 2 ** o < 3:
            break
        n = noise1d(rng, period / 2 ** o)
        if ridged:
            n = (1 - ridged) * n + ridged * (1 - np.abs(2 * n - 1))
        tot += amp * n
        norm += amp
        amp *= pers
    r = tot / norm
    return (r - r.min()) / (r.max() - r.min() + 1e-6)


def fbm2d(rng, cells_y, cells_x, octaves=5, pers=0.5):
    tot = np.zeros((H, W), np.float32)
    amp, norm = 1.0, 0.0
    for o in range(octaves):
        cy, cx = max(2, int(cells_y * 2 ** o)), max(2, int(cells_x * 2 ** o))
        a = rng.random((cy, cx)).astype(np.float32)
        tot += amp * np.asarray(Image.fromarray(a).resize((W, H), Image.BICUBIC))
        norm += amp
        amp *= pers
    t = tot / norm
    return (t - t.min()) / (t.max() - t.min() + 1e-6)


def sky_img(stops):
    col = ramp(np.arange(H) / H, stops)
    return np.ascontiguousarray(np.broadcast_to(col[:, None, :], (H, W, 3)))


def add_glow(img, cx, cy, sx, sy, col, k):
    d = ((XX - cx) / sx) ** 2 + ((YY - cy) / sy) ** 2
    img += np.exp(-d)[..., None] * np.asarray(col, np.float32) * k


def add_stars(img, rng, n, ymax, k=1.0):
    xs = rng.integers(0, W, n)
    ys = (rng.random(n) ** 0.9 * ymax).astype(int)
    keep = ~((xs > 0.72 * W) & (ys < 0.25 * H))
    xs, ys = xs[keep], ys[keep]
    b = (rng.random(len(xs)) ** 3 * 0.9 + 0.1) * k
    tint = np.array((0.85, 0.92, 1.0), np.float32) * 255
    np.add.at(img, (ys, xs), b[:, None] * tint)
    big = b > 0.5 * k
    for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
        np.add.at(img, (np.clip(ys[big] + dy, 0, H - 1), np.clip(xs[big] + dx, 0, W - 1)),
                  b[big, None] * tint * 0.3)


def fill_layer(img, ytop, top, bot, fade=300.0, alpha=1.0):
    top, bot = np.asarray(top, np.float32), np.asarray(bot, np.float32)
    top = top[None, None, :] if top.ndim == 1 else top[None, :, :]
    bot = bot[None, None, :] if bot.ndim == 1 else bot[None, :, :]
    dy = YY - np.asarray(ytop, np.float32)[None, :]
    a = np.clip(dy + 0.5, 0, 1) * alpha
    depth = smooth(dy / fade)
    col = top + (bot - top) * depth[..., None]
    img += (col - img) * a[..., None]


def veil(img, col, alpha):
    img += (np.asarray(col, np.float32) - img) * alpha


def mist(img, rng, y0, sigma, col, k, xperiod=500):
    m = np.exp(-((YY - y0) / sigma) ** 2) * (0.55 + 0.45 * noise1d(rng, xperiod))[None, :] * k
    img += (np.asarray(col, np.float32) - img) * m[..., None]


def add_clouds(img, rng, y0, y1, warm, cool, k, cells=(3, 7), thr=0.5):
    f = fbm2d(rng, cells[0], cells[1], 5, 0.55)
    env = smooth((YY - y0) / (0.08 * H)) * smooth((y1 - YY) / (0.12 * H))
    quiet = 1 - 0.85 * smooth((XX / W - 0.7) / 0.2) * smooth((0.3 * H - YY) / (0.12 * H))
    dens = smooth((f - thr) * 3.5) * env * quiet * k
    mv = smooth((YY - y0) / (y1 - y0))
    col = np.asarray(cool, np.float32) * (1 - mv)[..., None] + np.asarray(warm, np.float32) * mv[..., None]
    img += (col - img) * dens[..., None]


def reflect(img, yw, tint, mix, rng, rip=5.0):
    """Mirror everything above row yw into the lake below it, with ripples."""
    n = H - yw
    ys = np.arange(yw, H)
    refl = img[np.clip(2 * yw - 1 - ys, 0, H - 1)].copy()
    depth = (ys - yw) / n
    shift = np.sin((ys - yw) * 0.35 + rng.random() * 6.28) * rip * (0.15 + depth) \
        + rng.normal(0, 1, n) * rip * 0.3 * depth
    for i in range(n):
        refl[i] = np.roll(refl[i], int(round(shift[i])), axis=0)
    acc = np.zeros_like(refl)
    for s in range(-6, 7, 2):
        acc += np.roll(refl, s, axis=1)
    refl = acc / 7.0
    m = (mix + 0.25 * depth)[:, None, None]
    refl = refl * (1 - m) + np.asarray(tint, np.float32) * m
    refl *= (1 - 0.12 * depth)[:, None, None] * (1 + 0.04 * rng.normal(0, 1, n))[:, None, None]
    img[yw:] = refl


def ridge(rng, base, amp, period, octaves=8, pers=0.5, ridged=0.5):
    return base - amp * fbm1d(rng, period, octaves, pers, ridged)


def conifers(rng, base, ground_amp, hmin, hmax, wratio, count):
    x = np.arange(W, dtype=np.float32)
    ground = base - ground_amp * fbm1d(rng, 700, 3, 0.5)
    tree = np.zeros(W, np.float32)
    for c, h in zip(rng.uniform(-50, W + 50, count), rng.uniform(hmin, hmax, count)):
        w = h * wratio * rng.uniform(0.8, 1.2)
        t7 = np.clip(1 - np.abs(x - c) / w, 0, 1) * 7
        fl = np.floor(t7)
        t = (fl + smooth((t7 - fl) * 2.5)) / 7 * h
        tree = np.maximum(tree, t)
    return ground - tree


def finalize(img, name, seed):
    t = YY / H
    dark = 1 - 0.42 * smooth((t - 0.6) / 0.4)
    dx, dy = (XX / W - 0.5) * 2, (YY / H - 0.5) * 2
    v = 1 - 0.10 * np.clip(dx ** 2 * 0.6 + dy ** 2 * 0.4, 0, 1)
    img = img * (dark * v)[..., None]
    path = track(os.path.join(WALL, name))
    for gs, q in ((1.0, 86), (0.7, 86), (0.45, 86), (0.45, 82), (0.45, 78), (0.45, 74)):
        rng = np.random.default_rng(seed)
        g = rng.normal(0, 1.1 * gs, (H, W, 1)) + rng.normal(0, 0.5 * gs, (H, W, 3))
        im = Image.fromarray(np.clip(img + g + 0.5, 0, 255).astype(np.uint8))
        im.save(path, 'JPEG', quality=q, optimize=True)
        if os.path.getsize(path) <= 450_000:
            break


# ---------------------------------------------------------------- D. scenes

def scene_alpine():
    rng = np.random.default_rng(101)
    img = sky_img([(0, (18, 20, 58)), (0.28, (52, 46, 108)), (0.46, (132, 86, 140)),
                   (0.58, (238, 142, 118)), (0.7, (255, 190, 130)), (1, (255, 190, 130))])
    add_stars(img, rng, 350, 0.3 * H, 0.5)
    add_glow(img, 0.36 * W, 0.60 * H, 520, 230, (255, 140, 80), 0.55)
    add_glow(img, 0.36 * W, 0.60 * H, 160, 90, (255, 200, 140), 0.4)
    haze = (222, 140, 140)
    bases = [0.50, 0.56, 0.63, 0.72, 0.82, 0.93]
    amps = [0.20, 0.19, 0.17, 0.14, 0.11, 0.08]
    periods = [700, 520, 420, 330, 260, 200]
    ridged = [0.7, 0.65, 0.55, 0.45, 0.35, 0.3]
    for i in range(6):
        t = i / 5
        ytop = ridge(rng, bases[i] * H, amps[i] * H, periods[i], ridged=ridged[i])
        top = lerp((150, 110, 165), (16, 18, 40), t ** 0.75)
        bot = lerp(top, haze, 0.5 * (1 - t) + 0.05)
        fill_layer(img, ytop, top, bot, fade=amps[i] * H * 1.1)
        if i in (1, 3):
            mist(img, rng, bases[i] * H - 0.02 * H, 55, lerp(haze, (120, 100, 150), 0.5), 0.45)
    return img


def add_aurora(img, rng, base, hgt, amp, strength):
    x = np.arange(W)
    yc = (base + amp * (fbm1d(rng, 900, 4, 0.5) - 0.5) * 2
          + 0.04 * H * np.sin(x / 260.0 + rng.random() * 6)).astype(np.float32)
    rays = (0.55 + 0.45 * noise1d(rng, 10)) * (0.6 + 0.4 * noise1d(rng, 60)) * (0.35 + 0.65 * noise1d(rng, 300))
    d = yc[None, :] - YY
    prof = np.where(d >= 0, np.exp(-np.clip(d, 0, None) / hgt), np.exp(-np.clip(-d, 0, None) / 10))
    quiet = 1 - 0.85 * smooth((XX / W - 0.72) / 0.2) * smooth((0.32 - YY / H) / 0.2)
    col = ramp(np.clip(d / (2.2 * hgt), 0, 1), [(0, (70, 255, 160)), (0.5, (60, 200, 210)), (1, (150, 90, 230))])
    a = prof * rays[None, :] * quiet * strength
    img += a[..., None] * col


def scene_aurora():
    rng = np.random.default_rng(202)
    yw = int(0.74 * H)
    img = sky_img([(0, (2, 5, 16)), (0.4, (8, 20, 42)), (0.7, (20, 60, 72)), (1, (20, 60, 72))])
    add_stars(img, rng, 1100, 0.62 * H, 1.0)
    add_aurora(img, rng, 0.38 * H, 190, 0.06 * H, 0.75)
    add_aurora(img, rng, 0.28 * H, 150, 0.05 * H, 0.45)
    add_aurora(img, rng, 0.46 * H, 120, 0.04 * H, 0.3)
    for base, amp, per, top in ((0.60, 0.14, 560, (14, 30, 46)), (0.66, 0.10, 420, (8, 18, 30)),
                                (0.725, 0.05, 300, (4, 8, 14))):
        fill_layer(img, ridge(rng, base * H, amp * H, per, ridged=0.45), top,
                   lerp(top, (20, 50, 60), 0.3), fade=200)
    reflect(img, yw, (6, 18, 30), 0.25, rng, 5.0)
    return img


def scene_ocean():
    rng = np.random.default_rng(303)
    yh = int(0.58 * H)
    sx, sy = 0.46 * W, yh - 18
    img = sky_img([(0, (56, 76, 138)), (0.25, (150, 140, 172)), (0.45, (250, 170, 142)),
                   (0.58, (255, 212, 156)), (1, (255, 212, 156))])
    add_glow(img, sx, sy, 900, 400, (255, 190, 130), 0.35)
    add_glow(img, sx, sy, 300, 160, (255, 190, 120), 0.6)
    add_glow(img, sx, sy, 60, 50, (255, 240, 210), 1.0)
    add_clouds(img, rng, 0.10 * H, yh - 10, (255, 190, 150), (130, 110, 150), 0.65)
    disc = smooth((46 - np.hypot(XX - sx, YY - sy)) / 4)[..., None]
    img += (np.array((255, 248, 225), np.float32) - img) * disc
    reflect(img, yh, (30, 58, 98), 0.35, rng, 3.5)
    dyw = np.clip(YY - yh, 0, None)
    g = np.exp(-((XX - sx) / (40 + dyw * 0.30)) ** 2) * smooth(dyw / 4) * np.exp(-dyw / 450)
    sp = smooth((fbm2d(rng, 200, 40, 3, 0.5) - 0.35) * 3)
    img += (g * sp * 0.95)[..., None] * np.array((255, 215, 150), np.float32)
    wave = fbm2d(rng, 120, 30, 3, 0.5)
    img[yh:] *= (0.95 + 0.1 * wave[yh:])[..., None]
    return img


def scene_desert():
    rng = np.random.default_rng(404)
    img = sky_img([(0, (140, 182, 214)), (0.3, (196, 214, 224)), (0.5, (246, 222, 196)), (1, (246, 222, 196))])
    add_glow(img, 0.26 * W, 0.34 * H, 700, 380, (255, 236, 200), 0.45)
    add_glow(img, 0.26 * W, 0.34 * H, 120, 100, (255, 248, 230), 0.5)
    bases = [0.55, 0.62, 0.70, 0.80, 0.92]
    amps = [0.07, 0.09, 0.10, 0.12, 0.12]
    periods = [900, 700, 600, 500, 450]
    for i in range(5):
        t = i / 4
        # smooth silhouette: few low octaves, no ridged creases
        ytop = ridge(rng, bases[i] * H, amps[i] * H, periods[i], octaves=3, pers=0.3, ridged=0.0)
        top = lerp((240, 212, 186), (230, 158, 96), t)
        bot = lerp((208, 170, 160), (110, 62, 50), t)
        fill_layer(img, ytop, top, bot, fade=amps[i] * H * 2.5)
        # soft sunlit rim along the crest (same for every column, no per-column shading)
        rim = np.exp(-np.clip(YY - ytop[None, :], 0, None) / 22.0) * (YY >= ytop[None, :] - 0.5)
        img += (np.array((255, 236, 200), np.float32) - img) * (rim * 0.35 * (1 - 0.5 * t))[..., None]
        if i < 4:
            mist(img, rng, bases[i] * H, 40, (246, 222, 196), 0.18)
    img *= (0.97 + 0.06 * fbm2d(rng, 6, 12, 4, 0.5))[..., None]
    return img


def scene_forest():
    rng = np.random.default_rng(505)
    fog = (186, 204, 204)
    img = sky_img([(0, (205, 218, 216)), (0.5, (186, 204, 202)), (1, (186, 204, 202))])
    add_glow(img, 0.28 * W, 0.22 * H, 500, 300, (255, 252, 235), 0.35)
    bases = [0.50, 0.58, 0.66, 0.74, 0.83, 0.92, 1.02]
    hmaxs = [0.07, 0.09, 0.11, 0.14, 0.18, 0.23, 0.30]
    for i in range(7):
        t = i / 6
        hmax = hmaxs[i] * H
        count = int(W / (hmax * 0.24 * 0.5))
        ytop = conifers(rng, bases[i] * H, 0.04 * H, 0.55 * hmax, hmax, 0.24, count)
        top = lerp((74, 98, 96), (14, 30, 30), t)
        fill_layer(img, ytop, top, lerp(top, (150, 170, 170), 0.35 * (1 - t) + 0.1), fade=hmax * 1.5)
        if i < 6:
            veil(img, fog, 0.32)
    return img


def scene_lake():
    rng = np.random.default_rng(606)
    yw = int(0.66 * H)
    img = sky_img([(0, (52, 92, 150)), (0.3, (150, 160, 190)), (0.5, (246, 196, 140)),
                   (0.66, (255, 206, 130)), (1, (255, 206, 130))])
    add_glow(img, 0.30 * W, 0.52 * H, 800, 330, (255, 190, 110), 0.55)
    add_glow(img, 0.30 * W, 0.52 * H, 140, 90, (255, 230, 170), 0.5)
    add_clouds(img, rng, 0.12 * H, 0.55 * H, (255, 200, 150), (150, 140, 170), 0.35, (2, 6), 0.55)
    haze = (250, 190, 130)
    specs = [(yw - 10, 0.30, 640, (182, 150, 160), 0.5), (yw - 4, 0.24, 480, (120, 100, 128), 0.4),
             (yw, 0.17, 360, (64, 60, 84), 0.3), (yw + 0.01 * H, 0.05, 260, (22, 28, 34), 0.1)]
    for i, (base, amp, per, top, hz) in enumerate(specs):
        ytop = ridge(rng, base, amp * H, per, ridged=0.6 - 0.1 * i)
        fill_layer(img, ytop, top, lerp(top, haze, hz), fade=amp * H * 1.2)
        if i == 1:
            mist(img, rng, yw - 0.03 * H, 50, (255, 205, 150), 0.5)
    mist(img, rng, yw - 0.005 * H, 30, (255, 205, 150), 0.35)
    reflect(img, yw, (60, 70, 95), 0.18, rng, 4.0)
    return img


# ---------------------------------------------------------------- contact sheet

def nine_slice(im, size, b):
    w, h = im.size
    xs, ys = [0, b, w - b, w], [0, b, h - b, h]
    xd, yd = [0, b, size[0] - b, size[0]], [0, b, size[1] - b, size[1]]
    out = Image.new('RGBA', size, (0, 0, 0, 0))
    for j in range(3):
        for i in range(3):
            piece = im.crop((xs[i], ys[j], xs[i + 1], ys[j + 1]))
            out.paste(piece.resize((xd[i + 1] - xd[i], yd[j + 1] - yd[j]), Image.BILINEAR), (xd[i], yd[j]))
    return out


def make_contact(wall_names):
    cw, ch = 1540, 1230
    sheet = Image.new('RGB', (cw, ch), (18, 20, 26))
    for i, n in enumerate(wall_names):
        th = Image.open(os.path.join(WALL, n)).convert('RGB').resize((480, 270), Image.LANCZOS)
        sheet.paste(th, (30 + (i % 3) * 500, 30 + (i // 3) * 290))
    cmask = Image.open(os.path.join(MEDIA, 'card-mask.png')).split()[3].resize((200, 200), Image.LANCZOS)
    cards = [os.path.join(APPS, n) for n in ('netflix.png', 'disney.png', 'prime.png', 'max.png')]
    cards.append(os.path.join(BASE, 'icon.png'))
    for i, p in enumerate(cards):
        im = Image.open(p)
        if im.mode == 'RGBA':
            sheet.paste(im.convert('RGB').resize((200, 200), Image.LANCZOS), (30 + i * 220, 640),
                        im.split()[3].resize((200, 200), Image.LANCZOS))
        else:
            sheet.paste(im.convert('RGB').resize((200, 200), Image.LANCZOS), (30 + i * 220, 640), cmask)
    # focused card demo: shadow + card + glow, 9-sliced the way the skin would
    ox, oy = 1258, 614
    sh = nine_slice(Image.open(os.path.join(MEDIA, 'card-shadow.png')), (252, 252), 56)
    gl = nine_slice(Image.open(os.path.join(MEDIA, 'card-glow.png')), (252, 252), 56)
    sheet.paste(sh, (ox, oy + 8), sh)
    dm = Image.open(os.path.join(MEDIA, 'card-mask.png')).split()[3].resize((220, 220), Image.LANCZOS)
    sheet.paste(Image.open(cards[1]).convert('RGB').resize((220, 220), Image.LANCZOS), (ox + 16, oy + 16), dm)
    sheet.paste(gl, (ox, oy), gl)
    # icons on a plate
    plate = Image.new('RGB', (cw - 60, 120), (44, 50, 62))
    sheet.paste(plate, (30, 900))
    names = ['search', 'apps', 'phone', 'settings', 'power', 'menu', 'wifi', 'ethernet', 'chevron-left']
    for i, n in enumerate(names):
        a = Image.open(os.path.join(MEDIA, 'icon-%s.png' % n)).split()[3].resize((80, 80), Image.LANCZOS)
        sheet.paste(Image.new('RGB', (80, 80), (255, 255, 255)), (60 + i * 160, 920), a)
    fb = Image.open(os.path.join(MEDIA, 'app-fallback.png')).convert('RGB').resize((200, 200), Image.LANCZOS)
    sheet.paste(fb, (30, 1020), cmask)
    pill = Image.open(os.path.join(MEDIA, 'pill-80.png'))
    for k, wd in enumerate((120, 240, 420)):
        pl = Image.new('L', (wd, 80), 0)  # border 40 on a 80px-high pill: horizontal stretch only
        a = pill.split()[3]
        pl.paste(a.crop((0, 0, 40, 80)), (0, 0))
        pl.paste(a.crop((40, 0, 80, 80)), (wd - 40, 0))
        pl.paste(a.crop((39, 0, 41, 80)).resize((wd - 80, 80), Image.BILINEAR), (40, 0))
        sheet.paste(Image.new('RGB', pl.size, (230, 232, 238)), (260 + k * 300, 1080), pl)
    os.makedirs(ART, exist_ok=True)
    sheet.save(os.path.join(ART, 'contact.png'))


def main():
    for d in (MEDIA, APPS, WALL):
        os.makedirs(d, exist_ok=True)
    make_textures()
    make_icons()
    make_cards()
    make_addon_icon()
    make_extra_media()
    scenes = [('01-alpine-dusk.jpg', scene_alpine, 11), ('02-northern-lights.jpg', scene_aurora, 12),
              ('03-ocean-sunrise.jpg', scene_ocean, 13), ('04-desert-dunes.jpg', scene_desert, 14),
              ('05-misty-forest.jpg', scene_forest, 15), ('06-lake-mountains.jpg', scene_lake, 16)]
    for name, fn, seed in scenes:
        finalize(fn(), name, seed)
        print('done', name, flush=True)
    with open(track(os.path.join(WALL, 'LICENSE.txt')), 'w') as f:
        f.write('These wallpapers were generated procedurally for this repository by tools/make-launcher-art.py '
                '(numpy and Pillow, fixed random seeds) and contain no third-party material. '
                'They are released under CC0 1.0 Universal (public domain dedication): '
                'https://creativecommons.org/publicdomain/zero/1.0/\n')
    make_contact([s[0] for s in scenes])
    for p in WRITTEN:
        print('%9d  %s' % (os.path.getsize(p), os.path.relpath(p, BASE)))
    print('contact sheet:', os.path.join(ART, 'contact.png'))


if __name__ == '__main__':
    main()
