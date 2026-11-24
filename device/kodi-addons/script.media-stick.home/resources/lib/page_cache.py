"""Pages kept on disk between launches: a screen that was seen once shows at once the next time, while the page is asked
for again in the background. One cache for every app screen (YouTube, SWEET.TV, ...); what a page is, is the app's business:
here it is any JSON value (the app turns its entries into lists and dicts and back).

What an app screen needs (the same four lines for any app):

  ns = "youtube:" + profile_id                    # one namespace per account: another account never sees these pages
  hit = page_cache.get(ns, key, ttl=300)          # key = the section or route; Hit(value, age_s, stale) or None
  if hit: show(hit.value); refresh_in_background() if hit.stale
  page_cache.put(ns, key, value)                  # a good answer only: never an error, an empty list, a sign-in or key card
  prefetch.warm(ns, [(key, fetch), ...])         # at start-up: fetch the pages one after another, see prefetch.py
  page_cache.drop_service("youtube")              # on sign-out: the account's pages go (drop(ns) for one namespace)

Stale-while-revalidate: a page older than `ttl` is still returned (stale=True) so that it shows at once and is refreshed; a
page older than `max_age` (a day) is not returned at all. Nothing here raises: a missing, unreadable or damaged file is an
empty cache, a value that cannot be stored (not JSON, too big, looks like a credential) is refused with False.

On disk: one JSON file for each namespace in special://profile/addon_data/script.media-stick.home/cache/, written whole and
renamed into place (a power cut leaves the old file or the new one). Caps, for a Pi with 1 GB: MAX_ENTRIES pages for each
namespace (the oldest go first), MAX_FILE_BYTES for a file, MAX_TOTAL_BYTES for the folder (the file untouched longest goes
first). Pictures are not kept here: Kodi caches thumbnails itself. A file is read again only when it changed on disk.
"""
import copy
import hashlib
import json
import os
import re
import tempfile
import threading
import time
from collections import namedtuple

ADDON_ID = "script.media-stick.home"
CACHE_DIR = f"special://profile/addon_data/{ADDON_ID}/cache/"
VERSION = 1
MAX_ENTRIES = 40                 # pages kept for one namespace
MAX_FILE_BYTES = 512 * 1024      # one namespace's file
MAX_TOTAL_BYTES = 4 * 1024 * 1024    # the folder
MAX_KEY = 400                    # characters of a key (a route)
MAX_NAMESPACE = 120
DEFAULT_TTL = 300                # s a page is shown without asking again
DEFAULT_MAX_AGE = 24 * 3600      # s after which a page is not shown at all
STALE_TMP = 3600                 # s: a .tmp file left by an interrupted write older than this is removed
MAX_DEPTH = 12                   # nesting of a value

# What a stored page may not contain: a key that names a credential, a string that is one. Pages hold titles and addresses.
SECRET_KEY = re.compile(r"token|secret|passw|credential|api[_-]?key|authorization|cookie|session|bearer", re.IGNORECASE)
SECRET_TEXT = re.compile(r"(?:access_token|refresh_token|id_token|api_?key|client_secret|password)=|bearer\s+\S|ya29\.", re.IGNORECASE)

Hit = namedtuple("Hit", "value age_s stale")

DIR = None                       # a test (or a caller) may point the cache at another folder
_lock = threading.RLock()
_memo = {}                       # path -> ((mtime_ns, size), document): the file is read again only when it changed


def directory():
    if DIR:
        return DIR
    import xbmcvfs
    return xbmcvfs.translatePath(CACHE_DIR)


def _name_ok(namespace):
    return isinstance(namespace, str) and 0 < len(namespace) <= MAX_NAMESPACE and namespace.isprintable()


def _safe(text):
    return re.sub(r"[^A-Za-z0-9.-]", "_", text)[:40]


def _path(namespace):
    return os.path.join(directory(), f"{_safe(namespace)}-{hashlib.sha1(namespace.encode('utf-8')).hexdigest()[:10]}.json")


def _empty(namespace):
    return {"v": VERSION, "ns": namespace, "items": {}}


def _number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == value and abs(value) != float("inf")


def _valid(raw, namespace):
    """The document in `raw` when it is ours (version, namespace), with the items that are well formed; else an empty one."""
    if not isinstance(raw, dict) or raw.get("v") != VERSION or raw.get("ns") != namespace or not isinstance(raw.get("items"), dict):
        return _empty(namespace)
    items = {key: item for key, item in raw["items"].items()
             if isinstance(key, str) and isinstance(item, dict) and _number(item.get("t")) and "v" in item}
    return {"v": VERSION, "ns": namespace, "items": items}


def _read(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError, MemoryError, RecursionError):
        return None


def _load(path, namespace):
    """The namespace's document: from memory while the file is as it was, else from disk; empty when there is none or it is damaged."""
    try:
        info = os.stat(path)
    except OSError:
        _memo.pop(path, None)
        return _empty(namespace)
    stamp = (info.st_mtime_ns, info.st_size)
    memo = _memo.get(path)
    if memo and memo[0] == stamp:
        return memo[1]
    doc = _valid(_read(path), namespace)
    _memo[path] = (stamp, doc)
    return doc


