"""SWEET.TV: going back on a live channel. Pure, standard library only; nothing happens on import.

A live SWEET.TV stream is a window of about a minute in Kodi, so Kodi's own seek back cannot go further than that. What can:
the archive of the programme on now (the add-on's `playvid/<channel>|<programme id>`), started at the place the person
asked for. One function decides that for everybody who asks - the TV remote (the add-on's service sees the seek), the
phone's -10 and the way back to the live stream - so they cannot disagree.

  plan(raw, cid, back, now)   raw is channelList.json (the add-on's own cache) -> what to play instead, or why not
  url(cid, epg, start)        the plugin path Kodi plays; `start` (seconds into the programme) rides in the query
  ref(file)                   a played item's path -> (channel id, programme id or "", start seconds), or None
  remember / recall / identify   what an address of a stream is (see "Identity" below)
  seek_step / follow          the start place of an archive that has begun (see "Start place" below)
  ask / ask_url / start_of    how the add-on learns the place it was asked to start at (see "The ask" below)

Identity. Kodi tells the player the address of the stream the add-on resolved (https://hls-dvr2.sweet.tv/dvr/...), not the
plugin path that was asked for - at least for an archive - so nobody who asks the player "what is playing" can tell which
channel and programme it is. The add-on's `playvid` writes it down when it resolves (`remember`: channel, programme, where
to start, a hash of the address) in /run/media-stick/sweettv-now.json, the last few entries, newest first; whoever sees a
stream address later (`recall`, `identify`: the phone's "now playing", "К эфиру", the TV's remote, the recorder of places)
looks it up there. An address that is not in the file is not a SWEET.TV item of ours: it is nothing. No address, no token
is kept in the file, only a hash; the file is in RAM.

Start place. Kodi ignores the item property StartOffset of a plugin-resolved item, so an archive asked to start at second N
may begin at 0. `seek_step` decides, from where the player is and how long it says the stream is, whether to seek, and
`follow` is the loop that does it after the playback has begun (the add-on's service runs it in a thread).

The ask. Where the place of an archive travels is Kodi's business: on the device the add-on saw no `?ms_start=N` where it looked
(sys.argv[2]) although the path it was opened with had one (the "|" of `playvid/<channel>|<programme>` may make Kodi read what
follows as protocol options), so the add-on reads the place from every spot it may be in (argv[2], argv[0], the id itself) and, failing that, from the ask:
whoever opens an archive from a place (the phone's play and -10, the TV remote's seek back) knows channel, programme and
place before it opens, writes them in /run/media-stick/sweettv-ask.json (`ask`, `ask_url`) and opens. The add-on's `start_of`
takes the ask when it is for that channel and programme and no older than ASK_FRESH s, and takes it for good: a later play of
the programme, from the TV, is not put at a stale place.

Assumed, to be checked on a device: the time of the picture is the wall clock (LIVE_LAG seconds behind it).
"""
import hashlib
import importlib.util
import json
import os
import re
import tempfile
import time
from urllib.parse import unquote, urlsplit

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
NOW_DIR = os.environ.get("MEDIASTICK_SWEETNOW_DIR", "/run/media-stick")
NOW_FILE = "sweettv-now.json"
NOW_KEEP = 4               # entries kept: the item that is going away is still told apart while the next one is being opened
WEAK_AGE = 300             # s: an address that is not in the file but is of the same CDN folder as an entry this young is that entry
SEEK_FRESH = 120           # s: an entry older than this is not a start that someone is waiting for
SEEK_TOLERANCE = 8         # s: the player this near the asked place (or past it) is there
SEEK_WAIT = 60             # s the service waits for the playback to show its length, and for a seek to land
SEEK_RETRY = 3             # s between two seeks of one start
SEEK_ATTEMPTS = 3
MIN_TOTAL = 30             # s: a length shorter than this is the player not knowing yet, not a programme
ID_RE = re.compile(r"[0-9]{1,12}")
ASK_FILE = "sweettv-ask.json"
ASK_FRESH = 30             # s an ask is good for: the add-on is asked to resolve the item a moment after it is written
START_RE = re.compile(r"ms_start=([0-9]{1,12})")
ITEM_RE = re.compile(r"\s*([0-9]{1,12})\|(null|[0-9]{1,12})(?=$|[?&|#/%\s])")   # `<channel>|<programme or null>` and what Kodi may leave after it


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


