"""SWEET.TV app, the part that needs no Kodi: reading the plugin's channel list, categories, what is on
now and next, what the window shows. Everything here takes ready data and returns data.

The plugin plugin.video.sweettv (0.1.13) saves the answer of TvService/GetChannels.json, unchanged, as
special://temp/channelList.json every 15 minutes once it is logged in (it asks for the 10 programmes before now
and the 100 after). What is read from it:

  status                       "OK"
  list[]                       id, name, number, icon_v2_url (icon_url), category[] (ids), catchup,
                               catchup_duration (days), available, epg[]
  list[].epg[]                 id, time_start, time_stop (seconds), text, available, description
  categories[]                 id, caption

Of these the plugin's own code uses everything but `number` and `description`; those two are read when
present and everything is optional here: a missing or odd field never raises, a bad channel is skipped.
"""
import math
import os
import re
import time
from typing import NamedTuple, Optional, Tuple

PLUGIN_ID = "plugin.video.sweettv"
PLAY_URL = "plugin://plugin.video.sweettv/playvid/{cid}|{epg}"    # live: epg is "null"; an archived programme: its epg id
HIDDEN_CATEGORY = 1000          # the plugin's own playlist export leaves this one out too

ALL, RECENT, FAVOURITES = "all", "recent", "fav"
SEARCH = "search"               # the rail's entry that asks for words and shows what SWEET.TV finds (sweettv_find)
SHOWS, FILMS, GENRES = "shows", "films", "genres"    # the rail's entries of what the carousel holds besides channels, and the heading of the genres
MAIN_GROUP, SECTION_GROUP, HEADING_GROUP, GENRE_GROUP = "main", "sections", "heading", "genres"   # the rail's kinds of entries
RECENT_NAME, FAVOURITES_NAME, ALL_NAME = "Continue", "Favourites", "All"    # msgids (sweettv_text): the menu's names of the channel lists
SHOWS_NAME, FILMS_NAME, GENRES_NAME, SEARCH_NAME = "Shows and series", "Films", "Genres", "Search"
DATA, SIGNIN, EMPTY = "data", "signin", "empty"      # what the window shows

KEEP_PAST = 2 * 3600            # s of finished programmes kept on a channel without a catch-up archive
MAX_PAST, MAX_AHEAD = 10, 30    # finished programmes kept (the service sends 10), and current plus coming ones
MAX_PROGRAMMES = MAX_PAST + MAX_AHEAD
MAX_SPAN = 2 * 86400            # a programme longer than this is a data error
DEFAULT_DAYS, MAX_DAYS = 1, 30  # days of archive when a catch-up channel does not say how many
STALE_AFTER = 2 * 3600          # s: the plugin writes every 15 minutes, so a file this old is not being kept up
BAR_STEPS = 20                  # progress bars are sweettv-bar-00..20.png (card) and sweettv-pbar-00..20.png (preview)
POLL_EMPTY, POLL_DATA = 3, 60   # s between looks while a message is shown / while channels are shown
MAX_DIGITS, DIGIT_WAIT = 4, 1.2  # channel number typed on the remote; s of quiet before it is used
REMOTE_0 = 58                   # Kodi's ACTION_REMOTE_0..9
KEY_ASCII = 0xF000              # Kodi's button code of a plain key is this plus its ASCII code
ID_RE = re.compile(r"[0-9]{1,12}")


class Programme(NamedTuple):
    start: int
    stop: int
    title: str
    epg_id: str
    available: bool
    desc: str


class Channel(NamedTuple):
    cid: str
    name: str
    number: int                 # 0: none
    logo: str
    cats: Tuple[str, ...]
    catchup: bool
    epg: Tuple[Programme, ...]
    days: int = 0               # days of archive behind a catch-up channel; 0: no archive
    fast: bool = False          # 24/7 FAST marathon channel (is_fast_channel)


class Catalog(NamedTuple):
    channels: Tuple[Channel, ...]                 # in display order
    categories: Tuple[Tuple[str, str], ...]       # (key, name) of the categories that have channels
    skipped: int                                  # channels left out as unusable
    error: str = ""                               # "service" (status is not OK), "format" (no channel list), or ""


