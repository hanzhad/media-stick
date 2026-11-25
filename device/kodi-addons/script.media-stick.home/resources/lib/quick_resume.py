"""Quick Resume UI snapshot helpers over mediastick_store.CacheStore.

Pure Core:
  - build_sweettv_snapshot(...) -> dict
  - build_youtube_snapshot(...) -> dict

Thin Debounced I/O Shell:
  - save_snapshot(app_id, profile_id, snapshot, debounce_s=0.0, now=None) -> bool
  - load_snapshot(app_id, profile_id="default") -> dict | None
  - drop_snapshots(app_id=None) -> None
"""
import os
import sys
import threading

from resources.lib import page_cache


def _import_store():
    try:
        import mediastick_store
        return mediastick_store
    except ImportError:
        for candidate in (
            "/usr/local/lib/media-stick",
            os.path.abspath(
                os.path.join(
                    os.path.dirname(__file__),
                    "..", "..", "..", "..", "files", "usr", "local", "lib", "media-stick",
                )
            ),
        ):
            if os.path.isdir(candidate) and candidate not in sys.path:
                sys.path.insert(0, candidate)
        import mediastick_store
        return mediastick_store


ms = _import_store()

DEBOUNCE_S = 0.5
DIR = None
_lock = threading.RLock()
_timers = {}
_stores = {}


def _compact_sweettv_card(card):
    if isinstance(card, dict):
        return dict(card)
    return {
        "key": str(getattr(card, "key", "") or ""),
        "kind": str(getattr(card, "kind", "") or ""),
        "title": str(getattr(card, "title", "") or "")[:120],
        "thumb": str(getattr(card, "art", "") or "")[:300],
        "cid": str(getattr(card, "cid", "") or ""),
        "epg": str(getattr(card, "epg", "") or ""),
    }


def _compact_youtube_card(card):
    if isinstance(card, dict):
        return dict(card)
    if isinstance(card, (list, tuple)):
        return list(card[:12])
    return {"title": str(card)[:120]}


def _compact_youtube_stack_entry(entry):
    if isinstance(entry, dict):
        return dict(entry)
    if isinstance(entry, (list, tuple)) and len(entry) >= 2:
        view, pos = entry[0], entry[1]
        return {
            "key": str(getattr(view, "key", "") or ""),
            "route": str(getattr(view, "route", "") or ""),
            "title": str(getattr(view, "title", "") or ""),
            "kind": str(getattr(view, "kind", "") or ""),
            "needs_login": bool(getattr(view, "needs_login", False)),
            "pos": int(pos or 0),
        }
    return {}


def _cap_snapshot(snap: dict) -> dict:
    candidate = dict(snap)
    cards = list(candidate.get("cards") or ())
    if len(ms.encode_payload(candidate)) <= ms.MAX_SNAPSHOT_BYTES:
        return ms.validate_snapshot(candidate)
    lo, hi = 0, len(cards)
    best = 0
    while lo <= hi:
        mid = (lo + hi) // 2
        candidate["cards"] = cards[:mid]
        if len(ms.encode_payload(candidate)) <= ms.MAX_SNAPSHOT_BYTES:
            best = mid
            lo = mid + 1
        else:
            hi = mid - 1
    candidate["cards"] = cards[:best]
    stack = list(candidate.get("nav_stack") or ())
    while stack and len(ms.encode_payload(candidate)) > ms.MAX_SNAPSHOT_BYTES:
        stack = stack[:-1]
        candidate["nav_stack"] = stack
    return ms.validate_snapshot(candidate)


def build_sweettv_snapshot(
    section="",
    filter="",
    sort="",
    search_query="",
    nav_stack=None,
    focused_control=0,
    focused_index=0,
    focused_key="",
    scroll_offset=0,
    cards=None,
    media_ref=None,
) -> dict:
    compact_cards = [_compact_sweettv_card(c) for c in (cards or ())]
    raw = {
        "schema_v": 1,
        "section": str(section or ""),
        "filter": str(filter or ""),
        "sort": str(sort or ""),
        "search_query": str(search_query or ""),
        "nav_stack": list(nav_stack or ()),
        "focused_control": int(focused_control or 0),
        "focused_index": max(0, int(focused_index or 0)),
        "focused_key": str(focused_key or ""),
        "scroll_offset": max(0, int(scroll_offset or 0)),
        "cards": compact_cards,
        "media_ref": dict(media_ref) if isinstance(media_ref, dict) else None,
    }
    return _cap_snapshot(raw)


