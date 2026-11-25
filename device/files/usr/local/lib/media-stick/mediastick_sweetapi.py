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
TOP_SEARCH = "SearchService/GetTop.json"
CONFIG = "MovieService/GetConfiguration.json"
COLLECTIONS = "MovieService/GetCollections.json"
COLLECTION_INFO = "MovieService/GetCollectionInfo.json"
GENRE_MOVIES = "MovieService/GetGenreMovies.json"
MOVIE_INFO = "MovieService/GetMovieInfo.json"
MOVIE_LINK = "MovieService/GetLink.json"
EPG_RECORDS = "TvService/GetEpgRecords.json"
TIMEOUT = 8                         # s a call may take
CACHE_TTL, CACHE_MAX = 60, 64       # s an answer is kept, and how many
CONFIG_TTL = 600                    # s configuration() is cached in memory
UHD_GENRE = 57
UHD_CATEGORY = 24
SORT_MODE_IDS = (1, 2, 3, 5, 6)
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
SHOW_MARKER_RE = re.compile(
    r"(?:\s*[—\-.,:]\s*|\s+)(?:Season|Episode|Сезон|Серія|Серия|Епізод|Эпизод|Випуск|Выпуск)\s*[0-9]+\b.*$",
    re.IGNORECASE,
)
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


_CF_IMG_RE = re.compile(r"^(https?://[^/]+)/cdn-cgi/image/[^/]+/(https?://.+|.+)$")


def _hq_url(url):
    """Strip Cloudflare /cdn-cgi/image/.../ resize proxy for full-res HD hero backdrops."""
    u = https(url)
    if not u:
        return ""
    m = _CF_IMG_RE.match(u)
    if not m:
        return u
    rest = m.group(2)
    return https(rest) if rest.startswith("http") else f"{m.group(1)}/{rest.lstrip('/')}"


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
    """{channel id: channel} of a channel list ({"list": [...]}, slimmed or not) or an existing map; {} for anything else."""
    if not isinstance(raw, dict):
        return {}
    if "list" in raw:
        rows = raw.get("list")
        return {str(c["id"]): c for c in rows if isinstance(c, dict) and c.get("id") is not None} if isinstance(rows, list) else {}
    return {str(c["id"]): c for c in raw.values() if isinstance(c, dict) and c.get("id") is not None}


def _channel_list(channels):
    """Channel dicts from either raw {"list": [...]} or channel_map {cid: ch}."""
    if not isinstance(channels, dict):
        return []
    if "list" in channels:
        rows = channels.get("list")
        return [c for c in rows if isinstance(c, dict)] if isinstance(rows, list) else []
    return [c for c in channels.values() if isinstance(c, dict) and c.get("id") is not None]


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


def _is_uhd_movie(item):
    genres = item.get("genres")
    if isinstance(genres, list):
        return any(_num(g) == UHD_GENRE for g in genres)
    if isinstance(genres, str):
        return "ultra hd" in genres.casefold()
    return False


def _is_uhd_channel(item, channel=None):
    for src in (item, channel):
        if not isinstance(src, dict):
            continue
        for key in ("category", "categories"):
            cats = src.get(key)
            if isinstance(cats, list) and any(_num(c) == UHD_CATEGORY for c in cats):
                return True
    genres = item.get("genres")
    return isinstance(genres, str) and "ultra hd" in genres.casefold()


def _programme_row(item, channels, now, tr):
    epg, cid, start, stop = _id(item.get("id")), _id(item.get("sub_id")), _time(item.get("time_start")), _time(item.get("time_stop"))
    title = _clean(item.get("text"))
    if not epg or not cid or start is None or not title:
        return None
    stop = stop if stop is not None and stop > start else start
    channel = _known_channel(channels, cid)
    archive = bool(channel) and ml.archive_ok(channel, {"time_start": start}, now)
    live = start <= now < stop
    show_id = _id(item.get("tv_show_id"))
    base_title = _base_show_title(title)
    return {"kind": "programme", "id": epg, "title": title, "base_title": base_title, "show_id": show_id,
            "subtitle": "", "cid": cid, "epg": epg, "start": start, "stop": stop,
            "channel_name": _clean(channel.get("name"), 120) if channel else "", "when": when_text(start, now, tr),
            "live": live, "playable_in_archive": archive, "playable": archive or (live and channel is not None),
            "available": True, "preview": "", "image_url": https(item.get("image_url")), "repeats": 0, "more": ""}