class RailEntry(NamedTuple):
    key: str
    name: str
    count: Optional[int]        # None: not counted yet (the shows and the films are counted when their lists have been made); a heading has none
    group: str = GENRE_GROUP

    @property
    def focusable(self) -> bool:
        """A heading only names the entries under it: the cursor never rests on it."""
        return self.group != HEADING_GROUP

    @property
    def msgid(self) -> bool:
        """Whether `name` is our own English text, to be said through sweettv_text.tr (a genre's name is SWEET.TV's, already in
        the account's language)."""
        return self.group != GENRE_GROUP


EMPTY_CATALOG = Catalog((), (), 0)
SERVICE_ERROR, FORMAT_ERROR = Catalog((), (), 0, "service"), Catalog((), (), 0, "format")


# ---- reading values --------------------------------------------------------------------------

def as_int(value) -> Optional[int]:
    """An int from an int, a whole float or a string of digits; None for anything else (a bool too)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if math.isfinite(value) and value == int(value) else None
    if isinstance(value, str) and re.fullmatch(r"\s*-?[0-9]{1,18}\s*", value):
        return int(value)
    return None


def as_time(value) -> Optional[int]:
    """Unix seconds from a time field; milliseconds are accepted, anything outside 2001..5138 is not a time."""
    n = as_int(value)
    if n is None:
        return None
    if n > 10 ** 11:
        n //= 1000
    return n if 10 ** 9 <= n < 10 ** 11 else None


def clean_text(value, limit=200) -> str:
    """Text for a Kodi label: one line, no control characters, no [B] / [COLOR] markup, cut to `limit`."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    text = "".join(c if c.isprintable() else " " for c in str(value))
    return " ".join(text.replace("[", "(").replace("]", ")").split())[:limit]


def logo_of(*values) -> str:
    """The first usable picture address: a web address, or a local path (the demo's logos)."""
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text.startswith(("http://", "https://", "special://")) or os.path.isabs(text):
                return text
    return ""


# ---- the channel list ------------------------------------------------------------------------

def parse_programme(raw) -> Optional[Programme]:
    if not isinstance(raw, dict):
        return None
    start, stop = as_time(raw.get("time_start")), as_time(raw.get("time_stop"))
    if start is None or stop is None or not 0 < stop - start <= MAX_SPAN:
        return None
    epg_id = as_int(raw.get("id"))
    return Programme(start, stop, clean_text(raw.get("text"), 120) or "Programme",
                     str(epg_id) if epg_id is not None and epg_id > 0 else "",
                     raw.get("available") is not False,
                     clean_text(raw.get("description") or raw.get("text_description"), 300))


def parse_epg(raw, now, days=0) -> Tuple[Programme, ...]:
    """The programmes of a channel in time order: no duplicates, the last MAX_PAST finished ones (only those
    inside the archive when the channel has one, else the last two hours), then the current and coming ones."""
    if not isinstance(raw, list):
        return ()
    oldest = now - max(KEEP_PAST, days * 86400)
    found, seen = [], set()
    for item in raw:
        programme = parse_programme(item)
        if programme and programme.stop > oldest and (programme.start, programme.stop) not in seen:
            seen.add((programme.start, programme.stop))
            found.append(programme)
    found.sort(key=lambda p: (p.start, p.stop))
    past = [p for p in found if p.stop <= now]
    ahead = [p for p in found if p.stop > now]
    return tuple(past[-MAX_PAST:] + ahead[:MAX_AHEAD])


def parse_channel(raw, now) -> Optional[Channel]:
    """One channel, or None when it cannot be played (no usable id) or the account may not watch it."""
    if not isinstance(raw, dict) or raw.get("available") is False:
        return None
    cid = as_int(raw.get("id"))
    if cid is None or cid <= 0:
        return None
    number = as_int(raw.get("number"))
    cats = raw.get("category")
    keys = (as_int(c) for c in cats) if isinstance(cats, list) else ()
    catchup = bool(raw.get("catchup"))
    days = as_int(raw.get("catchup_duration")) if catchup else 0
    days = min(days, MAX_DAYS) if days and days > 0 else DEFAULT_DAYS if catchup else 0
    return Channel(str(cid), clean_text(raw.get("name"), 80) or f"Channel {cid}",
                   number if number and number > 0 else 0,
                   logo_of(raw.get("icon_v2_url"), raw.get("icon_url")),
                   tuple(dict.fromkeys(str(k) for k in keys if k is not None)),
                   catchup, parse_epg(raw.get("epg"), now, days), days, bool(raw.get("is_fast_channel")))


