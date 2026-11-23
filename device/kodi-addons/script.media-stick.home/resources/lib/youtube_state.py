"""YouTube app: the section the screen was left on and the last search, in a small JSON file in the add-on's
userdata (written whole and renamed into place). Pure apart from load_state/save_state.

The state also holds what the search is for (`kind`: videos, channels, playlists, live), but only while the app is
open: the file keeps the section and the query, and the app starts on Videos every time."""
import json
import os
import tempfile

from resources.lib import youtube_data as data

PERSISTED = ("section", "query")                 # what the file keeps


def normalize_state(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    section = raw.get("section")
    kind = raw.get("kind")
    return {"section": section if section in data.SECTION_KEYS else data.DEFAULT_SECTION,
            "query": data.clean_query(raw.get("query")),
            "kind": kind if kind in data.KIND_KEYS else data.DEFAULT_KIND}


def remember_section(state, key):
    return normalize_state({**state, "section": key})


def remember_kind(state, kind):
    return normalize_state({**state, "kind": kind})


def record_query(state, text):
    """A new search: the type chosen so far stays."""
    return normalize_state({**state, "section": data.SEARCH, "query": text})


def load_state(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        return normalize_state({key: raw.get(key) for key in PERSISTED} if isinstance(raw, dict) else None)
    except (OSError, ValueError):
        return normalize_state({})


def save_state(path, state) -> bool:
    """Write the whole file and rename it into place, so a power cut leaves the old one or the new one."""
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({key: value for key, value in normalize_state(state).items() if key in PERSISTED}, f)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        return True
    except (OSError, ValueError, TypeError):
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False
