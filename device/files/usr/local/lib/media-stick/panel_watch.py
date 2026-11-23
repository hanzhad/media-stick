"""The "Смотреть" part of the panel: pick an app on the phone, browse what to watch, send it to the TV,
and run the player from the phone. JSON under /api/watch/.

What is known about the content is not written a second time here: the add-on's pure modules
(resources/lib/sweettv_data.py, youtube_data.py, apps.py) are loaded from where the add-on lives on
the device (or from the repository next to this file) and used as they are. apps.py imports xbmc
only to log and to find a file, so it is loaded with two empty stand-ins for the length of the load.
Everything else here is a function from ready data to data; the thin part at the bottom talks to
Kodi through the `rpc` callable the panel hands in (its kodi() JSON-RPC helper) and reads files.
The page's markup, style and script live in panel_watch_ui.py; inject() puts them into the page.

Standard library only, nothing happens on import.
"""
import importlib.util
import json
import os
import re
import sys
import threading
import time
import types
from urllib.parse import parse_qs, unquote, urlsplit

import mediastick_signin as signin
import mediastick_screen as screen   # a cast or a web app has the TV: say so, not "Kodi не отвечает"
import panel_watch_ui as ui

PREFIX = "/api/watch/"
LAUNCHER = "script.media-stick.home"
KODI_DOWN = "Kodi не отвечает. Подождите минуту и попробуйте снова."
ADDON_LIB = os.path.join("script.media-stick.home", "resources", "lib")
HERE = os.path.dirname(os.path.abspath(__file__))
LIB_DIRS = (os.environ.get("MEDIASTICK_ADDON_LIB", ""),
            "/home/media/.kodi/addons/" + ADDON_LIB,
            "/opt/media-stick/device/kodi-addons/" + ADDON_LIB,
            os.path.join(HERE, "..", "..", "..", "..", "..", "kodi-addons", ADDON_LIB))

# Pictures are passed through only from the image CDNs the add-ons' art comes from; the page never loads
# anything else and the panel proxies nothing.
IMAGE_HOSTS = ("ytimg.com", "ggpht.com", "googleusercontent.com", "sweet.tv")
IMAGE_MAX = 512

YT_SECTIONS = {"home": "rec", "subscriptions": "subs", "history": "history", "playlists": "lists",
               "trending": "trend", "search": "search"}
CATALOG_APPS = ("plugin.video.sweettv", "plugin.video.youtube")
SWEET_PLAY_RE = re.compile(r"plugin://plugin\.video\.sweettv/playvid/([0-9]{1,12})\|(null|[0-9]{1,12})")
APPS_TTL, ROUTES_TTL = 60, 300
RESUME_MIN, RESUME_MAX = 5, 86400
SEEK_MAX = 86400
START_WAIT = 40                  # s a started stream gets before the resume seek is given up on


class Refused(Exception):
    def __init__(self, message, code=400):
        super().__init__(message)
        self.message, self.code = message, code


# ---- the add-on's pure modules ---------------------------------------------------------------

_loaded = {}
_load_lock = threading.Lock()


def _find(name):
    for folder in LIB_DIRS:
        path = os.path.join(folder, name + ".py") if folder else ""
        if path and os.path.isfile(path):
            return path
    return ""