def parse_catalog(raw, now) -> Catalog:
    """GetChannels.json as the plugin saved it -> the channels in display order (numbered first, by number;
    the rest in the order the service sent them) and the categories that have any. Never raises."""
    if not isinstance(raw, dict) or not isinstance(raw.get("list"), list):
        return FORMAT_ERROR
    if isinstance(raw.get("status"), str) and raw["status"] != "OK":
        return SERVICE_ERROR
    channels, seen, skipped = [], set(), 0
    for item in raw["list"]:
        try:
            channel = parse_channel(item, now)
        except (TypeError, ValueError, AttributeError, OverflowError):
            channel = None
        if channel is None or channel.cid in seen:
            skipped += 1
            continue
        seen.add(channel.cid)
        channels.append(channel)
    channels.sort(key=lambda c: (c.number == 0, c.number))
    used = {k for c in channels for k in c.cats}
    categories, known = [], set()
    for item in raw.get("categories") if isinstance(raw.get("categories"), list) else ():
        cat = as_int(item.get("id")) if isinstance(item, dict) else None
        name = clean_text(item.get("caption") or item.get("name"), 40) if isinstance(item, dict) else ""
        if cat is None or cat == HIDDEN_CATEGORY or not name or str(cat) in known or str(cat) not in used:
            continue
        known.add(str(cat))
        categories.append((f"c:{cat}", name))
    return Catalog(tuple(channels), tuple(categories), skipped)


# ---- what is on ------------------------------------------------------------------------------

def now_next(channel, now):
    """(on now, on next) as Programmes or None. In a gap there is no "now" and "next" is the coming one."""
    current = following = None
    for p in channel.epg:
        if p.start <= now < p.stop:
            current = p
        elif p.start > now:
            following = p
            break
    return current, following


def progress_step(programme, now) -> int:
    """How far through `programme` it is, in BAR_STEPS steps."""
    if programme is None or programme.stop <= programme.start:
        return 0
    fraction = (now - programme.start) / (programme.stop - programme.start)
    return max(0, min(BAR_STEPS, round(fraction * BAR_STEPS)))


def bar_name(step, wide=False) -> str:
    """The progress picture for `step`: the thin one of a card, or the long one of the preview."""
    return f"sweettv-{'pbar' if wide else 'bar'}-{max(0, min(BAR_STEPS, int(step))):02d}.png"


def hhmm(ts) -> str:
    return time.strftime("%H:%M", time.localtime(ts))


def span(start, stop) -> str:
    return f"{hhmm(start)} – {hhmm(stop)}"


def time_range(programme) -> str:
    return span(programme.start, programme.stop)


def play_url(cid, epg_id=None) -> str:
    """What Player.Open takes: live is `<cid>|null`, an archived programme `<cid>|<epg id>`. "" when unsafe."""
    cid = str(cid)
    epg = "null" if epg_id is None else str(epg_id)
    if not ID_RE.fullmatch(cid) or not (epg == "null" or ID_RE.fullmatch(epg)):
        return ""
    return PLAY_URL.format(cid=cid, epg=epg)


# ---- what the window shows -------------------------------------------------------------------

def view_mode(signed_in, catalog) -> str:
    if not signed_in:
        return SIGNIN
    return DATA if catalog and catalog.channels else EMPTY


def is_stale(mtime, now) -> bool:
    return mtime is not None and now - mtime > STALE_AFTER


def poll_interval(showing_data) -> int:
    """Seconds until the file is looked at again. Never below POLL_EMPTY; the long wait while channels are shown."""
    return POLL_DATA if showing_data else POLL_EMPTY


def recent_ids(state) -> list:
    """The ids of the recently watched channels, the last one first (state is sweettv_state's normal form)."""
    return [entry["id"] for entry in state["recent"]]


