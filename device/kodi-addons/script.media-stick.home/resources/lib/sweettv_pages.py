"""SWEET.TV app: paginated page_cache helpers (VERSION 4, slices <= 50 items, < 512 KB).

Pure functions: ready data in -> JSON-serializable dict out, and strict validation on read.
"""
import re
from typing import Optional, Tuple

from resources.lib import sweettv_text as words

SERVICE = "sweettv"
ACCOUNT = "main"
PAGE_TTL, PAGE_MAX_AGE = 300, 6 * 3600
VERSION = 4
MAX_SLICE = 50
MAX_TEXT, MAX_ICON, MAX_COUNT = 300, 600, 100_000
ACCOUNT_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


def namespace(account=ACCOUNT) -> Optional[str]:
    """The namespace of an account; None when the account cannot be told (nothing is then kept)."""
    return f"{SERVICE}:{account}" if isinstance(account, str) and ACCOUNT_RE.fullmatch(account) else None


def catalog_key(section, genre_id=0, sort_mode_id=1, offset=0) -> Optional[str]:
    if section not in ("movies", "series", "shows", "top_search"):
        return None
    if section in ("shows", "top_search"):
        return section
    return f"{section}:{int(genre_id or 0)}:{int(sort_mode_id or 1)}:{int(offset or 0)}"


def to_value(title, items, total) -> dict:
    return {
        "v": VERSION,
        "lang": words.LANG,
        "title": str(title or "")[:200],
        "total": int(total or 0),
        "items": list(items or ()),
    }


def _int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _text(value, limit=MAX_TEXT) -> bool:
    return isinstance(value, str) and len(value) <= limit and value.isprintable()


def _item_ok(item) -> bool:
    if not isinstance(item, dict):
        return False
    title = item.get("title")
    if not _text(title, 200) or not title:
        return False
    for key in ("poster", "banner", "image_url", "preview"):
        val = item.get(key)
        if val is not None:
            if not _text(val, MAX_ICON):
                return False
            if val and not val.startswith(("http://", "https://", "special://", "/")):
                return False
    return True


def from_value(section, raw) -> Optional[Tuple[str, list, int]]:
    """(title, items, total) of a cached slice; None when invalid or over MAX_SLICE."""
    try:
        if not isinstance(raw, dict) or raw.get("v") != VERSION or raw.get("lang") != words.LANG:
            return None
        title, total, items = raw["title"], raw["total"], raw["items"]
        if not _text(title, 200) or not _int(total) or not isinstance(items, list):
            return None
        if not 0 < len(items) <= MAX_SLICE or not len(items) <= total <= MAX_COUNT:
            return None
        if not all(_item_ok(item) for item in items):
            return None
        return title, list(items), total
    except (TypeError, KeyError):
        return None
