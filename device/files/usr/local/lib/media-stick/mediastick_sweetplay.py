"""Resident SWEET.TV playback, wall-clock timeline, CDN failover, and sprite parser.

Pure Core (stdlib-only, zero xbmc imports):
  - JSONRPC.NotifyAll payload builders & validators: build_play_notify, build_ctl_notify
  - Uncached stream resolution & CDN mirror rotation: open_stream, open_vod
  - Demuxer & quality cap selection: is_finished_hls_archive, parse_hls_master,
      pick_hls_variant, resolve_hls_variant, select_demuxer
  - Timeline, rollover, overrun grace & seek state machines:
      compute_initial_seek, plan_slot_end, classify_overrun_resume, plan_seek,
      evaluate_watchdog, SeekCoalescer, wall_timeline
  - Thumbnail sprite parser & HTTPS *.sweet.tv allowlist:
      parse_thumbnails_spec, fetch_thumbnails_spec
  - Atomic active session file (/run/media-stick/sweettv-session.json):
      write_active_session, read_active_session, read_active_thumbnails, clear_active_session
"""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit

import mediastick_store as ms_store
import mediastick_sweetapi as sweetapi

try:
    import mediastick_sweetstore as _sweetstore
except ImportError:
    _sweetstore = None

SESSION_FILE = "/run/media-stick/sweettv-session.json"
NOTIFY_SENDER = "script.media-stick.home"
PLAY_MESSAGE = "sweettv.play"
CTL_MESSAGE = "sweettv.ctl"

VALID_PLAY_KINDS = ("live", "epg", "vod")
VALID_CTL_OPS = ("seek_by", "seek_wall", "from_start", "live", "prev_prog", "next_prog", "stop_preview")

MIN_TOTAL = 30
SEEK_TOLERANCE = 8
LIVE_EDGE_LAG = 15
RAW_LIVE_REWIND_THRESHOLD = 45
SLOT_END_MARGIN = 45
LIVE_HANDOFF_WINDOW = 90
OVERRUN_GRACE_SECONDS = 1200
ARCHIVE_OVERRUN_WINDOW = 1800

STALL_TIMEOUT = 8.0
FAILOVER_COOLDOWN = 6.0
HEALTHY_RESET_SECONDS = 30.0
MAX_FAILOVERS = 3
COALESCE_WINDOW = 0.6

TV_RIGHT_STEPS = (60, 180, 300)
TV_LEFT_STEPS = (-15, -60)
VOD_RIGHT_STEPS = (30,)
VOD_LEFT_STEPS = (-10,)

STREAM_TIMEOUT = 5
USER_AGENT = sweetapi.HEADERS["user-agent"]
SWEET_ORIGIN = "https://sweet.tv"
SWEET_REFERER = "https://sweet.tv/"

_ID_RE = re.compile(r"^[1-9][0-9]{0,11}$")
_SAFE_SESSION_KEYS = (
    "kind",
    "cid",
    "epg_id",
    "movie_id",
    "episode_id",
    "owner_id",
    "title",
    "channel_name",
    "slot_start",
    "slot_stop",
    "anchor_start",
    "anchor_stop",
    "start_offset",
    "from_start",
    "episode_mode",
    "auto_rollover_from",
    "thumbnails",
    "updated_at",
)


# ---- validation helpers -------------------------------------------------------


def _req_id(val, field: str) -> str:
    if isinstance(val, bool) or val is None:
        raise TypeError(f"{field} must be a positive numeric ID")
    if isinstance(val, int):
        if val <= 0 or val >= 10**12:
            raise ValueError(f"{field} out of range: {val}")
        return str(val)
    if isinstance(val, str):
        s = val.strip()
        if _ID_RE.fullmatch(s):
            return s
        raise ValueError(f"invalid {field}: {val!r}")
    raise TypeError(f"invalid type for {field}: {type(val).__name__}")


def _opt_id(val, field: str) -> str:
    if isinstance(val, bool):
        raise TypeError(f"{field} must not be bool")
    if val in (None, "", "null", 0, "0"):
        return ""
    return _req_id(val, field)


def _nonneg_int(val, field: str, default: int = 0) -> int:
    if val is None or val == "":
        return default
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise TypeError(f"{field} must be numeric")
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"{field} must be finite")
    n = int(val)
    if n < 0:
        raise ValueError(f"{field} must be >= 0")
    return n


def _signed_int(val, field: str) -> int:
    if isinstance(val, bool) or not isinstance(val, (int, float)):
        raise TypeError(f"{field} must be numeric")
    if math.isnan(val) or math.isinf(val):
        raise ValueError(f"{field} must be finite")
    return int(val)


# ---- JSONRPC.NotifyAll payload builders ---------------------------------------


def validate_play_data(data: dict) -> dict:
    """Validate and normalize a sweettv.play notification payload dict."""
    if not isinstance(data, dict):
        raise TypeError("play payload must be a dict")
    kind = data.get("kind")
    if isinstance(kind, bool) or not isinstance(kind, str) or kind not in VALID_PLAY_KINDS:
        raise ValueError(f"invalid play kind: {kind!r}")

    if kind == "live":
        cid_s = _req_id(data.get("cid"), "cid")
        epg_s = ""
        mid_s = ""
        epid_s = ""
    elif kind == "epg":
        cid_s = _req_id(data.get("cid"), "cid")
        epg_s = _req_id(data.get("epg_id"), "epg_id")
        mid_s = ""
        epid_s = ""
    else:
        cid_s = ""
        epg_s = ""
        mid_s = _req_id(data.get("movie_id"), "movie_id")
        epid_s = _opt_id(data.get("episode_id"), "episode_id")

    owner_int = _nonneg_int(data.get("owner_id", 0), "owner_id", default=0)
    offset_int = _nonneg_int(data.get("start_offset", 0), "start_offset", default=0)
    wall_int = _nonneg_int(data.get("wall_ts", 0), "wall_ts", default=0)
    title_raw = data.get("title", "")
    title_s = str(title_raw)[:200] if isinstance(title_raw, (str, int, float)) and not isinstance(title_raw, bool) else ""
    preview_flag = bool(data.get("preview", False))
    if preview_flag and kind != "live":
        raise ValueError(f"preview is only supported for live playback, got {kind!r}")

    out = {
        "kind": kind,
        "cid": cid_s,
        "epg_id": epg_s,
        "movie_id": mid_s,
        "episode_id": epid_s,
        "owner_id": owner_int,
        "start_offset": offset_int,
        "from_start": bool(data.get("from_start", False)),
        "wall_ts": wall_int,
        "title": title_s,
        "episode_mode": bool(data.get("episode_mode", False)),
        "preview": preview_flag,
    }
    if data.get("anchor_start"):
        out["anchor_start"] = _nonneg_int(data.get("anchor_start"), "anchor_start", default=0)
    if data.get("anchor_stop"):
        out["anchor_stop"] = _nonneg_int(data.get("anchor_stop"), "anchor_stop", default=0)
    if data.get("auto_rollover_from"):
        out["auto_rollover_from"] = _opt_id(data.get("auto_rollover_from"), "auto_rollover_from")
    return out


