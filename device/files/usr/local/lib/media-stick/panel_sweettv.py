"""The phone API of SWEET.TV: what the page asks of the stick beyond the play and ctl routes of panel_watch.

Routes /api/sweettv/..., answered as (body, status) like those of panel_watch; the format is the README section
"SWEET.TV API". The pure functions (what a playing item means, what a play request becomes) take the channel list as
a dict, so the tests need no files and no Kodi. Which programme to play and from where is decided by
mediastick_sweetlive, the same function that the seek of the TV remote goes through.
"""
import os
import time
from urllib.parse import parse_qs

import panel_watch as pw

try:
    import mediastick_sweetsections as sections
except ImportError:
    sections = None

try:
    import mediastick_resume as mr
except ImportError:
    mr = None

try:
    import mediastick_sweetlive as ml
except ImportError:   # a device without the library: the routes refuse, the rest of the panel works
    ml = None

PREFIX = "/api/sweettv/"
SEEK_BACK_MAX = 86400
LIST_KEEP = ("id", "name", "catchup", "catchup_duration", "available", "category", "icon_v2_url", "icon_url")
EPG_KEEP = ("id", "text", "time_start", "time_stop", "available", "tv_show_id", "season_number", "episode_number")
LOCAL_LABEL = "Remember where I stopped, on the device"
LOCAL_HINT = ("Places to continue from are taken only from what this device saved while you watched. The history of "
              "YouTube, SWEET.TV and Kodi is not used.")
_slim_cache = {"key": None, "value": None}
_index_cache = {"raw": None, "value": None}


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
    cats = [{k: c[k] for k in ("id", "caption", "name") if k in c} for c in _rows(raw.get("categories") if isinstance(raw, dict) else None)]
    return {"list": out, "categories": cats}


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


def _rows(value):
    return [row for row in value if isinstance(row, dict)] if isinstance(value, list) else []


def _channel(raw, cid):
    for c in _rows(raw.get("list") if isinstance(raw, dict) else None):
        if str(c.get("id")) == str(cid):
            return c
    return None


def _programme(channel, epg):
    for p in _rows(channel.get("epg") if channel else None):
        if str(p.get("id")) == str(epg):
            return p
    return None


def _on_now(channel, now):
    for p in _rows(channel.get("epg") if channel else None):
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


def _saved(local, cid, epg):
    """The saved entry of a programme in the stick's positions (mediastick_resume's document), or None."""
    return ((local or {}).get("items") or {}).get("sw:%s|%s" % (cid, epg))


def _entry(channel, p, now, archive=True, local=None):
    entry = {"id": str(p.get("id")), "title": str(p.get("text") or "")[:200], "start": ml._seconds(p.get("time_start")),
             "stop": ml._seconds(p.get("time_stop")), **({"archive": archive_ok(channel, p, now)} if archive else {})}
    if archive and local is not None:     # "remember where I stopped, on the device" is on
        saved = _saved(local, channel.get("id"), p.get("id"))
        entry["resume"] = saved["pos"] if saved and not saved["done"] and saved["pos"] >= mr.MIN_POS else 0
        entry["watched"] = bool(saved and saved["done"])
    return entry


