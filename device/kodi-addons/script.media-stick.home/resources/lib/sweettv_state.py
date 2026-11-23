"""SWEET.TV app: where it left off. Favourites, the channels watched last (with when), the last channel and, for
a programme watched from the archive, the place it stopped at: a small JSON file in the add-on's userdata, written
whole and renamed into place. Pure apart from load_state/save_state; the window writes only through
sweettv_writer, which does it off the UI thread.

  {"favourites": ["101", ...],
   "recent": [{"id": "105", "at": 1799990000}, ...],          the last one watched first, at most MAX_RECENT
   "last": "105",
   "resume": {"105": {"epg": "105004", "title": "Harbour Lights", "start": 1799985000, "stop": 1799990400,
                      "pos": 1500, "at": 1799990000}}}         seconds into the programme the player had reached

A state saved by an earlier version (recent as a list of ids) is read as it is.
"""
import json
import os
import tempfile

from resources.lib.sweettv_data import as_int, as_time, clean_text

MAX_RECENT, MAX_FAVOURITES, MAX_RESUME = 12, 500, 12
MIN_RESUME = 60                  # s: a programme left in its first minute is not worth coming back to
END_MARGIN = 90                  # s: ... nor one left in its last minute and a half (it was watched to the end)


def _id(value):
    n = as_int(value)
    return str(n) if n is not None and n > 0 else ""


def _ids(values, limit):
    out = []
    for value in values if isinstance(values, list) else ():
        cid = _id(value)
        if cid and cid not in out:
            out.append(cid)
    return out[:limit]


def _recent(values):
    """[{"id", "at"}], newest first as given; an entry may be a bare id (the older file format)."""
    out, seen = [], set()
    for value in values if isinstance(values, list) else ():
        raw = value if isinstance(value, dict) else {"id": value}
        cid = _id(raw.get("id"))
        if cid and cid not in seen:
            seen.add(cid)
            at = as_int(raw.get("at"))
            out.append({"id": cid, "at": at if at and at > 0 else 0})
    return out[:MAX_RECENT]


def _resume(values):
    """{channel id: {"epg", "title", "start", "stop", "pos", "at"}}: the newest MAX_RESUME entries that make sense."""
    out = []
    for key, raw in values.items() if isinstance(values, dict) else ():
        cid, raw = _id(key), raw if isinstance(raw, dict) else {}
        start, stop, pos, at = as_time(raw.get("start")), as_time(raw.get("stop")), as_int(raw.get("pos")), as_int(raw.get("at"))
        epg = _id(raw.get("epg"))
        if cid and epg and start and stop and stop > start and pos is not None and 0 < pos < stop - start:
            out.append((at or 0, cid, {"epg": epg, "title": clean_text(raw.get("title"), 120) or "Programme",
                                       "start": start, "stop": stop, "pos": pos, "at": at or 0}))
    out.sort(key=lambda e: -e[0])
    return {cid: entry for _, cid, entry in out[:MAX_RESUME]}


def normalize_state(raw) -> dict:
    raw = raw if isinstance(raw, dict) else {}
    recent = _recent(raw.get("recent"))
    return {"favourites": _ids(raw.get("favourites"), MAX_FAVOURITES), "recent": recent,
            "last": _id(raw.get("last")) or (recent[0]["id"] if recent else ""),
            "resume": _resume(raw.get("resume"))}


def toggle_favourite(state, cid):
    """(new state, now a favourite)."""
    favourites = [c for c in state["favourites"] if c != cid]
    added = len(favourites) == len(state["favourites"])
    return normalize_state({**state, "favourites": favourites + [cid] if added else favourites}), added


def record_played(state, cid, now):
    """`cid` was started at `now`: first among the recent channels and the last one."""
    recent = [{"id": cid, "at": int(now)}] + [e for e in state["recent"] if e["id"] != cid]
    return normalize_state({**state, "recent": recent, "last": cid})


def record_position(state, cid, programme, pos, total, now):
    """The player stopped `pos` seconds into an archived programme (`programme`: epg, title, start, stop) of
    `cid`, of `total` seconds if it said (0: it did not). A programme left at its very start or very end is
    forgotten instead: nothing to continue."""
    length = total if total and total > 0 else programme["stop"] - programme["start"]
    resume = {c: e for c, e in state["resume"].items() if c != cid}
    if pos >= MIN_RESUME and pos <= length - END_MARGIN:
        resume[cid] = {**programme, "pos": int(pos), "at": int(now)}
    return normalize_state({**state, "resume": resume})


def forget_position(state, cid):
    return normalize_state({**state, "resume": {c: e for c, e in state["resume"].items() if c != cid}})


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
