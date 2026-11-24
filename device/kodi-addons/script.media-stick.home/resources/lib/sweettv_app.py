"""SWEET.TV app window: Netflix-style TV UI with 7-section left rail, hero banner, 4x2 card grid, and modals."""
import os
import sys
import threading
import time

import xbmc
import xbmcgui

LIB_DIR = "/usr/local/lib/media-stick"
if LIB_DIR not in sys.path:
    sys.path.insert(0, LIB_DIR)

import mediastick_resume as mr
from resources.lib import page_cache, single_instance, sweettv_data as data, sweettv_demo, \
    sweettv_files as files, sweettv_items as items, sweettv_pages as pages, sweettv_play as play, \
    sweettv_sections as sections, sweettv_state as saved, sweettv_text as words, ui
from resources.lib.sweettv_find import Find
from resources.lib.sweettv_guide import GUIDE, GUIDE_BUTTON, MODAL_TABS, Guide
from resources.lib.sweettv_jump import DigitJump
from resources.lib.sweettv_shelf import CHIP_FIRST, CHIP_LAST, Shelf
from resources.lib.sweettv_writer import StateWriter

XML = "script-media-stick-sweettv.xml"
MENU, ROW, ACTIONS, RESUME = 100, 200, 209, 210
BTN_ALT, BTN_FAV = 211, 213
SIGNIN_BUTTON, RETRY = 300, 301
ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_CONTEXT_MENU = 2, 3, 4, 117
MENU_DELAY = 0.12
RETURN_GRACE = 2
RUNNING = "media-stick.sweettv"
DEMO_LOGOS = os.path.join(ui.ADDON_PATH, "resources", "media", "demo")
STALE_NOTICE = "The channel list is out of date. Refreshing…"

PREVIEW_VIDEO = False
PREVIEW_DELAY = 1.5


def clock():
    return time.time()


def playing():
    try:
        return xbmc.Player().isPlaying()
    except Exception:
        return False


