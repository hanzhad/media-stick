"""SWEET.TV: what only SWEET.TV's own API (api.sweet.tv) knows, for the phone page and the TV screen alike. Standard library
only; nothing happens on import.

The channel list the add-on keeps (channelList.json) is a tiny window of the guide (10 programmes back, 100 ahead), so a show that
aired on Friday is not in it on Tuesday, and no search can be made from it. Two questions go to the API instead:

  search(needle, channels)      SearchService/Search.json: programmes, channels, films, people that match -> rows (see "Rows")
  day(cid, day_unix, channels)  TvService/GetChannels.json for one channel at any moment: that channel's programmes of one day
                                (a past day up to the channel's catchup_duration, a future one up to epg_days_future)
  recall(cid, epg)              the start and stop of a programme these two returned lately: what the play route checks a programme
                                that is not in the channel list's window against (the API is trusted, a number from a caller is not)

`channels` is the channel list reduced by mediastick_sweetlive.slim (or any {"list": [{id, name, catchup, catchup_duration,
epg_days_future, available}]}); channel_map() makes the lookup. Every function returns a dict and never raises: {"ok": True, ...}
or {"ok": False, "error": <code>, "message": <text for a person>}, the codes being auth (no sign-in, or SWEET.TV refuses it),
network, service, format, and for a day also unknown, bad_date, too_old, too_far. The words come out of the add-on's dictionary
(`tr`, `tr_n`: sweettv_text's, by default through mediastick_sweetlive.text), so the TV says them in the device's language.

Rows. A programme row: kind "programme", title, cid, epg, start, stop (unix s), channel_name (from the channel list, "" when the
channel is not in it), when ("Пт 20 ноя 17:00", local time, the names of the day and the month in the language), live (on now),
playable_in_archive (it has started, the channel keeps an archive and it is within catchup_duration days: the guide's own rule,
mediastick_sweetlive.archive_ok), playable (live or in the archive, on a channel of the list), repeats (how many other airings
the same title has: they are one row), more ("ещё 2 показа" or ""). One title is one row (the same text, whichever case): the airing
that stands for it is the newest one that can be watched now, else the one soonest to come, else the newest; the rows are sorted
newest first. After the programmes: channel rows (kind "channel": cid, title, playable when the channel is in the list), movie rows
(kind "movie", id, subtitle: the year and genre; not playable here: the film library is not played yet) and person rows. A day's
row: epg, title, start, stop, when, live, playable_in_archive, preview (https, preview_url_ext else preview_url, "" when there
is none), season, episode, show_id.

The calls are POSTs of JSON with the headers the add-on's helper sends and the bearer of the add-on's settings.xml (read again
for every call, never logged, never returned). A 401 reads the bearer again (the add-on's service renews it by itself) and tries
once more with a new one; it does not renew it itself. 8 s a call; an answer is kept for 60 s under the request (answers that
failed are not).
"""
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import date, timedelta
from typing import NamedTuple

import mediastick_sweetlive as ml

try:
    import mediastick_signin as signin
except ImportError:                 # a device without it: no bearer, every call says "auth"
    signin = None

API = "https://api.sweet.tv/"
SEARCH, CHANNELS = "SearchService/Search.json", "TvService/GetChannels.json"
TIMEOUT = 8                         # s a call may take
CACHE_TTL, CACHE_MAX = 60, 64       # s an answer is kept, and how many
MIN_NEEDLE, MAX_NEEDLE = 2, 100
MAX_ROWS = 60
DAY_PAGE = 30                       # programmes asked for before and after the moment (the API counts programmes, not hours)
DAY_EXTEND = 2                      # more calls, each way, when a busy day did not fit in the first
DEFAULT_FUTURE_DAYS = 3             # days of guide ahead when the channel does not say
KNOWN_MAX, KNOWN_TTL = 1000, 7200   # programmes recall() remembers, and for how many seconds
ADDON_VERSION = "0.1.13"            # the add-on's, as its x-device header says (kodi-addons.want)
HEADERS = {"user-agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
           "x-device": "1;22;0;2;" + ADDON_VERSION, "origin": "https://sweet.tv", "referer": "https://sweet.tv/",
           "content-type": "application/json", "accept": "application/json"}