def _other_row(item, kind, channels, quality="1080p"):
    ident, title = _id(item.get("id")), _clean(item.get("text"))
    if not ident or not title:
        return None
    channel = _known_channel(channels, ident) if kind == "channel" else None
    if quality != "unlimited":
        if kind == "movie" and _is_uhd_movie(item):
            return None
        if kind == "channel" and _is_uhd_channel(item, channel):
            return None
    name = (_clean(channel.get("name"), 120) if channel else title) if kind == "channel" else ""
    img = https(item.get("image_url"))
    if kind == "movie":
        avail_info = item.get("availability_info")
        avail = (not isinstance(avail_info, dict) or avail_info.get("available") is not False) and item.get("available") is not False
        vod_url = ml.vod_url(ident, None, 0) if avail else ""
        genres = item.get("genres") if isinstance(item.get("genres"), list) else ()
        is_series = bool(item.get("is_serial") or (item.get("seasons_count") or 0) > 0 or any(_num(g) == 1 for g in genres))
        return {"kind": "series" if is_series else kind, "id": ident, "title": title, "subtitle": _clean(item.get("subtext")),
                "cid": "", "epg": "", "start": 0, "stop": 0, "channel_name": "", "when": "",
                "live": False, "playable_in_archive": False, "playable": bool(avail and vod_url), "available": avail,
                "vod_url": vod_url, "preview": "", "image_url": img, "repeats": 0, "more": ""}
    return {"kind": kind, "id": ident, "title": title, "subtitle": _clean(item.get("subtext")),
            "cid": ident if kind == "channel" else "", "epg": "", "start": 0, "stop": 0, "channel_name": name, "when": "",
            "live": False, "playable_in_archive": False, "playable": channel is not None, "available": False, "preview": "",
            "image_url": img, "repeats": 0, "more": ""}


def _watchable(row):
    return row["live"] or row["playable_in_archive"]


def _span(row):
    """Positive duration in whole seconds when start and stop are numeric and stop > start, else 0."""
    start, stop = row.get("start"), row.get("stop")
    if isinstance(start, bool) or isinstance(stop, bool):
        return 0
    if isinstance(start, (int, float)) and isinstance(stop, (int, float)) and stop > start:
        return int(stop - start)
    return 0


def _complete(rows):
    """Airings at least 80% as long as the longest one; unchanged when no row has a positive span."""
    longest = max(_span(r) for r in rows)
    return rows if longest <= 0 else [r for r in rows if _span(r) * 5 >= longest * 4]


def _stands_for(airings, now):
    """The airing of one title that is the row: the newest complete airing that can be watched now, else the soonest to come, else the newest complete airing."""
    ready = [r for r in airings if _watchable(r)]
    if ready:
        return max(_complete(ready), key=lambda r: r["start"])
    coming = [r for r in airings if r["start"] > now]
    return min(coming, key=lambda r: r["start"]) if coming else max(_complete(airings), key=lambda r: r["start"])


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


_SEARCH_SHOWS = {}
_SEARCH_SHOWS_LOCK = threading.Lock()


def _remember_search_shows(rows, now):
    with _SEARCH_SHOWS_LOCK:
        for k in list(_SEARCH_SHOWS.keys()):
            if now - _SEARCH_SHOWS[k][0] > KNOWN_TTL:
                del _SEARCH_SHOWS[k]
        for r in rows:
            if r.get("kind") == "show_tv" and r.get("episodes"):
                _SEARCH_SHOWS[r["id"]] = (now, list(r["episodes"]))


def _group_search_programmes(programmes, now, tr_n):
    by_show, order, singles = {}, [], []
    # First pass: bucket by tv_show_id or stripped base_title
    buckets = {}
    for p in programmes:
        sid = p.get("show_id") or ""
        base = p.get("base_title") or p["title"]
        if sid:
            key = ("tv", sid)
        elif SHOW_MARKER_RE.search(p["title"]) and base != p["title"]:
            key = ("base", " ".join(base.casefold().split()))
        else:
            key = ("single", p["id"])
        buckets.setdefault(key, []).append(p)
    shows = []
    for key, grp in buckets.items():
        distinct_titles = {" ".join(r["title"].casefold().split()) for r in grp}
        if len(distinct_titles) >= 2 and (key[0] == "tv" or key[0] == "base"):
            grp_sorted = collapse(grp, now, tr_n)
            best = _stands_for(grp_sorted, now)
            base = best.get("base_title") or best["title"]
            show_key = f"tv:{key[1]}" if key[0] == "tv" else f"tv_s:{abs(hash(key[1])) % 10**9}"
            img = next((r["image_url"] for r in grp_sorted if r.get("image_url")), "")
            shows.append({
                "kind": "show_tv",
                "id": show_key,
                "show_id": key[1] if key[0] == "tv" else "",
                "title": base,
                "subtitle": f"{len(grp_sorted)} вып.",
                "cid": best["cid"],
                "epg": best["epg"],
                "start": best["start"],
                "stop": best["stop"],
                "channel_name": best["channel_name"],
                "when": best["when"],
                "live": any(r["live"] for r in grp_sorted),
                "playable_in_archive": any(r["playable_in_archive"] for r in grp_sorted),
                "playable": any(r["playable"] for r in grp_sorted),
                "available": True,
                "preview": img,
                "image_url": img,
                "repeats": len(grp_sorted) - 1,
                "more": "",
                "episodes_count": len(grp_sorted),
                "episodes": grp_sorted,
            })
        else:
            singles.extend(grp)
    return shows, collapse(singles, now, tr_n)


