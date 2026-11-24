# media-stick overlay of sweettv.py (0.1.13, upstream sha256 0637d3cd62d3d7a57543b0cb3a10f925cb9a9d5a42056000733404210dd2acf1): changes sit between media-stick begin/end
# coding: UTF-8
import sys
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import routing
import urllib3
import xbmc
import xbmcgui
import xbmcplugin
import xbmcvfs
from six.moves.urllib.parse import urlencode

# media-stick begin: publish the sign-in code for the TV screen and the phone page
try:
    import sys as _ms_sys
    _ms_sys.path.insert(0, '/usr/local/lib/media-stick')
    import mediastick_signin as _ms
except Exception:  # not a media-stick device: the add-on behaves as upstream
    _ms = None
# media-stick end

urllib3.disable_warnings()

from .helper import Helper

base_url = sys.argv[0]
try:
    handle = int(sys.argv[1])
except:
    handle = None  # or whatever you want to do
helper = Helper(base_url, handle)
plugin = routing.Plugin()

# media-stick begin: the language of the categories and programme titles (the accept-language header). The box has one
# language, the phone's «Язык» (mediastick_lang); once it was chosen SWEET.TV is asked in it, and a long-lived process
# (the service) reads it again before every request. Without a choice: the add-on's own setting, but upstream's untouched
# default (Hungarian) is Russian
MS_LANGUAGE = 'ru'


def _ms_language_untouched():
    # upstream's default is 'hu'. Kodi writes a setting nobody has changed as default="true" (or not at all): that one
    # is ours to replace; a 'hu' the person chose is kept
    try:
        translate = getattr(xbmcvfs, 'translatePath', None) or xbmc.translatePath
        with open(translate('special://profile/addon_data/%s/settings.xml' % helper.addon_name), encoding='utf-8') as f:
            text = f.read()
    except FileNotFoundError:
        return True
    except Exception:
        return False
    import re as _ms_re
    found = _ms_re.search(r'<setting id="countryCode"([^>]*)>', text)
    return found is None or 'default="true"' in found.group(1)


def _ms_language():
    try:
        import mediastick_lang as _ms_lang
        from os.path import exists as _ms_exists
        if _ms_exists(_ms_lang.path()):
            return _ms_lang.resolve(_ms_lang.read()).sweet   # the box's language, chosen by the owner
    except Exception:  # not a media-stick device, or the file cannot be read: the add-on's own setting decides
        pass
    stored = helper.get_setting('countryCode') or helper.countryCode
    return MS_LANGUAGE if stored == 'hu' and _ms_language_untouched() else stored


def _ms_sync_language():
    code = _ms_language()
    if code and code != helper.countryCode:
        helper.countryCode = code
    if code:
        helper.headers['accept-language'] = code


_ms_sync_language()
# media-stick end


def getTime(x, y):
    data = ''
    if y == 'date':
        data = '%Y-%m-%d'
    elif y == 'hour':
        data = '%H:%M'
    return datetime.fromtimestamp(x).strftime(data)


# media-stick begin: the sign-in token is read when it is needed. `helper` is built when this module is imported: in the sign-in
# (which stays in this process for hours) and in the add-on's service (which lives from Kodi's start) that is before the new
# bearer is stored, and a helper built without one sends no authorization: the channel list never loads
def _ms_sync_auth():
    bearer = helper.get_setting('bearer')
    helper.bearer = bearer
    if bearer:
        helper.headers.update({'authorization': bearer})
    else:
        helper.headers.pop('authorization', None)


def _ms_status(reply):
    # the answer's own status field and nothing else: never the body, never a token
    status = reply.get('status') if isinstance(reply, dict) else None
    return repr(status)[:40] if isinstance(status, (str, int)) else type(status).__name__
# media-stick end


