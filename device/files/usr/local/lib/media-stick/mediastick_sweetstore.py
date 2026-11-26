#!/usr/bin/env python3
"""Canonical disk-backed WAL SQLite Anti-Corruption Layer for SWEET.TV entities.

Pure Core (no filesystem, SQLite, or network I/O):
  - strip_programme_prefix(title) -> str
  - base_show_title(title) -> str
  - compute_can_archive(catchup, catchup_duration, available, time_start, now) -> bool
  - normalize_channels_payload(doc, now) -> dict
  - normalize_title_payload(detail, now) -> tuple[dict, list[dict]]

Thin I/O Shell (SQLite WAL mode, stdlib only, zero xbmc imports):
  - SweetStore (/var/cache/media-stick/sweettv/sweettv.db)
  - default_store() / reset_default_store()
"""
from __future__ import annotations

from datetime import date, timedelta
import json
import os
import re
import sqlite3
import sys
import threading
import time
import zlib

_LIB_DIR = os.path.dirname(os.path.abspath(__file__))
if _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

import mediastick_store as ms_core  # noqa: E402

DEFAULT_DB_PATH = "/var/cache/media-stick/sweettv/sweettv.db"
DEFAULT_FUTURE_DAYS = 3

_PREFIX_RE = re.compile(
    r"^\s*(?:(?:прем[ь'’]?[еє]ра|новинка|анонс|х/ф|т/с|д/ф|м/ф|д/с|м/с)(?![\w-])(?:[.!:,—-]+\s*|\s+))+",
    re.IGNORECASE,
)
_SHOW_MARKER_RE = re.compile(
    r"(?:\s*[—\-.,:]+\s*|\s+)(?:Season|Episode|Сезон|Серія|Серия|Епізод|Эпизод|Випуск|Выпуск|Частина|Часть)\b\s*[0-9]+\b.*$",
    re.IGNORECASE,
)
_DATE_KEY_RE = re.compile(r"^([0-9]{4})-([0-9]{2})-([0-9]{2})$")
_QUOTE_PAIRS = (
    ('"', '"'),
    ("«", "»"),
    ("„", "“"),
    ("“", "”"),
)

_ALL_TABLES = (
    "meta",
    "channel_categories",
    "channels",
    "programmes",
    "titles",
    "episodes",
    "collections",
    "search_index",
    "swr_cache",
)


def _safe_int(val, default=0):
    if isinstance(val, bool) or val is None:
        return default
    if isinstance(val, (int, float)):
        return int(val) if val == val and abs(val) < 10 ** 15 else default
    if isinstance(val, str) and re.fullmatch(r"\s*-?[0-9]{1,15}\s*", val):
        return int(val)
    return default


def _safe_ts(val, default=0) -> int:
    n = _safe_int(val, None)
    if n is None:
        return default
    return n // 1000 if n > 10 ** 11 else n


def _safe_float(val, default=0.0) -> float:
    if isinstance(val, bool) or val is None:
        return default
    try:
        f = float(val)
        return f if f == f else default
    except (TypeError, ValueError):
        return default


def _safe_str(val, limit=512) -> str:
    if not isinstance(val, str):
        return ""
    return " ".join("".join(ch if ch.isprintable() else " " for ch in val).split())[:limit]


def _https_url(url, limit=400) -> str:
    if not isinstance(url, str):
        return ""
    u = url.strip()
    if u.startswith("//"):
        return ("https:" + u)[:limit]
    if u.startswith("http://"):
        return ("https://" + u[7:])[:limit]
    return u[:limit] if u.startswith("https://") else ""


def _clean_id(val) -> str:
    n = _safe_int(val, 0)
    return str(n) if n > 0 else ""


def _day_key(ts: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(int(ts)))


def _day_bounds(day_key: str) -> tuple[int, int] | None:
    m = _DATE_KEY_RE.match(str(day_key or ""))
    if not m:
        return None
    try:
        d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None
    nxt = d + timedelta(days=1)
    lo = int(time.mktime((d.year, d.month, d.day, 0, 0, 0, 0, 0, -1)))
    hi = int(time.mktime((nxt.year, nxt.month, nxt.day, 0, 0, 0, 0, 0, -1)))
    return lo, hi


def _strip_outer_quotes(text: str) -> str:
    s = text.strip()
    while len(s) >= 2:
        matched = False
        for left_q, right_q in _QUOTE_PAIRS:
            if s.startswith(left_q) and s.endswith(right_q):
                inner = s[len(left_q):-len(right_q)].strip()
                if inner:
                    s = inner
                    matched = True
                    break
        if not matched:
            break
    return s


# ---- Pure Core normalizers (no filesystem, SQLite, or network I/O) ----------------------------

def strip_programme_prefix(title) -> str:
    """Strip leading promotional/format prefixes and outer quotes for title grouping."""
    if not isinstance(title, str):
        return ""
    raw_norm = " ".join(title.split())
    if not raw_norm:
        return ""
    cleaned = _PREFIX_RE.sub("", raw_norm).strip()
    cleaned = _strip_outer_quotes(cleaned)
    cleaned = _PREFIX_RE.sub("", cleaned).strip()
    cleaned = _strip_outer_quotes(cleaned)
    return " ".join(cleaned.split()) or raw_norm


def base_show_title(title) -> str:
    """Strip leading promotional prefixes and trailing season/episode suffixes for show grouping."""
    cleaned = strip_programme_prefix(title)
    if not cleaned:
        return ""
    stripped = _SHOW_MARKER_RE.sub("", cleaned).strip()
    if stripped and stripped != cleaned:
        return strip_programme_prefix(stripped)
    for sep in (" — ", " - "):
        if sep in cleaned:
            head, tail = cleaned.split(sep, 1)
            if head and any(ch.isdigit() for ch in tail[:12]):
                return strip_programme_prefix(head)
    if ". " in cleaned:
        head, tail = cleaned.split(". ", 1)
        if head and any(ch.isdigit() for ch in tail):
            return strip_programme_prefix(head)
    return cleaned


def compute_can_archive(catchup, catchup_duration, available, time_start, now) -> bool:
    """Return True if a programme is within the channel's catch-up archive window."""
    if not bool(catchup) or not bool(available):
        return False
    dur = _safe_int(catchup_duration, 0)
    t_start = _safe_ts(time_start, 0)
    now_ts = _safe_ts(now, 0)
    if dur <= 0 or t_start <= 0 or t_start > now_ts:
        return False
    return (now_ts - t_start) <= dur * 86400


def _parse_int_list(values) -> list[int]:
    out: list[int] = []
    if not isinstance(values, (list, tuple)):
        return out
    for item in values:
        v = _safe_int(item, None)
        if v is not None and v not in out:
            out.append(v)
    return out


def _normalize_epg_record(
    p: dict,
    cid: str,
    catchup: bool,
    catchup_duration: int,
    ch_available: bool,
    now_ts: int,
) -> dict | None:
    if not isinstance(p, dict):
        return None
    eid = _clean_id(p.get("id") if "id" in p else p.get("epg"))
    t_start = _safe_ts(p.get("time_start") if "time_start" in p else p.get("start"), 0)
    t_stop = _safe_ts(p.get("time_stop") if "time_stop" in p else p.get("stop"), 0)
    title = _safe_str(p.get("text") if p.get("text") is not None else p.get("title"), 200)
    if not eid or t_start <= 0 or not title:
        return None
    if t_stop <= t_start:
        t_stop = t_start
    prog_avail = p.get("available") is not False
    explicit_arch = p.get("can_archive") if "can_archive" in p else p.get("playable_in_archive")
    if isinstance(explicit_arch, bool):
        can_arch = explicit_arch and prog_avail
    else:
        can_arch = compute_can_archive(
            catchup and ch_available,
            catchup_duration,
            prog_avail,
            t_start,
            now_ts,
        )
    sid_int = _safe_int(p.get("tv_show_id") if p.get("tv_show_id") is not None else p.get("show_id"), 0)
    show_id = str(sid_int) if sid_int > 0 else ""
    season_num = max(
        0,
        _safe_int(p.get("season_number") if p.get("season_number") is not None else p.get("season"), 0),
    )
    episode_num = max(
        0,
        _safe_int(p.get("episode_number") if p.get("episode_number") is not None else p.get("episode"), 0),
    )
    image_url = _https_url(p.get("image_url"))
    preview_url = (
        _https_url(p.get("preview_url_ext"))
        or _https_url(p.get("preview_url"))
        or _https_url(p.get("preview"))
    )
    return {
        "epg_id": eid,
        "cid": cid,
        "title": title,
        "base_title": base_show_title(title),
        "description": _safe_str(p.get("description"), 1000),
        "show_id": show_id,
        "season_num": season_num,
        "episode_num": episode_num,
        "time_start": t_start,
        "time_stop": t_stop,
        "day_key": _day_key(t_start),
        "image_url": image_url,
        "preview_url": preview_url,
        "can_archive": bool(can_arch),
        "available": bool(prog_avail),
    }


