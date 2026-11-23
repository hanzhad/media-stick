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
         "                _ms.publish('youtube', 'waiting', code=user_code,\n"
         "                            url=('' if verification_url.startswith('http') else 'https://www.') + verification_url,\n"
         "                            link=json_data.get('verification_url_complete') or '',\n"
         "                            step=token_idx + 1, steps=len(token_types), ttl=10 * 60)\n"
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