def refreshChannelList():
    if not helper.get_setting('logged'):
        return
    # media-stick begin
    _ms_sync_auth()
    _ms_sync_language()   # the language may have been chosen since this process started
    # media-stick end

    timestamp = int(time.time())
    json_data = {
        'epg_limit_prev': 10,
        'epg_limit_next': 100,
        'epg_current_time': timestamp,
        'need_epg': True,
        'need_list': True,
        'need_categories': True,
        'need_offsets': False,
        'need_hash': False,
        'need_icons': False,
        'need_big_icons': False,
    }

    url = helper.base_api_url.format('TvService/GetChannels.json')
    jsdata = helper.request_sess(url, 'post', headers=helper.headers, data=json_data, json=True, json_data=True,
                                 result=False)

    if jsdata is None:
        # media-stick begin
        xbmc.log('media-stick: SWEET.TV channel list not updated: no answer (authorization sent: %s)'
                 % ('authorization' in helper.headers), xbmc.LOGWARNING)
        # media-stick end
        return

    jsdata_content = jsdata.content
    jsdata = jsdata.json()

    categories = {}

    if jsdata.get("status", None) == 'OK':
        if "categories" in jsdata:
            for category in jsdata.get('categories', None):
                categories.update({category.get('id', None): category.get('caption', None)})

        if "list" in jsdata:
            xml_root = ET.Element("tv")
            for json_channel in jsdata.get("list"):
                channel = ET.SubElement(xml_root, "channel",
                                        attrib={"id": str(json_channel.get("id")) + ".id.com"})
                ET.SubElement(channel, "display-name", lang=helper.countryCode).text = json_channel.get("name")
                ET.SubElement(channel, "icon", src=json_channel.get("icon_url"))
            for json_channel in jsdata.get("list"):
                if "epg" in json_channel:
                    for json_epg in json_channel.get("epg"):
                        programme_metadata = {
                            "start": time.strftime('%Y%m%d%H%M%S',
                                                   time.localtime(json_epg.get("time_start"))) + " +0100",
                            "stop": time.strftime('%Y%m%d%H%M%S',
                                                  time.localtime(json_epg.get("time_stop") - 1)) + " +0100",
                            "channel": str(json_channel.get("id")) + ".id.com"
                        }

                        if json_channel.get("catchup") and json_channel.get("available") and json_epg.get("available"):
                            catchup = {"catchup-id": str(json_epg.get("id"))}
                            programme_metadata.update(catchup)

                        programme = ET.SubElement(xml_root, "programme", attrib=programme_metadata)
                        if json_epg.get("available") == False and json_channel.get("live_blackout") == True:
                            ET.SubElement(programme, "title",
                                          lang=helper.countryCode).text = "!NOT AVAILABLE! " + json_epg.get(
                                "text")
                        else:
                            ET.SubElement(programme, "title", lang=helper.countryCode).text = json_epg.get("text")
                else:
                    programme = ET.SubElement(xml_root, "programme", attrib={
                        "start": time.strftime('%Y%m%d%H%M%S', time.localtime(time.time())) + " +0100",
                        "stop": time.strftime('%Y%m%d%H%M%S', time.localtime(time.time() + (12 * 60 * 60))) + " +0100",
                        "channel": str(json_channel.get("id")) + ".id.com"})
                    ET.SubElement(programme, "title", lang=helper.countryCode).text = json_channel.get("name")

            tree = ET.ElementTree(xml_root)
            if sys.version_info[:3] >= (3, 9, 0):
                ET.indent(tree, space="  ", level=0)
            xmlstr = '<?xml version="1.0" encoding="utf-8"?>\n'.encode("utf-8") + ET.tostring(xml_root,
                                                                                              encoding='utf-8')
            path_m3u = helper.get_setting('path_m3u')
            file_name = helper.get_setting('name_epg')
            if path_m3u != '' and file_name != '':
                f = xbmcvfs.File(path_m3u + file_name, 'w')
                f.write(xmlstr)
                f.close()

            data = '#EXTM3U\n'
            for json_channel in jsdata.get("list"):
                if json_channel.get('available', None):
                    img = json_channel.get('icon_v2_url', None)
                    cName = json_channel.get('name', None)
                    cid = json_channel.get('id', None)
                    category_list = ''
                    for category in json_channel.get('category', None):
                        if category in categories and category != 1000:
                            category_list += categories[category] + ';'
                    category_list = category_list[:-1]

                    if json_channel.get('catchup', None):
                        catchup = 'catchup="vod" catchup-source="plugin://plugin.video.sweettv/playvid/%s|{catchup-id}"' % (
                            cid)
                    else:
                        catchup = ''
                    data += '#EXTINF:0 tvg-id="%s.id.com" tvg-name="%s" tvg-logo="%s" group-title="%s" %s,%s\nplugin://plugin.video.sweettv/playvid/%s|null\n' % (
                        cid, cName, img, category_list, catchup, cName, cid)

            file_name = helper.get_setting('name_m3u')
            if path_m3u != '' and file_name != '':
                f = xbmcvfs.File(path_m3u + file_name, 'w')
                f.write(data.encode("utf-8"))
                f.close()

            f = xbmcvfs.File(helper.channelListPath, 'wb')
            f.write(jsdata_content)
            f.close()
    else:
        xbmc.log("Failed to update channel list", xbmc.LOGERROR)
        # media-stick begin: the cause without DEBUG logging: the status the API answered with (never the body, never a token)
        xbmc.log('media-stick: SWEET.TV channel list not updated: status=%s (authorization sent: %s)'
                 % (_ms_status(jsdata), 'authorization' in helper.headers), xbmc.LOGWARNING)
        # media-stick end
        xbmc.log("Failed to update channel list " + str(jsdata), xbmc.LOGDEBUG)

    return jsdata


