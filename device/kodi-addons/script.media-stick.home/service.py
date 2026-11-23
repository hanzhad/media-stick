# Keeps the launcher window on screen whenever Kodi is on the skin Home.
# show() plus waitForAbort() is what lets the window's callbacks run.
import time

import xbmc
import xbmcgui

from resources.lib.launcher import ADDON_PATH, Launcher

LOG = "[script.media-stick.home]"
HOME_WINDOWS = (10000,)
STATUS_EVERY = 5                     # seconds between IP / network refreshes
BLOCKED = "System.ScreenSaverActive | System.HasModalDialog | System.HasActiveModalDialog"


def drop(launcher):
    if launcher is not None:
        try:
            launcher.close()
        except Exception:
            pass


def apply_language():
    """The device's language file may have been written while Kodi was down: apply it once, now."""
    try:
        from resources.lib import lang
        lang.reconcile()
    except Exception as e:
        xbmc.log(f"{LOG} language not applied: {type(e).__name__}", xbmc.LOGERROR)


def main():
    xbmc.log(f"{LOG} service started", xbmc.LOGINFO)
    apply_language()
    monitor = xbmc.Monitor()
    launcher = None
    last_status = time.monotonic()
    while not monitor.abortRequested():
        try:
            current = xbmcgui.getCurrentWindowId()
            blocked = xbmc.getCondVisibility(BLOCKED)
            if current in HOME_WINDOWS and not blocked:
                if launcher is None:
                    try:
                        launcher = Launcher("script-media-stick-home.xml", ADDON_PATH, "default", "1080i")
                    except Exception as e:
                        xbmc.log(f"{LOG} cannot create the launcher window: {e!r}", xbmc.LOGERROR)
                        if monitor.waitForAbort(30):
                            break
                        continue
                launcher.show()
            if launcher is not None:
                # once shown, the launcher is itself the current window, not Home: idle is judged
                # there too, and cleared under a dialog or once the window is left
                on_screen = current in HOME_WINDOWS or current == launcher.window_id()
                launcher.refresh_idle(on_screen and not blocked)
                if time.monotonic() - last_status >= STATUS_EVERY:
                    last_status = time.monotonic()
                    launcher.refresh_status()
        except Exception as e:
            xbmc.log(f"{LOG} loop error: {e!r}", xbmc.LOGERROR)
            drop(launcher)
            monitor.waitForAbort(5)
            launcher = None
        if monitor.waitForAbort(0.15):
            break
    drop(launcher)
    del launcher


main()
