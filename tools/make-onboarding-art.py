#!/usr/bin/env python3
"""Pictures of the onboarding screens (resources/lib/onboarding_app.py, signin.py): the marker of a finished step (a
green disc with a white check), the ring of the other steps (white, tinted grey by the skin for a step to come) and
the rounded rectangle under a chip or a status badge (white, tinted by the skin; used with border="24").

Dev tool, needs python3-pil.
Usage: python3 tools/make-onboarding-art.py <repo path>
Deterministic; only the three files named here are written. Released under CC0 1.0.
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
CHIP, CHIP_RADIUS = 64, 21     # the chip's picture and its corners (the mockup's 14 px at 1.5 times)


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


def chip():
    """A rounded rectangle, not a pill: the skin cuts it at border 24 (more than the corner), so the corners are never
    stretched or cut through (the 96 px pill.png cut at a smaller border gives the spiky ends)."""
    size = CHIP * SS
    canvas = Image.new("RGBA", (size, size), WHITE + (0,))
    ImageDraw.Draw(canvas).rounded_rectangle((0, 0, size - 1, size - 1), radius=CHIP_RADIUS * SS, fill=WHITE + (255,))
    out = canvas.resize((CHIP, CHIP), Image.LANCZOS)
    out.save(os.path.join(MEDIA, "onboarding-chip.png"), optimize=True)
    print("%6d  %s" % (os.path.getsize(os.path.join(MEDIA, "onboarding-chip.png")), "onboarding-chip.png"))


if __name__ == "__main__":
    done()
    ring()
    chip()
