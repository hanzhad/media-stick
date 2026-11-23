"""YouTube app: the section the screen was left on and the last search, in a small JSON file in the add-on's
userdata (written whole and renamed into place). Pure apart from load_state/save_state."""
import json
import os
import tempfile

from resources.lib import youtube_data as data


def normalize_state(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    section = raw.get("section")
    return {"section": section if section in data.SECTION_KEYS else data.DEFAULT_SECTION,
            "query": data.clean_query(raw.get("query"))}


def remember_section(state, key):
    return normalize_state({**state, "section": key})


def record_query(state, text):
    return normalize_state({**state, "section": data.SEARCH, "query": text})


def load_state(path) -> dict:
    try:
        with open(path, encoding="utf-8") as f:
            return normalize_state(json.load(f))
    except (OSError, ValueError):
        return normalize_state({})


def save_state(path, state) -> bool:
    """Write the whole file and rename it into place, so a power cut leaves the old one or the new one."""
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(normalize_state(state), f)
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
