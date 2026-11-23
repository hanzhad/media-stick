"""The device's language, applied from inside Kodi (the only supported way to change an add-on's settings while Kodi runs):

  RunScript(script.media-stick.home,lang)

takes no argument: the phone page's panel writes the language into /var/lib/media-stick/prefs/language and asks for
this script (device/files/usr/local/lib/media-stick/mediastick_lang.py has the table and the file). The service runs the
same reconcile once at start, so a language chosen while Kodi was down is applied then. Only a setting whose value
differs is written. Kodi's own interface language and the YouTube region are not touched here.
"""
import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import store, ui   # noqa: F401  (store puts the shared library on the path)
import mediastick_lang as lang        # noqa: E402

PROPERTY = "media-stick.lang"         # the Home window property our own screens read


def reconcile(code=None):
    """Make the add-ons and the Home property follow the language file. Never raises; returns the settings written."""
    try:
        chosen = lang.resolve(code) if code else lang.resolve(lang.read())
    except Exception as e:
        ui.log(f"lang: cannot read the language ({type(e).__name__})", xbmc.LOGERROR)
        return []
    written = []
    for (addon_id, setting), value in lang.wanted(chosen).items():
        try:
            addon = xbmcaddon.Addon(addon_id)
            if addon.getSettingString(setting) != value:
                if addon.setSettingString(setting, value) is False:
                    ui.log(f"lang: {addon_id} refused {setting}", xbmc.LOGWARNING)
                    continue
                written.append(f"{addon_id}:{setting}")
        except RuntimeError:                  # Kodi's way of saying there is no such add-on
            continue
        except Exception as e:
            ui.log(f"lang: {addon_id} {setting} failed ({type(e).__name__})", xbmc.LOGERROR)
    try:
        window = xbmcgui.Window(ui.HOME)
        if window.getProperty(PROPERTY) != chosen.code:
            window.setProperty(PROPERTY, chosen.code)
    except Exception as e:
        ui.log(f"lang: cannot set {PROPERTY} ({type(e).__name__})", xbmc.LOGERROR)
    ui.log(f"lang: {chosen.code}, wrote {', '.join(written) or 'nothing'}", xbmc.LOGINFO)
    return written


def main(args=()):
    """Entry for `RunScript(script.media-stick.home,lang)`."""
    return reconcile()
