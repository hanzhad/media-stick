"""SWEET.TV: going back on a live channel. Pure, standard library only; nothing happens on import.

A live SWEET.TV stream is a window of about a minute in Kodi, so Kodi's own seek back cannot go further than that. What can:
the archive of the programme on now (the add-on's `playvid/<channel>|<programme id>`), started at the place the person
asked for. One function decides that for everybody who asks - the TV remote (the add-on's service sees the seek), the
phone's -10 and the way back to the live stream - so they cannot disagree.

  plan(raw, cid, back, now)   raw is channelList.json (the add-on's own cache) -> what to play instead, or why not
  url(cid, epg, start)        the plugin path Kodi plays; `start` (seconds into the programme) rides in the query
  ref(file)                   a played item's path -> (channel id, programme id or "", start seconds), or None

Assumed, to be checked on a device: the time of the picture is the wall clock (LIVE_LAG seconds behind it).
"""
import importlib.util
import os
import re

ADDON_LIB = os.path.join("script.media-stick.home", "resources", "lib")
TEXT_DIRS = (os.environ.get("MEDIASTICK_ADDON_LIB", ""), "/home/media/.kodi/addons/" + ADDON_LIB,
             "/opt/media-stick/device/kodi-addons/" + ADDON_LIB)
_words = []
PLAY = "plugin://plugin.video.sweettv/playvid/{cid}|{epg}"
REF_RE = re.compile(r"plugin://plugin\.video\.sweettv/playvid/([0-9]{1,12})\|(null|[0-9]{1,12})(?:\?ms_start=([0-9]{1,6}))?")
LIVE_LAG = 0               # s the picture of a live stream is behind the clock; 0 until measured on a device
START_MAX = 3 * 86400
NO_ARCHIVE = "No archive for this channel"   # a msgid: text(NO_ARCHIVE) is what a person reads
PAUSE_LIMIT = 30           # s of pause on a live stream after which resuming goes to the archive (the window is ~60 s)


def text(msgid):
    """What a person reads for a msgid: the add-on's own dictionary (sweettv_text.tr), loaded as a module of its own
    because this library also runs inside another add-on; the msgid itself (English) when there is none."""
    if not _words:
        found = None
        for folder in TEXT_DIRS:
            path = os.path.join(folder, "sweettv_text.py") if folder else ""
            if path and os.path.isfile(path):
                try:
                    spec = importlib.util.spec_from_file_location("mediastick_sweettv_text", path)
                    found = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(found)
                except Exception:
                    found = None
                break
        _words.append(found)
    try:
        return _words[0].tr(msgid) if _words[0] else msgid
    except Exception:
        return msgid


def url(cid, epg=None, start=0):
    """What Player.Open / PlayMedia takes: the live stream of `cid`, or programme `epg` of its archive from `start` s."""
    cid, epg = str(cid), "null" if epg in (None, "") else str(epg)
    if not re.fullmatch(r"[0-9]{1,12}", cid) or not re.fullmatch(r"null|[0-9]{1,12}", epg):
        return ""
    link = PLAY.format(cid=cid, epg=epg)
    start = int(start) if isinstance(start, (int, float)) and not isinstance(start, bool) and start == start else 0
    return link + "?ms_start=%d" % min(start, START_MAX) if epg != "null" and start > 0 else link


def ref(file):
    """(channel id, programme id or "" for live, start seconds) of a played SWEET.TV item, or None."""
    m = REF_RE.fullmatch(file) if isinstance(file, str) else None
    return (m.group(1), "" if m.group(2) == "null" else m.group(2), int(m.group(3) or 0)) if m else None


def _seconds(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    n = int(value)
    return n // 1000 if n > 10 ** 11 else n


def _channel(raw, cid):
    rows = raw.get("list") if isinstance(raw, dict) else None
    for c in rows if isinstance(rows, list) else ():
        if isinstance(c, dict) and str(c.get("id")) == str(cid):
            return c
    return None


def plan(raw, cid, back, now):
    """What to play when the person goes `back` seconds on the live channel `cid`:
    {"ok": True, "epg", "title", "start", "stop", "offset", "url"} - the programme on now, from `offset` s in (never
    before its start); or {"ok": False, "reason": "unknown" | "no_archive" | "no_programme"}."""
    channel = _channel(raw, cid)
    if channel is None:
        return {"ok": False, "reason": "unknown"}
    if not channel.get("catchup") or channel.get("available") is False:
        return {"ok": False, "reason": "no_archive"}
    for p in channel.get("epg") if isinstance(channel.get("epg"), list) else ():
        if not isinstance(p, dict):
            continue
        start, stop = _seconds(p.get("time_start")), _seconds(p.get("time_stop"))
        if start is None or stop is None or not start <= now < stop:
            continue
        epg = p.get("id")
        if p.get("available") is False or isinstance(epg, bool) or not isinstance(epg, int) or epg <= 0:
            return {"ok": False, "reason": "no_archive"}
        offset = int(max(0, min(now - LIVE_LAG - start - max(0, back), stop - start - 1)))
        return {"ok": True, "epg": str(epg), "title": str(p.get("text") or "")[:120], "start": start, "stop": stop,
                "offset": offset, "url": url(cid, epg, offset)}
    return {"ok": False, "reason": "no_programme"}
