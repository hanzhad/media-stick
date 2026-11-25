"""Shared SQLite WAL store for Quick Resume snapshots, resume state, and cache.

Pure Core (no filesystem or database I/O):
  - SecretRefused, CacheHit, MAX_SNAPSHOT_BYTES
  - contains_secret(obj) -> bool
  - encode_payload(value) -> bytes / decode_payload(blob: bytes)
  - classify_cache_entry(fetched_at, now, ttl, max_age) -> "fresh" | "stale" | "expired"
  - validate_snapshot(snapshot: dict) -> dict
  - compute_eviction_keys(rows, budget_bytes) -> list[tuple[str, str]]

Thin I/O Shell (SQLite WAL mode, stdlib only, zero xbmc imports):
  - StateStore: durable resume, favourites, app_recent, prefs + legacy JSON migration
  - CacheStore: SWR pages, API cache with combined LRU eviction, UI snapshots
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
import re
import sqlite3
import threading
import time
import zlib

DEFAULT_STATE_DB = "/var/lib/media-stick/state.db"
DEFAULT_CACHE_DB = "/var/cache/media-stick/cache.db"
DEFAULT_MAX_CACHE_BYTES = 8 * 1024 * 1024
MAX_SNAPSHOT_BYTES = 65536
BUSY_TIMEOUT_MS = 3000

_SECRET_TOKENS = frozenset({
    "token",
    "tokens",
    "password",
    "passwords",
    "passwd",
    "secret",
    "secrets",
    "cookie",
    "cookies",
    "authorization",
    "bearer",
    "auth",
    "credential",
    "credentials",
})
_SECRET_JOINED = frozenset({
    "accesstoken",
    "refreshtoken",
    "idtoken",
    "apikey",
    "clientsecret",
    "setcookie",
    "bearertoken",
})
_SECRET_VALUE_PATTERNS = (
    re.compile(r"(?:^|\b)bearer\s+[A-Za-z0-9._~+/=-]+", re.IGNORECASE),
    re.compile(r"(?:^|\b)(?:authorization|cookie)\s*:\s*\S", re.IGNORECASE),
    re.compile(
        r"(?:^|[?&;\s,])(?:token|access_token|refresh_token|id_token|api[_-]?key|"
        r"client_secret|password|passwd|secret|cookie|auth|authorization)\s*=\s*[^\s&]+",
        re.IGNORECASE,
    ),
    re.compile(r"\bya29\.[A-Za-z0-9_-]+"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"),
)
_CAMEL_RE = re.compile(r"([a-z0-9])([A-Z])")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


class SecretRefused(ValueError):
    """Raised before any DB write when a payload contains credential-like data."""


@dataclass(frozen=True)
class CacheHit:
    data: object
    stale: bool
    fetched_at: float = 0.0
    age_s: float = 0.0


def _is_secret_key(key: str) -> bool:
    expanded = _CAMEL_RE.sub(r"\1_\2", key).lower()
    tokens = [tok for tok in _NON_ALNUM_RE.split(expanded) if tok]
    if any(tok in _SECRET_TOKENS for tok in tokens):
        return True
    return "".join(tokens) in _SECRET_JOINED


def _is_secret_string(text: str) -> bool:
    return any(pat.search(text) for pat in _SECRET_VALUE_PATTERNS)


def contains_secret(obj, _depth: int = 0) -> bool:
    """Recursively return True if obj contains secret keys or secret-like string values."""
    if _depth > 32:
        return True
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str) and _is_secret_key(k):
                return True
            if contains_secret(v, _depth + 1):
                return True
        return False
    if isinstance(obj, (list, tuple, set, frozenset)):
        return any(contains_secret(item, _depth + 1) for item in obj)
    if isinstance(obj, str):
        return _is_secret_string(obj)
    return False


def encode_payload(value) -> bytes:
    """Serialize value to UTF-8 JSON and compress with zlib."""
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return zlib.compress(raw)


def decode_payload(blob: bytes):
    """Decompress zlib blob and decode UTF-8 JSON."""
    if not isinstance(blob, (bytes, bytearray, memoryview)) or not blob:
        raise ValueError("payload must be non-empty bytes")
    raw = zlib.decompress(bytes(blob)).decode("utf-8")
    return json.loads(raw)


def classify_cache_entry(fetched_at: float, now: float, ttl: float, max_age: float) -> str:
    """Classify a cached entry under SWR semantics: 'fresh', 'stale', or 'expired'."""
    age = float(now) - float(fetched_at)
    if age > float(max_age):
        return "expired"
    if age < 0:
        return "stale"
    if age <= float(ttl):
        return "fresh"
    return "stale"


def _opt_str(value, field: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TypeError(f"{field} must be a string or None")
    return value


def _opt_int(value, field: str, default: int = 0) -> int:
    if value is None:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field} must be an int or None")
    return value


def validate_snapshot(snapshot: dict) -> dict:
    """Normalize and validate a Quick Resume snapshot and enforce MAX_SNAPSHOT_BYTES."""
    if not isinstance(snapshot, dict):
        raise TypeError("snapshot must be a dict")
    if contains_secret(snapshot):
        raise SecretRefused("snapshot contains secret data")

    schema_v = _opt_int(snapshot.get("schema_v", 1), "schema_v", default=1)
    if schema_v <= 0:
        raise ValueError("schema_v must be positive")

    nav_stack = snapshot.get("nav_stack")
    if nav_stack is None:
        nav_stack = []
    elif isinstance(nav_stack, tuple):
        nav_stack = list(nav_stack)
    elif not isinstance(nav_stack, list):
        raise TypeError("nav_stack must be a list")

    cards = snapshot.get("cards")
    if cards is None:
        cards = []
    elif isinstance(cards, tuple):
        cards = list(cards)
    elif not isinstance(cards, list):
        raise TypeError("cards must be a list")

    media_ref = snapshot.get("media_ref")
    if media_ref is not None and not isinstance(media_ref, dict):
        raise TypeError("media_ref must be a dict or None")

    normalized = {
        "schema_v": schema_v,
        "section": _opt_str(snapshot.get("section"), "section"),
        "filter": _opt_str(snapshot.get("filter"), "filter"),
        "sort": _opt_str(snapshot.get("sort"), "sort"),
        "search_query": _opt_str(snapshot.get("search_query"), "search_query"),
        "nav_stack": nav_stack,
        "focused_control": _opt_int(snapshot.get("focused_control"), "focused_control", default=0),
        "focused_index": _opt_int(snapshot.get("focused_index"), "focused_index", default=0),
        "focused_key": _opt_str(snapshot.get("focused_key"), "focused_key"),
        "scroll_offset": _opt_int(snapshot.get("scroll_offset"), "scroll_offset", default=0),
        "cards": cards,
        "media_ref": media_ref,
    }
    blob = encode_payload(normalized)
    if len(blob) > MAX_SNAPSHOT_BYTES:
        raise ValueError(f"snapshot compressed size {len(blob)} exceeds {MAX_SNAPSHOT_BYTES} bytes")
    return normalized


def compute_eviction_keys(
    rows: list[tuple[str, str, int, float]],
    budget_bytes: int,
) -> list[tuple[str, str]]:
    """Select (scope, key) pairs in LRU order until total remaining bytes <= budget_bytes."""
    total = sum(row[2] for row in rows)
    if total <= budget_bytes:
        return []
    evict: list[tuple[str, str]] = []
    for scope, key, size_bytes, _last_used in sorted(rows, key=lambda r: (r[3], r[0], r[1])):
        if total <= budget_bytes:
            break
        evict.append((scope, key))
        total -= size_bytes
    return evict


class _SQLiteStore:
    """Shared WAL-mode SQLite connection lifecycle and transaction helper."""

    _SCHEMA_SQL = ""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._lock = threading.RLock()
        parent = os.path.dirname(os.path.abspath(db_path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        self._con = sqlite3.connect(
            db_path,
            timeout=30.0,
            isolation_level=None,
            check_same_thread=False,
        )
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            mode_row = self._con.execute("PRAGMA journal_mode").fetchone()
            if not mode_row or str(mode_row[0]).lower() != "wal":
                self._con.execute("PRAGMA journal_mode=WAL")
            self._con.execute("PRAGMA synchronous=NORMAL")
            self._con.execute(f"PRAGMA busy_timeout={BUSY_TIMEOUT_MS}")
            self._con.execute("PRAGMA temp_store=MEMORY")
            if self._SCHEMA_SQL:
                self._con.executescript(self._SCHEMA_SQL)

    @contextmanager
    def _tx(self):
        with self._lock:
            self._con.execute("BEGIN IMMEDIATE")
            try:
                yield self._con
            except Exception:
                try:
                    self._con.execute("ROLLBACK")
                except sqlite3.Error:
                    pass
                raise
            else:
                self._con.execute("COMMIT")

    def close(self) -> None:
        with self._lock:
            con = self._con
            self._con = None
            if con is not None:
                con.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def _read_json_file(path: str | None):
    if not path:
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _infer_app(media_key: str) -> str:
    if media_key.startswith("yt:"):
        return "youtube"
    if media_key.startswith("sw:"):
        return "sweettv"
    return ""


class StateStore(_SQLiteStore):
    """Durable user state store backed by WAL-mode SQLite."""

    _SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS resume (
        media_key TEXT PRIMARY KEY,
        app TEXT NOT NULL,
        pos INTEGER NOT NULL,
        total INTEGER NOT NULL,
        done INTEGER NOT NULL,
        updated_at REAL NOT NULL,
        meta_json TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX IF NOT EXISTS idx_resume_updated_at ON resume(updated_at DESC);

    CREATE TABLE IF NOT EXISTS favourites (
        fav_key TEXT PRIMARY KEY,
        app TEXT NOT NULL,
        title TEXT NOT NULL DEFAULT '',
        thumb TEXT NOT NULL DEFAULT '',
        meta_json TEXT NOT NULL DEFAULT '{}',
        added_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_favourites_app_added ON favourites(app, added_at DESC);

    CREATE TABLE IF NOT EXISTS app_recent (
        app_id TEXT PRIMARY KEY,
        launched_at REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS prefs (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """

    def __init__(self, db_path: str = DEFAULT_STATE_DB):
        super().__init__(db_path)

    def get_resume(self, media_key: str) -> dict | None:
        with self._lock:
            row = self._con.execute(
                "SELECT media_key, app, pos, total, done, updated_at, meta_json "
                "FROM resume WHERE media_key = ?",
                (media_key,),
            ).fetchone()
        if row is None:
            return None
        return self._row_to_resume(row)

    @staticmethod
    def _row_to_resume(row) -> dict:
        return {
            "media_key": row[0],
            "app": row[1],
            "pos": int(row[2]),
            "total": int(row[3]),
            "done": bool(row[4]),
            "updated_at": float(row[5]),
            "meta": json.loads(row[6]) if row[6] else {},
        }

    def list_resume(self, app: str | None = None, limit: int | None = None) -> list[dict]:
        sql = "SELECT media_key, app, pos, total, done, updated_at, meta_json FROM resume"
        params: list = []
        if app is not None:
            sql += " WHERE app = ?"
            params.append(app)
        sql += " ORDER BY updated_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(int(limit))
        with self._lock:
            rows = self._con.execute(sql, params).fetchall()
        return [self._row_to_resume(row) for row in rows]

    def upsert_resume(
        self,
        media_key: str,
        app: str,
        pos: int,
        total: int,
        done: bool,
        updated_at: float | None = None,
        meta: dict | None = None,
    ) -> None:
        if meta is not None and contains_secret(meta):
            raise SecretRefused("resume meta contains secret data")
        ts = time.time() if updated_at is None else float(updated_at)
        meta_json = json.dumps(meta or {}, ensure_ascii=False, separators=(",", ":"))
        with self._tx() as con:
            con.execute(
                "INSERT INTO resume (media_key, app, pos, total, done, updated_at, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(media_key) DO UPDATE SET "
                "app = excluded.app, pos = excluded.pos, total = excluded.total, "
                "done = excluded.done, updated_at = excluded.updated_at, meta_json = excluded.meta_json",
                (media_key, app, int(pos), int(total), int(bool(done)), ts, meta_json),
            )

    def delete_resume(self, media_key: str) -> bool:
        with self._tx() as con:
            cur = con.execute("DELETE FROM resume WHERE media_key = ?", (media_key,))
            return cur.rowcount > 0

    def list_favourites(self, app: str | None = None) -> list[dict]:
        sql = "SELECT fav_key, app, title, thumb, meta_json, added_at FROM favourites"
        params: list = []
        if app is not None:
            sql += " WHERE app = ?"
            params.append(app)
        sql += " ORDER BY added_at DESC"
        with self._lock:
            rows = self._con.execute(sql, params).fetchall()
        return [
            {
                "fav_key": row[0],
                "app": row[1],
                "title": row[2],
                "thumb": row[3],
                "meta": json.loads(row[4]) if row[4] else {},
                "added_at": float(row[5]),
            }
            for row in rows
        ]

    def set_favourite(
        self,
        fav_key: str,
        app: str,
        title: str = "",
        thumb: str = "",
        meta: dict | None = None,
        added_at: float | None = None,
    ) -> None:
        if contains_secret(thumb) or (meta is not None and contains_secret(meta)):
            raise SecretRefused("favourite contains secret data")
        ts = time.time() if added_at is None else float(added_at)
        meta_json = json.dumps(meta or {}, ensure_ascii=False, separators=(",", ":"))
        with self._tx() as con:
            con.execute(
                "INSERT INTO favourites (fav_key, app, title, thumb, meta_json, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(fav_key) DO UPDATE SET "
                "app = excluded.app, title = excluded.title, thumb = excluded.thumb, "
                "meta_json = excluded.meta_json, added_at = excluded.added_at",
                (fav_key, app, title or "", thumb or "", meta_json, ts),
            )

    def delete_favourite(self, fav_key: str) -> bool:
        with self._tx() as con:
            cur = con.execute("DELETE FROM favourites WHERE fav_key = ?", (fav_key,))
            return cur.rowcount > 0

    def record_app_launch(self, app_id: str, launched_at: float | None = None) -> None:
        ts = time.time() if launched_at is None else float(launched_at)
        with self._tx() as con:
            con.execute(
                "INSERT INTO app_recent (app_id, launched_at) VALUES (?, ?) "
                "ON CONFLICT(app_id) DO UPDATE SET launched_at = excluded.launched_at",
                (app_id, ts),
            )

    def get_app_recent(self) -> dict[str, float]:
        with self._lock:
            rows = self._con.execute(
                "SELECT app_id, launched_at FROM app_recent ORDER BY launched_at DESC"
            ).fetchall()
        return {row[0]: float(row[1]) for row in rows}

    def get_pref(self, key: str, default=None):
        with self._lock:
            row = self._con.execute("SELECT value FROM prefs WHERE key = ?", (key,)).fetchone()
        return row[0] if row is not None else default

    def set_pref(self, key: str, value: str) -> None:
        if contains_secret({key: value}):
            raise SecretRefused("pref contains secret data")
        with self._tx() as con:
            con.execute(
                "INSERT INTO prefs (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, str(value)),
            )

    def migrate_legacy_json(
        self,
        positions_path: str | None = None,
        favourites_path: str | None = None,
        recent_path: str | None = None,
    ) -> None:
        """Idempotently import legacy JSON files without overwriting newer SQLite rows."""
        pos_doc = _read_json_file(positions_path)
        fav_doc = _read_json_file(favourites_path)
        rec_doc = _read_json_file(recent_path)

        with self._tx() as con:
            if isinstance(pos_doc, dict) and isinstance(pos_doc.get("items"), dict):
                self._migrate_positions(con, pos_doc["items"])
            if isinstance(fav_doc, dict) and isinstance(fav_doc.get("items"), dict):
                self._migrate_favourites(con, fav_doc["items"])
            if isinstance(rec_doc, dict):
                self._migrate_recent(con, rec_doc)

    @staticmethod
    def _migrate_positions(con: sqlite3.Connection, items: dict) -> None:
        skip_keys = {"pos", "total", "done", "at"}
        for media_key, entry in items.items():
            if not isinstance(media_key, str) or not isinstance(entry, dict):
                continue
            try:
                pos = int(entry.get("pos", 0))
                total = int(entry.get("total", 0))
                updated_at = float(entry.get("at", 0))
            except (TypeError, ValueError):
                continue
            done = bool(entry.get("done", False))
            meta = {k: v for k, v in entry.items() if k not in skip_keys}
            if contains_secret(meta):
                continue
            meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
            con.execute(
                "INSERT INTO resume (media_key, app, pos, total, done, updated_at, meta_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(media_key) DO UPDATE SET "
                "app = excluded.app, pos = excluded.pos, total = excluded.total, "
                "done = excluded.done, updated_at = excluded.updated_at, meta_json = excluded.meta_json "
                "WHERE excluded.updated_at > resume.updated_at",
                (media_key, _infer_app(media_key), pos, total, int(done), updated_at, meta_json),
            )

    @staticmethod
    def _migrate_favourites(con: sqlite3.Connection, items: dict) -> None:
        for fav_key, entry in items.items():
            if not isinstance(fav_key, str) or not isinstance(entry, dict):
                continue
            try:
                added_at = float(entry.get("at", 0))
            except (TypeError, ValueError):
                continue
            title = str(entry.get("title") or "")
            thumb = str(entry.get("thumb") or "")
            meta = entry.get("meta") if isinstance(entry.get("meta"), dict) else {}
            if contains_secret(thumb) or contains_secret(meta):
                continue
            meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))
            con.execute(
                "INSERT INTO favourites (fav_key, app, title, thumb, meta_json, added_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(fav_key) DO UPDATE SET "
                "app = excluded.app, title = excluded.title, thumb = excluded.thumb, "
                "meta_json = excluded.meta_json, added_at = excluded.added_at "
                "WHERE excluded.added_at > favourites.added_at",
                (fav_key, "sweettv", title, thumb, meta_json, added_at),
            )

    @staticmethod
    def _migrate_recent(con: sqlite3.Connection, rec_doc: dict) -> None:
        for app_id, ts_val in rec_doc.items():
            if not isinstance(app_id, str):
                continue
            try:
                launched_at = float(ts_val)
            except (TypeError, ValueError):
                continue
            con.execute(
                "INSERT INTO app_recent (app_id, launched_at) VALUES (?, ?) "
                "ON CONFLICT(app_id) DO UPDATE SET launched_at = excluded.launched_at "
                "WHERE excluded.launched_at > app_recent.launched_at",
                (app_id, launched_at),
            )