def normalize_channels_payload(doc, now) -> dict:
    """Normalize a ChannelService/GetChannels document into categories, channels, and programmes."""
    empty = {"status": "", "categories": [], "channels": [], "programmes": []}
    if not isinstance(doc, dict):
        return empty
    now_ts = _safe_ts(now, 0)

    raw_status = doc.get("status")
    if isinstance(raw_status, str) and raw_status.strip():
        status = _safe_str(raw_status, 64)
    elif isinstance(doc.get("list"), list):
        status = "OK"
    else:
        status = ""

    cat_candidates = []
    seen_cats: set[int] = set()
    raw_cats = doc.get("categories")
    if isinstance(raw_cats, list):
        for idx, cat in enumerate(raw_cats):
            if not isinstance(cat, dict):
                continue
            cat_id = _safe_int(cat.get("id"), None)
            if cat_id is None or cat_id in seen_cats:
                continue
            seen_cats.add(cat_id)
            caption = _safe_str(cat.get("caption") if cat.get("caption") is not None else cat.get("name"), 120)
            sort_ord = _safe_int(cat.get("order"), 1_000_000 + idx)
            cat_candidates.append((sort_ord, idx, {"id": cat_id, "caption": caption}))
    cat_candidates.sort(key=lambda item: (item[0], item[1]))
    categories = [item[2] for item in cat_candidates]

    channels = []
    programmes = []
    seen_cids: set[str] = set()
    raw_list = doc.get("list")
    if isinstance(raw_list, list):
        for ch in raw_list:
            if not isinstance(ch, dict):
                continue
            cid = _clean_id(ch.get("id"))
            if not cid or cid in seen_cids:
                continue
            seen_cids.add(cid)
            name = _safe_str(ch.get("name"), 120) or cid
            avail = ch.get("available") is not False
            catchup = bool(ch.get("catchup"))
            cdur = max(0, _safe_int(ch.get("catchup_duration"), 0))
            if "epg_days_future" in ch and ch.get("epg_days_future") is not None:
                future_days = max(0, _safe_int(ch.get("epg_days_future"), DEFAULT_FUTURE_DAYS))
            else:
                future_days = DEFAULT_FUTURE_DAYS
            icon_v2 = _safe_str(ch.get("icon_v2_url"), 400)
            icon_plain = _safe_str(ch.get("icon_url"), 400)
            icon_url = icon_v2 or icon_plain
            banner_url = _safe_str(ch.get("banner_url"), 400)
            cat_ids = _parse_int_list(ch.get("category"))
            channels.append({
                "cid": cid,
                "name": name,
                "number": _safe_int(ch.get("number"), 0),
                "slug": _safe_str(ch.get("slug"), 120),
                "icon_url": icon_url,
                "icon_v2_url": icon_v2 or icon_url,
                "banner_url": banner_url,
                "catchup": catchup,
                "catchup_duration": cdur,
                "epg_days_future": future_days,
                "available": avail,
                "is_fast_channel": bool(ch.get("is_fast_channel")),
                "quality": _safe_int(ch.get("quality"), 0),
                "category": cat_ids,
            })
            raw_epg = ch.get("epg")
            if isinstance(raw_epg, list):
                seen_epg: set[str] = set()
                for p in raw_epg:
                    pr = _normalize_epg_record(p, cid, catchup, cdur, avail, now_ts)
                    if pr and pr["epg_id"] not in seen_epg:
                        seen_epg.add(pr["epg_id"])
                        programmes.append(pr)

    return {
        "status": status,
        "categories": categories,
        "channels": channels,
        "programmes": programmes,
    }


def _season_number(season: dict, fallback_idx: int) -> int:
    num = _safe_int(season.get("number"), None)
    if num is not None and num > 0:
        return num
    title = _safe_str(season.get("title"), 80)
    m = re.search(r"(\d+)", title)
    return int(m.group(1)) if m else fallback_idx + 1