def normalize_search(reply, channels, now, tr=None, tr_n=None, quality="1080p"):
    """The rows of a SearchService/Search.json answer: grouped shows/series first, then programmes, channels, movies, people."""
    tr = tr or ml.text
    channels = channel_map(channels)
    found = reply.get("result") if isinstance(reply, dict) else None
    programmes, others = [], {"series": [], "channel": [], "movie": [], "person": []}
    for item in found if isinstance(found, list) else ():
        kind = KINDS.get(item.get("type")) if isinstance(item, dict) else None
        if kind == "programme":
            row = _programme_row(item, channels, now, tr)
            programmes.extend([row] if row else [])
        elif kind:
            row = _other_row(item, kind, channels, quality=quality)
            if row:
                others[row["kind"]].append(row)
    grouped_shows, single_progs = _group_search_programmes(programmes, now, tr_n)
    _remember_search_shows(grouped_shows, now)
    rows = others["series"] + grouped_shows + single_progs + others["channel"] + others["movie"] + others["person"]
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
            for item in (row.get("episodes") or (row,)):
                if item.get("epg") and item.get("cid"):
                    _known[(item["cid"], item["epg"])] = (item["start"], item["stop"], now, item.get("available") is not False)
        if len(_known) > KNOWN_MAX:
            for key in sorted(_known, key=lambda k: _known[k][2])[:len(_known) - KNOWN_MAX]:
                del _known[key]


def recall(cid, epg, now=None):
    """{"start", "stop", "available"} of a programme search() or day() returned within KNOWN_TTL s; None for any other."""
    now = time.time() if now is None else now
    with _known_lock:
        found = _known.get((str(cid), str(epg)))
    return {"start": found[0], "stop": found[1], "available": found[3]} if found and 0 <= now - found[2] <= KNOWN_TTL else None


def search(needle, channels, now=None, client=None, tr=None, tr_n=None, quality="1080p"):
    """{"ok": True, "query", "items": [row, ...], "count"}; with a needle shorter than MIN_NEEDLE characters nothing is asked
    ("short": True, no items); {"ok": False, "error", "message"} when SWEET.TV could not answer."""
    now = time.time() if now is None else now
    query = _clean(needle, MAX_NEEDLE)
    if len(query) < MIN_NEEDLE:
        return {"ok": True, "query": query, "items": [], "count": 0, "short": True}
    reply = (client or _default).post(SEARCH, {"needle": query})
    if not reply.ok:
        return _failure(reply.error, tr)
    rows = normalize_search(reply.data, channels, now, tr, tr_n, quality=quality)
    _remember(rows, now)
    return {"ok": True, "query": query, "items": rows, "count": len(rows)}


def top_search(channels, now=None, quality="1080p", client=None, tr=None, tr_n=None):
    """{"ok": True, "items": [row, ...]} from SearchService/GetTop.json, marking playable movies and hiding UHD."""
    now = time.time() if now is None else now
    reply = (client or _default).post(TOP_SEARCH, {})
    if not reply.ok:
        return _failure(reply.error, tr)
    rows = normalize_search(reply.data, channels, now, tr, tr_n, quality=quality)
    _remember(rows, now)
    return {"ok": True, "items": rows, "count": len(rows)}


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


# ---- VOD, catalog, shows & stream links -------------------------------------------------------

_config_cache = {}
_config_lock = threading.Lock()


def quality_id(quality) -> int:
    """Map quality cap string ('720p', '1080p', 'unlimited'/'4k') to Sweet.TV video_quality_id (1/2/3)."""
    if not isinstance(quality, str):
        return 2
    q = quality.strip().lower()
    if q == "720p":
        return 1
    if q in ("unlimited", "4k"):
        return 3
    return 2


def owner_of(movie) -> int:
    """Extract owner_id from external_id_pairs (preferred first, else first valid) or owners[0], else 0."""
    if not isinstance(movie, dict):
        return 0
    pairs = movie.get("external_id_pairs")
    if isinstance(pairs, list):
        for p in pairs:
            if isinstance(p, dict) and p.get("preferred") is True:
                oid = _num(p.get("owner_id"))
                if oid and oid > 0:
                    return oid
        for p in pairs:
            if isinstance(p, dict):
                oid = _num(p.get("owner_id"))
                if oid and oid > 0:
                    return oid
    owners = movie.get("owners")
    if isinstance(owners, list) and owners:
        oid = _num(owners[0])
        if oid and oid > 0:
            return oid
    return 0


