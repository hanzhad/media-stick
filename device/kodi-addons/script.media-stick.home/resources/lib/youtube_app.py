"""The YouTube app window: a section rail (100), a grid of video cards (200) and a card with one button (300) for
everything that is not a list of videos (not signed in, no Google key, nothing here, loading, an error, search).

  RunScript(script.media-stick.home,youtube,open)           the app, from the YouTube add-on's directories
  RunScript(script.media-stick.home,youtube,demo[,<what>])  the same screen on invented videos; plays nothing.
                                                            <what> is one of youtube_demo.SCENARIOS: the card shown instead of the list

A section is asked for with JSON-RPC Files.GetDirectory in a worker thread (youtube_files); the answer is parsed
(youtube_data) and shown, the UI is never held. Pictures are loaded by Kodi in the background. A listing is kept
for a few minutes so that going back to a section is instant. The first page of a section, a search or a playlist is also kept
on disk (page_cache, one namespace per profile, see youtube_pages): a page seen before shows at once even in the next launch,
a stale one is asked for again in the background and swapped in only if it changed, and right after the window opens the other
sections are fetched into it one at a time (prefetch). A long list loads its next page by itself, in a worker,
when the cursor comes within two rows of the last card. The thin Kodi part is here; the choices are in youtube_data
and what a card says is in youtube_cards.

A cold start (no page of the first section on disk or in memory, so the window would show an empty grid and a Loading card)
shows a splash instead, like the YouTube app on a set-top box: the window property `splash`, which the skin answers by hiding
everything else and drawing the mark, the word and a quiet line. It comes down when the first listing or card is shown,
whatever that card is (an error is never hidden), and in SPLASH_CAP seconds whatever happens. A warm start, and the demo
(but for its `loading` card), have none.
"""
import json
import os
import sys
import threading
import time
import zlib

import xbmc
import xbmcgui

_LIB_DIR = "/usr/local/lib/media-stick"
if os.path.isdir(_LIB_DIR) and _LIB_DIR not in sys.path:
    sys.path.insert(0, _LIB_DIR)

try:
    import mediastick_ui_context  # noqa: E402
    import panel_ui_context  # noqa: E402
except ImportError:
    mediastick_ui_context = None
    panel_ui_context = None

from resources.lib import (onboarding_view, profiles, single_instance, sweettv_text, ui, youtube_cards as cards, youtube_data as data,
                           youtube_demo, youtube_files as files, youtube_state as saved)
from resources.lib import page_cache, prefetch, quick_resume, youtube_pages as pages

XML = "script-media-stick-youtube.xml"
RAIL, AVATAR, GRID, ACTION = 100, 150, 200, 300
KIND_BUTTONS = {401 + n: kind.key for n, kind in enumerate(data.KINDS)}     # the row of choices above the results of a search
ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_PAGE_UP, ACTION_PAGE_DOWN = 1, 2, 3, 4, 5, 6
ACTION_CONTEXT_MENU = 117
MOVES = (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_PAGE_UP, ACTION_PAGE_DOWN)
COLUMNS = 4                      # the grid's columns (the panel in the skin)
AHEAD = 2 * COLUMNS              # the next page is asked for when the cursor is this close to the last card
MORE_RETRY = 8                   # s after a next page that failed before it is asked for again
LOADING_MORE = "Loading…"
CHANNEL_RECHECK = 5.0            # s until a card in a section of the account looks again at whether the account has a channel,
CHANNEL_TRIES = 3                # and how many times it does
KEYS_POLL = 2.0                  # s between looks at the key wizard's progress while its card is shown
PROFILE_POLL = 2.0               # s between looks at whether the add-on's current profile is still the one this window loaded with
DEMO_NAME, SIGNED_OUT_COLOR = "Demo", "FF5F5F5F"      # the avatar of the demo; of nobody
RAIL_DELAY = 0.3                 # s the rail rests on a section before the grid follows
RETURN_GRACE = 2                 # s: the window coming back sooner than this after Play is not a return from the player
RUNNING = "media-stick.youtube"  # Home window property while the app is open (single_instance): a live one blocks a second launch
FOCUS_POLL = 0.05                # s between looks at whether Kodi shows a control yet
FOCUS_WAIT = 2.0                 # s a worker waits for the control to be shown before it gives up
PAGES = True                     # the first pages are kept on disk (page_cache) and the sections are fetched at start-up (prefetch)
SPLASH_CAP = 15.0                # s the launch splash is up at most, whatever the first load is doing
NO_THUMB = os.path.join(ui.MEDIA, data.NO_THUMB)
DEMO_ART = f"{ui.ADDON_PATH}/resources/media/demo"
DEMO_NOTICE = "Demo: nothing is played."
DEMO_PICK_NOTICE = "Demo: no profile is switched."

_SECTION_LABELS = {
    "rec": "Рекомендации",
    "subs": "Подписки",
    "later": "Смотреть позже",
    "history": "История",
    "lists": "Плейлисты",
    "trend": "В тренде",
    data.SEARCH: "Поиск",
}
_KIND_LABELS = {
    data.KIND_VIDEO: "Видео",
    data.KIND_CHANNEL: "Каналы",
    data.KIND_PLAYLIST: "Плейлисты",
    data.KIND_LIVE: "Трансляции",
}
_SEARCH_HINT = "Поиск на YouTube"
_UI_CMD_METHOD = "Other.mediastick.ui_cmd"
_MonitorBase = getattr(xbmc, "Monitor", object)