def normalize_title_payload(detail, now) -> tuple[dict, list[dict]]:
    """Normalize VOD/show detail and sort seasons & episodes ascending."""
    if not isinstance(detail, dict) or detail.get("ok") is False:
        return {}, []
    tkey = _safe_str(detail.get("id"), 64)
    title = _safe_str(detail.get("title"), 200)
    if not tkey or not title:
        return {}, []
    now_ts = _safe_ts(now, 0)
    owner_id = _safe_int(detail.get("owner_id"), 0)

    raw_seasons = detail.get("seasons") if isinstance(detail.get("seasons"), list) else []
    norm_seasons = []
    for si, s in enumerate(raw_seasons):
        if not isinstance(s, dict):
            continue
        s_num = _season_number(s, si)
        s_id = _safe_int(s.get("id"), 0)
        s_title = _safe_str(s.get("title"), 120) or f"Сезон {s_num}"
        s_owner = _safe_int(s.get("owner_id"), owner_id)
        norm_eps = []
        for ei, ep in enumerate(s.get("episodes") if isinstance(s.get("episodes"), list) else ()):
            if not isinstance(ep, dict):
                continue
            ep_id = _safe_int(ep.get("episode_id") or ep.get("id"), 0)
            ep_num = _safe_int(ep.get("number"), ei + 1)
            ep_owner = _safe_int(ep.get("owner_id"), s_owner)
            ep_key = str(ep_id) if ep_id > 0 else f"s{s_num}:e{ep_num}:{ei}"
            norm_eps.append({
                "ep_key": ep_key,
                "id": ep_id,
                "episode_id": ep_id,
                "season_num": s_num,
                "episode_num": ep_num,
                "number": ep_num,
                "title": _safe_str(ep.get("title"), 200),
                "duration": max(0, _safe_int(ep.get("duration"), 0)),
                "preview": _https_url(ep.get("preview") or ep.get("preview_url") or ep.get("image_url")),
                "owner_id": ep_owner,
                "vod_url": _safe_str(ep.get("vod_url"), 400),
                "cid": _safe_str(str(ep.get("cid") or ""), 32),
                "epg_id": _safe_str(str(ep.get("epg") or ep.get("epg_id") or ""), 32),
                "time_start": _safe_ts(ep.get("start") or ep.get("time_start"), 0),
                "time_stop": _safe_ts(ep.get("stop") or ep.get("time_stop"), 0),
                "coming_soon": bool(ep.get("coming_soon")),
                "release_date": _safe_str(ep.get("release_date"), 32),
            })
        norm_eps.sort(key=lambda e: (e["episode_num"], e["id"], e["ep_key"]))
        norm_seasons.append({
            "id": s_id,
            "number": s_num,
            "title": s_title,
            "owner_id": s_owner,
            "episodes": norm_eps,
        })
    norm_seasons.sort(key=lambda s: (s["number"], s["id"]))

    ep_rows: list[dict] = []
    if norm_seasons:
        for s in norm_seasons:
            for ep in s["episodes"]:
                ep_rows.append(dict(ep, title_key=tkey))
    elif isinstance(detail.get("episodes"), list):
        for ei, ep in enumerate(detail["episodes"]):
            if not isinstance(ep, dict):
                continue
            eid = _safe_str(str(ep.get("epg") or ep.get("id") or f"ep:{ei}"), 64)
            cid = _safe_str(str(ep.get("cid") or ""), 32)
            ep_key = f"{cid}|{eid}" if cid else eid
            ep_rows.append({
                "title_key": tkey,
                "ep_key": ep_key,
                "id": _safe_int(ep.get("id"), 0),
                "episode_id": _safe_int(ep.get("episode_id") or ep.get("id"), 0),
                "season_num": 0,
                "episode_num": ei + 1,
                "number": ei + 1,
                "title": _safe_str(ep.get("title"), 200),
                "duration": max(0, _safe_int(ep.get("duration"), 0)),
                "preview": _https_url(ep.get("preview") or ep.get("image_url")),
                "owner_id": 0,
                "vod_url": _safe_str(ep.get("vod_url") or ep.get("url"), 400),
                "cid": cid,
                "epg_id": eid,
                "time_start": _safe_ts(ep.get("start") or ep.get("time_start"), 0),
                "time_stop": _safe_ts(ep.get("stop") or ep.get("time_stop"), 0),
                "coming_soon": bool(ep.get("coming_soon")),
                "release_date": _safe_str(ep.get("release_date"), 32),
            })

    if norm_seasons:
        kind = _safe_str(detail.get("kind"), 32) or "series"
    elif isinstance(detail.get("episodes"), list) and detail.get("episodes"):
        kind = _safe_str(detail.get("kind"), 32) or (
            "show_epg" if tkey.startswith("epg:") else "show_tv"
        )
    else:
        kind = _safe_str(detail.get("kind"), 32) or "movie"

    genres = _parse_int_list(detail.get("genres"))
    genre_names = [
        _safe_str(x, 80)
        for x in (detail.get("genre_names") or ())
        if isinstance(x, str) and _safe_str(x, 80)
    ]
    countries = [
        _safe_str(str(x), 64)
        for x in (detail.get("countries") or ())
        if _safe_str(str(x), 64)
    ]
    seasons_meta = [
        {"id": s["id"], "number": s["number"], "title": s["title"], "owner_id": s["owner_id"]}
        for s in norm_seasons
    ]
    released = detail.get("released") is not False
    t_row = {
        "title_key": tkey,
        "id": tkey,
        "kind": kind,
        "title": title,
        "subtitle": _safe_str(detail.get("subtitle"), 200),
        "description": _safe_str(detail.get("description"), 2000),
        "poster": _safe_str(detail.get("poster"), 400),
        "banner": _safe_str(detail.get("banner"), 400),
        "wide_art": _safe_str(detail.get("wide_art"), 400),
        "year": _safe_int(detail.get("year"), 0),
        "duration": _safe_int(detail.get("duration"), 0),
        "imdb": _safe_float(detail.get("imdb"), 0.0),
        "age_rating": _safe_str(detail.get("age_rating"), 32),
        "genres": genres,
        "genre_names": genre_names,
        "countries": countries,
        "owner_id": owner_id,
        "released": released,
        "vod_url": _safe_str(detail.get("vod_url"), 400) if released else "",
        "seasons_count": len(norm_seasons),
        "seasons_meta": seasons_meta,
        "seasons": norm_seasons,
        "updated_at": now_ts,
    }
    return t_row, ep_rows