class SweetTV(Guide, DigitJump, Shelf, Find, xbmcgui.WindowXML):
    """Set up with setup() after construction: the Kodi window constructors take no extra arguments."""
    GRID_ID = ROW
    MENU_ID = MENU
    DEMO_LOGOS = DEMO_LOGOS
    instance = None

    def setup(self, demo=False):
        words.set_language(files.language())
        self.demo = demo
        self._lock = threading.RLock()
        self._loading = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._timers = {}
        self._io = None
        self._window_props = {}
        self._shown_props = {}
        self.writer = None if demo else StateWriter(files.state_path())
        self.started = False
        self.looks = 0
        self.mode = self.kind = ""
        self.signed = False
        self.dropped = False
        self.waiting_since = None
        self.catalog = None
        self.raw_catalog = None
        self.demo_catalog = None
        self.stamp = self.mtime = None
        self.state = saved.normalize_state({})
        self.resume_doc = mr.empty()
        self.favs_doc = {"v": 1, "items": {}}
        self.fav_keys = set()
        self.cat_key = ""
        self.cat_names = {}
        self.items = {}
        self.shown = []
        self.menu_list = []
        self.numbered = False
        self.archive_any = False
        self.digits = ""
        self.play_at = 0.0
        self.session = None
        self.previewing = ""
        self._shelf_setup()
        self._find_setup()
        self._guide_setup()

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
                self.resume_doc = mr.load()
                self.favs_doc = mr.load_favs()
                self._migrate_legacy_favs()
                self.fav_keys = mr.fav_keys(self.favs_doc)
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

    def _migrate_legacy_favs(self):
        legacy = self.state.get("favourites") or ()
        if not legacy:
            return
        existing = mr.fav_keys(self.favs_doc)
        now = int(self._now())
        changed = False
        for cid in legacy:
            key = f"ch:{cid}"
            if key not in existing:
                mr.toggle_fav(key, {"title": f"Channel {cid}"}, now=now)
                changed = True
        if changed:
            self.favs_doc = mr.load_favs()

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
            if not playing():
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
        if self.demo:
            if self.demo_catalog is None:
                raw = self._demo_raw(now)
                self.raw_catalog = raw
                self.state = saved.normalize_state(sweettv_demo.demo_state(raw, now))
                self.resume_doc = sweettv_demo.demo_resume_doc(raw, now)
                self.favs_doc = sweettv_demo.demo_favs_doc(raw, now)
                self.fav_keys = set(self.favs_doc["items"].keys())
                self.demo_catalog = data.parse_catalog(raw, now)
            return files.Snapshot(True, self.demo_catalog, ("demo",), now, True, False)
        snap = files.snapshot(now, self.catalog, self.stamp, self.mtime)
        if snap.catalog is not None and snap.catalog is not self.catalog:
            raw = files.read_raw(files.channel_path())
            if isinstance(raw, dict):
                self.raw_catalog = raw
        return snap

    def _apply(self, snap, now):
        mode = data.view_mode(snap.signed, snap.catalog)
        phone = None
        ip, kind = files.network()
        if mode == data.SIGNIN:
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
                if snap.catalog is not self.catalog:
                    self._install(snap.catalog, now)
                elif self.section == "channels":
                    self._refresh_channels(now)
                self.stamp, self.mtime = snap.stamp, snap.mtime
                self._show_mode(mode, {})
            else:
                self._prop("notice", "")
                self._show_mode(mode, self._card_props(mode, snap, now, phone))
        if snap.signed:
            self.dropped = False
        elif not self.dropped:
            self.dropped = True
            if not self.demo:
                ns = pages.namespace()
                if ns:
                    page_cache.drop_namespace(ns)

    def _card_props(self, mode, snap, now, phone):
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
        return {"msg_kind": status.kind, "msg_glyph": status.glyph, "msg_tint": status.tint,
                "msg_title": status.title, "msg_text": status.text, "msg_note": status.note}

    def _install(self, catalog, now):
        keep = self._focused_card()
        focus_cid = keep.cid if keep and keep.cid else self.state["last"]
        self.catalog = catalog
        self.cat_names = dict(catalog.categories)
        self.numbered = any(c.number for c in catalog.channels)
        self.archive_any = any(c.catchup for c in catalog.channels)
        if not self.section:
            has_cont = bool(sections.continue_cards(self.resume_doc, catalog, now, self.fav_keys))
            self.section = "continue" if has_cont else "channels"
        self._fill_menu()
        if self.section == "channels":
            if self.filter_key.startswith("c:") and self.filter_key not in self.cat_names:
                self.filter_key = "all"
            self._show_channels(focus_cid)
        elif self.section == "continue":
            self._show_continue()
        elif self.section == "favourites":
            self._show_favourites()

    def _refresh_channels(self, now):
        cards = [sections.channel_card(c, self.cat_names, now, self.resume_doc, self.fav_keys) for c in self.shown]
        ctrl = self.getControl(ROW)
        for idx, card in enumerate(cards):
            if idx < len(ctrl.items):
                self._shown_props[card.key] = items.apply_card(ctrl.items[idx], card, self._shown_props.get(card.key))
        self.cards = cards
        self._sync_hero()

    # -- the controls --

    def _prop(self, key, value):
        if self._window_props.get(key) != value:
            self._window_props[key] = value
            self.setProperty(key, value)

    def _show_mode(self, mode, props):
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
            self._focus_on(ROW if self.cards else MENU)
        elif self.kind != "loading":
            self._focus_on(RETRY)

    def _focus(self):
        try:
            return self.getFocusId()
        except RuntimeError:
            return 0

    def _focus_on(self, control_id, tries=6):
        for _ in range(tries):
            try:
                self.setFocusId(control_id)
                if self.getFocusId() == control_id:
                    return True
            except RuntimeError:
                pass
            xbmc.sleep(60)
        return False

    def _section_counts(self):
        cont = len(sections.continue_cards(self.resume_doc, self.catalog, self._now(), self.fav_keys))
        favs = len(self.fav_keys)
        chans = len(self.catalog.channels) if self.catalog else 0
        return {"continue": cont or None, "favourites": favs or None, "channels": chans or None}

    def _fill_menu(self):
        ctrl = self.getControl(MENU)
        self.menu_list = items.rail_items(self.section, self._section_counts())
        ctrl.reset()
        ctrl.addItems(self.menu_list)
        idx = next((i for i, k in enumerate(sections.SECTION_KEYS) if k == self.section), 0)
        ctrl.selectItem(idx)

    def _update_menu(self, follow=False):
        counts = self._section_counts()
        for idx, (li, (key, _)) in enumerate(zip(self.menu_list, sections.RAIL)):
            li.setProperty("active", "1" if key == self.section else "")
            c = counts.get(key)
            li.setLabel2(str(c) if c is not None else "")
            if follow and key == self.section:
                self.getControl(MENU).selectItem(idx)

    def _apply_cards(self, cards, focus_key="", empty_msg="", keep_pos=False):
        ctrl = self.getControl(ROW)
        old_pos = ctrl.getSelectedPosition() if keep_pos else 0
        self.cards = list(cards)
        self._shown_props = {}
        list_items = []
        for c in self.cards:
            li = items.card_item(c)
            self._shown_props[c.key] = dict(li.props) if hasattr(li, "props") else items.card_props(c)
            list_items.append(li)
        ctrl.reset()
        ctrl.addItems(list_items)
        if self.cards:
            pos = next((i for i, c in enumerate(self.cards) if c.key == focus_key), 0) if focus_key else min(
                max(0, old_pos), len(self.cards) - 1)
            ctrl.selectItem(pos)
        self._prop("emptycat", "" if self.cards else empty_msg)
        self._sync_hero()

    def _select_grid(self, pos):
        ctrl = self.getControl(ROW)
        if 0 <= pos < len(self.cards):
            ctrl.selectItem(pos)
            self._sync_hero()

    def _focused_card(self):
        try:
            pos = self.getControl(ROW).getSelectedPosition()
        except RuntimeError:
            return None
        return self.cards[pos] if 0 <= pos < len(self.cards) else None

    def _sync_hero(self):
        card = self._focused_card()
        info = sections.hero_info(card)
        for k, v in info.items():
            self._prop(k, v)
        self.getControl(RESUME).setLabel(info["hero_play"])
        self.getControl(BTN_ALT).setLabel(info["hero_alt"])
        self.getControl(GUIDE_BUTTON).setLabel(info["hero_guide"])
        self.getControl(BTN_FAV).setLabel(info["hero_fav"])

    # -- section switching --

    def _open_section(self, key, focus_cid="", sync_menu=False):
        with self._lock:
            self.section = key
            self._update_menu(follow=sync_menu)
            if key == "search":
                self._set_chips("search", [("new", words.tr("New search"))])
                self._prop("hint", words.section_hint("films"))
                if self.search_cards:
                    self._apply_cards(self.search_cards)
                else:
                    self._apply_cards([], empty_msg=words.tr("Loading…"))
                    self._load_top_search()
            elif key == "continue":
                self._set_chips("continue", [])
                self._prop("hint", words.section_hint("films"))
                self._show_continue()
            elif key == "favourites":
                self._set_chips("favourites", [])
                self._prop("hint", words.section_hint("films"))
                self._show_favourites()
            elif key == "shows":
                self._set_chips("shows", [])
                self._prop("hint", words.section_hint("shows"))
                self._apply_cards([], empty_msg=words.tr("Loading…"))
                self._load_shows()
            elif key in ("series", "movies"):
                self.genre_id = 0
                self._set_chips(key, sections.catalog_chips(self.genres, self.sort_modes, self.sort_idx))
                self._prop("hint", words.section_hint("shows" if key == "series" else "films"))
                self._apply_cards([], empty_msg=words.tr("Loading…"))
                self._load_catalog(key, offset=0)
            elif key == "channels":
                self._show_channels(focus_cid)

    def _fill_row(self, key, focus_cid="", sync_menu=False):
        if key == data.ALL:
            self.filter_key = "all"
            self._open_section("channels", focus_cid=focus_cid, sync_menu=sync_menu)
        elif key == data.RECENT:
            self._open_section("continue", sync_menu=sync_menu)
        elif key == data.FAVOURITES:
            self._open_section("favourites", sync_menu=sync_menu)
        elif key in sections.SECTION_KEYS:
            self._open_section(key, focus_cid=focus_cid, sync_menu=sync_menu)

    def _show_continue(self):
        if not self.demo:
            self.resume_doc = mr.load()
        cards = sections.continue_cards(self.resume_doc, self.catalog, self._now(), self.fav_keys)
        self._apply_cards(cards, empty_msg=words.tr("Nothing in Continue yet."))

    def _show_favourites(self):
        if not self.demo:
            self.favs_doc = mr.load_favs()
            self.fav_keys = mr.fav_keys(self.favs_doc)
        cards = sections.favourites_cards(self.favs_doc, self.catalog, self.cat_names, self._now(), self.resume_doc)
        self._apply_cards(cards, empty_msg=words.tr("No favourites yet."))

    def _show_channels(self, focus_cid=""):
        if not self.catalog:
            return
        self.shown = sections.filter_channels(self.catalog.channels, self.filter_key)
        self._set_chips("channels", sections.channel_chips(self.catalog.categories))
        self._prop("hint", words.hint_line(self.numbered, self.archive_any))
        now = self._now()
        cards = [sections.channel_card(c, self.cat_names, now, self.resume_doc, self.fav_keys) for c in self.shown]
        self._apply_cards(cards, focus_key=focus_cid, empty_msg=words.tr("No channels here."))

    # -- keys & clicks --

    def onAction(self, action):
        action_id = action.getId()
        if action_id in ui.BACK_ACTIONS:
            if self._modal_open():
                self._guide_close()
            elif self.digits:
                self._digits_clear()
            elif self.mode == data.DATA and self._focus() in (ROW, RESUME, BTN_ALT, GUIDE_BUTTON, BTN_FAV,
                                                              *range(CHIP_FIRST, CHIP_LAST + 1)):
                self._focus_on(MENU)
            else:
                self.close()
            return
        if self.mode == data.DATA:
            digit = data.digit_of(action_id, action.getButtonCode())
            if self._modal_open():
                if digit is not None or action_id == ACTION_CONTEXT_MENU:
                    return
            else:
                if action_id == ACTION_CONTEXT_MENU:
                    if self._focus() in (ROW, RESUME, BTN_ALT, GUIDE_BUTTON, BTN_FAV):
                        self._toggle_favourite()
                    return
                if digit is not None:
                    if self.numbered and self.section == "channels":
                        self._digit(digit)
                    return
                if action_id == ACTION_MOVE_RIGHT and self._focus() == MENU:
                    self._cancel("menu")
                    self._apply_menu()
        super().onAction(action)
        if self._focus() == ROW:
            self._sync_hero()
            if action_id == ACTION_MOVE_DOWN:
                self._maybe_paginate()
            if PREVIEW_VIDEO:
                self._later("preview", PREVIEW_DELAY, self._preview_start)
        elif action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and self._focus() == MENU:
            self._later("menu", MENU_DELAY, self._apply_menu)

    def onClick(self, control_id):
        try:
            if control_id == ROW:
                self._ok_card()
            elif control_id == MENU:
                self._cancel("menu")
                pos = self.getControl(MENU).getSelectedPosition()
                if 0 <= pos < len(sections.SECTION_KEYS):
                    key = sections.SECTION_KEYS[pos]
                    if key == "search" and self.section == "search":
                        self._ask_search()
                        return
                    self._open_section(key)
                    if self.cards:
                        self._focus_on(ROW)
            elif control_id == RESUME:
                self._ok_card()
            elif control_id == BTN_ALT:
                self._alt_action()
            elif control_id == GUIDE_BUTTON:
                self._guide_show()
            elif control_id == BTN_FAV:
                self._toggle_favourite()
            elif CHIP_FIRST <= control_id <= CHIP_LAST:
                self._chip_click(control_id)
            elif control_id == MODAL_TABS:
                self._modal_select_tab(self.getControl(MODAL_TABS).getSelectedPosition())
            elif control_id == GUIDE:
                self._modal_click()
            elif control_id == SIGNIN_BUTTON:
                self._signin()
            elif control_id == RETRY:
                self._look_soon()
        except Exception as e:
            ui.log(f"click {control_id} failed: {e!r}", xbmc.LOGERROR)

    def _apply_menu(self):
        with self._lock:
            pos = self.getControl(MENU).getSelectedPosition()
            if 0 <= pos < len(sections.SECTION_KEYS):
                key = sections.SECTION_KEYS[pos]
                if key != self.section:
                    self._open_section(key)

    def _ok_card(self):
        card = self._focused_card()
        if card is None:
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        if not card.playable or not card.play_url:
            ui.notify(words.tr("This programme has not aired yet."))
            return
        if card.kind == "channel":
            self._start_playback(card.play_url, cid=card.cid)
        else:
            session = play.Session(card.cid, card.epg, card.title, card.start, card.stop, url=card.play_url)
            self._start_playback(card.play_url, cid=card.cid, session=session, seek_to=card.resume_pos)

    def _alt_action(self):
        card = self._focused_card()
        if card is None:
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        if card.alt_url:
            session = play.Session(card.cid, card.epg, card.title, card.start, card.stop, url=card.alt_url)
            self._start_playback(card.alt_url, cid=card.cid, session=session, seek_to=0)

    # -- playback & resume --

    def _start_playback(self, url, cid="", session=None, seek_to=0):
        if self.demo:
            ui.notify(words.tr("Demo: nothing is played."))
            return
        if not url:
            return
        now = self._now()
        if PREVIEW_VIDEO and cid and session is None and self.previewing == cid and playing():
            xbmc.executebuiltin("Action(FullScreen)")
            self.play_at = now
            return
        with self._lock:
            if cid:
                self.state = saved.record_played(self.state, cid, now)
                self._update_menu()
            self.session = session
        if self.writer is not None and cid:
            self.writer.submit(self.state)
        self.play_at = now
        self._in_worker(self._start_stream, url, session, seek_to)

    def _start_stream(self, url, session, seek_to):
        xbmc.executeJSONRPC(play.open_request(url))
        if session is not None:
            play.follow(session, self._player(), self._stop, self._report, seek_to)

    def _player(self):
        if self._io is None:
            self._io = play.PlayerIO()
        return self._io

    def _report(self, session, pos, total):
        with self._lock:
            if self.session is not session:
                return
            self.session = None
            now = self._now()
            if session.url:
                self.resume_doc = mr.record(self.resume_doc, session.url, pos, total, now,
                                            {"title": session.title, "start": session.start, "stop": session.stop})
                mr.save(self.resume_doc)
            if session.cid and session.epg:
                self.state = saved.record_position(self.state, session.cid, session.programme(), pos, total, now)
                if self.writer is not None:
                    self.writer.submit(self.state)

    def _after_player(self):
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
        if self.mode == data.DATA and self._focus() not in (MENU, ROW, RESUME, BTN_ALT, GUIDE_BUTTON, BTN_FAV, GUIDE):
            self._focus_on(GUIDE if self._modal_open() else ROW)

    def _preview_start(self):
        card = self._focused_card()
        url = card.play_url if (card and card.kind == "channel" and not self.demo) else ""
        if url and self.mode == data.DATA and not self._modal_open():
            self.previewing = card.cid
            xbmc.Player().play(url, None, True)

    def _toggle_favourite(self):
        card = self._focused_card()
        if card is None or not card.fav_key:
            return
        with self._lock:
            if self.demo:
                items_map = self.favs_doc["items"]
                if card.fav_key in items_map:
                    del items_map[card.fav_key]
                    added = False
                else:
                    items_map[card.fav_key] = {"title": card.title, "thumb": card.art, "at": int(self._now())}
                    added = True
            else:
                added, _ = mr.toggle_fav(card.fav_key, {"title": card.title, "thumb": card.art}, now=self._now())
                self.favs_doc = mr.load_favs()
            self.fav_keys = set(self.favs_doc["items"].keys())
            pos = max(0, self.getControl(ROW).getSelectedPosition())
            if self.section == "favourites" and not added:
                self._show_favourites()
                if self.cards:
                    self._select_grid(min(pos, len(self.cards) - 1))
            else:
                updated = card._replace(fav=added)
                self.cards[pos] = updated
                li = self.getControl(ROW).items[pos]
                self._shown_props[card.key] = items.apply_card(li, updated, self._shown_props.get(card.key))
                self._sync_hero()
            self._update_menu()

    # -- timers & workers --

    def _later(self, name, delay, function):
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
        thread = threading.Thread(target=self._guarded, args=(function,) + args, daemon=True)
        thread.start()
        return thread

    def _look_soon(self):
        threading.Thread(target=self._look, daemon=True).start()

    def _signin(self):
        from resources.lib import accounts
        accounts.signin_service("sweettv")
        self._look_soon()


def main(args):
    """Entry for `RunScript(script.media-stick.home,sweettv,open|demo)`. True when the window was shown."""
    instance = single_instance.claim(xbmcgui.Window(ui.HOME), RUNNING)
    if instance is None:
        return False
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