@plugin.route('/')
def root():
    refresh_token = helper.get_setting('refresh_token')

    xbmc.log("refresh " + refresh_token, xbmc.LOGDEBUG)
    xbmc.log("logged " + str(helper.get_setting('logged')), xbmc.LOGDEBUG)

    if refresh_token == 'None':
        helper.set_setting('bearer', '')
        helper.set_setting('logged', 'false')

    if helper.get_setting('logged'):
        startwt()
    else:
        helper.add_item('[COLOR lightgreen][B]Login[/COLOR][/B]', plugin.url_for(login), folder=False)
        helper.add_item('[B]Settings[/B]', plugin.url_for(settings), folder=False)

    helper.eod()


def initSettings():
    if not helper.uuid:
        import uuid
        uuidx = uuid.uuid4()
        helper.set_setting('uuid', str(uuidx))

    if not helper.mac:
        helper.set_setting('mac', helper.get_random_mac())

    if not helper.access_token_last_update:
        helper.set_setting('access_token_last_update', str(0))

    if not helper.access_token_lifetime:
        helper.set_setting('access_token_lifetime', str(0))

    return


@plugin.route('/startwt')
def startwt():
    helper.add_item('[B]TV[/B]', plugin.url_for(mainpage, mainid='live'), folder=True)
    helper.add_item('[B]Replay[/B]', plugin.url_for(mainpage, mainid='replay'), folder=True)


def refreshToken():
    if not helper.get_setting('logged'):
        return
    # Reduce the token validity to refresh it a bit earlier
    # In this case we always will have a valid Bearer and token
    if int(time.time()) - int(helper.get_setting('access_token_last_update')) > int(int(
            helper.get_setting('access_token_lifetime')) * 0.9):
        json_data = helper.json_data
        json_data.update({"refresh_token": helper.get_setting('refresh_token')})

        jsdata = helper.request_sess(helper.token_url, 'post', headers=helper.headers, data=json_data, json=True,
                                     json_data=True)

        if jsdata is None:
            return

        xbmc.log("refresh " + str(jsdata), xbmc.LOGDEBUG)

        if jsdata.get("access_token", None):
            xbmc.log("Token refresh success", xbmc.LOGDEBUG)
            helper.set_setting('bearer', 'Bearer ' + str(jsdata.get("access_token")))
            helper.headers.update({'authorization': helper.get_setting('bearer')})

            helper.set_setting('access_token_last_update', str(int(time.time())))

            access_token_lifetime = int(jsdata.get("expires_in"))
            helper.set_setting('access_token_lifetime', str(access_token_lifetime))

            return True
        else:
            xbmc.log("Token refresh failed", xbmc.LOGERROR)
            helper.set_setting('logged', 'false')

            return False

    return True


