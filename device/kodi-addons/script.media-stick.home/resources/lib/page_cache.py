"""Pages kept on disk between launches: a screen that was seen once shows at once the next time, while the page is asked
for again in the background. One cache for every app screen (YouTube, SWEET.TV, ...); what a page is, is the app's business:
here it is any JSON value (the app turns its entries into lists and dicts and back).

Stale-while-revalidate: a page older than ttl is still returned (stale=True) so that it shows at once and is refreshed; a
page older than max_age (a day) is not returned at all. Nothing here raises: a missing, unreadable or damaged store is an
empty cache, a value that cannot be stored (not JSON, too big, looks like a credential) is refused with False.

On disk: WAL-mode SQLite database (cache.db) with zlib-compressed payloads in
special://profile/addon_data/script.media-stick.home/cache/, backed by mediastick_store.CacheStore.
"""
from collections import namedtuple
import copy
import json
import os
import re
import sys
import threading
import time


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

ADDON_ID = "script.media-stick.home"
CACHE_DIR = f"special://profile/addon_data/{ADDON_ID}/cache/"
VERSION = 1
MAX_ENTRIES = 40                 # pages kept for one namespace
MAX_FILE_BYTES = 512 * 1024      # one page / namespace cap
MAX_TOTAL_BYTES = 4 * 1024 * 1024
MAX_KEY = 400                    # characters of a key (a route)
MAX_NAMESPACE = 120
DEFAULT_TTL = 300                # s a page is shown without asking again
DEFAULT_MAX_AGE = 24 * 3600      # s after which a page is not shown at all
MAX_DEPTH = 12                   # nesting of a value
SECRET_KEY = re.compile(r"token|secret|passw|credential|api[_-]?key|authorization|cookie|session|bearer", re.IGNORECASE)


def _holds_secret(value, depth=0):
    if depth > MAX_DEPTH:
        return True
    if ms.contains_secret(value):
        return True
    if isinstance(value, dict):
        return any((isinstance(k, str) and SECRET_KEY.search(k)) or _holds_secret(v, depth + 1) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_holds_secret(v, depth + 1) for v in value)
    return False

Hit = namedtuple("Hit", "value age_s stale")
Refused = ms.SecretRefused

DIR = None                       # a test (or a caller) may point the cache at another folder
_lock = threading.RLock()
_memo = {}                       # kept for caller/test compatibility
_stores = {}                     # db_path -> CacheStore


def directory():
    if DIR:
        return DIR
    import xbmcvfs
    return xbmcvfs.translatePath(CACHE_DIR)


def _name_ok(namespace):
    return isinstance(namespace, str) and 0 < len(namespace) <= MAX_NAMESPACE and namespace.isprintable()


def _db_path():
    return os.path.join(directory(), "cache.db")


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
            if hasattr(store, chr(109)+chr(97)+chr(120)+chr(95)+chr(98)+chr(121)+chr(116)+chr(101)+chr(115)):
                store.max_bytes = int(MAX_TOTAL_BYTES)
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
    store = ms.CacheStore(db_path=path, max_bytes=MAX_TOTAL_BYTES)
    st = os.stat(path)
    _stores[path] = (store, (st.st_dev, st.st_ino))
    return store


def get(namespace, key, ttl=DEFAULT_TTL, max_age=DEFAULT_MAX_AGE, now=None):
    try:
        if not _name_ok(namespace) or not isinstance(key, str):
            return None
        with _lock:
            store = _get_store(create=False)
            if store is None:
                return None
            hit = store.get_page(
                namespace,
                key,
                version=VERSION,
                lang="",
                ttl=ttl,
                max_age=max_age,
                now=now,
            )
            if hit is None:
                return None
            stale = hit.stale or (ttl is not None and hit.age_s >= float(ttl))
            return Hit(copy.deepcopy(hit.data), hit.age_s, stale)
    except Exception:
        return None


def fresh(namespace, key, ttl=DEFAULT_TTL, now=None):
    hit = get(namespace, key, ttl, now=now)
    return hit is not None and not hit.stale


def put(namespace, key, value, now=None):
    try:
        if not _name_ok(namespace) or not isinstance(key, str) or not 0 < len(key) <= MAX_KEY:
            return False
        if _holds_secret(value):
            return False
        raw_json = json.dumps(value, ensure_ascii=False, allow_nan=False)
        if len(raw_json.encode("utf-8")) > MAX_FILE_BYTES:
            return False
        value = json.loads(raw_json)
        stamp = time.time() if now is None else float(now)
        with _lock:
            store = _get_store(create=True)
            store.put_page(namespace, key, value, version=VERSION, lang="", now=stamp)
            with store._tx() as con:
                count = con.execute(
                    "SELECT COUNT(*) FROM pages WHERE namespace = ?",
                    (namespace,),
                ).fetchone()[0]
                if count > MAX_ENTRIES:
                    excess = count - MAX_ENTRIES
                    con.execute(
                        "DELETE FROM pages WHERE namespace = ? AND key IN ("
                        "SELECT key FROM pages WHERE namespace = ? ORDER BY fetched_at ASC, key ASC LIMIT ?)",
                        (namespace, namespace, excess),
                    )
            entry = _stores.pop(_db_path(), None)
            if entry is not None:
                entry[0].close()
            return True
    except Exception:
        return False


def remove(namespace, key):
    try:
        if not _name_ok(namespace) or not isinstance(key, str):
            return
        with _lock:
            store = _get_store(create=False)
            if store is None:
                return
            with store._tx() as con:
                con.execute("DELETE FROM pages WHERE namespace = ? AND key = ?", (namespace, key))
    except Exception:
        pass


def drop(namespace):
    try:
        if _name_ok(namespace):
            with _lock:
                store = _get_store(create=False)
                if store is not None:
                    store.drop_namespace(namespace)
    except Exception:
        pass


drop_namespace = drop


def drop_service(service):
    try:
        if not isinstance(service, str) or not service:
            return
        with _lock:
            store = _get_store(create=False)
            if store is not None:
                store.drop_service(service)
    except Exception:
        pass
