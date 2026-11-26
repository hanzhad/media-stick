"""The phone API of SWEET.TV: what the page asks of the stick beyond the play and ctl routes of panel_watch.

Routes /api/sweettv/..., answered as (body, status) like those of panel_watch. The pure functions take the channel
list as a dict, so the tests need no files and no Kodi. Which programme to play and from where is decided by
mediastick_sweetlive, the same function that the seek of the TV remote goes through.
"""
import math
import os
import re
import time
from urllib.parse import parse_qs, urlsplit

import panel_watch as pw

try:
    import mediastick_resume as mr
except ImportError:
    mr = None

try:
    import mediastick_sweetlive as ml
except ImportError:   # a device without the library: the routes refuse, the rest of the panel works
    ml = None

try:
    import mediastick_sweetapi as api
except ImportError:   # likewise: search and the days of a channel refuse, the rest works
    api = None

try:
    import mediastick_sweetplay as sp
except ImportError:
    sp = None

try:
    import mediastick_sweetstore as sweetstore
except ImportError:
    sweetstore = None

try:
    import mediastick_sweetchannels as sc
except ImportError:
    sc = None

try:
    import panel_lang
except ImportError:
    panel_lang = None

PREFIX = "/api/sweettv/"
API_STATUS = {"auth": 409, "network": 502, "service": 502, "format": 502, "unknown": 404, "bad_date": 400, "too_old": 409,
              "too_far": 409}      # what a failed call of mediastick_sweetapi is answered with
SEEK_BACK_MAX = 86400
LOCAL_LABEL = "Remember where I stopped, on the device"
LOCAL_HINT = ("Places to continue from are taken only from what this device saved while you watched. The history of "
              "YouTube, SWEET.TV and Kodi is not used.")
SHOW_KEY_RE = re.compile(r"(?:vod|epg|tv|tv_s):[0-9]{1,12}")
MOVIE_ID_RE = re.compile(r"[0-9]{1,12}")
VALID_QUALITIES = ("720p", "1080p", "unlimited")
QUALITY_OPTIONS = [
    {"id": "720p", "label": "До 720p"},
    {"id": "1080p", "label": "До 1080p (Pi 3)"},
    {"id": "unlimited", "label": "Без лимита / 4K (Pi 5)"},
]
HOME_LABELS = {
    "continue": "Продолжить",
    "favourites": "Избранное",
    "shows": "Шоу",
    "series": "Сериалы",
    "films": "Фильмы",
    "channels": "ТВ-каналы",
}
def _t(msgid):
    """Every string the page may show goes through the dictionary (sweettv_text.TEXT); English when there is none."""
    return ml.text(msgid) if ml else msgid


def slim(raw):
    """The channel list reduced to what these routes read."""
    return ml.slim(raw) if ml else {"list": [], "categories": []}


def channels(now=None):
    """The channel list from SweetStore (GetChannels-compatible dict); {} when there is none."""
    if sweetstore is None:
        return {}
    try:
        return sweetstore.default_store().get_channels_payload(now=now)
    except Exception:
        return {}


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


def _next_after(channel, now):
    best, best_start = None, None
    for p in _rows(channel.get("epg") if channel else None):
        start = ml._seconds(p.get("time_start"))
        if start is not None and start > now and (best_start is None or start < best_start):
            best, best_start = p, start
    return best


def archive_ok(channel, p, now):
    """Can this programme be played from the archive?"""
    return ml.archive_ok(channel, p, now)


def _saved(local, cid, epg):
    return ((local or {}).get("items") or {}).get("sw:%s|%s" % (cid, epg))


def _saved_vod(local, movie_id, episode_id=""):
    items = (local or {}).get("items") or {}
    if episode_id:
        return items.get("sw:vod:%s|%s" % (movie_id, episode_id))
    return items.get("sw:vod:%s" % movie_id)


def _entry(channel, p, now, archive=True, local=None):
    entry = {"id": str(p.get("id")), "title": str(p.get("text") or "")[:200], "start": ml._seconds(p.get("time_start")),
             "stop": ml._seconds(p.get("time_stop")), **({"can_archive": archive_ok(channel, p, now)} if archive else {})}
    if archive and local is not None:
        saved = _saved(local, channel.get("id"), p.get("id"))
        min_pos = mr.MIN_POS if mr else 15
        entry["resume"] = saved["pos"] if saved and not saved["done"] and saved["pos"] >= min_pos else 0
        entry["watched"] = bool(saved and saved["done"])
    return entry


def guide_view(raw, cid, now, local=None):
    """GET guide?cid=: the programmes of one channel as the channel list holds them."""
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
            "can_archive": bool(channel.get("catchup")) and channel.get("available") is not False,
            "archive_days": channel.get("catchup_duration") if isinstance(channel.get("catchup_duration"), int) else 0,
            "now": int(now),
            "past": [_entry(channel, p, now, local=local) for p in past],
            "current": _entry(channel, current, now, local=local) if current else None,
            "next": [_entry(channel, p, now, archive=False) for p in upcoming],
            "counts": {"past": len(past), "next": len(upcoming)}}


