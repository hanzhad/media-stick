"""The full-screen sign-in dialog: the code, a QR that opens it on the phone, following the state file.

Follow is the pure part (what to show for each state the add-on publishes, and when to close);
SigninDialog and run() are the thin Kodi wrapper around it.

Partner mode (the state says mode "partner"): a partner's specialist types the code from this
screen into their own form, within a working day. So the screen stays for hours, counts down the
time left, draws no QR, keeps the screensaver off (ScreensaverHold), and never cancels on a stray
key: the first button, the one focused, is "keep waiting", and cancelling asks first.

Onboarding layout (onboarding_view, the document the sign-in writes next to its state: "Continue on your phone", the
three steps, a QR of the phone page and the code to type): while a normal sign-in waits and its document is there, the
window shows that layout in place of the plain one. It has no buttons, the keys do it: Back cancels, Menu goes on
without an account (when that is allowed). The plain layout stays for the first seconds, for partner mode and for
every end: whatever the document says or fails to say, the state file decides how the sign-in ends.
"""
import subprocess
import threading
import time
from typing import NamedTuple, Optional

import xbmc
import xbmcgui

from resources.lib import onboarding_files, onboarding_view as view, remote, store, ui

# 10 is the button that has the focus: Cancel, and in partner mode Wait, so a stray OK does nothing.
# 11 is Continue without account, and in partner mode Cancel.
CONTROL_CANCEL, CONTROL_SKIP = 10, 11
CONTROL_STEPS = 20         # the onboarding layout's list of steps
ACTION_CONTEXT_MENU = 117  # the remote's Menu key
QR_RETRY = 5               # s between looks for the phone page's QR while there is none (no network yet)
TICK = 0.5                 # s between looks for an add-on dialog on top; the state file is read every other tick
START_WAIT = 45            # s without any state from the add-on: give up
CANCEL_WAIT = 10           # s the add-on gets to see a stop request (YouTube looks between two polls)
FRESH_SLACK = 2            # s: the state's `updated` has whole-second resolution
MAX_REOPEN = 40            # a dialog that keeps getting covered is left alone after this many tries
SHOWING = "media-stick.signin"       # Home window property "<service>:<unix time>" while a screen is up
SHOWING_ALIVE = 5          # s: the screen refreshes the property every second or so
PROGRESS_DIALOG = 10101    # the add-on's own modal progress dialog (YouTube's code dialog)
LINGER = {"done": 2.0, "failed": 3.0, "cancelled": 1.5, "gone": 1.5, "skipped": 0.5}   # s the result stays up
MESSAGES = {               # result -> (headline, status)
    "done": ("Signed in", ""),
    "failed": ("Sign-in did not work", "Try again from Accounts."),
    "cancelled": ("Sign-in cancelled", ""),
    "gone": ("Sign-in stopped", ""),
    "skipped": ("Continuing without an account", ""),
}
FINISHED = ("done", "failed", "cancelled")
WAITING = "waiting"
PARTNER = "partner"
BUTTONS = ("Cancel", "Continue without account")                  # the two buttons, by mode
PARTNER_BUTTONS = ("Ждать / Wait", "Отмена / Cancel")
PARTNER_STATUS = ("Ждём подключения специалистом партнёра. Не выключайте ТВ.",
                  "Waiting for the partner's specialist to connect. Keep the TV on.")
CONFIRM = ("Отменить вход? / Cancel sign-in?",
           "Специалист партнёра не сможет подключить подписку, а код пропадёт.[CR]"
           "The partner's specialist will not be able to connect, and the code will be lost.")
CONFIRM_AUTOCLOSE = 30000  # ms: a question nobody answers closes itself, and the sign-in goes on
INHIBIT_EVERY = 60         # s: how often the screensaver is told to stay off while a partner is awaited


