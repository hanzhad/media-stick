"""A QR code in the bottom-right corner of the home screen, pointing at the device's
page (http://<ip>/, the phone remote). Uses the IP address rather than mediastick.local:
many Android phones cannot resolve .local names.

Kodi rebuilds a skin window each time it opens, dropping controls added from Python,
so the code is put back every time the home screen comes up, and redrawn when the
address changes. Nothing is shown without a home-network address (the setup hotspot
shows its own instructions)."""
import os
import subprocess

import xbmc
import xbmcgui
import xbmcvfs

HOME_WINDOWS = (10000, 10060)        # Home, Favourites
W, H = 3840, 2160                    # skin.ftv's coordinate space
SIZE = 400
MARGIN = 80
TEMP = xbmcvfs.translatePath("special://temp/")


def address():
    ip = xbmc.getIPAddress()
    return ip if ip and not ip.startswith("127.") and not ip.startswith("10.42.") else ""


def qr_png(url, ip):
    # The address in the name: Kodi caches textures by path.
    path = os.path.join(TEMP, f"media-stick-qr-{ip}.png")
    if not os.path.exists(path):
        subprocess.run(["qrencode", "-o", path, "-s", "12", "-m", "2", "-l", "M", url],
                       check=True, timeout=10)
    return path


class Overlay:
    def __init__(self):
        self.window = None
        self.controls = []

    def show(self, window_id, ip):
        self.hide()
        url = f"http://{ip}/"
        try:
            image = qr_png(url, ip)
        except (OSError, subprocess.SubprocessError) as e:
            xbmc.log(f"media-stick-qr: qrencode failed: {e}", xbmc.LOGWARNING)
            return
        x, y = W - MARGIN - SIZE, H - MARGIN - SIZE - 70
        self.window = xbmcgui.Window(window_id)
        self.controls = [
            xbmcgui.ControlImage(x, y, SIZE, SIZE, image),
            xbmcgui.ControlLabel(x - 700, y + SIZE + 10, SIZE + 700, 70, f"Пульт: {ip}",
                                 font="Reg37", textColor="FFFFFFFF", alignment=1),
        ]
        self.window.addControls(self.controls)

    def hide(self):
        if self.window and self.controls:
            try:
                self.window.removeControls(self.controls)
            except (RuntimeError, TypeError):
                pass                 # already gone with the window
        self.window, self.controls = None, []


def main():
    monitor = xbmc.Monitor()
    overlay = Overlay()
    shown = None                     # (window id, ip) currently drawn
    while not monitor.abortRequested():
        current = xbmcgui.getCurrentWindowId()
        ip = address()
        want = (current, ip) if current in HOME_WINDOWS and ip else None
        if want != shown:
            overlay.hide()
            if want:
                overlay.show(*want)
            shown = want
        if monitor.waitForAbort(1):
            break
    overlay.hide()


main()
