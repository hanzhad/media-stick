"""Fitting words into a label: a name broken into the lines a label has room for. Ready data in, strings out;
nothing here touches Kodi. The width of a character is an estimate (Roboto, in ems) that errs wide: a line that
wraps early is fine, one that clips is not. The YouTube cards use it for titles, meta lines, badges and the
wizard step."""
from typing import Tuple

SAFETY = 1.05                   # the estimate errs wide
NARROW, MIDDLE, WIDE = "iljI.,:;'!|", "ftr", "mM"
EM = {"narrow": 0.26, "middle": 0.34, "wide": 0.85, "w": 0.8, "space": 0.25, "upper": 0.66, "digit": 0.56, "other": 0.54}


def _em(char) -> float:
    """Roughly how wide `char` is in Roboto, in ems."""
    if char == " ":
        return EM["space"]
    if char in NARROW:
        return EM["narrow"]
    if char in MIDDLE:
        return EM["middle"]
    if char in WIDE:
        return EM["wide"]
    if char in "wW":
        return EM["w"]
    if char.isdigit():
        return EM["digit"]
    return EM["upper"] if char.isupper() else EM["other"]


def text_px(text, size) -> float:
    return sum(_em(c) for c in text) * size * SAFETY


def _take(text, width, size, last):
    """(the first line of `text`, what is left): cut at the last space that fits, inside a word when one
    word is wider than the line; on the last line the rest is given up for an ellipsis."""
    if text_px(text, size) <= width:
        return text, ""
    if last:
        n = len(text)
        while n and text_px(text[:n].rstrip() + "…", size) > width:
            n -= 1
        return text[:n].rstrip() + "…", ""
    cut = max((i for i, c in enumerate(text) if c == " " and text_px(text[:i], size) <= width), default=0)
    if cut:
        return text[:cut], text[cut + 1:]
    n = max(1, max((i for i in range(1, len(text)) if text_px(text[:i], size) <= width), default=1))
    return text[:n], text[n:]


def wrap_name(name, width, size, lines) -> Tuple[str, ...]:
    """`name` as `lines` lines (padded with "") that each fit `width` px; the last ends in an ellipsis when
    the name is still too long."""
    rest, out = " ".join(name.split()), []
    while rest and len(out) < lines:
        head, rest = _take(rest, width, size, len(out) == lines - 1)
        out.append(head)
    return tuple(out + [""] * (lines - len(out)))
