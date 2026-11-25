#!/usr/bin/env python3
"""Rebuild the add-on overlays in device/skin-overlay from the pinned zips.

  python3 tools/make-skin-overlays.py            write the overlay files
  python3 tools/make-skin-overlays.py --check    rebuild in memory, exit 1 if a committed overlay differs

An overlay is a whole upstream file with a few fenced edits (media-stick begin/end). Each add-on
is downloaded from the url in device/kodi-addons.list, checked against the sha256 on its line, and
only the one file is taken out. That file must be the one the existing overlay was made from (the
`upstream sha256` in its header); if upstream changed it, this stops: look at what changed, then
rerun with --accept-new-upstream. Every edit is anchored on an exact upstream snippet that must
occur exactly once.
"""
import hashlib
import io
import os
import re
import sys
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "device", "kodi-addons.list")
OVERLAY = os.path.join(ROOT, "device", "skin-overlay")
HEADER = re.compile(r"# media-stick overlay of (\S+) \(([^,]+), upstream sha256 ([0-9a-f]{64})\)")


class Stop(Exception):
    pass


IMPORT = """# media-stick begin: publish the sign-in code for the TV screen and the phone page
try:
    import sys as _ms_sys
    _ms_sys.path.insert(0, '/usr/local/lib/media-stick')
    import mediastick_signin as _ms
except Exception:  # not a media-stick device: the add-on behaves as upstream
    _ms = None
# media-stick end
"""

# YouTube: on the device the TV screen shows the code, so the add-on opens no dialog of its own;
# this stands in for the progress dialog and the loop polls as before
NO_DIALOG = """# media-stick begin: stands in for the progress dialog (the TV screen shows the code, the add-on shows nothing)
class _MsNoDialog(object):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_total(self, total):
        pass

    def update(self, *args, **kwargs):
        pass

    def is_aborted(self):
        return False
# media-stick end
"""