def rail(catalog, state, counts=None) -> list:
    """The menu on the left, the entries that matter first so that nobody has to press down 25 times: Continue (what was
    watched last), Favourites, All, Search (OK asks for words, the carousel shows what SWEET.TV finds), then "Shows and series" and
    "Films" (whose cards the carousel shows instead of channels), then a heading and under it the genres of the data (SWEET.TV has about 18). The heading is not focusable (see
    next_focusable) and is left out when there are no genres. `counts` is (shows, films) once known, None until then."""
    ids = {c.cid for c in catalog.channels}
    favourites = [c for c in state["favourites"] if c in ids]
    recent = [c for c in recent_ids(state) if c in ids]
    shows, films = counts if counts else (None, None)
    out = [RailEntry(RECENT, RECENT_NAME, len(recent), MAIN_GROUP), RailEntry(FAVOURITES, FAVOURITES_NAME, len(favourites), MAIN_GROUP),
           RailEntry(ALL, ALL_NAME, len(catalog.channels), MAIN_GROUP), RailEntry(SEARCH, SEARCH_NAME, None, MAIN_GROUP),
           RailEntry(SHOWS, SHOWS_NAME, shows, SECTION_GROUP), RailEntry(FILMS, FILMS_NAME, films, SECTION_GROUP)]
    if catalog.categories:
        out.append(RailEntry(GENRES, GENRES_NAME, None, HEADING_GROUP))
    for key, name in catalog.categories:
        out.append(RailEntry(key, name, sum(1 for c in catalog.channels if key[2:] in c.cats)))
    return out


def next_focusable(entries, position, step) -> int:
    """Where the cursor of the menu goes when it lands on `position` and the key was up (-1) or down (+1): on, in that
    direction, to the first entry that can have the cursor; back the other way when there is none that way; where it is
    when nothing can."""
    for direction in (step, -step):
        i = position
        while 0 <= i < len(entries) and not entries[i].focusable:
            i += direction
        if 0 <= i < len(entries):
            return i
    return position


def channels_for(catalog, key, state) -> list:
    if key == ALL:
        return list(catalog.channels)
    if key == FAVOURITES:
        wanted = set(state["favourites"])
        return [c for c in catalog.channels if c.cid in wanted]
    if key == RECENT:
        by_id = {c.cid: c for c in catalog.channels}
        return [by_id[cid] for cid in recent_ids(state) if cid in by_id]
    if key.startswith("c:"):
        return [c for c in catalog.channels if key[2:] in c.cats]
    return []


def default_category(catalog, state) -> str:
    """What the screen opens on: the channels watched last when there are any, else everything."""
    return RECENT if channels_for(catalog, RECENT, state) else ALL


def empty_category_text(key) -> str:
    """What the empty row says, as a msgid (sweettv_text.TEXT): this module is the phone page's too and has no language."""
    if key == FAVOURITES:
        return "No favourites yet. Press the menu key on a channel to add it."
    if key == RECENT:
        return "Nothing watched yet. The channels you play show up here."
    return "No channels here."


def focus_index(channels, cid) -> int:
    for i, channel in enumerate(channels):
        if channel.cid == cid:
            return i
    return 0


# ---- the number keys -------------------------------------------------------------------------

def digit_of(action_id, button_code=0) -> Optional[int]:
    """The digit a remote or keyboard key stands for, or None."""
    if REMOTE_0 <= action_id <= REMOTE_0 + 9:
        return action_id - REMOTE_0
    if KEY_ASCII + ord("0") <= button_code <= KEY_ASCII + ord("9"):
        return button_code - KEY_ASCII - ord("0")
    return None


def push_digit(typed, digit) -> str:
    """The digits typed so far with `digit` added; a leading 0 is ignored, a fifth digit starts over."""
    if not typed and digit == 0:
        return ""
    return str(digit) if len(typed) >= MAX_DIGITS else typed + str(digit)


def channel_numbered(channels, typed) -> Optional[Channel]:
    number = as_int(typed)
    return next((c for c in channels if number and c.number == number), None)


def could_grow(channels, typed) -> bool:
    """True when more digits could still name a channel: wait for them instead of jumping at once."""
    return len(typed) < MAX_DIGITS and any(c.number != int(typed) and str(c.number).startswith(typed)
                                           for c in channels if typed)