def _movie_available(movie) -> bool:
    if not isinstance(movie, dict):
        return False
    avail = movie.get("availability_info")
    if isinstance(avail, dict) and avail.get("available") is False:
        return False
    return movie.get("available") is not False


def _movie_card(movie):
    mid = _num(movie.get("id"))
    if not mid or mid <= 0:
        return None
    owner_id = owner_of(movie)
    poster = https(movie.get("poster_url") or movie.get("original_poster_url"))
    banner = _hq_url(movie.get("horizontal_poster_url") or movie.get("banner_url") or movie.get("original_banner_url") or poster)
    genres = [g for g in (_num(x) for x in (movie.get("genres") or ())) if g is not None]
    imdb_raw = movie.get("rating_imdb")
    imdb = float(imdb_raw) if isinstance(imdb_raw, (int, float)) and not isinstance(imdb_raw, bool) else 0.0
    return {
        "id": mid,
        "title": _clean(movie.get("title")),
        "owner_id": owner_id,
        "poster": poster,
        "banner": banner,
        "year": _num(movie.get("year")) or 0,
        "duration": _num(movie.get("duration")) or 0,
        "imdb": imdb,
        "genres": genres,
        "vod_url": ml.vod_url(mid, None, owner_id),
        "available": True,
    }


def configuration(client=None, tr=None):
    """Fetch and normalize MovieService/GetConfiguration.json, cached in memory for CONFIG_TTL (600s)."""
    c = client or _default
    now = c._clock()
    ckey = id(c)
    with _config_lock:
        hit = _config_cache.get(ckey)
        if hit and now - hit[0] < CONFIG_TTL:
            return hit[1]
    reply = c.post(CONFIG, {})
    if not reply.ok:
        return _failure(reply.error, tr)
    raw_genres = reply.data.get("genres") if isinstance(reply.data.get("genres"), list) else ()
    genres = [{"id": _num(g.get("id")), "name": _clean(g.get("name"), 80)}
              for g in raw_genres if isinstance(g, dict) and _num(g.get("id")) is not None and _clean(g.get("name"), 80)]
    raw_modes = reply.data.get("sort_modes") if isinstance(reply.data.get("sort_modes"), list) else ()
    modes_by_id = {_num(m.get("id")): _clean(m.get("name"), 80)
                   for m in raw_modes if isinstance(m, dict) and _num(m.get("id")) in SORT_MODE_IDS}
    sort_modes = [{"id": sid, "name": modes_by_id[sid]} for sid in SORT_MODE_IDS if sid in modes_by_id]
    res = {"ok": True, "genres": genres, "sort_modes": sort_modes}
    with _config_lock:
        _config_cache[ckey] = (now, res)
    return res


def _genre_movie_ids(c, genre_id):
    reply = c.post(GENRE_MOVIES, {"genre_id": int(genre_id)})
    if not reply.ok:
        return None, reply.error
    ids = [_num(x) for x in (reply.data.get("movies") or ())]
    return [x for x in ids if x and x > 0], ""


def catalog_page(section, genre_id=0, sort_mode_id=1, offset=0, limit=30, quality="1080p", client=None, tr=None):
    """Paginated movies or series catalog from api.sweet.tv, filtering out TVOD and 4K UHD (unless unlimited)."""
    c = client or _default
    gid = int(genre_id or 0)
    if section == "series":
        base, err = _genre_movie_ids(c, 1)
        if err:
            return _failure(err, tr)
        col_reply = c.post(COLLECTIONS, {"type": 3})
        seen = set(base)
        id_list = list(base)
        if col_reply.ok:
            for col in col_reply.data.get("collection") or col_reply.data.get("collections") or ():
                if isinstance(col, dict):
                    for mid in col.get("id_list") or ():
                        n = _num(mid)
                        if n and n > 0 and n not in seen:
                            seen.add(n)
                            id_list.append(n)
        if gid > 1:
            g_ids, g_err = _genre_movie_ids(c, gid)
            if not g_err and g_ids is not None:
                allowed = set(g_ids)
                id_list = [x for x in id_list if x in allowed]
    else:
        target_gid = gid or 61
        id_list, err = _genre_movie_ids(c, target_gid)
        if err:
            return _failure(err, tr)
        if target_gid == 61:
            exclude = set()
            for ex_gid in (1, 3):
                ex_ids, ex_err = _genre_movie_ids(c, ex_gid)
                if not ex_err and ex_ids:
                    exclude.update(ex_ids)
            if exclude:
                id_list = [x for x in id_list if x not in exclude]

    if not id_list:
        return {"ok": True, "section": section, "items": [], "total": 0}
    info_reply = c.post(MOVIE_INFO, {
        "movies": id_list,
        "limit": int(limit),
        "offset": int(offset),
        "sort_mode_id": int(sort_mode_id),
        "need_extended_info": False,
    })
    if not info_reply.ok:
        return _failure(info_reply.error, tr)
    allowed_ids = set(id_list)
    items = []
    for m in info_reply.data.get("movies") or ():
        if not isinstance(m, dict) or not _movie_available(m):
            continue
        mid = _num(m.get("id"))
        if mid not in allowed_ids:
            continue
        card = _movie_card(m)
        if not card:
            continue
        if quality != "unlimited" and UHD_GENRE in card["genres"]:
            continue
        items.append(card)
    return {"ok": True, "section": section, "items": items, "total": len(id_list)}