def build_youtube_snapshot(
    section="home",
    query="",
    kind="videos",
    stack=None,
    focused_index=0,
    focused_key="",
    focused_control=0,
    scroll_offset=0,
    cards=None,
    media_ref=None,
) -> dict:
    compact_stack = [_compact_youtube_stack_entry(s) for s in (stack or ())]
    compact_cards = [_compact_youtube_card(c) for c in (cards or ())]
    raw = {
        "schema_v": 1,
        "section": str(section or "home"),
        "filter": str(kind or "videos"),
        "sort": "",
        "search_query": str(query or ""),
        "nav_stack": compact_stack,
        "focused_control": int(focused_control or 0),
        "focused_index": max(0, int(focused_index or 0)),
        "focused_key": str(focused_key or ""),
        "scroll_offset": max(0, int(scroll_offset or 0)),
        "cards": compact_cards,
        "media_ref": dict(media_ref) if isinstance(media_ref, dict) else None,
    }
    return _cap_snapshot(raw)


def _db_path():
    folder = DIR if DIR else page_cache.directory()
    return os.path.join(folder, "cache.db")


def _get_store(create=True):
    path = _db_path()
    try:
        st = os.stat(path)
        ident = (st.st_dev, st.st_ino)
    except OSError:
        ident = None
    if not create and ident is None:
        return None
    entry = _stores.get(path)
    if entry is not None:
        store, old_ident = entry
        if ident is None or ident != old_ident:
            try:
                store.close()
            except Exception:
                pass
            _stores.pop(path, None)
        else:
            return store
    if len(_stores) >= 4:
        for old_path in list(_stores):
            if old_path != path:
                old_entry = _stores.pop(old_path, None)
                if old_entry is not None:
                    try:
                        old_entry[0].close()
                    except Exception:
                        pass
    store = ms.CacheStore(db_path=path)
    st = os.stat(path)
    _stores[path] = (store, (st.st_dev, st.st_ino))
    return store


def _write_now(app_id: str, profile_id: str, snapshot: dict, now=None) -> bool:
    try:
        with _lock:
            store = _get_store(create=True)
            store.save_snapshot(app_id, profile_id or "default", snapshot, now=now)
        return True
    except Exception:
        return False


def save_snapshot(
    app_id: str,
    profile_id: str = "default",
    snapshot: dict | None = None,
    debounce_s: float = 0.0,
    now: float | None = None,
) -> bool:
    if not isinstance(snapshot, dict):
        return False
    prof = profile_id or "default"
    key = (app_id, prof)
    with _lock:
        old = _timers.pop(key, None)
        if old is not None:
            old.cancel()
        if debounce_s and debounce_s > 0:
            timer = threading.Timer(debounce_s, _write_now, args=(app_id, prof, snapshot, now))
            timer.daemon = True
            _timers[key] = timer
            timer.start()
            return True
    return _write_now(app_id, prof, snapshot, now=now)


def load_snapshot(app_id: str, profile_id: str = "default") -> dict | None:
    try:
        with _lock:
            store = _get_store(create=False)
            if store is None:
                return None
            return store.load_snapshot(app_id, profile_id or "default")
    except Exception:
        return None


def drop_snapshots(app_id: str | None = None) -> None:
    try:
        with _lock:
            for key in list(_timers):
                if app_id is None or key[0] == app_id:
                    timer = _timers.pop(key, None)
                    if timer is not None:
                        timer.cancel()
            store = _get_store(create=False)
            if store is not None:
                store.drop_snapshots(app_id)
    except Exception:
        pass
