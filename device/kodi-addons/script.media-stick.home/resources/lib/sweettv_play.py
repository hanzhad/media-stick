"""SWEET.TV app: starting a stream and remembering where an archived programme stopped.

Live and archive go through the plugin (`plugin://plugin.video.sweettv/playvid/<channel>|<epg id or null>`): the
plugin asks the service for the stream and hands it to inputstream.adaptive, so pause, rewind and stop are the
player's own keys. Nothing here draws; the window calls these from worker threads.

For a programme watched from the archive, `follow` watches the player while it runs (the window itself is
behind the full-screen video and sees nothing), seeks to the saved place when asked, and reports the last
position it saw when the player stops. The player is reached through a small object (`PlayerIO`), so the
loop is tested without Kodi.
"""
import json
from typing import NamedTuple

import xbmc

POLL = 5                         # s between looks at the player
START_WAIT = 120                 # s the stream gets to start before it is given up on
SEEK_MARGIN = 5                  # s: a stream is "seekable" when it is this much longer than the place to go to


class Session(NamedTuple):
    """An archived programme being played."""
    cid: str
    epg: str
    title: str
    start: int
    stop: int

    def programme(self) -> dict:
        return {"epg": self.epg, "title": self.title, "start": self.start, "stop": self.stop}


class PlayerIO:
    """The player, as `follow` sees it."""

    def __init__(self):
        self._player = xbmc.Player()

    def playing(self) -> bool:
        try:
            return bool(self._player.isPlaying())
        except Exception:
            return False

    def position(self):
        """(seconds played, seconds in all) or None when the player has nothing to say."""
        try:
            return float(self._player.getTime()), float(self._player.getTotalTime())
        except Exception:
            return None

    def seek(self, seconds):
        self._player.seekTime(float(seconds))

    def stop(self):
        self._player.stop()


def open_request(url) -> str:
    """The JSON-RPC call that plays `url` full screen."""
    return json.dumps({"jsonrpc": "2.0", "id": 1, "method": "Player.Open", "params": {"item": {"file": url}}})


def follow(session, io, stopped, report, seek_to=0, poll=None):
    """Watch the player until it stops. `stopped` is a threading.Event that ends the watch early; `report(session,
    pos, total)` is called once with the last position seen (nothing is reported when the stream never started).
    With `seek_to`, the player is moved there once the stream is long enough to go that far."""
    poll = POLL if poll is None else poll
    started, waited, pos, total = False, 0, 0.0, 0.0
    pending = seek_to > 0
    while not stopped.is_set():
        if io.playing():
            started = True
            seen = io.position()
            if seen:
                pos, total = seen
                if pending and total > seek_to + SEEK_MARGIN:
                    io.seek(seek_to)
                    pending, pos = False, float(seek_to)
        elif started:
            break
        elif waited >= START_WAIT:
            return
        waited += poll
        if stopped.wait(poll):
            break
    if started:
        report(session, pos, total)