def load_module(name, stubs=()):
    """The add-on's resources/lib/<name>.py as a module of its own (no package, no clash with the panel's
    names), or None when this device has no such file. `stubs` are names of modules (xbmc, xbmcvfs) that
    the file imports but never needs while it is read: empty ones stand in during the load only."""
    with _load_lock:
        if name in _loaded:
            return _loaded[name]
        path = _find(name)
        module = None
        if path:
            added = [s for s in stubs if s not in sys.modules]
            for s in added:
                sys.modules[s] = types.ModuleType(s)
            try:
                spec = importlib.util.spec_from_file_location("mswatch_" + name, path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
            except Exception:
                module = None
            finally:
                for s in added:
                    sys.modules.pop(s, None)
        _loaded[name] = module
        return module


def yt():
    return load_module("youtube_data")


def sweet():
    return load_module("sweettv_data")


def launcher_apps():
    return load_module("apps", stubs=("xbmc", "xbmcvfs"))


# ---- pictures --------------------------------------------------------------------------------

def image_url(value):
    """The https address of a picture, or "" . Kodi's art is `image://<url-encoded address>/`; it is decoded,
    and passed on only when it is https to one of IMAGE_HOSTS (a host or any of its subdomains)."""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if text.startswith("image://"):
        text = unquote(text[len("image://"):].rstrip("/")).strip()
    if not text or len(text) > IMAGE_MAX or any(ord(c) < 33 or ord(c) > 126 for c in text):
        return ""
    try:
        u = urlsplit(text)
        port = u.port
    except ValueError:
        return ""
    host = (u.hostname or "").lower()
    if u.scheme != "https" or u.username or u.password or port not in (None, 443):
        return ""
    return text if any(host == d or host.endswith("." + d) for d in IMAGE_HOSTS) else ""


# ---- what may be played ----------------------------------------------------------------------

def play_target(file):
    """The path to hand to Player.Open, or "" when it is not one the page may start: a YouTube play route
    (the launcher's own PATH_RE decides what a path may hold) or a SWEET.TV `playvid/<channel>|<epg or null>`."""
    if not isinstance(file, str):
        return ""
    data, sw = yt(), sweet()
    text = file.strip()
    if data is not None and data.PATH_RE.fullmatch(text):
        route = urlsplit(text).path
        if (route.startswith("/play/") or route == "/play") and "/../" not in route + "/":
            return text
        return ""
    m = SWEET_PLAY_RE.fullmatch(text)
    if m and sw is not None:
        return sw.play_url(m.group(1), None if m.group(2) == "null" else m.group(2))
    return ""


def clean_resume(value):
    """Seconds to start from, 0 when none (or too small to matter, or not a number)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        return 0
    return int(value) if RESUME_MIN <= value <= RESUME_MAX else 0


def app_of(file):
    f = file if isinstance(file, str) else ""
    if f.startswith("plugin://plugin.video.youtube/"):
        return "youtube"
    if f.startswith("plugin://plugin.video.sweettv/"):
        return "sweettv"
    return "other"


# ---- apps ------------------------------------------------------------------------------------

def build_apps(mod, found, recent):
    """The launcher's list for the phone: `found` is the add-ons Kodi has (dicts with addonid and name), `mod`
    the launcher's apps module (hide rules, web apps, order). -> [{id, name, kind}]"""
    seen, apps = set(), []
    for item in found:
        addon_id = item.get("addonid", "") if isinstance(item, dict) else ""
        if addon_id and addon_id not in seen and not mod.is_hidden(addon_id):
            seen.add(addon_id)
            apps.append(mod.App(addon_id, item.get("name") or addon_id, ""))
    apps += mod.web_apps()
    ordered = mod.order(apps, recent if isinstance(recent, dict) else {})
    return [{"id": a.id, "name": a.name, "kind": "catalog" if a.id in CATALOG_APPS else "launch"}
            for a in ordered if a.id != mod.CARD_ID]


# ---- YouTube ---------------------------------------------------------------------------------

def map_entry(e):
    """One of youtube_data's entries as the page gets it."""
    video = e.kind == "video"
    resume = int(round(e.progress * e.seconds)) if video and e.seconds and 0 < e.progress < 0.97 else 0
    return {"title": e.title, "channel": e.channel, "duration": e.seconds, "views": e.views,
            "published": e.published, "thumb": image_url(e.thumb), "file": e.path,
            "playable": video, "folder": e.kind == "folder", "live": e.live, "count": e.count,
            "progress": round(e.progress, 3), "resume": resume if resume >= RESUME_MIN else 0}


def folder_path(value):
    """A directory path the page asks for: only the YouTube add-on's own, as the launcher's PATH_RE allows."""
    data = yt()
    if isinstance(value, str) and data is not None and data.PATH_RE.fullmatch(value.strip()):
        return value.strip()
    return ""


def youtube_state(data, gated, listing, keys):
    """The page's state word for a listing: data | empty | needkey | signin | error."""
    if gated:
        return {data.SIGNIN: "signin", data.NEEDKEY: "needkey"}.get(gated, "error")
    mode = data.mode_for(listing, keys)
    if mode == data.UNAVAILABLE:
        return "needkey" if keys is not True else "error"
    return {data.DATA: "data", data.EMPTY: "empty", data.NEEDKEY: "needkey"}.get(mode, "error")


def youtube_reply(data, result, error_text=""):
    """The JSON-RPC answer in the shape youtube_data.parse_reply reads. kodi() hands over only `result`; None
    there means Kodi answered with an error, which for these paths is the add-on refusing ("Invalid params")."""
    if result is None:
        return {"error": {"code": data.INVALID_PARAMS, "message": error_text or "Invalid params"}}
    return {"result": result}


# ---- SWEET.TV --------------------------------------------------------------------------------

def sweet_programme(p, now):
    percent = int(round(100 * (now - p.start) / (p.stop - p.start))) if p.stop > p.start else 0
    return {"title": p.title, "start": p.start, "end": p.stop, "percent": max(0, min(100, percent))}


def sweet_channel(sw, c, now):
    cur, nxt = sw.now_next(c, now)
    return {"id": c.cid, "name": c.name, "number": c.number, "icon": image_url(c.logo),
            "cats": ["c:" + k for k in c.cats], "catchup": c.catchup, "play": sw.play_url(c.cid),
            "now": sweet_programme(cur, now) if cur else None,
            "next": {"time": sw.hhmm(nxt.start), "start": nxt.start, "title": nxt.title} if nxt else None}


def sweet_view(sw, raw, now, signed=True, mtime=None):
    """channelList.json (already read as JSON, None when there is no readable file) -> the page's answer. The
    parsing is the add-on's: sweettv_data.parse_catalog."""
    if raw is None:
        return {"state": "signin", "channels": [], "categories": []}
    catalog = sw.parse_catalog(raw, now)
    if catalog.error:
        return {"state": "error", "channels": [], "categories": []}
    state = sw.view_mode(signed, catalog)
    if state != sw.DATA:
        return {"state": state, "channels": [], "categories": []}
    return {"state": "data", "stale": mtime is not None and sw.is_stale(mtime, now),
            "channels": [sweet_channel(sw, c, now) for c in catalog.channels],
            "categories": [{"key": k, "name": n} for k, n in catalog.categories]}


# ---- the player ------------------------------------------------------------------------------

def kodi_seconds(t):
    if not isinstance(t, dict):
        return 0
    try:
        return max(0, t.get("hours", 0) * 3600 + t.get("minutes", 0) * 60 + t.get("seconds", 0)
                   + t.get("milliseconds", 0) / 1000)
    except TypeError:
        return 0


def time_value(seconds):
    s = int(seconds)
    return {"time": {"hours": s // 3600, "minutes": s // 60 % 60, "seconds": s % 60, "milliseconds": 0}}


def _streams(items, current, label):
    out = []
    for i, s in enumerate(items if isinstance(items, list) else []):
        if not isinstance(s, dict):
            continue
        idx = s.get("index", i)
        name = str(s.get("name") or "").strip() or str(s.get("language") or "").upper() or "%s %d" % (label, i + 1)
        out.append({"index": idx, "name": name[:60], "language": str(s.get("language") or "")[:8]})
    cur = current.get("index") if isinstance(current, dict) else None
    return out, cur


def now_view(item, props, app):
    """The page's "now playing" from Player.GetItem's item, Player.GetProperties and Application.GetProperties."""
    item = item if isinstance(item, dict) else {}
    props = props if isinstance(props, dict) else {}
    art = item.get("art") if isinstance(item.get("art"), dict) else {}
    thumb = image_url(item.get("thumbnail")) or image_url(art.get("thumb")) or image_url(art.get("poster"))
    subs, sub_cur = _streams(props.get("subtitles"), props.get("currentsubtitle"), "Субтитры")
    audio, audio_cur = _streams(props.get("audiostreams"), props.get("currentaudiostream"), "Дорожка")
    app = app if isinstance(app, dict) else {}
    return {"playing": True,
            "title": str(item.get("title") or item.get("label") or "")[:200],
            "channel": str(item.get("showtitle") or item.get("channel") or "")[:120],
            "thumb": thumb, "app": app_of(item.get("file")),
            "time": kodi_seconds(props.get("time")), "total": kodi_seconds(props.get("totaltime")),
            "speed": props.get("speed", 1), "subtitles": subs, "subtitle": sub_cur,
            "subtitles_on": bool(props.get("subtitleenabled")), "audio": audio, "audio_index": audio_cur,
            "volume": app.get("volume"), "muted": bool(app.get("muted"))}


def _number(value, low, high, what):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != value:
        raise Refused("Нужно число: %s." % what)
    if not low <= value <= high:
        raise Refused("Вне диапазона: %s." % what)
    return value


def _index(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 99:
        raise Refused("Неверный номер дорожки.")
    return value


def clean_ctl(body):
    """The page's control request, checked: a dict with `op` and only the arguments that op takes."""
    if not isinstance(body, dict):
        raise Refused("Неверный запрос.")
    op = body.get("op")
    if op in ("playpause", "stop", "mute"):
        return {"op": op}
    if op == "seek":
        if "to" in body:
            return {"op": op, "to": _number(body["to"], 0, SEEK_MAX, "время")}
        return {"op": op, "by": _number(body.get("by"), -SEEK_MAX, SEEK_MAX, "сдвиг")}
    if op == "volume":
        if "level" in body:
            return {"op": op, "level": int(_number(body["level"], 0, 100, "громкость"))}
        return {"op": op, "by": int(_number(body.get("by"), -100, 100, "громкость"))}
    if op == "subtitle":
        return {"op": op, "off": True} if body.get("off") is True else {"op": op, "index": _index(body.get("index"))}
    if op == "audio":
        return {"op": op, "index": _index(body.get("index"))}
    raise Refused("Неизвестная команда.")


NEEDS_PLAYER = ("playpause", "stop", "seek", "subtitle", "audio")


def ctl_rpc(c, playerid, volume=None):
    """(method, params) for a checked request. A volume step is turned into a level from `volume`, the current one."""
    op = c["op"]
    if op == "playpause":
        return "Player.PlayPause", {"playerid": playerid}
    if op == "stop":
        return "Player.Stop", {"playerid": playerid}
    if op == "seek":
        value = time_value(c["to"]) if "to" in c else {"seconds": int(c["by"])}
        return "Player.Seek", {"playerid": playerid, "value": value}
    if op == "volume":
        level = c["level"] if "level" in c else max(0, min(100, int(volume or 0) + c["by"]))
        return "Application.SetVolume", {"volume": level}
    if op == "mute":
        return "Application.SetMute", {"mute": "toggle"}
    if op == "subtitle":
        if c.get("off"):
            return "Player.SetSubtitle", {"playerid": playerid, "subtitle": "off"}
        return "Player.SetSubtitle", {"playerid": playerid, "subtitle": c["index"], "enable": True}
    return "Player.SetAudioStream", {"playerid": playerid, "stream": c["index"]}


# ---- what the page reads: files and Kodi -----------------------------------------------------

_cache = {}


def _cached(key, ttl, make):
    hit = _cache.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    value = make()
    if value is not None:
        _cache[key] = (now, value)
    return value


def _rpc(rpc, method, params=None):
    try:
        return rpc(method, params or {})
    except (OSError, ValueError):
        raise Refused(screen.kodi_down(), 503)


def _read_json(path):
    try:
        with open(path, "rb") as f:
            return json.load(f), os.stat(path).st_mtime
    except (OSError, ValueError, MemoryError):
        return None, None


def _addon_data(addon, name):
    return os.path.join(signin.USERDATA, addon, name)


def apps_view(rpc):
    mod = launcher_apps()
    if mod is None:
        raise Refused("Список приложений недоступен на этом устройстве.", 503)

    def make():
        found = []
        for addon_type, content in mod.QUERIES:
            try:
                r = rpc("Addons.GetAddons", {"type": addon_type, "content": content, "enabled": True,
                                             "properties": ["name", "thumbnail"]})
            except (OSError, ValueError):
                r = None
            found += (r or {}).get("addons") or [] if isinstance(r, dict) else []
        recent, _ = _read_json(os.path.join(signin.USERDATA, LAUNCHER, "recent.json"))
        return build_apps(mod, found, recent)
    return {"apps": _cached("apps", APPS_TTL, make) or []}


def launch(body, rpc):
    app = body.get("app") if isinstance(body, dict) else None
    if not isinstance(app, str) or app not in [a["id"] for a in apps_view(rpc)["apps"]]:
        raise Refused("Неизвестное приложение.")
    _cache.pop("apps", None)      # the launcher records it as the latest one
    _rpc(rpc, "Addons.ExecuteAddon", {"addonid": LAUNCHER, "params": ["launch", app]})
    return {"ok": True}


def _keys_configured(data):
    try:
        with open(_addon_data("plugin.video.youtube", "settings.xml"), encoding="utf-8") as f:
            text = f.read()
    except OSError:
        text = None
    from_settings = data.settings_keys_present(text) if text is not None else False
    raw, _ = _read_json(_addon_data("plugin.video.youtube", "api_keys.json"))
    return data.keys_state(from_settings, data.keys_present(raw))


def _directory(data, rpc, route):
    media = "files" if route == data.ROOT else "video"
    try:
        result = rpc("Files.GetDirectory", {"directory": route, "media": media, "properties": data.PROPERTIES,
                                            "sort": {"method": "none"}}, 6)
    except (OSError, ValueError):
        raise Refused(screen.kodi_down(), 503)
    return data.parse_reply(youtube_reply(data, result))


def _routes(data, rpc):
    def make():
        listing = _directory(data, rpc, data.ROOT)
        return data.discover_routes(listing) if listing.entries else None
    return _cached("routes", ROUTES_TTL, make) or {}


def youtube_view(query, rpc):
    data = yt()
    if data is None:
        raise Refused("YouTube недоступен на этом устройстве.", 503)
    section = YT_SECTIONS.get((query.get("section") or ["home"])[0])
    if section is None:
        raise Refused("Неизвестный раздел.")
    accounts = signin.youtube_accounts()
    signed = any(p["signed_in"] for p in accounts) if accounts else False
    keys = _keys_configured(data)
    path = folder_path((query.get("path") or [""])[0])
    if (query.get("path") or [""])[0] and not path:
        raise Refused("Недопустимый путь.")
    if path:
        view, gated = data.View(data.FOLDER_KEY, "", path, False), None
    else:
        if section == "rec" and not signed:
            section = "trend"      # without an account the home page is what everyone sees
        text = data.clean_query((query.get("q") or [""])[0])
        if section == data.SEARCH and not text:
            return {"state": "prompt", "section": "search", "items": [], "more": ""}
        view = data.section_view(section, _routes(data, rpc) if section != data.SEARCH else None, text)
        gated = data.gate(signed, view.needs_login, keys)
    if gated:
        listing = data.Listing((), "", "")
    else:
        listing = _directory(data, rpc, view.route)
    return {"state": youtube_state(data, gated, listing, keys), "section": view.key,
            "items": [map_entry(e) for e in listing.entries], "more": listing.more, "signed": signed,
            "keys": keys, "error": listing.error}


def sweettv_view():
    sw = sweet()
    if sw is None:
        raise Refused("SWEET.TV недоступен на этом устройстве.", 503)
    temp = os.path.join(os.path.dirname(os.path.dirname(signin.USERDATA)), "temp", "channelList.json")
    raw, mtime = _read_json(temp)
    signed = signin.sweettv_signed_in()
    return sweet_view(sw, raw, time.time(), signed, mtime)


def _player_id(rpc):
    players = _rpc(rpc, "Player.GetActivePlayers")
    for p in players if isinstance(players, list) else []:
        if isinstance(p, dict) and p.get("type") == "video":
            return p.get("playerid")
    for p in players if isinstance(players, list) else []:
        if isinstance(p, dict) and isinstance(p.get("playerid"), int):
            return p["playerid"]
    return None


PLAYER_PROPS = ["time", "totaltime", "speed", "subtitles", "currentsubtitle", "subtitleenabled",
                "audiostreams", "currentaudiostream"]
ITEM_PROPS = ["title", "showtitle", "thumbnail", "art", "file"]


def now_state(rpc):
    pid = _player_id(rpc)
    if pid is None:
        return {"playing": False}
    item = (_rpc(rpc, "Player.GetItem", {"playerid": pid, "properties": ITEM_PROPS}) or {}).get("item")
    props = _rpc(rpc, "Player.GetProperties", {"playerid": pid, "properties": PLAYER_PROPS})
    app = _rpc(rpc, "Application.GetProperties", {"properties": ["volume", "muted"]})
    return now_view(item, props, app)


def _seek_when_started(rpc, seconds):
    """Resume: Player.Open's own resume option is not relied on; once the stream runs, seek to the place."""
    end = time.time() + START_WAIT
    while time.time() < end:
        time.sleep(1.5)
        try:
            pid = _player_id(rpc)
            if pid is None:
                continue
            props = rpc("Player.GetProperties", {"playerid": pid, "properties": ["totaltime"]})
            if kodi_seconds((props or {}).get("totaltime")) > seconds + 5:
                rpc("Player.Seek", {"playerid": pid, "value": time_value(seconds)})
                return
        except (OSError, ValueError):
            return


def play(body, rpc):
    body = body if isinstance(body, dict) else {}
    target = play_target(body.get("file"))
    if not target:
        raise Refused("Это нельзя запустить.")
    _rpc(rpc, "Player.Open", {"item": {"file": target}})
    resume = clean_resume(body.get("resume"))
    if resume:
        threading.Thread(target=_seek_when_started, args=(rpc, resume), daemon=True).start()
    return {"ok": True}


def ctl(body, rpc):
    c = clean_ctl(body)
    pid = None
    if c["op"] in NEEDS_PLAYER:
        pid = _player_id(rpc)
        if pid is None:
            raise Refused("Сейчас ничего не играет.", 409)
    volume = None
    if c["op"] == "volume" and "by" in c:
        volume = (_rpc(rpc, "Application.GetProperties", {"properties": ["volume"]}) or {}).get("volume")
    method, params = ctl_rpc(c, pid, volume)
    _rpc(rpc, method, params)
    return {"ok": True}


# ---- routes ----------------------------------------------------------------------------------

def get(path, rpc):
    """GET /api/watch/...: (body, status)."""
    parts = urlsplit(path)
    query = parse_qs(parts.query)
    try:
        if parts.path == PREFIX + "apps":
            return apps_view(rpc), 200
        if parts.path == PREFIX + "youtube":
            return youtube_view(query, rpc), 200
        if parts.path == PREFIX + "sweettv":
            return sweettv_view(), 200
        if parts.path == PREFIX + "now":
            try:
                return now_state(rpc), 200
            except Refused:
                return {"playing": False}, 200
    except Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404


def post(path, body, rpc):
    """POST /api/watch/... (the panel has already checked X-Panel and the host): (body, status)."""
    route = urlsplit(path).path
    try:
        if route == PREFIX + "launch":
            return launch(body, rpc), 200
        if route == PREFIX + "play":
            return play(body, rpc), 200
        if route == PREFIX + "ctl":
            return ctl(body, rpc), 200
    except Refused as e:
        return {"error": e.message}, e.code
    return {"error": "not found"}, 404


def inject(page):
    """The panel's page with the Смотреть tab put in front: its section, its tab button, its style and script."""
    return ui.inject(page)