def _base_show_title(text):
    title = _clean(text, 120)
    stripped = SHOW_MARKER_RE.sub("", title).strip()
    if stripped and stripped != title:
        return stripped
    for sep in (" — ", " - "):
        if sep in title:
            head, tail = title.split(sep, 1)
            if head and any(ch.isdigit() for ch in tail[:12]):
                return head.strip()
    if ". " in title:
        head, tail = title.split(". ", 1)
        if head and any(ch.isdigit() for ch in tail):
            return head.strip()
    return title


def shows(channels, now=None, quality="1080p", client=None, tr=None):
    """Dynamically unify GetCollections(type=7) Movie & Epg shows and playable channel EPG shows."""
    c = client or _default
    now = time.time() if now is None else now
    col_reply = c.post(COLLECTIONS, {"type": 7})
    if not col_reply.ok:
        return _failure(col_reply.error, tr)

    movie_ids, movie_seen = [], set()
    epg_col_ids, epg_seen = [], set()
    for col in col_reply.data.get("collection") or col_reply.data.get("collections") or ():
        if not isinstance(col, dict):
            continue
        ctype = col.get("type")
        if ctype == "Movie":
            for mid in col.get("id_list") or ():
                n = _num(mid)
                if n and n > 0 and n not in movie_seen:
                    movie_seen.add(n)
                    movie_ids.append(n)
        elif ctype == "Epg":
            n = _num(col.get("id"))
            if n and n > 0 and n not in epg_seen:
                epg_seen.add(n)
                epg_col_ids.append(n)

    special_ids = set(movie_ids)
    col3_reply = c.post(COLLECTIONS, {"type": 3})
    if col3_reply.ok:
        for col in col3_reply.data.get("collection") or col3_reply.data.get("collections") or ():
            if not isinstance(col, dict) or col.get("type") not in (None, "", "Movie"):
                continue
            for mid in col.get("id_list") or ():
                n = _num(mid)
                if n and n > 0 and n not in movie_seen:
                    movie_seen.add(n)
                    movie_ids.append(n)

    items = []
    seen_titles = set()

    def _add_item(item):
        key = " ".join(item["title"].casefold().split())
        if not key or key in seen_titles:
            return
        seen_titles.add(key)
        items.append(item)

    if movie_ids:
        m_reply = c.post(MOVIE_INFO, {"movies": movie_ids, "need_extended_info": False})
        if m_reply.ok:
            for m in m_reply.data.get("movies") or ():
                if not isinstance(m, dict) or not _movie_available(m):
                    continue
                card = _movie_card(m)
                if not card:
                    continue
                if quality != "unlimited" and UHD_GENRE in card["genres"]:
                    continue
                _add_item({
                    "kind": "show_vod",
                    "id": "vod:%d" % card["id"],
                    "movie_id": str(card["id"]),
                    "owner_id": card["owner_id"],
                    "title": card["title"],
                    "poster": card["poster"],
                    "banner": card["banner"],
                    "year": card["year"],
                    "imdb": card["imdb"],
                    "vod_url": card["vod_url"],
                    "special": card["id"] in special_ids,
                })

    if epg_col_ids:
        ci_reply = c.post(COLLECTION_INFO, {"id_list": epg_col_ids, "need_translations": True})
        cols = (ci_reply.data.get("collections") or ci_reply.data.get("collection") or []) if ci_reply.ok else []
        sec_ids, sec_seen = [], set()
        for col in cols if isinstance(cols, list) else ():
            if isinstance(col, dict):
                for sid in col.get("secondary_id_list") or ():
                    n = _num(sid)
                    if n and n > 0 and n not in sec_seen:
                        sec_seen.add(n)
                        sec_ids.append(n)
        rec_by_id = {}
        if sec_ids:
            er_reply = c.post(EPG_RECORDS, {"id_list": sec_ids, "image_type": 0, "need_extended_info": True})
            if er_reply.ok:
                for r in er_reply.data.get("epg_records") or er_reply.data.get("list") or ():
                    rid = _num(r.get("id")) if isinstance(r, dict) else None
                    if rid:
                        rec_by_id[rid] = r

        for col in cols if isinstance(cols, list) else ():
            if not isinstance(col, dict):
                continue
            col_id = _num(col.get("id"))
            if not col_id:
                continue
            recs = [rec_by_id[_num(sid)] for sid in (col.get("secondary_id_list") or ()) if _num(sid) in rec_by_id]
            show_ids = {_num(r.get("tv_show_id")) for r in recs if _num(r.get("tv_show_id"))}
            if len(show_ids) <= 1:
                ch_ids = sorted({str(_num(r.get("channel_id"))) for r in recs if _num(r.get("channel_id"))})
                col_posters = [p for p in (col.get("posters") or ()) if isinstance(p, dict)]
                poster_from_list = next((https(p.get("original_poster_url") or p.get("poster_url")) for p in col_posters if p.get("original_poster_url") or p.get("poster_url")), "")
                horiz_from_list = next((https(p.get("original_poster_url") or p.get("poster_url")) for p in col_posters if p.get("orientation") == "Horizontal" and (p.get("original_poster_url") or p.get("poster_url"))), "")
                poster = https(col.get("poster_url")) or poster_from_list or next((https(r.get("image_url")) for r in recs if r.get("image_url")), "")
                banner = _hq_url(col.get("horizontal_poster_url") or col.get("banner_url")) or _hq_url(horiz_from_list) or _hq_url(next(
                    (r.get("preview_url_ext") for r in recs if r.get("preview_url_ext")), ""))
                _add_item({
                    "kind": "show_epg",
                    "id": "epg:%d" % col_id,
                    "collection_id": str(col_id),
                    "channel_ids": ch_ids,
                    "curated_epg_ids": [str(_num(r.get("id"))) for r in recs if _num(r.get("id"))],
                    "title": _clean(col.get("title"), 120),
                    "poster": poster,
                    "banner": banner,
                    "special": False,
                })
            else:
                grouped = {}
                for r in recs:
                    sid = _num(r.get("tv_show_id")) or 0
                    base = _base_show_title(r.get("text"))
                    gkey = ("id", sid) if sid else ("title", base.casefold())
                    grouped.setdefault(gkey, []).append(r)
                for gkey, grecs in grouped.items():
                    base = _base_show_title(grecs[0].get("text"))
                    sid = gkey[1] if gkey[0] == "id" else ""
                    ch_ids = sorted({str(_num(r.get("channel_id"))) for r in grecs if _num(r.get("channel_id"))})
                    poster = next((https(r.get("image_url")) for r in grecs if r.get("image_url")), "")
                    banner = _hq_url(next((r.get("preview_url_ext") for r in grecs if r.get("preview_url_ext")), ""))
                    _add_item({
                        "kind": "show_tv",
                        "id": "tv:%s" % (sid or col_id),
                        "show_id": str(sid),
                        "channel_ids": ch_ids,
                        "curated_epg_ids": [str(_num(r.get("id"))) for r in grecs if _num(r.get("id"))],
                        "title": base,
                        "poster": poster,
                        "banner": banner,
                        "special": False,
                    })

    for ch in _channel_list(channels):
        if ch.get("available") is False:
            continue
        cid = _id(ch.get("id"))
        for p in ch.get("epg") if isinstance(ch.get("epg"), list) else ():
            if not isinstance(p, dict):
                continue
            sid = _num(p.get("tv_show_id"))
            if not sid:
                continue
            start, stop = _time(p.get("time_start")), _time(p.get("time_stop"))
            if start is None:
                continue
            live = stop is not None and start <= now < stop
            if not (live or ml.archive_ok(ch, p, now)):
                continue
            title = _base_show_title(p.get("text"))
            _add_item({
                "kind": "show_tv",
                "id": "tv:%d" % sid,
                "show_id": str(sid),
                "channel_ids": [cid] if cid else [],
                "curated_epg_ids": [],
                "title": title,
                "poster": https(p.get("image_url")),
                "banner": _hq_url(p.get("preview_url_ext") or p.get("preview_url")),
                "special": False,
            })
    return {"ok": True, "items": items}