def build_play_notify(
    kind,
    cid="",
    epg_id="",
    movie_id="",
    episode_id="",
    owner_id=0,
    start_offset=0,
    from_start=False,
    wall_ts=0,
    title="",
    episode_mode=False,
    preview=False,
) -> dict:
    """Build a JSONRPC.NotifyAll request for sweettv.play."""
    payload = validate_play_data(
        {
            "kind": kind,
            "cid": cid,
            "epg_id": epg_id,
            "movie_id": movie_id,
            "episode_id": episode_id,
            "owner_id": owner_id,
            "start_offset": start_offset,
            "from_start": from_start,
            "wall_ts": wall_ts,
            "title": title,
            "episode_mode": episode_mode,
            "preview": preview,
        }
    )
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "JSONRPC.NotifyAll",
        "params": {
            "sender": NOTIFY_SENDER,
            "message": PLAY_MESSAGE,
            "data": payload,
        },
    }


def validate_ctl_data(data: dict) -> dict:
    """Validate and normalize a sweettv.ctl notification payload dict."""
    if not isinstance(data, dict):
        raise TypeError("ctl payload must be a dict")
    op = data.get("op")
    if isinstance(op, bool) or not isinstance(op, str) or op not in VALID_CTL_OPS:
        raise ValueError(f"invalid ctl op: {op!r}")
    seconds_int = _signed_int(data.get("seconds", 0), "seconds")
    wall_int = _nonneg_int(data.get("wall_ts", 0), "wall_ts", default=0)
    if op == "seek_wall" and wall_int <= 0:
        raise ValueError("seek_wall requires positive wall_ts")
    return {
        "op": op,
        "seconds": seconds_int,
        "wall_ts": wall_int,
    }


def build_ctl_notify(op, seconds=0, wall_ts=0) -> dict:
    """Build a JSONRPC.NotifyAll request for sweettv.ctl."""
    payload = validate_ctl_data({"op": op, "seconds": seconds, "wall_ts": wall_ts})
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "JSONRPC.NotifyAll",
        "params": {
            "sender": NOTIFY_SENDER,
            "message": CTL_MESSAGE,
            "data": payload,
        },
    }


# ---- HTTP transport & direct uncached stream resolution -----------------------


def _http_send(url: str, headers: dict, payload: bytes | None, timeout: float) -> tuple[int, bytes]:
    method = "GET" if payload is None else "POST"
    try:
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(2 * 1024 * 1024)
    except urllib.error.HTTPError as exc:
        return exc.code, b""
    except Exception:
        return 0, b""


def _post_uncached(
    endpoint: str,
    body: dict,
    bearer: str | None = None,
    accept_lang: str | None = None,
    send=None,
    timeout: float = STREAM_TIMEOUT,
) -> tuple[bool, dict, str]:
    transport = send or _http_send
    tok = bearer if bearer is not None else sweetapi.bearer()
    if not tok:
        return False, {}, "auth"
    lang = accept_lang or sweetapi.language()
    headers = {**sweetapi.HEADERS, "accept-language": lang, "authorization": tok}
    raw_body = json.dumps(body).encode("utf-8")
    url = sweetapi.API + endpoint
    status, raw = transport(url, headers, raw_body, timeout)
    if status == 401 and bearer is None:
        fresh = sweetapi.bearer()
        if fresh and fresh != tok:
            headers = {**headers, "authorization": fresh}
            status, raw = transport(url, headers, raw_body, timeout)
    if status == 0:
        return False, {}, "network"
    if status in (401, 403):
        return False, {}, "auth"
    if status != 200:
        return False, {}, "service"
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False, {}, "format"
    if not isinstance(doc, dict):
        return False, {}, "format"
    if doc.get("code") == 13:
        return False, doc, "unavailable"
    for field in ("result", "status"):
        val = doc.get(field)
        if isinstance(val, str) and val not in ("OK", ""):
            return False, doc, "service"
    return True, doc, ""


def _extract_stream_candidates(doc: dict) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []
    seen: set[str] = set()

    raw_entries = []
    if isinstance(doc.get("http_stream"), dict):
        raw_entries.append(doc["http_stream"])
    for list_key in ("mirrors", "http_streams", "streams"):
        items = doc.get(list_key)
        if isinstance(items, list):
            raw_entries.extend(items)

    for entry in raw_entries:
        host = ""
        full_url = ""
        if isinstance(entry, dict):
            host_obj = entry.get("host")
            if isinstance(host_obj, dict):
                host = str(host_obj.get("address") or "").strip()
            elif isinstance(host_obj, str):
                host = host_obj.strip()
            u = str(entry.get("url") or "").strip()
            if u.startswith(("http://", "https://")):
                full_url = "https://" + u[7:] if u.startswith("http://") else u
                host = (urlsplit(full_url).hostname or host).strip()
            elif host and u:
                path = u if u.startswith("/") else "/" + u
                full_url = f"https://{host}{path}"
        elif isinstance(entry, str) and entry.strip().startswith(("http://", "https://")):
            u = entry.strip()
            full_url = "https://" + u[7:] if u.startswith("http://") else u
            host = (urlsplit(full_url).hostname or "").strip()

        if full_url and full_url not in seen:
            seen.add(full_url)
            candidates.append((host, full_url))
    return candidates


def _pick_candidate(candidates: list[tuple[str, str]], exclude_hosts) -> tuple[str, str]:
    excluded = {str(h).strip().lower() for h in (exclude_hosts or ()) if isinstance(h, str) and h.strip()}
    for host, url in candidates:
        if host.lower() not in excluded:
            return host, url
    return candidates[0]


def _format_drm(doc: dict, stream_url: str) -> tuple[str, str | None, str]:
    scheme = str(doc.get("scheme") or "").upper()
    path_lower = stream_url.split("?", 1)[0].lower()
    protocol = "mpd" if ("DASH" in scheme or path_lower.endswith(".mpd")) else "hls"

    drm_type = str(doc.get("drm_type") or "").upper()
    lic_raw = str(doc.get("license_server") or doc.get("license_url") or "").strip()
    if drm_type == "DRM_WIDEVINE" or lic_raw:
        drm = "com.widevine.alpha"
        if lic_raw and "|" not in lic_raw:
            lic_headers = urlencode(
                {
                    "User-Agent": USER_AGENT,
                    "origin": SWEET_ORIGIN,
                    "referer": SWEET_REFERER,
                }
            )
            license_url = f"{lic_raw}|{lic_headers}|R{{SSM}}|"
        else:
            license_url = lic_raw
    else:
        drm = None
        license_url = ""
    return protocol, drm, license_url


