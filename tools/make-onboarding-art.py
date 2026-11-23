#!/usr/bin/env python3
"""Pictures of the onboarding screens (resources/lib/onboarding_app.py, signin.py): the marker of a finished step (a
green disc with a white check) and the ring of the other steps (white, tinted grey by the skin for a step to come).

Dev tool, needs python3-pil.
Usage: python3 tools/make-onboarding-art.py <repo path>
Deterministic; only the two files named here are written. Released under CC0 1.0.
"""
import os
import sys

from PIL import Image, ImageDraw

if len(sys.argv) < 2:
    sys.exit(__doc__)
MEDIA = os.path.join(sys.argv[1], "device", "kodi-addons", "script.media-stick.home", "resources", "skins", "default", "media")
SIZE, SS = 96, 8               # the picture, and how much larger it is drawn
GREEN, WHITE = (47, 107, 76), (255, 255, 255)
RING = 7                       # px of the ring's stroke, in the 96 px picture


def finish(canvas, name):
    out = canvas.resize((SIZE, SIZE), Image.LANCZOS)
    out.save(os.path.join(MEDIA, name), optimize=True)
    print("%6d  %s" % (os.path.getsize(os.path.join(MEDIA, name)), name))


def done():
    canvas = Image.new("RGBA", (SIZE * SS, SIZE * SS), GREEN + (0,))
    d = ImageDraw.Draw(canvas)
    d.ellipse((0, 0, SIZE * SS - 1, SIZE * SS - 1), fill=GREEN + (255,))
    points = [(27, 50), (42, 65), (70, 34)]
    d.line([(x * SS, y * SS) for x, y in points], fill=WHITE + (255,), width=8 * SS, joint="curve")
    for x, y in (points[0], points[2]):             # round ends
        r = 4 * SS
        d.ellipse((x * SS - r, y * SS - r, x * SS + r, y * SS + r), fill=WHITE + (255,))
    finish(canvas, "onboarding-done.png")


def ring():
    canvas = Image.new("RGBA", (SIZE * SS, SIZE * SS), WHITE + (0,))
    d = ImageDraw.Draw(canvas)
    d.ellipse((0, 0, SIZE * SS - 1, SIZE * SS - 1), fill=WHITE + (255,))
    inset = RING * SS
    d.ellipse((inset, inset, SIZE * SS - 1 - inset, SIZE * SS - 1 - inset), fill=WHITE + (0,))
    finish(canvas, "onboarding-ring.png")


if __name__ == "__main__":
    done()
    ring()