ID_RE = re.compile(r"[0-9]{1,12}")
DATE_RE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")                                 # msgids (sweettv_text)
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MORE_ONE, MORE_MANY = "{n} more airing", "{n} more airings"
MESSAGES = {                        # msgids: what a person reads for each error code
    "auth": "SWEET.TV does not accept the sign-in. Sign in again.",
    "network": "SWEET.TV did not answer. Check the internet connection.",
    "service": "SWEET.TV answered with an error. Try again in a minute.",
    "format": "SWEET.TV answered in a way this device does not understand.",
    "unknown": "This channel is not in the list.",
    "bad_date": "Wrong date.",
    "too_old": "The archive of this channel does not go back that far.",
    "too_far": "The guide of this channel does not reach that far ahead.",
}


class Reply(NamedTuple):
    ok: bool
    data: dict
    error: str = ""                 # "" | auth | network | service | format


# ---- reading values ---------------------------------------------------------------------------

def _num(value):
    """An int from an int, a whole float or a string of digits (the API sends 64-bit numbers as strings); None otherwise."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value == value and abs(value) < 10 ** 15 else None
    if isinstance(value, str) and re.fullmatch(r"\s*-?[0-9]{1,15}\s*", value):
        return int(value)
    return None


def _id(value):
    n = _num(value)
    return str(n) if n is not None and 0 < n < 10 ** 12 else ""


def _time(value):
    n = _num(value)
    n = ml._seconds(n) if n is not None else None
    return n if n is not None and 10 ** 9 <= n < 10 ** 11 else None


def _clean(value, limit=200):
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join("".join(c if c.isprintable() else " " for c in str(value)).split())[:limit]


def https(url):
    """A picture address as https; "" when it is not a web address."""
    if not isinstance(url, str):
        return ""
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    if url.startswith("http://"):
        return "https://" + url[7:]
    return url if url.startswith("https://") else ""


def channel_map(raw):
    """{channel id: channel} of a channel list ({"list": [...]}, slimmed or not); {} for anything else."""
    rows = raw.get("list") if isinstance(raw, dict) else None
    return {str(c["id"]): c for c in rows if isinstance(c, dict) and c.get("id") is not None} if isinstance(rows, list) else {}


def when_text(ts, now=None, tr=None):
    """"Пт 20 ноя 17:00": the day of the week, the day, the month and the time, in the local time of the device."""
    tr = tr or ml.text
    t = time.localtime(ts)
    return "%s %d %s %02d:%02d" % (tr(WEEKDAYS[t.tm_wday]), t.tm_mday, tr(MONTHS[t.tm_mon - 1]), t.tm_hour, t.tm_min)


def parse_date(text):
    """A `date` of "YYYY-MM-DD"; None for anything else."""
    m = DATE_RE.fullmatch(text) if isinstance(text, str) else None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


def noon(day):
    """A moment of the local day `day` that no change of the clock moves out of it: its noon, as unix seconds."""
    return int(time.mktime((day.year, day.month, day.day, 12, 0, 0, 0, 0, -1)))


def _midnight(day):
    return int(time.mktime((day.year, day.month, day.day, 0, 0, 0, 0, 0, -1)))


# ---- search -----------------------------------------------------------------------------------

def _known_channel(channels, cid):
    return channels.get(cid) if isinstance(channels, dict) else None


def _programme_row(item, channels, now, tr):
    epg, cid, start, stop = _id(item.get("id")), _id(item.get("sub_id")), _time(item.get("time_start")), _time(item.get("time_stop"))
    title = _clean(item.get("text"))
    if not epg or not cid or start is None or not title:
        return None
    stop = stop if stop is not None and stop > start else start
    channel = _known_channel(channels, cid)
    archive = bool(channel) and ml.archive_ok(channel, {"time_start": start}, now)
    live = start <= now < stop
    return {"kind": "programme", "id": epg, "title": title, "subtitle": "", "cid": cid, "epg": epg, "start": start, "stop": stop,
            "channel_name": _clean(channel.get("name"), 120) if channel else "", "when": when_text(start, now, tr),
            "live": live, "playable_in_archive": archive, "playable": archive or (live and channel is not None),
            "available": True, "preview": "", "repeats": 0, "more": ""}


def _other_row(item, kind, channels):
    ident, title = _id(item.get("id")), _clean(item.get("text"))
    if not ident or not title:
        return None
    channel = _known_channel(channels, ident) if kind == "channel" else None
    name = (_clean(channel.get("name"), 120) if channel else title) if kind == "channel" else ""
    return {"kind": kind, "id": ident, "title": title, "subtitle": _clean(item.get("subtext")),
            "cid": ident if kind == "channel" else "", "epg": "", "start": 0, "stop": 0, "channel_name": name, "when": "",
            "live": False, "playable_in_archive": False, "playable": channel is not None, "available": False, "preview": "", "repeats": 0,
            "more": ""}


def _watchable(row):
    return row["live"] or row["playable_in_archive"]


def _stands_for(airings, now):
    """The airing of one title that is the row: the newest that can be watched now, else the soonest to come, else the newest."""
    ready = [r for r in airings if _watchable(r)]
    if ready:
        return max(ready, key=lambda r: r["start"])
    coming = [r for r in airings if r["start"] > now]
    return min(coming, key=lambda r: r["start"]) if coming else max(airings, key=lambda r: r["start"])


def collapse(rows, now, tr_n=None):
    """The programme rows with the airings of one title made one (see the module's doc), newest first. A new list."""
    tr_n = tr_n or ml.text_n
    groups = {}
    for row in rows:
        groups.setdefault(" ".join(row["title"].casefold().split()), []).append(row)
    out = []
    for airings in groups.values():
        row = dict(_stands_for(airings, now))
        row["repeats"] = len(airings) - 1
        row["more"] = tr_n(row["repeats"], MORE_ONE, MORE_MANY) if row["repeats"] else ""
        out.append(row)
    out.sort(key=lambda r: (-r["start"], r["title"]))
    return out


KINDS = {"EpgRecord": "programme", "Channel": "channel", "Movie": "movie", "Person": "person"}


def normalize_search(reply, channels, now, tr=None, tr_n=None):
    """The rows of a SearchService/Search.json answer: programmes (collapsed, newest first), then channels, films, people
    in the order the service gave them; at most MAX_ROWS. Odd items are left out; never raises."""
    tr = tr or ml.text
    found = reply.get("result") if isinstance(reply, dict) else None
    programmes, others = [], {"channel": [], "movie": [], "person": []}
    for item in found if isinstance(found, list) else ():
        kind = KINDS.get(item.get("type")) if isinstance(item, dict) else None
        if kind == "programme":
            row = _programme_row(item, channels, now, tr)
            programmes.extend([row] if row else [])
        elif kind:
            row = _other_row(item, kind, channels)
            others[kind].extend([row] if row else [])
    rows = collapse(programmes, now, tr_n) + others["channel"] + others["movie"] + others["person"]
    return rows[:MAX_ROWS]


# ---- a day of a channel -----------------------------------------------------------------------

def _archive_days(channel):
    days = channel.get("catchup_duration")
    if not channel.get("catchup") or channel.get("available") is False:
        return 0
    return min(days, 30) if isinstance(days, int) and not isinstance(days, bool) and days > 0 else 1


def _future_days(channel):
    days = channel.get("epg_days_future")
    return days if isinstance(days, int) and not isinstance(days, bool) and days >= 0 else DEFAULT_FUTURE_DAYS


def check_day(channel, day, now):
    """"" when the local date `day` may be asked for, else the error code: unknown (no such channel), too_old (further back than
    the channel's archive: catchup_duration days, none for a channel without one: then only today), too_far (further ahead than
    epg_days_future days)."""
    if not isinstance(channel, dict):
        return "unknown"
    today = date.fromtimestamp(now)
    if day < today - timedelta(days=_archive_days(channel)):
        return "too_old"
    return "too_far" if day > today + timedelta(days=_future_days(channel)) else ""


def day_body(cid, moment):
    return {"channels": [int(cid)], "epg_current_time": int(moment), "epg_limit_prev": DAY_PAGE, "epg_limit_next": DAY_PAGE,
            "need_epg": True, "need_list": True, "need_categories": False, "need_offsets": False, "need_hash": False,
            "need_icons": False, "need_big_icons": False}


def programmes_of(reply, cid):
    """The programme dicts of a GetChannels answer for channel `cid` (what `list[0].epg` holds); [] for anything odd."""
    rows = reply.get("list") if isinstance(reply, dict) else None
    for channel in rows if isinstance(rows, list) else ():
        if isinstance(channel, dict) and str(channel.get("id")) == str(cid):
            epg = channel.get("epg")
            return [p for p in epg if isinstance(p, dict)] if isinstance(epg, list) else []
    return []


def _day_row(p, cid, channel, now, tr):
    epg, start, stop = _id(p.get("id")), _time(p.get("time_start")), _time(p.get("time_stop"))
    if not epg or start is None or stop is None or stop <= start:
        return None
    preview = https(p.get("preview_url_ext")) or https(p.get("preview_url"))
    return {"epg": epg, "cid": str(cid), "title": _clean(p.get("text")) or "-", "start": start, "stop": stop,
            "when": when_text(start, now, tr), "live": start <= now < stop,
            "playable_in_archive": ml.archive_ok(channel, {"time_start": start, "available": p.get("available")}, now),
            "available": p.get("available") is not False, "preview": preview, "season": _num(p.get("season_number")) or 0, "episode": _num(p.get("episode_number")) or 0,
            "show_id": _id(p.get("tv_show_id"))}


def normalize_day(programmes, cid, channel, day, now, tr=None):
    """The rows of the programmes that are on during the local date `day`, in time order, each once."""
    tr = tr or ml.text
    lo, hi = _midnight(day), _midnight(day + timedelta(days=1))
    rows = {}
    for p in programmes:
        row = _day_row(p, cid, channel, now, tr)
        if row and row["stop"] > lo and row["start"] < hi:
            rows[row["epg"]] = row
    return sorted(rows.values(), key=lambda r: (r["start"], r["epg"]))


# ---- asking -----------------------------------------------------------------------------------

def bearer():
    """The add-on bearer (its settings.xml), "" when there is none. Never log it."""
    try:
        return (signin.sweettv_setting("bearer") or "") if signin else ""
    except Exception:
        return ""


def language():
    """SWEET.TV code of the device language (ru, uk, en, ...), as the add-on sends it; "ru" when it cannot be told."""
    try:
        import mediastick_lang
        return mediastick_lang.resolve(mediastick_lang.read()).sweet
    except Exception:
        return "ru"


def transport(url, headers, payload, timeout):
    """One POST: (status, body bytes); (0, b"") when nothing answered. Never raises."""
    try:
        request = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        with urllib.request.urlopen(request, timeout=timeout) as answer:
            return answer.status, answer.read(8 * 1024 * 1024)
    except urllib.error.HTTPError as e:
        return e.code, b""
    except Exception:
        return 0, b""


class Client:
    """Posts JSON to api.sweet.tv and keeps the answers for CACHE_TTL s. token, send and clock are what the tests replace."""

    def __init__(self, token=None, send=None, clock=None):
        self._token = token or bearer
        self._send = send or transport
        self._clock = clock or time.time
        self._lock = threading.Lock()
        self._cache = {}

    def _headers(self, token):
        return {**HEADERS, "accept-language": language(), "authorization": token}

    def post(self, method, body):
        """Reply(ok, data, error): the answer of `method` to `body`. Never raises."""
        key = method + "\n" + json.dumps(body, sort_keys=True)
        now = self._clock()
        with self._lock:
            hit = self._cache.get(key)
            if hit and now - hit[0] < CACHE_TTL:
                return hit[1]
        token = self._token()
        if not token:
            return Reply(False, {}, "auth")
        payload = json.dumps(body).encode("utf-8")
        status, raw = self._send(API + method, self._headers(token), payload, TIMEOUT)
        if status == 401:                  # the service of the add-on may have renewed the bearer since it was read
            fresh = self._token()
            if not fresh or fresh == token:
                return Reply(False, {}, "auth")
            status, raw = self._send(API + method, self._headers(fresh), payload, TIMEOUT)
        reply = self._reply(status, raw)
        if reply.ok:
            self._keep(key, now, reply)
        return reply

    def _keep(self, key, now, reply):
        with self._lock:
            self._cache = {k: v for k, v in self._cache.items() if now - v[0] < CACHE_TTL}
            while len(self._cache) >= CACHE_MAX:
                self._cache.pop(next(iter(self._cache)))
            self._cache[key] = (now, reply)

    @staticmethod
    def _reply(status, raw):
        if status == 0:
            return Reply(False, {}, "network")
        if status in (401, 403):
            return Reply(False, {}, "auth")
        if status != 200:
            return Reply(False, {}, "service")
        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return Reply(False, {}, "format")
        if not isinstance(data, dict):
            return Reply(False, {}, "format")
        state = data.get("status")
        return Reply(False, {}, "service") if isinstance(state, str) and state not in ("OK", "") else Reply(True, data)


_default = Client()
_known = {}
_known_lock = threading.Lock()


def _failure(code, tr):
    return {"ok": False, "error": code, "message": (tr or ml.text)(MESSAGES.get(code, MESSAGES["service"]))}


def _remember(rows, now):
    """What the play route may check a programme against: the programmes shown lately (cid, epg -> start, stop)."""
    with _known_lock:
        for row in rows:
            if row.get("kind", "programme") == "programme" and row.get("epg") and row.get("cid"):
                _known[(row["cid"], row["epg"])] = (row["start"], row["stop"], now, row.get("available") is not False)
        if len(_known) > KNOWN_MAX:
            for key in sorted(_known, key=lambda k: _known[k][2])[:len(_known) - KNOWN_MAX]:
                del _known[key]


def recall(cid, epg, now=None):
    """{"start", "stop", "available"} of a programme search() or day() returned within KNOWN_TTL s; None for any other."""
    now = time.time() if now is None else now
    with _known_lock:
        found = _known.get((str(cid), str(epg)))
    return {"start": found[0], "stop": found[1], "available": found[3]} if found and 0 <= now - found[2] <= KNOWN_TTL else None


def search(needle, channels, now=None, client=None, tr=None, tr_n=None):
    """{"ok": True, "query", "items": [row, ...], "count"}; with a needle shorter than MIN_NEEDLE characters nothing is asked
    ("short": True, no items); {"ok": False, "error", "message"} when SWEET.TV could not answer."""
    now = time.time() if now is None else now
    query = _clean(needle, MAX_NEEDLE)
    if len(query) < MIN_NEEDLE:
        return {"ok": True, "query": query, "items": [], "count": 0, "short": True}
    reply = (client or _default).post(SEARCH, {"needle": query})
    if not reply.ok:
        return _failure(reply.error, tr)
    rows = normalize_search(reply.data, channels, now, tr, tr_n)
    _remember(rows, now)
    return {"ok": True, "query": query, "items": rows, "count": len(rows)}


def _fetch(client, cid, moment, found):
    """Add the programmes around `moment` to `found` (id -> dict); the error code of the reply ("" when there is none)."""
    reply = client.post(CHANNELS, day_body(cid, moment))
    for p in programmes_of(reply.data, cid) if reply.ok else ():
        if _id(p.get("id")):
            found.setdefault(_id(p.get("id")), p)
    return reply.error


def _times(found):
    """(earliest start, latest stop) of what was found; (None, None) for nothing."""
    spans = [(_time(p.get("time_start")), _time(p.get("time_stop"))) for p in found.values()]
    spans = [(a, b) for a, b in spans if a is not None and b is not None]
    return (min(a for a, _ in spans), max(b for _, b in spans)) if spans else (None, None)


def _cover(client, cid, found, lo, hi):
    """The first call found 30 programmes either way of noon; a day with more is asked for again, from the earliest start
    back and from the latest stop on, until the day is covered or nothing new comes (DAY_EXTEND calls each way at most)."""
    for _ in range(DAY_EXTEND):
        first = _times(found)[0]
        before = len(found)
        if first is None or first <= lo or _fetch(client, cid, first - 1, found) or len(found) == before:
            break
    for _ in range(DAY_EXTEND):
        last = _times(found)[1]
        before = len(found)
        if last is None or last >= hi or _fetch(client, cid, last, found) or len(found) == before:
            break


def day(cid, day_unix, channels, now=None, client=None, tr=None):
    """{"ok": True, "cid", "name", "date" (YYYY-MM-DD), "now", "archive_days", "future_days", "items": [row, ...]}: the programmes of
    channel `cid` on the local day that holds `day_unix`; {"ok": False, "error", "message"} for a channel that is not in the list,
    a day outside what the channel keeps, or when SWEET.TV could not answer."""
    now = time.time() if now is None else now
    cid = str(cid)
    channel = _known_channel(channels, cid) if ID_RE.fullmatch(cid) else None
    if isinstance(day_unix, bool) or not isinstance(day_unix, (int, float)):
        return _failure("bad_date", tr)
    try:
        when = date.fromtimestamp(day_unix)
    except (OverflowError, OSError, ValueError):
        return _failure("bad_date", tr)
    code = check_day(channel, when, now)
    if code:
        return _failure(code, tr)
    client = client or _default
    lo, hi = _midnight(when), _midnight(when + timedelta(days=1))
    found = {}
    error = _fetch(client, cid, (lo + hi) // 2, found)
    if error:
        return _failure(error, tr)
    _cover(client, cid, found, lo, hi)
    rows = normalize_day(list(found.values()), cid, channel, when, now, tr)
    _remember(rows, now)
    return {"ok": True, "cid": cid, "name": _clean(channel.get("name"), 120), "date": when.isoformat(), "now": int(now),
            "archive_days": _archive_days(channel), "future_days": _future_days(channel), "items": rows}