class CacheStore(_SQLiteStore):
    """Evictable SWR page/API cache and Quick Resume UI snapshot store."""

    _SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS pages (
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        version INTEGER NOT NULL,
        lang TEXT NOT NULL,
        payload BLOB NOT NULL,
        size_bytes INTEGER NOT NULL,
        fetched_at REAL NOT NULL,
        last_used_at REAL NOT NULL,
        PRIMARY KEY (namespace, key)
    );
    CREATE INDEX IF NOT EXISTS idx_pages_last_used ON pages(last_used_at);

    CREATE TABLE IF NOT EXISTS ui_snapshots (
        app_id TEXT NOT NULL,
        profile_id TEXT NOT NULL,
        schema_v INTEGER NOT NULL,
        payload BLOB NOT NULL,
        size_bytes INTEGER NOT NULL,
        updated_at REAL NOT NULL,
        PRIMARY KEY (app_id, profile_id)
    );

    CREATE TABLE IF NOT EXISTS api_cache (
        endpoint TEXT NOT NULL,
        req_hash TEXT NOT NULL,
        payload BLOB NOT NULL,
        size_bytes INTEGER NOT NULL,
        fetched_at REAL NOT NULL,
        ttl_s REAL NOT NULL,
        last_used_at REAL NOT NULL,
        PRIMARY KEY (endpoint, req_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_api_cache_last_used ON api_cache(last_used_at);
    """

    def __init__(self, db_path: str = DEFAULT_CACHE_DB, max_bytes: int = DEFAULT_MAX_CACHE_BYTES):
        self.max_bytes = int(max_bytes)
        super().__init__(db_path)

    def _evict_lru(self, con: sqlite3.Connection) -> None:
        rows: list[tuple[str, str, int, float]] = []
        pk_map: dict[tuple[str, str], tuple[str, str]] = {}

        for ns, key, size_bytes, last_used_at in con.execute(
            "SELECT namespace, key, size_bytes, last_used_at FROM pages"
        ):
            ident = f"{ns}\x00{key}"
            rows.append(("pages", ident, int(size_bytes), float(last_used_at)))
            pk_map[("pages", ident)] = (ns, key)

        for endpoint, req_hash, size_bytes, last_used_at in con.execute(
            "SELECT endpoint, req_hash, size_bytes, last_used_at FROM api_cache"
        ):
            ident = f"{endpoint}\x00{req_hash}"
            rows.append(("api_cache", ident, int(size_bytes), float(last_used_at)))
            pk_map[("api_cache", ident)] = (endpoint, req_hash)

        for scope, ident in compute_eviction_keys(rows, self.max_bytes):
            pk1, pk2 = pk_map[(scope, ident)]
            if scope == "pages":
                con.execute("DELETE FROM pages WHERE namespace = ? AND key = ?", (pk1, pk2))
            else:
                con.execute("DELETE FROM api_cache WHERE endpoint = ? AND req_hash = ?", (pk1, pk2))

    def get_page(
        self,
        namespace: str,
        key: str,
        version: int,
        lang: str,
        ttl: float,
        max_age: float,
        now: float | None = None,
    ) -> CacheHit | None:
        with self._lock:
            row = self._con.execute(
                "SELECT version, lang, payload, fetched_at FROM pages WHERE namespace = ? AND key = ?",
                (namespace, key),
            ).fetchone()
            if row is None:
                return None
            row_version, row_lang, payload, fetched_at = row
            if int(row_version) != int(version) or row_lang != lang:
                return None
            cur_now = time.time() if now is None else float(now)
            status = classify_cache_entry(fetched_at, cur_now, ttl, max_age)
            if status == "expired":
                return None
            try:
                data = decode_payload(payload)
            except (ValueError, zlib.error):
                return None
            self._con.execute(
                "UPDATE pages SET last_used_at = ? WHERE namespace = ? AND key = ?",
                (cur_now, namespace, key),
            )
            return CacheHit(
                data=data,
                stale=(status == "stale"),
                fetched_at=float(fetched_at),
                age_s=max(0.0, cur_now - float(fetched_at)),
            )

    def put_page(
        self,
        namespace: str,
        key: str,
        value,
        version: int = 1,
        lang: str = "",
        now: float | None = None,
    ) -> None:
        if contains_secret(value):
            raise SecretRefused("page payload contains secret data")
        blob = encode_payload(value)
        size_bytes = len(blob)
        if size_bytes > self.max_bytes:
            raise ValueError(f"page size {size_bytes} exceeds max_bytes {self.max_bytes}")
        ts = time.time() if now is None else float(now)
        with self._tx() as con:
            con.execute(
                "INSERT INTO pages (namespace, key, version, lang, payload, size_bytes, fetched_at, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(namespace, key) DO UPDATE SET "
                "version = excluded.version, lang = excluded.lang, payload = excluded.payload, "
                "size_bytes = excluded.size_bytes, fetched_at = excluded.fetched_at, "
                "last_used_at = excluded.last_used_at",
                (namespace, key, int(version), lang, sqlite3.Binary(blob), size_bytes, ts, ts),
            )
            self._evict_lru(con)

    def drop_namespace(self, namespace: str) -> None:
        with self._tx() as con:
            con.execute("DELETE FROM pages WHERE namespace = ?", (namespace,))

    def drop(self, namespace: str) -> None:
        self.drop_namespace(namespace)

    def drop_service(self, prefix: str) -> None:
        ns_prefix = prefix if prefix.endswith(":") else f"{prefix}:"
        base = prefix.rstrip(":")
        plen = len(ns_prefix)
        with self._tx() as con:
            con.execute(
                "DELETE FROM pages WHERE namespace = ? OR substr(namespace, 1, ?) = ?",
                (base, plen, ns_prefix),
            )

    def save_snapshot(
        self,
        app_id: str,
        profile_id: str,
        snapshot: dict,
        now: float | None = None,
    ) -> None:
        if contains_secret(snapshot):
            raise SecretRefused("snapshot contains secret data")
        normalized = validate_snapshot(snapshot)
        blob = encode_payload(normalized)
        size_bytes = len(blob)
        ts = time.time() if now is None else float(now)
        with self._tx() as con:
            con.execute(
                "INSERT INTO ui_snapshots (app_id, profile_id, schema_v, payload, size_bytes, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(app_id, profile_id) DO UPDATE SET "
                "schema_v = excluded.schema_v, payload = excluded.payload, "
                "size_bytes = excluded.size_bytes, updated_at = excluded.updated_at",
                (app_id, profile_id, int(normalized["schema_v"]), sqlite3.Binary(blob), size_bytes, ts),
            )

    def load_snapshot(self, app_id: str, profile_id: str) -> dict | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload FROM ui_snapshots WHERE app_id = ? AND profile_id = ?",
                (app_id, profile_id),
            ).fetchone()
        if row is None:
            return None
        try:
            data = decode_payload(row[0])
        except (ValueError, zlib.error):
            return None
        return data if isinstance(data, dict) else None

    def drop_snapshots(self, app_id: str | None = None) -> None:
        with self._tx() as con:
            if app_id is None:
                con.execute("DELETE FROM ui_snapshots")
            else:
                con.execute("DELETE FROM ui_snapshots WHERE app_id = ?", (app_id,))

    def get_api(
        self,
        endpoint: str,
        req_hash: str,
        max_age: float | None = None,
        now: float | None = None,
    ) -> CacheHit | None:
        with self._lock:
            row = self._con.execute(
                "SELECT payload, fetched_at, ttl_s FROM api_cache WHERE endpoint = ? AND req_hash = ?",
                (endpoint, req_hash),
            ).fetchone()
            if row is None:
                return None
            payload, fetched_at, ttl_s = row
            cur_now = time.time() if now is None else float(now)
            eff_max_age = float(ttl_s) if max_age is None else float(max_age)
            status = classify_cache_entry(fetched_at, cur_now, float(ttl_s), eff_max_age)
            if status == "expired":
                return None
            try:
                data = decode_payload(payload)
            except (ValueError, zlib.error):
                return None
            self._con.execute(
                "UPDATE api_cache SET last_used_at = ? WHERE endpoint = ? AND req_hash = ?",
                (cur_now, endpoint, req_hash),
            )
            return CacheHit(
                data=data,
                stale=(status == "stale"),
                fetched_at=float(fetched_at),
                age_s=max(0.0, cur_now - float(fetched_at)),
            )

    def put_api(
        self,
        endpoint: str,
        req_hash: str,
        value,
        ttl_s: float = 300.0,
        now: float | None = None,
    ) -> None:
        if contains_secret(value):
            raise SecretRefused("api payload contains secret data")
        blob = encode_payload(value)
        size_bytes = len(blob)
        if size_bytes > self.max_bytes:
            raise ValueError(f"api payload size {size_bytes} exceeds max_bytes {self.max_bytes}")
        ts = time.time() if now is None else float(now)
        with self._tx() as con:
            con.execute(
                "INSERT INTO api_cache (endpoint, req_hash, payload, size_bytes, fetched_at, ttl_s, last_used_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(endpoint, req_hash) DO UPDATE SET "
                "payload = excluded.payload, size_bytes = excluded.size_bytes, "
                "fetched_at = excluded.fetched_at, ttl_s = excluded.ttl_s, "
                "last_used_at = excluded.last_used_at",
                (endpoint, req_hash, sqlite3.Binary(blob), size_bytes, ts, float(ttl_s), ts),
            )
            self._evict_lru(con)
