#!/usr/bin/env python3
"""The boot picture: what the TV shows from power-on until the home screen.

Dev tool, needs python3-pil and Inter (fonts-inter; on the device: /usr/share/fonts/opentype/inter).
Usage: python3 tools/make-splash.py [path to InterDisplay-SemiBold.otf]
One picture, written twice: for Plymouth (the boot splash, theme "mediastick") and for Kodi
(special://home/media/splash.png, shown while Kodi loads). The same picture in both, so the
hand-over from one to the other does not show. It is the home screen's icon (the launcher's own,
script.media-stick.home/icon.png) over the dark of its lower edge, with the name under it.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ICON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home", "icon.png")
OUT = [os.path.join(ROOT, "device", "files", "usr", "share", "plymouth", "themes", "mediastick", "splash.png"),
       os.path.join(ROOT, "device", "files", "home", "media", ".kodi", "media", "splash.png")]
FONT = sys.argv[1] if len(sys.argv) > 1 else "/usr/share/fonts/opentype/inter/InterDisplay-SemiBold.otf"
W, H = 1920, 1080
BG = (16, 18, 24)          # the icon's lower edge
TEXT = (230, 232, 238)
NAME = "Media Stick"
ICON_SIZE, GAP, TEXT_SIZE = 220, 44, 64

img = Image.new("RGB", (W, H), BG)
icon = Image.open(ICON).convert("RGBA").resize((ICON_SIZE, ICON_SIZE), Image.LANCZOS)
font = ImageFont.truetype(FONT, TEXT_SIZE)
draw = ImageDraw.Draw(img)
left, top, right, bottom = draw.textbbox((0, 0), NAME, font=font)
block = ICON_SIZE + GAP + (bottom - top)
y = (H - block) // 2
img.paste(icon, ((W - ICON_SIZE) // 2, y), icon)
draw.text(((W - (right - left)) // 2 - left, y + ICON_SIZE + GAP - top), NAME, font=font, fill=TEXT)
for path in OUT:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    img.save(path, optimize=True)
    print(path)
