"""The SWEET.TV app window, laid out like the launcher: a full-screen backdrop in the colour of the focused channel,
a row of channel cards along the bottom, a narrow category menu on the left, and over the row what the focused
channel is showing now (title, times, progress, description, what comes next, badges, and the buttons for the
programme guide and for continuing an archived programme). Also a sign-in card and, when there is nothing to
show, a status card (loading, empty, error) with a retry button.

  RunScript(script.media-stick.home,sweettv,open)    the app, from the plugin's channel list
  RunScript(script.media-stick.home,sweettv,demo)    the same screen on invented channels; plays nothing

Three screens inside the window (the property `screen`), then the cards for signing in and for waiting:
  home      the choice of Channels, Shows and series, Films: three cards (500). OK opens one; Back closes the app.
  channels  the channel screen below: the genres of SWEET.TV are its menu. Back returns to the choice.
  list      one list (600) for the shows, the episodes of a show and the films (sweettv_sections): OK on a show opens its
            episodes, OK on an episode or a film plays it from its start in the archive (one that is not on air yet, or not
            in the archive, says so). Back goes up one step: episodes to shows, shows or films to the choice.

Focus: the cards (500), the list (600), the menu (100), the row (200), the buttons over the row (210 continue, 211 guide),
the guide's list (400). The menu's up/down changes the row to that category's channels; right goes into the row, left
from its first card back. The channels open on "Continue" (the channels watched last, the last one first and focused) or,
with nothing watched yet, on "All".

The shows and the films are made from the same channel list as the phone page makes them (mediastick_sweetsections), by a
Library that reads the file when a list is opened (on a worker thread; "Loading..." is shown meanwhile) and lets the index
go two minutes after the lists are left.

The lists that were made are also kept on disk (page_cache, namespace "sweettv:main", see sweettv_pages): a list seen before
shows at once, even in the next launch; one older than five minutes is made again in the background and swapped in only if
the person is still on it and it changed (the cursor stays on its line); a list that cannot be made leaves the one on screen,
a section that is empty now drops its page. Right after the catalog is shown the shows and the films are made one after the
other (prefetch, at a low priority, only while nothing is loading and no video plays), so that their counts are on the cards and
their lists are there when the person gets to them. Signed out, the pages of the account go. The channels are not kept: they are
the file the plugin keeps already.

The channels come from special://temp/channelList.json, which the SWEET.TV plugin writes while it is
signed in (sweettv_data describes it). The file is read and parsed off the UI thread, once per change of
its mtime/size. What is on now and next is worked out from the clock, so a minute's tick refreshes the cards.
The state (favourites, recent, places in the archive) is written by sweettv_writer's thread, Player.Open and the
watch of the player run on worker threads. The thin Kodi part is here; the choices are in sweettv_data and
sweettv_view, the words in sweettv_text, the number keys in sweettv_jump, the guide in sweettv_guide, the
streams in sweettv_play.
"""
import os
import threading
import time

import xbmc
import xbmcgui

from resources.lib import page_cache, prefetch, single_instance, sweettv_data as data, sweettv_demo, sweettv_files as files, \
    sweettv_items as items, sweettv_pages as pages, sweettv_play as play, sweettv_sections as sections, sweettv_state as saved, \
    sweettv_text as words, sweettv_view as view, ui
from resources.lib.sweettv_guide import GUIDE, GUIDE_BUTTON, Guide
from resources.lib.sweettv_jump import DigitJump
from resources.lib.sweettv_writer import StateWriter

XML = "script-media-stick-sweettv.xml"
MENU, ROW, ACTIONS, RESUME = 100, 200, 209, 210          # the buttons over the row are the group 209: 210, 211
SIGNIN_BUTTON, RETRY = 300, 301
SECTIONS, ITEMS = 500, 600       # the three cards of the first screen; the list of shows, episodes or films
HOME, CHANNELS, LIST = "home", "channels", "list"       # the screens of the data mode (the window property `screen`)
LIBRARY_KEEP = 120               # s the index of the shows and films is kept after the lists are left
PAGES = True                     # the lists are kept on disk (page_cache) and the shows and films are made at start-up (prefetch)
LOAD_FAILED = "The list could not be loaded. Try again in a minute."
LIST_COUNTS = {sections.SHOWS: sections.COUNTS[sections.SHOWS], sections.EPISODES: "Episodes: {n}", sections.FILMS: sections.COUNTS[sections.FILMS]}
ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_CONTEXT_MENU = 2, 3, 4, 117
MENU_DELAY = 0.12                # s the menu rests on a category before the row follows (key repeat does not thrash it)
RETURN_GRACE = 2                 # s: the window coming back sooner than this after Play is not a return from the player
RUNNING = "media-stick.sweettv"  # Home window property while the app is open (single_instance): a live one blocks a second launch
DEMO_LOGOS = os.path.join(ui.ADDON_PATH, "resources", "media", "demo")
STALE_NOTICE = "The channel list is out of date. Refreshing…"