def _holds_secret(value, depth=0):
    """Whether a value has a key named like a credential or a string that is one (too deep counts: pages are flat)."""
    if depth > MAX_DEPTH:
        return True
    if isinstance(value, dict):
        return any(not isinstance(k, str) or SECRET_KEY.search(k) or _holds_secret(v, depth + 1) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_holds_secret(v, depth + 1) for v in value)
    return isinstance(value, str) and bool(SECRET_TEXT.search(value))


def _write(path, doc):
    """Write the document whole and rename it into place. False when it could not be written."""
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
        info = os.stat(path)
        _memo[path] = ((info.st_mtime_ns, info.st_size), doc)
        return True
    except (OSError, ValueError, TypeError):
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        _memo.pop(path, None)
        return False


def _size(doc):
    return len(json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


def _oldest(items, spare):
    return min((k for k in items if k != spare), key=lambda k: items[k]["t"], default=None)


def _trim_folder(keep):
    """Keep the folder within MAX_TOTAL_BYTES: the file untouched longest (not `keep`) goes first; leftover .tmp files go."""
    folder = os.path.dirname(keep)
    now = time.time()
    found = []
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        try:
            info = os.stat(path)
        except OSError:
            continue
        if name.endswith(".tmp"):
            if now - info.st_mtime > STALE_TMP:
                os.unlink(path)
        elif name.endswith(".json") and path != keep:
            found.append((info.st_mtime, info.st_size, path))
    total = sum(size for _, size, _ in found) + os.stat(keep).st_size
    for _, size, path in sorted(found):
        if total <= MAX_TOTAL_BYTES:
            break
        os.unlink(path)
        _memo.pop(path, None)
        total -= size


def get(namespace, key, ttl=DEFAULT_TTL, max_age=DEFAULT_MAX_AGE, now=None):
    """Hit(value, age_s, stale) for a page kept under (namespace, key), None for none or one older than `max_age`.
    `stale` is True from `ttl` on (and for a page written in the future, a clock that went back): show it, ask again.
    The value is a copy: the caller may change it."""
    try:
        if not _name_ok(namespace) or not isinstance(key, str):
            return None
        with _lock:
            item = _load(_path(namespace), namespace)["items"].get(key)
            if item is None:
                return None
            age = (time.time() if now is None else now) - item["t"]
            if age > max_age:
                return None
            return Hit(copy.deepcopy(item["v"]), max(age, 0.0), age < 0 or age >= ttl)
    except Exception:
        return None


def fresh(namespace, key, ttl=DEFAULT_TTL, now=None):
    """Whether a page under (namespace, key) is there and younger than `ttl`: nothing to fetch."""
    hit = get(namespace, key, ttl, now=now)
    return hit is not None and not hit.stale


def put(namespace, key, value, now=None):
    """Keep `value` (any JSON value) under (namespace, key). True when it is stored; False when it is refused (not JSON, too
    big for a file, a credential in it, a name that is too long) or the disk would not take it."""
    try:
        if not _name_ok(namespace) or not isinstance(key, str) or not 0 < len(key) <= MAX_KEY or _holds_secret(value):
            return False
        value = json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))      # what a file will give back
        stamp = time.time() if now is None else now
        with _lock:
            path = _path(namespace)
            items = dict(_load(path, namespace)["items"])
            items[key] = {"t": stamp, "v": value}
            while len(items) > MAX_ENTRIES:
                items.pop(_oldest(items, key))
            doc = {"v": VERSION, "ns": namespace, "items": items}
            while _size(doc) > MAX_FILE_BYTES:
                oldest = _oldest(items, key)
                if oldest is None:
                    return False                 # this page alone is too big
                items.pop(oldest)
            if not _write(path, doc):
                return False
            try:
                _trim_folder(path)
            except OSError:
                pass                             # the page is stored; the folder is trimmed by the next put
            return True
    except Exception:
        return False


def remove(namespace, key):
    """Forget one page (it is no longer good: the section now says empty, or sign in)."""
    try:
        with _lock:
            path = _path(namespace)
            doc = _load(path, namespace)
            if key in doc["items"]:
                _write(path, {**doc, "items": {k: v for k, v in doc["items"].items() if k != key}})
    except Exception:
        pass


def _unlink(path):
    _memo.pop(path, None)
    try:
        os.unlink(path)
    except OSError:
        pass


def drop(namespace):
    """Forget every page of a namespace (sign-out, a removed profile)."""
    try:
        if _name_ok(namespace):
            with _lock:
                _unlink(_path(namespace))
    except Exception:
        pass


def drop_service(service):
    """Forget the pages of every namespace of an app ("youtube" drops "youtube:<every profile>"): a sign-out must leave
    nothing of the account behind, and the app need not know which profile it was."""
    try:
        prefix = f"{service}:"
        with _lock:
            folder = directory()
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if not name.endswith(".json"):
                    continue
                raw = _read(path)
                named = raw.get("ns") if isinstance(raw, dict) else None
                if isinstance(named, str) and named.startswith(prefix) or named is None and name.startswith(_safe(prefix)):
                    _unlink(path)                # a file that cannot be read is dropped by its name
    except Exception:
        pass