def _clean_thumbs(thumbs):
    if not isinstance(thumbs, dict):
        return None
    rows, cols, interval = thumbs.get("rows"), thumbs.get("columns"), thumbs.get("interval")
    if (
        isinstance(rows, bool) or not isinstance(rows, int) or rows <= 0
        or isinstance(cols, bool) or not isinstance(cols, int) or cols <= 0
        or isinstance(interval, bool) or not isinstance(interval, int) or interval <= 0
    ):
        return None
    sheets = []
    for raw_url in thumbs.get("sheets") or ():
        safe = pw.image_url(raw_url)
        if not safe:
            continue
        host = (urlsplit(safe).hostname or "").lower()
        if host == "sweet.tv" or host.endswith(".sweet.tv"):
            sheets.append(safe)
    if not sheets:
        return None
    return {"rows": rows, "columns": cols, "interval": interval, "sheets": sheets}


def _prog_hint(p):
    if not isinstance(p, dict):
        return None
    return {
        "epg": str(p.get("epg") or p.get("id") or ""),
        "title": str(p.get("title") or p.get("text") or ""),
        "start": int(p.get("start") or p.get("time_start") or 0),
        "stop": int(p.get("stop") or p.get("time_stop") or 0),
        "can_archive": bool(p.get("can_archive")),
    }


def _adjacent_hints(cid, epg_id, now_i):
    if sweetstore is None or not cid:
        return None, None, None
    try:
        st = sweetstore.default_store()
        cur_p = st.recall_programme(epg_id, cid=cid, now=now_i) if epg_id else st.programme_at(cid, now_i)
        cur_epg = str((cur_p or {}).get("epg") or epg_id or "")
        if not cur_epg:
            return cur_p, None, None
        p_prev, p_next = st.adjacent_programmes(cid, cur_epg)
        return cur_p, _prog_hint(p_prev), _prog_hint(p_next)
    except Exception:
        return None, None, None


def decorate(view, raw, now, session=None):
    """Enrich panel_watch.now_view with active session, wall_timeline, prev/next, and sprite flags."""
    view = dict(view)
    file_str = str(view.get("file") or "")
    app_name = str(view.get("app") or "")
    cid = str(view.get("cid") or "")
    epg = str(view.get("epg") or "")
    use_session = bool(
        isinstance(session, dict)
        and session.get("kind") in ("live", "epg", "vod")
        and (app_name == "sweettv" or bool(cid) or (app_name in ("", "other") and file_str.startswith(("http://", "https://"))))
    )
    is_vod = bool((use_session and session.get("kind") == "vod") or cid.startswith("vod:") or "playvod/" in file_str)
    view.update(
        programme="", prog_start=0, prog_stop=0, in_progress=False, lag_seconds=0,
        can_rewind=False, go_live=False, is_vod=is_vod,
        timeline_mode="file", wall_ts=0, window_start=0, window_end=0,
        slot_ticks=[], time_label="", at_live_edge=False,
        prev_prog=None, next_prog=None, has_thumbs=False,
    )
    now_i = int(now)
    if use_session:
        view["app"] = "sweettv"
        view["has_thumbs"] = bool(_clean_thumbs(session.get("thumbnails")))
        if is_vod:
            view["live"] = False
            if not view.get("title") and session.get("title"):
                view["title"] = str(session["title"])[:200]
            return view
        kind = session["kind"]
        cid = str(session.get("cid") or cid)
        epg = str(session.get("epg_id") or epg)
        view["cid"] = cid
        view["epg"] = epg
        view["live"] = (kind == "live")
        if not view.get("channel") and session.get("channel_name"):
            view["channel"] = str(session["channel_name"])[:120]
        if not view.get("title") and session.get("title"):
            view["title"] = str(session["title"])[:200]
        if sp is not None:
            wt = sp.wall_timeline(session, view.get("time", 0), now_i)
            for k in ("timeline_mode", "wall_ts", "window_start", "window_end",
                      "slot_ticks", "time_label", "lag_seconds", "at_live_edge"):
                view[k] = wt[k]
        cur_p, prev_p, next_p = _adjacent_hints(cid, epg, now_i)
        slot_start = int(session.get("slot_start") or (cur_p or {}).get("start") or 0)
        slot_stop = int(session.get("slot_stop") or (cur_p or {}).get("stop") or 0)
        ch = _channel(raw, cid)
        view["programme"] = str((cur_p or {}).get("title") or session.get("title") or "")[:120]
        view["prog_start"] = slot_start
        view["prog_stop"] = slot_stop
        view["in_progress"] = bool(slot_start and slot_stop and slot_start <= now_i < slot_stop) or (kind == "live" and not slot_stop)
        view["go_live"] = (kind == "epg")
        view["can_rewind"] = bool(kind == "live" and ch and ch.get("catchup") and ch.get("available") is not False)
        view["prev_prog"] = prev_p
        view["next_prog"] = next_p
        return view

    if is_vod or not cid or ml is None:
        return view
    tl = ml.live_timeline(raw, cid, epg, view.get("time", 0), view.get("total", 0), now)
    view.update(programme=tl["programme"], prog_start=tl["start"], prog_stop=tl["stop"],
                in_progress=tl["in_progress"], lag_seconds=tl["lag_seconds"],
                can_rewind=False if epg else tl["can_rewind"], go_live=tl["go_live"])
    if sp is not None:
        synth = {"kind": "epg" if epg else "live", "cid": cid, "epg_id": epg,
                 "slot_start": tl["start"], "slot_stop": tl["stop"], "channel_name": view.get("channel") or ""}
        wt = sp.wall_timeline(synth, view.get("time", 0), now_i)
        for k in ("timeline_mode", "wall_ts", "window_start", "window_end",
                  "slot_ticks", "time_label", "lag_seconds", "at_live_edge"):
            view[k] = wt[k]
    _cur, prev_p, next_p = _adjacent_hints(cid, epg, now_i)
    view["prev_prog"] = prev_p
    view["next_prog"] = next_p
    return view


