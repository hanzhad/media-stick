"""The Accounts screen of the side menu: each service's state and what can be done about it."""
import threading
from typing import NamedTuple

import xbmc
import xbmcgui

from resources.lib import accounts, store, ui

LIST = 600
REFRESH = 2.0            # s between looks at who is signed in (the phone page may change it too)
MOVE_ACTIONS = (3, 4)    # up, down: moving away cancels a half-done sign-out
CODES = 4                # YouTube asks for up to this many codes per profile
NO_CHANNEL = "No YouTube channel on this account"     # the dim line under a signed-in profile whose account has none


class Row(NamedTuple):
    service: str
    action: str          # signin | signout | switch
    label: str
    detail: str
    confirm: bool = False


def _channel_of(accts) -> str:
    """"yes", "no" or "unknown" for the current YouTube profile (store.channel_state: the remembered answer at once)."""
    entry = next((e for e in accts if e["service"] == "youtube"), None)
    current = next((p for p in entry["profiles"] if p["current"]), None) if entry else None
    if not current or not current["signed_in"]:
        return "unknown"
    return store.channel_state(current["id"])


def _youtube_rows(entry, pending, channel="unknown"):
    profile_list = entry["profiles"]
    current = next((p for p in profile_list if p["current"]), None)
    who = current["name"] if current else "Default"
    tokens = current["tokens"] if current else 0
    out = []
    if entry["signin"] and entry["signin"]["state"] == "waiting":
        out.append(Row("youtube", "signin", "Show the sign-in code", f"{who}: signing in now"))
    elif tokens < CODES:
        label = "Sign in to YouTube" if not tokens else "Finish signing in to YouTube"
        detail = f"{who}: not signed in" if not tokens else f"{who}: {tokens} of {CODES} codes entered"
        out.append(Row("youtube", "signin", label, detail))
    if tokens:
        confirm = pending == ("youtube", "signout")
        detail = f"{who}: signed in" if tokens >= CODES else f"{who}: {tokens} of {CODES} codes entered"
        if channel == "no":                      # only when it is known; with a channel there is nothing to add
            detail += " · " + NO_CHANNEL
        out.append(Row("youtube", "signout", "Press OK again to sign out" if confirm else "Sign out of YouTube", detail, confirm))
    names = ", ".join(p["name"] for p in profile_list)
    out.append(Row("youtube", "switch", "Switch profile or add one",
                   f"{len(profile_list)} profile{'s' if len(profile_list) != 1 else ''}: {names}" if names else "Default"))
    return out


def _sweettv_rows(entry):
    if entry["signin"] and entry["signin"]["state"] == "waiting":
        return [Row("sweettv", "signin", "Show the sign-in code", "Signing in now")]
    if entry["signed_in"]:
        return [Row("sweettv", "signout", "Sign out of SWEET.TV", "Signed in")]
    return [Row("sweettv", "signin", "Sign in to SWEET.TV", "Not signed in")]


def rows(accts, pending=None, channel="unknown"):
    """The list shown: per service its sign-in state and the actions that make sense. `pending` is the
    (service, action) that has had its first press; YouTube's sign-out needs a second one. `channel` is whether the
    current YouTube profile's Google account has a channel (_channel_of)."""
    out = []
    for entry in accts:
        if entry["service"] == "youtube":
            out += _youtube_rows(entry, pending, channel)
        elif entry["service"] == "sweettv":
            out += _sweettv_rows(entry)
    return out


class AccountsDialog(xbmcgui.WindowXMLDialog):
    def setup(self):
        self.rows = []
        self.pending = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None

    def onInit(self):
        self._refresh()
        self.setFocusId(LIST)
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _watch(self):
        while not self._stop.wait(REFRESH):
            try:
                self._refresh()
            except Exception as e:
                ui.log(f"accounts refresh failed: {e!r}")

    def _refresh(self):
        with self._lock:
            accts = store.lib.accounts()
            new = rows(accts, self.pending, self._channel(accts))
            if new == self.rows:
                return
            control = self.getControl(LIST)
            position = max(0, control.getSelectedPosition())
            items = []
            for row in new:
                item = xbmcgui.ListItem(row.label, row.detail, offscreen=True)
                item.setProperty("confirm", "1" if row.confirm else "")
                items.append(item)
            control.reset()
            control.addItems(items)
            if items:
                control.selectItem(min(position, len(items) - 1))
            self.rows = new

    @staticmethod
    def _channel(accts):
        try:
            return _channel_of(accts)
        except Exception as e:                   # the note is a courtesy: the list must show without it
            ui.log(f"channel state unknown: {e!r}")
            return "unknown"

    def onClick(self, controlId):
        if controlId != LIST:
            return
        position = self.getControl(LIST).getSelectedPosition()
        if not 0 <= position < len(self.rows):
            return
        row = self.rows[position]
        try:
            self._act(row)
        except Exception as e:
            ui.log(f"accounts {row.action} {row.service} failed: {e!r}", xbmc.LOGERROR)

    def _act(self, row):
        if row.service == "youtube" and row.action == "signout":
            if self.pending != (row.service, row.action):
                self.pending = (row.service, row.action)
                self._refresh()
                return
        self.pending = None
        if row.action == "signin":
            accounts.signin_service(row.service)
        elif row.action == "signout":
            accounts.sign_out(row.service)
        elif row.action == "switch":
            accounts.choose_profile()
        self._refresh()

    def onAction(self, action):
        if action.getId() in ui.BACK_ACTIONS:
            self.close()
            return
        super().onAction(action)
        if action.getId() in MOVE_ACTIONS and self.pending:
            self.pending = None
            self._refresh()


def show():
    dialog = ui.load(AccountsDialog, "script-media-stick-accounts.xml")
    dialog.setup()
    dialog.doModal()
    dialog.stop()
    del dialog