# (add-on id, file inside the add-on, [(anchor, replacement), ...])
OVERLAYS = [
    # YouTube: the codes, cancelling, and picking a profile without the dialog
    ("plugin.video.youtube", "resources/lib/youtube_plugin/youtube/helper/yt_login.py", [
        ("from ...kodion import logging\n",
         "from ...kodion import logging\n\n" + IMPORT + "\n" + NO_DIALOG),
        ("    new_access_tokens = dict.fromkeys(token_types, None)\n",
         "    new_access_tokens = dict.fromkeys(token_types, None)\n"
         "    # media-stick begin: how many approvals this sign-in will ask for: the token slots that still lack a token\n"
         "    ms_round, ms_rounds = 0, 0\n"
         "    if _ms:\n"
         "        for ms_idx in range(len(token_types)):\n"
         "            try:\n"
         "                if access_tokens[ms_idx] and refresh_tokens[ms_idx]:\n"
         "                    continue\n"
         "            except IndexError:\n"
         "                pass\n"
         "            ms_rounds += 1\n"
         "    # media-stick end\n"),
        ("            json_data = client.request_device_and_user_code(token_idx)\n            if not json_data:\n                continue\n",
         "            json_data = client.request_device_and_user_code(token_idx)\n"
         "            if not json_data:\n"
         "                # media-stick begin: Google gave no code for this slot: one approval fewer\n"
         "                ms_rounds -= 1\n"
         "                # media-stick end\n"
         "                continue\n"),
        ("    ui.on_ok(localize('sign.multi.title'), localize('sign.multi.text'))\n",
         "    # media-stick begin: the TV screen and the phone page explain the several codes\n"
         "    if _ms is None:\n"
         "        ui.on_ok(localize('sign.multi.title'), localize('sign.multi.text'))\n"
         "    else:\n"
         "        _ms.begin('youtube')\n"
         "    # media-stick end\n"),
        ("            else:\n                verification_url = 'youtube.com/activate'\n\n",
         "            else:\n                verification_url = 'youtube.com/activate'\n\n"
         "            # media-stick begin\n"
         "            if _ms:\n"
         "                ms_round += 1\n"
         "                _ms.publish('youtube', 'waiting', code=user_code,\n"
         "                            url=('' if verification_url.startswith('http') else 'https://www.') + verification_url,\n"
         "                            link=json_data.get('verification_url_complete') or '',\n"
         "                            step=token_idx + 1, steps=len(token_types), ttl=10 * 60,\n"
         "                            round=ms_round, rounds=max(ms_rounds, ms_round))\n"
         "            # media-stick end\n\n"),
        ("            with ui.create_progress_dialog(\n"
         "                    heading=localize('sign.in'),\n"
         "                    message=message,\n"
         "                    background=False\n"
         "            ) as progress_dialog:\n",
         "            # media-stick begin: the TV screen shows the code, so no dialog of the add-on's own: poll without one\n"
         "            dialog = _MsNoDialog() if _ms else ui.create_progress_dialog(\n"
         "                heading=localize('sign.in'),\n"
         "                message=message,\n"
         "                background=False\n"
         "            )\n"
         "            with dialog as progress_dialog:\n"
         "            # media-stick end\n"),
        ("                    progress_dialog.update()\n                    json_data = client.request_access_token(",
         "                    progress_dialog.update()\n"
         "                    # media-stick begin: heartbeat, and stop when the TV or the phone asks\n"
         "                    if _ms:\n"
         "                        _ms.touch('youtube')\n"
         "                        if _ms.cancel_requested('youtube'):\n"
         "                            break\n"
         "                    # media-stick end\n"
         "                    json_data = client.request_access_token("),
        ("                    context.sleep(interval)\n        except LoginException:",
         "                    context.sleep(interval)\n"
         "            # media-stick begin: a stop request ends the whole sign-in, not just this code\n"
         "            if _ms and _ms.cancel_requested('youtube'):\n"
         "                break\n"
         "            # media-stick end\n"
         "        except LoginException:"),
        ("        access_manager.update_access_token(addon_id, *zip(*token_types))\n        return True\n    return False",
         "        access_manager.update_access_token(addon_id, *zip(*token_types))\n"
         "        # media-stick begin\n"
         "        if _ms:  # upstream also ends here when a code was refused or ran out: say done only if a token came\n"
         "            _ms.publish('youtube', 'done' if any(isinstance(t, tuple) and t[2] for t in token_types) else 'failed')\n"
         "        # media-stick end\n"
         "        return True\n"
         "    # media-stick begin\n"
         "    if _ms:\n"
         "        _ms.publish('youtube', 'cancelled' if _ms.cancel_requested('youtube') else 'failed')\n"
         "    # media-stick end\n"
         "    return False"),
    ]),
    ("plugin.video.youtube", "resources/lib/youtube_plugin/kodion/script_actions.py", [
        ("def _user_actions(context, action, params):\n    if params:\n",
         "def _user_actions(context, action, params):\n"
         "    # media-stick begin: parse_params drops parameters the add-on does not know, ours included\n"
         "    ms = {key: (params or {}).get(key) for key in ('ms_name', 'ms_switch', 'ms_user')}\n"
         "    # media-stick end\n"
         "    if params:\n"),
        ("    def add_user():\n        results = ui.on_keyboard_input(localize('user.enter_name'))\n",
         "    def add_user():\n"
         "        # media-stick begin: a name from the TV or the phone page skips the keyboard\n"
         "        ms_name = ms['ms_name']\n"
         "        if ms_name:\n"
         "            results = (True, ms_name)\n"
         "        else:\n"
         "            results = ui.on_keyboard_input(localize('user.enter_name'))\n"
         "        # media-stick end\n"),
        ("    if action == 'switch':\n        result, user_index_map = select_user(localize('user.switch'),",
         "    # media-stick begin: users/switch?ms_user=<id> picks the profile without the dialog\n"
         "    ms_user = ms['ms_user'] if action == 'switch' else None\n"
         "    if ms_user not in (None, ''):\n"
         "        user = next((key for key in access_manager.get_users() if str(key) == str(ms_user)), None)\n"
         "        if user is None:\n"
         "            return False\n"
         "        if user != access_manager.get_current_user():\n"
         "            switch_to_user(user)\n"
         "            reload = True\n"
         "    # media-stick end\n"
         "    elif action == 'switch':\n        result, user_index_map = select_user(localize('user.switch'),"),
        ("            result = ui.on_yes_no_input(\n                localize('user.switch'),\n                localize('user.switch_to.x', details.get('name'))\n            )",
         "            # media-stick begin: users/add?ms_switch=1 switches without asking\n"
         "            result = True if ms['ms_switch'] else ui.on_yes_no_input(\n"
         "                localize('user.switch'),\n"
         "                localize('user.switch_to.x', details.get('name'))\n"
         "            )\n"
         "            # media-stick end"),
    ]),
    # SWEET.TV: the code, cancelling
    ("plugin.video.sweettv", "resources/lib/sweettv.py", [
        ("from six.moves.urllib.parse import urlencode\n",
         "from six.moves.urllib.parse import urlencode\n\n" + IMPORT),
        # the token the sign-in just stored must be the one the channel list request carries, and a failed fetch says why
        ("def refreshChannelList():\n    if not helper.get_setting('logged'):\n        return\n",
         "# media-stick begin: the sign-in token is read when it is needed. `helper` is built when this module is imported: in the sign-in\n"
         "# (which stays in this process for hours) and in the add-on's service (which lives from Kodi's start) that is before the new\n"
         "# bearer is stored, and a helper built without one sends no authorization: the channel list never loads\n"
         "def _ms_sync_auth():\n"
         "    bearer = helper.get_setting('bearer')\n"
         "    helper.bearer = bearer\n"
         "    if bearer:\n"
         "        helper.headers.update({'authorization': bearer})\n"
         "    else:\n"
         "        helper.headers.pop('authorization', None)\n"
         "\n\n"
         "def _ms_status(reply):\n"
         "    # the answer's own status field and nothing else: never the body, never a token\n"
         "    status = reply.get('status') if isinstance(reply, dict) else None\n"
         "    return repr(status)[:40] if isinstance(status, (str, int)) else type(status).__name__\n"
         "# media-stick end\n\n\n"
         "def refreshChannelList():\n    if not helper.get_setting('logged'):\n        return\n"
         "    # media-stick begin\n"
         "    _ms_sync_auth()\n"
         "    _ms_sync_language()   # the language may have been chosen since this process started\n"
         "    # media-stick end\n"),
        ("    if jsdata is None:\n        return\n\n    jsdata_content = jsdata.content\n",
         "    if jsdata is None:\n"
         "        # media-stick begin\n"
         "        xbmc.log('media-stick: SWEET.TV channel list not updated: no answer (authorization sent: %s)'\n"
         "                 % ('authorization' in helper.headers), xbmc.LOGWARNING)\n"
         "        # media-stick end\n"
         "        return\n\n    jsdata_content = jsdata.content\n"),
        ('        xbmc.log("Failed to update channel list", xbmc.LOGERROR)\n',
         '        xbmc.log("Failed to update channel list", xbmc.LOGERROR)\n'
         "        # media-stick begin: the cause without DEBUG logging: the status the API answered with (never the body, never a token)\n"
         "        xbmc.log('media-stick: SWEET.TV channel list not updated: status=%s (authorization sent: %s)'\n"
         "                 % (_ms_status(jsdata), 'authorization' in helper.headers), xbmc.LOGWARNING)\n"
         "        # media-stick end\n"),
        # the add-on's language: Russian unless the person chose one (upstream's default is Hungarian, and it names the
        # categories and the programmes)
        ("helper = Helper(base_url, handle)\nplugin = routing.Plugin()\n",
         "helper = Helper(base_url, handle)\n"
         "plugin = routing.Plugin()\n\n"
         "# media-stick begin: the language of the categories and programme titles (the accept-language header). The box has one\n"
         "# language, the phone's «Язык» (mediastick_lang); once it was chosen SWEET.TV is asked in it, and a long-lived process\n"
         "# (the service) reads it again before every request. Without a choice: the add-on's own setting, but upstream's untouched\n"
         "# default (Hungarian) is Russian\n"
         "MS_LANGUAGE = 'ru'\n\n\n"
         "def _ms_language_untouched():\n"
         "    # upstream's default is 'hu'. Kodi writes a setting nobody has changed as default=\"true\" (or not at all): that one\n"
         "    # is ours to replace; a 'hu' the person chose is kept\n"
         "    try:\n"
         "        translate = getattr(xbmcvfs, 'translatePath', None) or xbmc.translatePath\n"
         "        with open(translate('special://profile/addon_data/%s/settings.xml' % helper.addon_name), encoding='utf-8') as f:\n"
         "            text = f.read()\n"
         "    except FileNotFoundError:\n"
         "        return True\n"
         "    except Exception:\n"
         "        return False\n"
         "    import re as _ms_re\n"
         "    found = _ms_re.search(r'<setting id=\"countryCode\"([^>]*)>', text)\n"
         "    return found is None or 'default=\"true\"' in found.group(1)\n\n\n"
         "def _ms_language():\n"
         "    try:\n"
         "        import mediastick_lang as _ms_lang\n"
         "        from os.path import exists as _ms_exists\n"
         "        if _ms_exists(_ms_lang.path()):\n"
         "            return _ms_lang.resolve(_ms_lang.read()).sweet   # the box's language, chosen by the owner\n"
         "    except Exception:  # not a media-stick device, or the file cannot be read: the add-on's own setting decides\n"
         "        pass\n"
         "    stored = helper.get_setting('countryCode') or helper.countryCode\n"
         "    return MS_LANGUAGE if stored == 'hu' and _ms_language_untouched() else stored\n\n\n"
         "def _ms_sync_language():\n"
         "    code = _ms_language()\n"
         "    if code and code != helper.countryCode:\n"
         "        helper.countryCode = code\n"
         "    if code:\n"
         "        helper.headers['accept-language'] = code\n\n\n"
         "_ms_sync_language()\n"
         "# media-stick end\n"),
        # the name of the channel (and of the programme) on the item that is played: Kodi shows its title and label
        # (the phone's bar and sheet, the TV's player menu); upstream hands over an item with neither
        ("@plugin.route('/playvid/<videoid>')\ndef playvid(videoid):\n",
         "# media-stick begin: the played item is named after the channel (and the programme of an archive), and what its stream is is written down\n"
         "try:\n"
         "    if '/usr/local/lib/media-stick' not in sys.path:\n"
         "        sys.path.insert(0, '/usr/local/lib/media-stick')\n"
         "    import mediastick_sweetlive as _ms_live\n"
         "except Exception:  # not a media-stick device: the add-on behaves as upstream\n"
         "    _ms_live = None\n\n\n"
         "def _ms_remember(cid, epg, url, offset):\n"
         "    # Kodi tells the player the stream's address, not the plugin path: write down which channel and programme that address is\n"
         "    # (the phone's 'now playing', the way back to live, the recorder of places read it), and where it was asked to start\n"
         "    try:\n"
         "        if _ms_live and not _ms_live.remember(cid, epg, url, offset):\n"
         "            xbmc.log('media-stick: SWEET.TV stream not written down', xbmc.LOGWARNING)\n"
         "    except Exception as e:\n"
         "        xbmc.log('media-stick: SWEET.TV stream not written down: ' + repr(e)[:120], xbmc.LOGWARNING)\n\n\n"
         "def _ms_ids(videoid):\n"
         "    # '<channel>|<programme id or null>': a query or protocol options that Kodi left behind it are not part of the id\n"
         "    found = _ms_live.split_id(videoid) if _ms_live else None\n"
         "    return found if found else tuple(videoid.split('|'))\n\n\n"
         "def _ms_start(cid, epg, videoid):\n"
         "    # where to start an archived programme, seconds in. Kodi may not hand the query over (the '|' of the path makes it read\n"
         "    # what follows as protocol options), so every place it may be in is looked at, then what the opener wrote down\n"
         "    # (mediastick_sweetlive.start_of); the one line in the log says where it came from\n"
         "    if not _ms_live or not epg:\n"
         "        return 0\n"
         "    try:\n"
         "        offset, source = _ms_live.start_of(sys.argv, videoid, cid, epg, now=time.time())\n"
         "    except Exception as e:\n"
         "        xbmc.log('media-stick: SWEET.TV start place not read: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "        return 0\n"
         "    try:\n"
         "        xbmc.log('media-stick: SWEET.TV archive %s|%s asked to start at %ss (%s)' % (cid, epg, offset, source), xbmc.LOGINFO)\n"
         "    except Exception:\n"
         "        pass\n"
         "    return offset\n\n\n"
         "def _ms_quality():\n"
         "    try:\n"
         "        import mediastick_resume as _ms_res\n"
         "        return _ms_res.read_quality()\n"
         "    except Exception:\n"
         "        return '1080p'\n\n\n"
         "def _ms_apply_quality_cap(listitem, quality):\n"
         "    if listitem is not None and helper.get_setting('playerType') != 'ffmpeg' and quality in ('720p', '1080p'):\n"
         "        listitem.setProperty('inputstream.adaptive.max_resolution', quality)\n\n\n"
         "def _ms_names(cid, epg):\n"
         "    \"\"\"(channel name, programme text, start, stop) from the saved channel list (falling back to sweetapi.recall).\"\"\"\n"
         "    name = ''\n"
         "    try:\n"
         "        now = int(time.time())\n"
         "        for channel in helper.get_channel_list().get('list') or []:\n"
         "            if str(channel.get('id')) != str(cid):\n"
         "                continue\n"
         "            name = str(channel.get('name') or '')\n"
         "            for p in channel.get('epg') or []:\n"
         "                here = str(p.get('id')) == str(epg) if epg else p['time_start'] <= now < p['time_stop']\n"
         "                if here:\n"
         "                    return name, str(p.get('text') or ''), int(p['time_start']), int(p['time_stop'])\n"
         "            break\n"
         "    except Exception as e:\n"
         "        xbmc.log('media-stick: SWEET.TV channel name not read: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "    if epg:\n"
         "        try:\n"
         "            import mediastick_sweetapi as _ms_api\n"
         "            rec = _ms_api.recall(cid, epg)\n"
         "            if rec:\n"
         "                return name, '', int(rec['start']), int(rec['stop'])\n"
         "        except Exception:\n"
         "            pass\n"
         "    return name, '', 0, 0\n\n\n"
         "def _ms_use_ffmpeg(cid, epg, protocol, drm):\n"
         "    \"\"\"Use Kodi's native ffmpeg demuxer for finished non-DRM HLS archives (avoids ISA+DRMPRIME seek stalls).\"\"\"\n"
         "    if drm is not None:\n"
         "        return False\n"
         "    if helper.get_setting('playerType') == 'ffmpeg':\n"
         "        return True\n"
         "    if protocol != 'hls' or not epg:\n"
         "        return False\n"
         "    _, _, begin, end = _ms_names(cid, epg)\n"
         "    return (not end) or end <= int(time.time())\n\n\n"
         "def _ms_name_the_item(cid, epg, offset=0):\n"
         "    \"\"\"Wraps setResolvedUrl until the returned function is called: names the item, sets ResumeTime/TotalTime/DVR,\n"
         "    and applies the device's inputstream.adaptive max_resolution cap.\"\"\"\n"
         "    name, text, begin, end = _ms_names(cid, epg)\n"
         "    quality = _ms_quality()\n"
         "    real = xbmcplugin.setResolvedUrl\n"
         "\n"
         "    def resolved(handle, succeeded, listitem=None):\n"
         "        try:\n"
         "            if succeeded and listitem is not None:\n"
         "                if name:\n"
         "                    title = (text or name) if epg else name\n"
         "                    info = {'title': title, 'tvshowtitle': name}\n"
         "                    if text and not epg:\n"
         "                        info['plot'] = text           # live: what is on now\n"
         "                    listitem.setLabel(title)\n"
         "                    listitem.setInfo('video', info)\n"
         "                now = int(time.time())\n"
         "                use_is = helper.get_setting('playerType') != 'ffmpeg'\n"
         "                in_progress = bool(use_is and epg and begin and end and begin <= now < end)\n"
         "                if epg and offset:\n"
         "                    listitem.setProperty('ResumeTime', str(offset))\n"
         "                if in_progress:\n"
         "                    listitem.setProperty('inputstream.adaptive.manifest_update_parameter', 'full')\n"
         "                elif epg and end > begin:\n"
         "                    listitem.setProperty('TotalTime', str(end - begin))   # the bar is the programme (upstream says 1 s)\n"
         "                _ms_apply_quality_cap(listitem, quality)\n"
         "        except Exception as e:\n"
         "            xbmc.log('media-stick: SWEET.TV item not named: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "        return real(handle, succeeded, listitem)\n"
         "\n"
         "    xbmcplugin.setResolvedUrl = resolved\n"
         "    return lambda: setattr(xbmcplugin, 'setResolvedUrl', real)\n\n\n"
         "@plugin.route('/playvod/<videoid>')\n"
         "def playvod(videoid):\n"
         "    if not helper.get_setting('logged'):\n"
         "        return\n"
         "    _ms_sync_auth()\n"
         "    _ms_sync_language()\n"
         "    parts = _ms_live.split_vod_id(videoid) if _ms_live else None\n"
         "    if not parts:\n"
         "        return\n"
         "    movie_id, ep_raw, owner_raw = parts\n"
         "    episode_id = None if ep_raw == 'null' else int(ep_raw)\n"
         "    owner_id = int(owner_raw)\n"
         "    quality = _ms_quality()\n"
         "    try:\n"
         "        import mediastick_sweetapi as _ms_api\n"
         "        res = _ms_api.vod_link(int(movie_id), episode_id=episode_id, owner_id=owner_id, quality=quality)\n"
         "    except Exception as e:\n"
         "        xbmc.log('media-stick: SWEET.TV vod_link failed: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "        return\n"
         "    if not isinstance(res, dict) or not res.get('ok'):\n"
         "        xbmc.log('media-stick: SWEET.TV vod_link refused', xbmc.LOGWARNING)\n"
         "        return\n"
         "    ep_str = '' if episode_id is None else str(episode_id)\n"
         "    offset = _ms_start('vod:' + movie_id, ep_str, videoid) if ep_str else (\n"
         "        _ms_live.start_of(sys.argv, videoid, 'vod:' + movie_id, '', now=time.time())[0] if _ms_live else 0)\n"
         "    _ms_remember('vod:' + movie_id, ep_str, res['url'], offset)\n"
         "    real = xbmcplugin.setResolvedUrl\n"
         "\n"
         "    def resolved(handle, succeeded, listitem=None):\n"
         "        try:\n"
         "            if succeeded and listitem is not None:\n"
         "                title = res.get('title') or ''\n"
         "                if title:\n"
         "                    listitem.setLabel(title)\n"
         "                    listitem.setInfo('video', {'title': title})\n"
         "                if offset:\n"
         "                    listitem.setProperty('ResumeTime', str(offset))\n"
         "                if res.get('duration'):\n"
         "                    listitem.setProperty('TotalTime', str(res['duration']))\n"
         "                _ms_apply_quality_cap(listitem, quality)\n"
         "        except Exception as e:\n"
         "            xbmc.log('media-stick: SWEET.TV vod item not named: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "        return real(handle, succeeded, listitem)\n"
         "\n"
         "    xbmcplugin.setResolvedUrl = resolved\n"
         "    try:\n"
         "        drm = 'com.widevine.alpha' if res.get('license_url') else None\n"
         "        helper.playstream(res['url'], res.get('license_url') or '', res.get('protocol') or 'hls', drm, flags=False, vod=True)\n"
         "    finally:\n"
         "        xbmcplugin.setResolvedUrl = real\n\n\n"
         "@plugin.route('/golive')\n"
         "def ms_golive():\n"
         "    # an archived programme is playing: its channel live (the remote's red key; the phone has a button of its own)\n"
         "    path = xbmc.getInfoLabel('Player.Filenameandpath')\n"
         "    prefix = 'plugin://plugin.video.sweettv/playvid/'\n"
         "    cid, rest = '', ''\n"
         "    if path.startswith(prefix):\n"
         "        cid, _, rest = path[len(prefix):].partition('|')\n"
         "    elif _ms_live:   # the label can give the stream's address: what the add-on wrote down says which programme it is\n"
         "        try:\n"
         "            found = _ms_live.identify(xbmc.Player().getPlayingFile(), time.time())\n"
         "            cid, rest = (found[0], found[1]) if found else ('', '')\n"
         "        except Exception:\n"
         "            pass\n"
         "    if cid.isdigit() and rest and not rest.startswith('null'):\n"
         "        xbmc.executebuiltin('PlayMedia(%s%s|null)' % (prefix, cid))\n"
         "# media-stick end\n\n\n"
         "@plugin.route('/playvid/<videoid>')\ndef playvid(videoid):\n"),
        ("        idx, pid = videoid.split('|')\n",
         "        idx, pid = _ms_ids(videoid)   # media-stick: a query that Kodi left in the id is not the programme\n"),
        ("            if helper.get_setting('playerType') == 'ffmpeg' and DRM is None:\n",
         "            # media-stick begin\n"
         "            ms_epg = pid if pid != 'null' else None\n"
         "            ms_offset = _ms_start(idx, ms_epg, videoid)\n"
         "            ms_undo = _ms_name_the_item(idx, ms_epg, ms_offset)\n"
         "            _ms_remember(idx, ms_epg, stream_url, ms_offset)\n"
         "            # media-stick end\n"
         "            if _ms_use_ffmpeg(idx, ms_epg, PROTOCOL, DRM):\n"),
        ("                helper.playstream(stream_url, lic_url, PROTOCOL, DRM, flags=False, subs=subs, vod=vod)\n",
         "                helper.playstream(stream_url, lic_url, PROTOCOL, DRM, flags=False, subs=subs, vod=vod)\n"
         "            # media-stick begin\n"
         "            ms_undo()\n"
         "            # media-stick end\n"),
        ("def login():\n    jsdata = helper.request_sess(helper.auth_url,",
         "def login(ms_mode=None):\n"
         "    # media-stick begin: the mode comes as the argument or as the phone's request (the phone asks for none: normal)\n"
         "    if _ms:\n"
         "        _ms.begin('sweettv')\n"
         "        ms_mode = _ms.clean_mode(ms_mode or _ms.take_mode('sweettv'))\n"
         "    # media-stick end\n"
         "    jsdata = helper.request_sess(helper.auth_url,"),
        ("        helper.notification('Information', 'Login error')\n        helper.set_setting('logged', 'false')\n        return\n",
         "        helper.notification('Information', 'Login error')\n        helper.set_setting('logged', 'false')\n"
         "        # media-stick begin\n"
         "        if _ms:\n"
         "            _ms.publish('sweettv', 'failed')\n"
         "        # media-stick end\n"
         "        return\n\n"
         "    # media-stick begin: the code and the link the QR holds, for the TV screen and the phone page\n"
         "    ms_poll = None\n"
         "    if _ms:\n"
         "        _ms.publish('sweettv', 'waiting', code=auth_code, url='https://sweet.tv/addDevice', mode=ms_mode)   # six hours: the code is typed into a reseller's page, maybe much later\n"
         "        ms_deadline = time.time() + _ms.ttl_for(ms_mode, 'sweettv')  # no popup to close: the code runs out on its own\n"
         "        ms_poll = _ms.PartnerPoll(time.time())   # patient checks: gentle pace, a lost network is waited out, an expired code is told\n"
         "\n"
         "    def ms_wait(seconds):\n"
         "        # a long pause in short slices: the heartbeat goes on (a minute of silence reads as dead) and a stop request is seen\n"
         "        end = time.time() + seconds\n"
         "        while time.time() < end:\n"
         "            if _ms:\n"
         "                _ms.touch('sweettv')\n"
         "                if _ms.cancel_requested('sweettv') or _ms.renew_requested('sweettv'):\n"
         "                    return\n"
         "            time.sleep(max(0, min(3, end - time.time())))\n"
         "\n"
         "    def ms_renew():\n"
         "        # the phone asks for a new code: SWEET.TV is asked for one inside this same run (the TV's screen follows the state, no\n"
         "        # second launch of it), and the old code is dropped only once the new one is here; a failure leaves the old one waiting\n"
         "        nonlocal auth_code, ms_deadline, ms_poll\n"
         "        try:\n"
         "            fresh = helper.request_sess(helper.auth_url, 'post', headers=helper.headers, data=helper.json_data, json=True,\n"
         "                                        json_data=True)\n"
         "        except Exception as e:\n"
         "            xbmc.log('media-stick: SWEET.TV new code failed: ' + repr(e)[:200], xbmc.LOGWARNING)\n"
         "            return False\n"
         "        code = fresh.get('auth_code') if isinstance(fresh, dict) and fresh.get('result') == 'OK' else None\n"
         "        if not code:\n"
         "            ms_why = _ms.describe(fresh)\n"
         "            xbmc.log('media-stick: SWEET.TV gave no new code: ' + ms_why, xbmc.LOGWARNING)\n"
         "            return False\n"
         "        auth_code = code\n"
         "        ms_deadline = time.time() + _ms.ttl_for(ms_mode, 'sweettv')\n"
         "        ms_poll = _ms.PartnerPoll(time.time())\n"
         "        _ms.publish('sweettv', 'waiting', code=code, url='https://sweet.tv/addDevice', mode=ms_mode)\n"
         "        return True\n"
         "    # media-stick end\n"),
        ("    resp = helper.request_sess(\"https://api.qrserver.com/v1/create-qr-code/\",\n"
         "                               params={\"data\": \"sweet.tv/addDevice?connectCode={}\".format(auth_code)}, result=False)\n"
         "\n    path = None\n    if resp.status_code == 200:\n",
         "    # media-stick begin: on the device the TV screen draws the QR, so no image is requested (that would hand the code to a third party)\n"
         "    resp = None if _ms else helper.request_sess(\"https://api.qrserver.com/v1/create-qr-code/\",\n"
         "                               params={\"data\": \"sweet.tv/addDevice?connectCode={}\".format(auth_code)}, result=False)\n"
         "\n    path = None\n    if resp is not None and resp.status_code == 200:\n"
         "    # media-stick end\n"),
        ("    t = threading.Thread(target=delayed_close)\n",
         "    # media-stick begin: no popup on the device: wait right here, polling, until the code is entered or a stop is asked for\n"
         "    if _ms:\n"
         "        delayed_close()\n"
         "        helper.refresh()\n"
         "        return\n"
         "    # media-stick end\n\n"
         "    t = threading.Thread(target=delayed_close)\n"),
        ("        while not result:\n            if not QRPopup.running:\n                helper.notification('Information', 'Login interrupted')\n                helper.set_setting('logged', 'false')\n",
         "        while not result:\n"
         "            # media-stick begin: heartbeat, and stop when the TV or the phone asks\n"
         "            if _ms:\n"
         "                _ms.touch('sweettv')\n"
         "                if _ms.cancel_requested('sweettv'):\n"
         "                    _ms.publish('sweettv', 'cancelled')\n"
         "                    helper.set_setting('logged', 'false')\n"
         "                    if path is not None:\n"
         "                        xbmcvfs.delete(path)\n"
         "                    return\n"
         "                if _ms.take_renew('sweettv') and ms_renew():\n"
         "                    json_data = dumps({'auth_code': auth_code}, separators=(',', ':'))\n"
         "                if time.time() > ms_deadline:\n"
         "                    _ms.publish('sweettv', 'failed', reason=_ms.EXPIRED)\n"
         "                    helper.set_setting('logged', 'false')\n"
         "                    if path is not None:\n"
         "                        xbmcvfs.delete(path)\n"
         "                    return\n"
         "            # media-stick end\n"
         "            if not QRPopup.running:\n"
         "                helper.notification('Information', 'Login interrupted')\n"
         "                helper.set_setting('logged', 'false')\n"),
        ("            jsdata = helper.request_sess(helper.check_auth_url, 'post', headers=headers, data=json_data, json=True,\n"
         "                                         json_data=False)\n",
         "            # media-stick begin: patient: a check that raises (upstream's json() on a missing response, a page that is not JSON) or answers\n"
         "            # with something that is not an object is \"no answer\" or an unknown answer, not the end of the sign-in\n"
         "            try:\n"
         "                jsdata = helper.request_sess(helper.check_auth_url, 'post', headers=headers, data=json_data, json=True,\n"
         "                                             json_data=False)\n"
         "                if ms_poll is not None and jsdata is not None and not isinstance(jsdata, dict):\n"
         "                    jsdata = {'unexpected_reply': type(jsdata).__name__}\n"
         "            except Exception as e:\n"
         "                if ms_poll is None:\n"
         "                    raise\n"
         "                xbmc.log('media-stick: SWEET.TV check failed: ' + repr(e)[:200], xbmc.LOGWARNING)\n"
         "                jsdata = None\n"
         "            # media-stick end\n"),
        ("            if jsdata is None:\n                return\n\n            xbmc.log(\"login \"",
         "            if jsdata is None:\n"
         "                # media-stick begin: patient: no answer (the network is down) is waited out with growing pauses until the code runs out or, after half an hour of silence, is given up\n"
         "                if ms_poll is not None:\n"
         "                    ms_pause, ms_note = ms_poll.no_answer(time.time())\n"
         "                    if ms_note:\n"
         "                        xbmc.log(ms_note, xbmc.LOGWARNING)\n"
         "                    if ms_poll.lost(time.time()):\n"
         "                        _ms.publish('sweettv', 'failed', reason=_ms.EXPIRED)\n"
         "                        helper.set_setting('logged', 'false')\n"
         "                        if path is not None:\n"
         "                            xbmcvfs.delete(path)\n"
         "                        return\n"
         "                    ms_wait(ms_pause)\n"
         "                    continue\n"
         "                if _ms:\n"
         "                    _ms.publish('sweettv', 'failed')\n"
         "                # media-stick end\n"
         "                return\n\n            xbmc.log(\"login \""),
        ("                result = jsdata\n            else:\n                time.sleep(3)\n",
         "                result = jsdata\n            else:\n"
         "                # media-stick begin: patient: a refusal ends it, an answer nobody has described is logged and waited on, and after\n"
         "                # ten minutes the checks come slower\n"
         "                if ms_poll is not None:\n"
         "                    ms_verdict, ms_note = ms_poll.answer(jsdata, time.time())\n"
         "                    if ms_note:\n"
         "                        xbmc.log(ms_note, xbmc.LOGWARNING)\n"
         "                    if ms_verdict == 'refused':\n"
         "                        _ms.publish('sweettv', 'failed', reason=_ms.EXPIRED)\n"
         "                        helper.set_setting('logged', 'false')\n"
         "                        if path is not None:\n"
         "                            xbmcvfs.delete(path)\n"
         "                        return\n"
         "                    ms_wait(ms_poll.delay(time.time()))\n"
         "                    continue\n"
         "                # media-stick end\n"
         "                time.sleep(3)\n"),
        ("\n            refreshChannelList()\n        else:\n",
         "\n            # media-stick begin\n"
         "            if _ms:\n"
         "                _ms.publish('sweettv', 'done')\n"
         "            # media-stick end\n"
         "            refreshChannelList()\n        else:\n"),
        ("            info = jsdata.get('result', None)\n            helper.notification('Information', info)\n",
         "            info = jsdata.get('result', None)\n            helper.notification('Information', info)\n"
         "            # media-stick begin\n"
         "            if _ms:\n"
         "                _ms.publish('sweettv', 'failed')\n"
         "            # media-stick end\n"),
    ]),
    # SWEET.TV's service: a channel list that did not load is asked for again after a minute, not after a quarter of an hour
    ("plugin.video.sweettv", "service.py", [
        ("from resources.lib.sweettv import refreshToken, initSettings, refreshChannelList\n",
         "from resources.lib.sweettv import refreshToken, initSettings, refreshChannelList\n\n"
         "# media-stick begin: going back on a live channel plays the archive of the programme on now (the window of a live stream is\n"
         "# about a minute): a seek back, and a pause that outlasts the window. The deciding is mediastick_sweetlive.plan, which the\n"
         "# phone's -10 asks too. An archive asked to start somewhere other than its beginning is put there once it has begun (Kodi\n"
         "# ignores the start place of a plugin item), and an item whose address is a stream's is known from what the plugin wrote down\n"
         "import sys as _ms_sys\n"
         "import threading as _ms_threading\n"
         "\n"
         "import xbmcgui as _ms_gui\n"
         "from resources.lib import sweettv as _ms_sweettv\n"
         "\n"
         "try:\n"
         "    _ms_sys.path.insert(0, '/usr/local/lib/media-stick')\n"
         "    import mediastick_sweetlive as _ml\n"
         "except Exception:  # not a media-stick device: the add-on behaves as upstream\n"
         "    _ml = None\n"
         "\n\n"
         "class _MsPlayer(xbmc.Player):\n"
         "    def __init__(self):\n"
         "        xbmc.Player.__init__(self)\n"
         "        self.paused_at = 0\n"
         "        self.quiet_until = 0\n"
         "\n"
         "    def _live(self):\n"
         "        # the channel id of the live SWEET.TV stream that is playing, else ''\n"
         "        try:\n"
         "            found = _ml.identify(self.getPlayingFile(), time.time())\n"
         "        except Exception:\n"
         "            return ''\n"
         "        return found[0] if found and not found[1] else ''\n"
         "\n"
         "    def onAVStarted(self):\n"
         "        # an archive that was asked to start at second N: the stream starts at 0 and the player is told where it should be\n"
         "        try:\n"
         "            file = self.getPlayingFile()\n"
         "            entry = _ml.start_place(file, time.time())\n"
         "            if entry:\n"
         "                _ms_threading.Thread(target=self._to_place, args=(entry, file), daemon=True).start()\n"
         "        except Exception as e:\n"
         "            xbmc.log('media-stick: SWEET.TV start place not looked at: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "\n"
         "    def _to_place(self, entry, file):\n"
         "        try:\n"
         "            result = _ml.follow(self, entry, file)\n"
         "            xbmc.log('media-stick: SWEET.TV start place %ss: %s' % (entry['offset'], result), xbmc.LOGINFO)\n"
         "        except Exception as e:\n"
         "            xbmc.log('media-stick: SWEET.TV start place not set: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "\n"
         "    def _rewind(self, cid, back):\n"
         "        if time.time() < self.quiet_until:   # a held key sends several seeks: the first one counts\n"
         "            return\n"
         "        self.quiet_until = time.time() + 8\n"
         "        try:\n"
         "            plan = _ml.plan(_ms_sweettv.helper.get_channel_list(), cid, back, int(time.time()))\n"
         "        except Exception as e:\n"
         "            xbmc.log('media-stick: SWEET.TV rewind not planned: ' + repr(e)[:120], xbmc.LOGWARNING)\n"
         "            return\n"
         "        if plan['ok']:\n"
         "            _ml.ask_url(plan['url'])   # the add-on that resolves it is told the place here too: the path may lose its query\n"
         "            xbmc.executebuiltin('PlayMedia(%s)' % plan['url'])\n"
         "        elif plan['reason'] == 'no_archive':\n"
         "            _ms_gui.Dialog().notification('SWEET.TV', _ml.text(_ml.NO_ARCHIVE), _ms_gui.NOTIFICATION_INFO)\n"
         "\n"
         "    def onPlayBackSeek(self, seek_time, seek_offset):\n"
         "        if seek_offset < 0:\n"
         "            cid = self._live()\n"
         "            if cid:\n"
         "                self._rewind(cid, -seek_offset / 1000.0)\n"
         "            return\n"
         "        try:\n"
         "            found = _ml.identify(self.getPlayingFile(), time.time())\n"
         "            if found and not found[0].startswith('vod:') and found[1]:\n"
         "                handoff = _ml.forward_handoff(_ms_sweettv.helper.get_channel_list(), found[0], found[1],\n"
         "                                              self.getTime(), int(time.time()))\n"
         "                if handoff and handoff.get('ok'):\n"
         "                    xbmc.executebuiltin('PlayMedia(%s)' % handoff['url'])\n"
         "        except Exception:\n"
         "            pass\n"
         "\n"
         "    def onPlayBackPaused(self):\n"
         "        self.paused_at = time.time() if self._live() else 0\n"
         "\n"
         "    def onPlayBackResumed(self):\n"
         "        paused, self.paused_at = self.paused_at, 0\n"
         "        cid = self._live() if paused else ''\n"
         "        if cid and time.time() - paused > _ml.PAUSE_LIMIT:\n"
         "            self._rewind(cid, time.time() - paused)\n"
         "\n"
         "    def onPlayBackStopped(self):\n"
         "        self.paused_at = 0\n"
         "\n"
         "    def onPlayBackEnded(self):\n"
         "        self.paused_at = 0\n"
         "        try:\n"
         "            found = _ml.identify(self.getPlayingFile(), time.time())\n"
         "            if found and not found[0].startswith('vod:') and found[1]:\n"
         "                nxt = _ml.ended_plan(_ms_sweettv.helper.get_channel_list(), found[0], found[1], int(time.time()))\n"
         "                if nxt:\n"
         "                    xbmc.executebuiltin('PlayMedia(%s)' % nxt)\n"
         "        except Exception:\n"
         "            pass\n"
         "# media-stick end\n"),
        ("    initSettings()\n",
         "    initSettings()\n"
         "    # media-stick begin\n"
         "    ms_player = _MsPlayer() if _ml else None\n"
         "    # media-stick end\n"),
        ("    refreshChannelListTimer = 0\n",
         "    refreshChannelListTimer = 0\n"
         "    # media-stick begin\n"
         "    ms_failed = 0   # fetches in a row that did not give a channel list\n"
         "    # media-stick end\n"),
        ("                refreshChannelList()\n                refreshChannelListTimer = int(time.time())\n",
         "                # media-stick begin: a failed fetch is due again on the next pass (a minute), up to five times in a row, then every quarter of an hour\n"
         "                ms_reply = refreshChannelList()\n"
         "                refreshChannelListTimer = int(time.time())\n"
         "                if isinstance(ms_reply, dict) and ms_reply.get('status') == 'OK':\n"
         "                    ms_failed = 0\n"
         "                else:\n"
         "                    ms_failed += 1\n"
         "                    if ms_failed <= 5:\n"
         "                        refreshChannelListTimer -= 15 * 60\n"
         "                # media-stick end\n"),
    ]),
]