def rewind(raw, file, by, now):
    """Rewind a live SWEET.TV channel into the DVR archive."""
    ref = pw.sweet_ref(file) if ml else None
    if not ref or str(ref[0]).startswith("vod:") or ref[1] or by >= 0:
        return None
    plan = ml.plan(raw, ref[0], min(-by, SEEK_BACK_MAX), now)
    if plan["ok"]:
        return {"switched": "archive", "url": plan["url"], "epg": plan["epg"], "offset": plan["offset"]}
    if plan["reason"] == "no_archive":
        return {"switched": "", "note": _t(ml.NO_ARCHIVE)}
    return {"switched": "", "note": ""}


def _from_store(cid, epg, now):
    if sweetstore is None:
        return None
    try:
        found = sweetstore.default_store().recall_programme(epg, cid=cid, now=now)
    except Exception:
        return None
    if not found:
        return None
    return {
        "id": epg,
        "time_start": found.get("time_start") or found.get("start"),
        "time_stop": found.get("time_stop") or found.get("stop"),
        "available": found.get("available", True),
    }


def _from_api(cid, epg, now):
    found = _from_store(cid, epg, now) or (api.recall(cid, epg, now) if api else None)
    if not found:
        return None
    if "time_start" in found:
        return found
    return {"id": epg, "time_start": found["start"], "time_stop": found["stop"], "available": found["available"]}


def _clean_vod_play(body, local=None):
    movie_id = body.get("movie_id")
    episode_id = body.get("episode_id")
    owner_id = body.get("owner_id", 0)
    start = body.get("start", 0)
    if isinstance(movie_id, bool) or not isinstance(movie_id, (int, str)) or not MOVIE_ID_RE.fullmatch(str(movie_id)):
        raise pw.Refused(_t("Wrong value."))
    if episode_id not in (None, "", "null"):
        if isinstance(episode_id, bool) or not isinstance(episode_id, (int, str)) or not MOVIE_ID_RE.fullmatch(str(episode_id)):
            raise pw.Refused(_t("Wrong value."))
    if owner_id not in (None, ""):
        if isinstance(owner_id, bool) or not isinstance(owner_id, (int, str)) or not MOVIE_ID_RE.fullmatch(str(owner_id)):
            raise pw.Refused(_t("Wrong value."))
    if start == "resume" or body.get("at") == "resume":
        saved = _saved_vod(local, str(movie_id), "" if episode_id in (None, "", "null") else str(episode_id))
        offset = saved["pos"] if saved and not saved["done"] else 0
    elif isinstance(start, (int, float)) and not isinstance(start, bool) and start == start and start >= 0:
        offset = int(start)
    else:
        raise pw.Refused(_t("Wrong start place."))
    url = ml.vod_url(movie_id, episode_id, owner_id, offset)
    if not url:
        raise pw.Refused(_t("Wrong value."))
    return url, "", offset


