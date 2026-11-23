"""The phone API of SWEET.TV: what the page asks of the stick beyond the play and ctl routes of panel_watch.

Routes /api/sweettv/..., answered as (body, status) like those of panel_watch; the format is the README section
"SWEET.TV API". The pure functions (what a playing item means, what a play request becomes) take the channel list as
a dict, so the tests need no files and no Kodi. Which programme to play and from where is decided by
mediastick_sweetlive, the same function that the seek of the TV remote goes through.
"""
import os
import time

import panel_watch as pw

try:
    import mediastick_sweetlive as ml
except ImportError:   # a device without the library: the routes refuse, the rest of the panel works
    ml = None

PREFIX = "/api/sweettv/"
SEEK_BACK_MAX = 86400
LIST_KEEP = ("id", "name", "catchup", "catchup_duration", "available")
EPG_KEEP = ("id", "text", "time_start", "time_stop", "available", "tv_show_id", "season_number", "episode_number")
_slim_cache = {"key": None, "value": None}


def _t(msgid):
    """Every string the page may show goes through the dictionary (sweettv_text.TEXT); English when there is none."""
    return ml.text(msgid) if ml else msgid


def slim(raw):
    """The channel list reduced to what these routes read (the file holds pictures, links and ids for 200 channels, 5 MB,
    which is not kept in memory for a page that polls)."""
    rows = raw.get("list") if isinstance(raw, dict) else None
    out = []
    for c in rows if isinstance(rows, list) else ():
        if not isinstance(c, dict) or c.get("id") is None:
            continue
        item = {k: c[k] for k in LIST_KEEP if k in c}
        epg = c.get("epg") if isinstance(c.get("epg"), list) else []
        item["epg"] = [{k: p[k] for k in EPG_KEEP if k in p} for p in epg if isinstance(p, dict)]
        out.append(item)
    return {"list": out}


def channels():
    """The channel list of the add-on (reduced), read again only when the file changed; {} when there is none."""
    path = pw._sweet_list_path()
    try:
        key = os.stat(path).st_mtime
    except OSError:
        return {}
    if _slim_cache["key"] != key:
        raw, _ = pw._read_json(path)
        _slim_cache.update(key=key, value=slim(raw))
    return _slim_cache["value"] or {}


def _channel(raw, cid):
    for c in raw.get("list", ()) if isinstance(raw, dict) else ():
        if str(c.get("id")) == str(cid):
            return c
    return None


def _programme(channel, epg):
    for p in channel.get("epg", ()) if channel else ():
        if str(p.get("id")) == str(epg):
            return p
    return None


def _on_now(channel, now):
    for p in channel.get("epg", ()) if channel else ():
        start, stop = ml._seconds(p.get("time_start")), ml._seconds(p.get("time_stop"))
        if start is not None and stop is not None and start <= now < stop:
            return p
    return None


def archive_ok(channel, p, now):
    """Can this programme be played from the archive? The channel keeps one (catchup, for catchup_duration days), the
    programme is available, and it has started."""
    start = ml._seconds(p.get("time_start"))
    if not channel or not channel.get("catchup") or channel.get("available") is False or start is None or start > now:
        return False
    days = channel.get("catchup_duration")
    if isinstance(days, int) and not isinstance(days, bool) and days > 0 and now - start > days * 86400:
        return False
    return p.get("available") is not False


def decorate(view, raw, now):
    """The now-playing of the page (panel_watch.now_view) with what only the channel list knows: the title of the
    programme (programme), can_rewind (a live channel that has an archive: -10 works), go_live (an archived programme
    is playing: the "К эфиру" button)."""
    view = dict(view)
    cid, epg = view.get("cid"), view.get("epg")
    view.update(programme="", can_rewind=False, go_live=False)
    if not cid or ml is None:
        return view
    channel = _channel(raw, cid)
    if epg:
        p = _programme(channel, epg)
        view["programme"] = str(p.get("text") or "")[:200] if p else ""
        view["go_live"] = True
        return view
    p = _on_now(channel, now)
    view["programme"] = str(p.get("text") or "")[:200] if p else ""
    view["can_rewind"] = bool(channel) and ml.plan(raw, cid, 0, now)["ok"]
    return view