# ---- identity: what the address of a stream is -------------------------------------------------

def _stream(file):
    """The address of a stream without the options after the first "|" (`url|User-Agent=...`), "" when `file` is not one."""
    head = file.split("|", 1)[0].strip() if isinstance(file, str) else ""
    return head if head.startswith(("http://", "https://")) else ""


def _where(stream):
    """The CDN folder of a stream address, "host/first-folder" ("" when it has no folder): what two addresses of one
    archive service share."""
    parts = urlsplit(stream)
    folders = parts.path.split("/")
    return "%s/%s" % (parts.netloc, folders[1]) if parts.netloc and len(folders) > 2 and folders[1] else ""


def _hash(stream):
    return hashlib.sha256(stream.encode("utf-8", "replace")).hexdigest()


def _write(folder, name, text):
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


def _number(value):
    return int(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value == value \
        and abs(value) < 10 ** 12 else None


def _entries(folder=None):
    """The entries of the file, newest first; a file that is missing or not ours reads as none."""
    try:
        with open(os.path.join(folder or NOW_DIR, NOW_FILE), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError, MemoryError):
        return []
    rows = raw.get("items") if isinstance(raw, dict) else None
    out = []
    for e in rows if isinstance(rows, list) else ():
        if not isinstance(e, dict):
            continue
        cid, epg, at, offset = e.get("cid"), e.get("epg"), _number(e.get("at")), _number(e.get("offset"))
        sha, where = e.get("sha"), e.get("where")
        if not (isinstance(cid, str) and ID_RE.fullmatch(cid) and isinstance(epg, str) and (not epg or ID_RE.fullmatch(epg))
                and isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{64}", sha) and at is not None and offset is not None):
            continue
        out.append({"cid": cid, "epg": epg, "offset": max(0, offset), "at": at, "sha": sha,
                    "where": where if isinstance(where, str) and len(where) < 200 else ""})
    return out[:NOW_KEEP]


def remember(cid, epg, url, offset=0, now=None, folder=None):
    """The add-on has resolved `url` for channel `cid` (programme `epg`, "" or None for live) to start `offset` s into it:
    written down so that the stream's address tells what it is. Only a hash of the address is kept. True when written."""
    cid, epg = str(cid), "" if epg in (None, "", "null") else str(epg)
    stream = _stream(url)
    if not stream or not ID_RE.fullmatch(cid) or (epg and not ID_RE.fullmatch(epg)):
        return False
    offset = offset if isinstance(offset, (int, float)) and not isinstance(offset, bool) and offset == offset else 0
    entry = {"cid": cid, "epg": epg, "offset": int(max(0, min(offset, START_MAX))), "at": int(time.time() if now is None else now),
             "sha": _hash(stream), "where": _where(stream)}
    rows = [entry] + [e for e in _entries(folder) if e["sha"] != entry["sha"]]
    return _write(folder or NOW_DIR, NOW_FILE, json.dumps({"v": 1, "items": rows[:NOW_KEEP]}))


def recall(file, now=None, folder=None):
    """The entry (cid, epg, offset, at, ...) of the stream whose address is `file`, or None. The same address is the same
    item; with `now` an address of the same CDN folder as an entry written less than WEAK_AGE s ago is that entry too (the
    address Kodi plays is not always letter for letter the one that was resolved), the newest such entry."""
    stream = _stream(file)
    if not stream:
        return None
    rows = _entries(folder)
    digest = _hash(stream)
    for e in rows:
        if e["sha"] == digest:
            return e
    where = _where(stream)
    if now is not None and where:
        for e in rows:
            if e["where"] == where and 0 <= now - e["at"] <= WEAK_AGE:
                return e
    return None


def identify(file, now=None, folder=None):
    """(channel id, programme id or "" for live, start seconds) of a played item: the plugin path it was asked for, or the
    stream address the add-on wrote down; None when it is neither."""
    found = ref(file)
    if found:
        return found
    entry = recall(file, now, folder)
    return (entry["cid"], entry["epg"], entry["offset"]) if entry else None


# ---- start place: an archive that has begun -------------------------------------------------------

def start_place(file, now):
    """What an archive that has just begun playing as `file` was asked to start at: {"cid", "epg", "offset", "at"} or None
    when nobody asked for a place (live, from the beginning, a stream of no entry, an entry older than SEEK_FRESH s, anything
    else). `file` is the stream's address (exactly an entry's: a guess is no reason to seek) or, if the player gives the plugin
    path it was asked to open, that path with its ms_start."""
    entry = recall(file)
    if entry:
        return entry if entry["epg"] and entry["offset"] > 0 and 0 <= now - entry["at"] <= SEEK_FRESH else None
    found = ref(file)
    if found and found[1] and found[2] > 0:
        return {"cid": found[0], "epg": found[1], "offset": found[2], "at": int(now), "sha": "", "where": ""}
    return None


def seek_step(offset, pos, total):
    """What to do about the place an archive was asked to start at, `offset` s, when the player is at `pos` s of `total`:
    ("done", 0) nothing (no place was asked, or the player is there or past it), ("wait", 0) the length is not known yet,
    ("seek", seconds) seek there (not past the length: a programme that is still on is as long as it has been so far)."""
    if not offset or offset <= 0 or pos >= offset - SEEK_TOLERANCE:
        return ("done", 0)
    if total < MIN_TOTAL:
        return ("wait", 0)
    return ("seek", int(max(0, min(offset, total - 5))))


def follow(player, entry, file, sleep=None, clock=None, step=0.5):
    """Once the playback of `file` has begun: seek to the start place of `entry` (recall's), look that it landed, seek again if not
    (SEEK_ATTEMPTS times, SEEK_RETRY s apart), for at most SEEK_WAIT s. `player` has getPlayingFile, getTime, getTotalTime and
    seekTime, as Kodi's does. Returns "done" (it is there), "gone" (something else plays, or nothing) or "gave_up"."""
    sleep, clock = sleep or time.sleep, clock or time.time
    stream = _stream(file) or file
    end, last, tries = clock() + SEEK_WAIT, None, 0
    while clock() < end:
        try:
            playing = player.getPlayingFile()
            if (_stream(playing) or playing) != stream:
                return "gone"
            action, target = seek_step(entry["offset"], player.getTime(), player.getTotalTime())
            if action == "done":
                return "done"
            if action == "seek" and tries < SEEK_ATTEMPTS and (last is None or clock() - last >= SEEK_RETRY):
                player.seekTime(target)
                last, tries = clock(), tries + 1
        except RuntimeError:           # Kodi: nothing is playing (it stopped between two questions)
            return "gone"
        sleep(step)
    return "gave_up"


# ---- the ask: where the opener of an archive says it should start -------------------------------------

def split_id(videoid):
    """(channel id, programme id or "null") of the add-on's `videoid`, whatever Kodi has left after it (a query, protocol
    options): None when it does not begin with `<channel>|<programme or null>`."""
    m = ITEM_RE.match(videoid) if isinstance(videoid, str) else None
    return (m.group(1), m.group(2)) if m else None


def ask(cid, epg, offset, now=None, folder=None):
    """The opener of programme `epg` of channel `cid` starts it `offset` s in: written down for the add-on, which may not be told
    in the path (see "The ask"). Nothing for live, for the beginning, or for what is not an id. True when written."""
    cid, epg = str(cid), "" if epg in (None, "", "null") else str(epg)
    offset = _number(offset)
    if not epg or not offset or offset <= 0 or not ID_RE.fullmatch(cid) or not ID_RE.fullmatch(epg):
        return False
    record = {"cid": cid, "epg": epg, "offset": min(offset, START_MAX), "at": int(time.time() if now is None else now)}
    return _write(folder or NOW_DIR, ASK_FILE, json.dumps({"v": 1, "ask": record}))


def ask_url(url, now=None, folder=None):
    """`ask` for the plugin path `url` (what `url()` made), just before it is opened. Never raises: an ask that is not
    written leaves the add-on to what the path says."""
    try:
        found = ref(url)
        return bool(found and ask(found[0], found[1], found[2], now, folder))
    except Exception:
        return False


def _read_ask(folder=None):
    try:
        with open(os.path.join(folder or NOW_DIR, ASK_FILE), encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError, MemoryError):
        return None
    e = raw.get("ask") if isinstance(raw, dict) else None
    if not isinstance(e, dict):
        return None
    cid, epg, at, offset = e.get("cid"), e.get("epg"), _number(e.get("at")), _number(e.get("offset"))
    if not (isinstance(cid, str) and ID_RE.fullmatch(cid) and isinstance(epg, str) and ID_RE.fullmatch(epg)
            and at is not None and offset is not None and offset > 0):
        return None
    return {"cid": cid, "epg": epg, "offset": min(offset, START_MAX), "at": at}


def _forget_ask(folder=None):
    path = os.path.join(folder or NOW_DIR, ASK_FILE)
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass
    except OSError:                    # not ours to remove: an empty ask says the same
        _write(folder or NOW_DIR, ASK_FILE, json.dumps({"v": 1, "ask": None}))


def take_ask(cid, epg, now=None, folder=None):
    """(offset, state) the ask has for this item: state "used" with the offset when there is one for exactly this channel and
    programme and it is no older than ASK_FRESH s, else offset 0 and state "none" (no ask), "other" (an ask for another item,
    left alone) or "stale". An ask for this item is taken whatever its age: it is not asked again."""
    e = _read_ask(folder)
    if e is None:
        return 0, "none"
    if e["cid"] != str(cid) or e["epg"] != str(epg):
        return 0, "other"
    _forget_ask(folder)
    age = (time.time() if now is None else now) - e["at"]
    return (e["offset"], "used") if -5 <= age <= ASK_FRESH else (0, "stale")


def _positive(match):
    return min(int(match.group(1)), START_MAX) if match and int(match.group(1)) > 0 else 0


def start_of(argv, videoid, cid, epg, now=None, folder=None):
    """(offset in s, source) where the add-on is asked to start programme `epg` of channel `cid` (resolving `videoid`, with
    the process's `argv`). The first that says a place above 0 wins: "query" (argv[2], the query as Kodi should give it),
    "path" (argv[0]), "videoid" (the id string itself), "argv" (any other argument), "ask" (what the opener wrote down).
    No place: (0, "none, ask <none|other|stale>"). The ask for this item is consumed whichever source wins."""
    asked, state = take_ask(cid, epg, now, folder)
    args = [a if isinstance(a, str) else "" for a in (argv if isinstance(argv, (list, tuple)) else ())]
    where = []
    if len(args) > 2:
        where.append(("query", args[2]))
    if args:
        where.append(("path", args[0]))
    where.append(("videoid", videoid if isinstance(videoid, str) else ""))
    where += [("argv", a) for a in args[3:]]
    for source, text_ in where:
        found = _positive(START_RE.search(unquote(text_)))
        if found:
            return found, source
    return (asked, "ask") if asked else (0, "none, ask " + state)