def guide_view(raw, cid, now, local=None):
    """GET guide?cid=: the programmes of one channel as the channel list holds them. past: the ones that are over, the
    newest first, each with archive (can it be played from the archive); current: the one on now (archive: can it be
    played from its start); next: the ones to come, soonest first, for information (they cannot be played). With
    `local` (the stick's positions, given when the choice to remember them on the device is on) each past and current
    entry also has resume (seconds to continue from, 0: none) and watched (played to its end)."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    if not isinstance(cid, str) or not ml.url(cid):
        raise pw.Refused(_t("Wrong channel."))
    channel = _channel(raw, cid)
    if channel is None:
        raise pw.Refused(_t("This channel is not in the list."), 404)
    past, current, upcoming = [], None, []
    for p in _rows(channel.get("epg")):
        start, stop = ml._seconds(p.get("time_start")), ml._seconds(p.get("time_stop"))
        if start is None or stop is None or stop <= start or p.get("id") is None:
            continue
        if stop <= now:
            past.append(p)
        elif start <= now:
            current = current or p
        else:
            upcoming.append(p)
    past.sort(key=lambda p: -ml._seconds(p["time_start"]))
    upcoming.sort(key=lambda p: ml._seconds(p["time_start"]))
    return {"ok": True, "cid": str(cid), "name": str(channel.get("name") or "")[:120],
            "archive": bool(channel.get("catchup")) and channel.get("available") is not False,
            "archive_days": channel.get("catchup_duration") if isinstance(channel.get("catchup_duration"), int) else 0,
            "now": int(now),
            "past": [_entry(channel, p, now, local=local) for p in past],
            "current": _entry(channel, current, now, local=local) if current else None,
            "next": [_entry(channel, p, now, archive=False) for p in upcoming],
            "counts": {"past": len(past), "next": len(upcoming)}}


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
    ref = pw.sweet_ref(file) if ml else None
    if not ref or ref[1] or by >= 0:
        return None
    plan = ml.plan(raw, ref[0], min(-by, SEEK_BACK_MAX), now)
    if plan["ok"]:
        return {"switched": "archive", "url": plan["url"], "epg": plan["epg"], "offset": plan["offset"]}
    if plan["reason"] == "no_archive":
        return {"switched": "", "note": _t(ml.NO_ARCHIVE)}
    return {"switched": "", "note": ""}


def play_request(raw, body, now, local=None):
    """POST play {cid, epg?, at?}, checked: (url, epg, offset). Without epg it is the live channel. With it, the
    programme must be one of the channel, started, and in the archive; at is "start" (default), "now" (the place the
    live stream is at, for the programme on now), "resume" (the place the stick saved, `local`: its positions when the
    choice to remember them on the device is on; 0 when there is none) or seconds from the start."""
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
    elif at == "resume":
        saved = _saved(local, cid, epg)
        offset = saved["pos"] if saved and not saved["done"] else 0
    elif isinstance(at, (int, float)) and not isinstance(at, bool) and at == at:
        offset = at
    else:
        raise pw.Refused(_t("Wrong start place."))
    offset = int(max(0, min(offset, last)))
    return ml.url(cid, epg, offset), str(epg), offset


def local():
    """The stick's saved positions when "remember where I stopped, on the device" is on, else None."""
    try:
        return mr.load() if mr is not None and mr.enabled() else None
    except Exception:
        return None


def settings_view():
    """GET settings: the choice and what the page says about it. It is one choice for the whole device (YouTube and
    SWEET.TV), kept here because this is where the page asks for SWEET.TV things."""
    if mr is None:
        raise pw.Refused(_t("Remembering places is not available on this device."), 503)
    return {"ok": True, "local_resume": bool(mr.enabled()), "default": mr.DEFAULT, "saved": len(mr.load()["items"]),
            "label": _t(LOCAL_LABEL), "hint": _t(LOCAL_HINT)}


def set_settings(body):
    """POST settings {local_resume: true|false}."""
    if mr is None:
        raise pw.Refused(_t("Remembering places is not available on this device."), 503)
    value = body.get("local_resume") if isinstance(body, dict) else None
    if not isinstance(value, bool):
        raise pw.Refused(_t("Wrong value."))
    if not mr.set_enabled(value):
        raise pw.Refused(_t("The choice could not be saved."), 500)
    return settings_view()


def _index(raw):
    """The sections' index of the channel list, made again only when the list is a new one."""
    if _index_cache["raw"] is not raw or _index_cache["value"] is None:
        _index_cache.update(raw=raw, value=sections.build(raw))
    return _index_cache["value"]


def _playable(now):
    """The guide's own archive rule, for a record of the index."""
    return lambda r: archive_ok(r["channel_ref"], r["programme_ref"], now)


