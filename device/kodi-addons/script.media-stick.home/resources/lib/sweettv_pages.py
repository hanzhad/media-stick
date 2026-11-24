"""SWEET.TV app, the part of the page cache that needs no Kodi: which namespace and key a list is kept under, how long it is
good for, and the cards of a list turned into a JSON value and back (page_cache keeps JSON; a Row is a tuple of 14 fields).
Everything here takes ready data and returns data.

  namespace   sweettv:<account>    ("sweettv:main": a stick has one SWEET.TV account; a sign-out drops "sweettv:*" and so does
                                   the window when it finds the account signed out, so another account never sees these pages)
  key         shows                the cards of the shows
              films                the cards of the films
              show:<id>            the episodes of one show
              counts               how many shows and films there are (the numbers in the menu on the left)
  value       {"v", "lang", "title", "total", "rows": [[key, title, sub, side, icon, mark, playable, future, cid, epg, start,
              stop, name, line], ...]}   (counts: {"v", "lang", "shows", "films"})

Only a list that was made from the guide and has lines is kept (sweettv_app decides: never a failure, an empty list or a
sign-in). Nothing live is kept: the address of a stream is made when a programme is played, from the two ids a row holds; what
the guide says about the time (what can be watched now, "Soon") is why a page is good for minutes (PAGE_TTL) and is shown
at all for hours (PAGE_MAX_AGE), and why a page that is older than its ttl is asked for again as soon as it is shown.
A cached page is read back strictly: a row of the wrong shape, ids that are not numbers, a text in another language, a line
too long, makes the whole page a miss. No token, cookie or stream address is ever part of a key or a value.
"""
import re
from typing import Optional, Tuple

from resources.lib import sweettv_sections as sections, sweettv_text as words

SERVICE = "sweettv"
ACCOUNT = "main"
PAGE_TTL, PAGE_MAX_AGE = 300, 6 * 3600           # s: a page is shown without asking again for 5 minutes, and not shown after 6 hours
COUNTS = "counts"
VERSION = 3                                      # 3: an episode is named in the language (С1 Э3); 2: a Row has its `line`, its titles are whole
MAX_TEXT, MAX_ICON, MAX_COUNT = 300, 600, 100_000
SHOW_ID = re.compile(r"[0-9]{1,12}|t[0-9a-f]{10}")
NUMBER = re.compile(r"[0-9]{1,20}")
ACCOUNT_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")
LIMITS = {sections.SHOWS: sections.MAX_SHOWS, sections.FILMS: sections.MAX_FILMS, sections.EPISODES: sections.MAX_EPISODES}
_ROW = (("key", str), ("title", str), ("sub", str), ("side", str), ("icon", str), ("mark", str), ("playable", bool), ("future", bool),
        ("cid", str), ("epg", str), ("start", int), ("stop", int), ("name", str), ("line", str))
assert tuple(name for name, _ in _ROW) == sections.Row._fields


def namespace(account=ACCOUNT) -> Optional[str]:
    """The namespace of an account; None when the account cannot be told (nothing is then kept)."""
    return f"{SERVICE}:{account}" if isinstance(account, str) and ACCOUNT_RE.fullmatch(account) else None


def key_of(kind, sid="") -> Optional[str]:
    """The key a list is kept under; None for a list that is not kept (a show id that is none)."""
    if kind == sections.SHOWS:
        return "shows"
    if kind == sections.FILMS:
        return "films"
    if kind == sections.EPISODES and isinstance(sid, str) and SHOW_ID.fullmatch(sid):
        return f"show:{sid}"
    return None


def to_value(title, rows, total) -> dict:
    return {"v": VERSION, "lang": words.LANG, "title": title, "total": total, "rows": [list(row) for row in rows]}


def counts_value(shows, films) -> dict:
    return {"v": VERSION, "lang": words.LANG, "shows": shows, "films": films}


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value, limit=MAX_TEXT) -> bool:
    return isinstance(value, str) and len(value) <= limit and value.isprintable()


def _row_ok(row, kind) -> bool:
    if not isinstance(row, list) or len(row) != len(_ROW):
        return False
    for value, (_, type_) in zip(row, _ROW):
        if type_ is int and not _int(value) or type_ is bool and not isinstance(value, bool) or type_ is str and not isinstance(value, str):
            return False
    key, title, sub, side, icon, mark, playable, future, cid, epg, start, stop, name, line = row
    if not all(_text(t) for t in (title, sub, side, mark, name, line)) or not _text(icon, MAX_ICON) or not title:
        return False
    if icon and not icon.startswith(("http://", "https://", "special://", "/")):
        return False
    if start < 0 or stop < start or future and playable:
        return False
    if kind == sections.SHOWS:                        # a show: its id, and nothing to play
        return bool(SHOW_ID.fullmatch(key)) and not cid and not epg and playable and not future and start == 0 and stop == 0
    return key == "" and bool(NUMBER.fullmatch(cid)) and bool(NUMBER.fullmatch(epg))


def from_value(kind, raw) -> Optional[Tuple[str, list, int]]:
    """(title, [Row, ...], how many there are) of a list kept by to_value; None when it is not a page this screen wrote."""
    try:
        if not isinstance(raw, dict) or raw.get("v") != VERSION or raw.get("lang") != words.LANG:
            return None
        title, total, rows = raw["title"], raw["total"], raw["rows"]
        if not _text(title, 200) or not _int(total) or not isinstance(rows, list):
            return None
        if not 0 < len(rows) <= LIMITS.get(kind, 0) or not len(rows) <= total <= MAX_COUNT:
            return None
        if not all(_row_ok(row, kind) for row in rows):
            return None
        return title, [sections.Row(*row) for row in rows], total
    except (TypeError, KeyError):
        return None


def counts_from_value(raw) -> Optional[Tuple[int, int]]:
    """(shows, films) of a page kept by counts_value; None for anything else."""
    try:
        if not isinstance(raw, dict) or raw.get("v") != VERSION or raw.get("lang") != words.LANG:
            return None
        shows, films = raw["shows"], raw["films"]
        if not (_int(shows) and _int(films) and 0 <= shows <= MAX_COUNT and 0 <= films <= MAX_COUNT):
            return None
        return shows, films
    except (TypeError, KeyError):
        return None