@plugin.route('/getEPG/<epgid>')
def getEPG(epgid):
    epgid, dur = epgid.split('|')
    timestamp = int(time.time())
    json_data = {
        "channels": [
            int(epgid)
        ],
        "epg_current_time": timestamp,
        "need_big_icons": False,
        "need_categories": False,
        "need_epg": True,
        "need_icons": False,
        "need_list": True,
        "need_offsets": False
    }
    url = 'https://api.sweet.tv/TvService/GetChannels.json'
    jsdata = helper.request_sess(url, 'post', headers=helper.headers, data=json_data, json=True, json_data=True)

    if jsdata is None:
        return

    if helper.get_setting('reverse_order') == 'Newest':
        reverse_order = True
    elif helper.get_setting('reverse_order') == 'Oldest':
        reverse_order = False

    tv_shows = []

    if jsdata.get("status", None) == 'OK':
        progs = jsdata['list'][0]['epg']
        for p in progs:
            now = int(time.time())
            tStart = p.get('time_start', None)
            if p['available'] == True and tStart >= now - int(dur) * 24 * 60 * 60 and tStart <= now:
                pid = str(p.get('id', None))
                tit = p.get('text', None)
                date = getTime(p.get('time_start', None), 'date')
                ts = getTime(p.get('time_start', None), 'hour')
                te = getTime(p.get('time_stop', None), 'hour')
                title = '[COLOR=gold]%s[/COLOR] | [B]%s-%s[/B] %s' % (date, ts, te, tit)
                ID = epgid + '|' + pid

                mod = plugin.url_for(playvid, videoid=ID)
                imag = p.get('preview_url_ext', None)
                art = {'icon': imag, 'fanart': helper.addon.getAddonInfo('fanart')}

                info = {'title': title, 'plot': ''}

                tv_show_data = {
                    "title": title,
                    "url": mod,
                    "info": info,
                    "art": art
                }
                tv_shows.append(tv_show_data)

        for s in reversed(tv_shows) if reverse_order is True else tv_shows:
            helper.add_item(s["title"], s["url"], playable=True, info=s["info"], art=s["art"], folder=False,
                            content='videos')

    helper.eod()


@plugin.route('/mainpage/<mainid>')
def mainpage(mainid):
    jsdata = helper.get_channel_list()

    if jsdata.get("status", None) == 'OK':
        for j in jsdata.get('list', []):
            catchup = j.get('catchup', None)
            available = j.get('available', None)
            isShow = False
            if (mainid == 'replay' and catchup and available) or (mainid == 'live' and available):
                isShow = True
            if isShow:
                _id = str(j.get('id', None))
                title = j.get('name', None)
                slug = j.get('slug', None)
                epgs = j.get('epg', None)
                epg = ''
                if mainid == 'live' and epgs:
                    for e in epgs:
                        if e.get('time_stop', None) > int(time.time()):
                            tit = e.get('text', None)
                            ts = getTime(e.get('time_start', None), 'hour')
                            te = getTime(e.get('time_stop', None), 'hour')
                            epg += '[B]%s-%s[/B] %s\n' % (ts, te, tit)

                if mainid == 'live':
                    idx = _id + '|null'  # +slug
                    mod = plugin.url_for(playvid, videoid=idx)
                    fold = False
                    ispla = True
                else:  # id=='replay'
                    dur = str(j.get('catchup_duration', None))
                    idx = _id + '|' + dur
                    mod = plugin.url_for(getEPG, epgid=idx)
                    fold = True
                    ispla = False

                imag = j.get('icon_v2_url', None)
                art = {'icon': imag, 'fanart': helper.addon.getAddonInfo('fanart')}

                info = {'title': title, 'plot': epg}
                helper.add_item('[COLOR gold][B]' + title + '[/COLOR][/B]', mod, playable=ispla, info=info, art=art,
                                folder=fold)

    helper.eod()


@plugin.route('/empty')
def empty():
    return


@plugin.route('/settings')
def settings():
    helper.open_settings()
    helper.refresh()


@plugin.route('/logout')
def logout():
    log_out = helper.dialog_choice('Logout', 'Do you want to log out?', agree='Yes', disagree='No')
    if log_out:
        json_data = {"refresh_token": helper.get_setting('refresh_token')}
        helper.request_sess(helper.logout_url, 'post', headers=helper.headers, data=json_data, json=True,
                            json_data=True)
        helper.set_setting('bearer', '')
        helper.set_setting('logged', 'false')
        helper.refresh()


class QRPopup(xbmcgui.WindowDialog):
    exit_flag = False  # Class-level flag
    running = True

    def __init__(self, auth_code, qrcode_path=None):
        super(QRPopup, self).__init__()

        self.label = xbmcgui.ControlLabel(320, 100, 640, 40, "Enter code {} on the website,".format(auth_code),
                                          alignment=6)
        self.addControl(self.label)

        self.label2 = xbmcgui.ControlLabel(320, 140, 640, 40, "or scan the QR code with your phone!",
                                           alignment=6)
        self.addControl(self.label2)

        if qrcode_path is not None:
            self.qr_image = xbmcgui.ControlImage(490, 180, 300, 300, qrcode_path)
            self.addControl(self.qr_image)

        self.close_button = xbmcgui.ControlButton(540, 500, 200, 50, "Close", alignment=6)
        self.addControl(self.close_button)
        self.setFocus(self.close_button)

        self.monitor_thread = threading.Thread(target=self.monitor_exit_flag)
        self.monitor_thread.setDaemon(True)
        self.monitor_thread.start()

    def onControl(self, control):
        if control == self.close_button:
            QRPopup.running = False
            self.close()

    def monitor_exit_flag(self):
        while QRPopup.running:
            if QRPopup.exit_flag:
                QRPopup.running = False
                self.close()
            time.sleep(0.5)


