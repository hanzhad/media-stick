"""Remembers where the person stopped, whoever started the video (the phone, the YouTube or SWEET.TV app of the TV, Kodi's
own lists), in the stick's own file (mediastick_resume). Runs in the home add-on's service: the Player's callbacks and
one look every SAMPLE_EVERY seconds at what plays.

The positions are recorded whether or not «remember where I stopped, on the device» is on: the choice only decides
whether the places that offer to continue read them (mediastick_resume.enabled()). So switching it on shows what was
watched since this version, not an empty page.

Recorder is plain Python (it is fed samples, the tests feed it directly); Watcher is the thin Kodi part.
"""
import time

import xbmc

from resources.lib import store

LOG = "[script.media-stick.home]"
SAMPLE_EVERY = 5                      # s between two looks at the player (the place of a stop is at most this old)


class Recorder:
    """Samples of (file, position, length) in, positions out: written when a video changes, stops or ends, and otherwise at
    most every mediastick_resume.WRITE_EVERY seconds, so the SD card is not written to every few seconds."""

    def __init__(self, lib, clock=time.time, meta=None, path=None, log=None):
        self.lib, self.clock, self.meta_of, self.path, self.log = lib, clock, meta, path, log or (lambda text: None)
        self.file = ""                # the item being followed ("" when none)
        self.last = None              # (position, length) seen last
        self.written = 0.0            # when the place of this item was last written
        self.meta = None              # title, start, stop of a SWEET.TV programme (looked up once per item)

    def _remembered(self, file):
        return bool(file) and self.lib.parse(file) is not None

    def sample(self, file, pos, total):
        """What plays now: `file` at `pos` of `total` seconds. A file that is not one of the remembered kinds ends the
        previous one and is itself ignored."""
        if file != self.file:
            self.flush()
            self.file, self.last, self.written, self.meta = (file if self._remembered(file) else ""), None, 0.0, None
        if not self.file:
            return
        self.last = (pos, total)
        if self.lib.due(self.written, self.clock()):
            self._write()

    def flush(self):
        """The item stopped (or is replaced): its last sample is its place."""
        if self.file and self.last:
            self._write()
        self.last = None

    def finish(self):
        """The item played to its end: the place is the end (watched, a full bar)."""
        if self.file and self.last:
            self.last = (self.last[1], self.last[1])
            self._write()
        self.last = None

    def _meta(self):
        parsed = self.lib.parse(self.file)
        if self.meta is None:
            self.meta = {}
            if parsed and parsed[0] == "sw" and parsed[2] and self.meta_of:
                try:
                    self.meta = self.meta_of(parsed[1], parsed[2]) or {}
                except Exception as e:
                    self.log("programme not looked up: %r" % (e,))
        return self.meta

    def _write(self):
        pos, total = self.last
        before = self.lib.load(self.path)
        after = self.lib.record(before, self.file, pos, total, self.clock(), self._meta())
        self.written = self.clock()
        if after != before and not self.lib.save(after, self.path):
            self.log("positions not written")


def programme_meta(cid, epg):
    """{"title", "start", "stop"} of a SWEET.TV programme from SweetStore; {} when it is not there."""
    import mediastick_sweetstore as sweetstore
    rec = sweetstore.default_store().recall_programme(epg, cid=cid)
    if not rec:
        return {}
    out = {
        "title": str(rec.get("title") or "")[:120],
        "start": int(rec.get("start") or rec.get("time_start") or 0),
        "stop": int(rec.get("stop") or rec.get("time_stop") or 0),
    }
    if rec.get("show_id"):
        out["show_id"] = rec["show_id"]
    if rec.get("season"):
        out["season"] = rec["season"]
    if rec.get("episode"):
        out["episode"] = rec["episode"]
    if rec.get("preview") or rec.get("image_url"):
        out["thumb"] = rec.get("preview") or rec.get("image_url")
    return out


class Watcher(xbmc.Player):
    def __init__(self, recorder):
        xbmc.Player.__init__(self)
        self.recorder = recorder

    def _file(self):
        """The path of what plays: the player's own, else the label Kodi keeps for a plugin item, else the plugin path of the
        stream address the player gives (an archived programme: the add-on wrote down which one it is); "" when none is one
        the library remembers."""
        streams = []
        for ask in (self.getPlayingFile, lambda: xbmc.getInfoLabel("Player.Filenameandpath")):
            try:
                found = ask()
            except RuntimeError:
                continue
            if self.recorder.lib.parse(found):
                return found
            streams.append(found)
        return self._known(streams)

    @staticmethod
    def _known(streams):
        lib = store.sweetlive
        for found in streams:
            try:
                known = lib.identify(found, time.time()) if lib else None
            except Exception:
                known = None
            if known:
                if known[0].startswith("vod:"):
                    return lib.vod_url(known[0][4:], known[1] or None, 0)
                return lib.url(known[0], known[1])   # no place in it: one string for the whole item, whatever its start was
        return ""

    def tick(self):
        try:
            if not self.isPlayingVideo():
                return
            self.recorder.sample(self._file(), self.getTime(), self.getTotalTime())
        except RuntimeError:           # it stopped between the look and the question
            pass

    def onPlayBackStopped(self):
        self.recorder.flush()

    def onPlayBackError(self):
        self.recorder.flush()

    def onPlayBackEnded(self):
        self.recorder.finish()


def start():
    """The watcher of the service, None when the device has no library for it."""
    if store.resume is None:
        return None
    return Watcher(Recorder(store.resume, meta=programme_meta,
                            log=lambda text: xbmc.log("%s resume: %s" % (LOG, text), xbmc.LOGWARNING)))
