"""The YouTube app window: a section rail (100), a grid of video cards (200) and a card with one button (300) for
everything that is not a list of videos (not signed in, no Google key, nothing here, loading, an error, search).

  RunScript(script.media-stick.home,youtube,open)           the app, from the YouTube add-on's directories
  RunScript(script.media-stick.home,youtube,demo[,<what>])  the same screen on invented videos; plays nothing.
                                                            <what> is one of youtube_demo.SCENARIOS: the card shown instead of the list

A section is asked for with JSON-RPC Files.GetDirectory in a worker thread (youtube_files); the answer is parsed
(youtube_data) and shown, the UI is never held. Pictures are loaded by Kodi in the background. A listing is kept
for a few minutes so that going back to a section is instant. A long list loads its next page by itself, in a worker,
when the cursor comes within two rows of the last card. The thin Kodi part is here; the choices are in youtube_data
and what a card says is in youtube_cards.
"""
import os
import threading
import time
import zlib

import xbmc
import xbmcgui

from resources.lib import (onboarding_view, profiles, single_instance, sweettv_text, ui, youtube_cards as cards, youtube_data as data,
                           youtube_demo, youtube_files as files, youtube_state as saved)

XML = "script-media-stick-youtube.xml"
RAIL, GRID, ACTION = 100, 200, 300
ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_PAGE_UP, ACTION_PAGE_DOWN = 1, 2, 3, 4, 5, 6
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
NO_THUMB = os.path.join(ui.MEDIA, data.NO_THUMB)
DEMO_ART = f"{ui.ADDON_PATH}/resources/media/demo"
DEMO_NOTICE = "Demo: nothing is played."


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

    def onInit(self):
        if self.instance is not None:
            self.instance.bind(xbmcgui.getCurrentWindowId())
        self._prop("demo", "1" if self.demo else "")
        if self.started:
            self._after_player()
            return
        self.started = True
        if not self.demo:
            self.state = saved.load_state(files.state_path())
        self._set_avatar(None, "")
        self._fill_rail()
        self._navigate(data.section_view(self.state["section"], query=self.state["query"]), focus=True)
        if not self.demo:
            self._later("profile", PROFILE_POLL, self._profile_tick)

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
                if view is not None:
                    self._navigate(view)
        finally:
            if not self._stop.is_set():
                self._later("profile", PROFILE_POLL, self._profile_tick)

    def stop(self):
        self._stop.set()
        for timer in list(self._timers.values()):
            timer.cancel()
        if not self.demo and self.started:
            saved.save_state(files.state_path(), self.state)

    # -- asking for a list (worker thread) --

    def _navigate(self, view, focus=False, select=0):
        """Show `view`: from the cache at once, else a card says Loading and a worker asks the add-on."""
        self._cancel("rail")
        self._cancel("focus")
        with self._lock:
            self.token += 1
            token, self.view = self.token, view
            self._prop("title", data.crumb(self.stack, view))
            self._prop("notice", "")
            self._mark_rail()
            cached = self.cache.get(view.route)
            if not view.route:
                self._show_card(data.PROMPT)
                shown = True
            elif cached and data.fresh(cached[0], clock()):
                self._install(view, cached[1], self._prepare(cached[1]), select)
                shown = True
            else:
                self._show_card(data.LOADING)
                shown = False
        if shown:
            if focus:
                self._focus_content()
            self._more_when_near()
            return
        threading.Thread(target=self._load, args=(token, view, focus, select), daemon=True).start()

    def _load(self, token, view, focus, select):
        signed = keys = gated = None
        name = ""
        listing = data.NO_LISTING
        try:
            signed, keys, name = self._situation()
            self.channel = "unknown" if self.demo or not signed else files.channel_state()
            gated = data.gate(signed, view.needs_login, keys)
            if gated is None:
                listing = data.parse_reply(self._reply(self._resolve(view)))
        except Exception as e:                   # never let a worker die silently with a Loading card up
            ui.log(f"YouTube load failed: {e!r}", xbmc.LOGERROR)
            listing = data.Listing((), "", "Something went wrong.")
        try:
            self._apply(token, view, (signed, name), keys, gated, listing, focus, select)
        finally:
            self.loads += 1

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

    def _apply(self, token, view, account, keys, gated, listing, focus, select):
        prepared = None
        mode = gated or data.mode_for(listing, keys)
        if mode == data.DATA:
            prepared = self._prepare(listing)    # the slow part: no lock held
        with self._lock:
            if self._stop.is_set() or token != self.token:
                return
            self._set_avatar(*account)
            if prepared is not None:
                self._remember(view.route, listing)
                self._install(view, listing, prepared, select)
            else:
                self._show_card(mode, keys, listing.error)
                self._watch_channel(view, token, mode)
        if focus:
            self._focus_content(FOCUS_WAIT)
        if prepared is not None:
            self._more_when_near()

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
        if action_id == ACTION_MOVE_RIGHT and self._focus() == RAIL and self.mode != data.DATA:
            self._focus_content()                # no grid to go to: the card's button
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
            view = data.section_view(key, self.routes, self.state["query"])
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

    def _search(self):
        text = data.clean_query(xbmcgui.Dialog().input("Search YouTube", defaultt=self.state["query"]))
        if not text:
            return
        with self._lock:
            self.stack = []
            self.state = saved.record_query(self.state, text)
        if not self.demo:
            saved.save_state(files.state_path(), self.state)
        self._navigate(data.section_view(data.SEARCH, query=text), focus=True)

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


def main(args):
    """Entry for `RunScript(script.media-stick.home,youtube,open|demo[,scenario])`. True when the window was shown."""
    instance = single_instance.claim(xbmcgui.Window(ui.HOME), RUNNING)
    if instance is None:
        return False                             # already open (a double press on the card)
    try:
        demo = bool(args) and args[0] == "demo"
        window = ui.load(YouTube, XML)
        window.instance = instance
        window.setup(demo=demo, scenario=args[1] if demo and len(args) > 1 else "")
        window.doModal()
        window.stop()
        del window
    finally:
        instance.release()
    return True