class Frame(NamedTuple):
    props: dict                  # window properties for the skin
    link: str                    # what the QR holds ("" when no code is shown)
    result: Optional[str]        # done | failed | cancelled | gone | skipped, once decided
    close: bool                  # the result has been up long enough
    rows: tuple = ()             # the onboarding layout's steps, when it is the one shown (view.Row)
    ob_link: str = ""            # the sign-in link, for a QR when the phone page has none to show


def time_left(seconds):
    """(line, English line) for the time left. Under an hour it is minutes and seconds, "59:59" or "0:05", as a clock
    counts down (nothing to translate: the English line is empty). From an hour on the hours are said, in whole minutes
    rounded down so it only ever goes down: 21599 -> "5 ч 59 мин" and "5 h 59 min", 3600 -> "1 ч 00 мин". The line is
    Russian (it is big: the screen is read by a partner's specialist) and the English one goes under it, small:
    both do not fit side by side in the label. 0 and anything that is not a time -> "0:00"."""
    total = max(0, int(seconds or 0))
    if total < 3600:
        return f"{total // 60}:{total % 60:02d}", ""
    hour, minute = divmod(total // 60, 60)
    return f"{hour} ч {minute:02d} мин", f"{hour} h {minute:02d} min"


def hours(seconds):
    """The first line of time_left: what the big label shows."""
    return time_left(seconds)[0]


def asked_partner(service):
    """Whether the phone asked for a partner sign-in that has not started yet (so the first
    seconds of the screen already say so). An older library without modes: no."""
    try:
        return store.lib.requested_mode(service) == PARTNER
    except Exception as e:
        ui.log(f"cannot read the requested sign-in mode: {e!r}")
        return False


class ScreensaverHold:
    """Keeps Kodi's screensaver (and display power-off) away while a partner is awaited. Pure: step()
    says which builtin to run now, if any: at once when it starts being wanted, again every
    INHIBIT_EVERY seconds, and the release when it is wanted no more.
    InhibitScreensaver(true) is Kodi 21's own builtin: it holds the idle timer off until it is told
    false, so a missed call costs nothing, and it is not a fake key press that could hit a button."""

    def __init__(self):
        self.last = None

    def step(self, wanted, now):
        if wanted and (self.last is None or now - self.last >= INHIBIT_EVERY):
            self.last = now
            return "InhibitScreensaver(true)"
        if not wanted and self.last is not None:
            self.last = None
            return "InhibitScreensaver(false)"
        return None


def spaced(code):
    """A code for reading from the sofa: letters apart, groups set off by a dash."""
    return "  -  ".join(" ".join(group) for group in code.split("-"))


def site(url):
    """youtube.com/activate from https://www.youtube.com/activate."""
    return view.site(url)


def covered(top, mine):
    """True when a dialog of the add-on is on top of ours: its progress dialog, or a script window
    of the add-on (same block of window ids as ours). Kodi's own questions are left alone."""
    if not mine or not top or top == mine:
        return False
    return top == PROGRESS_DIALOG or top // 100 == mine // 100


def parse_showing(text, now):
    """The service whose screen is up according to the Home property, or ""."""
    service, _, stamp = (text or "").partition(":")
    try:
        return service if service in store.SERVICES and now - int(stamp) <= SHOWING_ALIVE else ""
    except ValueError:
        return ""


def can_attach(state, now):
    """A sign-in that is waiting and was touched a moment ago is alive: show it, do not start another."""
    return bool(state) and state["state"] == WAITING and now - state.get("updated", 0) <= 15


class Follow:
    """Follows one sign-in through the states its add-on publishes. Pure: feed() takes what
    store.lib.read returned and the time, and says what to show and whether to close."""

    def __init__(self, name, started, attach=False, partner=False):
        self.name, self.started, self.attach = name, started, attach
        self.partner = partner       # a partner's specialist will type the code in (the state says so too)
        self.seen = False            # a state of this sign-in has been read
        self.cancel_at = None
        self.skipped = False         # the person chose to go on without an account
        self.result = None
        self.result_at = 0.0
        self.note = ""

    @property
    def cancelling(self):
        return self.cancel_at is not None and self.result is None

    def cancel(self, now, skip=False):
        if self.result is None and self.cancel_at is None:
            self.cancel_at, self.skipped = now, skip

    def force(self, now):
        """A second Back while cancelling: leave without waiting for the add-on."""
        if self.result is None:
            self._finish("skipped" if self.skipped else "cancelled", now)

    def _finish(self, result, now, note=""):
        self.result, self.result_at, self.note = result, now, note

    def usable(self, state):
        """The state, unless it is left over from before this screen (an earlier result, or a
        dead sign-in this one started over). A live one shown by attaching is accepted at any age."""
        if not state:
            return None
        if self.attach and state["state"] == WAITING:
            return state
        return state if state.get("updated", 0) >= self.started - FRESH_SLACK else None

    def _decide(self, state, now):
        kind = state["state"] if state else ""
        if self.cancel_at is not None:
            if (kind in FINISHED or (not state and self.seen) or now - self.cancel_at >= CANCEL_WAIT):
                self._finish("skipped" if self.skipped else "cancelled", now)
        elif kind in FINISHED:
            self._finish(kind, now)
        elif not state and self.seen:
            self._finish("gone", now)
        elif not state and now - self.started >= START_WAIT:
            self._finish("failed", now, "No code came. Try again from Accounts.")

    def feed(self, state, now, ob=None):
        """`ob` is the sign-in's onboarding screen (view.Screen) when it has one: it replaces the plain layout while a
        normal sign-in waits."""
        state = self.usable(state)
        if state:
            self.seen = True
            if state["state"] == WAITING:
                self.partner = state.get("mode") == PARTNER
        if self.result is None:
            self._decide(state, now)
        waiting = state if state and state["state"] == WAITING and self.result is None and self.cancel_at is None else None
        props, link = self._props(waiting)
        shown = ob if waiting and not self.partner and ob and ob.active and ob.flow == view.SIGNIN else None
        props.update(view.signin_props(shown, "", ""))
        return Frame(props, link, self.result, self.result is not None and now - self.result_at >= LINGER[self.result],
                     view.step_rows(shown, view.SIGNIN_STEP_W) if shown else (),
                     str(waiting.get("link", "")) if shown else "")

    def _props(self, waiting):
        props = {"title": self.name, "step": "", "code": "", "codelong": "", "site": "", "headline": "", "status": "",
                 "status2": "", "left": "", "left2": "", "partner": "1" if self.partner else "",
                 "btn1": (PARTNER_BUTTONS if self.partner else BUTTONS)[0],
                 "btn2": (PARTNER_BUTTONS if self.partner else BUTTONS)[1]}
        if self.result:
            props["headline"], props["status"] = MESSAGES[self.result]
            props["status"] = self.note or props["status"]
        elif self.cancel_at is not None:
            props["headline"], props["status"] = "Cancelling…", "Stopping the sign-in."
        elif waiting:
            code = str(waiting.get("code", ""))
            if waiting.get("steps", 1) > 1:
                props["step"] = f"Code {waiting.get('step', 1)} of {waiting['steps']}"
            props["code"] = spaced(code)
            props["codelong"] = "1" if len(code) > 14 else ""
            if self.partner:         # a person reads the code off the screen: no QR, no "scan", the time left instead
                props["left"], props["left2"] = time_left(waiting.get("left", 0))
                props["status"], props["status2"] = PARTNER_STATUS
                return props, ""
            if waiting.get("url"):
                props["site"] = f"Or open {site(waiting['url'])} and type the code"
            props["status"] = "Waiting for the code to be entered…"
            return props, str(waiting.get("link", ""))
        else:
            props["headline"], props["status"] = "Getting a code…", "This takes a few seconds."
        return props, ""


def mark_showing(service, now):
    xbmcgui.Window(ui.HOME).setProperty(SHOWING, f"{service}:{int(now)}")


def clear_showing():
    xbmcgui.Window(ui.HOME).setProperty(SHOWING, "")


def showing(now=None):
    """The service whose sign-in screen is up right now (any script's), or ""."""
    return parse_showing(xbmcgui.Window(ui.HOME).getProperty(SHOWING), time.time() if now is None else now)


class LibSource:
    """What the window follows and where its stop request goes: the device's libraries. The demo (onboarding_demo) has
    one of its own with the same five methods."""

    def read(self, service):
        return store.lib.read(service)

    def onboarding(self, service):
        return onboarding_files.read(service)

    def request_cancel(self, service):
        store.lib.request_cancel(service)

    def asked_partner(self, service):
        return asked_partner(service)

    def phone_qr(self):
        return onboarding_files.phone_qr()


class SigninDialog(xbmcgui.WindowXMLDialog):
    """Set up with setup() after construction: the Kodi window constructors take no extra arguments."""

    def setup(self, service, follow, allow_skip, cover, hold=None, source=None):
        self.service, self.follow, self.allow_skip, self.cover = service, follow, allow_skip, cover
        self.hold = hold or ScreensaverHold()
        self.source = source or LibSource()
        self._rows = None                # the steps now in the list (the onboarding layout)
        self._phone_qr, self._qr_at = "", 0.0
        self._link_qr = ("", "")         # (link, its QR picture): the fallback of the onboarding layout
        self.reopen = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._shown = {}
        self._link = ""
        self._window_id = 0

    def onInit(self):
        self._window_id = xbmcgui.getCurrentWindowDialogId()
        self.setProperty("skip", "1" if self.allow_skip else "")
        self.setFocusId(CONTROL_CANCEL)
        self._poll()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _watch(self):
        beat = 0
        while not self._stop.wait(TICK):
            try:
                if self.cover and covered(xbmcgui.getCurrentWindowDialogId(), self._window_id):
                    self.reopen = True       # the add-on's dialog came up above ours: close and open again on top
                    self.close()
                    return
                beat += 1
                if beat % 2 == 0:
                    self._poll()
                self._hold_screensaver()
            except Exception as e:
                ui.log(f"sign-in screen tick failed: {e!r}")

    def _hold_screensaver(self):
        """Keep the screensaver off while a partner is awaited (this screen is the only thing they see)."""
        command = self.hold.step(self.follow.partner and self.follow.result is None, time.time())
        if command:
            xbmc.executebuiltin(command)

    def _read(self):
        try:
            return self.source.read(self.service)
        except Exception as e:
            ui.log(f"cannot read the sign-in state: {e!r}")
            return None

    def _read_onboarding(self):
        try:
            return view.parse(self.source.onboarding(self.service), self.follow.name)
        except Exception as e:
            ui.log(f"cannot read the onboarding document: {e!r}")
            return None

    def _poll(self):
        with self._lock:
            now = time.time()
            frame = self.follow.feed(self._read(), now, self._read_onboarding())
            self._apply(frame)
            if self.follow.cancelling:
                self.source.request_cancel(self.service)       # again: the add-on clears an early request when it starts
            mark_showing(self.service, now)
        if frame.close:
            self.close()

    def _set(self, key, value):
        if self._shown.get(key) != value:
            self._shown[key] = value
            self.setProperty(key, value)

    def _apply(self, frame):
        props = dict(frame.props)
        if props.get("ob"):
            try:
                props.update(self._onboarding_extras(frame))
            except Exception as e:           # the layout cannot be filled: the plain one still shows the code
                ui.log(f"onboarding layout failed, the plain layout is used: {e!r}")
                props.update(view.signin_props(None, "", ""))
        for key, value in props.items():
            self._set(key, value)
        self._set("skip", "1" if self.allow_skip or self.follow.partner else "")     # partner: the second button is Cancel
        if frame.link and frame.link != self._link:
            self._link = frame.link
            self._set("qr", self._qr(frame.link))

    def _onboarding_extras(self, frame):
        """What only the window knows about the onboarding layout: the steps in their list, the QR and its line, the
        footer. The QR is the phone page's (the person is told to scan it when the phone is not on the page yet); with
        no network it is the sign-in link's, which opens the provider's page on the phone."""
        if frame.rows != self._rows:
            self._rows = frame.rows
            ui.fill_list(self, CONTROL_STEPS, [r.props() for r in frame.rows],
                         select=next((n for n, r in enumerate(frame.rows) if r.state == "now"), 0))
        now = time.time()
        if not self._phone_qr and now - self._qr_at >= QR_RETRY:
            self._qr_at = now
            self._phone_qr = self.source.phone_qr()
        if self._phone_qr:
            picture, caption = self._phone_qr, view.QR_REMOTE
        else:
            if frame.ob_link and self._link_qr[0] != frame.ob_link:
                self._link_qr = (frame.ob_link, self._qr(frame.ob_link))
            picture, caption = self._link_qr[1] if frame.ob_link else "", view.QR_LINK
        return {"ob_qr": picture, "ob_caption": caption, "ob_footer": view.signin_footer(self.allow_skip)}

    @staticmethod
    def _qr(link):
        try:
            return remote.qr_png(link)
        except (OSError, subprocess.SubprocessError) as e:
            ui.log(f"sign-in QR failed: {e!r}")
            return ""

    def _sure(self):
        """The question before a partner sign-in is given up: the answer is no unless it is a clear yes
        (the first button, which has the focus, is "Wait"); the focus goes back to Wait afterwards."""
        heading, line = CONFIRM
        try:
            yes = xbmcgui.Dialog().yesno(heading, line, nolabel=PARTNER_BUTTONS[0], yeslabel=PARTNER_BUTTONS[1],
                                         autoclose=CONFIRM_AUTOCLOSE)
        except Exception as e:
            ui.log(f"cannot ask before cancelling: {e!r}")
            yes = False
        self.setFocusId(CONTROL_CANCEL)
        return bool(yes)

    def _cancel(self, skip):
        if self.follow.partner and self.follow.result is None and not self.follow.cancelling and not self._sure():
            return
        self.follow.cancel(time.time(), skip)
        self.source.request_cancel(self.service)
        self._poll()

    def onClick(self, controlId):
        if self.follow.partner:
            if controlId == CONTROL_SKIP:            # Cancel; the first button only keeps waiting
                self._cancel(False)
        elif controlId == CONTROL_CANCEL:
            self._cancel(False)
        elif controlId == CONTROL_SKIP and self.allow_skip:
            self._cancel(True)

    def onAction(self, action):
        if action.getId() in ui.BACK_ACTIONS:
            if self.follow.cancelling:
                self.follow.force(time.time())
                self._poll()
            else:
                self._cancel(False)
        elif action.getId() == ACTION_CONTEXT_MENU and self._shown.get("ob") and self.allow_skip \
                and not self.follow.cancelling:
            self._cancel(True)               # the onboarding layout has no buttons: Menu is "continue without an account"
        else:
            super().onAction(action)


def run(service, attach=False, allow_skip=False, source=None):
    """Show the sign-in screen for `service` until it has a result; returns done | failed |
    cancelled | gone | skipped, or "closed" when the window went away without one. Every path ends.
    `source` is where the window reads from (LibSource, the device's files; the demo brings its own)."""
    source = source or LibSource()
    follow = Follow(store.SERVICES[service]["name"], time.time(), attach, partner=source.asked_partner(service))
    hold = ScreensaverHold()           # outlives a reopened window, so it does not flap
    opened = 0
    try:
        while True:
            dialog = ui.load(SigninDialog, "script-media-stick-signin.xml")
            dialog.setup(service, follow, allow_skip, cover=opened < MAX_REOPEN, hold=hold, source=source)
            dialog.doModal()
            dialog.stop()
            again = dialog.reopen
            del dialog
            opened += 1
            if follow.result is not None or not again:
                break
    finally:
        clear_showing()
        release = hold.step(False, time.time())      # whatever ended the screen, the screensaver is allowed again
        if release:
            xbmc.executebuiltin(release)
    return follow.result or "closed"
