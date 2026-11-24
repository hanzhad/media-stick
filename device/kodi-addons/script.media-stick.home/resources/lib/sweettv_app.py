"""The SWEET.TV app window, laid out like the launcher: a full-screen backdrop in the colour of the focused card, a menu on
the left, a row of cards (a carousel) along the bottom, and over the row what the focused card is (for a channel: what it is
showing now, times, progress, description, what comes next, badges, and the buttons for the programme guide and for
continuing an archived programme; for a show: its title, how many episodes, the channel and the newest one; for a film: its
title, length, channel and time). Also a sign-in card and, when there is nothing to show, a status card (loading, empty,
error) with a retry button.

  RunScript(script.media-stick.home,sweettv,open)    the app, from the plugin's channel list
  RunScript(script.media-stick.home,sweettv,demo)    the same screen on invented channels, shows and films; plays nothing

One screen. The menu (100) lists Continue, Favourites, All, "Search", "Shows and series" and "Films" (the last two in the accent colour),
then a small heading "Genres" and under it the genres of SWEET.TV (about 18, so the entries that matter come first). The
heading is never focused: the cursor steps over it, key repeat too. The row (200) holds what the menu is on: that category's channel
cards, or the cards of the shows, or of the films (sweettv_shelf). OK on a channel plays it live, on a film plays it from its
start in the archive, on a show opens its episodes in the same row; OK on an episode plays it (one not on air yet, or not in
the archive, says so). Back goes one step up: the episodes to the shows (the cursor on the same show), the row to the menu,
the menu closes the app. OK on "Search" opens the on-screen keyboard (a worker thread, sweettv_find); the row then holds
the cards of what api.sweet.tv found (sweettv_search, mediastick_sweetapi), the last query is kept while the window is open;
OK plays a programme from the archive or a channel live, a card out of the archive is dimmed and says so. The menu's up/down changes the row to that entry's cards a moment after the key rests; right goes
into the row, left from its first card back. The screen opens on "Continue" (the channels watched last, the last one first
and focused) or, with nothing watched yet, on "All".

Focus: the menu (100), the row (200), the buttons over the row (210 continue, 211 guide), the guide's list (400).

The channels come from special://temp/channelList.json, which the SWEET.TV plugin writes while it is
signed in (sweettv_data describes it). The file is read and parsed off the UI thread, once per change of
its mtime/size. What is on now and next is worked out from the clock, so a minute's tick refreshes the cards.
The state (favourites, recent, places in the archive) is written by sweettv_writer's thread, Player.Open and the
watch of the player run on worker threads. The thin Kodi part is here; the choices are in sweettv_data and
sweettv_view, the words in sweettv_text (said in the device's language: sweettv_files.language), the number keys in sweettv_jump, the guide in sweettv_guide, the shows and
films in sweettv_shelf (rows in sweettv_sections), the streams in sweettv_play.
"""
import os
import threading
import time

import xbmc
import xbmcgui

from resources.lib import single_instance, sweettv_data as data, sweettv_demo, sweettv_files as files, sweettv_items as items, \
    sweettv_play as play, sweettv_state as saved, sweettv_text as words, sweettv_view as view, ui
from resources.lib.sweettv_find import Find
from resources.lib.sweettv_guide import GUIDE, GUIDE_BUTTON, Guide
from resources.lib.sweettv_jump import DigitJump
from resources.lib.sweettv_shelf import CHANNELS, EPISODES, Shelf
from resources.lib.sweettv_writer import StateWriter

XML = "script-media-stick-sweettv.xml"
MENU, ROW, ACTIONS, RESUME = 100, 200, 209, 210          # the buttons over the row are the group 209: 210, 211
SIGNIN_BUTTON, RETRY = 300, 301
ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_CONTEXT_MENU = 2, 3, 4, 117
MENU_DELAY = 0.12                # s the menu rests on an entry before the row follows (key repeat does not thrash it)
RETURN_GRACE = 2                 # s: the window coming back sooner than this after Play is not a return from the player
RUNNING = "media-stick.sweettv"  # Home window property while the app is open (single_instance): a live one blocks a second launch
DEMO_LOGOS = os.path.join(ui.ADDON_PATH, "resources", "media", "demo")
STALE_NOTICE = "The channel list is out of date. Refreshing…"      # a msgid (sweettv_text)

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