def open_stream(
    cid,
    epg_id=None,
    bearer: str | None = None,
    accept_lang: str | None = None,
    exclude_hosts=(),
    send=None,
    timeout: float = STREAM_TIMEOUT,
) -> dict:
    """Resolve live or DVR stream via TvService/OpenStream.json (strictly uncached)."""
    try:
        cid_s = _req_id(cid, "cid")
        epg_s = _opt_id(epg_id, "epg_id")
    except (TypeError, ValueError):
        return {"ok": False, "error": "format"}

    body: dict = {
        "without_auth": True,
        "channel_id": int(cid_s),
        "multistream": True,
    }
    if epg_s:
        body["epg_id"] = int(epg_s)

    ok, doc, err = _post_uncached(
        "TvService/OpenStream.json",
        body,
        bearer=bearer,
        accept_lang=accept_lang,
        send=send,
        timeout=timeout,
    )
    if not ok:
        return {"ok": False, "error": err or "service"}

    candidates = _extract_stream_candidates(doc)
    if not candidates:
        return {"ok": False, "error": "service"}

    host, stream_url = _pick_candidate(candidates, exclude_hosts)
    protocol, drm, license_url = _format_drm(doc, stream_url)
    thumbs_url = str(doc.get("thumbnails_playlist_url") or "").strip()
    return {
        "ok": True,
        "stream_url": stream_url,
        "url": stream_url,
        "host": host,
        "protocol": protocol,
        "drm": drm,
        "license_url": license_url,
        "thumbnails_playlist_url": thumbs_url,
    }


def open_vod(
    movie_id,
    episode_id=None,
    owner_id=0,
    quality: str = "1080p",
    bearer: str | None = None,
    accept_lang: str | None = None,
    exclude_hosts=(),
    send=None,
    timeout: float = STREAM_TIMEOUT,
) -> dict:
    """Resolve VOD stream via MovieService/GetLink.json (strictly uncached)."""
    try:
        mid_s = _req_id(movie_id, "movie_id")
        epid_s = _opt_id(episode_id, "episode_id")
        oid = _nonneg_int(owner_id, "owner_id", default=0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "format"}

    title = ""
    duration = 0
    if not oid and _sweetstore is not None:
        try:
            cached = _sweetstore.default_store().get_title_detail(f"vod:{mid_s}")
            if isinstance(cached, dict):
                title = str(cached.get("title") or "")
                duration = int(cached.get("duration") or 0)
                oid = int(cached.get("owner_id") or 0)
        except Exception:
            pass

    if not oid:
        ok_info, info_doc, _ = _post_uncached(
            sweetapi.MOVIE_INFO,
            {"movies": [int(mid_s)], "need_extended_info": True},
            bearer=bearer,
            accept_lang=accept_lang,
            send=send,
            timeout=timeout,
        )
        if ok_info:
            movies = info_doc.get("movies") or ()
            movie = movies[0] if isinstance(movies, list) and movies and isinstance(movies[0], dict) else None
            if movie:
                title = str(movie.get("title") or "")[:200]
                duration = int(movie.get("duration") or 0) if isinstance(movie.get("duration"), int) else 0
                oid = sweetapi.owner_of(movie)

    body: dict = {
        "movie_id": int(mid_s),
        "owner_id": int(oid),
        "video_quality_id": sweetapi.quality_id(quality),
        "audio_track": -1,
        "preferred_link_type": 0,
        "subtitle": "all",
    }
    if epid_s:
        body["episode_id"] = int(epid_s)

    ok, doc, err = _post_uncached(
        sweetapi.MOVIE_LINK,
        body,
        bearer=bearer,
        accept_lang=accept_lang,
        send=send,
        timeout=timeout,
    )
    if not ok:
        return {"ok": False, "error": err or "service"}

    candidates = _extract_stream_candidates(doc)
    if not candidates:
        return {"ok": False, "error": "service"}

    host, stream_url = _pick_candidate(candidates, exclude_hosts)
    protocol, drm, license_url = _format_drm(doc, stream_url)
    thumbs_url = str(doc.get("thumbnails_playlist_url") or "").strip()
    return {
        "ok": True,
        "stream_url": stream_url,
        "url": stream_url,
        "host": host,
        "protocol": protocol,
        "drm": drm,
        "license_url": license_url,
        "thumbnails_playlist_url": thumbs_url,
        "title": title,
        "duration": duration,
    }


_HLS_ATTR_RE = re.compile(r'([A-Z0-9-]+)=("[^"]*"|[^,]*)')
_QUALITY_HEIGHT_CAPS = {"720p": 720, "1080p": 1080, "unlimited": None}


def is_finished_hls_archive(
    stream_info: dict,
    kind: str = "epg",
    slot_stop: int = 0,
    now: int = 0,
) -> bool:
    """Return True when stream_info is a finished non-DRM HLS DVR archive."""
    if not isinstance(stream_info, dict):
        return False
    protocol = str(stream_info.get("protocol") or "hls").lower()
    drm = stream_info.get("drm")
    stop_i = int(slot_stop or 0)
    now_i = int(now or 0)
    return bool(
        kind == "epg"
        and not drm
        and protocol == "hls"
        and stop_i > 0
        and stop_i <= now_i
    )


def _valid_http_url(url: str) -> str:
    if not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw or any(ord(ch) <= 0x20 for ch in raw):
        return ""
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        return ""
    try:
        _ = parts.port
    except ValueError:
        return ""
    return raw


