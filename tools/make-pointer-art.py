#!/usr/bin/env python3
"""Draw the TV mouse pointer: a white dot with a hairline edge and a soft shadow.

Usage: make-pointer-art.py <out.png>     (no dependencies, writes a 96x96 RGBA PNG)

skin.ftv is laid out in 3840x2160, so 96 px here is 48 px on the 1080p TV.
The result is kept in device/skin-overlay/skin.ftv/media/ms-pointer.png; run this
again only to change the look.
"""
import math
import struct
import sys
import zlib

N = 96          # image size
C = 48.0        # dot centre (x and y)
R = 16.0        # dot radius
EDGE = 2.5      # dark hairline round the dot, so it still shows on a white screen
SS = 4          # samples per axis per pixel (anti-aliasing)


def sample(x, y):
    """Premultiplied (r, g, b, a) of the picture at one point."""
    d = math.hypot(x - C, y - C)
    ds = math.hypot(x - C, y - (C + 3.0))             # shadow sits a little lower
    shadow = 0.5 * max(0.0, 1.0 - (ds - (R + EDGE - 2.0)) / 12.0) ** 2   # fades out over 12 px
    if d <= R:
        return (1.0, 1.0, 1.0, 1.0)
    if d <= R + EDGE:
        return (0.0, 0.0, 0.0, 0.34 + shadow * (1 - 0.34))
    return (0.0, 0.0, 0.0, shadow)


def png(w, h, rows):
    def chunk(tag, data):
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)
    raw = b"".join(bytes([0]) + row for row in rows)
    return (bytes([137, 80, 78, 71, 13, 10, 26, 10])
            + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def main(out):
    rows = []
    for py in range(N):
        row = bytearray()
        for px in range(N):
            acc = [0.0, 0.0, 0.0, 0.0]
            for sy in range(SS):
                for sx in range(SS):
                    s = sample(px + (sx + 0.5) / SS, py + (sy + 0.5) / SS)
                    for i in range(4):
                        acc[i] += s[i]
            r, g, b, a = (v / (SS * SS) for v in acc)
            if a > 0:
                r, g, b = r / a, g / a, b / a
            row += bytes([round(min(1, v) * 255) for v in (r, g, b, a)])
        rows.append(bytes(row))
    with open(out, "wb") as f:
        f.write(png(N, N, rows))


if __name__ == "__main__":
    main(sys.argv[1])
