# media-stick overlay of service.py (0.1.13, upstream sha256 f9c72a1a5ebfb7ac88941ca9f86b79a3a52f971645fa9dfd8b242331579c8ff8): changes sit between media-stick begin/end
import time

import xbmc

from resources.lib.helper import Helper
from resources.lib.sweettv import refreshToken, initSettings, refreshChannelList

if __name__ == '__main__':
    monitor = xbmc.Monitor()
    helper = Helper()
    refreshChannelListTimer = 0
    # media-stick begin
    ms_failed = 0   # fetches in a row that did not give a channel list
    # media-stick end
    initSettings()

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
