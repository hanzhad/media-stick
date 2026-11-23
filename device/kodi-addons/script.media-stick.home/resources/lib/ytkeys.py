"""The YouTube add-on's personal Google keys, written from inside Kodi (the only supported way to change an
add-on's settings while Kodi runs):

  RunScript(script.media-stick.home,ytkeys)

takes no argument: the phone page's panel leaves the values in a private file in /run/media-stick and asks for
this script (device/files/usr/local/lib/media-stick/mediastick_ytkeys.py has the hand-over and the rules).
The request is read and deleted first, the three settings are written, and the answer goes back in a second
file. Nothing here logs a value: the log gets the operation and its outcome, an exception only by its type.
"""
import xbmc
import xbmcaddon

from resources.lib import store, ui   # noqa: F401  (store puts the shared library on the path)
import mediastick_ytkeys as keys      # noqa: E402


def open_addon():
    return xbmcaddon.Addon(keys.ADDON)


def perform(request, addon):
    """Write the request's three values (all empty for `clear`) into the add-on's settings: "" or an error code."""
    values = request["values"] if request["op"] == "save" else {}
    for name, setting in keys.SETTINGS.items():
        if addon.setSettingString(setting, values.get(name, "")) is False:
            return "write_failed"
    return ""


def main(args=()):
    """Entry for `RunScript(script.media-stick.home,ytkeys)`: never raises; True when the settings were written."""
    try:
        request = keys.take_request()
    except keys.BadRequest as e:
        ui.log(f"ytkeys: request refused ({e.code})")
        if e.id:
            keys.send_result(e.id, False, e.code)
        return False
    try:
        error = perform(request, open_addon())
    except RuntimeError:                  # Kodi's way of saying there is no such add-on
        error = "addon_missing"
    except Exception as e:
        ui.log(f"ytkeys {request['op']} failed: {type(e).__name__}", xbmc.LOGERROR)
        error = "write_failed"
    ok = not error
    keys.send_result(request["id"], ok, error, request["values"].get("api_key", "") if ok else "")
    ui.log(f"ytkeys {request['op']}: {'done' if ok else error}", xbmc.LOGINFO)
    return ok