def _fav_set(favs):
    if isinstance(favs, dict) and isinstance(favs.get("items"), dict):
        return set(favs["items"].keys())
    if isinstance(favs, (set, list, tuple)):
        return set(favs)
    return set()


def _local_resume(local, key):
    if not isinstance(local, dict) or not isinstance(local.get("items"), dict):
        return 0, False
    e = local["items"].get(key)
    if not isinstance(e, dict):
        return 0, False
    done = e.get("done") is True
    pos = _num(e.get("pos")) or 0
    return (0 if done else max(0, pos)), done


def _vod_resume(local, movie_id, episode_id=None):
    key = "sw:vod:%s|%s" % (movie_id, episode_id) if episode_id else "sw:vod:%s" % movie_id
    return _local_resume(local, key)


def vod_detail(movie_id, local=None, favs=None, client=None, tr=None):
    """Detailed VOD movie/series metadata with seasons/episodes, local resume/watched, and local favourites."""
    c = client or _default
    if isinstance(movie_id, str) and movie_id.startswith("vod:"):
        movie_id = movie_id[4:]
    mid = _num(movie_id)
    if not mid or mid <= 0:
        return _failure("format", tr)
    reply = c.post(MOVIE_INFO, {"movies": [mid], "need_extended_info": True})
    if not reply.ok:
        return _failure(reply.error, tr)
    movies = reply.data.get("movies") or ()
    movie = movies[0] if isinstance(movies, list) and movies and isinstance(movies[0], dict) else None
    if not movie:
        return _failure("service", tr)
    card = _movie_card(movie)
    if not card:
        return _failure("format", tr)
    fav_keys = _fav_set(favs)
    is_fav = ("show:vod:%d" % mid) in fav_keys or ("vod:%d" % mid) in fav_keys
    m_resume, m_watched = _vod_resume(local, mid)
    seasons = []
    for s in movie.get("seasons") if isinstance(movie.get("seasons"), list) else ():
        if not isinstance(s, dict):
            continue
        s_owner = _num(s.get("owner_id")) or card["owner_id"]
        eps = []
        for ep in s.get("episodes") if isinstance(s.get("episodes"), list) else ():
            if not isinstance(ep, dict) or ep.get("available") is False:
                continue
            eid = _num(ep.get("id"))
            if not eid:
                continue
            ep_res, ep_done = _vod_resume(local, mid, eid)
            eps.append({
                "id": eid,
                "episode_id": eid,
                "number": _num(ep.get("number")) or 0,
                "title": _clean(ep.get("title"), 120),
                "duration": _num(ep.get("duration")) or 0,
                "preview": https(ep.get("preview_url") or ep.get("image_url")),
                "owner_id": s_owner,
                "vod_url": ml.vod_url(mid, eid, s_owner),
                "resume": ep_res,
                "watched": ep_done,
            })
        seasons.append({
            "id": _num(s.get("id")) or 0,
            "title": _clean(s.get("title"), 120),
            "owner_id": s_owner,
            "episodes": eps,
        })
    return {
        "ok": True,
        "id": "vod:%d" % mid,
        "movie_id": str(mid),
        "title": card["title"],
        "poster": card["poster"],
        "banner": card["banner"],
        "year": card["year"],
        "duration": card["duration"],
        "imdb": card["imdb"],
        "owner_id": card["owner_id"],
        "favourite": is_fav,
        "resume": m_resume,
        "watched": m_watched,
        "vod_url": card["vod_url"],
        "seasons": seasons,
    }