def show_popup(auth_code, qrcode_path=None):
    QRPopup.exit_flag = False
    window = QRPopup(auth_code, qrcode_path)
    window.doModal()
    del window
    return None


@plugin.route('/login')
def login(ms_mode=None):
    # media-stick begin: the mode comes as the argument or as the phone's request (the phone asks for none: normal)
    if _ms:
        _ms.begin('sweettv')
        ms_mode = _ms.clean_mode(ms_mode or _ms.take_mode('sweettv'))
    # media-stick end
    jsdata = helper.request_sess(helper.auth_url, 'post', headers=helper.headers, data=helper.json_data, json=True,
                                 json_data=True)

    if jsdata is None:
        return

    auth_code = jsdata.get("auth_code")
    if jsdata.get("result") != 'OK' or not auth_code:
        helper.notification('Information', 'Login error')
        helper.set_setting('logged', 'false')
        # media-stick begin
        if _ms:
            _ms.publish('sweettv', 'failed')
        # media-stick end
        return

    # media-stick begin: the code and the link the QR holds, for the TV screen and the phone page
    ms_poll = None
    if _ms:
        _ms.publish('sweettv', 'waiting', code=auth_code, url='https://sweet.tv/addDevice', mode=ms_mode)   # six hours: the code is typed into a reseller's page, maybe much later
        ms_deadline = time.time() + _ms.ttl_for(ms_mode, 'sweettv')  # no popup to close: the code runs out on its own
        ms_poll = _ms.PartnerPoll(time.time())   # patient checks: gentle pace, a lost network is waited out, an expired code is told

    def ms_wait(seconds):
        # a long pause in short slices: the heartbeat goes on (a minute of silence reads as dead) and a stop request is seen
        end = time.time() + seconds
        while time.time() < end:
            if _ms:
                _ms.touch('sweettv')
                if _ms.cancel_requested('sweettv') or _ms.renew_requested('sweettv'):
                    return
            time.sleep(max(0, min(3, end - time.time())))

    def ms_renew():
        # the phone asks for a new code: SWEET.TV is asked for one inside this same run (the TV's screen follows the state, no
        # second launch of it), and the old code is dropped only once the new one is here; a failure leaves the old one waiting
        nonlocal auth_code, ms_deadline, ms_poll
        try:
            fresh = helper.request_sess(helper.auth_url, 'post', headers=helper.headers, data=helper.json_data, json=True,
                                        json_data=True)
        except Exception as e:
            xbmc.log('media-stick: SWEET.TV new code failed: ' + repr(e)[:200], xbmc.LOGWARNING)
            return False
        code = fresh.get('auth_code') if isinstance(fresh, dict) and fresh.get('result') == 'OK' else None
        if not code:
            ms_why = _ms.describe(fresh)
            xbmc.log('media-stick: SWEET.TV gave no new code: ' + ms_why, xbmc.LOGWARNING)
            return False
        auth_code = code
        ms_deadline = time.time() + _ms.ttl_for(ms_mode, 'sweettv')
        ms_poll = _ms.PartnerPoll(time.time())
        _ms.publish('sweettv', 'waiting', code=code, url='https://sweet.tv/addDevice', mode=ms_mode)
        return True
    # media-stick end

    # media-stick begin: on the device the TV screen draws the QR, so no image is requested (that would hand the code to a third party)
    resp = None if _ms else helper.request_sess("https://api.qrserver.com/v1/create-qr-code/",
                               params={"data": "sweet.tv/addDevice?connectCode={}".format(auth_code)}, result=False)

    path = None
    if resp is not None and resp.status_code == 200:
    # media-stick end
        try:
            path = xbmcvfs.translatePath('special://temp') + "{}.png".format(auth_code)
        except:
            path = xbmc.translatePath('special://temp') + "{}.png".format(auth_code)
        f = xbmcvfs.File(path, 'w')
        f.write(resp.content)
        f.close()

    def delayed_close():
        # wait for user to enter code
        jsdata = {"auth_code": auth_code}
        from json import dumps
        json_data = dumps(jsdata, separators=(',', ':'))
        result = None
        headers = helper.headers
        headers.update({'Content-Type': 'application/json'})

        while not result:
            # media-stick begin: heartbeat, and stop when the TV or the phone asks
            if _ms:
                _ms.touch('sweettv')
                if _ms.cancel_requested('sweettv'):
                    _ms.publish('sweettv', 'cancelled')
                    helper.set_setting('logged', 'false')
                    if path is not None:
                        xbmcvfs.delete(path)
                    return
                if _ms.take_renew('sweettv') and ms_renew():
                    json_data = dumps({'auth_code': auth_code}, separators=(',', ':'))
                if time.time() > ms_deadline:
                    _ms.publish('sweettv', 'failed', reason=_ms.EXPIRED)
                    helper.set_setting('logged', 'false')
                    if path is not None:
                        xbmcvfs.delete(path)
                    return
            # media-stick end
            if not QRPopup.running:
                helper.notification('Information', 'Login interrupted')
                helper.set_setting('logged', 'false')
                if path is not None:
                    xbmcvfs.delete(path)
                return
            # media-stick begin: patient: a check that raises (upstream's json() on a missing response, a page that is not JSON) or answers
            # with something that is not an object is "no answer" or an unknown answer, not the end of the sign-in
            try:
                jsdata = helper.request_sess(helper.check_auth_url, 'post', headers=headers, data=json_data, json=True,
                                             json_data=False)
                if ms_poll is not None and jsdata is not None and not isinstance(jsdata, dict):
                    jsdata = {'unexpected_reply': type(jsdata).__name__}
            except Exception as e:
                if ms_poll is None:
                    raise
                xbmc.log('media-stick: SWEET.TV check failed: ' + repr(e)[:200], xbmc.LOGWARNING)
                jsdata = None
            # media-stick end

            if jsdata is None:
                # media-stick begin: patient: no answer (the network is down) is waited out with growing pauses until the code runs out or, after half an hour of silence, is given up
                if ms_poll is not None:
                    ms_pause, ms_note = ms_poll.no_answer(time.time())
                    if ms_note:
                        xbmc.log(ms_note, xbmc.LOGWARNING)
                    if ms_poll.lost(time.time()):
                        _ms.publish('sweettv', 'failed', reason=_ms.EXPIRED)
                        helper.set_setting('logged', 'false')
                        if path is not None:
                            xbmcvfs.delete(path)
                        return
                    ms_wait(ms_pause)
                    continue
                if _ms:
                    _ms.publish('sweettv', 'failed')
                # media-stick end
                return

            xbmc.log("login " + str(jsdata), xbmc.LOGDEBUG)
            if jsdata.get("result") == "COMPLETED":
                result = jsdata
            else:
                # media-stick begin: patient: a refusal ends it, an answer nobody has described is logged and waited on, and after
                # ten minutes the checks come slower
                if ms_poll is not None:
                    ms_verdict, ms_note = ms_poll.answer(jsdata, time.time())
                    if ms_note:
                        xbmc.log(ms_note, xbmc.LOGWARNING)
                    if ms_verdict == 'refused':
                        _ms.publish('sweettv', 'failed', reason=_ms.EXPIRED)
                        helper.set_setting('logged', 'false')
                        if path is not None:
                            xbmcvfs.delete(path)
                        return
                    ms_wait(ms_poll.delay(time.time()))
                    continue
                # media-stick end
                time.sleep(3)

        if result.get("result") == 'COMPLETED':

            access_token = result.get("access_token")
            refresh_token = result.get("refresh_token")
            helper.set_setting('bearer', 'Bearer ' + str(access_token))
            helper.set_setting('refresh_token', str(refresh_token))
            helper.set_setting('logged', 'true')
            helper.set_setting('access_token_last_update', str(int(time.time())))

            access_token_lifetime = int(jsdata.get("expires_in"))
            helper.set_setting('access_token_lifetime', str(access_token_lifetime))

            # media-stick begin
            if _ms:
                _ms.publish('sweettv', 'done')
            # media-stick end
            refreshChannelList()
        else:

            info = jsdata.get('result', None)
            helper.notification('Information', info)
            # media-stick begin
            if _ms:
                _ms.publish('sweettv', 'failed')
            # media-stick end

            helper.set_setting('logged', 'false')

        QRPopup.exit_flag = True

    # media-stick begin: no popup on the device: wait right here, polling, until the code is entered or a stop is asked for
    if _ms:
        delayed_close()
        helper.refresh()
        return
    # media-stick end

    t = threading.Thread(target=delayed_close)
    t.setDaemon(True)
    t.start()

    show_popup(auth_code, path)

    if path is not None:
        xbmcvfs.delete(path)

    helper.refresh()


