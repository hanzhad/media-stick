"""Where the person stopped, remembered on the stick, plus SWEET.TV local favourites and device quality cap.
Standard library only; nothing happens on import.

SWEET.TV (TV app and phone panel) reads the stick's local positions in /var/lib/media-stick/resume/positions.json
and local favourites in sweettv-favourites.json directly. YouTube uses its own profile/account history.

  load() / save(data)                 the positions file, written whole and renamed into place
  record(data, file, pos, total, now) the new positions after `file` was seen at `pos` of `total` seconds
  lookup(data, file), seconds_for, progress_for     what the places read
  localize_reply(reply, data)         a YouTube Files.GetDirectory answer with only the local resume and play count
  read_quality() / write_quality(val) device video quality cap ('720p', '1080p', 'unlimited') in prefs/max-quality
  load_favs() / toggle_fav(key, meta) SWEET.TV local favourites in sweettv-favourites.json

Positions (the same document for every app):
  {"v": 1, "items": {"yt:<video id>": {"pos", "total", "done", "at"},
                     "sw:<channel>|<programme>": {"cid", "epg", "pos", "total", "done", "at", "title", "start", "stop"},
                     "sw:vod:<movie_id>[|<episode_id>]": {"movie_id", "episode_id", "pos", "total", "done", "at", "title"}},
   "live": {"cid": "105", "at": <unix>}}                    the SWEET.TV channel that was on last
A SWEET.TV live stream has no place in it, only the channel; an archived programme or VOD item has its id and the
seconds; a video or programme watched to its end is kept as done (a full bar), not as a place.
"""
import json
import os
import re
import tempfile
import time
from urllib.parse import parse_qs, urlsplit

PREFS = os.environ.get("MEDIASTICK_PREFS_DIR", "/var/lib/media-stick/prefs")
DIR = os.environ.get("MEDIASTICK_RESUME_DIR", "/var/lib/media-stick/resume")
STORE_FILE = "positions.json"
QUALITY_FILE, DEFAULT_QUALITY = "max-quality", "1080p"
FAVS_FILE = "sweettv-favourites.json"
MAX_ITEMS = 300                     # the newest ones are kept
MIN_POS = 5                         # s: a place nearer the start than this is not worth coming back to
END_MARGIN = 30                     # s: a place nearer the end than this (or past 97 %) means watched to the end
WRITE_EVERY = 30                    # s between two writes of a place that moves on (a stop or the end writes at once)

SWEET_RE = re.compile(r"plugin://plugin\.video\.sweettv/playvid/([0-9]{1,12})\|(null|[0-9]{1,12})(?:\?[^\s]*)?")
SWEET_VOD_RE = re.compile(r"plugin://plugin\.video\.sweettv/playvod/([0-9]{1,12})\|(null|[0-9]{1,12})\|([0-9]{1,12})(?:\?[^\s]*)?")
YOUTUBE_RE = re.compile(r"plugin://plugin\.video\.youtube/[^\s]*")
VIDEO_ID_RE = re.compile(r"[A-Za-z0-9_-]{6,20}")
FAV_KEY_RE = re.compile(r"(show:vod:[0-9]{1,12}|show:epg:[0-9]{1,12}|show:tv:[0-9]{1,12}|vod:[0-9]{1,12}|ch:[0-9]{1,12})")


# ---- device preferences -----------------------------------------------------------------------

