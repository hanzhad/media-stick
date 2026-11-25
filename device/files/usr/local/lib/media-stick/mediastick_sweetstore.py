#!/usr/bin/env python3
"""Canonical tmpfs WAL SQLite Anti-Corruption Store for SWEET.TV entities.

Normalizes raw SWEET.TV API payloads (channels, 7-day EPG programmes, VOD/TV
titles, episodes, collections) into stable internal contracts so TV UI and
Phone Remote never spread API quirks across callers.
"""
import json
import os
import re
import sqlite3
import threading
import time

DEFAULT_DB_PATH = "/run/media-stick/sweettv-catalog.db"

_PREFIX_RE = re.compile(
    r"^\s*(?:прем[ь'’]?[еє]ра\.?\s+|х/ф\s+|т/с\s+|м/ф\s+|д/ф\s+|д/с\s+)+",
    re.IGNORECASE,
)


def strip_programme_prefix(title):
    """Strip promotional/format prefixes like 'Премьера.' or 'Т/с' for grouping."""
    if not isinstance(title, str):
        return ""
    cleaned = _PREFIX_RE.sub("", title).strip()
    if len(cleaned) >= 2 and cleaned[0] in ('"', "«") and cleaned[-1] in ('"', "»"):
        inner = cleaned[1:-1].strip()
        if inner:
            cleaned = inner
    return " ".join(cleaned.split()) or " ".join(title.split())


def _day_key(ts):
    return time.strftime("%Y-%m-%d", time.localtime(int(ts)))