# media-stick begin: the played item is named after the channel (and the programme of an archive), and what its stream is is written down
try:
    if '/usr/local/lib/media-stick' not in sys.path:
        sys.path.insert(0, '/usr/local/lib/media-stick')
    import mediastick_sweetlive as _ms_live
except Exception:  # not a media-stick device: the add-on behaves as upstream
    _ms_live = None


def _ms_remember(cid, epg, url, offset):
    # Kodi tells the player the stream's address, not the plugin path: write down which channel and programme that address is
    # (the phone's 'now playing', the way back to live, the recorder of places read it), and where it was asked to start
    try:
        if _ms_live and not _ms_live.remember(cid, epg, url, offset):
            xbmc.log('media-stick: SWEET.TV stream not written down', xbmc.LOGWARNING)
    except Exception as e:
        xbmc.log('media-stick: SWEET.TV stream not written down: ' + repr(e)[:120], xbmc.LOGWARNING)


def _ms_start():
    # where to start an archived programme, seconds in: the add-on's own service and the phone ask for a place in the query
    try:
        from urllib.parse import parse_qs
        return max(0, min(int(parse_qs(sys.argv[2].lstrip('?')).get('ms_start', ['0'])[0]), 3 * 86400))
    except Exception:
        return 0


def _ms_names(cid, epg):
    """(channel name, programme text, start, stop) from the saved channel list; empty where unknown, never raises."""
    try:
        now = int(time.time())
        for channel in helper.get_channel_list().get('list') or []:
            if str(channel.get('id')) != str(cid):
                continue
            name = str(channel.get('name') or '')
            for p in channel.get('epg') or []:
                here = str(p.get('id')) == str(epg) if epg else p['time_start'] <= now < p['time_stop']
                if here:
                    return name, str(p.get('text') or ''), int(p['time_start']), int(p['time_stop'])
            return name, '', 0, 0
    except Exception as e:
        xbmc.log('media-stick: SWEET.TV channel name not read: ' + repr(e)[:120], xbmc.LOGWARNING)
    return '', '', 0, 0