def play_request(raw, body, now, local=None):
    """POST play {cid, epg?, at?, from_start?} or {movie_id, episode_id?, owner_id?, start?}: (url, epg, offset)."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    body = body if isinstance(body, dict) else {}
    if "movie_id" in body and "cid" not in body:
        return _clean_vod_play(body, local)
    cid, epg = body.get("cid"), body.get("epg")
    from_start = body.get("from_start") is True
    at = "start" if from_start else body.get("at", "start")
    if isinstance(cid, bool) or not isinstance(cid, (int, str)) or not ml.url(cid):
        raise pw.Refused(_t("Wrong channel."))
    channel = _channel(raw, cid)
    if epg in (None, "", "null"):
        if from_start:
            cur = _on_now(channel, now)
            if cur is None:
                raise pw.Refused(_t("This programme is not in the channel's guide."), 404)
            epg = cur.get("id")
        else:
            return ml.url(cid), "", 0
    if isinstance(epg, bool) or not isinstance(epg, (int, str)) or not ml.url(cid, epg):
        raise pw.Refused(_t("Wrong programme."))
    p = _programme(channel, epg) or _from_api(cid, epg, now)
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
    """SWEET.TV always uses the stick's local positions."""
    try:
        return mr.load() if mr is not None else None
    except Exception:
        return None


def _favs():
    try:
        return mr.load_favs() if mr is not None else {"v": 1, "items": {}}
    except Exception:
        return {"v": 1, "items": {}}


def _quality():
    try:
        return mr.read_quality() if mr is not None else "1080p"
    except Exception:
        return "1080p"


def home_view(raw, now, local_data=None, favs_data=None, quality="1080p"):
    """GET /api/sweettv/home: continue watching, local favourites, counts, labels, and quality."""
    ch_by_id = {str(c.get("id")): c for c in _rows(raw.get("list") if isinstance(raw, dict) else None) if c.get("id") is not None}
    min_pos = mr.MIN_POS if mr else 15
    cont = []
    for key, e in ((local_data or {}).get("items") or {}).items():
        if not key.startswith("sw:") or not isinstance(e, dict) or e.get("done") or e.get("pos", 0) < min_pos:
            continue
        total = e.get("total") or 0
        pct = int(round(100 * e["pos"] / total)) if total > 0 else 0
        if key.startswith("sw:vod:"):
            cont.append({
                "key": key, "kind": "vod",
                "movie_id": e.get("movie_id", ""), "episode_id": e.get("episode_id", ""),
                "title": e.get("title", ""), "thumb": e.get("thumb", ""),
                "pos": e["pos"], "total": total, "pct": min(100, max(0, pct)), "at": e.get("at", 0),
            })
        else:
            cid = str(e.get("cid", ""))
            ch = ch_by_id.get(cid) or {}
            thumb = e.get("thumb") or pw.image_url(ch.get("icon_v2_url") or ch.get("icon_url"))
            cont.append({
                "key": key, "kind": "epg",
                "cid": cid, "epg": str(e.get("epg", "")),
                "channel": str(ch.get("name") or "")[:120],
                "title": e.get("title", ""), "thumb": thumb,
                "start": e.get("start", 0), "stop": e.get("stop", 0),
                "pos": e["pos"], "total": total, "pct": min(100, max(0, pct)), "at": e.get("at", 0),
            })
    cont.sort(key=lambda x: -x.get("at", 0))
    fav_items = []
    for key, e in ((favs_data or {}).get("items") or {}).items():
        if isinstance(e, dict):
            fav_items.append({"key": key, "title": e.get("title", ""), "thumb": e.get("thumb", ""),
                              "at": e.get("at", 0), "meta": e.get("meta") or {}})
    fav_items.sort(key=lambda x: -x.get("at", 0))
    playable_channels = [c for c in ch_by_id.values() if c.get("available") is not False]
    return {
        "ok": True,
        "continue": cont,
        "favourites": fav_items,
        "counts": {"continue": len(cont), "favourites": len(fav_items), "channels": len(playable_channels)},
        "labels": dict(HOME_LABELS),
        "quality": quality,
    }