# ---- Thin WAL SQLite Shell --------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channel_categories (
    cat_id INTEGER PRIMARY KEY,
    caption TEXT NOT NULL DEFAULT '',
    sort_order INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS channels (
    cid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    number INTEGER NOT NULL DEFAULT 0,
    slug TEXT NOT NULL DEFAULT '',
    icon_url TEXT NOT NULL DEFAULT '',
    icon_v2_url TEXT NOT NULL DEFAULT '',
    banner_url TEXT NOT NULL DEFAULT '',
    catchup INTEGER NOT NULL DEFAULT 0,
    catchup_duration INTEGER NOT NULL DEFAULT 0,
    epg_days_future INTEGER NOT NULL DEFAULT 3,
    available INTEGER NOT NULL DEFAULT 1,
    is_fast_channel INTEGER NOT NULL DEFAULT 0,
    quality INTEGER NOT NULL DEFAULT 0,
    category_json TEXT NOT NULL DEFAULT '[]',
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS programmes (
    cid TEXT NOT NULL,
    epg_id TEXT NOT NULL,
    title TEXT NOT NULL,
    base_title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    show_id TEXT NOT NULL DEFAULT '',
    season_num INTEGER NOT NULL DEFAULT 0,
    episode_num INTEGER NOT NULL DEFAULT 0,
    time_start INTEGER NOT NULL,
    time_stop INTEGER NOT NULL,
    day_key TEXT NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    preview_url TEXT NOT NULL DEFAULT '',
    can_archive INTEGER NOT NULL DEFAULT 0,
    available INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'epg',
    updated_at INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (cid, epg_id)
);
CREATE INDEX IF NOT EXISTS idx_prog_cid_window ON programmes(cid, time_start, time_stop);
CREATE INDEX IF NOT EXISTS idx_prog_cid_day ON programmes(cid, day_key, time_start);
CREATE INDEX IF NOT EXISTS idx_prog_show ON programmes(show_id);

CREATE TABLE IF NOT EXISTS titles (
    title_key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    subtitle TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    poster TEXT NOT NULL DEFAULT '',
    banner TEXT NOT NULL DEFAULT '',
    wide_art TEXT NOT NULL DEFAULT '',
    year INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 0,
    imdb REAL NOT NULL DEFAULT 0.0,
    age_rating TEXT NOT NULL DEFAULT '',
    genres_json TEXT NOT NULL DEFAULT '[]',
    genre_names_json TEXT NOT NULL DEFAULT '[]',
    countries_json TEXT NOT NULL DEFAULT '[]',
    seasons_meta_json TEXT NOT NULL DEFAULT '[]',
    owner_id INTEGER NOT NULL DEFAULT 0,
    released INTEGER NOT NULL DEFAULT 1,
    vod_url TEXT NOT NULL DEFAULT '',
    seasons_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS episodes (
    title_key TEXT NOT NULL,
    ep_key TEXT NOT NULL,
    ep_id INTEGER NOT NULL DEFAULT 0,
    season_num INTEGER NOT NULL DEFAULT 0,
    episode_num INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    duration INTEGER NOT NULL DEFAULT 0,
    preview TEXT NOT NULL DEFAULT '',
    owner_id INTEGER NOT NULL DEFAULT 0,
    vod_url TEXT NOT NULL DEFAULT '',
    cid TEXT NOT NULL DEFAULT '',
    epg_id TEXT NOT NULL DEFAULT '',
    time_start INTEGER NOT NULL DEFAULT 0,
    time_stop INTEGER NOT NULL DEFAULT 0,
    coming_soon INTEGER NOT NULL DEFAULT 0,
    release_date TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (title_key, ep_key)
);
CREATE INDEX IF NOT EXISTS idx_ep_title ON episodes(title_key, season_num, episode_num);

CREATE TABLE IF NOT EXISTS collections (
    col_id TEXT PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    items_json TEXT NOT NULL DEFAULT '[]',
    updated_at INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS search_index (
    norm_key TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    display_title TEXT NOT NULL,
    rank_boost INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (entity_type, entity_id)
);
CREATE INDEX IF NOT EXISTS idx_search_norm ON search_index(norm_key);

CREATE TABLE IF NOT EXISTS swr_cache (
    key TEXT PRIMARY KEY,
    payload BLOB NOT NULL,
    size_bytes INTEGER NOT NULL,
    fetched_at REAL NOT NULL,
    ttl_s REAL NOT NULL,
    last_used_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_swr_last_used ON swr_cache(last_used_at);
"""

_SCHEMA_VERSION = "2"


class SweetStore:
    """Thread-safe WAL SQLite store for normalized SWEET.TV catalog data."""

    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or os.environ.get("MEDIASTICK_SWEETSTORE_DB") or DEFAULT_DB_PATH
        self._lock = threading.RLock()
        self._conn = self._open(self.db_path)

    def _open(self, path: str) -> sqlite3.Connection:
        if path != ":memory:":
            parent = os.path.dirname(os.path.abspath(path))
            if parent:
                os.makedirs(parent, exist_ok=True)
        conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA busy_timeout=3000")
        self._ensure_schema(conn)
        return conn

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection) -> None:
        migrations = (
            ("titles", "wide_art", "TEXT NOT NULL DEFAULT ''"),
            ("titles", "released", "INTEGER NOT NULL DEFAULT 1"),
            ("episodes", "coming_soon", "INTEGER NOT NULL DEFAULT 0"),
            ("episodes", "release_date", "TEXT NOT NULL DEFAULT ''"),
        )
        cols_by_table: dict[str, set[str]] = {}
        for tbl, col, ddl in migrations:
            if tbl not in cols_by_table:
                cols_by_table[tbl] = {
                    r[1] for r in conn.execute(f"PRAGMA table_info('{tbl}')").fetchall()
                }
            if col not in cols_by_table[tbl]:
                conn.execute(f"ALTER TABLE {tbl} ADD COLUMN {col} {ddl}")
                cols_by_table[tbl].add(col)

    @staticmethod
    def _ensure_schema(conn: sqlite3.Connection) -> None:
        existing = {
            r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        needs_reset = False
        if "programmes" in existing and "meta" not in existing:
            needs_reset = True
        elif "meta" in existing:
            ver_row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
            if ver_row is not None and ver_row[0] != _SCHEMA_VERSION:
                needs_reset = True
        if needs_reset:
            for tbl in _ALL_TABLES:
                conn.execute(f"DROP TABLE IF EXISTS {tbl}")
        conn.executescript(_SCHEMA)
        SweetStore._ensure_columns(conn)
        conn.commit()

    def close(self) -> None:
        with self._lock:
            conn = self._conn
            self._conn = None
            if conn is not None:
                conn.close()

    def _get_meta(self, key: str, default: str = "") -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row is not None else default

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )

    def record_sync_error(self, code: str, now=None) -> None:
        """Record a channel sync error without wiping any previously synced catalog."""
        if ms_core.contains_secret(code):
            raise ms_core.SecretRefused("sync error contains secret data")
        err_code = _safe_str(str(code or "ERROR"), 64) or "ERROR"
        ts = int(now if now is not None else time.time())
        with self._lock:
            self._set_meta("last_sync_error", err_code)
            self._set_meta("last_sync_error_at", str(ts))
            self._conn.commit()

    def upsert_channels(self, channels_doc, now=None) -> int:
        """Atomically reconcile channels, categories, inline EPG, and search_index."""
        if ms_core.contains_secret(channels_doc):
            raise ms_core.SecretRefused("channels payload contains secret data")
        if not isinstance(channels_doc, dict):
            return 0
        ts = int(now if now is not None else time.time())
        norm = normalize_channels_payload(channels_doc, ts)
        if "status" in channels_doc and norm["status"] != "OK":
            self.record_sync_error(norm["status"] or "ERROR", now=ts)
            return 0
        if norm["status"] != "OK":
            return 0

        ch_rows = [
            (
                ch["cid"],
                ch["name"],
                ch["number"],
                ch["slug"],
                ch["icon_url"],
                ch["icon_v2_url"],
                ch["banner_url"],
                1 if ch["catchup"] else 0,
                ch["catchup_duration"],
                ch["epg_days_future"],
                1 if ch["available"] else 0,
                1 if ch["is_fast_channel"] else 0,
                ch["quality"],
                json.dumps(ch["category"], separators=(",", ":")),
                ts,
            )
            for ch in norm["channels"]
        ]
        search_rows = [
            (ch["name"].casefold(), "channel", ch["cid"], ch["name"], 100 if ch["available"] else 10)
            for ch in norm["channels"]
        ]
        prog_rows = [
            (
                pr["cid"],
                pr["epg_id"],
                pr["title"],
                pr["base_title"],
                pr["description"],
                pr["show_id"],
                pr["season_num"],
                pr["episode_num"],
                pr["time_start"],
                pr["time_stop"],
                pr["day_key"],
                pr["image_url"],
                pr["preview_url"],
                1 if pr["can_archive"] else 0,
                1 if pr["available"] else 0,
                "channels",
                ts,
            )
            for pr in norm["programmes"]
        ]
        new_cids = [ch["cid"] for ch in norm["channels"]]

        with self._lock:
            if new_cids:
                placeholders = ",".join("?" for _ in new_cids)
                self._conn.execute(f"DELETE FROM channels WHERE cid NOT IN ({placeholders})", new_cids)
                self._conn.execute(f"DELETE FROM programmes WHERE cid NOT IN ({placeholders})", new_cids)
                self._conn.execute(
                    f"DELETE FROM search_index WHERE entity_type = 'channel' AND entity_id NOT IN ({placeholders})",
                    new_cids,
                )
            else:
                self._conn.execute("DELETE FROM channels")
                self._conn.execute("DELETE FROM programmes")
                self._conn.execute("DELETE FROM search_index WHERE entity_type = 'channel'")

            if "categories" in channels_doc and isinstance(channels_doc.get("categories"), list):
                self._conn.execute("DELETE FROM channel_categories")
                if norm["categories"]:
                    self._conn.executemany(
                        "INSERT INTO channel_categories(cat_id, caption, sort_order) VALUES (?, ?, ?)",
                        [(cat["id"], cat["caption"], idx) for idx, cat in enumerate(norm["categories"])],
                    )

            if ch_rows:
                self._conn.executemany(
                    """INSERT INTO channels(
                         cid, name, number, slug, icon_url, icon_v2_url, banner_url,
                         catchup, catchup_duration, epg_days_future, available,
                         is_fast_channel, quality, category_json, updated_at
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(cid) DO UPDATE SET
                         name=excluded.name, number=excluded.number, slug=excluded.slug,
                         icon_url=excluded.icon_url, icon_v2_url=excluded.icon_v2_url,
                         banner_url=excluded.banner_url, catchup=excluded.catchup,
                         catchup_duration=excluded.catchup_duration,
                         epg_days_future=excluded.epg_days_future,
                         available=excluded.available, is_fast_channel=excluded.is_fast_channel,
                         quality=excluded.quality, category_json=excluded.category_json,
                         updated_at=excluded.updated_at""",
                    ch_rows,
                )
            if search_rows:
                self._conn.executemany(
                    """INSERT INTO search_index(norm_key, entity_type, entity_id, display_title, rank_boost)
                       VALUES (?, ?, ?, ?, ?)
                       ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                         norm_key=excluded.norm_key, display_title=excluded.display_title,
                         rank_boost=excluded.rank_boost""",
                    search_rows,
                )
            if prog_rows:
                self._upsert_prog_rows(prog_rows)

            self._set_meta("channels_updated_at", str(ts))
            self._set_meta("last_sync_error", "")
            self._conn.commit()
        return len(ch_rows)

    def _upsert_prog_rows(self, prog_rows: list[tuple]) -> None:
        self._conn.executemany(
            """INSERT INTO programmes(
                 cid, epg_id, title, base_title, description, show_id,
                 season_num, episode_num, time_start, time_stop, day_key,
                 image_url, preview_url, can_archive, available, source, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(cid, epg_id) DO UPDATE SET
                 title=CASE WHEN excluded.title != '' THEN excluded.title ELSE programmes.title END,
                 base_title=CASE WHEN excluded.base_title != '' THEN excluded.base_title ELSE programmes.base_title END,
                 description=CASE WHEN excluded.description != '' THEN excluded.description ELSE programmes.description END,
                 show_id=CASE WHEN excluded.show_id != '' THEN excluded.show_id ELSE programmes.show_id END,
                 season_num=CASE WHEN excluded.season_num > 0 THEN excluded.season_num ELSE programmes.season_num END,
                 episode_num=CASE WHEN excluded.episode_num > 0 THEN excluded.episode_num ELSE programmes.episode_num END,
                 time_start=CASE WHEN excluded.time_start > 0 THEN excluded.time_start ELSE programmes.time_start END,
                 time_stop=CASE WHEN excluded.time_stop > 0 THEN excluded.time_stop ELSE programmes.time_stop END,
                 day_key=CASE WHEN excluded.day_key != '' THEN excluded.day_key ELSE programmes.day_key END,
                 image_url=CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE programmes.image_url END,
                 preview_url=CASE WHEN excluded.preview_url != '' THEN excluded.preview_url ELSE programmes.preview_url END,
                 can_archive=MAX(programmes.can_archive, excluded.can_archive),
                 available=excluded.available,
                 source=excluded.source,
                 updated_at=excluded.updated_at""",
            prog_rows,
        )

    def get_channels_payload(self, now=None) -> dict:
        """Reconstruct canonical GetChannels-compatible payload from SQLite."""
        with self._lock:
            updated_raw = self._get_meta("channels_updated_at", "")
            sync_err = self._get_meta("last_sync_error", "")
            ch_rows = self._conn.execute(
                "SELECT * FROM channels ORDER BY CASE WHEN number > 0 THEN 0 ELSE 1 END, number ASC, CAST(cid AS INTEGER) ASC"
            ).fetchall()
            if not ch_rows and not updated_raw:
                if sync_err:
                    return {"status": "error", "error": sync_err}
                return {}
            cat_rows = self._conn.execute(
                "SELECT cat_id, caption FROM channel_categories ORDER BY sort_order ASC, cat_id ASC"
            ).fetchall()
            updated_at = _safe_int(updated_raw, 0)
            ref_ts = int(now) if now is not None else (updated_at or int(time.time()))
            prog_rows = self._conn.execute(
                """SELECT cid, epg_id, title, description, show_id, season_num, episode_num,
                          time_start, time_stop, image_url, preview_url, available
                   FROM programmes
                   ORDER BY cid ASC, time_start ASC, epg_id ASC"""
            ).fetchall()

        epg_by_cid: dict[str, list[sqlite3.Row]] = {}
        for pr in prog_rows:
            epg_by_cid.setdefault(pr["cid"], []).append(pr)

        out_list = []
        for ch in ch_rows:
            cid = ch["cid"]
            cid_progs = epg_by_cid.get(cid, [])
            if len(cid_progs) > 120:
                prev_p = [p for p in cid_progs if int(p["time_stop"]) <= ref_ts][-15:]
                curr_next = [p for p in cid_progs if int(p["time_stop"]) > ref_ts][:105]
                cid_progs = prev_p + curr_next
            epg_out = [
                {
                    "id": int(p["epg_id"]) if str(p["epg_id"]).isdigit() else p["epg_id"],
                    "text": p["title"],
                    "description": p["description"],
                    "time_start": int(p["time_start"]),
                    "time_stop": int(p["time_stop"]),
                    "available": bool(p["available"]),
                    "tv_show_id": int(p["show_id"]) if p["show_id"] and str(p["show_id"]).isdigit() else 0,
                    "season_number": int(p["season_num"]),
                    "episode_number": int(p["episode_num"]),
                    "preview_url": p["preview_url"] or p["image_url"],
                    "image_url": p["image_url"],
                }
                for p in cid_progs
            ]
            out_list.append({
                "id": int(cid) if cid.isdigit() else cid,
                "name": ch["name"],
                "number": int(ch["number"]),
                "slug": ch["slug"],
                "icon_v2_url": ch["icon_v2_url"] or ch["icon_url"],
                "icon_url": ch["icon_url"],
                "banner_url": ch["banner_url"],
                "category": json.loads(ch["category_json"] or "[]"),
                "catchup": bool(ch["catchup"]),
                "catchup_duration": int(ch["catchup_duration"]),
                "epg_days_future": int(ch["epg_days_future"]),
                "available": bool(ch["available"]),
                "is_fast_channel": bool(ch["is_fast_channel"]),
                "quality": int(ch["quality"]),
                "epg": epg_out,
            })

        return {
            "status": "OK",
            "list": out_list,
            "categories": [{"id": int(c["cat_id"]), "caption": c["caption"]} for c in cat_rows],
            "updated_at": updated_at,
            "sync_error": sync_err,
        }

    def upsert_epg(
        self,
        cid,
        records,
        now=None,
        source: str = "epg",
        catchup=None,
        catchup_duration=None,
    ) -> int:
        """Normalize and store EPG records for channel cid."""
        if ms_core.contains_secret(records):
            raise ms_core.SecretRefused("epg records contain secret data")
        cid_s = _clean_id(cid)
        if not cid_s or not isinstance(records, list):
            return 0
        ts = int(now if now is not None else time.time())
        ch_avail = True
        with self._lock:
            row = self._conn.execute(
                "SELECT catchup, catchup_duration, available FROM channels WHERE cid = ?",
                (cid_s,),
            ).fetchone()
            if row is not None:
                if catchup is None:
                    catchup = bool(row["catchup"])
                if catchup_duration is None:
                    catchup_duration = int(row["catchup_duration"])
                ch_avail = bool(row["available"])

        eff_catchup = bool(catchup)
        eff_cdur = max(0, _safe_int(catchup_duration, 0))
        prog_rows = []
        seen_epg: set[str] = set()
        for p in records:
            pr = _normalize_epg_record(p, cid_s, eff_catchup, eff_cdur, ch_avail, ts)
            if not pr or pr["epg_id"] in seen_epg:
                continue
            seen_epg.add(pr["epg_id"])
            prog_rows.append((
                pr["cid"],
                pr["epg_id"],
                pr["title"],
                pr["base_title"],
                pr["description"],
                pr["show_id"],
                pr["season_num"],
                pr["episode_num"],
                pr["time_start"],
                pr["time_stop"],
                pr["day_key"],
                pr["image_url"],
                pr["preview_url"],
                1 if pr["can_archive"] else 0,
                1 if pr["available"] else 0,
                source,
                ts,
            ))
        if not prog_rows:
            return 0
        with self._lock:
            self._upsert_prog_rows(prog_rows)
            self._conn.commit()
        return len(prog_rows)

    def upsert_epg_records(self, records: list[dict], now=None, source: str = "epg_records") -> int:
        """Normalize and upsert raw TvService/GetEpgRecords.json records across channels."""
        if ms_core.contains_secret(records):
            raise ms_core.SecretRefused("epg records contain secret data")
        if not isinstance(records, (list, tuple)):
            return 0
        ts = int(now if now is not None else time.time())
        by_cid: dict[str, list[dict]] = {}
        for r in records:
            if not isinstance(r, dict):
                continue
            eid = _clean_id(r.get("id") if r.get("id") is not None else r.get("epg_id"))
            cid_s = _clean_id(r.get("channel_id") if r.get("channel_id") is not None else r.get("cid"))
            if not eid or not cid_s:
                continue
            by_cid.setdefault(cid_s, []).append(r)
        if not by_cid:
            return 0

        ch_info: dict[str, tuple[bool, int, bool]] = {}
        with self._lock:
            cids = list(by_cid.keys())
            for i in range(0, len(cids), 500):
                chunk = cids[i:i + 500]
                placeholders = ",".join("?" for _ in chunk)
                for row in self._conn.execute(
                    f"SELECT cid, catchup, catchup_duration, available FROM channels WHERE cid IN ({placeholders})",
                    chunk,
                ).fetchall():
                    ch_info[str(row["cid"])] = (
                        bool(row["catchup"]),
                        int(row["catchup_duration"]),
                        bool(row["available"]),
                    )

        deduped: dict[tuple[str, str], tuple] = {}
        for cid_s, recs in by_cid.items():
            catchup, cdur, ch_avail = ch_info.get(cid_s, (False, 0, True))
            for r in recs:
                eid = _clean_id(r.get("id") if r.get("id") is not None else r.get("epg_id"))
                title = _safe_str(r.get("text") if r.get("text") is not None else r.get("title"), 200)
                t_start = _safe_ts(r.get("time_start") if "time_start" in r else r.get("start"), 0)
                t_stop = _safe_ts(r.get("time_stop") if "time_stop" in r else r.get("stop"), 0)
                if t_start > 0 and t_stop <= t_start:
                    t_stop = t_start
                elif t_start <= 0:
                    t_start = 0
                    t_stop = 0
                day_key = _day_key(t_start) if t_start > 0 else ""
                prog_avail = r.get("available") is not False
                can_arch = (
                    compute_can_archive(catchup and ch_avail, cdur, prog_avail, t_start, ts)
                    if t_start > 0
                    else False
                )
                sid_int = _safe_int(
                    r.get("tv_show_id") if r.get("tv_show_id") is not None else r.get("show_id"),
                    0,
                )
                show_id = str(sid_int) if sid_int > 0 else ""
                season_num = max(
                    0,
                    _safe_int(r.get("season_number") if r.get("season_number") is not None else r.get("season"), 0),
                )
                episode_num = max(
                    0,
                    _safe_int(r.get("episode_number") if r.get("episode_number") is not None else r.get("episode"), 0),
                )
                image_url = _https_url(r.get("image_url"))
                preview_url = (
                    _https_url(r.get("preview_url_ext"))
                    or _https_url(r.get("preview_url"))
                    or _https_url(r.get("preview"))
                )
                deduped[(cid_s, eid)] = (
                    cid_s,
                    eid,
                    title,
                    base_show_title(title) if title else "",
                    _safe_str(r.get("description"), 1000),
                    show_id,
                    season_num,
                    episode_num,
                    t_start,
                    t_stop,
                    day_key,
                    image_url,
                    preview_url,
                    1 if can_arch else 0,
                    1 if prog_avail else 0,
                    source,
                    ts,
                )
        prog_rows = list(deduped.values())
        if not prog_rows:
            return 0
        with self._lock:
            self._upsert_prog_rows(prog_rows)
            self._conn.commit()
        return len(prog_rows)

    def epg_ids_missing_art(self, epg_ids) -> list[int]:
        """Return deduplicated positive int EPG IDs missing both image_url and preview_url in programmes."""
        ordered: list[int] = []
        seen: set[int] = set()
        for raw in epg_ids or ():
            eid = _safe_int(raw, 0)
            if eid > 0 and eid not in seen:
                seen.add(eid)
                ordered.append(eid)
        if not ordered:
            return []
        has_art: set[str] = set()
        str_ids = [str(x) for x in ordered]
        with self._lock:
            for i in range(0, len(str_ids), 500):
                chunk = str_ids[i:i + 500]
                placeholders = ",".join("?" for _ in chunk)
                rows = self._conn.execute(
                    f"SELECT DISTINCT epg_id FROM programmes "
                    f"WHERE epg_id IN ({placeholders}) AND (image_url != '' OR preview_url != '')",
                    chunk,
                ).fetchall()
                for row in rows:
                    has_art.add(str(row["epg_id"]))
        return [eid for eid in ordered if str(eid) not in has_art]

    @staticmethod
    def _effective_archive(r: sqlite3.Row, ch: sqlite3.Row | None, ts: int) -> tuple[bool, bool]:
        t_start = int(r["time_start"])
        prog_avail = bool(r["available"])
        if ch is not None:
            ch_avail = bool(ch["available"])
            arch = compute_can_archive(
                bool(ch["catchup"]) and ch_avail,
                int(ch["catchup_duration"]),
                prog_avail,
                t_start,
                ts,
            )
            return arch, ch_avail
        arch = bool(r["can_archive"]) and prog_avail and 0 < t_start <= ts
        return arch, True

    def channel_day(self, cid, day_key: str, now=None) -> list[dict]:
        """Return sorted programmes for (cid, day_key) with canonical archive/live flags."""
        cid_s = _clean_id(cid)
        if not cid_s:
            return []
        ts = int(now if now is not None else time.time())
        bounds = _day_bounds(day_key)
        with self._lock:
            ch = self._conn.execute(
                "SELECT catchup, catchup_duration, available FROM channels WHERE cid = ?",
                (cid_s,),
            ).fetchone()
            if bounds is not None:
                lo, hi = bounds
                rows = self._conn.execute(
                    """SELECT * FROM programmes
                       WHERE cid = ? AND (
                         (time_start < ? AND time_stop > ?)
                         OR (day_key = ? AND time_stop = time_start)
                       )
                       ORDER BY time_start ASC, epg_id ASC""",
                    (cid_s, hi, lo, str(day_key)),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT * FROM programmes
                       WHERE cid = ? AND day_key = ?
                       ORDER BY time_start ASC, epg_id ASC""",
                    (cid_s, str(day_key)),
                ).fetchall()

        out = []
        for r in rows:
            t_start = int(r["time_start"])
            t_stop = int(r["time_stop"])
            prog_avail = bool(r["available"])
            arch, ch_avail = self._effective_archive(r, ch, ts)
            live = t_start <= ts < t_stop
            playable = bool(arch or (live and ch_avail and prog_avail))
            out.append({
                "id": r["epg_id"],
                "epg": r["epg_id"],
                "cid": r["cid"],
                "title": r["title"],
                "text": r["title"],
                "base_title": r["base_title"],
                "description": r["description"],
                "show_id": r["show_id"],
                "season": int(r["season_num"]),
                "episode": int(r["episode_num"]),
                "time_start": t_start,
                "time_stop": t_stop,
                "start": t_start,
                "stop": t_stop,
                "day_key": r["day_key"],
                "preview": r["image_url"] or r["preview_url"],
                "image_url": r["image_url"],
                "live": live,
                "can_archive": arch,
                "playable_in_archive": arch,
                "archive": arch,
                "playable": playable,
                "available": prog_avail,
            })
        return out

    def _programme_summary(self, r: sqlite3.Row, ts: int) -> dict:
        t_start = int(r["time_start"])
        t_stop = int(r["time_stop"])
        prog_avail = bool(r["available"])
        if r["ch_catchup"] is not None:
            ch_avail = bool(r["ch_available"])
            arch = compute_can_archive(
                bool(r["ch_catchup"]) and ch_avail,
                int(r["ch_catchup_duration"] or 0),
                prog_avail,
                t_start,
                ts,
            )
        else:
            arch = bool(r["can_archive"]) and prog_avail and 0 < t_start <= ts
        return {
            "cid": r["cid"],
            "epg": r["epg_id"],
            "title": r["title"],
            "description": r["description"],
            "time_start": t_start,
            "time_stop": t_stop,
            "start": t_start,
            "stop": t_stop,
            "available": prog_avail,
            "can_archive": arch,
            "playable_in_archive": arch,
            "channel_name": r["channel_name"] or "",
            "show_id": r["show_id"],
            "season": int(r["season_num"]),
            "episode": int(r["episode_num"]),
            "preview": r["image_url"] or r["preview_url"],
            "image_url": r["image_url"],
        }

    def recall_programme(self, epg_id, cid=None, now=None) -> dict | None:
        """Return stored programme metadata for epg_id (scoped to cid when given), or None."""
        eid = _clean_id(epg_id)
        if not eid:
            return None
        ts = int(now if now is not None else time.time())
        sql_base = """
            SELECT p.*, c.name AS channel_name, c.catchup AS ch_catchup,
                   c.catchup_duration AS ch_catchup_duration, c.available AS ch_available
            FROM programmes p
            LEFT JOIN channels c ON c.cid = p.cid
        """
        with self._lock:
            if cid is not None:
                cid_s = _clean_id(cid)
                if not cid_s:
                    return None
                r = self._conn.execute(
                    sql_base + " WHERE p.cid = ? AND p.epg_id = ?",
                    (cid_s, eid),
                ).fetchone()
            else:
                r = self._conn.execute(
                    sql_base + " WHERE p.epg_id = ? ORDER BY p.updated_at DESC LIMIT 1",
                    (eid,),
                ).fetchone()
        if r is None:
            return None
        return self._programme_summary(r, ts)

    def programme_at(self, cid, wall_ts) -> dict | None:
        """Return the programme airing on cid at wall_ts (time_start <= int(wall_ts) < time_stop) with offset."""
        cid_s = _clean_id(cid)
        if not cid_s or isinstance(wall_ts, bool) or not isinstance(wall_ts, (int, float)):
            return None
        ts_int = int(wall_ts)
        with self._lock:
            r = self._conn.execute(
                """SELECT p.*, c.name AS channel_name, c.catchup AS ch_catchup,
                          c.catchup_duration AS ch_catchup_duration, c.available AS ch_available
                   FROM programmes p
                   LEFT JOIN channels c ON c.cid = p.cid
                   WHERE p.cid = ? AND p.time_start <= ? AND ? < p.time_stop
                   ORDER BY p.time_start DESC, p.epg_id DESC
                   LIMIT 1""",
                (cid_s, ts_int, ts_int),
            ).fetchone()
        if r is None:
            return None
        out = self._programme_summary(r, ts_int)
        out["offset"] = ts_int - out["time_start"]
        return out

    def adjacent_programmes(self, cid, epg_id) -> tuple[dict | None, dict | None]:
        """Return (prev_prog, next_prog) on cid ordered by time_start."""
        cid_s = _clean_id(cid)
        eid = _clean_id(epg_id)
        if not cid_s or not eid:
            return None, None
        ts = int(time.time())
        sql_base = """
            SELECT p.*, c.name AS channel_name, c.catchup AS ch_catchup,
                   c.catchup_duration AS ch_catchup_duration, c.available AS ch_available
            FROM programmes p
            LEFT JOIN channels c ON c.cid = p.cid
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT time_start FROM programmes WHERE cid = ? AND epg_id = ?",
                (cid_s, eid),
            ).fetchone()
            if cur is None:
                return None, None
            t_start = int(cur["time_start"])
            prev_r = self._conn.execute(
                sql_base
                + """ WHERE p.cid = ? AND p.epg_id != ?
                      AND (p.time_start < ? OR (p.time_start = ? AND p.epg_id < ?))
                      ORDER BY p.time_start DESC, p.epg_id DESC LIMIT 1""",
                (cid_s, eid, t_start, t_start, eid),
            ).fetchone()
            next_r = self._conn.execute(
                sql_base
                + """ WHERE p.cid = ? AND p.epg_id != ?
                      AND (p.time_start > ? OR (p.time_start = ? AND p.epg_id > ?))
                      ORDER BY p.time_start ASC, p.epg_id ASC LIMIT 1""",
                (cid_s, eid, t_start, t_start, eid),
            ).fetchone()
        return (
            self._programme_summary(prev_r, ts) if prev_r is not None else None,
            self._programme_summary(next_r, ts) if next_r is not None else None,
        )

    def programmes_for_show(self, show_id) -> list[dict]:
        """Return stored EPG programme records matching tv_show_id."""
        sid = _clean_id(show_id)
        if not sid:
            return []
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM programmes WHERE show_id = ? ORDER BY time_start DESC",
                (sid,),
            ).fetchall()
        return [
            {
                "id": r["epg_id"],
                "channel_id": r["cid"],
                "text": r["title"],
                "description": r["description"],
                "tv_show_id": r["show_id"],
                "season_number": int(r["season_num"]),
                "episode_number": int(r["episode_num"]),
                "time_start": int(r["time_start"]),
                "time_stop": int(r["time_stop"]),
                "image_url": r["image_url"],
                "preview_url": r["preview_url"],
                "available": bool(r["available"]),
            }
            for r in rows
        ]

    def upsert_title_detail(self, detail, now=None) -> None:
        """Normalize and persist VOD/series/show detail and sorted seasons & episodes."""
        if ms_core.contains_secret(detail):
            raise ms_core.SecretRefused("title detail contains secret data")
        ts = int(now if now is not None else time.time())
        t_row, ep_rows = normalize_title_payload(detail, ts)
        if not t_row:
            return
        tkey = t_row["title_key"]
        with self._lock:
            self._conn.execute(
                """INSERT INTO titles(
                     title_key, kind, title, subtitle, description, poster, banner, wide_art,
                     year, duration, imdb, age_rating, genres_json, genre_names_json,
                     countries_json, seasons_meta_json, owner_id, released, vod_url,
                     seasons_count, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(title_key) DO UPDATE SET
                     kind=excluded.kind, title=excluded.title, subtitle=excluded.subtitle,
                     description=excluded.description, poster=excluded.poster, banner=excluded.banner,
                     wide_art=excluded.wide_art, year=excluded.year, duration=excluded.duration,
                     imdb=excluded.imdb, age_rating=excluded.age_rating, genres_json=excluded.genres_json,
                     genre_names_json=excluded.genre_names_json,
                     countries_json=excluded.countries_json,
                     seasons_meta_json=excluded.seasons_meta_json,
                     owner_id=excluded.owner_id, released=excluded.released,
                     vod_url=excluded.vod_url,
                     seasons_count=excluded.seasons_count, updated_at=excluded.updated_at""",
                (
                    tkey,
                    t_row["kind"],
                    t_row["title"],
                    t_row["subtitle"],
                    t_row["description"],
                    t_row["poster"],
                    t_row["banner"],
                    t_row["wide_art"],
                    t_row["year"],
                    t_row["duration"],
                    t_row["imdb"],
                    t_row["age_rating"],
                    json.dumps(t_row["genres"], ensure_ascii=False),
                    json.dumps(t_row["genre_names"], ensure_ascii=False),
                    json.dumps(t_row["countries"], ensure_ascii=False),
                    json.dumps(t_row["seasons_meta"], ensure_ascii=False),
                    t_row["owner_id"],
                    1 if t_row.get("released", True) else 0,
                    t_row["vod_url"],
                    t_row["seasons_count"],
                    ts,
                ),
            )
            self._conn.execute("DELETE FROM episodes WHERE title_key = ?", (tkey,))
            if ep_rows:
                self._conn.executemany(
                    """INSERT INTO episodes(
                         title_key, ep_key, ep_id, season_num, episode_num, title,
                         duration, preview, owner_id, vod_url, cid, epg_id,
                         time_start, time_stop, coming_soon, release_date
                       ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (
                            tkey,
                            ep["ep_key"],
                            ep["id"],
                            ep["season_num"],
                            ep["episode_num"],
                            ep["title"],
                            ep["duration"],
                            ep["preview"],
                            ep["owner_id"],
                            ep["vod_url"],
                            ep["cid"],
                            ep["epg_id"],
                            ep["time_start"],
                            ep["time_stop"],
                            1 if ep.get("coming_soon") else 0,
                            ep.get("release_date", ""),
                        )
                        for ep in ep_rows
                    ],
                )
            self._conn.commit()

    def get_title_detail(self, title_key: str) -> dict | None:
        """Return stored rich title metadata with reconstructed sorted seasons and episodes."""
        tkey = _safe_str(title_key, 64)
        if not tkey:
            return None
        with self._lock:
            r = self._conn.execute("SELECT * FROM titles WHERE title_key = ?", (tkey,)).fetchone()
            if r is None:
                return None
            ep_rows = self._conn.execute(
                """SELECT * FROM episodes WHERE title_key = ?
                   ORDER BY season_num ASC, episode_num ASC, ep_id ASC, ep_key ASC""",
                (tkey,),
            ).fetchall()

        seasons_meta = json.loads(r["seasons_meta_json"] or "[]")
        seasons_by_num: dict[int, dict] = {}
        for sm in seasons_meta:
            if isinstance(sm, dict):
                snum = _safe_int(sm.get("number"), 1)
                seasons_by_num[snum] = {
                    "id": _safe_int(sm.get("id"), 0),
                    "number": snum,
                    "title": _safe_str(sm.get("title"), 120) or f"Сезон {snum}",
                    "owner_id": _safe_int(sm.get("owner_id"), int(r["owner_id"])),
                    "episodes": [],
                }

        flat_episodes = []
        for ep in ep_rows:
            snum = int(ep["season_num"])
            ep_id = int(ep["ep_id"])
            ep_num = int(ep["episode_num"])
            if snum > 0:
                season_obj = seasons_by_num.setdefault(
                    snum,
                    {
                        "id": 0,
                        "number": snum,
                        "title": f"Сезон {snum}",
                        "owner_id": int(r["owner_id"]),
                        "episodes": [],
                    },
                )
                season_obj["episodes"].append({
                    "id": ep_id,
                    "episode_id": ep_id,
                    "number": ep_num,
                    "title": ep["title"],
                    "duration": int(ep["duration"]),
                    "preview": ep["preview"],
                    "owner_id": int(ep["owner_id"]),
                    "vod_url": ep["vod_url"],
                    "coming_soon": bool(ep["coming_soon"]),
                    "release_date": ep["release_date"],
                })
            else:
                flat_episodes.append({
                    "epg": ep["epg_id"],
                    "cid": ep["cid"],
                    "title": ep["title"],
                    "start": int(ep["time_start"]),
                    "stop": int(ep["time_stop"]),
                    "duration": int(ep["duration"]),
                    "preview": ep["preview"],
                    "image_url": ep["preview"],
                    "url": ep["vod_url"],
                    "available": True,
                })

        sorted_seasons = []
        for snum in sorted(seasons_by_num.keys()):
            s_obj = seasons_by_num[snum]
            s_obj["episodes"].sort(key=lambda e: (e["number"], e["id"]))
            sorted_seasons.append(s_obj)

        released = bool(r["released"]) if "released" in r.keys() else True
        out = {
            "ok": True,
            "id": r["title_key"],
            "kind": r["kind"],
            "title": r["title"],
            "subtitle": r["subtitle"],
            "description": r["description"],
            "poster": r["poster"],
            "banner": r["banner"],
            "wide_art": r["wide_art"] or r["banner"],
            "year": int(r["year"]),
            "duration": int(r["duration"]),
            "imdb": float(r["imdb"]),
            "age_rating": r["age_rating"],
            "genres": json.loads(r["genres_json"] or "[]"),
            "genre_names": json.loads(r["genre_names_json"] or "[]"),
            "countries": json.loads(r["countries_json"] or "[]"),
            "owner_id": int(r["owner_id"]),
            "released": released,
            "vod_url": r["vod_url"] if released else "",
            "seasons_count": len(sorted_seasons),
            "seasons": sorted_seasons,
        }
        if flat_episodes:
            out["episodes"] = flat_episodes
        return out

    def put_swr(self, key: str, value, ttl_s: float = 300.0, now: float | None = None) -> None:
        """Store compressed SWR payload under key after verifying zero secrets."""
        if ms_core.contains_secret({key: value}):
            raise ms_core.SecretRefused("swr payload contains secret data")
        blob = ms_core.encode_payload(value)
        size_bytes = len(blob)
        ts = time.time() if now is None else float(now)
        with self._lock:
            self._conn.execute(
                """INSERT INTO swr_cache(key, payload, size_bytes, fetched_at, ttl_s, last_used_at)
                   VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(key) DO UPDATE SET
                     payload=excluded.payload, size_bytes=excluded.size_bytes,
                     fetched_at=excluded.fetched_at, ttl_s=excluded.ttl_s,
                     last_used_at=excluded.last_used_at""",
                (str(key), sqlite3.Binary(blob), size_bytes, ts, float(ttl_s), ts),
            )
            self._conn.commit()

    def get_swr(self, key: str, max_age_s: float = 21600.0, now: float | None = None) -> ms_core.CacheHit | None:
        """Read SWR payload under key, returning CacheHit(data, stale, ...) or None when expired/missing."""
        cur_now = time.time() if now is None else float(now)
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, fetched_at, ttl_s FROM swr_cache WHERE key = ?",
                (str(key),),
            ).fetchone()
            if row is None:
                return None
            fetched_at = float(row["fetched_at"])
            ttl_s = float(row["ttl_s"])
            status = ms_core.classify_cache_entry(fetched_at, cur_now, ttl_s, float(max_age_s))
            if status == "expired":
                return None
            try:
                data = ms_core.decode_payload(row["payload"])
            except (ValueError, zlib.error):
                return None
            self._conn.execute(
                "UPDATE swr_cache SET last_used_at = ? WHERE key = ?",
                (cur_now, str(key)),
            )
            self._conn.commit()
        return ms_core.CacheHit(
            data=data,
            stale=(status == "stale"),
            fetched_at=fetched_at,
            age_s=max(0.0, cur_now - fetched_at),
        )

    def seed_from_channel_file(self, path: str, now=None) -> bool:
        """Seed channels from a JSON channelList file only when channels table is empty."""
        if not path or not os.path.isfile(path):
            return False
        with self._lock:
            has_rows = self._conn.execute("SELECT 1 FROM channels LIMIT 1").fetchone() is not None
            if has_rows:
                return False
        try:
            with open(path, encoding="utf-8") as f:
                doc = json.load(f)
        except (OSError, ValueError):
            return False
        return self.upsert_channels(doc, now=now) > 0

    def search_channels(self, query: str, available_only: bool = True) -> list[dict]:
        """Return stored channels matching query, ordered by availability and channel number."""
        q = _safe_str(query, 120).casefold()
        if not q:
            return []
        like = f"%{q}%"
        with self._lock:
            sql = """SELECT c.cid, c.name, c.number, c.slug, c.icon_url, c.catchup, c.catchup_duration, c.available
                     FROM channels c
                     JOIN search_index s ON s.entity_type = 'channel' AND s.entity_id = c.cid
                     WHERE s.norm_key LIKE ?"""
            if available_only:
                sql += " AND c.available = 1"
            sql += " ORDER BY c.available DESC, c.number ASC, c.name ASC"
            rows = self._conn.execute(sql, (like,)).fetchall()
        return [
            {
                "cid": r["cid"],
                "name": r["name"],
                "number": int(r["number"]),
                "slug": r["slug"],
                "icon_url": r["icon_url"],
                "catchup": bool(r["catchup"]),
                "catchup_duration": int(r["catchup_duration"]),
                "available": bool(r["available"]),
            }
            for r in rows
        ]

    def purge_expired(self, now=None, keep_days: int = 8) -> int:
        """Delete EPG programmes older than keep_days."""
        ts = int(now if now is not None else time.time())
        cutoff = ts - max(1, int(keep_days)) * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM programmes WHERE time_stop < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount

    def clear(self) -> None:
        """Wipe all cached catalog data on sign-out."""
        with self._lock:
            for tbl in _ALL_TABLES:
                self._conn.execute(f"DELETE FROM {tbl}")
            self._conn.commit()


_DEFAULT_STORE: SweetStore | None = None
_DEFAULT_LOCK = threading.Lock()


def default_store() -> SweetStore:
    """Return process-wide singleton SweetStore."""
    global _DEFAULT_STORE
    with _DEFAULT_LOCK:
        if _DEFAULT_STORE is None or _DEFAULT_STORE._conn is None:
            _DEFAULT_STORE = SweetStore()
        return _DEFAULT_STORE


def reset_default_store() -> None:
    """Close and reset the process-wide singleton SweetStore."""
    global _DEFAULT_STORE
    with _DEFAULT_LOCK:
        old = _DEFAULT_STORE
        _DEFAULT_STORE = None
    if old is not None:
        old.close()