def _write_atomic(folder, name, text):
    tmp = None
    try:
        os.makedirs(folder, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.chmod(tmp, 0o644)
        os.replace(tmp, os.path.join(folder, name))
        return True
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def normalize_quality(value) -> str:
    """Normalize device video quality cap to '720p', '1080p' (default), or 'unlimited'."""
    if not isinstance(value, str):
        return DEFAULT_QUALITY
    v = value.strip().lower()
    if v == "720p":
        return "720p"
    if v in ("unlimited", "4k"):
        return "unlimited"
    return DEFAULT_QUALITY


def read_quality() -> str:
    """Read /var/lib/media-stick/prefs/max-quality, returning '1080p' when missing or invalid."""
    try:
        with open(os.path.join(PREFS, QUALITY_FILE), encoding="utf-8") as f:
            return normalize_quality(f.readline())
    except (OSError, ValueError):
        return DEFAULT_QUALITY


def write_quality(value) -> bool:
    """Write normalized quality cap atomically to prefs/max-quality."""
    return _write_atomic(PREFS, QUALITY_FILE, normalize_quality(value) + "\n")


# ---- what a played file is -------------------------------------------------------------------

def parse(file):
    """(\"yt\", video id), (\"sw\", channel id, programme id or \"\" for live), (\"sw_vod\", movie id, episode id or \"\"), or None."""
    if not isinstance(file, str):
        return None
    text = file.strip()
    m = SWEET_RE.fullmatch(text)
    if m:
        return ("sw", m.group(1), "" if m.group(2) == "null" else m.group(2))
    m = SWEET_VOD_RE.fullmatch(text)
    if m:
        return ("sw_vod", m.group(1), "" if m.group(2) == "null" else m.group(2))
    if YOUTUBE_RE.fullmatch(text):
        found = parse_qs(urlsplit(text).query).get("video_id", [""])[0]
        return ("yt", found) if VIDEO_ID_RE.fullmatch(found) else None
    return None


def key_of(parsed):
    if not parsed:
        return ""
    if parsed[0] == "yt":
        return "yt:" + parsed[1]
    if parsed[0] == "sw_vod":
        return "sw:vod:%s|%s" % (parsed[1], parsed[2]) if parsed[2] else "sw:vod:%s" % parsed[1]
    return "sw:%s|%s" % (parsed[1], parsed[2]) if parsed[2] else ""


# ---- the positions ---------------------------------------------------------------------------

def empty():
    return {"v": 1, "items": {}, "live": {}}


def _number(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        and abs(value) < 10 ** 12 else None


def _clean_sw_extras(item, src, old=None):
    old = old if isinstance(old, dict) else {}
    sid = src.get("show_id") if src.get("show_id") is not None else old.get("show_id")
    if isinstance(sid, (str, int)) and not isinstance(sid, bool) and str(sid).strip():
        item["show_id"] = str(sid).strip()[:32]
    for field in ("season", "episode"):
        val = _number(src.get(field) if src.get(field) is not None else old.get(field))
        if val is not None and val >= 0:
            item[field] = int(val)
    thumb = src.get("thumb") or old.get("thumb")
    if isinstance(thumb, str) and thumb.strip():
        item["thumb"] = thumb.strip()[:300]


def _clean(raw):
    """A positions document read from disk, reduced to what this library writes; anything else reads as nothing."""
    out = empty()
    items = raw.get("items") if isinstance(raw, dict) else None
    for key, e in (items.items() if isinstance(items, dict) else ()):
        if not isinstance(key, str) or not isinstance(e, dict) or not re.fullmatch(
                r"(yt:[A-Za-z0-9_-]{6,20}|sw:[0-9]{1,12}\|[0-9]{1,12}|sw:vod:[0-9]{1,12}(?:\|[0-9]{1,12})?)", key):
            continue
        pos, total, at = _number(e.get("pos")), _number(e.get("total")), _number(e.get("at"))
        if at is None or total is None or total <= 0 or pos is None or pos < 0:
            continue
        item = {"pos": int(pos), "total": int(total), "done": e.get("done") is True, "at": int(at)}
        if key.startswith("sw:vod:"):
            movie_id, _, ep_id = key[7:].partition("|")
            item.update(movie_id=movie_id, episode_id=ep_id, title=str(e.get("title") or "")[:120])
            thumb = e.get("thumb")
            if isinstance(thumb, str) and thumb.strip():
                item["thumb"] = thumb.strip()[:300]
        elif key.startswith("sw:"):
            cid, epg = key[3:].split("|")
            item.update(cid=cid, epg=epg, title=str(e.get("title") or "")[:120])
            for field in ("start", "stop"):
                value = _number(e.get(field))
                item[field] = int(value) if value and value > 0 else 0
            _clean_sw_extras(item, e)
        out["items"][key] = item
    live = raw.get("live") if isinstance(raw, dict) else None
    cid, at = (live.get("cid"), _number(live.get("at"))) if isinstance(live, dict) else (None, None)
    if isinstance(cid, str) and re.fullmatch(r"[0-9]{1,12}", cid) and at is not None:
        out["live"] = {"cid": cid, "at": int(at)}
    return out


def load(path=None):
    try:
        with open(path or os.path.join(DIR, STORE_FILE), encoding="utf-8") as f:
            return _clean(json.load(f))
    except (OSError, ValueError, MemoryError):
        return empty()


def save(data, path=None) -> bool:
    """Write the whole document and rename it into place: a power cut leaves the old one or the new one."""
    if path:
        return _write_atomic(os.path.dirname(path), os.path.basename(path), json.dumps(data, ensure_ascii=False))
    return _write_atomic(DIR, STORE_FILE, json.dumps(data, ensure_ascii=False))


def record(data, file, pos, total, now, meta=None):
    """The positions after `file` was seen at `pos` of `total` seconds (a new dict; `data` is not changed).
    `meta` is {"title", "start", "stop"} of a SWEET.TV programme when the caller knows it."""
    parsed = parse(file)
    data = _clean(data)
    if not parsed:
        return data
    if parsed[0] == "sw" and not parsed[2]:
        data["live"] = {"cid": parsed[1], "at": int(now)}          # live: the channel, no place
        return data
    pos, total = _number(pos), _number(total)
    if pos is None or total is None or total <= 0 or pos < 0:
        return data
    key = key_of(parsed)
    done = total - pos <= END_MARGIN or pos >= 0.97 * total
    if not done and pos < MIN_POS:
        return data                                              # seen at the start: an older place is not erased
    item = {"pos": 0 if done else int(pos), "total": int(total), "done": done, "at": int(now)}
    if parsed[0] == "sw":
        meta = meta if isinstance(meta, dict) else {}
        old = data["items"].get(key, {})
        item.update(cid=parsed[1], epg=parsed[2], title=str(meta.get("title") or old.get("title") or "")[:120],
                    start=int(_number(meta.get("start")) or old.get("start") or 0),
                    stop=int(_number(meta.get("stop")) or old.get("stop") or 0))
        _clean_sw_extras(item, meta, old)
    elif parsed[0] == "sw_vod":
        meta = meta if isinstance(meta, dict) else {}
        old = data["items"].get(key, {})
        item.update(movie_id=parsed[1], episode_id=parsed[2], title=str(meta.get("title") or old.get("title") or "")[:120])
        thumb = meta.get("thumb") or old.get("thumb")
        if isinstance(thumb, str) and thumb.strip():
            item["thumb"] = thumb.strip()[:300]
    data["items"][key] = item
    if len(data["items"]) > MAX_ITEMS:
        newest = sorted(data["items"].items(), key=lambda kv: -kv[1]["at"])[:MAX_ITEMS]
        data["items"] = dict(newest)
    return data


def lookup(data, file):
    """The saved entry of `file`, or None."""
    return _clean(data)["items"].get(key_of(parse(file)))


def seconds_for(data, file) -> int:
    """Where to continue `file` from: 0 when there is no place worth it (never saved, done, or nearer the start)."""
    e = lookup(data, file)
    return e["pos"] if e and not e["done"] and e["pos"] >= MIN_POS else 0


def progress_for(data, file) -> float:
    """How much of `file` was watched, 0..1 (1 for one watched to the end)."""
    e = lookup(data, file)
    if not e:
        return 0.0
    return 1.0 if e["done"] else min(1.0, e["pos"] / e["total"])


def due(last_write, now) -> bool:
    return now - last_write >= WRITE_EVERY


def programme_meta(raw, cid, epg):
    """{"title", "start", "stop"} of programme `epg` of channel `cid` in the add-on's channelList.json (already parsed), {}
    when it is not there."""
    for c in raw.get("list", ()) if isinstance(raw, dict) and isinstance(raw.get("list"), list) else ():
        if isinstance(c, dict) and str(c.get("id")) == str(cid):
            for p in c.get("epg", ()) if isinstance(c.get("epg"), list) else ():
                if isinstance(p, dict) and str(p.get("id")) == str(epg):
                    return {"title": str(p.get("text") or "")[:120], "start": p.get("time_start"), "stop": p.get("time_stop")}
    return {}


# ---- YouTube listings ------------------------------------------------------------------------

def localize_reply(reply, data):
    """A Files.GetDirectory answer ({"result": {"files": [...]}}) in which every YouTube video has only the local resume and
    play count: what Kodi or the add-on said about it is dropped, what this library saved is put in. Anything that does not
    look like such an answer comes back as it is."""
    result = reply.get("result") if isinstance(reply, dict) else None
    files = result.get("files") if isinstance(result, dict) else None
    if not isinstance(files, list):
        return reply
    data = _clean(data)
    out = []
    for item in files:
        parsed = parse(item.get("file")) if isinstance(item, dict) else None
        if not parsed or parsed[0] != "yt":
            out.append(item)
            continue
        item = {k: v for k, v in item.items() if k not in ("resume", "playcount", "lastplayed")}
        e = data["items"].get(key_of(parsed))
        item["playcount"] = 1 if e and e["done"] else 0
        if e and not e["done"] and e["pos"] >= MIN_POS:
            item["resume"] = {"position": e["pos"], "total": e["total"]}
        out.append(item)
    return {**reply, "result": {**result, "files": out}}


# ---- SWEET.TV local favourites ----------------------------------------------------------------

def _clean_favs(raw):
    out = {"v": 1, "items": {}}
    items = raw.get("items") if isinstance(raw, dict) else None
    for key, e in (items.items() if isinstance(items, dict) else ()):
        if not isinstance(key, str) or not FAV_KEY_RE.fullmatch(key) or not isinstance(e, dict):
            continue
        at = _number(e.get("at"))
        entry = {
            "title": str(e.get("title") or "")[:120],
            "thumb": str(e.get("thumb") or "")[:300],
            "at": int(at) if at is not None else 0,
        }
        if isinstance(e.get("meta"), dict):
            entry["meta"] = {str(k)[:32]: v for k, v in e["meta"].items() if isinstance(v, (str, int, float, bool)) or v is None}
        out["items"][key] = entry
    return out


def load_favs(path=None):
    try:
        with open(path or os.path.join(DIR, FAVS_FILE), encoding="utf-8") as f:
            return _clean_favs(json.load(f))
    except (OSError, ValueError, MemoryError):
        return {"v": 1, "items": {}}


def save_favs(data, path=None) -> bool:
    cleaned = _clean_favs(data)
    if path:
        return _write_atomic(os.path.dirname(path), os.path.basename(path), json.dumps(cleaned, ensure_ascii=False))
    return _write_atomic(DIR, FAVS_FILE, json.dumps(cleaned, ensure_ascii=False))


def fav_keys(data=None) -> set:
    doc = _clean_favs(data) if data is not None else load_favs()
    return set(doc["items"].keys())


def toggle_fav(key, meta=None, now=None, path=None):
    """Toggle a local SWEET.TV favourite (`show:vod:<id>`, `show:epg:<id>`, `show:tv:<id>`, `vod:<id>`, `ch:<id>`).
    Returns (is_now_fav, saved_ok)."""
    if not isinstance(key, str) or not FAV_KEY_RE.fullmatch(key):
        return False, False
    doc = load_favs(path)
    if key in doc["items"]:
        del doc["items"][key]
        return False, save_favs(doc, path)
    meta = meta if isinstance(meta, dict) else {}
    entry = {
        "title": str(meta.get("title") or "")[:120],
        "thumb": str(meta.get("thumb") or "")[:300],
        "at": int(time.time() if now is None else now),
    }
    if isinstance(meta.get("meta"), dict):
        entry["meta"] = meta["meta"]
    doc["items"][key] = entry
    return True, save_favs(doc, path)