def channels_view(raw, now, favs_data=None, lang=None):
    """GET /api/sweettv/channels: all playable channels with curated 9-tab classification, current/next, favourite."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    if sweetstore is not None and isinstance(raw, dict) and raw.get("list") and "updated_at" not in raw:
        try:
            sweetstore.default_store().upsert_channels(raw, now=now)
        except Exception:
            pass
    fkeys = mr.fav_keys(favs_data) if mr else set()
    chs = [c for c in _rows(raw.get("list") if isinstance(raw, dict) else None)
           if c.get("id") is not None and c.get("available") is not False]
    categories_map = {
        str(cat.get("id")): str(cat.get("caption") or cat.get("name") or "")[:80]
        for cat in _rows(raw.get("categories") if isinstance(raw, dict) else None)
        if cat.get("id") is not None
    }
    eff_lang = lang or (panel_lang.current() if panel_lang is not None else "ru")
    if sc is not None:
        tabs, _, tabs_by_cid = sc.classify_channels(chs, categories_map, lang=eff_lang)
        default_tab = sc.DEFAULT_TAB
        cats = [{"id": k, "caption": label} for k, label in tabs]
    else:
        default_tab = "main"
        tabs_by_cid = {}
        cats = [{"id": cid_cat, "caption": label} for cid_cat, label in categories_map.items()]
    out = []
    for c in chs:
        cid = str(c["id"])
        cur_p = _on_now(c, now)
        nxt_p = _next_after(c, now)
        now_obj = None
        if cur_p:
            s, e = ml._seconds(cur_p.get("time_start")), ml._seconds(cur_p.get("time_stop"))
            pct = int(round(100 * (now - s) / (e - s))) if s is not None and e is not None and e > s else 0
            now_obj = {"id": str(cur_p.get("id") or ""), "title": str(cur_p.get("text") or "")[:200],
                       "start": s, "stop": e, "percent": max(0, min(100, pct))}
        nxt_obj = None
        if nxt_p:
            ns = ml._seconds(nxt_p.get("time_start"))
            nxt_obj = {"title": str(nxt_p.get("text") or "")[:200], "start": ns}
        out.append({
            "id": cid,
            "name": str(c.get("name") or "")[:120],
            "icon": pw.image_url(c.get("icon_v2_url") or c.get("icon_url")),
            "cats": [str(x) for x in (c.get("category") or []) if x is not None],
            "is_fast_channel": bool(c.get("is_fast_channel")),
            "can_archive": bool(c.get("catchup")) and c.get("available") is not False,
            "favourite": ("ch:" + cid) in fkeys,
            "now": now_obj,
            "next": nxt_obj,
            "tabs": tabs_by_cid.get(cid, ["all"]),
        })
    return {"ok": True, "default_tab": default_tab, "channels": out, "categories": cats}


def shows_api_view(raw, now, local_data=None, favs_data=None, quality="1080p"):
    """GET /api/sweettv/shows."""
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    res = _answered(api.shows(raw, now, quality=quality))
    fkeys = mr.fav_keys(favs_data) if mr else set()
    items = []
    for it in res.get("items") or []:
        row = dict(it)
        sid = str(row.get("id") or "")
        row["favourite"] = ("show:" + sid) in fkeys
        row.setdefault("resume", 0)
        items.append(row)
    return {"ok": True, "items": items}


def show_api_view(raw, sid, now, local_data=None, favs_data=None):
    """GET /api/sweettv/show?id=<show_key>."""
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    if not isinstance(sid, str) or not SHOW_KEY_RE.fullmatch(sid):
        raise pw.Refused(_t("Wrong show."))
    return _answered(api.show_detail(sid, raw, now, local=local_data, favs=favs_data))


def _int_param(query, name, default=0, low=0, high=100000):
    raw = (query.get(name) or [""])[0]
    if not raw:
        return default
    try:
        val = int(raw)
    except ValueError:
        return default
    return max(low, min(high, val))


def catalog_view(section, query, local_data=None, favs_data=None, quality="1080p"):
    """GET /api/sweettv/movies or /api/sweettv/series."""
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    genre_id = _int_param(query, "genre", 0, 0, 10**9)
    sort_id = _int_param(query, "sort", 1, 0, 100)
    offset = _int_param(query, "offset", 0, 0, 10**6)
    limit = _int_param(query, "limit", 30, 1, 100)
    cfg = _answered(api.configuration())
    page = _answered(api.catalog_page(section, genre_id, sort_id, offset, limit, quality=quality))
    fkeys = mr.fav_keys(favs_data) if mr else set()
    items = []
    for it in page.get("items") or []:
        row = dict(it)
        mid = str(row.get("id") or "")
        row["favourite"] = ("vod:" + mid) in fkeys
        saved = _saved_vod(local_data, mid)
        row["resume"] = saved["pos"] if saved and not saved["done"] else 0
        items.append(row)
    return {
        "ok": True,
        "items": items,
        "total": page.get("total", len(items)),
        "offset": page.get("offset", offset),
        "limit": page.get("limit", limit),
        "has_more": bool(page.get("has_more")),
        "genres": cfg.get("genres", []),
        "sort_modes": cfg.get("sort_modes", []),
    }


def vod_view(mid, local_data=None, favs_data=None):
    """GET /api/sweettv/vod?id=<movie_id>."""
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    if not isinstance(mid, str) or not MOVIE_ID_RE.fullmatch(mid) or int(mid) <= 0:
        raise pw.Refused(_t("Wrong value."))
    return _answered(api.vod_detail(mid, local=local_data, favs=favs_data))


def top_view(raw, now, quality="1080p", client=None):
    """GET /api/sweettv/top."""
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    return _answered(api.top_search(api.channel_map(raw), now, quality=quality, client=client))


def settings_view():
    """GET /api/sweettv/settings: device video quality cap and background preview."""
    if mr is None:
        raise pw.Refused(_t("Remembering places is not available on this device."), 503)
    return {
        "ok": True,
        "quality": mr.read_quality(),
        "preview_video": mr.read_preview_video(),
        "options": list(QUALITY_OPTIONS),
    }


def set_settings(body):
    """POST /api/sweettv/settings {quality?: "720p"|"1080p"|"unlimited", preview_video?: bool}."""
    if mr is None:
        raise pw.Refused(_t("Remembering places is not available on this device."), 503)
    if not isinstance(body, dict) or ("quality" not in body and "preview_video" not in body):
        raise pw.Refused(_t("Wrong value."))
    has_q = "quality" in body
    has_pv = "preview_video" in body
    if has_q:
        q = body.get("quality")
        if not isinstance(q, str) or q not in VALID_QUALITIES:
            raise pw.Refused(_t("Wrong value."))
    if has_pv:
        pv = body.get("preview_video")
        if not isinstance(pv, bool):
            raise pw.Refused(_t("Wrong value."))
    if has_q and not mr.write_quality(q):
        raise pw.Refused(_t("The choice could not be saved."), 500)
    if has_pv and not mr.write_preview_video(pv):
        raise pw.Refused(_t("The choice could not be saved."), 500)
    return settings_view()


def toggle_favourite(body):
    """POST /api/sweettv/favourite {key, title?, thumb?, banner?, wide_art?, meta?}."""
    if mr is None:
        raise pw.Refused(_t("Remembering places is not available on this device."), 503)
    if not isinstance(body, dict):
        raise pw.Refused(_t("Wrong value."))
    key = body.get("key")
    if not isinstance(key, str) or not mr.FAV_KEY_RE.fullmatch(key):
        raise pw.Refused(_t("Wrong value."))
    now_fav, saved_ok = mr.toggle_fav(
        key,
        {
            "title": body.get("title"),
            "thumb": body.get("thumb"),
            "banner": body.get("banner"),
            "wide_art": body.get("wide_art"),
            "meta": body.get("meta"),
        },
    )
    if not saved_ok:
        raise pw.Refused(_t("The choice could not be saved."), 500)
    return {"ok": True, "key": key, "favourite": now_fav}


def clean_ctl(body):
    """Validate POST /api/sweettv/ctl {op: from_start|live|prev_prog|next_prog|seek_by|seek_wall, seconds?, wall_ts?}."""
    if not isinstance(body, dict):
        raise pw.Refused(_t("Wrong value."))
    op = body.get("op")
    if op in ("from_start", "live", "prev_prog", "next_prog"):
        return {"op": op}
    if op == "seek_by":
        sec = body.get("seconds")
        if (
            isinstance(sec, bool)
            or not isinstance(sec, (int, float))
            or not math.isfinite(sec)
            or not -SEEK_BACK_MAX <= sec <= SEEK_BACK_MAX
        ):
            raise pw.Refused(_t("Wrong value."))
        return {"op": "seek_by", "seconds": int(sec)}
    if op == "seek_wall":
        wts = body.get("wall_ts")
        if (
            isinstance(wts, bool)
            or not isinstance(wts, (int, float))
            or not math.isfinite(wts)
            or wts <= 0
            or wts >= 10 ** 11
        ):
            raise pw.Refused(_t("Wrong value."))
        return {"op": "seek_wall", "wall_ts": int(wts)}
    raise pw.Refused(_t("Wrong value."))


def _send_notify(rpc, req):
    res = pw._rpc(rpc, req["method"], req["params"])
    return not (res is None or (isinstance(res, dict) and "error" in res))


def ctl(body, rpc):
    """POST /api/sweettv/ctl: unified Live/DVR/VOD controls routed via sweettv.ctl NotifyAll."""
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    c = clean_ctl(body)
    pid = pw._player_id(rpc)
    session = sp.read_active_session() if sp is not None else None
    if pid is None and session is None:
        raise pw.Refused("Сейчас ничего не играет.", 409)
    op = c["op"]
    if sp is not None:
        req = sp.build_ctl_notify(op=op, seconds=c.get("seconds", 0), wall_ts=c.get("wall_ts", 0))
        if _send_notify(rpc, req):
            return {"ok": True}
    if pid is None:
        raise pw.Refused("Сейчас ничего не играет.", 409)
    item = (pw._rpc(rpc, "Player.GetItem", {"playerid": pid, "properties": ["file"]}) or {}).get("item")
    props = pw._rpc(rpc, "Player.GetProperties", {"playerid": pid, "properties": ["time", "totaltime"]}) or {}
    file = (item or {}).get("file") if isinstance(item, dict) else None
    ref = pw.sweet_ref(file)
    pos = pw.kodi_seconds(props.get("time"))
    raw, now = channels(), time.time()
    if op == "live":
        if not ref or str(ref[0]).startswith("vod:") or not ref[1]:
            raise pw.Refused(_t("An archived programme is not playing."), 409)
        open_url(ml.url(ref[0]), rpc)
        return {"ok": True, "switched": "live"}
    if op == "from_start":
        if ref and not str(ref[0]).startswith("vod:") and not ref[1]:
            ch = _channel(raw, ref[0])
            cur_p = _on_now(ch, now)
            if cur_p and archive_ok(ch, cur_p, now):
                epg_id = str(cur_p.get("id"))
                open_url(ml.url(ref[0], epg_id, 0), rpc)
                return {"ok": True, "switched": "archive", "epg": epg_id, "offset": 0}
            raise pw.Refused(_t(ml.NO_ARCHIVE), 409)
        pw._rpc(rpc, "Player.Seek", {"playerid": pid, "value": pw.time_value(0)})
        return {"ok": True, "offset": 0}
    if op in ("prev_prog", "next_prog", "seek_wall"):
        return {"ok": True}
    # op == "seek_by"
    sec = c["seconds"]
    if ref and not str(ref[0]).startswith("vod:") and not ref[1]:
        if sec < 0:
            found = rewind(raw, file, sec, now)
            if found and found["switched"]:
                open_url(found["url"], rpc)
                return {"ok": True, "switched": "archive", "epg": found["epg"], "offset": found["offset"]}
            if found and found.get("note"):
                pw._rpc(rpc, "Player.Seek", {"playerid": pid, "value": {"seconds": sec}})
                return {"ok": True, "switched": "", "note": found["note"]}
        pw._rpc(rpc, "Player.Seek", {"playerid": pid, "value": {"seconds": sec}})
        return {"ok": True}
    if ref and not str(ref[0]).startswith("vod:") and ref[1] and sec > 0:
        handoff = ml.forward_handoff(raw, ref[0], ref[1], max(0, int(pos) + sec), now)
        if handoff:
            open_url(handoff["url"], rpc)
            return {"ok": True, "switched": "live"}
    pw._rpc(rpc, "Player.Seek", {"playerid": pid, "value": {"seconds": sec}})
    return {"ok": True}


# ---- API helpers -----------------------------------------------------------------------------

def _answered(result):
    if result.get("ok"):
        return result
    raise pw.Refused(str(result.get("message") or _t("SWEET.TV answered with an error. Try again in a minute.")),
                     API_STATUS.get(result.get("error"), 502))


def search_view(raw, needle, now, quality="1080p", client=None):
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    return _answered(api.search(needle, api.channel_map(raw), now, client=client, quality=quality))


def _canonical_day_item(p, cid, now, local_data=None):
    epg_id = str(p.get("epg") or p.get("id") or "")
    start = int(p.get("start") or p.get("time_start") or 0)
    stop = int(p.get("stop") or p.get("time_stop") or 0)
    item = {
        "id": epg_id,
        "epg": epg_id,
        "cid": str(cid),
        "title": str(p.get("title") or p.get("text") or ""),
        "start": start,
        "stop": stop,
        "when": str(p.get("when") or (api.when_text(start, now) if api and start else "")),
        "live": bool(p.get("live")) if "live" in p else bool(start <= now < stop),
        "can_archive": bool(p.get("can_archive")),
        "available": p.get("available") is not False,
        "preview": str(p.get("preview") or p.get("image_url") or ""),
        "season": int(p.get("season") or 0),
        "episode": int(p.get("episode") or 0),
        "show_id": str(p.get("show_id") or ""),
    }
    if local_data is not None:
        saved = _saved(local_data, cid, epg_id)
        min_pos = mr.MIN_POS if mr else 15
        item["resume"] = saved["pos"] if saved and not saved["done"] and saved["pos"] >= min_pos else 0
        item["watched"] = bool(saved and saved["done"])
    return item


def day_view(raw, cid, date_text, now, local_data=None, client=None):
    if ml is None or api is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    if not isinstance(cid, str) or not ml.url(cid):
        raise pw.Refused(_t("Wrong channel."))
    when = api.parse_date(date_text)
    if when is None:
        raise pw.Refused(_t("Wrong date."))
    ch_map = api.channel_map(raw)
    ch = ch_map.get(str(cid))
    code = api.check_day(ch, when, now)
    if code:
        return _answered({"ok": False, "error": code})
    if sweetstore is not None:
        try:
            stored = sweetstore.default_store().channel_day(cid, when.isoformat(), now=now)
        except Exception:
            stored = []
        if stored:
            items = [_canonical_day_item(p, cid, now, local_data) for p in stored if (p.get("stop") or 0) > (p.get("start") or 0)]
            if items:
                return {
                    "ok": True,
                    "cid": str(cid),
                    "name": str((ch or {}).get("name") or "")[:120],
                    "date": when.isoformat(),
                    "now": int(now),
                    "archive_days": api._archive_days(ch),
                    "future_days": api._future_days(ch),
                    "items": items,
                }
    res = _answered(api.day(cid, api.noon(when), ch_map, now, client=client))
    res["items"] = [_canonical_day_item(p, cid, now, local_data) for p in (res.get("items") or [])]
    return res


def open_url(url, rpc):
    if ml is not None:
        ml.ask_url(url)
    pw._rpc(rpc, "Player.Open", {"item": {"file": url}})


def _play_notify_req(body, epg, offset):
    if isinstance(body, dict) and "movie_id" in body and "cid" not in body:
        ep_raw = body.get("episode_id")
        ep_id = "" if ep_raw in (None, "", "null") else str(ep_raw)
        owner_raw = body.get("owner_id", 0)
        owner_id = int(owner_raw) if owner_raw not in (None, "") else 0
        return sp.build_play_notify(
            kind="vod",
            movie_id=str(body.get("movie_id")),
            episode_id=ep_id,
            owner_id=owner_id,
            start_offset=offset,
            title=str(body.get("title") or ""),
        )
    cid = str(body.get("cid"))
    if epg:
        return sp.build_play_notify(
            kind="epg",
            cid=cid,
            epg_id=str(epg),
            start_offset=offset,
            from_start=(body.get("from_start") is True),
            title=str(body.get("title") or ""),
        )
    return sp.build_play_notify(kind="live", cid=cid, from_start=False, title=str(body.get("title") or ""))


def play(body, rpc):
    url, epg, offset = play_request(channels(), body, time.time(), local())
    if sp is not None:
        req = _play_notify_req(body, epg, offset)
        if not _send_notify(rpc, req):
            open_url(url, rpc)
    else:
        open_url(url, rpc)
    res = {"ok": True, "epg": epg, "offset": offset}
    if isinstance(body, dict) and "movie_id" in body and "cid" not in body:
        res["movie_id"] = str(body.get("movie_id"))
    return res


def golive(rpc):
    if ml is None:
        raise pw.Refused(_t("SWEET.TV is not available on this device."), 503)
    pid = pw._player_id(rpc)
    item = None
    if pid is not None:
        item = (pw._rpc(rpc, "Player.GetItem", {"playerid": pid, "properties": ["file"]}) or {}).get("item")
    ref = pw.sweet_ref((item or {}).get("file"))
    if not ref or str(ref[0]).startswith("vod:") or not ref[1]:
        raise pw.Refused(_t("An archived programme is not playing."), 409)
    if sp is not None:
        req = sp.build_play_notify(kind="live", cid=str(ref[0]))
        if not _send_notify(rpc, req):
            open_url(ml.url(ref[0]), rpc)
    else:
        open_url(ml.url(ref[0]), rpc)
    return {"ok": True}


def thumbs_view():
    """GET /api/sweettv/thumbs: validated https://*.sweet.tv sprite cues for active stream."""
    raw = sp.read_active_thumbnails() if sp is not None else None
    clean = _clean_thumbs(raw)
    if clean is None:
        raise pw.Refused("Миниатюры недоступны.", 404)
    return {"ok": True, **clean}


