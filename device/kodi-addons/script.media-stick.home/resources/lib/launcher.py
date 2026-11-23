"""The home launcher window: wallpaper, app carousel (100) and side drawer (201)."""
import os
import subprocess
import threading
import time
from urllib.parse import quote_plus

import xbmc
import xbmcgui

from resources.lib import apps, net, remote, ui
from resources.lib.remote import RemoteDialog
from resources.lib.ui import ADDON_PATH, LOG, MEDIA

ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
ACTION_CONTEXT_MENU = 117
NAV_ACTIONS = {1, 2, 3, 4, 7}            # left, right, up, down, select
IDLE_S = 30                              # seconds without input before the row dims (XML: Window.Property(idle))
WAKE_ONLY = NAV_ACTIONS | {ACTION_CONTEXT_MENU}   # the first of these after idle only wakes the screen
CAROUSEL, DRAWER = 100, 201
EDGE_LEFT, EDGE_RIGHT = 301, 302         # mouse-only strips at the screen edges
EDGE_STEP_S = 0.35                       # one card per step while the pointer rests there
CARDS_IN_VIEW = 7                        # whole 252 px cards in the 1824 px row
PILL_RIGHT, PILL_PAD = 1632, 24          # right edge and padding of the status pill
PILL_DIGIT, PILL_DOT = 14, 7             # approximate Reg25 glyph widths in px
WALLPAPER_CACHE = "/var/cache/media-stick/wallpapers/"
WINDOW_ID = 13000                        # Kodi's first script window id, used only if the window cannot say its own

PHONE_ICON = os.path.join(MEDIA, "icon-phone.png")

# (label, icon file in the skin media folder)
DRAWER_ITEMS = [("Search", "icon-search.png"), ("Accounts", "icon-accounts.png"),
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
    _last_input = 0.0                # time.monotonic() of the last action this window saw

    def onInit(self):
        self._last_input = time.monotonic()
        self.setProperty("idle", "")
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

    def window_id(self):
        """The id Kodi gave this window: once it is shown, it, not Home, is the current window."""
        try:
            return self.getId()
        except AttributeError:
            return WINDOW_ID

    def refresh_idle(self, on_screen=True):
        """Set or clear the idle window property, which the skin animates (the row dims and
        slides down, the QR moves to the corner). Idle needs both Kodi's own input timer, which
        sees every window, and this window's last action, so a pointer that Kodi does not count
        as input cannot make it flicker. Called by the service loop on every pass; on_screen is
        False while this window is left or under a dialog, which clears the property."""
        idle = (on_screen and time.monotonic() - self._last_input >= IDLE_S
                and xbmc.getCondVisibility(f"System.IdleTime({IDLE_S})"))
        if idle != bool(self.getProperty("idle")):
            self.setProperty("idle", "1" if idle else "")

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
        qr = ""
        if url:
            try:
                qr = remote.qr_png(url)
            except (OSError, subprocess.SubprocessError) as e:
                xbmc.log(f"{LOG} phone card QR failed: {e!r}", xbmc.LOGWARNING)
        self.setProperty("qr", qr)           # the skin's corner QR while idle shows the same png
        return qr

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

    def _focus(self):
        try:
            return self.getFocusId()
        except RuntimeError:
            return 0                 # no control has focus (the mouse left it nowhere)

    _edging = False

    def onFocus(self, controlId):
        if controlId in (EDGE_LEFT, EDGE_RIGHT) and not self._edging:
            self._edging = True
            threading.Thread(target=self._edge, args=(controlId,), daemon=True).start()

    def _edge(self, edge):
        try:
            self._edge_loop(edge)
        finally:
            self.setProperty("edgemenu", "")
            self._edging = False

    def _edge_loop(self, edge):
        """While the pointer rests on an edge strip, step the row one card at a time; the
        left strip at the row's start shows the menu instead (the strip keeps the focus, so
        the pointer resting there does not make Kodi drop it and close the menu again)."""
        row = self.getControl(CAROUSEL)
        while self._focus() == edge:
            try:
                current = int(xbmc.getInfoLabel(f"Container({CAROUSEL}).CurrentItem") or 0)
                pos = int(xbmc.getInfoLabel(f"Container({CAROUSEL}).Position") or 0)
            except ValueError:
                return
            first = current - 1 - pos            # index of the first card in view
            if edge == EDGE_LEFT:
                if first <= 0:
                    self.setProperty("edgemenu", "1")
                    xbmc.sleep(100)
                    continue
                row.selectItem(first - 1)
            else:
                if first + CARDS_IN_VIEW >= row.size():
                    return                        # the last card is in view already
                row.selectItem(first + CARDS_IN_VIEW)
            xbmc.sleep(int(EDGE_STEP_S * 1000))

    def onAction(self, action):
        self._last_input = time.monotonic()
        if self.getProperty("idle"):         # any input brings the row back; a key only does that
            self.setProperty("idle", "")
            if action.getId() in WAKE_ONLY:
                return
        # after the mouse, focus can be nowhere or on an edge strip, where keys lead nowhere:
        # the first arrow or OK then brings it back to the row
        if action.getId() in NAV_ACTIONS and self._focus() not in (CAROUSEL, DRAWER):
            self.setFocusId(DRAWER if self.getProperty("edgemenu") else CAROUSEL)
            return
        if action.getId() in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
            try:
                if self.getFocusId() == DRAWER:
                    self.setFocusId(CAROUSEL)
            except RuntimeError:
                pass                 # no control has focus
            return                   # Home never closes itself
        if action.getId() == ACTION_CONTEXT_MENU:   # the remote's menu key: menu in, menu out
            self.setFocusId(CAROUSEL if self._focus() == DRAWER else DRAWER)
            return
        super().onAction(action)

    def onClick(self, controlId):
        try:
            if controlId == CAROUSEL:
                item = self.getControl(CAROUSEL).getSelectedItem()
                if item and item.getProperty("card") == "remote":
                    self._remote()
                elif item and item.getProperty("app_id"):
                    self._launch(item.getProperty("app_id"))
                    self._fill_apps()    # the launched app is first after the card on return
            elif controlId == DRAWER:
                self._drawer(self.getControl(DRAWER).getSelectedPosition())
        except Exception as e:      # never let a click kill the service loop
            xbmc.log(f"{LOG} click {controlId} failed: {e}", xbmc.LOGERROR)

    @staticmethod
    def _launch(app_id):
        """Launch an app; a YouTube profile or a sign-in may come first. Any trouble there is a plain launch."""
        try:
            from resources.lib import accounts
            accounts.launch_app(app_id)
        except Exception as e:
            xbmc.log(f"{LOG} accounts step unavailable, launching {app_id}: {e!r}", xbmc.LOGERROR)
            apps.launch(app_id)

    def _drawer(self, position):
        label = DRAWER_ITEMS[position][0] if 0 <= position < len(DRAWER_ITEMS) else ""
        if label == "Search":
            self._search()
        elif label == "Phone & network":
            self._remote()
        elif label == "Accounts":
            self._accounts()
        elif label == "Settings":
            xbmc.executebuiltin("ActivateWindow(Settings)")
        elif label == "Power":
            self._power()

    @staticmethod
    def _accounts():
        try:
            from resources.lib import accounts_screen
            accounts_screen.show()
        except Exception as e:
            xbmc.log(f"{LOG} accounts screen failed: {e!r}", xbmc.LOGERROR)
            ui.notify("Accounts are not available.")

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