def show_detail(show_key, channels, now=None, local=None, favs=None, client=None, tr=None):
    """Detail for show_key ('vod:<id>', 'epg:<col_id>', or 'tv:<show_id>')."""
    if not isinstance(show_key, str):
        return _failure("format", tr)
    if show_key.startswith("vod:"):
        return vod_detail(show_key[4:], local=local, favs=favs, client=client, tr=tr)
    c = client or _default
    now = time.time() if now is None else now
    fav_keys = _fav_set(favs)
    curated_ids = []
    curated_set = set()
    recs = []
    title = ""
    if show_key.startswith("epg:"):
        col_id = _num(show_key[4:])
        if not col_id:
            return _failure("format", tr)
        ci = c.post(COLLECTION_INFO, {"id_list": [col_id], "need_translations": True})
        if ci.ok:
            cols = ci.data.get("collections") or ci.data.get("collection") or []
            if isinstance(cols, list) and cols and isinstance(cols[0], dict):
                title = _clean(cols[0].get("title"), 120)
                curated_ids = [_num(x) for x in (cols[0].get("secondary_id_list") or ()) if _num(x)]
                curated_set = set(curated_ids)
        if curated_ids:
            er = c.post(EPG_RECORDS, {"id_list": curated_ids, "image_type": 0, "need_extended_info": True})
            if er.ok:
                recs = [r for r in (er.data.get("epg_records") or er.data.get("list") or ()) if isinstance(r, dict)]
    elif show_key.startswith(("tv:", "tv_s:")):
        if show_key.startswith("tv:"):
            target_sid = _num(show_key[3:])
            if not target_sid:
                return _failure("format", tr)
            for ch in _channel_list(channels):
                for p in ch.get("epg") if isinstance(ch.get("epg"), list) else ():
                    if isinstance(p, dict) and _num(p.get("tv_show_id")) == target_sid:
                        recs.append({**p, "channel_id": ch.get("id")})
                        if not title:
                            title = _base_show_title(p.get("text"))
        with _SEARCH_SHOWS_LOCK:
            cached_eps = _SEARCH_SHOWS.get(show_key)
            cached_list = list(cached_eps[1]) if cached_eps else []
        seen_epg = {_id(r.get("id")) for r in recs}
        for ep in cached_list:
            if ep["epg"] not in seen_epg:
                seen_epg.add(ep["epg"])
                recs.append({"id": ep["epg"], "channel_id": ep["cid"], "text": ep["title"],
                             "time_start": ep["start"], "time_stop": ep["stop"],
                             "image_url": ep.get("image_url", ""), "available": ep.get("available", True)})
                if not title:
                    title = ep.get("base_title") or _base_show_title(ep["title"])
    else:
        return _failure("format", tr)

    ch_map = channel_map(channels)
    airings = []
    for r in recs:
        epg = _id(r.get("id"))
        cid = _id(r.get("channel_id"))
        start, stop = _time(r.get("time_start")), _time(r.get("time_stop"))
        if not epg or not cid or start is None or stop is None or stop <= start:
            continue
        ch = _known_channel(ch_map, cid)
        ep_res, ep_done = _local_resume(local, "sw:%s|%s" % (cid, epg))
        airings.append({
            "epg": epg,
            "cid": cid,
            "title": _clean(r.get("text"), 120),
            "start": start,
            "stop": stop,
            "duration": int(stop - start),
            "when": when_text(start, now, tr),
            "channel_name": _clean(ch.get("name"), 120) if ch else "",
            "preview": https(r.get("preview_url_ext")) or https(r.get("preview_url")) or https(r.get("image_url")),
            "curated": _num(epg) in curated_set,
            "available": r.get("available") is not False,
            "playable": bool(ch) and (start <= now < stop or ml.archive_ok(ch, r, now)),
            "resume": ep_res,
            "watched": ep_done,
            "url": ml.url(cid, epg, 0),
        })
    grouped = {}
    for a in airings:
        grouped.setdefault(" ".join(a["title"].casefold().split()), []).append(a)
    episodes = []
    for g in grouped.values():
        curated_g = [x for x in g if x["curated"]]
        pool = curated_g if curated_g else g
        episodes.append(max(_complete(pool), key=lambda x: x["start"]))
    episodes.sort(key=lambda x: -x["start"])
    _remember(episodes, now)
    return {
        "ok": True,
        "id": show_key,
        "title": title,
        "favourite": ("show:" + show_key) in fav_keys,
        "episodes": episodes,
    }