def parse_header(text):
    """(file name, version, upstream sha256) from the first line of an overlay, or None."""
    m = HEADER.match(text)
    return m.groups() if m else None


def apply_edits(text, edits, name):
    for anchor, new in edits:
        n = text.count(anchor)
        if n != 1:
            raise Stop(f"{name}: anchor found {n} times, need exactly 1:\n{anchor}")
        text = text.replace(anchor, new)
    return text


def build(upstream, edits, name, version):
    """The overlay text for upstream file bytes: header line, then the file with the edits."""
    sha = hashlib.sha256(upstream).hexdigest()
    text = upstream.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
    head = f"# media-stick overlay of {name} ({version}, upstream sha256 {sha}): changes sit between media-stick begin/end\n"
    return head + apply_edits(text, edits, name)


def pinned(list_text):
    """{add-on id: (version, url, sha256)} from the lines of kodi-addons.list."""
    out = {}
    for line in list_text.splitlines():
        f = line.split()
        if len(f) == 4 and not f[0].startswith("#"):
            out[f[0]] = tuple(f[1:])
    return out


def download(url):
    req = urllib.request.Request(url, headers={"User-Agent": "media-stick"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def read_text(path):
    try:
        with open(path, encoding="utf-8", newline="") as f:
            return f.read()
    except FileNotFoundError:
        return None


def rebuild(accept_new_upstream=False, fetch=None):
    """{overlay path under device/skin-overlay: new text} for every overlay; raises Stop."""
    fetch = fetch or download
    pins = pinned(read_text(LIST))
    zips, out = {}, {}
    for addon, path, edits in OVERLAYS:
        if addon not in pins:
            raise Stop(f"{addon} is not in {os.path.relpath(LIST, ROOT)}")
        version, url, want = pins[addon]
        if addon not in zips:
            data = fetch(url)
            if hashlib.sha256(data).hexdigest() != want:
                raise Stop(f"{addon}: the zip from {url} does not match the sha256 in kodi-addons.list")
            zips[addon] = zipfile.ZipFile(io.BytesIO(data))
        member = f"{addon}/{path}"
        try:
            upstream = zips[addon].read(member)
        except KeyError:
            raise Stop(f"{addon} {version}: no {member} in the zip")
        rel = member
        old = parse_header(read_text(os.path.join(OVERLAY, rel)) or "")
        sha = hashlib.sha256(upstream).hexdigest()
        if not accept_new_upstream and (old is None or old[2] != sha):
            was = f"the overlay was made from sha256 {old[2]}" if old else "there is no overlay yet"
            raise Stop(f"{rel}: {addon} {version} has this file at sha256 {sha}, but {was}. "
                       "Read what changed upstream; if the edits still apply, rerun with --accept-new-upstream.")
        out[rel] = build(upstream, edits, os.path.basename(path), version)
    return out


def main(argv):
    args = set(argv)
    if args - {"--check", "--accept-new-upstream"}:
        sys.exit(__doc__)
    check = "--check" in args
    if check and "--accept-new-upstream" in args:
        sys.exit("--check compares with what is committed; it cannot accept anything")
    try:
        built = rebuild("--accept-new-upstream" in args)
    except (Stop, OSError) as e:  # OSError: the download
        sys.exit(str(e))
    differ = []
    for rel, text in built.items():
        dest = os.path.join(OVERLAY, rel)
        if read_text(dest) == text:
            continue
        differ.append(rel)
        if not check:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with open(dest, "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
    for rel in differ:
        print(("differs: " if check else "written: ") + rel)
    if check and differ:
        sys.exit(1)
    print(f"{len(built)} overlays, {len(differ)} {'differ' if check else 'written'}")


if __name__ == "__main__":
    main(sys.argv[1:])
