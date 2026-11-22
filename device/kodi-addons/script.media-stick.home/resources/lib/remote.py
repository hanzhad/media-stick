"""Phone remote dialog: QR code and address of the device's web page."""
import hashlib
import json
import os
import subprocess

import xbmc
import xbmcgui
import xbmcvfs

from resources.lib import net

ACTION_NAV_BACK = 92
ACTION_PREVIOUS_MENU = 10
ACTION_SELECT_ITEM = 7
BUSY = "busydialognocancel"
HINT = "Scan with the phone camera, or open the address in a browser on the same Wi-Fi."
STATE = "/var/lib/media-stick"   # panel-url, https-status.json, https-suggest: world-readable, no secrets
LONG_URL = 22                    # a longer name than this is shown in the smaller, scrolling font


def qr_png(url, size=10):
    # The whole address in the name: Kodi caches textures by path.
    key = hashlib.sha1(url.encode()).hexdigest()[:12]
    path = os.path.join(xbmcvfs.translatePath("special://temp/"), f"media-stick-qr-{key}.png")
    if not os.path.exists(path):
        subprocess.run(["qrencode", "-o", path, "-s", str(size), "-m", "2", "-l", "M", url],
                       check=True, timeout=10, capture_output=True)
    return path


def state_text(name):
    try:
        with open(os.path.join(STATE, name)) as f:
            return f.read().strip()
    except OSError:
        return ""


def https_info(ip):
    """Air mouse (needs HTTPS) as the dialog shows it: the https address once a certificate
    exists, one status line while it is being set up or failed, or the three setup steps
    with a second QR that opens the phone page on the HTTPS card."""
    url = state_text("panel-url")
    if url.startswith("https://"):
        name = url[len("https://"):].rstrip("/")
        return {"url": url, "shown": name, "airline": f"Air mouse: on · {name}"}
    try:
        state = json.loads(state_text("https-status.json") or "{}").get("state", "")
    except (ValueError, AttributeError):
        state = ""
    if state == "error":
        return {"airline": "Air mouse: setup failed, see the phone page"}
    if state:
        return {"airline": "Air mouse: setting up…"}
    sub = state_text("https-suggest")
    link = f"http://{ip}/#https" + (f"?sub={sub}" if sub else "")
    return {"airsetup": "1", "airsub": sub or "your-name", "airqr": qr_png(link, 8)}


def network_line(ip):
    if not ip:
        return "Not connected"
    if net.kind() == "wifi":
        ssid = net.ssid()
        return f"Wi-Fi: {ssid}" if ssid else "Wi-Fi"
    return "Ethernet"


def field(name, fn):
    """One property value; a failure costs only that field."""
    try:
        return fn()
    except Exception as e:
        xbmc.log(f"[script.media-stick.home] remote {name} failed: {e!r}", xbmc.LOGWARNING)
        return ""


def gather():
    ip = field("ip", net.address)
    https = (field("https", lambda: https_info(ip)) or {}) if ip else {}
    url = https.get("url") or (f"http://{ip}/" if ip else "")
    shown = https.get("shown") or url
    props = {"ip": ip, "url": url, "shown": shown, "urllong": "1" if len(shown) > LONG_URL else "",
             "qr": field("qr", lambda: qr_png(url)) if ip else "",
             "network": field("network", lambda: network_line(ip)),
             "hint": HINT if ip else "Connect the stick to Wi-Fi or Ethernet first."}
    for key in ("airline", "airsetup", "airsub", "airqr"):
        props[key] = https.get(key, "")
    return props


class RemoteDialog(xbmcgui.WindowXMLDialog):
    def onInit(self):
        self.setFocusId(300)
        xbmc.executebuiltin(f"ActivateWindow({BUSY})")
        try:
            props = gather()
        finally:
            xbmc.executebuiltin(f"Dialog.Close({BUSY})")
        for key, value in props.items():
            self.setProperty(key, value)
        self.setFocusId(300)

    def onClick(self, controlId):
        self.close()

    def onAction(self, action):
        if action.getId() in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU, ACTION_SELECT_ITEM):
            self.close()
        else:
            super().onAction(action)