def vod_link(movie_id, episode_id=None, owner_id=0, quality="1080p", client=None, tr=None):
    """Resolve playable VOD stream URL (hls/mpd) and optional Widevine license URL via MovieService/GetLink.json."""
    c = client or _default
    mid = _num(movie_id)
    if not mid or mid <= 0:
        return _failure("format", tr)
    ep_id = _num(episode_id)
    oid = _num(owner_id) or 0
    title = ""
    duration = 0

    if not oid or ep_id is None:
        info = c.post(MOVIE_INFO, {"movies": [mid], "need_extended_info": True})
        if info.ok:
            movies = info.data.get("movies") or ()
            movie = movies[0] if isinstance(movies, list) and movies and isinstance(movies[0], dict) else None
            if movie:
                title = _clean(movie.get("title"), 120)
                duration = _num(movie.get("duration")) or 0
                if not oid:
                    oid = owner_of(movie)
                seasons = movie.get("seasons") if isinstance(movie.get("seasons"), list) else ()
                if seasons and ep_id is None:
                    for s in seasons:
                        if not isinstance(s, dict):
                            continue
                        for ep in s.get("episodes") if isinstance(s.get("episodes"), list) else ():
                            if isinstance(ep, dict) and ep.get("available") is not False and _num(ep.get("id")):
                                ep_id = _num(ep.get("id"))
                                oid = _num(s.get("owner_id")) or oid
                                duration = _num(ep.get("duration")) or duration
                                break
                        if ep_id is not None:
                            break

    body = {
        "movie_id": int(mid),
        "owner_id": int(oid),
        "video_quality_id": quality_id(quality),
        "audio_track": -1,
        "preferred_link_type": 0,
        "subtitle": "all",
    }
    if ep_id:
        body["episode_id"] = int(ep_id)

    reply = c.post(MOVIE_LINK, body)
    if not reply.ok:
        return _failure(reply.error, tr)

    hs = reply.data.get("http_stream") if isinstance(reply.data.get("http_stream"), dict) else {}
    host = hs.get("host", {}).get("address") if isinstance(hs.get("host"), dict) else ""
    path = str(hs.get("url") or "")
    if path.startswith(("http://", "https://")):
        stream_url = path
    elif host and path:
        stream_url = "https://%s%s" % (host, path if path.startswith("/") else "/" + path)
    else:
        return _failure("service", tr)

    scheme = str(reply.data.get("scheme") or "").upper()
    protocol = "mpd" if ("DASH" in scheme or ".mpd" in stream_url.lower()) else "hls"
    return {
        "ok": True,
        "url": stream_url,
        "protocol": protocol,
        "license_url": str(reply.data.get("license_url") or ""),
        "duration": duration,
        "title": title,
    }