def _ms_name_the_item(cid, epg, offset=0):
    """Wraps setResolvedUrl until the returned function is called: the item it resolves gets the channel name as its
    title (for an archived programme: the programme, with the channel as its show). Unknown channel: upstream's item."""
    name, text, begin, end = _ms_names(cid, epg)
    real = xbmcplugin.setResolvedUrl
    if not name:
        return lambda: None

    def resolved(handle, succeeded, listitem=None):
        try:
            if succeeded and listitem is not None:
                title = (text or name) if epg else name
                info = {'title': title, 'tvshowtitle': name}
                if text and not epg:
                    info['plot'] = text           # live: what is on now
                listitem.setLabel(title)
                listitem.setInfo('video', info)
                if epg and offset:
                    # Kodi ignores StartOffset of a resolved plugin item; a resume point is what it starts from (the service of
                    # this add-on looks that the player got there, and seeks if not: mediastick_sweetlive.follow)
                    listitem.setProperty('ResumeTime', str(offset))
                if epg and end > begin:
                    listitem.setProperty('TotalTime', str(end - begin))   # the bar is the programme (upstream says 1 s)
        except Exception as e:
            xbmc.log('media-stick: SWEET.TV item not named: ' + repr(e)[:120], xbmc.LOGWARNING)
        return real(handle, succeeded, listitem)

    xbmcplugin.setResolvedUrl = resolved
    return lambda: setattr(xbmcplugin, 'setResolvedUrl', real)


