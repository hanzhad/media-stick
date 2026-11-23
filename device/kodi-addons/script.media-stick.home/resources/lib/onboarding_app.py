"""The onboarding window: what the TV shows while the phone works through a flow with steps (the Google key wizard).

  RunScript(script.media-stick.home,onboarding,show,<service>)   follows /run/media-stick/onboarding/<service>.json
  RunScript(script.media-stick.home,onboarding,demo,signin|keys) the same screens on an invented document; nothing real

A dim backdrop and one rounded card: the steps on the left (done, now, to come), on the right where on the Google page to
tap as rows of chips, a warning, and the status badges of what the phone has handed over so far (never a value). The
sign-in code has its own screen (signin.py, which draws the same kind of card from the same document): this window is
for every other flow. What the screen says is the document's `tv` text; onboarding_view turns it into properties and
says where the chips go. The window reads the file once a second in a worker thread, like the other watchers, and
changes only what changed. Back closes it; it closes itself a moment after the flow ends or the document is gone.
"""
import threading
import time

import xbmcgui

from resources.lib import onboarding_demo, onboarding_files, onboarding_view as view, store, ui

XML = "script-media-stick-onboarding.xml"
STEPS, BADGES, WARN = 20, 30, 50          # the lists, and the warning (which goes under the last row of chips)
CHIP_IMAGE, CHIP_LABEL, SEPARATOR, THEN = 100, 200, 300, 400     # + the slot's number: the controls the chips move
AREA_X, AREA_Y = 870, 259                 # the chip area's corner on the screen (the skin puts the slots there)
POLL = 1.0                                # s between looks at the document
LINGER = {"done": 2.5, "failed": 4.0, "cancelled": 1.5}     # s a flow's end stays up
GONE_GRACE = 4.0                          # s a document that is not there is waited for before the window gives up
ADDRESS_RETRY = 5                         # s between looks for the phone page's address while there is none
RUNNING = "media-stick.onboarding"        # Home window property while the window is open: a second launch does nothing


def clock():
    return time.time()


class LiveSource:
    """What the window reads: the device's onboarding document of the service."""

    def read(self, service):
        return onboarding_files.read(service)


class OnboardingDialog(xbmcgui.WindowXMLDialog):
    """Set up with setup() after construction: the Kodi window constructors take no extra arguments."""

    def setup(self, service, source, name=""):
        self.service, self.source, self.name = service, source, name
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._shown = {}                  # property -> value now set
        self._placed = None               # the chips where they are
        self._rows = None                 # the steps in the list
        self._badges = None
        self._gone = self._ended = None   # since when the document is not there / the flow has ended
        self._address, self._address_at = "", 0.0

    def onInit(self):
        self._look()
        self._thread = threading.Thread(target=self._watch, daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread is not None:
            self._thread.join(2)

    def _watch(self):
        while not self._stop.wait(POLL):
            try:
                self._look()
            except Exception as e:           # a look that fails is tried again at the next one
                ui.log(f"onboarding look failed: {e!r}")

    def _look(self):
        now = clock()
        try:
            screen = view.parse(self.source.read(self.service), self.name)
        except Exception as e:
            ui.log(f"cannot read the onboarding document: {e!r}")
            screen = None
        with self._lock:
            if self._stop.is_set():
                return
            if screen is None:
                self._gone = self._gone or now
                done = now - self._gone >= GONE_GRACE
            else:
                self._gone = None
                self._draw(screen, now)
                self._ended = None if screen.active else (self._ended or now)
                done = self._ended is not None and now - self._ended >= LINGER[screen.state]
        if done:
            self.close()

    def _draw(self, screen, now):
        placed = view.layout_chips(screen.chips)
        if placed != self._placed:
            self._placed = placed
            self._move(placed)
        props = view.keys_props(screen, view.keys_footer(self._phone_address(now)))
        props.update(view.chip_props(placed))
        for key, value in props.items():
            self._set(key, value)
        rows = view.step_rows(screen, view.KEYS_STEP_W)
        if rows != self._rows:
            self._rows = rows
            ui.fill_list(self, STEPS, [r.props() for r in rows], select=next((n for n, r in enumerate(rows) if r.state == "now"), 0))
        badges = view.badge_rows(screen)
        if badges != self._badges:
            self._badges = badges
            ui.fill_list(self, BADGES, badges)

    def _phone_address(self, now):
        if not self._address and now - self._address_at >= ADDRESS_RETRY:
            self._address_at = now
            self._address = onboarding_files.phone_address()
        return self._address

    def _move(self, placed):
        """Put the chip slots where layout_chips says; a slot that is not used keeps its place (its property is empty)."""
        bases = {"chip": (CHIP_IMAGE, CHIP_LABEL), "sep": (SEPARATOR,), "then": (THEN,)}
        spots = [(base + p.slot, AREA_X + p.x, AREA_Y + p.y, p.w) for p in placed for base in bases[p.kind]]
        for ident, x, y, width in spots + [(WARN, AREA_X, AREA_Y + view.warn_offset(placed), view.CHIP_AREA_W)]:
            try:
                control = self.getControl(ident)
                control.setPosition(x, y)
                control.setWidth(width)
            except RuntimeError as e:
                ui.log(f"cannot place control {ident}: {e!r}")

    def _set(self, key, value):
        if self._shown.get(key) != value:
            self._shown[key] = value
            self.setProperty(key, value)

    def onAction(self, action):
        if action.getId() in ui.BACK_ACTIONS:
            self.close()
        else:
            super().onAction(action)


def show(service, source, name=""):
    """The window over whatever is on screen, until the flow ends, the document is gone or Back is pressed."""
    window = ui.load(OnboardingDialog, XML)
    window.setup(service, source, name)
    window.doModal()
    window.stop()
    del window


def main(args):
    """Entry for `RunScript(script.media-stick.home,onboarding,show,<service>)` and `...,demo,signin|keys)`. True when a
    window was shown."""
    mode, what = (list(args) + ["", ""])[:2]
    home = xbmcgui.Window(ui.HOME)
    if home.getProperty(RUNNING):
        return False                         # already open (the wizard's card asks again at its next look)
    home.setProperty(RUNNING, "1")
    try:
        if mode == "demo" and what == "signin":
            from resources.lib import signin
            signin.run("youtube", attach=True, allow_skip=True,
                       source=onboarding_demo.SigninSource(onboarding_files.phone_qr()))
        elif mode == "demo" and what == "keys":
            show("youtube", onboarding_demo.KeysSource(), "YouTube")
        elif mode == "show" and store.onboarding is not None and what:
            show(what, LiveSource(), store.SERVICES.get(what, {}).get("name", what))
        else:
            ui.log(f"onboarding: nothing to show for {list(args)!r}")
            return False
    finally:
        home.setProperty(RUNNING, "")
    return True
