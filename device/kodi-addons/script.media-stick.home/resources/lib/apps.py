"""The app list: installed add-ons plus web apps, ordered by recency, and launching."""
import json
import os
import re
import tempfile
import time
from typing import NamedTuple

import xbmc
import xbmcvfs

ADDON_ID = "script.media-stick.home"
RECENT_DIR = f"special://profile/addon_data/{ADDON_ID}/"
APP_ART = f"special://home/addons/{ADDON_ID}/resources/media/apps/"
FALLBACK_ART = f"special://home/addons/{ADDON_ID}/resources/skins/default/media/app-fallback.png"

HIDE_PREFIXES = ("script.module.", "resource.", "service.", "script.media-stick.")
HIDE_IDS = {"script.skinshortcuts", "script.skinvariables", "script.favourites",
            "script.globalsearch", "plugin.video.themoviedb.helper"}
DEFAULT_ORDER = ["plugin.video.sweettv", "plugin.video.youtube", "webapp:netflix", "webapp:disney",
                 "webapp:prime", "webapp:max", "script.plex"]
WEB_APPS = [("webapp:netflix", "Netflix", "netflix"), ("webapp:disney", "Disney+", "disney"),
            ("webapp:prime", "Prime Video", "prime"), ("webapp:max", "HBO Max", "max")]
QUERIES = [("xbmc.python.pluginsource", "video"),
           ("xbmc.python.pluginsource", "executable"),
           ("xbmc.python.script", "executable"),
           ("xbmc.python.script", "video")]
ID_RE = re.compile(r"webapp:[a-z0-9-]+|[A-Za-z0-9._-]+")


class App(NamedTuple):
    id: str
    name: str
    art: str


def is_hidden(addon_id):
    return addon_id in HIDE_IDS or addon_id.startswith(HIDE_PREFIXES)


def order(apps, recent):
    """Recently launched first (newest first), then DEFAULT_ORDER, then by name."""
    rank = {app_id: i for i, app_id in enumerate(DEFAULT_ORDER)}

    def key(app):
        if app.id in recent:
            return (0, -recent[app.id], "")
        if app.id in rank:
            return (1, rank[app.id], "")
        return (2, 0, app.name.casefold())
    return sorted(apps, key=key)


def _query(addon_type, content):
    request = {"jsonrpc": "2.0", "id": 1, "method": "Addons.GetAddons",
               "params": {"type": addon_type, "content": content, "enabled": True,
                          "properties": ["name", "thumbnail"]}}
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        return reply.get("result", {}).get("addons") or []
    except (ValueError, AttributeError, TypeError):
        xbmc.log(f"[{ADDON_ID}] Addons.GetAddons failed for {addon_type}/{content}", xbmc.LOGWARNING)
        return []


def installed():
    found = {}
    for addon_type, content in QUERIES:
        for item in _query(addon_type, content):
            addon_id = item.get("addonid", "")
            if addon_id and addon_id not in found and not is_hidden(addon_id):
                found[addon_id] = App(addon_id, item.get("name") or addon_id,
                                      item.get("thumbnail") or FALLBACK_ART)
    return list(found.values())


def web_apps():
    return [App(app_id, name, f"{APP_ART}{art}.png") for app_id, name, art in WEB_APPS]


def _recent_path():
    return os.path.join(xbmcvfs.translatePath(RECENT_DIR), "recent.json")


def load_recent():
    try:
        with open(_recent_path(), encoding="utf-8") as f:
            data = json.load(f)
        return {k: float(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def record(app_id):
    recent = load_recent()
    recent[app_id] = time.time()
    path = _recent_path()
    tmp = None
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(recent, f)
        os.replace(tmp, path)
    except OSError as e:
        xbmc.log(f"[{ADDON_ID}] cannot write recent.json: {e}", xbmc.LOGWARNING)
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def ordered_apps():
    return order(installed() + web_apps(), load_recent())


def launch(app_id):
    if not ID_RE.fullmatch(app_id or ""):
        xbmc.log(f"[{ADDON_ID}] refusing to launch {app_id!r}", xbmc.LOGWARNING)
        return
    record(app_id)
    if app_id.startswith("webapp:"):
        xbmc.executebuiltin(f"RunScript(script.media-stick.webapp,{app_id.split(':', 1)[1]})")
    else:
        xbmc.executebuiltin(f"RunAddon({app_id})")
