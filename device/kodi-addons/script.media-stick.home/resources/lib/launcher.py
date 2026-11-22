"""The home launcher window: wallpaper, app carousel (100) and side drawer (201)."""
import os
import subprocess
from urllib.parse import quote_plus

import xbmc
import xbmcaddon
import xbmcgui

from resources.lib import apps, net, remote
from resources.lib.remote import RemoteDialog

LOG = "[script.media-stick.home]"
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
CAROUSEL, DRAWER = 100, 201
PILL_RIGHT, PILL_PAD = 1632, 24          # right edge and padding of the status pill
PILL_DIGIT, PILL_DOT = 14, 7             # approximate Reg25 glyph widths in px
WALLPAPER_CACHE = "/var/cache/media-stick/wallpapers/"
ADDON_PATH = xbmcaddon.Addon().getAddonInfo("path")
MEDIA = os.path.join(ADDON_PATH, "resources", "skins", "default", "media")

PHONE_ICON = os.path.join(MEDIA, "icon-phone.png")

# (label, icon file in the skin media folder)
DRAWER_ITEMS = [("Search", "icon-search.png"), ("Add-ons", "icon-apps.png"),
                ("Phone & network", "icon-phone.png"), ("Settings", "icon-settings.png"),
                ("Power", "icon-power.png")]
POWER = [("Restart Kodi", ["restart", "kodi.service"]),
         ("Reboot", ["reboot"]),
         ("Power off", ["poweroff"])]


def has_cached_wallpapers():
    try:
        return any(n.lower().endswith(".jpg") for n in os.listdir(WALLPAPER_CACHE))
    except OSError:
        return False


