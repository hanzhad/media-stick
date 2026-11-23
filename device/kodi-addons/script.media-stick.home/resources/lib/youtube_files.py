"""YouTube app: where its data lives and how it is asked for: the add-on's directories (JSON-RPC), who is signed in,
whether a personal Google key is set, the app's own state file (see youtube_state). Thin: each function is one look
or one call; what to make of the answer is youtube_data's business. get_directory() waits for the add-on, which may
take seconds on the network: call it from a worker thread, never from the UI."""
import json
import os

import xbmc
import xbmcvfs

from resources.lib import apps, ui, youtube_data as data

SETTINGS_FILE = "settings.xml"   # in the add-on's userdata folder: <setting id="youtube.api.key">..</setting> (and .id, .secret)
KEYS_FILE = "api_keys.json"      # the same folder, the older place: {"keys": {"personal": {"api_key", "client_id", "client_secret"}}}


def state_path():
    return os.path.join(xbmcvfs.translatePath(apps.RECENT_DIR), "youtube.json")


def rpc(method, params):
    """The parsed JSON-RPC answer, {} when there is none."""
    request = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    try:
        reply = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
    except (ValueError, TypeError) as e:
        ui.log(f"{method} gave no answer: {e!r}")
        return {}
    return reply if isinstance(reply, dict) else {}


def get_directory(route):
    """The raw answer to Files.GetDirectory for a plugin://plugin.video.youtube/ path, in the add-on's own order.
    The route is passed as it is, never with a slash added or dropped. The main page is a plain file listing (what
    the add-on answered it as when seen on a device); everything below it lists videos."""
    media = "files" if route == data.ROOT else "video"
    return rpc("Files.GetDirectory", {"directory": route, "media": media, "properties": data.PROPERTIES,
                                      "sort": {"method": "none"}})


def play(path):
    return rpc("Player.Open", {"item": {"file": path}})


def _current_profile():
    """The add-on's current profile ({id, name, current, tokens, signed_in}), None when there is none; raises when
    the sign-in library is not on this device."""
    from resources.lib import store
    return next((p for p in store.lib.youtube_accounts() if p["current"]), None)


def signed_in():
    """True/False as the add-on's current profile says; None when the sign-in library is not on this device."""
    try:
        current = _current_profile()
        return bool(current and current["signed_in"])
    except Exception as e:
        ui.log(f"cannot tell whether YouTube is signed in: {e!r}")
        return None


def profile_name():
    """The name of the add-on's current profile, "" when there is none or it cannot be told (the avatar shows it)."""
    try:
        current = _current_profile()
        return str(current["name"]) if current else ""
    except Exception as e:
        ui.log(f"cannot read the YouTube profile's name: {e!r}")
        return ""


STEP_FILE = "/run/media-stick/ytkeys.step.json"    # the phone page's key wizard writes its progress here (no secrets)


def read_step(now, path=STEP_FILE):
    """The key wizard's current step (data.Step), None when no wizard is running: no file, not readable, not JSON, a
    step of 0, a file older than data.STEP_MAX_AGE. A look costs one small file read."""
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, ValueError, MemoryError) as e:
        ui.log(f"key wizard progress not readable: {e!r}")
        return None
    return data.parse_step(raw, now)


def phone_page():
    """(address of the phone page, QR picture of it); ("", "") when the stick has no network or no QR can be made.
    The SWEET.TV app's look at the same thing (it caches the QR by address and tries a failing address once)."""
    try:
        from resources.lib import sweettv_files
        return sweettv_files.phone_page()
    except Exception as e:
        ui.log(f"phone page unknown: {e!r}")
        return "", ""


def _read(folder, name):
    """(text, readable): the file `name` of the add-on's userdata `folder`; ("", True) when there is none."""
    try:
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            return f.read(), True
    except FileNotFoundError:
        return "", True
    except (OSError, ValueError) as e:
        ui.log(f"{name} not readable: {e!r}")
        return "", False


def _json_keys(text, readable):
    """What api_keys.json says: True/False, None when it could not be read or is not JSON."""
    if not readable:
        return None
    if not text:
        return False
    try:
        return data.keys_present(json.loads(text))
    except ValueError as e:                      # the position only: never a value
        ui.log(f"{KEYS_FILE} is not JSON: {e!r}")
        return None


def _settings_keys(text, readable):
    """What settings.xml says: True/False, None when it could not be read or is not XML."""
    if not readable:
        return None
    return data.settings_keys_present(text) if text else False


def keys_configured():
    """True when the add-on has a personal Google key, False when it has none; None when that cannot be told.
    The add-on keeps the key in its settings (youtube.api.key, .id, .secret in settings.xml); api_keys.json is the
    fallback. Values are never logged."""
    try:
        from resources.lib import store
        folder = os.path.join(store.lib.USERDATA, data.PLUGIN_ID)
    except Exception as e:
        ui.log(f"cannot tell whether the Google key is set: {e!r}")
        return None
    settings, keys = _read(folder, SETTINGS_FILE), _read(folder, KEYS_FILE)
    return data.keys_state(_settings_keys(*settings), _json_keys(*keys))
