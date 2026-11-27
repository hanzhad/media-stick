"""SWEET.TV app: starting a stream via the resident SweetPlayerController and watching playback finish.

Playback is dispatched via JSONRPC.NotifyAll (`sweettv.play`) using `mediastick_sweetplay.build_play_notify`,
leaving stream opening, initial seeking, failover, and wall-clock timeline to the resident controller.
`follow` watches the player while it runs and reports the last position seen when the player stops.
"""
import json
import os
import re
import sys
from typing import NamedTuple
from urllib.parse import parse_qs, urlsplit

import xbmc

LIB_DIR = "/usr/local/lib/media-stick"
if os.path.isdir(LIB_DIR) and LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import mediastick_sweetplay as sweetplay  # noqa: E402

POLL = 5                         # s between looks at the player
START_WAIT = 120                 # s the stream gets to start before it is given up on

_PLAYVID_RE = re.compile(r"plugin://plugin\.video\.sweettv/playvid/([0-9]{1,12})\|(null|[0-9]{1,12})")
_PLAYVOD_RE = re.compile(r"plugin://plugin\.video\.sweettv/playvod/([0-9]{1,12})\|(null|[0-9]{1,12})\|([0-9]{1,12})")


class Session(NamedTuple):
    """An archived programme or VOD item being played."""
    cid: str
    epg: str
    title: str
    start: int
    stop: int
    url: str = ""
    season: int = 0
    episode: int = 0
    thumb: str = ""
    episode_mode: bool = False

    def programme(self) -> dict:
        return {"epg": self.epg, "title": self.title, "start": self.start, "stop": self.stop}


class PlayerIO:
    """The player, as `follow` sees it."""

    def __init__(self):
        self._player = xbmc.Player()

    def playing(self) -> bool:
        try:
            return bool(self._player.isPlaying())
        except Exception:
            return False

    def position(self):
        """(seconds played, seconds in all) or None when the player has nothing to say."""
        try:
            return float(self._player.getTime()), float(self._player.getTotalTime())
        except Exception:
            return None

    def seek(self, seconds):
        self._player.seekTime(float(seconds))

    def stop(self):
        self._player.stop()


def open_request(url) -> str:
    """Legacy Player.Open helper retained for compatibility."""
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "Player.Open", "params": {"item": {"file": url}}})


def parse_play_url(url: str) -> dict:
    """Parse plugin:// playvid or playvod URL into build_play_notify fields."""
    if not isinstance(url, str) or not url.strip():
        return {}
    parts = urlsplit(url.strip())
    base = f"{parts.scheme}://{parts.netloc}{parts.path}"
    qs = parse_qs(parts.query)
    try:
        start_q = max(0, int((qs.get("start") or ["0"])[0]))
    except (TypeError, ValueError):
        start_q = 0
    m = _PLAYVID_RE.fullmatch(base)
    if m:
        cid, epg = m.group(1), m.group(2)
        if epg == "null":
            return {"kind": "live", "cid": cid, "start_offset": 0}
        return {"kind": "epg", "cid": cid, "epg_id": epg, "start_offset": start_q}
    m = _PLAYVOD_RE.fullmatch(base)
    if m:
        mid, eid, oid = m.group(1), m.group(2), int(m.group(3))
        return {
            "kind": "vod",
            "movie_id": mid,
            "episode_id": "" if eid == "null" else eid,
            "owner_id": oid,
            "start_offset": start_q,
        }
    return {}


def notify_request(
    kind="",
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
    url="",
    preview=False,
) -> str:
    """Build JSON-RPC JSON string for `JSONRPC.NotifyAll` (`sweettv.play`)."""
    parsed = parse_play_url(url) if url else {}
    eff_kind = kind or parsed.get("kind") or ""
    eff_cid = cid or parsed.get("cid") or ""
    eff_epg = epg_id or parsed.get("epg_id") or ""
    eff_mid = movie_id or parsed.get("movie_id") or ""
    eff_eid = episode_id or parsed.get("episode_id") or ""
    eff_oid = owner_id if owner_id else parsed.get("owner_id", 0)
    eff_off = 0 if from_start else (start_offset if start_offset else parsed.get("start_offset", 0))
    payload = sweetplay.build_play_notify(
        kind=eff_kind,
        cid=eff_cid,
        epg_id=eff_epg,
        movie_id=eff_mid,
        episode_id=eff_eid,
        owner_id=eff_oid,
        start_offset=eff_off,
        from_start=bool(from_start),
        wall_ts=wall_ts,
        title=title,
        episode_mode=bool(episode_mode),
        preview=bool(preview),
    )
    return json.dumps(payload)


def stop_preview_request() -> str:
    """Build JSON-RPC JSON string for `JSONRPC.NotifyAll` (`sweettv.ctl` stop_preview)."""
    return json.dumps(sweetplay.build_ctl_notify("stop_preview"))


def follow(session, io, stopped, report, seek_to=0, poll=None):
    """Watch the player until it stops; seeking is owned by the resident SweetPlayerController."""
    poll = POLL if poll is None else poll
    started, waited, pos, total = False, 0, 0.0, 0.0
    while not stopped.is_set():
        if io.playing():
            started = True
            seen = io.position()
            if seen:
                pos, total = seen
        elif started:
            break
        elif waited >= START_WAIT:
            return
        waited += poll
        if stopped.wait(poll):
            break
    if started:
        report(session, pos, total)