class Launcher(xbmcgui.WindowXML):
    _card_url = None                 # the address the Phone remote card was last built for

    def onInit(self):
        self.setProperty("wallpaper", "cache" if has_cached_wallpapers() else "bundled")
        self.refresh_status(force=True)
        self._fill_drawer()
        self._fill_apps()
        if self.getControl(CAROUSEL).size():
            self.setFocusId(CAROUSEL)

    def refresh_status(self, force=False):
        """Update the ip / net window properties and the pill, touching them only when they change."""
        ip = net.address()
        kind = net.kind() if ip else ""
        changed = self.getProperty("ip") != ip or self.getProperty("net") != kind
        if changed:
            self.setProperty("ip", ip)
            self.setProperty("net", kind)
        if changed or force:
            self._layout_pill(ip, kind)
        try:
            self._sync_card(ip)
        except RuntimeError as e:
            xbmc.log(f"{LOG} phone card refresh failed: {e}", xbmc.LOGWARNING)

    def _layout_pill(self, ip, kind):
        """Size the pill to its content (phone icon, address, network icon): a skin cannot
        measure text, so the address width is estimated from its characters."""
        if not ip:
            return
        text = sum(PILL_DIGIT if c.isdigit() else PILL_DOT for c in ip) + 6
        width = PILL_PAD + 40 + 12 + text + (16 + 36 if kind else 0) + PILL_PAD
        left = PILL_RIGHT - width
        try:
            self.getControl(401).setPosition(left, 0)
            self.getControl(401).setWidth(width)
            self.getControl(402).setPosition(left + PILL_PAD, 20)
            self.getControl(403).setPosition(left + PILL_PAD + 52, 0)
            self.getControl(403).setWidth(text + 4)
            for control_id in (404, 405):
                self.getControl(control_id).setPosition(left + PILL_PAD + 52 + text + 16, 22)
        except RuntimeError as e:
            xbmc.log(f"{LOG} pill layout failed: {e}", xbmc.LOGWARNING)

    def _card_qr(self, url):
        """The QR png for the card, or "" when offline or qrencode fails (the card then shows the
        phone icon). Remembers the address, so a failure is not retried until it changes."""
        self._card_url = url
        if not url:
            return ""
        try:
            return remote.qr_png(url)
        except (OSError, subprocess.SubprocessError) as e:
            xbmc.log(f"{LOG} phone card QR failed: {e!r}", xbmc.LOGWARNING)
            return ""

    @staticmethod
    def _style_card(item, qr):
        art = qr or PHONE_ICON
        item.setArt({"icon": art, "thumb": art})
        item.setProperty("glyph", "" if qr else "1")     # the skin draws the icon small, not as a full card

    def _sync_card(self, ip):
        """Rebuild the card's art when the address changed (IP, or https switched on or off)."""
        url = remote.page_url(ip) if ip else ""
        if url == self._card_url:
            return
        control = self.getControl(CAROUSEL)
        if not control.size():
            return                   # _fill_apps builds the card
        item = control.getListItem(0)
        if item.getProperty("card") == "remote":
            self._style_card(item, self._card_qr(url))

    def _fill_apps(self):
        ip = net.address()
        url = remote.page_url(ip) if ip else ""
        items = []
        for app in apps.carousel(apps.ordered_apps()):
            item = xbmcgui.ListItem(app.name, offscreen=True)
            if app.id == apps.CARD_ID:
                item.setProperty("card", "remote")
                self._style_card(item, self._card_qr(url))
            else:
                item.setArt({"icon": app.art, "thumb": app.art})
                item.setProperty("app_id", app.id)
            items.append(item)
        control = self.getControl(CAROUSEL)
        control.reset()
        control.addItems(items)
        control.selectItem(apps.first_app_index(len(items) - 1))

    def _fill_drawer(self):
        items = []
        for label, icon in DRAWER_ITEMS:
            item = xbmcgui.ListItem(label, offscreen=True)
            item.setArt({"icon": os.path.join(MEDIA, icon)})
            items.append(item)
        control = self.getControl(DRAWER)
        control.reset()
        control.addItems(items)

    def onAction(self, action):
        if action.getId() in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
            try:
                if self.getFocusId() == DRAWER:
                    self.setFocusId(CAROUSEL)
            except RuntimeError:
                pass                 # no control has focus
            return                   # Home never closes itself
        super().onAction(action)

    def onClick(self, controlId):
        try:
            if controlId == CAROUSEL:
                item = self.getControl(CAROUSEL).getSelectedItem()
                if item and item.getProperty("card") == "remote":
                    self._remote()
                elif item and item.getProperty("app_id"):
                    apps.launch(item.getProperty("app_id"))
                    self._fill_apps()    # the launched app is first after the card on return
            elif controlId == DRAWER:
                self._drawer(self.getControl(DRAWER).getSelectedPosition())
        except Exception as e:      # never let a click kill the service loop
            xbmc.log(f"{LOG} click {controlId} failed: {e}", xbmc.LOGERROR)

    def _drawer(self, position):
        if position == 0:
            self._search()
        elif position == 1:
            xbmc.executebuiltin("ActivateWindow(AddonBrowser,return)")
        elif position == 2:
            self._remote()
        elif position == 3:
            xbmc.executebuiltin("ActivateWindow(Settings)")
        elif position == 4:
            self._power()

    def _remote(self):
        dialog = RemoteDialog("script-media-stick-remote.xml", ADDON_PATH, "default", "1080i")
        dialog.doModal()
        del dialog

    def _search(self):
        text = xbmcgui.Dialog().input("Search YouTube").strip()
        if text:
            url = f"plugin://plugin.video.youtube/kodion/search/query/?q={quote_plus(text)}"
            xbmc.executebuiltin(f'ActivateWindow(Videos,"{url}",return)')

    def _power(self):
        dialog = xbmcgui.Dialog()
        choice = dialog.select("Power", [label for label, _ in POWER])
        if choice < 0:
            return
        label, command = POWER[choice]
        if dialog.yesno("Power", f"{label}?"):
            try:
                subprocess.Popen(["sudo", "-n", "/bin/systemctl"] + command)
            except OSError as e:
                xbmc.log(f"{LOG} {label} failed: {e}", xbmc.LOGERROR)