# Live video in the preview is off: the Pi 3B+ has one hardware decoder and the guide would fight the stream for it.
# To try it: set True. The skin then shows a video window over the big logo (the property `preview_video`), the focused
# channel starts playing in it after PREVIEW_DELAY seconds of rest, OK on it goes full screen without reopening, and
# coming back from full screen leaves the stream running. Unverified on the device; it also needs the preview muted
# (JSON-RPC Application.SetMute) and stopped when the window closes, which is not done here.
PREVIEW_VIDEO = False
PREVIEW_DELAY = 1.5


def clock():
    return time.time()


def playing():
    try:
        return xbmc.Player().isPlaying()
    except Exception:
        return False


# ---- the window ------------------------------------------------------------------------------

class SweetTV(Guide, DigitJump, xbmcgui.WindowXML):
    """Set up with setup() after construction: the Kodi window constructors take no extra arguments."""
    GRID_ID = ROW                # the row of cards, for the number keys
    instance = None              # the launch's single_instance flag; main() sets it

    def setup(self, demo=False):
        self.demo = demo
        self._lock = threading.RLock()
        self._loading = threading.Lock()         # one look at the file at a time
        self._stop = threading.Event()
        self._thread = None
        self._timers = {}
        self._io = None
        self._shown_props = {}                   # channel id -> the properties its item has now
        self._window_props = {}
        self.writer = None if demo else StateWriter(files.state_path())
        self.started = False
        self.looks = 0                           # looks at the data that have finished (a test waits on it)
        self.mode = self.kind = ""               # what the window shows, and which status card when it is one
        self.waiting_since = None                # when this screen began to wait for a first channel list
        self.catalog = None
        self.demo_catalog = None                 # the demo's channels, parsed once
        self.stamp = self.mtime = None
        self.state = saved.normalize_state({})
        self.cat_key = ""                        # the category the row shows; "" until the first catalog
        self.cat_names = {}
        self.items = {}                          # channel id -> ListItem, kept so a minute's tick updates it in place
        self.shown = []                          # the channels in the row
        self.entries = []                        # the menu's entries
        self.menu_list = []
        self.numbered = False
        self.digits = ""
        self.play_at = 0.0
        self.session = None                      # the archived programme being played, if one is
        self.previewing = ""                     # PREVIEW_VIDEO: the channel in the preview window
        self.screen = HOME                       # which screen of the data mode is shown: HOME, CHANNELS or LIST
        self.home_pos = 0                        # the card of the first screen that was opened last
        self.archive_any = False                 # some channel has an archive (the key hints say so)
        self.library = sections.Library()        # the index of the shows and films, while they are looked at
        self.list_kind = ""                      # what the list shows: sections.SHOWS, EPISODES or FILMS
        self.list_token = 0                      # a list that is being made for an older token is dropped
        self.rows = []                           # the lines of the list (sweettv_sections.Row)
        self.trail = []                          # where Back goes from an episode list: [(kind, show id, cursor)]
        self.page = ("", 0)                      # (title, how many) of the list on screen
        self.signed = False                      # the plugin is signed in (the disk cache is the account's, kept only while it is)
        self.list_loading = 0                    # lists being made on a worker (the start-up prefetch waits for it to be 0)
        self.warming = None                      # the prefetch run (prefetch.Handle) that makes the shows and films at start-up
        self.dropped = False                     # the pages of a signed-out account are gone

    def onInit(self):
        if self.instance is not None:
            self.instance.bind(xbmcgui.getCurrentWindowId())
        self._prop("demo", "1" if self.demo else "")
        self._prop("preview_video", "1" if PREVIEW_VIDEO else "")
        self._prop("screen", self.screen)
        for key in ("list_title", "list_sub", "list_msg"):
            self._prop(key, self._window_props.get(key, ""))
        self._prop("home_title", words.tr("What to watch?"))
        if not self.started:
            self.started = True
            if not self.demo:
                self.state = saved.merge_local(saved.load_state(files.state_path()), files.local_positions())
                self.writer.start()
            self._show_mode(data.EMPTY, self._status_props(words.status("", False, False, 0)))
        else:
            self._after_player()
        self._start_watch()
        threading.Thread(target=self._look, daemon=True).start()

    def stop(self):
        self._stop.set()
        self._cancel_warm()
        for timer in list(self._timers.values()):
            timer.cancel()
        if self._thread is not None:
            self._thread.join(2)
        if self.writer is not None:
            self.writer.stop()
        self.library.release()

    def _now(self):
        return clock()

    # -- looking at the data (worker thread) --

    def _start_watch(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._watch, daemon=True)
            self._thread.start()

    def _watch(self):
        while not self._stop.wait(data.poll_interval(self.mode == data.DATA)):
            if not playing():                    # a parse is the last thing a stream on a Pi 3 needs
                self._look()

    def _look(self):
        if not self._loading.acquire(False):
            return
        try:
            if not self._stop.is_set():
                now = clock()
                self._apply(self._snapshot(now), now)
        except Exception as e:
            ui.log(f"SWEET.TV refresh failed: {e!r}", xbmc.LOGERROR)
        finally:
            self.looks += 1
            self._loading.release()

    def _snapshot(self, now) -> files.Snapshot:
        if self.demo:                            # the built-in channels: never the real file, never the real sign-in
            if self.demo_catalog is None:
                raw = sweettv_demo.demo_data(now, DEMO_LOGOS)
                self.state = saved.normalize_state(sweettv_demo.demo_state(raw, now))
                self.demo_catalog = data.parse_catalog(raw, now)
            return files.Snapshot(True, self.demo_catalog, ("demo",), now, True, False)
        return files.snapshot(now, self.catalog, self.stamp, self.mtime)

    def _apply(self, snap, now):
        mode = data.view_mode(snap.signed, snap.catalog)
        prepared = phone = None
        ip, kind = files.network()
        if mode == data.DATA:
            if snap.catalog is not self.catalog:
                prepared = items.build(snap.catalog, now, self.state)
            else:
                items.refresh(self.items, self.catalog.channels, now, self.state, self.cat_names, self._shown_props)
        elif mode == data.SIGNIN:
            phone = files.phone_page()
        with self._lock:
            if self._stop.is_set():
                return
            self.signed = bool(snap.signed)
            self._prop("signed", "1" if snap.signed else "")
            self._prop("chip", words.chip(self.demo, snap.signed))
            self._prop("ip", ip)
            self._prop("net", kind)
            if mode == data.DATA:
                self.waiting_since = None
                self._prop("notice", STALE_NOTICE if data.is_stale(snap.mtime, now) and not self.demo else "")
                if prepared is not None:
                    self._install(snap.catalog, prepared)
                self.stamp, self.mtime = snap.stamp, snap.mtime
                self._show_mode(mode, {})
            else:
                self._prop("notice", "")
                self._show_mode(mode, self._card_props(mode, snap, now, phone))
        if snap.signed:
            self.dropped = False
        elif not self.dropped:
            self._signed_out()

    def _signed_out(self):
        """Signed out (or the account changed under the window): the pages kept for the account go, the start-up run stops."""
        self.dropped = True
        self._cancel_warm()
        self.library.release()
        if not self.demo:
            page_cache.drop_service(pages.SERVICE)

    def _card_props(self, mode, snap, now, phone):
        """The window properties of a card that is not the channels: sign in on the phone, or a status."""
        if mode == data.SIGNIN:
            self.waiting_since = None
            url, qr = phone
            return {**words.phone_steps(url), "phone_qr": qr}
        if self.waiting_since is None:
            self.waiting_since = now
        error = snap.catalog.error if snap.catalog else ""
        return self._status_props(words.status(error, snap.has_file, snap.unreadable, now - self.waiting_since))

    @staticmethod
    def _status_props(status):
        return {"msg_kind": status.kind, "msg_glyph": status.glyph, "msg_tint": status.tint, "msg_title": status.title,
                "msg_text": status.text, "msg_note": status.note}

    def _install(self, catalog, prepared):
        """A new catalog: the cards, the menu and the row, keeping the focused channel (or the last one played)."""
        self.items, self._shown_props, self.cat_names = prepared
        keep = self._selected()
        focus = keep.cid if keep else self.state["last"]
        self.catalog = catalog
        self.numbered = any(c.number for c in catalog.channels)
        self.archive_any = any(c.catchup for c in catalog.channels)
        self._prop("hint", self._hint())
        keys = {e.key for e in data.rail(catalog, self.state)}
        self.cat_key = self.cat_key if self.cat_key in keys else data.default_category(catalog, self.state)
        self._fill_menu()
        self._fill_row(self.cat_key, focus)
        self._fill_home()
        self._start_warm()

    # -- the controls --

    def _prop(self, key, value):
        if self._window_props.get(key) != value:
            self._window_props[key] = value
            self.setProperty(key, value)

    def _show_mode(self, mode, props):
        """Show `mode` with the window properties of its card; focus moves when the mode or the status card changes."""
        for key, value in props.items():
            self._prop(key, value)
        kind = props.get("msg_kind", "")
        changed = (mode, kind) != (self.mode, self.kind)
        self.mode, self.kind = mode, kind
        self._prop("mode", mode)
        self._prop("msg_kind", kind)
        if changed:
            self._focus_mode()

    def _focus_mode(self):
        if self.mode == data.SIGNIN:
            self._focus_on(SIGNIN_BUTTON)
        elif self.mode == data.DATA:
            self._focus_on(self._screen_focus())
        elif self.kind != "loading":             # nothing to press while it loads
            self._focus_on(RETRY)

    def _screen_focus(self):
        """What has the focus when a screen of the data mode is shown."""
        return {HOME: SECTIONS, LIST: ITEMS}.get(self.screen) or (ROW if self.shown else MENU)

    def _hint(self):
        """The key hints over the screen that is shown."""
        if self.screen == CHANNELS:
            return words.hint_line(self.numbered, self.archive_any)
        return words.section_hint("home" if self.screen == HOME else self.list_kind)

    def _set_screen(self, screen):
        self.screen = screen
        self._prop("screen", screen)
        self._prop("hint", self._hint())

    def _focus(self):
        try:
            return self.getFocusId()
        except RuntimeError:
            return 0

    def _focus_on(self, control_id, tries=6):
        """Focus a control that has only just been made visible: Kodi takes a moment to agree."""
        for _ in range(tries):
            try:
                self.setFocusId(control_id)
                if self.getFocusId() == control_id:
                    return True
            except RuntimeError:
                pass
            xbmc.sleep(60)
        return False

    def _fill_menu(self):
        self.entries = data.rail(self.catalog, self.state)
        self.menu_list = items.menu_items(self.entries, self.cat_key)
        control = self.getControl(MENU)
        control.reset()
        control.addItems(self.menu_list)
        control.selectItem(next((i for i, e in enumerate(self.entries) if e.key == self.cat_key), 0))

    def _update_menu(self, follow=False):
        """Counts, headings and the marked category, in place; with `follow` the cursor goes to that category."""
        self.entries = data.rail(self.catalog, self.state)
        items.update_menu(self.menu_list, self.entries, self.cat_key)
        if follow:
            self.getControl(MENU).selectItem(next((i for i, e in enumerate(self.entries) if e.key == self.cat_key), 0))

    def _fill_row(self, key, focus_cid="", sync_menu=False):
        self.cat_key = key
        self.shown = data.channels_for(self.catalog, key, self.state)
        control = self.getControl(ROW)
        control.reset()
        control.addItems([self.items[c.cid] for c in self.shown])
        if self.shown:
            control.selectItem(data.focus_index(self.shown, focus_cid))
        self._prop("emptycat", "" if self.shown else data.empty_category_text(key))
        self._update_menu(sync_menu)

    def _selected(self):
        try:
            position = self.getControl(ROW).getSelectedPosition()
        except RuntimeError:
            return None
        return self.shown[position] if 0 <= position < len(self.shown) else None

    # -- keys --

    def onAction(self, action):
        action_id = action.getId()
        if action_id in ui.BACK_ACTIONS:
            if self.guide_open:
                self._guide_close()
            elif self.digits:
                self._digits_clear()
            elif self.mode == data.DATA and self.screen != HOME:
                self._back()
            else:
                self.close()
            return
        if self.mode == data.DATA and self.screen == CHANNELS:
            digit = data.digit_of(action_id, action.getButtonCode())
            if self.guide_open:
                if digit is not None or action_id == ACTION_CONTEXT_MENU:
                    return
            else:
                if action_id == ACTION_CONTEXT_MENU:
                    if self._focus() in (ROW, RESUME, GUIDE_BUTTON):
                        self._toggle_favourite()
                    return
                if digit is not None:
                    if self.numbered:
                        self._digit(digit)
                    return
                if action_id == ACTION_MOVE_UP and self._focus() == ROW and self._focus_actions():
                    return
                if action_id == ACTION_MOVE_RIGHT and self._focus() == MENU:
                    self._cancel("menu")
                    self._apply_menu()           # the row is what the menu shows, before the focus goes into it
        super().onAction(action)
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and self._focus() == MENU:
            self._later("menu", MENU_DELAY, self._apply_menu)
        elif PREVIEW_VIDEO and self._focus() == ROW:
            self._later("preview", PREVIEW_DELAY, self._preview_start)

    def onClick(self, control_id):
        try:
            if control_id == SECTIONS:
                self._open_section()
            elif control_id == ITEMS:
                self._open_row()
            elif control_id == ROW:
                self._play(self._selected())
            elif control_id == MENU:
                self._cancel("menu")
                self._apply_menu()
                if self.shown:
                    self._focus_on(ROW)
            elif control_id == RESUME:
                self._resume_archive()
            elif control_id == GUIDE_BUTTON:
                self._guide_show()
            elif control_id == GUIDE:
                self._guide_play()
            elif control_id == SIGNIN_BUTTON:
                self._signin()
            elif control_id == RETRY:
                self._look_soon()
        except Exception as e:                   # never let a click kill the window
            ui.log(f"click {control_id} failed: {e!r}", xbmc.LOGERROR)

    def _later(self, name, delay, function):
        """Run `function` once after `delay`; asking again for the same `name` starts the wait over."""
        self._cancel(name)
        timer = threading.Timer(delay, self._guarded, args=(function,))
        timer.daemon = True
        self._timers[name] = timer
        timer.start()

    def _cancel(self, name):
        timer = self._timers.pop(name, None)
        if timer is not None:
            timer.cancel()

    @staticmethod
    def _guarded(function, *args):
        try:
            function(*args)
        except Exception as e:
            ui.log(f"background job failed: {e!r}")

    def _in_worker(self, function, *args):
        """Run `function` on a thread of its own: JSON-RPC and the player never block the UI."""
        thread = threading.Thread(target=self._guarded, args=(function,) + args, daemon=True)
        thread.start()
        return thread

    def _apply_menu(self):
        with self._lock:
            position = self.getControl(MENU).getSelectedPosition()
            if self.catalog is not None and 0 <= position < len(self.entries) and self.entries[position].key != self.cat_key:
                self._fill_row(self.entries[position].key)

    def _focus_actions(self):
        """Up from the row: the button for continuing an archived programme, else the one for the guide."""
        channel = self._selected()
        props = self._shown_props.get(channel.cid, {}) if channel else {}
        for control_id, key in ((RESUME, "resume"), (GUIDE_BUTTON, "guide")):
            if props.get(key):
                return self._focus_on(control_id, tries=2)
        return False

    # -- what OK, menu and the number keys do --

    def _play(self, channel, programme=None, resume_at=0):
        """Start `channel` live, or `programme` (a sweettv_view.GuideRow) of its archive, `resume_at` seconds in."""
        if channel is not None:
            self._start(channel.cid, programme, resume_at)

    def _start(self, cid, programme=None, resume_at=0):
        """The same by channel id: the shows and films play a programme of a channel the screen may not be showing."""
        if self.demo:
            ui.notify("Demo: nothing is played.")
            return
        url = data.play_url(cid, programme.epg_id if programme else None)
        if not url:
            return
        now = self._now()
        if PREVIEW_VIDEO and not programme and self.previewing == cid and playing():
            xbmc.executebuiltin("Action(FullScreen)")      # already playing in the preview: just make it big
            self.play_at = now
            return
        session = play.Session(cid, programme.epg_id, programme.title, programme.start, programme.stop) \
            if programme else None
        with self._lock:
            self.state = saved.record_played(self.state, cid, now)
            self.session = session
            self._update_menu()
        self._save_state()
        self.play_at = now
        self._in_worker(self._start_stream, url, session, resume_at)

    def _start_stream(self, url, session, resume_at):
        xbmc.executeJSONRPC(play.open_request(url))
        if session is not None:
            play.follow(session, self._player(), self._stop, self._report, resume_at)

    def _player(self):
        if self._io is None:
            self._io = play.PlayerIO()
        return self._io

    def _report(self, session, pos, total):
        """The player stopped (or the screen came back) at `pos` s of the archived programme `session`."""
        with self._lock:
            if self.session is not session:
                return                           # already reported by the other path
            self.session = None
            self.state = saved.record_position(self.state, session.cid, session.programme(), pos, total, self._now())
            channel = next((c for c in self.catalog.channels if c.cid == session.cid), None) if self.catalog else None
            if channel is not None and session.cid in self.items:
                items.write_props(self.items[session.cid], channel, self._now(), self.state, self.cat_names,
                                  self._shown_props)
        self._save_state()

    def _save_state(self):
        if self.writer is not None:
            self.writer.submit(self.state)

    def _resume_archive(self):
        """The "Continue from ..." button: the saved programme of the focused channel, from where it stopped."""
        channel = self._selected()
        entry = view.resume_for(self.state, channel, self._now()) if channel else None
        if entry:
            self._play(channel, view.GuideRow(entry["epg"], entry["title"], "", "archive", entry["start"], entry["stop"]),
                       entry["pos"])

    def _after_player(self):
        """Back from the player: the stream is stopped (with the place it reached noted), so no sound runs behind
        a screen with no picture, unless the preview is meant to keep playing."""
        if self.play_at and clock() - self.play_at > RETURN_GRACE:
            self.play_at = 0.0
            if not PREVIEW_VIDEO:
                self._in_worker(self._stop_stream)
            self._in_worker(self._focus_back)

    def _stop_stream(self):
        io = self._player()
        session = self.session
        if session is not None:
            seen = io.position()
            if seen:
                self._report(session, *seen)
        if io.playing():
            io.stop()

    def _focus_back(self):
        """Kodi keeps the focus where it was; if it lost it, the row (or the open guide) gets it."""
        if self.mode == data.DATA and self._focus() not in (MENU, ROW, RESUME, GUIDE_BUTTON, GUIDE, SECTIONS, ITEMS):
            self._focus_on(GUIDE if self.guide_open else {HOME: SECTIONS, LIST: ITEMS}.get(self.screen, ROW))

    def _preview_start(self):
        """PREVIEW_VIDEO: play the focused channel in the window over the big logo."""
        channel = self._selected()
        url = data.play_url(channel.cid) if channel and not self.demo else ""
        if url and self.mode == data.DATA and not self.guide_open:
            self.previewing = channel.cid
            xbmc.Player().play(url, None, True)

    def _toggle_favourite(self):
        channel = self._selected()
        if channel is None:
            return
        with self._lock:
            self.state, added = saved.toggle_favourite(self.state, channel.cid)
            items.write_props(self.items[channel.cid], channel, self._now(), self.state, self.cat_names, self._shown_props)
            if self.cat_key == data.FAVOURITES and not added:
                i = self.shown.index(channel)
                near = self.shown[i + 1] if i + 1 < len(self.shown) else self.shown[i - 1] if i else None
                self._fill_row(self.cat_key, near.cid if near else "")
            else:
                self._update_menu()
        self._save_state()

    # -- the sections: the first screen, the shows, the episodes, the films --

    def _fill_home(self, keep_cursor=False):
        """The three cards, with the counts the library already knows (it counts the shows and films when it has built its
        index, never here: this runs on the UI thread) or else the ones the disk cache kept. The cursor stays on the card that
        was opened last (`keep_cursor`: where it is now, for a refresh while the person is looking at the cards)."""
        if self.catalog is None:
            return
        counts = self.library.counts(self._now()) or self._stored_counts()
        entries = sections.home_entries(len(self.catalog.channels), counts)
        control = self.getControl(SECTIONS)
        position = control.getSelectedPosition() if keep_cursor else -1
        control.reset()
        control.addItems(items.home_items(entries))
        control.selectItem(position if position >= 0 else self.home_pos)

    def _home_changed(self):
        """The counts are known now: said on the cards when they are what is on screen."""
        with self._lock:
            if self.screen == HOME and self.mode == data.DATA and not self._stop.is_set():
                self._fill_home(keep_cursor=True)

    def _show_home(self):
        with self._lock:
            self._fill_home()
            self._set_screen(HOME)
        self._focus_on(SECTIONS)

    def _open_section(self):
        """OK on a card of the first screen."""
        position = self.getControl(SECTIONS).getSelectedPosition()
        if not 0 <= position < len(sections.ORDER):
            return
        self.home_pos = position
        key = sections.ORDER[position]
        if key == sections.CHANNELS:
            with self._lock:
                self._set_screen(CHANNELS)
            self._focus_on(ROW if self.shown else MENU)
        else:
            self.trail = []
            self._open_list(key)

    def _back(self):
        """Back on a screen that is not the first one: up one step (episodes to the shows, a list or the channels to the cards)."""
        if self.screen == LIST:
            if self.trail:
                kind, sid, position = self.trail.pop()
                self._open_list(kind, sid, select=position)
                return
            with self._lock:
                self._leave_list()
        self._show_home()

    def _leave_list(self):
        """The list is closed: its lines go, and the index goes after a while (the person may come straight back)."""
        self.list_token += 1
        self.rows = []
        self.getControl(ITEMS).reset()
        self._prop("list_msg", "")
        self._later("library", LIBRARY_KEEP, self.library.release)

    def _open_list(self, kind, sid="", title="", select=None):
        """Show the list `kind` (shows, the episodes of show `sid`, films). A list kept on disk shows at once; one that is
        older than its ttl (or that is not there: empty, with "Loading..." over it) is made on a worker thread (the index reads
        the file) and replaces it when it differs. `select` is the line the cursor goes to when the lines are there."""
        with self._lock:
            self._cancel("library")
            self.list_token += 1
            token = self.list_token
            self.list_kind = kind
            stored = self._stored(kind, sid)
            if stored is not None:
                self._prop("list_title", title or words.tr(sections.NAMES[kind]))
                self._fill_list(kind, stored[0] or title, stored[1], stored[2], "", select)
            else:
                self.rows = []
                self.getControl(ITEMS).reset()
                self._prop("list_title", title or words.tr(sections.NAMES[kind]))
                self._prop("list_sub", "")
                self._prop("list_msg", words.tr("Loading…"))
            self._set_screen(LIST)
            asking = stored is None or stored[3]
            if asking:
                self.list_loading += 1
        self._focus_on(ITEMS)
        if asking:
            self._in_worker(self._load_list, kind, sid, token, select, stored is not None)

    def _fill_list(self, kind, title, rows, total, message, select):
        """The lines on screen (under the lock). `select` is the cursor's line; without one it is the first line, or on a
        show's episodes the first that can be watched."""
        self.rows, self.page = rows, (title, total)
        control = self.getControl(ITEMS)
        control.reset()
        control.addItems(items.row_items(rows))
        if rows:
            control.selectItem(select if select is not None and 0 <= select < len(rows) else
                               sections.first_playable(rows) if kind == sections.EPISODES else 0)
        if title:
            self._prop("list_title", sections.fit(title, sections.HEADING_PX, 60))
        self._prop("list_sub", words.tr(LIST_COUNTS[kind]).format(n=total) if rows else "")
        self._prop("list_msg", "" if rows else message)

    def _load_list(self, kind, sid, token, select, shown=False):
        """Make a list on a worker and show it. `shown`: the list on screen is the one kept on disk, asked for again: a
        failure leaves it, a list that is the same changes nothing, one that changed replaces it with the cursor kept."""
        now = self._now()
        try:
            try:
                title, rows, total, message, ok = self._list_rows(kind, sid, now)
            except Exception as e:
                ui.log(f"SWEET.TV {kind} failed: {e!r}", xbmc.LOGERROR)
                title, rows, total, message, ok = "", [], 0, words.tr(LOAD_FAILED), False
            if ok:
                self._keep(kind, sid, title, rows, total, now)
            with self._lock:
                self._show_made(kind, token, select, shown, (title, rows, total, message, ok))
        finally:
            with self._lock:
                self.list_loading -= 1
        if ok:
            self.library.warm(now)               # so that the first screen can say how many shows and films there are
            self._keep_counts(now)
            self._home_changed()

    def _show_made(self, kind, token, select, shown, made):
        """The list a worker made, on screen (under the lock) unless the person has gone elsewhere or it is no better than the
        list from the disk cache that is on screen."""
        title, rows, total, message, ok = made
        if token != self.list_token or self._stop.is_set():
            return
        if shown:
            if not ok or rows and (title, total) == self.page and rows == self.rows:
                return
            select = self._same_line(rows)
        self._fill_list(kind, title, rows, total, message, select)

    def _same_line(self, rows):
        """Where the cursor goes in `rows` when they replace the ones on screen: on the same programme (or show), else on the
        same place."""
        try:
            position = self.getControl(ITEMS).getSelectedPosition()
        except RuntimeError:
            position = 0
        old = self.rows[position] if 0 <= position < len(self.rows) else None
        if old is not None:
            for i, row in enumerate(rows):
                if (row.key, row.cid, row.epg) == (old.key, old.cid, old.epg):
                    return i
        return max(0, min(position, len(rows) - 1))

    def _list_rows(self, kind, sid, now):
        """(title, rows, how many there are, what to say when there are none, whether that is an answer) of the list
        `kind`; an answer is what to keep (an empty one drops the page), anything else (no library, no list) is only said.
        Slow: no lock held."""
        library = self.library
        if not library.available():
            return "", [], 0, words.tr("SWEET.TV is not available on this device."), False
        if self.demo:
            key, read = ("demo",), lambda: sweettv_demo.demo_data(now, DEMO_LOGOS)
        else:
            path = files.channel_path()
            key, read = files.file_stamp(path) or ("missing",), lambda: files.read_raw(path)
        if not library.load(key, read):
            return "", [], 0, words.tr(LOAD_FAILED), False
        logos = {c.cid: c.logo for c in self.catalog.channels if c.logo} if self.catalog else {}
        if kind == sections.SHOWS:
            rows, total = library.shows(now)
            return "", rows, total, words.tr("No shows with episodes in the archive yet."), True
        if kind == sections.FILMS:
            rows, total = library.films(now, logos)
            return "", rows, total, words.tr("No films in the archive yet."), True
        found = library.episodes(sid, now, logos)
        title, rows, total = found if found else ("", [], 0)
        return title, rows, total, words.tr("This show has no episodes to show."), True

    # -- the lists kept on disk (page_cache), made at start-up (prefetch) --

    def _ns(self):
        """The namespace the account's pages are kept in; None when nothing is kept (the demo, the cache switched off, signed out)."""
        return pages.namespace() if PAGES and not self.demo and self.signed else None

    def _stored(self, kind, sid=""):
        """(title, rows, how many there are, stale) of the list `kind` on disk; None for no page, an old one or a damaged one."""
        ns, key = self._ns(), pages.key_of(kind, sid)
        if ns is None or key is None:
            return None
        hit = page_cache.get(ns, key, pages.PAGE_TTL, pages.PAGE_MAX_AGE, now=self._now())
        found = pages.from_value(kind, hit.value) if hit else None
        return (*found, hit.stale) if found else None

    def _stored_counts(self):
        """(shows, films) the disk cache kept, for the cards; None for none."""
        ns = self._ns()
        hit = page_cache.get(ns, pages.HOME, pages.PAGE_TTL, pages.PAGE_MAX_AGE, now=self._now()) if ns else None
        return pages.counts_from_value(hit.value) if hit else None

    def _keep(self, kind, sid, title, rows, total, now):
        """A list that was made goes to the disk cache (it has lines), or goes from it (the section is empty now). Never a
        failure: the caller keeps only an answer."""
        ns, key = self._ns(), pages.key_of(kind, sid)
        if ns is None or key is None:
            return
        if rows:
            page_cache.put(ns, key, pages.to_value(title, rows, total), now=now)
        else:
            page_cache.remove(ns, key)

    def _keep_counts(self, now):
        ns, counts = self._ns(), self.library.counts(now)
        if ns is not None and counts is not None:
            page_cache.put(ns, pages.HOME, pages.counts_value(*counts), now=now)

    def _start_warm(self):
        """After a catalog is shown: the shows and the films are made one after the other in the background and kept on disk
        (prefetch: at a low priority, only while nothing is loading and no video plays, a page that is fresh is skipped), so
        that the cards have their counts and the lists are there when the person gets to them."""
        ns = self._ns()
        if ns is None or not self.library.available():
            return
        jobs = [(pages.key_of(kind), lambda kind=kind: self._warm_list(kind)) for kind in (sections.SHOWS, sections.FILMS)]
        self.warming = prefetch.warm(ns, jobs, ttl=pages.PAGE_TTL, idle=self._idle)

    def _cancel_warm(self):
        warming, self.warming = self.warming, None
        if warming is not None:
            warming.cancel()

    def _idle(self):
        """Whether the window is waiting for nothing: no list being made, no video playing."""
        return not self._stop.is_set() and not self.list_loading and not playing()

    def _warm_list(self, kind):
        """The job of one list: made as when it is opened, kept by prefetch; None when there is nothing worth keeping."""
        if self._stop.is_set() or not self.signed:
            return None
        now = self._now()
        title, rows, total, _, ok = self._list_rows(kind, "", now)
        if not ok or self._stop.is_set():
            return None
        self.library.warm(now)
        self._keep_counts(now)
        self._home_changed()
        if self.screen != LIST:
            self._later("library", LIBRARY_KEEP, self.library.release)       # nobody is looking at the lists: the index goes
        if not rows:
            ns, key = self._ns(), pages.key_of(kind)
            if ns is not None:
                page_cache.remove(ns, key)
            return None
        return pages.to_value(title, rows, total)

    def _open_row(self):
        """OK on a line of the list: a show opens its episodes, an episode or a film plays from its start in the archive."""
        position = self.getControl(ITEMS).getSelectedPosition()
        row = self.rows[position] if 0 <= position < len(self.rows) else None
        if row is None:
            return
        if self.list_kind == sections.SHOWS:
            self.trail.append((sections.SHOWS, "", position))
            self._open_list(sections.EPISODES, row.key, row.title)
        elif row.playable:
            self._play_row(row)
        else:
            ui.notify(words.tr("This programme has not aired yet." if row.future else "This programme is not in the archive."))

    def _play_row(self, row):
        """The archive path of the phone's play route with `at: start`: the programme from its first second."""
        self._start(row.cid, view.GuideRow(row.epg, row.name or row.title, "", "archive", row.start, row.stop))

    def _look_soon(self):
        threading.Thread(target=self._look, daemon=True).start()

    def _signin(self):
        """Run the existing sign-in screen; when it ends, look again (the plugin writes the list within seconds)."""
        from resources.lib import accounts
        accounts.signin_service("sweettv")
        self._look_soon()


def main(args):
    """Entry for `RunScript(script.media-stick.home,sweettv,open|demo)`. True when the window was shown."""
    instance = single_instance.claim(xbmcgui.Window(ui.HOME), RUNNING)
    if instance is None:
        return False                             # already open (a double press on the card)
    try:
        window = ui.load(SweetTV, XML)
        window.instance = instance
        window.setup(demo=bool(args) and args[0] == "demo")
        window.doModal()
        window.stop()
        del window
    finally:
        instance.release()
    return True
