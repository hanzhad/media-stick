"""Phone remote dialog: QR code and address of the device's web page."""
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


def qr_png(url, ip):
    # The address in the name: Kodi caches textures by path.
    path = os.path.join(xbmcvfs.translatePath("special://temp/"), f"media-stick-qr-{ip}.png")
    if not os.path.exists(path):
        subprocess.run(["qrencode", "-o", path, "-s", "10", "-m", "2", "-l", "M", url],
                       check=True, timeout=10, capture_output=True)
    return path


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
    url = f"http://{ip}/" if ip else ""
    return {"ip": ip, "url": url,
            "qr": field("qr", lambda: qr_png(url, ip)) if ip else "",
            "network": field("network", lambda: network_line(ip)),
            "hint": HINT if ip else "Connect the stick to Wi-Fi or Ethernet first."}


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