class SweetTV(Guide, DigitJump, Shelf, Find, xbmcgui.WindowXML):
    """Set up with setup() after construction: the Kodi window constructors take no extra arguments."""
    GRID_ID = ROW                # the row of cards, for the number keys
    MENU_ID = MENU               # the menu on the left
    instance = None              # the launch's single_instance flag; main() sets it

    def setup(self, demo=False):
        words.set_language(files.language())     # before anything is said: the items, the pages and the cache follow it
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
        self.cat_key = ""                        # the menu entry the row shows; "" until the first catalog
        self.cat_names = {}
        self.items = {}                          # channel id -> ListItem, kept so a minute's tick updates it in place
        self.shown = []                          # the channels in the row (none while it holds shows, episodes or films)
        self.entries = []                        # the menu's entries
        self.menu_list = []
        self.numbered = False
        self.archive_any = False                 # some channel has an archive (the key hints say so)
        self.digits = ""
        self.play_at = 0.0
        self.session = None                      # the archived programme being played, if one is
        self.previewing = ""                     # PREVIEW_VIDEO: the channel in the preview window
        self._shelf_setup()
        self._find_setup()

    def onInit(self):
        if self.instance is not None:
            self.instance.bind(xbmcgui.getCurrentWindowId())
        for key, value in words.labels().items():
            self._prop(key, value)
        self._prop("demo", "1" if self.demo else "")
        self._prop("preview_video", "1" if PREVIEW_VIDEO else "")
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

    def _playing(self):
        return playing()

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

    def _demo_raw(self, now):
        return sweettv_demo.demo_data(now, DEMO_LOGOS)

    def _snapshot(self, now) -> files.Snapshot:
        if self.demo:                            # the built-in channels: never the real file, never the real sign-in
            if self.demo_catalog is None:
                raw = self._demo_raw(now)
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
                self._prop("notice", words.tr(STALE_NOTICE) if data.is_stale(snap.mtime, now) and not self.demo else "")
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
        """A new catalog: the channel cards and the menu, and the row, keeping the focused channel (or the last one played).
        A row that holds shows, episodes or films stays as it is: those are made from the file when they are asked for."""
        self.items, self._shown_props, self.cat_names = prepared
        keep = self._selected()
        focus = keep.cid if keep else self.state["last"]
        self.catalog = catalog
        self.numbered = any(c.number for c in catalog.channels)
        self.archive_any = any(c.catchup for c in catalog.channels)
        self.counts = self.library.counts(self._now()) or self._stored_counts() or self.counts
        self._prop("hint", self._hint())
        keys = {e.key for e in data.rail(catalog, self.state)}
        self.cat_key = self.cat_key if self.cat_key in keys else data.default_category(catalog, self.state)
        self._fill_menu()
        if self.row_kind == CHANNELS:
            self._fill_row(self.cat_key, focus)
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
            self._focus_on(ROW if self._row_size() else MENU)
        elif self.kind != "loading":             # nothing to press while it loads
            self._focus_on(RETRY)

    def _hint(self):
        """The key hints over the screen: the channel keys, or only OK and Back while the row holds shows or films."""
        if self.row_kind == CHANNELS:
            return words.hint_line(self.numbered, self.archive_any)
        return words.section_hint(self.row_kind)

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

    def _rail(self):
        return data.rail(self.catalog, self.state, self.counts)

    def _fill_menu(self):
        self.entries = self._rail()
        self.menu_list = items.menu_items(self.entries, self.cat_key)
        control = self.getControl(MENU)
        control.reset()
        control.addItems(self.menu_list)
        control.selectItem(next((i for i, e in enumerate(self.entries) if e.key == self.cat_key), 0))

    def _update_menu(self, follow=False):
        """Counts, headings and the marked entry, in place; with `follow` the cursor goes to that entry."""
        self.entries = self._rail()
        items.update_menu(self.menu_list, self.entries, self.cat_key)
        if follow:
            self.getControl(MENU).selectItem(next((i for i, e in enumerate(self.entries) if e.key == self.cat_key), 0))

    def _fill_row(self, key, focus_cid="", sync_menu=False):
        """The row shows the channels of category `key`."""
        if self.row_kind != CHANNELS:
            self._leave_shelf()
        self.cat_key = key
        self.shown = data.channels_for(self.catalog, key, self.state)
        control = self.getControl(ROW)
        control.reset()
        control.addItems([self.items[c.cid] for c in self.shown])
        if self.shown:
            control.selectItem(data.focus_index(self.shown, focus_cid))
        self._prop("emptycat", "" if self.shown else words.tr(data.empty_category_text(key)))
        self._prop("hint", self._hint())
        self._update_menu(sync_menu)

    def _selected(self):
        """The channel under the cursor of the row; None while the row holds shows, episodes or films."""
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
            elif self.mode == data.DATA and self._focus() in (ROW, RESUME, GUIDE_BUTTON):
                self._back()
            else:
                self.close()
            return
        if self.mode == data.DATA:
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
                    if self.numbered and self.row_kind == CHANNELS:      # channel numbers mean nothing among shows and films
                        self._digit(digit)
                    return
                if action_id == ACTION_MOVE_UP and self._focus() == ROW and self._focus_actions():
                    return
                if action_id == ACTION_MOVE_RIGHT and self._focus() == MENU:
                    self._cancel("menu")
                    self._apply_menu()           # the row is what the menu shows, before the focus goes into it
                    self.enter_row = not self._row_size()
        super().onAction(action)
        if self._focus() == MENU:
            self._skip_heading(action_id)
        if action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and self._focus() == MENU:
            self._later("menu", MENU_DELAY, self._apply_menu)
        elif PREVIEW_VIDEO and self._focus() == ROW:
            self._later("preview", PREVIEW_DELAY, self._preview_start)

    def onClick(self, control_id):
        try:
            if control_id == ROW:
                if self.row_kind == CHANNELS:
                    self._play(self._selected())
                else:
                    self._ok_card()
            elif control_id == MENU:
                self._cancel("menu")
                self._apply_menu()
                if self._menu_key() == data.SEARCH:
                    self._search_ask()           # OK on Search asks for words; the row holds the last results meanwhile
                    return
                self.enter_row = not self._row_size()
                if not self.enter_row:
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

    def _back(self):
        """Back in the row: the episodes of a show to the shows (the cursor on the same show), anything else to the menu."""
        if self.row_kind == EPISODES and self.trail:
            self._episodes_back()
        else:
            self._focus_on(MENU)

    def _skip_heading(self, action_id):
        """The cursor of the menu landed on a heading (it is no entry): on to the next entry in the direction of the key. Every
        key press (and every repeat of a held one) comes through here, so the heading is never stopped on."""
        control = self.getControl(MENU)
        position = control.getSelectedPosition()
        if 0 <= position < len(self.entries) and not self.entries[position].focusable:
            control.selectItem(data.next_focusable(self.entries, position, -1 if action_id == ACTION_MOVE_UP else 1))

    def _apply_menu(self):
        """The row follows the menu: the channels of a category, or the cards of the shows or of the films."""
        with self._lock:
            position = self.getControl(MENU).getSelectedPosition()
            if self.catalog is not None and 0 <= position < len(self.entries) and self.entries[position].focusable                     and self.entries[position].key != self.cat_key:
                key = self.entries[position].key
                self.enter_row = False
                if key in (data.SHOWS, data.FILMS):
                    self.trail = []
                    self._open_section(key)
                elif key == data.SEARCH:
                    self.trail = []
                    self._open_search()
                else:
                    self._fill_row(key)

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
            ui.notify(words.tr("Demo: nothing is played."))
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
        if self.mode == data.DATA and self._focus() not in (MENU, ROW, RESUME, GUIDE_BUTTON, GUIDE):
            self._focus_on(GUIDE if self.guide_open else ROW)

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
