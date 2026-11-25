# Keeps the launcher window on screen whenever Kodi is on the skin Home.
# show() plus waitForAbort() is what lets the window's callbacks run.
import os
import sys
import threading
import time

import xbmc
import xbmcgui

from resources.lib.launcher import ADDON_PATH, Launcher

_LIB_DIR = "/usr/local/lib/media-stick"
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    from mediastick_display import DisplayClient  # noqa: E402
except Exception:
    DisplayClient = None

LOG = "[script.media-stick.home]"
HOME_WINDOWS = (10000,)
STATUS_EVERY = 5                     # seconds between IP / network refreshes
SAMPLE_EVERY = 5                     # seconds between two looks at what plays (resume_recorder)
IDLE_POLL = 1.0                      # seconds between checks while idle on Home
PLAYING_POLL = 5.0                   # seconds between checks while video plays
BLOCKED = "System.ScreenSaverActive | System.HasModalDialog | System.HasActiveModalDialog"


def poll_interval(playing):
    """Adaptive waitForAbort interval: slower during playback, 1 Hz while idle."""
    return PLAYING_POLL if playing else IDLE_POLL


def _notify_displayd(playing):
    """Notify mediastick-displayd of playback transitions; no-op when absent."""
    if DisplayClient is None:
        return
    client = None
    try:
        client = DisplayClient()
        client.set_kodi_playing(bool(playing))
    except Exception as e:
        xbmc.log(f"{LOG} displayd notify({playing!r}) skipped: {e!r}", xbmc.LOGWARNING)
    finally:
        if client is not None and hasattr(client, "close"):
            try:
                client.close()
            except Exception:
                pass




_MonitorBase = getattr(xbmc, "Monitor", object)


class HomeMonitor(_MonitorBase):
    """Wakes the real launcher immediately when Kodi opens Home."""

    def __init__(self, on_home=None):
        super().__init__()
        self._on_home = on_home

    def onNotification(self, sender, method, data):
        if self._on_home is not None and "home_shown" in (method or ""):
            self._on_home()


def _set_home_ready(value):
    try:
        xbmcgui.Window(10000).setProperty("launcher_ready", value)
    except Exception:
        pass

_PlayerBase = getattr(xbmc, "Player", object)


class PlaybackNotifier(_PlayerBase):
    """Tracks playback state and notifies mediastick-displayd on start/stop/end."""

    def __init__(self, notify=_notify_displayd):
        super().__init__()
        self.playing = False
        self._notify = notify

    def _set_playing(self, playing):
        self.playing = bool(playing)
        self._notify(self.playing)

    def onAVStarted(self):
        self._set_playing(True)

    def onPlayBackStopped(self):
        self._set_playing(False)

    def onPlayBackEnded(self):
        self._set_playing(False)

    def onPlayBackError(self):
        self._set_playing(False)


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


def start_recorder():
    """Remembers where the person stopped (resume_recorder); None when the device has no library for it."""
    try:
        from resources.lib import resume_recorder
        return resume_recorder.start()
    except Exception as e:
        xbmc.log(f"{LOG} positions not recorded: {type(e).__name__}", xbmc.LOGERROR)
        return None


def sample(watcher):
    try:
        watcher.tick()
    except Exception as e:
        xbmc.log(f"{LOG} position not read: {e!r}", xbmc.LOGWARNING)


def main():
    xbmc.log(f"{LOG} service started", xbmc.LOGINFO)
    apply_language()
    watcher = start_recorder()
    lock = threading.RLock()
    player = PlaybackNotifier()
    launcher = None

    def show_launcher():
        nonlocal launcher
        if xbmc.getCondVisibility(BLOCKED):
            return False
        with lock:
            if launcher is None:
                launcher = Launcher("script-media-stick-home.xml", ADDON_PATH, "default", "1080i")
            launcher.show()
        return True

    monitor = HomeMonitor(on_home=show_launcher)
    _set_home_ready("1")
    last_status = last_sample = time.monotonic()
    try:
        while not monitor.abortRequested():
            try:
                current = xbmcgui.getCurrentWindowId()
                blocked = xbmc.getCondVisibility(BLOCKED)
                if current in HOME_WINDOWS and not blocked:
                    try:
                        show_launcher()
                    except Exception as e:
                        xbmc.log(f"{LOG} cannot create the launcher window: {e!r}", xbmc.LOGERROR)
                        if monitor.waitForAbort(30):
                            break
                        continue
                with lock:
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
                with lock:
                    drop(launcher)
                    launcher = None
                monitor.waitForAbort(5)
            if watcher is not None and time.monotonic() - last_sample >= SAMPLE_EVERY:
                last_sample = time.monotonic()
                sample(watcher)
            if monitor.waitForAbort(poll_interval(player.playing)):
                break
    finally:
        _set_home_ready("")
        with lock:
            drop(launcher)
            launcher = None
    del player


main()