def _parse_hls_attrs(attr_text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, val in _HLS_ATTR_RE.findall(attr_text):
        cleaned = val[1:-1] if len(val) >= 2 and val.startswith('"') and val.endswith('"') else val
        out[key.upper()] = cleaned
    return out


def _parse_hls_int(val: str | None) -> int:
    if not val:
        return 0
    s = val.strip()
    return int(s) if s.isdigit() else 0


def _parse_hls_resolution(val: str) -> tuple[int, int]:
    if not val or "x" not in val.lower():
        return 0, 0
    w_s, _, h_s = val.lower().partition("x")
    w = _parse_hls_int(w_s)
    h = _parse_hls_int(h_s)
    return (w, h) if w > 0 and h > 0 else (0, 0)


def parse_hls_master(manifest_text: str | bytes, base_url: str) -> dict:
    """Parse an HLS master playlist into variant metadata and external-audio status."""
    empty = {"is_master": False, "variants": [], "has_external_audio": False, "external_audio_groups": []}
    if isinstance(manifest_text, (bytes, bytearray)):
        text = bytes(manifest_text).decode("utf-8", errors="replace")
    elif isinstance(manifest_text, str):
        text = manifest_text
    else:
        return empty

    lines = [ln.strip() for ln in text.lstrip("\ufeff").splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("#EXTM3U"):
        return empty

    saw_stream_inf = False
    has_external_audio = False
    external_audio_groups: set[str] = set()
    variants: list[dict] = []
    pending_inf: dict[str, str] | None = None

    for ln in lines[1:]:
        if ln.startswith("#EXT-X-MEDIA:"):
            attrs = _parse_hls_attrs(ln[len("#EXT-X-MEDIA:"):])
            if attrs.get("TYPE", "").upper() == "AUDIO" and attrs.get("URI", "").strip():
                has_external_audio = True
                grp = attrs.get("GROUP-ID", "").strip()
                if grp:
                    external_audio_groups.add(grp)
            continue
        if ln.startswith("#EXT-X-STREAM-INF:"):
            saw_stream_inf = True
            pending_inf = _parse_hls_attrs(ln[len("#EXT-X-STREAM-INF:"):])
            continue
        if ln.startswith("#"):
            continue
        if pending_inf is not None:
            attrs = pending_inf
            pending_inf = None
            if any(ord(ch) <= 0x20 for ch in ln):
                continue
            resolved = _valid_http_url(urljoin(base_url, ln))
            if not resolved:
                continue
            bw = _parse_hls_int(attrs.get("BANDWIDTH"))
            avg_bw = _parse_hls_int(attrs.get("AVERAGE-BANDWIDTH"))
            w, h = _parse_hls_resolution(attrs.get("RESOLUTION", ""))
            variants.append(
                {
                    "url": resolved,
                    "bandwidth": bw or avg_bw,
                    "average_bandwidth": avg_bw,
                    "width": w,
                    "height": h,
                    "audio": attrs.get("AUDIO", "").strip(),
                    "codecs": attrs.get("CODECS", "").strip(),
                }
            )

    return {
        "is_master": saw_stream_inf,
        "variants": variants,
        "has_external_audio": has_external_audio,
        "external_audio_groups": sorted(external_audio_groups),
    }


def pick_hls_variant(parsed: dict, quality: str = "1080p") -> str:
    """Pick a single variant URL matching quality cap, or '' to fall back to master."""
    if not isinstance(parsed, dict) or not parsed.get("is_master"):
        return ""
    if parsed.get("has_external_audio"):
        return ""
    variants = [v for v in (parsed.get("variants") or ()) if isinstance(v, dict) and v.get("url")]
    if not variants:
        return ""

    q_norm = str(quality or "1080p").strip().lower()
    cap = _QUALITY_HEIGHT_CAPS.get(q_norm, 1080)
    with_height = [v for v in variants if int(v.get("height") or 0) > 0]

    if not with_height:
        chosen = max(variants, key=lambda v: int(v.get("bandwidth") or 0))
    elif cap is not None:
        within_cap = [v for v in with_height if int(v.get("height") or 0) <= cap]
        if within_cap:
            chosen = max(within_cap, key=lambda v: (int(v.get("height") or 0), int(v.get("bandwidth") or 0)))
        else:
            chosen = min(with_height, key=lambda v: (int(v.get("height") or 0), int(v.get("bandwidth") or 0)))
    else:
        chosen = max(with_height, key=lambda v: (int(v.get("height") or 0), int(v.get("bandwidth") or 0)))

    ext_groups = set(parsed.get("external_audio_groups") or ())
    if chosen.get("audio") and chosen["audio"] in ext_groups:
        return ""
    return str(chosen.get("url") or "")


def resolve_hls_variant(
    master_url: str,
    quality: str = "1080p",
    send=None,
    timeout: float = STREAM_TIMEOUT,
) -> str:
    """Fetch HLS master manifest and return a matching variant URL, or base_url on fallback."""
    base_url = str(master_url or "").split("|", 1)[0].strip()
    if not _valid_http_url(base_url):
        return base_url

    transport = send or _http_send
    headers = {
        "User-Agent": USER_AGENT,
        "Origin": SWEET_ORIGIN,
        "Referer": SWEET_REFERER,
    }
    try:
        status, raw = transport(base_url, headers, None, timeout)
    except Exception:
        return base_url
    if status != 200 or not raw:
        return base_url

    try:
        parsed = parse_hls_master(raw, base_url)
        chosen = pick_hls_variant(parsed, quality=quality)
    except Exception:
        return base_url
    return chosen or base_url


def select_demuxer(
    stream_info: dict,
    kind: str = "epg",
    slot_stop: int = 0,
    now: int = 0,
    quality: str = "1080p",
) -> dict:
    """Select native ffmpeg for finished non-DRM HLS archives; inputstream.adaptive otherwise."""
    stream_url = str(stream_info.get("stream_url") or stream_info.get("url") or "")
    protocol = str(stream_info.get("protocol") or "hls").lower()
    drm = stream_info.get("drm")
    license_url = str(stream_info.get("license_url") or "")

    if is_finished_hls_archive(stream_info, kind=kind, slot_stop=slot_stop, now=now):
        if "|" in stream_url:
            play_url = stream_url
        else:
            hdrs = urlencode({"User-Agent": USER_AGENT, "Referer": SWEET_REFERER})
            play_url = f"{stream_url}|{hdrs}"
        return {
            "demuxer": "ffmpeg",
            "play_url": play_url,
            "properties": {},
        }

    props: dict[str, str] = {
        "inputstream": "inputstream.adaptive",
        "inputstream.adaptive.manifest_type": "mpd" if protocol == "mpd" else "hls",
        "inputstream.adaptive.stream_headers": urlencode(
            {
                "User-Agent": USER_AGENT,
                "Origin": SWEET_ORIGIN,
                "Referer": SWEET_REFERER,
            }
        ),
    }
    if drm:
        props["inputstream.adaptive.license_type"] = str(drm)
        if license_url:
            props["inputstream.adaptive.license_key"] = license_url
    if isinstance(quality, str) and quality in ("720p", "1080p"):
        props["inputstream.adaptive.chooser_resolution_max"] = quality
        props["inputstream.adaptive.chooser_resolution_secure_max"] = quality
        props["inputstream.adaptive.max_resolution"] = quality

    return {
        "demuxer": "inputstream.adaptive",
        "play_url": stream_url,
        "properties": props,
    }


# ---- pure timeline, rollover, overrun & seek state machines -------------------


def compute_initial_seek(offset, pos, total, from_start: bool = False) -> tuple[str, int]:
    """Guarantee 0:00 DVR start (from_start=True) or explicit start_offset once duration is known."""
    off = int(offset) if isinstance(offset, (int, float)) and not isinstance(offset, bool) and offset > 0 else 0
    if off <= 0 and not from_start:
        return ("done", 0)
    total_f = float(total) if isinstance(total, (int, float)) and not isinstance(total, bool) else 0.0
    pos_f = float(pos) if isinstance(pos, (int, float)) and not isinstance(pos, bool) else 0.0
    if total_f < MIN_TOTAL:
        return ("wait", 0)
    target = 0 if off <= 0 else int(max(0, min(off, total_f - 5)))
    if abs(pos_f - target) <= SEEK_TOLERANCE:
        return ("done", 0)
    return ("seek", target)


def _resolve_store(store=None):
    if store is not None:
        return store
    return _sweetstore.default_store() if _sweetstore is not None else None


def plan_slot_end(session: dict, pos: float, now: int, store=None) -> dict | None:
    """Plan continuous TV rollover at genuine slot end (suppressed when episode_mode=True)."""
    if not isinstance(session, dict) or session.get("kind") != "epg":
        return None
    if session.get("episode_mode"):
        return None

    slot_start = int(session.get("slot_start") or 0)
    slot_stop = int(session.get("slot_stop") or 0)
    expected_duration = max(0, slot_stop - slot_start)
    if expected_duration > 0 and float(pos) < expected_duration - SLOT_END_MARGIN:
        return None

    now_i = int(now)
    cid = str(session.get("cid") or "")
    epg_id = str(session.get("epg_id") or "")
    if not cid or not epg_id:
        return None

    anchor_start = int(session.get("anchor_start") or slot_start)
    anchor_stop = int(session.get("anchor_stop") or slot_stop)
    st = _resolve_store(store)
    if st is not None:
        try:
            _prev_p, next_p = st.adjacent_programmes(cid, epg_id)
        except Exception:
            next_p = None
        if isinstance(next_p, dict):
            n_epg = str(next_p.get("epg") or "")
            n_start = int(next_p.get("start") or next_p.get("time_start") or 0)
            n_stop = int(next_p.get("stop") or next_p.get("time_stop") or 0)
            fresh = st.recall_programme(n_epg, cid=cid, now=now_i) if n_epg else None
            can_arch = bool((fresh or next_p).get("can_archive"))
            if n_epg and n_start <= now_i and can_arch:
                return {
                    "kind": "epg",
                    "cid": cid,
                    "epg_id": n_epg,
                    "title": str((fresh or next_p).get("title") or ""),
                    "slot_start": n_start,
                    "slot_stop": n_stop,
                    "anchor_start": anchor_start,
                    "anchor_stop": anchor_stop,
                    "start_offset": 0,
                    "from_start": True,
                    "episode_mode": False,
                    "auto_rollover_from": epg_id,
                }

    if slot_stop > 0 and abs(now_i - slot_stop) <= LIVE_HANDOFF_WINDOW:
        return {
            "kind": "live",
            "cid": cid,
            "epg_id": "",
            "title": str(session.get("channel_name") or session.get("title") or ""),
            "anchor_start": anchor_start,
            "anchor_stop": anchor_stop,
            "start_offset": 0,
            "from_start": False,
            "episode_mode": False,
            "auto_rollover_from": epg_id,
        }
    return None


def classify_overrun_resume(session: dict, pos: float, total: float) -> dict:
    """Enforce the 20-minute (1200s) overrun grace rule for auto-rolled-over slots."""
    prev_epg = str((session or {}).get("auto_rollover_from") or "").strip()
    pos_s = max(0, int(pos)) if isinstance(pos, (int, float)) and not isinstance(pos, bool) else 0
    if prev_epg:
        return {
            "mark_prev_done": True,
            "prev_epg_id": prev_epg,
            "record_current": pos_s >= OVERRUN_GRACE_SECONDS,
        }
    kind = (session or {}).get("kind")
    return {
        "mark_prev_done": False,
        "prev_epg_id": "",
        "record_current": kind in ("epg", "vod"),
    }


def plan_seek(
    session: dict,
    op: str,
    seconds: int = 0,
    wall_ts: int = 0,
    pos: float = 0.0,
    total: float = 0.0,
    now: int = 0,
    store=None,
) -> dict:
    """Plan an in-stream seek or seamless cross-slot / live-to-DVR reopen."""
    if not isinstance(session, dict):
        return {"action": "noop"}
    kind = session.get("kind")
    cid = str(session.get("cid") or "")
    epg_id = str(session.get("epg_id") or "")
    slot_start = int(session.get("slot_start") or 0)
    slot_stop = int(session.get("slot_stop") or 0)
    anchor_start = int(session.get("anchor_start") or slot_start)
    anchor_stop = int(session.get("anchor_stop") or slot_stop)
    episode_mode = bool(session.get("episode_mode", False))
    now_i = int(now)
    st = _resolve_store(store)

    def _programme_reopen(target_wall: int) -> dict | None:
        if st is None or not cid:
            return None
        clamped_wall = min(int(target_wall), now_i)
        prog = st.programme_at(cid, clamped_wall)
        if not isinstance(prog, dict):
            return None
        p_epg = str(prog.get("epg") or "")
        rec = st.recall_programme(p_epg, cid=cid, now=now_i) if p_epg else None
        info = rec or prog
        if not p_epg or not info.get("can_archive"):
            return None
        p_start = int(info.get("start") or info.get("time_start") or 0)
        p_stop = int(info.get("stop") or info.get("time_stop") or 0)
        off = max(0, clamped_wall - p_start)
        if p_stop > p_start:
            off = min(off, max(0, p_stop - p_start - 1))
        return {
            "action": "reopen",
            "play": {
                "kind": "epg",
                "cid": cid,
                "epg_id": p_epg,
                "title": str(info.get("title") or ""),
                "start_offset": off,
                "from_start": off == 0,
                "episode_mode": False,
                "anchor_start": anchor_start or p_start,
                "anchor_stop": anchor_stop or p_stop,
            },
        }

    if op == "live":
        if kind == "epg" and cid:
            return {
                "action": "reopen",
                "play": {
                    "kind": "live",
                    "cid": cid,
                    "title": str(session.get("channel_name") or ""),
                    "anchor_start": anchor_start,
                    "anchor_stop": anchor_stop,
                },
            }
        return {"action": "noop"}

    if op == "from_start":
        if kind in ("epg", "vod"):
            return {"action": "seek", "target": 0.0}
        if kind == "live" and st is not None and cid:
            prog = st.programme_at(cid, now_i)
            if isinstance(prog, dict):
                p_epg = str(prog.get("epg") or "")
                rec = st.recall_programme(p_epg, cid=cid, now=now_i) if p_epg else None
                info = rec or prog
                if p_epg and info.get("can_archive"):
                    return {
                        "action": "reopen",
                        "play": {
                            "kind": "epg",
                            "cid": cid,
                            "epg_id": p_epg,
                            "title": str(info.get("title") or ""),
                            "start_offset": 0,
                            "from_start": True,
                            "episode_mode": False,
                        },
                    }
        return {"action": "seek", "target": 0.0}

    if op in ("prev_prog", "next_prog"):
        if kind not in ("live", "epg") or st is None or not cid:
            return {"action": "noop"}
        cur_epg = epg_id
        if not cur_epg:
            cur_p = st.programme_at(cid, now_i)
            cur_epg = str((cur_p or {}).get("epg") or "")
        if not cur_epg:
            return {"action": "noop"}
        prev_p, next_p = st.adjacent_programmes(cid, cur_epg)
        chosen = prev_p if op == "prev_prog" else next_p
        if not isinstance(chosen, dict):
            return {"action": "noop"}
        c_epg = str(chosen.get("epg") or "")
        rec = st.recall_programme(c_epg, cid=cid, now=now_i) if c_epg else None
        info = rec or chosen
        c_start = int(info.get("start") or info.get("time_start") or 0)
        if c_epg and c_start <= now_i and info.get("can_archive"):
            return {
                "action": "reopen",
                "play": {
                    "kind": "epg",
                    "cid": cid,
                    "epg_id": c_epg,
                    "title": str(info.get("title") or ""),
                    "start_offset": 0,
                    "from_start": True,
                    "episode_mode": False,
                    "anchor_start": anchor_start,
                    "anchor_stop": anchor_stop,
                },
            }
        return {"action": "noop"}

    if op == "seek_wall":
        target_w = int(wall_ts)
        if kind == "epg" and slot_start > 0 and slot_stop > slot_start:
            upper_w = min(slot_stop, now_i) if slot_stop > now_i else slot_stop
            if slot_start <= target_w < upper_w:
                return {"action": "seek", "target": float(max(0, target_w - slot_start))}
            reopened = _programme_reopen(target_w)
            if reopened:
                return reopened
            clamped = max(0, min(target_w - slot_start, upper_w - slot_start - 1))
            return {"action": "seek", "target": float(clamped)}
        if kind == "live":
            if now_i - target_w <= RAW_LIVE_REWIND_THRESHOLD and total > 0:
                return {"action": "seek", "target": float(max(0.0, total - max(0, now_i - target_w)))}
            reopened = _programme_reopen(target_w)
            return reopened or {"action": "noop"}
        return {"action": "noop"}

    if op == "seek_by":
        delta = int(seconds)
        if kind == "vod":
            hi = max(0.0, float(total) - 1.0) if total > 0 else max(0.0, float(pos) + delta)
            return {"action": "seek", "target": max(0.0, min(float(pos) + delta, hi))}

        if kind == "live":
            if delta >= -RAW_LIVE_REWIND_THRESHOLD:
                hi = float(total) if total > 0 else max(0.0, float(pos) + delta)
                return {"action": "seek", "target": max(0.0, min(float(pos) + delta, hi))}
            reopened = _programme_reopen(now_i + delta)
            if reopened:
                return reopened
            return {"action": "seek", "target": 0.0}

        if kind == "epg":
            raw_target = float(pos) + delta
            if raw_target < 0 and not episode_mode and slot_start > 0:
                reopened = _programme_reopen(slot_start + int(raw_target))
                if reopened and reopened["play"]["epg_id"] != epg_id:
                    return reopened
                return {"action": "seek", "target": 0.0}

            in_progress = bool(slot_start and slot_stop and slot_start <= now_i < slot_stop)
            if in_progress:
                # Stay inside growing DVR stream at live edge (zero forward_handoff reopen!)
                live_edge = max(0.0, float(now_i - slot_start))
                cap = max(live_edge, float(total)) if total > 0 else live_edge
                return {"action": "seek", "target": max(0.0, min(raw_target, cap))}

            expected_dur = float(slot_stop - slot_start) if slot_stop > slot_start else float(total)
            if expected_dur > 0 and raw_target >= expected_dur and not episode_mode and slot_start > 0:
                reopened = _programme_reopen(slot_start + int(raw_target))
                if reopened and reopened["play"]["epg_id"] != epg_id:
                    return reopened
            cap = max(0.0, expected_dur - 1.0) if expected_dur > 0 else max(0.0, raw_target)
            return {"action": "seek", "target": max(0.0, min(raw_target, cap))}

    return {"action": "noop"}


# ---- 8s stall & truncated-EOF watchdog ----------------------------------------


def evaluate_watchdog(
    state: dict | None,
    pos: float,
    now_mono: float,
    paused: bool = False,
    ended: bool = False,
    expected_duration: int = 0,
) -> dict:
    """Pure 8s unpaused stall & truncated-EOF failover state machine."""
    cur_pos = float(pos) if isinstance(pos, (int, float)) and not isinstance(pos, bool) else 0.0
    mono = float(now_mono)
    prev = dict(state) if isinstance(state, dict) else {}

    if "last_pos" not in prev:
        init_pos = max(0, int(cur_pos))
        next_state = {
            "last_pos": cur_pos,
            "last_advance_mono": mono,
            "healthy_since_mono": mono if not paused else None,
            "last_failover_mono": None,
            "failover_count": 0,
            "was_paused": bool(paused),
            "last_good_pos": init_pos,
        }
        if not ended:
            return {"action": "ok", "resume_pos": init_pos, "failover_count": 0, "state": next_state}
        prev = next_state

    last_pos = float(prev.get("last_pos", cur_pos))
    last_advance = float(prev.get("last_advance_mono", mono))
    healthy_since = prev.get("healthy_since_mono")
    last_failover = prev.get("last_failover_mono")
    failover_count = int(prev.get("failover_count", 0))
    was_paused = bool(prev.get("was_paused", False))
    last_good_pos = int(prev.get("last_good_pos", max(0, int(cur_pos))))

    advanced = abs(cur_pos - last_pos) >= 0.25
    if advanced:
        last_pos = cur_pos
        last_good_pos = max(0, int(cur_pos))
        last_advance = mono
        if not paused:
            if healthy_since is None:
                healthy_since = mono
            elif failover_count > 0 and round(mono - float(healthy_since), 6) >= HEALTHY_RESET_SECONDS:
                failover_count = 0

    if paused and not ended:
        next_state = {
            "last_pos": last_pos,
            "last_advance_mono": mono,
            "healthy_since_mono": None,
            "last_failover_mono": last_failover,
            "failover_count": failover_count,
            "was_paused": True,
            "last_good_pos": last_good_pos,
        }
        return {"action": "ok", "resume_pos": last_good_pos, "failover_count": failover_count, "state": next_state}

    if was_paused and not paused:
        was_paused = False
        last_advance = mono
        healthy_since = mono

    exp_dur = int(expected_duration or 0)
    truncated_eof = bool(ended and (exp_dur <= 0 or cur_pos < exp_dur - SLOT_END_MARGIN))
    stalled = bool(not ended and not paused and round(mono - last_advance, 6) >= STALL_TIMEOUT)

    if truncated_eof or stalled:
        if last_failover is not None and round(mono - float(last_failover), 6) < FAILOVER_COOLDOWN:
            next_state = {
                "last_pos": last_pos,
                "last_advance_mono": last_advance,
                "healthy_since_mono": healthy_since,
                "last_failover_mono": last_failover,
                "failover_count": failover_count,
                "was_paused": False,
                "last_good_pos": last_good_pos,
            }
            return {
                "action": "cooldown",
                "resume_pos": last_good_pos,
                "failover_count": failover_count,
                "state": next_state,
            }

        if failover_count >= MAX_FAILOVERS:
            next_state = {
                "last_pos": last_pos,
                "last_advance_mono": mono,
                "healthy_since_mono": None,
                "last_failover_mono": last_failover,
                "failover_count": failover_count,
                "was_paused": False,
                "last_good_pos": last_good_pos,
            }
            return {
                "action": "give_up",
                "resume_pos": last_good_pos,
                "failover_count": failover_count,
                "state": next_state,
            }

        failover_count += 1
        next_state = {
            "last_pos": last_pos,
            "last_advance_mono": mono,
            "healthy_since_mono": mono,
            "last_failover_mono": mono,
            "failover_count": failover_count,
            "was_paused": False,
            "last_good_pos": last_good_pos,
        }
        return {
            "action": "failover",
            "resume_pos": last_good_pos,
            "failover_count": failover_count,
            "state": next_state,
        }

    next_state = {
        "last_pos": last_pos,
        "last_advance_mono": last_advance,
        "healthy_since_mono": healthy_since,
        "last_failover_mono": last_failover,
        "failover_count": failover_count,
        "was_paused": False,
        "last_good_pos": last_good_pos,
    }
    return {"action": "ok", "resume_pos": last_good_pos, "failover_count": failover_count, "state": next_state}


# ---- 0.6s directional D-pad seek coalescer ------------------------------------


class SeekCoalescer:
    """Coalesces rapid D-pad directional steps or seek_by deltas within a 0.6s window."""

    def __init__(self, window: float = COALESCE_WINDOW):
        self.window = float(window)
        self.reset()

    def reset(self) -> None:
        self._total = 0
        self._last_dir = ""
        self._dir_count = 0
        self._last_ts: float | None = None
        self._pending = False

    def has_pending(self) -> bool:
        return self._pending

    def push(self, direction: str, now_mono: float, is_vod: bool = False) -> int:
        d = str(direction or "").strip().lower()
        if d not in ("right", "left"):
            raise ValueError(f"direction must be 'right' or 'left', got {direction!r}")
        if is_vod:
            steps = VOD_RIGHT_STEPS if d == "right" else VOD_LEFT_STEPS
        else:
            steps = TV_RIGHT_STEPS if d == "right" else TV_LEFT_STEPS

        if self._last_dir == d:
            idx = self._dir_count
            self._dir_count += 1
        else:
            idx = 0
            self._last_dir = d
            self._dir_count = 1

        step = steps[min(idx, len(steps) - 1)]
        self._total += step
        self._last_ts = float(now_mono)
        self._pending = True
        return self._total

    def push_seconds(self, seconds: int, now_mono: float) -> int:
        sec = _signed_int(seconds, "seconds")
        self._total += sec
        self._last_dir = ""
        self._dir_count = 0
        self._last_ts = float(now_mono)
        self._pending = True
        return self._total

    def flush(self, now_mono: float, force: bool = False) -> int | None:
        if not self._pending or self._last_ts is None:
            return None
        if not force and round(float(now_mono) - self._last_ts, 6) < self.window:
            return None
        delta = self._total
        self.reset()
        return delta


# ---- continuous wall-clock broadcast tape -------------------------------------


def _format_lag(seconds: int) -> str:
    sec = max(0, int(seconds))
    if sec >= 3600:
        hh, rem = divmod(sec, 3600)
        mm, ss = divmod(rem, 60)
        return f"{hh}:{mm:02d}:{ss:02d}"
    mm, ss = divmod(sec, 60)
    return f"{mm:02d}:{ss:02d}"


def wall_timeline(session: dict, pos: float, now: int) -> dict:
    """Compute continuous monotonic wall-clock broadcast timeline for TV/DVR OSD."""
    kind = (session or {}).get("kind")
    if kind not in ("live", "epg"):
        return {
            "timeline_mode": "file",
            "wall_ts": 0,
            "window_start": 0,
            "window_end": 0,
            "progress_pct": 0,
            "at_live_edge": False,
            "lag_seconds": 0,
            "slot_ticks": [],
            "time_label": "",
            "sublabel": "",
        }

    now_i = int(now)
    pos_s = max(0, int(pos)) if isinstance(pos, (int, float)) and not isinstance(pos, bool) else 0
    slot_start = int(session.get("slot_start") or 0)
    slot_stop = int(session.get("slot_stop") or 0)
    anchor_start = int(session.get("anchor_start") or slot_start or now_i)
    anchor_stop = int(session.get("anchor_stop") or slot_stop or now_i)

    wall_ts = now_i if kind == "live" else ((slot_start + pos_s) if slot_start > 0 else now_i)
    lt = time.localtime(wall_ts)
    hhmm = f"{lt.tm_hour:02d}:{lt.tm_min:02d}"

    is_past_day_archive = bool(
        kind == "epg"
        and slot_stop > 0
        and slot_stop <= now_i
        and time.localtime(anchor_start)[:3] < time.localtime(now_i)[:3]
    )

    if is_past_day_archive:
        window_start = anchor_start
        window_end = anchor_stop + ARCHIVE_OVERRUN_WINDOW
        slot_ticks = [anchor_stop] if anchor_stop > anchor_start else []
        at_live_edge = False
        lag_seconds = max(0, now_i - wall_ts)
        time_label = f"{hhmm} · в записи"
    else:
        window_start = anchor_start
        window_end = max(anchor_start + 1, now_i)
        slot_ticks = [anchor_stop] if anchor_start < anchor_stop < window_end else []
        lag_seconds = 0 if kind == "live" else max(0, now_i - wall_ts)
        at_live_edge = kind == "live" or lag_seconds <= LIVE_EDGE_LAG
        if at_live_edge:
            time_label = f"{hhmm} · В эфире"
        else:
            time_label = f"{hhmm} · \u2212{_format_lag(lag_seconds)} от эфира"

    span = max(1, window_end - window_start)
    pct = int(max(0, min(100, ((wall_ts - window_start) * 100) // span)))
    if kind == "live":
        pct = 100

    sublabel = str(session.get("channel_name") or "")
    return {
        "timeline_mode": "wall",
        "wall_ts": wall_ts,
        "window_start": window_start,
        "window_end": window_end,
        "progress_pct": pct,
        "at_live_edge": at_live_edge,
        "lag_seconds": lag_seconds,
        "slot_ticks": slot_ticks,
        "time_label": time_label,
        "sublabel": sublabel,
    }


# ---- server-side thumbnail sprite parser & atomic session file ----------------


def _normalize_sweettv_https(url, base_url: str = "") -> str:
    if not isinstance(url, str):
        return ""
    raw = url.strip()
    if not raw or any(ord(ch) <= 0x20 for ch in raw):
        return ""

    if "://" not in raw and not raw.startswith("//") and ":" not in raw.split("/", 1)[0]:
        if not base_url:
            return ""
        safe_base = _normalize_sweettv_https(base_url)
        if not safe_base:
            return ""
        raw = urljoin(safe_base, raw)
    elif raw.startswith("//"):
        raw = "https:" + raw

    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        return ""
    if parts.username or parts.password:
        return ""
    host = (parts.hostname or "").lower().rstrip(".")
    if not host or not (host == "sweet.tv" or host.endswith(".sweet.tv")):
        return ""
    try:
        port = parts.port
    except ValueError:
        return ""
    netloc = f"{host}:{port}" if port and port not in (80, 443) else host
    path = parts.path or "/"
    return urlunsplit(("https", netloc, path, parts.query, ""))


def _positive_int(val) -> int:
    if isinstance(val, bool) or not isinstance(val, int) or val <= 0:
        return 0
    return val


def parse_thumbnails_spec(raw, base_url: str = "") -> dict | None:
    """Parse SWEET.TV thumbnail sprite JSON / M3U8 descriptor, allowing only https://*.sweet.tv."""
    doc = None
    if isinstance(raw, dict):
        doc = raw
    elif isinstance(raw, (bytes, bytearray)):
        try:
            doc = json.loads(bytes(raw).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            return None
    elif isinstance(raw, str):
        try:
            doc = json.loads(raw)
        except ValueError:
            return None
    if not isinstance(doc, dict):
        return None

    rows = _positive_int(doc.get("rows"))
    columns = _positive_int(doc.get("columns"))
    interval = _positive_int(doc.get("interval"))
    if not (rows and columns and interval):
        return None

    sheets: list[str] = []
    if isinstance(doc.get("sheets"), list):
        for item in doc["sheets"]:
            candidate = item.get("image_url") or item.get("url") if isinstance(item, dict) else item
            safe = _normalize_sweettv_https(candidate, base_url=base_url)
            if safe:
                sheets.append(safe)
    elif isinstance(doc.get("playlist"), str):
        for line in doc["playlist"].splitlines():
            ln = line.strip()
            if not ln or ln.startswith("#"):
                continue
            safe = _normalize_sweettv_https(ln, base_url=base_url)
            if safe:
                sheets.append(safe)
    elif isinstance(doc.get("image_url"), str):
        safe = _normalize_sweettv_https(doc["image_url"], base_url=base_url)
        if safe:
            sheets.append(safe)

    if not sheets:
        return None
    return {
        "rows": rows,
        "columns": columns,
        "interval": interval,
        "sheets": sheets,
    }


def fetch_thumbnails_spec(playlist_url: str, send=None, timeout: float = STREAM_TIMEOUT) -> dict | None:
    """Fetch and validate a SWEET.TV thumbnails_playlist_url descriptor."""
    safe_url = _normalize_sweettv_https(playlist_url)
    if not safe_url:
        return None
    transport = send or _http_send
    headers = {"User-Agent": USER_AGENT, "Origin": SWEET_ORIGIN, "Referer": SWEET_REFERER}
    status, raw = transport(safe_url, headers, None, timeout)
    if status != 200 or not raw:
        return None
    spec = parse_thumbnails_spec(raw, base_url=safe_url)
    if spec is not None:
        return spec

    try:
        doc = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if isinstance(doc, dict) and isinstance(doc.get("playlist_url"), str):
        sub_url = _normalize_sweettv_https(doc["playlist_url"], base_url=safe_url)
        if sub_url:
            st2, raw2 = transport(sub_url, headers, None, timeout)
            if st2 == 200 and raw2:
                return parse_thumbnails_spec(
                    {
                        "rows": doc.get("rows"),
                        "columns": doc.get("columns"),
                        "interval": doc.get("interval"),
                        "playlist": raw2.decode("utf-8", errors="replace"),
                    },
                    base_url=sub_url,
                )
    return None


def write_active_session(session: dict, path: str | None = None) -> bool:
    """Atomically write sanitized active session metadata to /run/media-stick/sweettv-session.json."""
    if not isinstance(session, dict):
        return False
    clean = {k: session[k] for k in _SAFE_SESSION_KEYS if k in session}
    if "updated_at" not in clean:
        clean["updated_at"] = int(time.time())
    if ms_store.contains_secret(clean):
        return False

    target = path or SESSION_FILE
    folder = os.path.dirname(os.path.abspath(target))
    tmp = None
    try:
        os.makedirs(folder, mode=0o755, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(clean, f, ensure_ascii=False, separators=(",", ":"))
        os.chmod(tmp, 0o644)
        os.replace(tmp, target)
        return True
    except OSError:
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def read_active_session(path: str | None = None) -> dict | None:
    """Read active session dict from /run/media-stick/sweettv-session.json, or None."""
    target = path or SESSION_FILE
    try:
        with open(target, encoding="utf-8") as f:
            doc = json.load(f)
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def read_active_thumbnails(path: str | None = None) -> dict | None:
    """Return normalized thumbnails sprite spec for the active session, or None."""
    sess = read_active_session(path)
    if not isinstance(sess, dict):
        return None
    thumbs = sess.get("thumbnails")
    return thumbs if isinstance(thumbs, dict) else None


def clear_active_session(path: str | None = None) -> None:
    """Remove /run/media-stick/sweettv-session.json if present."""
    target = path or SESSION_FILE
    try:
        os.unlink(target)
    except OSError:
        pass