# ---- routes ----------------------------------------------------------------------------------

def get(path, rpc):
    """GET /api/sweettv/...: (body, status)."""
    route, _, query = path.partition("?")
    args = parse_qs(query)
    try:
        if route == PREFIX + "home":
            return home_view(channels(), time.time(), local(), _favs(), _quality()), 200
        if route == PREFIX + "channels":
            return channels_view(channels(), time.time(), _favs()), 200
        if route == PREFIX + "guide":
            return guide_view(channels(), (args.get("cid") or [""])[0], time.time(), local()), 200
        if route == PREFIX + "settings":
            return settings_view(), 200
        if route == PREFIX + "shows":
            return shows_api_view(channels(), time.time(), local(), _favs(), _quality()), 200
        if route == PREFIX + "show":
            return show_api_view(channels(), (args.get("id") or [""])[0], time.time(), local(), _favs()), 200
        if route == PREFIX + "movies":
            return catalog_view("movies", args, local(), _favs(), _quality()), 200
        if route == PREFIX + "series":
            return catalog_view("series", args, local(), _favs(), _quality()), 200
        if route == PREFIX + "vod":
            return vod_view((args.get("id") or [""])[0], local(), _favs()), 200
        if route == PREFIX + "top":
            return top_view(channels(), time.time(), _quality()), 200
        if route == PREFIX + "search":
            return search_view(channels(), (args.get("q") or [""])[0], time.time(), _quality()), 200
        if route == PREFIX + "day":
            return day_view(channels(), (args.get("cid") or [""])[0], (args.get("date") or [""])[0], time.time(), local()), 200
        if route == PREFIX + "thumbs":
            return thumbs_view(), 200
    except pw.Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404


def post(path, body, rpc):
    """POST /api/sweettv/... (the panel has already checked X-Panel and the host): (body, status)."""
    route = path.split("?")[0]
    try:
        if route == PREFIX + "play":
            return play(body, rpc), 200
        if route == PREFIX + "ctl":
            return ctl(body, rpc), 200
        if route == PREFIX + "favourite":
            return toggle_favourite(body), 200
        if route == PREFIX + "golive":
            return golive(rpc), 200
        if route == PREFIX + "settings":
            return set_settings(body), 200
    except pw.Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404
