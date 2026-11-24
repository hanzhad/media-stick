# media-stick overlay of service.py (0.1.13, upstream sha256 f9c72a1a5ebfb7ac88941ca9f86b79a3a52f971645fa9dfd8b242331579c8ff8): changes sit between media-stick begin/end
import time

import xbmc

from resources.lib.helper import Helper
from resources.lib.sweettv import refreshToken, initSettings, refreshChannelList

# media-stick begin: going back on a live channel plays the archive of the programme on now (the window of a live stream is
# about a minute): a seek back, and a pause that outlasts the window. The deciding is mediastick_sweetlive.plan, which the
# phone's -10 asks too. An archive asked to start somewhere other than its beginning is put there once it has begun (Kodi
# ignores the start place of a plugin item), and an item whose address is a stream's is known from what the plugin wrote down
import sys as _ms_sys
import threading as _ms_threading

import xbmcgui as _ms_gui
from resources.lib import sweettv as _ms_sweettv

try:
    _ms_sys.path.insert(0, '/usr/local/lib/media-stick')
    import mediastick_sweetlive as _ml
except Exception:  # not a media-stick device: the add-on behaves as upstream
    _ml = None


class _MsPlayer(xbmc.Player):
    def __init__(self):
        xbmc.Player.__init__(self)
        self.paused_at = 0
        self.quiet_until = 0

    def _live(self):
        # the channel id of the live SWEET.TV stream that is playing, else ''
        try:
            found = _ml.identify(self.getPlayingFile(), time.time())
        except Exception:
            return ''
        return found[0] if found and not found[1] else ''

    def onAVStarted(self):
        # an archive that was asked to start at second N: the stream starts at 0 and the player is told where it should be
        try:
            file = self.getPlayingFile()
            entry = _ml.start_place(file, time.time())
            if entry:
                _ms_threading.Thread(target=self._to_place, args=(entry, file), daemon=True).start()
        except Exception as e:
            xbmc.log('media-stick: SWEET.TV start place not looked at: ' + repr(e)[:120], xbmc.LOGWARNING)

    def _to_place(self, entry, file):
        try:
            result = _ml.follow(self, entry, file)
            xbmc.log('media-stick: SWEET.TV start place %ss: %s' % (entry['offset'], result), xbmc.LOGINFO)
        except Exception as e:
            xbmc.log('media-stick: SWEET.TV start place not set: ' + repr(e)[:120], xbmc.LOGWARNING)

    def _rewind(self, cid, back):
        if time.time() < self.quiet_until:   # a held key sends several seeks: the first one counts
            return
        self.quiet_until = time.time() + 8
        try:
            plan = _ml.plan(_ms_sweettv.helper.get_channel_list(), cid, back, int(time.time()))
        except Exception as e:
            xbmc.log('media-stick: SWEET.TV rewind not planned: ' + repr(e)[:120], xbmc.LOGWARNING)
            return
        if plan['ok']:
            _ml.ask_url(plan['url'])   # the add-on that resolves it is told the place here too: the path may lose its query
            xbmc.executebuiltin('PlayMedia(%s)' % plan['url'])
        elif plan['reason'] == 'no_archive':
            _ms_gui.Dialog().notification('SWEET.TV', _ml.text(_ml.NO_ARCHIVE), _ms_gui.NOTIFICATION_INFO)

    def onPlayBackSeek(self, seek_time, seek_offset):
        cid = self._live() if seek_offset < 0 else ''
        if cid:
            self._rewind(cid, -seek_offset / 1000.0)

    def onPlayBackPaused(self):
        self.paused_at = time.time() if self._live() else 0

    def onPlayBackResumed(self):
        paused, self.paused_at = self.paused_at, 0
        cid = self._live() if paused else ''
        if cid and time.time() - paused > _ml.PAUSE_LIMIT:
            self._rewind(cid, time.time() - paused)

    def onPlayBackStopped(self):
        self.paused_at = 0

    def onPlayBackEnded(self):
        self.paused_at = 0
# media-stick end

if __name__ == '__main__':
    monitor = xbmc.Monitor()
    helper = Helper()
    refreshChannelListTimer = 0
    # media-stick begin
    ms_failed = 0   # fetches in a row that did not give a channel list
    # media-stick end
    initSettings()
    # media-stick begin
    ms_player = _MsPlayer() if _ml else None
    # media-stick end

    while not monitor.abortRequested():
        try:
            refreshToken()

            if int(time.time()) - refreshChannelListTimer > 15 * 60:
                # media-stick begin: a failed fetch is due again on the next pass (a minute), up to five times in a row, then every quarter of an hour
                ms_reply = refreshChannelList()
                refreshChannelListTimer = int(time.time())
                if isinstance(ms_reply, dict) and ms_reply.get('status') == 'OK':
                    ms_failed = 0
                else:
                    ms_failed += 1
                    if ms_failed <= 5:
                        refreshChannelListTimer -= 15 * 60
                # media-stick end

            if monitor.waitForAbort(60):
                break
        except Exception as e:
            xbmc.log("Service exception: " + str(e), xbmc.LOGERROR)
