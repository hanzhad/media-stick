"""SWEET.TV app: what the screen says about a channel. Ready data in, strings out; nothing here touches Kodi.

One channel becomes the properties of its card and of the preview above the row (the skin reads both from the
focused card): its colours, now and next, the progress, the badges, and whether there is a place to continue
from or a guide to open. The programme guide of a channel and the "continue from" label are made here too.
"""
import time
import zlib
from typing import NamedTuple, Optional

from resources.lib import sweettv_data as data

TINTS = ("FF5B6EE1", "FF2E9E8F", "FFC4623B", "FF8E5CC4", "FFB5497A", "FF4F8F3A", "FF3F7FBF", "FFB0852B")
PLATE, PLATE_HI, GROUND = "FF1B222E", "FF2C3649", "FF0A0E14"    # a card, the focused card, the screen
NO_PROGRAMMES = "No programme information"


class GuideRow(NamedTuple):
    epg_id: str
    title: str
    when: str                   # "22:10 – 23:00", with the date in front when it is not today
    kind: str                   # "live" (on now) or "archive" (finished, can be watched again)
    start: int
    stop: int


# ---- colours ---------------------------------------------------------------------------------

def mix(base, over, share) -> str:
    """AARRGGBB colour `share` (0..1) of the way from `base` to `over`; always opaque (alpha 00 reads as white)."""
    a, b = int(base[2:], 16), int(over[2:], 16)
    out = 0
    for shift in (16, 8, 0):
        x, y = (a >> shift) & 255, (b >> shift) & 255
        out |= round(x + (y - x) * share) << shift
    return f"FF{out:06X}"


def tint(name) -> str:
    return TINTS[zlib.crc32(name.encode("utf-8", "replace")) % len(TINTS)]


def colours(name) -> dict:
    """The channel's own colours: its tint, the card, the card when focused, the screen behind the preview."""
    return shades(tint(name))


def shades(base) -> dict:
    """The colours made from one tint (a card of a section has a tint of its own, not one made from its name)."""
    return {"tint": base, "plate": mix(PLATE, base, 0.30), "plate_hi": mix(PLATE_HI, base, 0.42),
            "bg": mix(GROUND, base, 0.30)}


def initials(name) -> str:
    words = [w for w in name.split() if any(c.isalnum() for c in w)]
    letters = "".join(next(c for c in w if c.isalnum()) for w in words[:2])
    return (letters or name.strip()[:2]).upper()


# ---- the archive -----------------------------------------------------------------------------

def day_prefix(ts, now) -> str:
    """"" for today, else the date, so a list that reaches back over midnight stays readable."""
    same = time.strftime("%Y%m%d", time.localtime(ts)) == time.strftime("%Y%m%d", time.localtime(now))
    return "" if same else time.strftime("%d.%m  ", time.localtime(ts))


def guide_rows(channel, now) -> list:
    """The programme guide of a channel: what is on now first (live), then the finished programmes the archive
    still holds, the newest first. A channel without an archive has only the live one (or none)."""
    rows = []
    for p in reversed(channel.epg):
        if p.start <= now < p.stop:
            kind = "live"
        elif (p.stop <= now and channel.catchup and p.available and p.epg_id
              and p.start >= now - channel.days * 86400):
            kind = "archive"
        else:
            continue
        rows.append(GuideRow(p.epg_id, p.title, f"{day_prefix(p.start, now)}{data.time_range(p)}", kind, p.start, p.stop))
    rows.sort(key=lambda r: (r.kind != "live", -r.start))
    return rows


def has_archive(channel, now) -> bool:
    return any(r.kind == "archive" for r in guide_rows(channel, now))


def resume_for(state, channel, now) -> Optional[dict]:
    """Where to continue `channel` from: its saved place, while the programme is still inside the archive."""
    entry = state["resume"].get(channel.cid)
    if entry and channel.catchup and entry["start"] >= now - channel.days * 86400:
        return entry
    return None


def resume_label(entry) -> str:
    """"Continue from 23:10": the clock time of the programme at the place it stopped."""
    return f"Continue from {data.hhmm(entry['start'] + entry['pos'])}"


# ---- a channel -------------------------------------------------------------------------------

def card_props(channel, now, favourite=False, cat_names=None, resume=None) -> dict:
    """The strings the skin shows for a channel: the card and the preview. `cat_names` maps category key -> name,
    `resume` is the saved place of an archived programme (see resume_for) or None."""
    current, following = data.now_next(channel, now)
    meta = [f"Channel {channel.number}"] if channel.number else []
    meta += [cat_names[f"c:{k}"] for k in channel.cats if cat_names and f"c:{k}" in cat_names][:2]
    step = data.progress_step(current, now)
    return {
        **colours(channel.name),
        "num": str(channel.number) if channel.number else "",
        "initials": initials(channel.name),
        "now": current.title if current else NO_PROGRAMMES,
        "nowrange": data.time_range(current) if current else "",
        "bar": data.bar_name(step) if current else "",
        "pbar": data.bar_name(step, wide=True) if current else "",
        "desc": current.desc if current else "",
        "next": following.title if following else "",
        "nextrange": data.time_range(following) if following else "",
        "meta": "  ·  ".join(meta),
        "fav": "1" if favourite else "",
        "catchup": "1" if channel.catchup else "",
        "guide": "1" if has_archive(channel, now) else "",
        "resume": resume_label(resume) if resume else "",
    }


def category_heading(name, count) -> str:
    """The line over the preview: the category and how many channels it holds."""
    return f"{name}  ·  {count} channel{'' if count == 1 else 's'}"