def _build_ui_context(section: str, query: str, kind: str, searching: bool) -> dict:
    """Build the Pure Core UI context dict for YouTube."""
    sections = [{"id": s.key, "label": _SECTION_LABELS.get(s.key, s.name)} for s in data.SECTIONS]
    chips = (
        [{"id": k.key, "label": _KIND_LABELS.get(k.key, k.name), "active": k.key == kind} for k in data.KINDS]
        if searching
        else []
    )
    return {
        "app": "youtube",
        "view": "section",
        "section": section,
        "sections": sections,
        "chips": chips,
        "can_search": True,
        "search_query": query,
        "search_hint": _SEARCH_HINT,
        "modal": None,
    }


def _decode_ui_cmd(raw_data):
    """Parse and validate a Phone -> TV `ui_cmd` payload for YouTube; None when ignored or invalid."""
    if mediastick_ui_context is None:
        return None
    try:
        if isinstance(raw_data, str):
            if not raw_data.strip():
                return None
            payload = json.loads(raw_data)
            if isinstance(payload, str) and payload.strip():
                payload = json.loads(payload)
        elif isinstance(raw_data, dict):
            payload = raw_data
        else:
            return None
        cmd = mediastick_ui_context.validate_cmd(payload)
    except (ValueError, TypeError):
        return None
    return cmd if cmd.get("app") == "youtube" else None


def _notify_ui_context():
    """Emit optional wakeup JSONRPC.NotifyAll on a daemon thread only when xbmc.Monitor exists."""
    if getattr(xbmc, "Monitor", None) is None:
        return

    def _send():
        try:
            files.rpc("JSONRPC.NotifyAll", {
                "sender": "script.media-stick.home",
                "message": "mediastick.ui_context",
                "data": {},
            })
        except Exception:
            pass

    threading.Thread(target=_send, daemon=True).start()


def _write_ui_context(doc: dict) -> None:
    """Write `doc` to ui-context.json guarding missing module/directory/OSError, waking panel when changed."""
    if panel_ui_context is None or mediastick_ui_context is None:
        return
    try:
        changed = panel_ui_context.write_context(doc)
    except (OSError, ValueError, TypeError) as e:
        ui.log(f"ui-context write failed: {e!r}", xbmc.LOGWARNING)
        return
    if changed:
        _notify_ui_context()


def _clear_ui_context() -> None:
    if mediastick_ui_context is None:
        return
    _write_ui_context(mediastick_ui_context.empty_context())


class _UiCmdMonitor(_MonitorBase):
    """Persistent Monitor listener for Phone -> TV `Other.mediastick.ui_cmd` notifications."""

    def __init__(self, window):
        super().__init__()
        self._window = window

    def onNotification(self, sender, method, data):
        window = self._window
        if window is not None and method == _UI_CMD_METHOD:
            window._on_ui_cmd(data)


def _make_cmd_monitor(window):
    base = getattr(xbmc, "Monitor", None)
    if base is not None and base is not _MonitorBase:
        class _BoundUiCmdMonitor(base):
            def __init__(self, target):
                super().__init__()
                self._window = target

            def onNotification(self, sender, method, data):
                target = self._window
                if target is not None and method == _UI_CMD_METHOD:
                    target._on_ui_cmd(data)

        return _BoundUiCmdMonitor(window)
    return _UiCmdMonitor(window)


def clock():
    return time.time()


def playing():
    try:
        return xbmc.Player().isPlaying()
    except Exception:
        return False