def _safe_int(val, default=0):
    if isinstance(val, bool) or val is None:
        return default
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_float(val, default=0.0):
    if isinstance(val, bool) or val is None:
        return default
    try:
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_str(val, limit=512):
    if not isinstance(val, str):
        return ""
    return " ".join(val.split())[:limit]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS channels (
    cid TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    number INTEGER NOT NULL DEFAULT 0,
    slug TEXT NOT NULL DEFAULT '',
    icon_url TEXT NOT NULL DEFAULT '',
    catchup INTEGER NOT NULL DEFAULT 0,
    catchup_duration INTEGER NOT NULL DEFAULT 0,
    available INTEGER NOT NULL DEFAULT 1,
    quality INTEGER NOT NULL DEFAULT 0,
    genres_json TEXT NOT NULL DEFAULT '[]',
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS programmes (
    epg_id TEXT PRIMARY KEY,
    cid TEXT NOT NULL,
    title TEXT NOT NULL,
    base_title TEXT NOT NULL,
    show_id TEXT NOT NULL DEFAULT '',
    time_start INTEGER NOT NULL,
    time_stop INTEGER NOT NULL,
    day_key TEXT NOT NULL,
    image_url TEXT NOT NULL DEFAULT '',
    can_archive INTEGER NOT NULL DEFAULT 0,
    available INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'epg',
    updated_at INTEGER NOT NULL DEFAULT 0
);
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
    year INTEGER NOT NULL DEFAULT 0,
    duration INTEGER NOT NULL DEFAULT 0,
    imdb REAL NOT NULL DEFAULT 0.0,
    age_rating TEXT NOT NULL DEFAULT '',
    genres_json TEXT NOT NULL DEFAULT '[]',
    countries_json TEXT NOT NULL DEFAULT '[]',
    owner_id INTEGER NOT NULL DEFAULT 0,
    vod_url TEXT NOT NULL DEFAULT '',
    seasons_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS episodes (
    ep_key TEXT PRIMARY KEY,
    title_key TEXT NOT NULL,
    season_num INTEGER NOT NULL DEFAULT 0,
    episode_num INTEGER NOT NULL DEFAULT 0,
    title TEXT NOT NULL DEFAULT '',
    duration INTEGER NOT NULL DEFAULT 0,
    preview TEXT NOT NULL DEFAULT '',
    vod_url TEXT NOT NULL DEFAULT '',
    cid TEXT NOT NULL DEFAULT '',
    epg_id TEXT NOT NULL DEFAULT '',
    time_start INTEGER NOT NULL DEFAULT 0,
    time_stop INTEGER NOT NULL DEFAULT 0
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
"""


class SweetStore:
    """Thread-safe WAL SQLite store for normalized SWEET.TV catalog data."""

    def __init__(self, db_path=None):
        self.db_path = db_path or os.environ.get("MEDIASTICK_SWEETSTORE_DB") or DEFAULT_DB_PATH
        self._lock = threading.RLock()
        self._conn = self._open(self.db_path)

    def _open(self, path):
        if path != ":memory:":
            parent = os.path.dirname(path)
            if parent:
                try:
                    os.makedirs(parent, exist_ok=True)
                except OSError:
                    path = ":memory:"
                    self.db_path = path
        try:
            conn = sqlite3.connect(path, check_same_thread=False, timeout=5.0)
        except sqlite3.Error:
            self.db_path = ":memory:"
            conn = sqlite3.connect(":memory:", check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
        conn.executescript(_SCHEMA)
        conn.commit()
        return conn

    def close(self):
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def upsert_channels(self, channels_doc, now=None):
        """Normalize and store channels + inline EPG records from ChannelService/GetChannels."""
        ts = int(now if now is not None else time.time())
        ch_list = []
        if isinstance(channels_doc, dict):
            ch_list = channels_doc.get("list") or []
        elif isinstance(channels_doc, list):
            ch_list = channels_doc
        if not isinstance(ch_list, list):
            return 0
        ch_rows = []
        search_rows = []
        epg_by_cid = {}
        for ch in ch_list:
            if not isinstance(ch, dict):
                continue
            cid = _safe_int(ch.get("id"))
            if cid <= 0:
                continue
            cid_s = str(cid)
            name = _safe_str(ch.get("name"), 120) or cid_s
            avail = 0 if ch.get("available") is False else 1
            catchup = 1 if ch.get("catchup") else 0
            cdur = max(0, _safe_int(ch.get("catchup_duration")))
            ch_rows.append((
                cid_s,
                name,
                _safe_int(ch.get("number")),
                _safe_str(ch.get("slug"), 120),
                _safe_str(ch.get("icon_v2_url") or ch.get("icon_url"), 400),
                catchup,
                cdur,
                avail,
                _safe_int(ch.get("quality")),
                json.dumps(ch.get("genres") or [], ensure_ascii=False),
                ts,
            ))
            search_rows.append((name.casefold(), "channel", cid_s, name, 100 if avail else 10))
            if isinstance(ch.get("epg"), list) and ch["epg"]:
                epg_by_cid[cid_s] = (ch["epg"], catchup, cdur)
        with self._lock:
            self._conn.executemany(
                """INSERT INTO channels(cid, name, number, slug, icon_url, catchup, catchup_duration,
                   available, quality, genres_json, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(cid) DO UPDATE SET
                     name=excluded.name, number=excluded.number, slug=excluded.slug,
                     icon_url=excluded.icon_url, catchup=excluded.catchup,
                     catchup_duration=excluded.catchup_duration, available=excluded.available,
                     quality=excluded.quality, genres_json=excluded.genres_json,
                     updated_at=excluded.updated_at""",
                ch_rows,
            )
            self._conn.executemany(
                """INSERT INTO search_index(norm_key, entity_type, entity_id, display_title, rank_boost)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(entity_type, entity_id) DO UPDATE SET
                     norm_key=excluded.norm_key, display_title=excluded.display_title,
                     rank_boost=excluded.rank_boost""",
                search_rows,
            )
            self._conn.commit()
        for cid_s, (recs, catchup, cdur) in epg_by_cid.items():
            self.upsert_epg(cid_s, recs, now=ts, source="channels", catchup=catchup, catchup_duration=cdur)
        return len(ch_rows)

    def upsert_epg(self, cid, records, now=None, source="epg", catchup=None, catchup_duration=None):
        """Normalize and store EPG records for a channel."""
        cid_s = str(_safe_int(cid) or _safe_str(cid, 32))
        if not cid_s or not isinstance(records, list):
            return 0
        ts = int(now if now is not None else time.time())
        if catchup is None or catchup_duration is None:
            with self._lock:
                row = self._conn.execute(
                    "SELECT catchup, catchup_duration FROM channels WHERE cid = ?", (cid_s,)
                ).fetchone()
                if row:
                    catchup = row["catchup"] if catchup is None else catchup
                    catchup_duration = row["catchup_duration"] if catchup_duration is None else catchup_duration
        catchup = int(bool(catchup))
        cdur = max(0, _safe_int(catchup_duration))
        prog_rows = []
        for p in records:
            if not isinstance(p, dict):
                continue
            eid = _safe_int(p.get("id"))
            t_start = _safe_int(p.get("time_start"))
            t_stop = _safe_int(p.get("time_stop"))
            title = _safe_str(p.get("text") or p.get("title"), 200)
            if eid <= 0 or t_start <= 0 or not title:
                continue
            if t_stop <= t_start:
                t_stop = t_start
            avail = 0 if p.get("available") is False else 1
            in_win = (
                bool(catchup)
                and cdur > 0
                and avail == 1
                and t_start <= ts
                and (ts - t_start) <= cdur * 86400
            )
            can_arch = 1 if (p.get("can_archive") or p.get("playable_in_archive") or p.get("archive") or in_win) else 0
            show_id = str(_safe_int(p.get("tv_show_id")) or "")
            if show_id == "0":
                show_id = ""
            prog_rows.append((
                str(eid),
                cid_s,
                title,
                strip_programme_prefix(title),
                show_id,
                t_start,
                t_stop,
                _day_key(t_start),
                _safe_str(p.get("image_url") or p.get("preview_url_ext"), 400),
                can_arch,
                avail,
                source,
                ts,
            ))
        if not prog_rows:
            return 0
        with self._lock:
            self._conn.executemany(
                """INSERT INTO programmes(epg_id, cid, title, base_title, show_id, time_start, time_stop,
                   day_key, image_url, can_archive, available, source, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(epg_id) DO UPDATE SET
                     cid=excluded.cid, title=excluded.title, base_title=excluded.base_title,
                     show_id=CASE WHEN excluded.show_id != '' THEN excluded.show_id ELSE programmes.show_id END,
                     time_start=excluded.time_start, time_stop=excluded.time_stop, day_key=excluded.day_key,
                     image_url=CASE WHEN excluded.image_url != '' THEN excluded.image_url ELSE programmes.image_url END,
                     can_archive=MAX(programmes.can_archive, excluded.can_archive),
                     available=excluded.available, source=excluded.source, updated_at=excluded.updated_at""",
                prog_rows,
            )
            self._conn.commit()
        return len(prog_rows)

    def channel_day(self, cid, day_key, now=None):
        """Return ordered normalized EPG programmes for a channel on YYYY-MM-DD."""
        cid_s = str(_safe_int(cid) or _safe_str(cid, 32))
        ts = int(now if now is not None else time.time())
        with self._lock:
            ch = self._conn.execute(
                "SELECT catchup, catchup_duration, available FROM channels WHERE cid = ?", (cid_s,)
            ).fetchone()
            rows = self._conn.execute(
                """SELECT epg_id, cid, title, base_title, show_id, time_start, time_stop,
                          day_key, image_url, can_archive, available
                   FROM programmes WHERE cid = ? AND day_key = ?
                   ORDER BY time_start ASC, epg_id ASC""",
                (cid_s, str(day_key)),
            ).fetchall()
        catchup = bool(ch["catchup"]) if ch else False
        cdur = int(ch["catchup_duration"]) if ch else 0
        out = []
        for r in rows:
            t_start = int(r["time_start"])
            t_stop = int(r["time_stop"])
            in_win = (
                catchup
                and cdur > 0
                and int(r["available"]) == 1
                and t_start <= ts
                and (ts - t_start) <= cdur * 86400
            )
            arch = bool(r["can_archive"] or in_win)
            live = t_start <= ts < t_stop
            out.append({
                "id": r["epg_id"],
                "epg": r["epg_id"],
                "cid": r["cid"],
                "title": r["title"],
                "text": r["title"],
                "base_title": r["base_title"],
                "show_id": r["show_id"],
                "time_start": t_start,
                "time_stop": t_stop,
                "start": t_start,
                "stop": t_stop,
                "day_key": r["day_key"],
                "image_url": r["image_url"],
                "live": live,
                "can_archive": arch,
                "playable_in_archive": arch,
                "archive": arch,
                "available": bool(r["available"]),
            })
        return out

    def recall_programme(self, epg_id):
        """Return stored programme metadata for an EPG ID, or None."""
        eid = str(_safe_int(epg_id) or _safe_str(epg_id, 32))
        if not eid:
            return None
        with self._lock:
            r = self._conn.execute(
                """SELECT epg_id, cid, title, base_title, show_id, time_start, time_stop,
                          day_key, image_url, can_archive, available
                   FROM programmes WHERE epg_id = ?""",
                (eid,),
            ).fetchone()
        if not r:
            return None
        return {
            "id": r["epg_id"],
            "epg": r["epg_id"],
            "cid": r["cid"],
            "title": r["title"],
            "base_title": r["base_title"],
            "show_id": r["show_id"],
            "time_start": int(r["time_start"]),
            "time_stop": int(r["time_stop"]),
            "day_key": r["day_key"],
            "image_url": r["image_url"],
            "can_archive": bool(r["can_archive"]),
            "playable_in_archive": bool(r["can_archive"]),
            "archive": bool(r["can_archive"]),
            "available": bool(r["available"]),
        }

    def upsert_title_detail(self, detail, now=None):
        """Store rich VOD/series/show detail and its episodes."""
        if not isinstance(detail, dict) or not detail.get("ok"):
            return False
        tkey = _safe_str(detail.get("id"), 64)
        title = _safe_str(detail.get("title"), 200)
        if not tkey or not title:
            return False
        ts = int(now if now is not None else time.time())
        seasons = detail.get("seasons") if isinstance(detail.get("seasons"), list) else []
        kind = "series" if seasons else _safe_str(detail.get("kind") or "movie", 32)
        with self._lock:
            self._conn.execute(
                """INSERT INTO titles(title_key, kind, title, subtitle, description, poster, banner,
                   year, duration, imdb, age_rating, genres_json, countries_json, owner_id, vod_url,
                   seasons_count, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(title_key) DO UPDATE SET
                     kind=excluded.kind, title=excluded.title, subtitle=excluded.subtitle,
                     description=excluded.description, poster=excluded.poster, banner=excluded.banner,
                     year=excluded.year, duration=excluded.duration, imdb=excluded.imdb,
                     age_rating=excluded.age_rating, genres_json=excluded.genres_json,
                     countries_json=excluded.countries_json, owner_id=excluded.owner_id,
                     vod_url=excluded.vod_url, seasons_count=excluded.seasons_count,
                     updated_at=excluded.updated_at""",
                (
                    tkey,
                    kind,
                    title,
                    _safe_str(detail.get("subtitle"), 200),
                    _safe_str(detail.get("description"), 2000),
                    _safe_str(detail.get("poster"), 400),
                    _safe_str(detail.get("banner"), 400),
                    _safe_int(detail.get("year")),
                    _safe_int(detail.get("duration")),
                    _safe_float(detail.get("imdb")),
                    _safe_str(detail.get("age_rating"), 32),
                    json.dumps(detail.get("genres") or [], ensure_ascii=False),
                    json.dumps(detail.get("countries") or [], ensure_ascii=False),
                    _safe_int(detail.get("owner_id")),
                    _safe_str(detail.get("vod_url"), 400),
                    len(seasons),
                    ts,
                ),
            )
            ep_rows = []
            for si, s in enumerate(seasons):
                if not isinstance(s, dict):
                    continue
                snum = _safe_int(s.get("number"), si + 1)
                for ei, ep in enumerate(s.get("episodes") or ()):
                    if not isinstance(ep, dict):
                        continue
                    eid = _safe_str(str(ep.get("episode_id") or ep.get("id") or f"{si}:{ei}"), 64)
                    ep_rows.append((
                        f"{tkey}:{eid}",
                        tkey,
                        snum,
                        _safe_int(ep.get("number"), ei + 1),
                        _safe_str(ep.get("title"), 200),
                        _safe_int(ep.get("duration")),
                        _safe_str(ep.get("preview"), 400),
                        _safe_str(ep.get("vod_url"), 400),
                        _safe_str(str(ep.get("cid") or ""), 32),
                        _safe_str(str(ep.get("epg") or ""), 32),
                        _safe_int(ep.get("start") or ep.get("time_start")),
                        _safe_int(ep.get("stop") or ep.get("time_stop")),
                    ))
            if ep_rows:
                self._conn.executemany(
                    """INSERT INTO episodes(ep_key, title_key, season_num, episode_num, title, duration,
                       preview, vod_url, cid, epg_id, time_start, time_stop)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(ep_key) DO UPDATE SET
                         season_num=excluded.season_num, episode_num=excluded.episode_num,
                         title=excluded.title, duration=excluded.duration, preview=excluded.preview,
                         vod_url=excluded.vod_url, cid=excluded.cid, epg_id=excluded.epg_id,
                         time_start=excluded.time_start, time_stop=excluded.time_stop""",
                    ep_rows,
                )
            self._conn.commit()
        return True

    def get_title_detail(self, title_key):
        """Return stored rich title metadata, or None."""
        tkey = _safe_str(title_key, 64)
        if not tkey:
            return None
        with self._lock:
            r = self._conn.execute("SELECT * FROM titles WHERE title_key = ?", (tkey,)).fetchone()
        if not r:
            return None
        return {
            "id": r["title_key"],
            "kind": r["kind"],
            "title": r["title"],
            "subtitle": r["subtitle"],
            "description": r["description"],
            "poster": r["poster"],
            "banner": r["banner"],
            "year": r["year"],
            "duration": r["duration"],
            "imdb": r["imdb"],
            "age_rating": r["age_rating"],
            "genres": json.loads(r["genres_json"] or "[]"),
            "countries": json.loads(r["countries_json"] or "[]"),
            "owner_id": r["owner_id"],
            "vod_url": r["vod_url"],
            "seasons_count": r["seasons_count"],
        }

    def search_channels(self, query, available_only=True):
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

    def purge_expired(self, now=None, keep_days=8):
        """Delete EPG programmes older than keep_days."""
        ts = int(now if now is not None else time.time())
        cutoff = ts - max(1, int(keep_days)) * 86400
        with self._lock:
            cur = self._conn.execute("DELETE FROM programmes WHERE time_stop < ?", (cutoff,))
            self._conn.commit()
            return cur.rowcount


_DEFAULT_STORE = None
_DEFAULT_LOCK = threading.Lock()


def default_store():
    """Return process-wide singleton SweetStore."""
    global _DEFAULT_STORE
    with _DEFAULT_LOCK:
        if _DEFAULT_STORE is None:
            _DEFAULT_STORE = SweetStore()
        return _DEFAULT_STORE