def rewind(raw, file, by, now):
    """The -10 of the phone (by < 0) on what is playing: {"switched": "archive", "url", "epg", "offset"} when the item is
    a live SWEET.TV channel with an archive (the archive of the programme on now, from now - start + by),
    {"switched": "", "note": ...} when it is live but has none, None when this is not a live SWEET.TV item (an
    ordinary seek)."""
    ref = ml.ref(file) if ml else None
    if not ref or ref[1] or by >= 0:
        return None
    plan = ml.plan(raw, ref[0], min(-by, SEEK_BACK_MAX), now)
    if plan["ok"]:
        return {"switched": "archive", "url": plan["url"], "epg": plan["epg"], "offset": plan["offset"]}
    if plan["reason"] == "no_archive":
        return {"switched": "", "note": _t(ml.NO_ARCHIVE)}
    return {"switched": "", "note": ""}


def play_request(raw, body, now):
    """POST play {cid, epg?, at?}, checked: (url, epg, offset). Without epg it is the live channel. With it, the
    programme must be one of the channel, started, and in the archive; at is "start" (default), "now" (the place the
    live stream is at, for the programme on now) or seconds from the start."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    body = body if isinstance(body, dict) else {}
    cid, epg, at = body.get("cid"), body.get("epg"), body.get("at", "start")
    if isinstance(cid, bool) or not isinstance(cid, (int, str)) or not ml.url(cid):
        raise pw.Refused(_t("Wrong channel."))
    if epg in (None, "", "null"):
        return ml.url(cid), "", 0
    if isinstance(epg, bool) or not isinstance(epg, (int, str)) or not ml.url(cid, epg):
        raise pw.Refused(_t("Wrong programme."))
    channel = _channel(raw, cid)
    p = _programme(channel, epg)
    if p is None:
        raise pw.Refused(_t("This programme is not in the channel's guide."), 404)
    if not archive_ok(channel, p, now):
        raise pw.Refused(_t("This programme is not in the archive."), 409)
    start, stop = ml._seconds(p.get("time_start")), ml._seconds(p.get("time_stop"))
    last = max(0, (stop - start if stop and stop > start else 0) - 1)
    if at == "start":
        offset = 0
    elif at == "now":
        offset = now - ml.LIVE_LAG - start
    elif isinstance(at, (int, float)) and not isinstance(at, bool) and at == at:
        offset = at
    else:
        raise pw.Refused(_t("Wrong start place."))
    offset = int(max(0, min(offset, last)))
    return ml.url(cid, epg, offset), str(epg), offset


def play(body, rpc):
    url, epg, offset = play_request(channels(), body, time.time())
    pw._rpc(rpc, "Player.Open", {"item": {"file": url}})
    return {"ok": True, "epg": epg, "offset": offset}


def golive(rpc):
    """"К эфиру": the live stream of the channel whose archived programme is playing."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    pid = pw._player_id(rpc)
    item = None
    if pid is not None:
        item = (pw._rpc(rpc, "Player.GetItem", {"playerid": pid, "properties": ["file"]}) or {}).get("item")
    ref = ml.ref((item or {}).get("file"))
    if not ref or not ref[1]:
        raise pw.Refused(_t("An archived programme is not playing."), 409)
    pw._rpc(rpc, "Player.Open", {"item": {"file": ml.url(ref[0])}})
    return {"ok": True}


# ---- routes ----------------------------------------------------------------------------------

def get(path, rpc):
    """GET /api/sweettv/...: (body, status)."""
    return {"error": "not found"}, 404


def post(path, body, rpc):
    """POST /api/sweettv/... (the panel has already checked X-Panel and the host): (body, status)."""
    route = path.split("?")[0]
    try:
        if route == PREFIX + "play":
            return play(body, rpc), 200
        if route == PREFIX + "golive":
            return golive(rpc), 200
    except pw.Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404