@plugin.route('/golive')
def ms_golive():
    # an archived programme is playing: its channel live (the remote's red key; the phone has a button of its own)
    path = xbmc.getInfoLabel('Player.Filenameandpath')
    prefix = 'plugin://plugin.video.sweettv/playvid/'
    cid, rest = '', ''
    if path.startswith(prefix):
        cid, _, rest = path[len(prefix):].partition('|')
    elif _ms_live:   # the label can give the stream's address: what the add-on wrote down says which programme it is
        try:
            found = _ms_live.identify(xbmc.Player().getPlayingFile(), time.time())
            cid, rest = (found[0], found[1]) if found else ('', '')
        except Exception:
            pass
    if cid.isdigit() and rest and not rest.startswith('null'):
        xbmc.executebuiltin('PlayMedia(%s%s|null)' % (prefix, cid))
# media-stick end


@plugin.route('/playvid/<videoid>')
def playvid(videoid):
    DRM = None
    lic_url = None
    PROTOCOL = 'mpd'
    subs = None

    if not helper.get_setting('logged'):
        xbmcgui.Dialog().notification('Sweet.tv', 'Log in to the plugin', xbmcgui.NOTIFICATION_INFO)
        xbmcplugin.setResolvedUrl(helper.handle, False, xbmcgui.ListItem())
    else:
        idx, pid = videoid.split('|')
        json_data = {
            'without_auth': True,
            'channel_id': int(idx),
            # 'accept_scheme': ['HTTP_HLS',],
            'multistream': True,
        }
        vod = False
        if pid != 'null':
            json_data.update({'epg_id': int(pid)})
            vod = True

        url = helper.base_api_url.format('TvService/OpenStream.json')
        jsdata = helper.request_sess(url, 'post', headers=helper.headers, data=json_data, json=True, json_data=True)

        if jsdata is None:
            return

        if jsdata.get("code", None) == 13:
            xbmcgui.Dialog().notification('Sweet.tv', 'Recording unavailable', xbmcgui.NOTIFICATION_INFO)
            xbmcplugin.setResolvedUrl(helper.handle, False, xbmcgui.ListItem())
        if jsdata.get("result", None) == 'OK':
            host = jsdata.get('http_stream', None).get('host', None).get('address', None)
            nt = jsdata.get('http_stream', None).get('url', None)
            stream_url = 'https://' + host + nt
            if jsdata.get('scheme', None) == 'HTTP_DASH':
                if jsdata.get('drm_type', None) == 'DRM_WIDEVINE':
                    licURL = jsdata.get('license_server', None)
                    hea_lic = {
                        'User-Agent': helper.UA,
                        'origin': 'https://sweet.tv',
                        'referer': 'https://sweet.tv/'
                    }
                    lic_url = '%s|%s|R{SSM}|' % (licURL, urlencode(hea_lic))
                    DRM = 'com.widevine.alpha'
                else:
                    lic_url = None
                    DRM = None
                PROTOCOL = 'mpd'
                subs = None

            elif jsdata.get('scheme', None) == 'HTTP_HLS':
                lic_url = None
                mpdurl = ''
                DRM = None
                PROTOCOL = 'hls'
                subs = None

            # media-stick begin
            ms_undo = _ms_name_the_item(idx, pid if pid != 'null' else None, _ms_start())
            _ms_remember(idx, pid if pid != 'null' else None, stream_url, _ms_start())
            # media-stick end
            if helper.get_setting('playerType') == 'ffmpeg' and DRM is None:
                helper.ffmpeg_player(stream_url)
            else:
                helper.playstream(stream_url, lic_url, PROTOCOL, DRM, flags=False, subs=subs, vod=vod)
            # media-stick begin
            ms_undo()
            # media-stick end


@plugin.route('/listM3U')
def listM3U():
    if helper.get_setting('logged'):
        file_name = helper.get_setting('name_m3u')
        path_m3u = helper.get_setting('path_m3u')
        if file_name == '' or path_m3u == '':
            xbmcgui.Dialog().notification('Sweet.tv', 'Specify the file name and destination directory.',
                                          xbmcgui.NOTIFICATION_ERROR)
            return
        xbmcgui.Dialog().notification('Sweet tv', 'Generating M3U list.', xbmcgui.NOTIFICATION_INFO)
        channels = helper.get_channel_list()
        if channels.get("status", None) == 'OK':
            xbmcgui.Dialog().notification('Sweet.tv', 'M3U list generated.', xbmcgui.NOTIFICATION_INFO)
    else:
        xbmcgui.Dialog().notification('Sweet.tv', 'Log in to the plugin.', xbmcgui.NOTIFICATION_INFO)


class SweetTV(Helper):
    def __init__(self):
        super(SweetTV, self).__init__()
        plugin.run()
