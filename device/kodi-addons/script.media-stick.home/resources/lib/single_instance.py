"""One window per app: "already open" is decided by whether the app's window is really there.

An app (YouTube, SWEET.TV, the onboarding window) marks itself open with a property of the Home window and clears it in
a `finally` after doModal(). The window can go away without that `finally` running (the phone's Home key does
ActivateWindow(Home), a script is killed), and a flag nobody clears would block every later launch until Kodi restarts.
So the flag says who set it and where its window is, and a launch asks Kodi whether that window is still there:

  <token>:<window id>:<start time>        the property value; the window id is empty until the window is open

  inst = single_instance.claim(home, RUNNING)     None when a live instance holds the flag, else ours
  inst.bind(xbmcgui.getCurrentWindowId())         from onInit (getCurrentWindowDialogId() for a dialog)
  inst.release()                                  in the `finally`: clears the flag only if it is still ours

A flag is live for GRACE seconds from its start (the window id is not known yet, and a double press on the card must
open one window), while its window is the active one (also under a dialog), and while a video plays (the player's
fullscreen window is then the active one; the app is behind it). Anything else is stale and the new launch takes over.
A value that is not this format (an old "1") has no window and no start: stale.
"""
import os
import time
from collections import namedtuple

import xbmc

GRACE = 15.0                      # s after the start in which a flag is live whatever Kodi says (no window id yet)

Flag = namedtuple("Flag", "token window_id started")


def encode(flag):
    return f"{flag.token}:{flag.window_id or ''}:{flag.started:.0f}"


def decode(value):
    """The flag a property value holds; None for an empty value; one with no token for a value that is not ours."""
    if not value:
        return None
    try:
        token, window_id, started = value.split(":")
        return Flag(token, int(window_id) if window_id else 0, float(started))
    except ValueError:
        return Flag("", 0, 0.0)


def is_live(flag, now, window_active, video_playing):
    """Whether the instance that set `flag` is still there. `window_active(id)` and `video_playing()` ask Kodi."""
    if flag is None:
        return False
    if now - flag.started < GRACE:
        return True
    if flag.window_id and window_active(flag.window_id):
        return True
    return bool(video_playing())


def window_active(window_id):
    return bool(xbmc.getCondVisibility(f"Window.IsActive({window_id})"))


def video_playing():
    return bool(xbmc.getCondVisibility("Player.HasVideo"))


class Instance:
    """The flag of one launch."""

    def __init__(self, home, key, token, started):
        self.home, self.key, self.token, self.started = home, key, token, started

    def _mine(self):
        flag = decode(self.home.getProperty(self.key))
        return flag is not None and flag.token == self.token

    def bind(self, window_id):
        """Say which window this launch opened (a stale instance that finds the flag taken over writes nothing)."""
        if self._mine():
            self.home.setProperty(self.key, encode(Flag(self.token, window_id, self.started)))

    def release(self):
        """Clear the flag, but only if it is still this launch's: an old one finishing late must not clear a new one's."""
        if self._mine():
            self.home.setProperty(self.key, "")


def claim(home, key, clock=time.time, active=None, playing=None):
    """Take the flag `key` of the Home window `home`. None when a live instance holds it."""
    now = clock()
    if is_live(decode(home.getProperty(key)), now, active or window_active, playing or video_playing):
        return None
    token = os.urandom(4).hex()
    home.setProperty(key, encode(Flag(token, 0, now)))
    inst = Instance(home, key, token, now)
    return inst if inst._mine() else None          # two launches that took it at once: the later write stays
