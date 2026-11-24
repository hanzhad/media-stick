"""YouTube app, the part of the page cache that needs no Kodi: which namespace and key a view is kept under, how long it is
good for, and a listing turned into a JSON value and back (page_cache keeps JSON; an Entry is a tuple of 12 fields).
Everything here takes ready data and returns data.

  namespace   youtube:<profile id>    ("youtube:anon" for no profile): one account never sees another's pages
  key         s:<section key>         the first page of a section (the add-on's route is found at run time, so it is no key)
              r:<route>               a search (its route holds the words and the type) or a playlist opened from a card
  value       {"entries": [[kind, path, title, ...], ...], "more": "<next page route>"}

Only a first page that answered with cards is kept (youtube_app decides: never an error, an empty list or a sign-in card).
A cached page is read back strictly: a row of the wrong shape, a path that is not the add-on's, makes the whole page a miss.
"""
from typing import Optional

from resources.lib import youtube_data as data

SERVICE = "youtube"
NO_PROFILE = "anon"
SEARCH_TTL, SEARCH_MAX_AGE = 120, 3600           # s: results change faster than a section's list, and are not worth showing old
PAGE_TTL, PAGE_MAX_AGE = data.CACHE_TTL, 24 * 3600
_ROW = (("kind", str), ("path", str), ("title", str), ("channel", str), ("seconds", int), ("thumb", str), ("plot", str),
        ("views", int), ("published", int), ("live", bool), ("count", int), ("progress", float))
assert tuple(name for name, _ in _ROW) == data.Entry._fields


def namespace(profile) -> Optional[str]:
    """The namespace of a profile id ("" is no profile); None when the profile cannot be told (nothing is then kept)."""
    return None if profile is None else f"{SERVICE}:{profile or NO_PROFILE}"


def key_of(view) -> str:
    """The key a view's first page is kept under."""
    if view.key in data.SECTION_KEYS and view.key != data.SEARCH:
        return f"s:{view.key}"
    return f"r:{view.route}"


def ttl_of(view) -> int:
    return SEARCH_TTL if view.key == data.SEARCH else PAGE_TTL


def max_age_of(view) -> int:
    return SEARCH_MAX_AGE if view.key == data.SEARCH else PAGE_MAX_AGE


def warm_keys(current) -> list:
    """The sections to fetch at start-up, in order: those after the one on screen in the rail's order, then those before it.
    The one on screen is left out (the window is asking for it); search is no section to fetch."""
    keys = [k for k in data.SECTION_KEYS if k != data.SEARCH]
    if current not in keys:
        return keys
    at = keys.index(current)
    return keys[at + 1:] + keys[:at]


def to_value(listing) -> dict:
    return {"entries": [list(entry) for entry in listing.entries], "more": listing.more}


def _row_ok(row):
    if not isinstance(row, list) or len(row) != len(_ROW):
        return False
    for value, (_, kind) in zip(row, _ROW):
        if kind is float:
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        else:
            ok = isinstance(value, kind) and (kind is bool or not isinstance(value, bool))
        if not ok:
            return False
    return row[0] in (data.VIDEO, data.FOLDER) and bool(data.PATH_RE.fullmatch(row[1]))


def from_value(raw) -> Optional[data.Listing]:
    """The Listing a cached value holds; None when it is not a page this screen wrote (a damaged file is a miss)."""
    try:
        rows, more = raw["entries"], raw["more"]
        if not isinstance(rows, list) or not rows or len(rows) > data.MAX_ENTRIES or not all(map(_row_ok, rows)):
            return None
        if not isinstance(more, str) or more and not data.PATH_RE.fullmatch(more):
            return None
        return data.Listing(tuple(data.Entry(*row) for row in rows), more, "")
    except (TypeError, KeyError):
        return None