def _sections_ready():
    if ml is None or sections is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)


def sections_view(raw, now):
    """GET sections: how many there are in each, the genres of the channels, the names of the sections."""
    _sections_ready()
    index, ok = _index(raw), _playable(now)
    return {"ok": True, "channels": index["channels"], "shows": len(sections.shows(index, ok)),
            "films": len(sections.films(index, ok)), "genres": sections.genres(index),
            "labels": {"channels": _t("Channels"), "shows": _t("Shows and series"), "films": _t("Films")}}


def shows_view(raw, now):
    """GET shows: the shows with something to play now, by title."""
    _sections_ready()
    return {"ok": True, "items": [{"id": s["id"], "title": s["title"], "episodes": s["episodes"],
                                    "thumb": pw.image_url(s["icon"])} for s in sections.shows(_index(raw), _playable(now))]}


def show_view(raw, sid, now):
    """GET show?id=: the episodes of one show, playable now (available) or still to come."""
    _sections_ready()
    if not isinstance(sid, str) or not sections.SHOW_ID_RE.fullmatch(sid):
        raise pw.Refused(_t("Wrong show."))
    found = sections.show(_index(raw), sid, _playable(now))
    if found is None:
        raise pw.Refused(_t("This show is not in the list."), 404)
    return {"ok": True, "id": sid, "title": found["title"], "thumb": pw.image_url(found["icon"]),
            "episodes": found["episodes"]}


def films_view(raw, now):
    """GET films: the films that can be played now, by title."""
    _sections_ready()
    return {"ok": True, "items": sections.films(_index(raw), _playable(now))}


def open_url(url, rpc):
    """Player.Open of a SWEET.TV path. Where an archive is to start is written down first (mediastick_sweetlive.ask): Kodi may not
    give the add-on the query of the path, and what is written here is what the add-on reads then."""
    if ml is not None:
        ml.ask_url(url)
    pw._rpc(rpc, "Player.Open", {"item": {"file": url}})


def play(body, rpc):
    url, epg, offset = play_request(channels(), body, time.time(), local())
    open_url(url, rpc)
    return {"ok": True, "epg": epg, "offset": offset}


def golive(rpc):
    """"К эфиру": the live stream of the channel whose archived programme is playing."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    pid = pw._player_id(rpc)
    item = None
    if pid is not None:
        item = (pw._rpc(rpc, "Player.GetItem", {"playerid": pid, "properties": ["file"]}) or {}).get("item")
    ref = pw.sweet_ref((item or {}).get("file"))
    if not ref or not ref[1]:
        raise pw.Refused(_t("An archived programme is not playing."), 409)
    open_url(ml.url(ref[0]), rpc)
    return {"ok": True}


# ---- routes ----------------------------------------------------------------------------------

def get(path, rpc):
    """GET /api/sweettv/...: (body, status)."""
    route, _, query = path.partition("?")
    try:
        if route == PREFIX + "guide":
            cid = (parse_qs(query).get("cid") or [""])[0]
            return guide_view(channels(), cid, time.time(), local()), 200
        if route == PREFIX + "settings":
            return settings_view(), 200
        if route == PREFIX + "sections":
            return sections_view(channels(), time.time()), 200
        if route == PREFIX + "shows":
            return shows_view(channels(), time.time()), 200
        if route == PREFIX + "show":
            return show_view(channels(), (parse_qs(query).get("id") or [""])[0], time.time()), 200
        if route == PREFIX + "films":
            return films_view(channels(), time.time()), 200
    except pw.Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404


def post(path, body, rpc):
    """POST /api/sweettv/... (the panel has already checked X-Panel and the host): (body, status)."""
    route = path.split("?")[0]
    try:
        if route == PREFIX + "play":
            return play(body, rpc), 200
        if route == PREFIX + "golive":
            return golive(rpc), 200
        if route == PREFIX + "settings":
            return set_settings(body), 200
    except pw.Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404