class YouTube(xbmcgui.WindowXML):
    """Set up with setup() after construction: the Kodi window constructors take no extra arguments."""

    instance = None                              # the launch's single_instance flag; main() sets it

    def setup(self, demo=False, scenario=""):
        self.demo = demo
        self.scenario = scenario if demo and scenario in youtube_demo.SCENARIOS else ""
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._timers = {}
        self._window_props = {}
        self.started = False
        self.loads = 0                           # loads that have finished (a test waits on it)
        self.mode = ""
        self.state = saved.normalize_state({})
        self.routes = None                       # section key -> route found on the add-on's main page
        self.cache = {}                          # route -> (time, Listing)
        self.token = 0                           # the load whose answer is wanted: older answers are dropped
        self.view = None
        self.stack = []                          # (View, position) of the lists left to open a playlist
        self.listing = data.NO_LISTING
        self.entries = []                        # what the grid shows
        self.rail_items = []
        self.play_at = 0.0
        self.loading_more = 0                    # the token of the view whose next page is being asked for, 0 for none
        self.more_retry = 0.0                    # no next page is asked for before this time (a failed one waits)
        self.channel = "unknown"                 # whether the account has a YouTube channel (yes | no | unknown)
        self.profile = None                      # the id of the profile the window loaded with ("" none, None unknown)
        self.profile_known = False               # a load has said which profile that is: before it there is nothing to compare
        self._card = None                        # (mode, keys, detail) of the card shown, to say it again
        self._watching = False                   # a worker is looking at the key wizard's progress
        self._guide_up = False                   # the onboarding window was opened for the keys document now there
        self.refreshing = 0                      # shown pages from the disk cache that are being asked for again
        self.refresh_token = 0                   # the token of the view whose page was shown from the disk cache and is asked for again
        self.warming = None                      # the prefetch run (prefetch.Handle) of this profile
        self.splash = False                      # the launch splash is up (window property splash): a cold start, until the first page or card
        self._cmd_monitor = None

    def onInit(self):
        if self.instance is not None:
            self.instance.bind(xbmcgui.getCurrentWindowId())
        if self._cmd_monitor is None:
            self._cmd_monitor = _make_cmd_monitor(self)
        self._prop("demo", "1" if self.demo else "")
        self._prop("splash", "")
        if self.started:
            self._after_player()
            self._publish_ui_context()
            return
        self.started = True
        select = 0
        if not self.demo:
            self.state = saved.load_state(files.state_path())
            self.profile, self.profile_known = files.profile_id(), True    # the disk cache is the profile's: know it before the first look
            snap = quick_resume.load_snapshot("youtube", self.profile) if self._ns(self.profile) is not None else None
            if snap:
                has_state_file = os.path.exists(files.state_path())
                same_target = (snap.get("section") == self.state["section"]
                               and (snap.get("search_query") or "") == self.state["query"])
                if not has_state_file:
                    self.state = saved.apply_snapshot(self.state, snap)
                if not has_state_file or same_target:
                    select = max(0, int(snap.get("focused_index") or 0))
                    for item in snap.get("nav_stack") or ():
                        if isinstance(item, dict) and item.get("route"):
                            view = data.View(
                                item.get("key", ""),
                                item.get("route", ""),
                                item.get("title", ""),
                                item.get("kind", data.DEFAULT_KIND),
                                bool(item.get("needs_login", False)),
                            )
                            self.stack.append((view, max(0, int(item.get("pos") or 0))))
        self._set_avatar(None, "")
        self._fill_rail()
        self._navigate(data.section_view(self.state["section"], query=self.state["query"], kind=self.state["kind"]), focus=True,
                       select=select, launch=True)
        if not self.demo:
            self._later("profile", PROFILE_POLL, self._profile_tick)
            self._start_warm()                   # now, splash or not: it waits by itself (_idle) while the first page is asked for

    def _profile_tick(self):
        """On a timer: the window follows the add-on's current profile, as the phone does. A switch from the phone (or
        a sign-in that made a profile current) changes it behind the window's back: what the cache holds, the circle
        and the section were the other profile's. So a changed id clears the cache and the circle and loads the
        section again (a playlist opened from it is the other profile's too: the section it came from is shown).
        An id that cannot be told, or one the first load has not recorded yet, is not a change."""
        if self._stop.is_set():
            return
        try:
            now = files.profile_id(log=False)
            if now is not None and self.profile_known and now != self.profile:
                with self._lock:
                    self.profile = now
                    self.cache.clear()
                    self.channel = "unknown"
                    self._set_avatar(None, "")
                    view = self.stack[0][0] if self.stack else self.view
                    self.stack = []
                    self._cancel_warm()
                if view is not None:
                    self._navigate(view)
                    self._start_warm()
        finally:
            if not self._stop.is_set():
                self._later("profile", PROFILE_POLL, self._profile_tick)

    def stop(self):
        self._save_quick_resume(immediate=True)
        self._stop.set()
        if self._cmd_monitor is not None:
            self._cmd_monitor._window = None
            self._cmd_monitor = None
        self._cancel_warm()
        for timer in list(self._timers.values()):
            timer.cancel()
        if not self.demo and self.started:
            saved.save_state(files.state_path(), self.state)

    # -- the launch splash --

    def _splash_up(self):
        """A cold start: the splash instead of the empty grid and the Loading card, for SPLASH_CAP seconds at most. The demo
        loads nothing and has none, but for the card that never ends."""
        if self.demo and self.scenario != "loading":
            return
        with self._lock:
            self.splash = True
            self._prop("splash", "1")
            self._later("splash", SPLASH_CAP, self._splash_cap)

    def _end_splash(self):
        """Take the splash down; True when it was up. Called with the page or the card that replaces it already set."""
        with self._lock:
            if not self.splash:
                return False
            self.splash = False
            self._cancel("splash")
            self._prop("splash", "")
            return True

    def _splash_cap(self):
        """On a timer: the splash has been up for SPLASH_CAP seconds. The window shows what it has (the Loading card, or the
        page if it came a moment ago); the answer that comes later is shown as it would be."""
        if not self._stop.is_set() and self._end_splash():
            self._focus_after_splash(FOCUS_WAIT)

    def _focus_after_splash(self, wait=0.0):
        """The splash is down and nothing has the focus (the controls were hidden): where the window puts it, else the rail."""
        if self._wanted():
            self._focus_content(wait)
        else:
            self._focus_on(RAIL, wait)

    # -- asking for a list (worker thread) --

    def _navigate(self, view, focus=False, select=0, launch=False):
        """Show `view`: from the cache at once (the one in memory, else the first page kept on disk, even a stale one, which
        is then asked for again in the background), else a card says Loading and a worker asks the add-on. `launch` is the
        window's first look: when it finds nothing to show it is the splash that covers the Loading card."""
        self._cancel("rail")
        self._cancel("focus")
        stored = None
        dropped = False
        with self._lock:
            self.token += 1
            token, self.view = self.token, view
            self._prop("title", data.crumb(self.stack, view))
            self._prop("notice", "")
            self._prop("search", "1" if view.key == data.SEARCH else "")     # the row of choices is for a search only
            self._prop("kind", view.kind)
            self._mark_rail()
            if not launch:
                self._save_quick_resume()
            cached = self.cache.get(view.route)
            if not view.route:
                self._show_card(data.PROMPT)
                shown = True
            elif cached and data.fresh(cached[0], clock()):
                self._install(view, cached[1], self._prepare(cached[1]), select)
                shown = True
            elif (stored := self._stored(view)) is not None:
                self._install(view, stored[0], self._prepare(stored[0]), select)
                if stored[1]:
                    self.refreshing += 1
                    self.refresh_token = token
                shown = True
            else:
                self._show_card(data.LOADING)
                shown = False
                if launch:
                    self._splash_up()
            if shown:
                dropped = self._end_splash()
        if shown:
            if focus or dropped:
                self._focus_content()
            self._publish_ui_context()
            if stored is not None and stored[1]:
                threading.Thread(target=self._load, args=(token, view, False, select, stored[0]), daemon=True).start()
            else:
                self._more_when_near()
            return
        self._publish_ui_context()
        threading.Thread(target=self._load, args=(token, view, focus, select), daemon=True).start()

    def _load(self, token, view, focus, select, shown=None):
        """Ask the add-on for `view` and show the answer. `shown` is the page from the disk cache that is on screen while this
        asks again: a better answer replaces it, a failure leaves it."""
        signed = keys = gated = pid = None
        name = ""
        listing = data.NO_LISTING
        try:
            signed, keys, name = self._situation()
            pid = self.profile
            self.channel = "unknown" if self.demo or not signed else files.channel_state()
            gated = data.gate(signed, view.needs_login, keys)
            if gated is None:
                listing = data.parse_reply(self._reply(self._resolve(view)))
        except Exception as e:                   # never let a worker die silently with a Loading card up
            ui.log(f"YouTube load failed: {e!r}", xbmc.LOGERROR)
            listing = data.Listing((), "", "Something went wrong.")
        try:
            self._apply(token, view, (signed, name), keys, gated, listing, focus, select, shown)
            self._keep(view, listing, gated, pid)
        finally:
            self.loads += 1
            if shown is not None:
                with self._lock:
                    self.refreshing -= 1
                    if self.refresh_token == token:
                        self.refresh_token = 0
                self._more_when_near()           # held back while the page of the disk cache was being asked for again

    def _situation(self):
        """(signed in, Google key, the profile's name) as the add-on has them; the demo pretends."""
        if self.demo:
            situation = youtube_demo.situation(self.scenario)
            return situation.signed, situation.keys, DEMO_NAME
        self.profile, self.profile_known = files.profile_id(), True   # first: a switch during the questions below is seen by the next look
        signed = files.signed_in()
        return signed, files.keys_configured(), files.profile_name() if signed else ""

    def _reply(self, route):
        if self.demo:
            if self.scenario == "loading":
                self._stop.wait()                # the demo of the Loading card: it never ends
            return youtube_demo.reply(route, self.scenario, DEMO_ART, clock())
        return files.get_directory(route)

    def _resolve(self, view):
        """The route to ask for. A section's route is read once off the add-on's main page (data.discover_routes)."""
        if view.key in data.SECTION_KEYS and view.key != data.SEARCH:
            if self.routes is None:
                main = data.parse_reply(self._reply(data.ROOT))
                self.routes = data.discover_routes(main) if main.entries else None
            return (self.routes or {}).get(view.key) or view.route
        return view.route

    def _apply(self, token, view, account, keys, gated, listing, focus, select, shown=None):
        """Show the answer. With `shown` (the page of the disk cache on screen) a failed look changes nothing, an answer
        that is the same page changes nothing, a changed page replaces it with the cursor where it was, and a card (the
        section is empty now, or needs the sign-in) replaces it and drops the page from the cache."""
        prepared = None
        dropped = False
        mode = gated or data.mode_for(listing, keys)
        if shown is not None and mode in (data.ERROR, data.UNAVAILABLE):
            return
        if mode == data.DATA:
            prepared = self._prepare(listing)    # the slow part: no lock held
        with self._lock:
            if self._stop.is_set() or token != self.token:
                return
            self._set_avatar(*account)
            if shown is not None and prepared is not None:
                self._swap(view, shown, listing, prepared)
            elif prepared is not None:
                self._remember(view.route, listing)
                self._install(view, listing, prepared, select)
            else:
                if shown is not None:
                    self._forget(view)
                self._show_card(mode, keys, listing.error)
                self._watch_channel(view, token, mode)
            dropped = self._end_splash()         # the page or the card (an error, a sign-in: any) is set: nothing covers it now
        if dropped:
            self._focus_after_splash(FOCUS_WAIT)
        elif focus:
            self._focus_content(FOCUS_WAIT)
        if prepared is not None:
            self._more_when_near()

    def _swap(self, view, shown, listing, prepared):
        """The fresh first page where the one from the disk cache is on screen: only when the window still shows that very
        page (no next page was added to it) and the new one differs. The cursor stays on its position, the focus on the grid."""
        if self.listing is not shown:
            return
        self._remember(view.route, listing)
        if (listing.entries, listing.more) == (shown.entries, shown.more):
            return
        try:
            position = self.getControl(GRID).getSelectedPosition()
        except RuntimeError:
            position = 0
        grid_focused = self._focus() == GRID
        self._install(view, listing, prepared, max(0, min(position, len(prepared[0]) - 1)))
        if grid_focused:
            self._focus_on(GRID)

    def _set_avatar(self, signed, name):
        """The account's circle at the top right: the first letter of the profile's name on a colour taken from the
        name; a grey question mark when signed out; none while it is not known."""
        if self.demo:
            signed, name = youtube_demo.situation(self.scenario).signed, DEMO_NAME
        letter, color = "", ""
        if signed:
            letter = profiles.initial(name or "")
            color = profiles.PALETTE[zlib.crc32((name or "").encode("utf-8")) % len(profiles.PALETTE)]
        elif signed is not None:
            letter, color = "?", SIGNED_OUT_COLOR
        self._prop("signed", "" if signed is None else "1" if signed else "0")
        self._prop("avatar", letter)
        self._prop("avatar_color", color)

    # -- the first pages kept on disk (page_cache), fetched at start-up (prefetch) --

    def _ns(self, profile):
        """The namespace the disk cache keeps a profile's pages in; None when nothing is kept (the demo, the cache switched
        off, a profile that is not known)."""
        return pages.namespace(profile) if PAGES and not self.demo else None

    def _stored(self, view):
        """(Listing, stale) of the first page of `view` on disk; None for no page, an old one or a damaged one."""
        ns = self._ns(self.profile)
        if ns is None or not view.route:
            return None
        hit = page_cache.get(ns, pages.key_of(view), pages.ttl_of(view), pages.max_age_of(view), now=clock())
        listing = pages.from_value(hit.value) if hit else None
        return (listing, hit.stale) if listing else None

    def _keep(self, view, listing, gated, pid):
        """A first page the add-on answered with cards goes to the disk cache, under the profile it was asked for: not an
        error, an empty list, the sign-in or the key card."""
        ns = self._ns(pid)
        if ns is None or gated or not view.route or listing.error or not listing.entries:
            return
        if files.profile_id(log=False) not in (None, pid):       # the profile was switched while this was asked for
            return
        page_cache.put(ns, pages.key_of(view), pages.to_value(listing), now=clock())

    def _forget(self, view):
        ns = self._ns(self.profile)
        if ns is not None:
            page_cache.remove(ns, pages.key_of(view))

    def _start_warm(self):
        """Right after the window opens: the first pages of the other sections are fetched in the background and kept on disk
        (prefetch: one at a time, at a low priority, only while the window asks for nothing itself), so that the section
        the user goes to next is there already."""
        pid = self.profile
        ns = self._ns(pid)
        if ns is None or self.view is None:
            return
        views = [data.section_view(key, self.routes) for key in pages.warm_keys(self.view.key)]
        jobs = [(pages.key_of(v), lambda v=v: self._warm_page(v, pid)) for v in views]
        self.warming = prefetch.warm(ns, jobs, ttl=pages.PAGE_TTL, idle=self._idle)

    def _cancel_warm(self):
        warming, self.warming = self.warming, None
        if warming is not None:
            warming.cancel()

    def _idle(self):
        """Whether the window is waiting for nothing: no Loading card, no page being asked for again, no next page."""
        return not self._stop.is_set() and not playing() and self.mode not in ("", data.LOADING) and not self.refreshing and not self.loading_more

    def _save_quick_resume(self, immediate=False):
        if self.demo or not self.started or self._ns(self.profile) is None:
            return
        try:
            pos = max(0, self.getControl(GRID).getSelectedPosition())
        except Exception:
            pos = 0
        snap = quick_resume.build_youtube_snapshot(
            section=self.state.get("section", data.DEFAULT_SECTION),
            query=self.state.get("query", ""),
            kind=self.state.get("kind", data.DEFAULT_KIND),
            stack=self.stack,
            focused_index=pos,
            cards=[list(e) for e in self.entries[:24]],
        )
        quick_resume.save_snapshot(
            "youtube",
            self.profile,
            snap,
            debounce_s=0.0 if immediate else quick_resume.DEBOUNCE_S,
        )

    def _warm_page(self, view, pid):
        """The job of one section: its first page as page_cache keeps it, None when there is nothing worth keeping."""
        if files.profile_id(log=False) != pid or data.gate(files.signed_in(), view.needs_login, files.keys_configured()):
            return None
        listing = data.parse_reply(self._reply(self._resolve(view)))
        if listing.error or not listing.entries or files.profile_id(log=False) != pid:
            return None
        return pages.to_value(listing)

    def _remember(self, route, listing):
        self.cache[route] = (clock(), listing)
        while len(self.cache) > data.CACHE_SIZE:
            self.cache.pop(min(self.cache, key=lambda r: self.cache[r][0]))

    # -- the controls --

    def _prop(self, key, value):
        if self._window_props.get(key) != value:
            self._window_props[key] = value
            self.setProperty(key, value)

    def _focus(self):
        try:
            return self.getFocusId()
        except RuntimeError:
            return 0

    @staticmethod
    def _shown(control_id):
        """Whether Kodi has made the control visible: a property set from here shows a control a frame later."""
        try:
            return bool(xbmc.getCondVisibility(f"Control.IsVisible({control_id})"))
        except Exception:
            return True

    def _wanted(self):
        """The control the content is on: the grid when there are cards, else the card's button when it has one."""
        if self.mode == data.DATA and self.entries:
            return GRID
        return ACTION if self._window_props.get("action") else 0

    def _focus_on(self, control_id, wait=0.0):
        """Focus a control once Kodi shows it, looking again for up to `wait` seconds. Asking earlier does nothing
        and only logs "asked to focus, but it can't". True when the focus is there."""
        end = time.monotonic() + wait
        while True:
            if self._shown(control_id):
                try:
                    self.setFocusId(control_id)
                    if self.getFocusId() == control_id:
                        return True
                except RuntimeError:
                    pass
            if time.monotonic() >= end or self._stop.is_set():
                return False
            xbmc.sleep(int(FOCUS_POLL * 1000))

    def _focus_content(self, wait=0.0):
        """Focus what the window shows now. A worker passes `wait` and waits for Kodi to show it; the UI thread
        must not wait (Kodi shows the control only when that thread returns to it) and asks again from a timer."""
        control_id = self._wanted()
        if control_id and not self._focus_on(control_id, wait) and not wait:
            self._later("focus", FOCUS_POLL, self._focus_late)

    def _focus_late(self):
        control_id = self._wanted()
        if control_id:
            self._focus_on(control_id, FOCUS_WAIT)

    def _fill_rail(self):
        self.rail_items = [self._rail_item(entry) for entry in data.rail()]
        control = self.getControl(RAIL)
        control.reset()
        control.addItems(self.rail_items)

    @staticmethod
    def _rail_item(entry):
        item = xbmcgui.ListItem(entry.name, offscreen=True)
        item.setProperty("icon", entry.key)                  # the skin draws youtube-icon-<key>.png
        return item

    def _mark_rail(self):
        """The section the view belongs to is marked, and the rail's cursor goes to it."""
        key = (self.stack[0][0] if self.stack else self.view).key
        key = data.SEARCH if key == data.FOLDER_KEY else key
        for entry, item in zip(data.rail(), self.rail_items):
            item.setProperty("active", "1" if entry.key == key else "")
        if self._focus() != RAIL:
            self.getControl(RAIL).selectItem(data.SECTION_KEYS.index(key) if key in data.SECTION_KEYS else 0)

    def _set_mode(self, mode):
        self.mode = mode
        self._prop("mode", mode)
        if mode == data.NEEDKEY:
            self._start_keys_watch()
        else:
            self._show_step(None)                # the wizard's block is only for its own card

    def _publish_ui_context(self):
        if self._stop.is_set() or panel_ui_context is None or mediastick_ui_context is None:
            return
        with self._lock:
            if self._stop.is_set():
                return
            root_view = self.stack[0][0] if self.stack else self.view
            section = root_view.key if root_view is not None else self.state.get("section", data.DEFAULT_SECTION)
            if section == data.FOLDER_KEY:
                section = self.state.get("section", data.DEFAULT_SECTION)
            searching = self._searching()
            query = self.state.get("query", "")
            kind = self.view.kind if searching and self.view is not None else self.state.get("kind", data.DEFAULT_KIND)
        _write_ui_context(_build_ui_context(section, query, kind, searching))

    def _on_ui_cmd(self, raw_data):
        if self._stop.is_set():
            return
        cmd = _decode_ui_cmd(raw_data)
        if cmd is None:
            return
        threading.Thread(target=self._dispatch_ui_cmd, args=(cmd,), daemon=True).start()

    def _dispatch_ui_cmd(self, cmd):
        with self._lock:
            if self._stop.is_set():
                return
            action = cmd.get("cmd")
            if action == "set_section":
                section = cmd.get("section", "")
                if section not in data.SECTION_KEYS:
                    return
                self.stack = []
                self.state = saved.remember_section(self.state, section)
                view = data.section_view(section, self.routes, self.state["query"], self.state["kind"])
                if not self.demo:
                    saved.save_state(files.state_path(), self.state)
                self._navigate(view, focus=True)
            elif action == "set_filter":
                kind = cmd.get("id", "")
                if kind not in data.KIND_KEYS:
                    return
                self._choose_kind(kind)
            elif action == "search":
                self._run_search(cmd.get("query", ""))
            elif action == "play":
                entry = self._selected()
                if entry is not None:
                    if entry.kind == data.VIDEO:
                        self._play(entry)
                    elif entry.kind == data.FOLDER:
                        self.stack.append((self.view, self.getControl(GRID).getSelectedPosition()))
                        self._navigate(data.folder_view(entry), focus=True)

    def _show_card(self, mode, keys=None, detail=""):
        """Everything that is not a list: the grid is emptied and the card says why."""
        message = data.message(mode, self.view, keys, detail, self.channel)
        self._card = (mode, keys, detail)
        self.entries, self.listing = [], data.NO_LISTING
        self.getControl(GRID).reset()
        self._prop("msg_title", message.title)
        self._prop("msg_text", message.text)
        self._prop("action", message.action)
        self._set_mode(mode)

    def _watch_channel(self, view, token, mode, tries=CHANNEL_TRIES):
        """A card for an empty section of the account, shown before it was known whether the account has a channel: look
        again a few times, so the card says it when the answer comes (the library asks Google in the background)."""
        if (tries and not self.demo and self.channel == "unknown" and view.key in data.NEEDS_CHANNEL
                and mode in (data.EMPTY, data.ERROR, data.UNAVAILABLE)):
            self._later("channel", CHANNEL_RECHECK, lambda: self._recheck_channel(view, token, tries - 1))

    def _recheck_channel(self, view, token, tries):
        channel = files.channel_state()
        with self._lock:
            if self._stop.is_set() or token != self.token or self._card is None:
                return
            self.channel = channel
            if data.no_channel(view, self._card[0], channel):
                self._show_card(*self._card)
            else:
                self._watch_channel(view, token, self._card[0], tries)

    def _prepare(self, listing):
        """(entries, ListItems) for a listing: one card for each entry."""
        entries = list(listing.entries)
        return entries, self._items(entries)

    def _items(self, entries):
        now = clock()
        return [self._item(entry, now) for entry in entries]

    @staticmethod
    def _item(entry, now):
        item = xbmcgui.ListItem(entry.title, offscreen=True)
        item.setArt({"thumb": entry.thumb or NO_THUMB})     # no picture: the plate, never an empty tile
        for key, value in cards.card_props(entry, now).items():
            item.setProperty(key, value)
        return item

    def _install(self, view, listing, prepared, select=0):
        self.listing = listing
        self.entries, items = prepared
        control = self.getControl(GRID)
        control.reset()
        control.addItems(items)
        control.selectItem(select if 0 <= select < len(items) else 0)
        self._prop("action", "")
        self._set_mode(data.DATA)

    # -- the "Set up your Google key" card: the phone page's address as a QR and how far the wizard has got --

    def _start_keys_watch(self):
        with self._lock:
            if self._watching or self._stop.is_set():
                return
            self._watching = True
        threading.Thread(target=self._watch_keys, daemon=True).start()

    def _watch_keys(self):
        """In a worker, once in KEYS_POLL seconds while the card is shown: the QR (until there is one) and the step."""
        try:
            while not self._stop.is_set() and self.mode == data.NEEDKEY:
                try:
                    self._look_at_keys()
                except Exception as e:           # a look that fails is tried again at the next one
                    ui.log(f"key wizard look failed: {e!r}", xbmc.LOGERROR)
                self._stop.wait(KEYS_POLL)
        finally:
            with self._lock:
                self._watching = False
                again = self.mode == data.NEEDKEY and not self._stop.is_set()
            if again:                            # the card was left and came back while this one was ending
                self._start_keys_watch()

    def _look_at_keys(self):
        if not self._window_props.get("key_qr"):
            url, qr = files.phone_page()
            self._prop("key_url", sweettv_text.short_url(url))
            self._prop("key_qr", qr)
        guide = None if self.demo else files.read_keys_guide()
        self._open_guide(guide)
        step = onboarding_view.card_step(guide) or self._step()      # the onboarding document first, the step file after
        if self.mode == data.NEEDKEY:            # the card may have been left while the file was read
            self._show_step(step)

    def _open_guide(self, guide):
        """The phone's key wizard has a document: the TV shows it big in the onboarding window over this card, once for
        each wizard (Back closes it and it stays closed until the wizard is over and a new one starts)."""
        if guide is None:
            self._guide_up = False
        elif not self._guide_up:
            self._guide_up = True
            xbmc.executebuiltin("RunScript(script.media-stick.home,onboarding,show,youtube)")

    def _step(self):
        if self.demo:                            # the demo shows a step in the phone page's own (Russian) words
            now = clock()
            return data.parse_step({**youtube_demo.KEY_STEP, "updated": now}, now)
        return files.read_step(clock())

    def _show_step(self, step):
        heading, first, second = cards.step_lines(step)
        self._prop("step", heading)
        self._prop("step_hint1", first)
        self._prop("step_hint2", second)

    def _selected(self):
        try:
            position = self.getControl(GRID).getSelectedPosition()
        except RuntimeError:
            return None
        return self.entries[position] if 0 <= position < len(self.entries) else None

    # -- keys --

    def onAction(self, action):
        action_id = action.getId()
        if action_id in ui.BACK_ACTIONS:
            if not self._back():
                self.close()
            return
        if action_id == ACTION_CONTEXT_MENU:
            if not self.splash and self.mode:
                if self._focus() == RAIL:
                    self._focus_content()
                else:
                    self._focus_on(RAIL, 0)
            return
        if action_id == ACTION_MOVE_RIGHT and self._focus() == RAIL and self.mode != data.DATA:
            self._focus_content()                # no grid to go to: the card's button
            return
        if self._kind_move(action_id):
            return
        super().onAction(action)
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and self._focus() == RAIL:
            self._later("rail", RAIL_DELAY, self._rail_rested)
        elif action_id in MOVES and self._focus() == GRID:
            self._more_when_near()

    def onClick(self, control_id):
        try:
            if control_id == GRID:
                self._open_card()
            elif control_id == RAIL:
                self._cancel("rail")
                self._choose_section(commit=True)
            elif control_id == ACTION:
                self._act()
            elif control_id == AVATAR:
                self._pick_profile()
            elif control_id in KIND_BUTTONS:
                self._choose_kind(KIND_BUTTONS[control_id])
        except Exception as e:                   # never let a click kill the window
            ui.log(f"click {control_id} failed: {e!r}", xbmc.LOGERROR)

    def _later(self, name, delay, function):
        """Run `function` once after `delay`; asking again for the same `name` starts the wait over."""
        self._cancel(name)
        timer = threading.Timer(delay, self._timed, args=(function,))
        timer.daemon = True
        self._timers[name] = timer
        timer.start()

    def _cancel(self, name):
        timer = self._timers.pop(name, None)
        if timer is not None:
            timer.cancel()

    @staticmethod
    def _timed(function):
        try:
            function()
        except Exception as e:
            ui.log(f"timer failed: {e!r}")

    def _rail_rested(self):
        self._choose_section(commit=False)

    # -- what OK and Back do --

    def _choose_section(self, commit):
        position = self.getControl(RAIL).getSelectedPosition()
        if not 0 <= position < len(data.SECTIONS):
            return
        key = data.SECTIONS[position].key
        if key == data.SEARCH and commit:
            self._search()
            return
        with self._lock:
            same = not self.stack and self.view is not None and self.view.key == key
            if not same:
                self.stack = []
                self.state = saved.remember_section(self.state, key)
            view = data.section_view(key, self.routes, self.state["query"], self.state["kind"])
        if same and self.mode == data.DATA:
            if commit:
                self._focus_content()
        elif not same or commit:
            self._navigate(view, focus=commit)

    def _back(self):
        """Back out of a playlist to the list it was opened from; False when there is nowhere to go (leave the app)."""
        with self._lock:
            if not self.stack:
                return False
            view, position = self.stack.pop()
        self._navigate(view, focus=True, select=position)
        return True

    def _open_card(self):
        entry = self._selected()
        if entry is None:
            return
        if entry.kind == data.VIDEO:
            self._play(entry)
        elif entry.kind == data.FOLDER:
            with self._lock:
                self.stack.append((self.view, self.getControl(GRID).getSelectedPosition()))
            self._navigate(data.folder_view(entry), focus=True)

    def _more_when_near(self):
        """Ask for the next page once the cursor is within AHEAD cards of the last one (or the cards do not fill the
        screen yet), in a worker; one page at a time, and a page that failed is tried again after MORE_RETRY seconds."""
        with self._lock:
            if self._stop.is_set() or self.mode != data.DATA or not self.listing.more or self.loading_more == self.token:
                return
            if self.refresh_token == self.token:     # the first page is from the disk cache: its next page may be old too
                return
            if clock() < self.more_retry:
                return
            try:
                position = self.getControl(GRID).getSelectedPosition()
            except RuntimeError:
                return
            if position < len(self.entries) - AHEAD:
                return
            self.loading_more = token = self.token
            route = self.listing.more
        self._prop("notice", LOADING_MORE)
        threading.Thread(target=self._load_more, args=(token, route), daemon=True).start()

    def _load_more(self, token, route):
        """The next page, added after the cards shown; the cursor stays where it is. A failure is silent: the cards
        shown stay, the page is asked for again a little later."""
        try:
            page = data.parse_reply(self._reply(route))
        except Exception as e:
            ui.log(f"next page failed: {e!r}", xbmc.LOGERROR)
            page = data.Listing((), "", "Something went wrong.")
        try:
            self._added(token, page)
        finally:
            with self._lock:
                if self.loading_more == token:
                    self.loading_more = 0
                    self._prop("notice", "")
        self._more_when_near()                   # still near the end (a short page)? the next one

    def _added(self, token, page):
        with self._lock:
            if self._stop.is_set() or token != self.token:
                return
            if page.error:
                self.more_retry = clock() + MORE_RETRY
                return
            before = len(self.entries)
            merged = data.merge(self.listing, page)
            fresh = list(merged.entries[before:])
            items = self._items(fresh)
            self.listing = merged
            self.entries = list(merged.entries)
            self.getControl(GRID).addItems(items)              # appended: the grid does not jump
            self._remember(self.view.route, merged)

    def _play(self, entry):
        if self.demo:
            ui.notify(DEMO_NOTICE)
            return
        path = data.play_path(entry)
        if path:
            self.play_at = clock()
            files.play(path)

    def _after_player(self):
        """Back from the player: the video is stopped, so no sound runs behind a list with no picture."""
        if self.play_at and clock() - self.play_at > RETURN_GRACE:
            self.play_at = 0.0
            if playing():
                xbmc.Player().stop()

    def _run_search(self, raw_query):
        text = data.clean_query(raw_query)
        if not text:
            return
        with self._lock:
            if self._stop.is_set():
                return
            self.stack = []
            self.state = saved.record_query(self.state, text)
            view = data.section_view(data.SEARCH, query=text, kind=self.state["kind"])
        if not self.demo:
            saved.save_state(files.state_path(), self.state)
        self._navigate(view, focus=True)

    def _search(self):
        self._run_search(xbmcgui.Dialog().input("Search YouTube", defaultt=self.state["query"]))

    def _searching(self):
        """Whether the search is what the window shows (its row of choices is there); a folder opened from it is not."""
        return self.view is not None and self.view.key == data.SEARCH

    def _kind_move(self, action_id) -> bool:
        """Up from the first row of the results (or from the card's button) goes to the chosen type, Down from a type goes
        back to the results; the rest of the row is moved by the skin. True when the key was taken here."""
        focus = self._focus()
        if action_id == ACTION_MOVE_UP and self._searching() and (focus == ACTION or focus == GRID and self._first_row()):
            self._focus_on(next(button for button, kind in KIND_BUTTONS.items() if kind == self.state["kind"]))
            return True
        if action_id == ACTION_MOVE_UP and focus in KIND_BUTTONS:        # the skin has already moved the focus here: nothing is above
            return True
        if action_id == ACTION_MOVE_DOWN and focus in KIND_BUTTONS:
            self._focus_content()
            return True
        return False

    def _first_row(self):
        try:
            return 0 <= self.getControl(GRID).getSelectedPosition() < COLUMNS
        except RuntimeError:
            return False

    def _choose_kind(self, kind):
        """OK on a type: the current query is asked again for it. The focus stays on the row, so that the types can be tried
        one after another; Down goes to the results. The same type again only goes to the results."""
        with self._lock:
            if not self._searching():
                return
            changed = kind != self.state["kind"]
            self.state = saved.remember_kind(self.state, kind)
            view = data.section_view(data.SEARCH, query=self.state["query"], kind=kind)
        if changed:
            self._navigate(view)
        else:
            self._focus_content()

    def _act(self):
        """The card's button: sign in, search, or ask again."""
        view = self.view
        if self.mode == data.SIGNIN:
            self._signin()
        elif self.mode == data.PROMPT or (self.mode == data.EMPTY and view.key == data.SEARCH):
            self._search()
        elif view is not None:
            with self._lock:
                self.cache.pop(view.route, None)
                self._forget(view)
                self.routes = None               # the main page is read again too
            self._navigate(view, focus=True)

    def _signin(self):
        """Run the existing sign-in screen; when it ends, ask again."""
        if self.demo:
            ui.notify("Demo: nothing is signed in.")
            return
        from resources.lib import accounts
        accounts.signin_service("youtube")
        self._navigate(self.view, focus=True)

    def _pick_profile(self):
        """OK on the account's circle: the "Who's watching" picker, the one the Accounts screen has (it switches the add-on to
        the profile picked). The window then follows the add-on's current profile at once (the timer's look, so the cache
        and the circle are the new profile's); a profile with no account is offered the sign-in, with a way past it."""
        if self.demo:
            ui.notify(DEMO_PICK_NOTICE)
            return
        from resources.lib import accounts
        profile = accounts.choose_profile()
        if profile is None:
            return
        self._profile_tick()
        if accounts.after_pick(profile) != accounts.LAUNCH:
            accounts.signin_service("youtube", allow_skip=True)
            self._navigate(self.view, focus=True)


def main(args):
    """Entry for `RunScript(script.media-stick.home,youtube,open|demo[,scenario])`. True when the window was shown."""
    instance = single_instance.claim(xbmcgui.Window(ui.HOME), RUNNING)
    if instance is None:
        return False                             # already open (a double press on the card)
    window = None
    try:
        demo = bool(args) and args[0] == "demo"
        window = ui.load(YouTube, XML)
        window.instance = instance
        window.setup(demo=demo, scenario=args[1] if demo and len(args) > 1 else "")
        window.doModal()
    finally:
        if window is not None:
            try:
                window.stop()
            finally:
                window._cmd_monitor = None
        _clear_ui_context()
        instance.release()
    return True
