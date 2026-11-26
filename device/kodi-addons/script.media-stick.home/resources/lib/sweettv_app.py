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
from resources.lib import page_cache, quick_resume, single_instance, sweettv_data as data, sweettv_demo, \
    sweettv_files as files, sweettv_items as items, sweettv_pages as pages, sweettv_play as play, \
    sweettv_sections as sections, sweettv_state as saved, sweettv_text as words, ui
from resources.lib.sweettv_find import Find
from resources.lib.sweettv_guide import GUIDE, GUIDE_BUTTON, MODAL_TABS, Guide
from resources.lib.sweettv_jump import DigitJump
from resources.lib.sweettv_shelf import CHIP_FIRST, CHIP_LAST, PAGE_SIZE, Shelf
from resources.lib.sweettv_writer import StateWriter

XML = "script-media-stick-sweettv.xml"
MENU, ROW, WIDE_ROW, ACTIONS, RESUME = 100, 200, 201, 209, 210
WIDE_SECTIONS = frozenset(("continue", "channels"))
BTN_ALT, BTN_FAV = 211, 213
SIGNIN_BUTTON, RETRY = 300, 301
PAGE_SEARCH, HERO_GUIDE = 415, 416
HERO_PLAY, HERO_ALT, HERO_FAV = 417, 418, 420
ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT, ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_CONTEXT_MENU = 1, 2, 3, 4, 117
MENU_DELAY = 0.12
AUTOPLAY_SECONDS = 5
RETURN_GRACE = 2
RUNNING = "media-stick.sweettv"
DEMO_LOGOS = os.path.join(ui.ADDON_PATH, "resources", "media", "demo")
STALE_NOTICE = "The channel list is out of date. Refreshing…"

PREVIEW_VIDEO = False
PREVIEW_DELAY = 1.5
_UNSET = object()


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

    def _grid_id(self) -> int:
        return WIDE_ROW if self.section in WIDE_SECTIONS else ROW

    def _active_grid_pos(self) -> int:
        cid = self._focus()
        target = cid if cid in (ROW, WIDE_ROW) else self._grid_id()
        try:
            return max(0, self.getControl(target).getSelectedPosition())
        except RuntimeError:
            return 0
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
        self._qr_focus_index = 0
        self._qr_focus_key = ""
        self._qr_dirty = False
        self._pre_search_pos = None
        self._autoplay_candidate = None
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
                snap = quick_resume.load_snapshot("sweettv", "default")
                if snap and snap.get("section") in sections.SECTION_KEYS:
                    self.section = snap["section"]
                    if snap.get("filter"):
                        self.filter_key = snap["filter"]
                    self._qr_focus_index = max(0, int(snap.get("focused_index") or 0))
                    self._qr_focus_key = str(snap.get("focused_key") or "")
                self.writer.start()
            if not self._try_instant_start(clock()):
                self._show_mode(data.EMPTY, self._status_props(words.status("", False, False, 0)))
        else:
            self._after_player()
        self._start_watch()
        threading.Thread(target=self._look, daemon=True).start()

    def stop(self):
        if self._qr_dirty:
            self._save_quick_resume(immediate=True)
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

    def _continue_cards(self, catalog=_UNSET, now=None) -> list:
        cat = self.catalog if catalog is _UNSET else catalog
        ts = self._now() if now is None else now
        if self.demo:
            return sections.continue_cards(self.resume_doc, cat, ts, self.fav_keys)
        return sections.continue_cards(
            self.resume_doc,
            cat,
            ts,
            self.fav_keys,
            recall_prog=lambda cid, epg, t=ts: files.recall_programme(cid, epg, now=t),
            recall_title=files.recall_title_detail,
        )

    def _try_instant_start(self, now) -> bool:
        if self.demo or not files.signed_in():
            return False
        has_cont = bool(self._continue_cards(None, now))
        ns = pages.namespace()
        ckey = pages.catalog_key("shows") if ns else None
        shows_hit = bool(ns and ckey and page_cache.get(ns, ckey, ttl=pages.PAGE_TTL, max_age=pages.PAGE_MAX_AGE))
        if not has_cont and not shows_hit:
            return False
        with self._lock:
            self.signed = True
            self._prop("signed", "1")
            self._prop("chip", words.chip(False, True))
            if self.section not in ("continue", "shows"):
                self.section = "continue" if has_cont else "shows"
            self._prop("wide_grid", "1" if self.section in WIDE_SECTIONS else "")
            self._prop("section_title", words.section_title(self.section))
            self._sync_page_search_label()
            self._fill_menu()
            if self.section == "continue":
                self._show_continue()
            else:
                self._open_section("shows")
            self._show_mode(data.DATA, {})
        return True

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
            raw = files.read_raw(now)
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
            elif mode == data.EMPTY and snap.signed and snap.catalog is None and self.mode == data.DATA:
                self.waiting_since = None
                self._prop("notice", "")
                self._show_mode(data.DATA, {})
            else:
                self._prop("notice", "")
                self._show_mode(mode, self._card_props(mode, snap, now, phone))
        if snap.signed:
            self.dropped = False
        elif not self.dropped:
            self.dropped = True
            if not self.demo:
                files.clear_store()
                ns = pages.namespace()
                if ns:
                    page_cache.drop_namespace(ns)
                    quick_resume.drop_snapshots("sweettv")

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
            has_cont = bool(self._continue_cards(catalog, now))
            self.section = "continue" if has_cont else "channels"
        self._prop("wide_grid", "1" if self.section in WIDE_SECTIONS else "")
        self._prop("section_title", words.section_title(self.section))
        self._sync_page_search_label()
        self._fill_menu()
        if self.section == "channels":
            if self.filter_key.startswith("c:") and self.filter_key not in self.cat_names:
                self.filter_key = "all"
            self._show_channels(focus_cid)
        elif self.section == "continue":
            self._show_continue()
        elif self.section == "favourites":
            self._show_favourites()
        elif self.section in ("movies", "series", "shows", "search"):
            self._open_section(self.section, focus_cid=focus_cid)

    def _refresh_channels(self, now):
        cards = [sections.channel_card(c, self.cat_names, now, self.resume_doc, self.fav_keys) for c in self.shown]
        for cid in (ROW, WIDE_ROW):
            is_wide = cid == WIDE_ROW
            try:
                ctrl = self.getControl(cid)
            except Exception:
                continue
            size = ctrl.size() if hasattr(ctrl, "size") else len(ctrl.items)
            for idx, card in enumerate(cards):
                if idx < size:
                    item = ctrl.getListItem(idx) if hasattr(ctrl, "getListItem") else ctrl.items[idx]
                    self._shown_props[(cid, idx)] = items.apply_card(
                        item, card, self._shown_props.get((cid, idx)), wide=is_wide
                    )
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
        if changed or (mode == data.DATA and self._focus() == 0):
            self._focus_mode()

    def _focus_mode(self):
        if self.mode == data.SIGNIN:
            self._focus_on(SIGNIN_BUTTON)
        elif self.mode == data.DATA:
            self._focus_on(self._grid_id() if self.cards else MENU)
        elif self.kind != "loading":
            self._focus_on(RETRY)

    def _focus(self):
        try:
            return self.getFocusId()
        except RuntimeError:
            return 0

    def _focus_on(self, control_id, tries=12):
        for _ in range(tries):
            try:
                self.setFocusId(control_id)
                if self.getFocusId() == control_id:
                    return True
            except RuntimeError:
                pass
            xbmc.sleep(50)
        return False

    def _section_counts(self):
        cont = len(self._continue_cards())
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
        old_pos = self._active_grid_pos() if keep_pos else 0
        self.cards = list(cards)
        self._shown_props = {}
        list_items = []
        for idx, c in enumerate(self.cards):
            li = items.card_item(c, wide=False)
            self._shown_props[(ROW, idx)] = dict(li.props) if hasattr(li, "props") else items.card_props(c, wide=False)
            list_items.append(li)
        ctrl.reset()
        ctrl.addItems(list_items)
        try:
            wctrl = self.getControl(WIDE_ROW)
            wide_items = []
            for idx, c in enumerate(self.cards):
                wli = items.card_item(c, wide=True)
                self._shown_props[(WIDE_ROW, idx)] = dict(wli.props) if hasattr(wli, "props") else items.card_props(c, wide=True)
                wide_items.append(wli)
            wctrl.reset()
            wctrl.addItems(wide_items)
        except Exception:
            pass
        if self.cards:
            pos = next((i for i, c in enumerate(self.cards) if c.key == focus_key), 0) if focus_key else min(
                max(0, old_pos), len(self.cards) - 1)
            ctrl.selectItem(pos)
            try:
                self.getControl(WIDE_ROW).selectItem(pos)
            except Exception:
                pass
        self._prop("emptycat", "" if self.cards else empty_msg)
        self._sync_hero()

    def _select_grid(self, pos):
        if 0 <= pos < len(self.cards):
            self.getControl(ROW).selectItem(pos)
            try:
                self.getControl(WIDE_ROW).selectItem(pos)
            except Exception:
                pass
            self._sync_hero()

    def _focused_card(self):
        pos = self._active_grid_pos()
        return self.cards[pos] if 0 <= pos < len(self.cards) else None

    def _sync_hero(self, card=None, immediate=False):
        if card is None and self._modal_open():
            return
        card = card if card is not None else self._focused_card()
        banner = card.banner if card else ""
        if immediate or not banner or not self._window_props.get("hero_art"):
            self._cancel("hero_art")
            self._prop("hero_art", banner)
        else:
            self._later("hero_art", 0.18, lambda b=banner: self._prop("hero_art", b))
        info = sections.hero_info(card)
        if self._modal_open():
            info["has_guide"] = ""
            info["hero_guide"] = ""
        for k, v in info.items():
            self._prop(k, v)
        for cid, key in (
            (RESUME, "hero_play"), (BTN_ALT, "hero_alt"), (GUIDE_BUTTON, "hero_guide"), (BTN_FAV, "hero_fav"),
            (HERO_PLAY, "hero_play"), (HERO_ALT, "hero_alt"), (HERO_GUIDE, "hero_guide"), (HERO_FAV, "hero_fav"),
        ):
            try:
                self.getControl(cid).setLabel(info[key])
            except Exception:
                pass

    # -- section switching --

    def _restore_section_view(self):
        with self._lock:
            sec = self.section
            if sec == "channels":
                self._show_channels()
            elif sec == "continue":
                self._show_continue()
            elif sec == "favourites":
                self._show_favourites()
            elif sec == "shows":
                filtered = sections.filter_shows(self.shows_raw, self.show_filter)
                cards = [sections.show_card(r, self.fav_keys) for r in filtered]
                self.shows_all = cards
                self._apply_cards(cards[:PAGE_SIZE], empty_msg=words.tr("No shows with episodes in the archive yet."))
            elif sec in ("series", "movies"):
                cards = [sections.vod_card(r, kind="series" if sec == "series" else "movie",
                                          resume_doc=self.resume_doc, favs=self.fav_keys) for r in self.cat_items]
                self._apply_cards(cards, empty_msg=words.tr("Nothing here yet."))

    def _open_section(self, key, focus_cid="", sync_menu=False):
        with self._lock:
            self._pre_search_pos = None
            self.section = key
            self.page_query = ""
            self._prop("wide_grid", "1" if key in WIDE_SECTIONS else "")
            self._prop("section_title", words.section_title(key))
            self._sync_page_search_label()
            self._update_menu(follow=sync_menu)
            if key == "search":
                self._set_chips("search", sections.search_chips())
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
                self._set_chips("shows", sections.show_chips())
                self._prop("hint", words.section_hint("shows"))
                self._load_shows()
            elif key in ("series", "movies"):
                self.genre_id = 0
                self._set_chips(key, sections.catalog_chips(self.genres, self.sort_modes, self.sort_idx))
                self._prop("hint", words.section_hint("shows" if key == "series" else "films"))
                self._load_catalog(key, offset=0)
            elif key == "channels":
                self._show_channels(focus_cid)
        if self.cards and self.mode == data.DATA and self._focus() in (ROW, WIDE_ROW) and self._focus() != self._grid_id():
            self._focus_on(self._grid_id())
        self._qr_dirty = True
        self._save_quick_resume()

    def _save_quick_resume(self, immediate=False):
        if self.demo or not self.started or not self.signed or not self.section:
            return
        pos = self._active_grid_pos()
        card = self.cards[pos] if 0 <= pos < len(self.cards) else None
        fkey = card.key if card is not None else ""
        snap = quick_resume.build_sweettv_snapshot(
            section=self.section,
            filter=self.filter_key,
            focused_index=pos,
            focused_key=fkey,
            cards=self.cards[:24],
        )
        quick_resume.save_snapshot(
            "sweettv",
            "default",
            snap,
            debounce_s=0.0 if immediate else quick_resume.DEBOUNCE_S,
        )

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
        cards = self._continue_cards()
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
            if self._cancel_autoplay():
                return
            if self._modal_open():
                self._guide_close()
            elif self.digits:
                self._digits_clear()
            elif self.mode == data.DATA and self._focus() in (PAGE_SEARCH, HERO_PLAY, HERO_ALT, HERO_GUIDE, HERO_FAV):
                if self._focus() == PAGE_SEARCH and self._pre_search_pos is not None and self.cards:
                    pos = max(0, min(self._pre_search_pos, len(self.cards) - 1))
                    self._pre_search_pos = None
                    self._select_grid(pos)
                self._focus_on(self._grid_id() if self.cards else MENU)
            elif self.mode == data.DATA and self._focus() in (ROW, WIDE_ROW) and self.page_query:
                self.page_query = ""
                self._sync_page_search_label()
                self._restore_section_view()
            elif self.mode == data.DATA and self._focus() in (ROW, WIDE_ROW, RESUME, BTN_ALT, GUIDE_BUTTON, BTN_FAV,
                                                              HERO_PLAY, HERO_ALT, HERO_GUIDE, HERO_FAV,
                                                              *range(CHIP_FIRST, CHIP_LAST + 1)):
                self._focus_on(MENU)
            else:
                self.close()
            return
        if self.mode == data.DATA:
            digit = data.digit_of(action_id, action.getButtonCode())
            if self._modal_open():
                if self._focus() == GUIDE and action_id in (ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT) and self.modal_tabs:
                    step = -1 if action_id == ACTION_MOVE_LEFT else 1
                    target = max(0, min(len(self.modal_tabs) - 1, self.modal_tab_idx + step))
                    if target != self.modal_tab_idx:
                        self._modal_select_tab(target, keep_focus=True)
                    return
                if digit is not None or action_id == ACTION_CONTEXT_MENU:
                    return
            else:
                if action_id == ACTION_CONTEXT_MENU:
                    if self._focus() in (ROW, WIDE_ROW, RESUME, BTN_ALT, GUIDE_BUTTON, BTN_FAV,
                                         HERO_PLAY, HERO_ALT, HERO_GUIDE, HERO_FAV):
                        self._toggle_favourite()
                    return
                if digit is not None:
                    if self.numbered and self.section == "channels":
                        self._digit(digit)
                    return
                if action_id == ACTION_MOVE_RIGHT and self._focus() == MENU:
                    self._cancel("menu")
                    self._apply_menu()
                elif action_id == ACTION_MOVE_RIGHT and self._focus() == ROW:
                    pos = self._active_grid_pos()
                    if self.cards and (pos % 5 == 4 or pos == len(self.cards) - 1):
                        self._pre_search_pos = pos
                        self._focus_on(PAGE_SEARCH)
                        return
        super().onAction(action)
        if not self._modal_open() and self._focus() in (ROW, WIDE_ROW):
            self._sync_hero()
            if action_id in (ACTION_MOVE_RIGHT, ACTION_MOVE_DOWN):
                self._maybe_paginate()
            if PREVIEW_VIDEO:
                self._later("preview", PREVIEW_DELAY, self._preview_start)
        elif action_id in (ACTION_MOVE_UP, ACTION_MOVE_DOWN) and self._focus() == MENU:
            self._later("menu", MENU_DELAY, self._apply_menu)

    def onClick(self, control_id):
        try:
            if control_id in (ROW, WIDE_ROW):
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
                        self._focus_on(self._grid_id())
            elif control_id == RESUME:
                mk = getattr(self, "modal_kind", "")
                if mk == "show":
                    self._play_next_up()
                elif mk == "guide":
                    self._play_card(self.modal_card)
                elif mk == "detail":
                    self._play_card(self.modal_card, close_detail=True)
                else:
                    self._ok_card()
            elif control_id == HERO_PLAY:
                self._play_focused_card()
            elif control_id in (BTN_ALT, HERO_ALT):
                self._alt_action()
            elif control_id in (GUIDE_BUTTON, HERO_GUIDE):
                self._guide_show()
            elif control_id in (BTN_FAV, HERO_FAV):
                self._toggle_favourite()
            elif CHIP_FIRST <= control_id <= CHIP_LAST:
                self._chip_click(control_id)
            elif control_id == MODAL_TABS:
                self._modal_select_tab(self.getControl(MODAL_TABS).getSelectedPosition())
            elif control_id == GUIDE:
                self._modal_click()
            elif control_id == SIGNIN_BUTTON:
                self._signin()
            elif control_id == PAGE_SEARCH:
                self._ask_page_search()
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
        was_detail = getattr(self, "modal_kind", "") == "detail"
        card = getattr(self, "modal_card", None) if was_detail else self._focused_card()
        if card is None or card.kind == "skeleton":
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        if not was_detail and card.kind == "channel" and card.cid:
            self._open_channel_hub(card.cid)
            return
        if not was_detail and card.kind == "programme" and self.section == "search" and card.cid:
            self._open_channel_hub(card.cid, target_day=card.start, target_epg=card.epg)
            return
        if card.kind == "movie" and not was_detail and self.section not in WIDE_SECTIONS:
            self._open_detail_modal(card)
            return
        self._play_card(card, close_detail=was_detail)

    def _play_focused_card(self):
        card = self._focused_card()
        if card is None or card.kind == "skeleton":
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        self._play_card(card)

    def _play_card(self, card, from_start=False, close_detail=False):
        if card is None or card.kind == "skeleton":
            return
        url = card.alt_url if from_start else card.play_url
        if not card.playable or not url:
            ui.notify(words.tr("This programme has not aired yet."))
            return
        if close_detail:
            self._guide_close()
        if card.kind == "channel":
            if from_start and card.epg:
                session = play.Session(card.cid, card.epg, card.title, card.start, card.stop, url=url)
                notify_spec = {
                    "kind": "epg",
                    "cid": card.cid,
                    "epg_id": card.epg,
                    "start_offset": 0,
                    "from_start": True,
                    "title": card.title,
                }
                self._start_playback(url, cid=card.cid, session=session, notify_spec=notify_spec)
            else:
                notify_spec = {"kind": "live", "cid": card.cid, "title": card.title}
                self._start_playback(url, cid=card.cid, notify_spec=notify_spec)
        else:
            pos = 0 if from_start else card.resume_pos
            ep_mode = card.kind == "episode"
            session = play.Session(card.cid, card.epg, card.title, card.start, card.stop,
                                   url=url, episode_mode=ep_mode)
            notify_spec = {
                "url": url,
                "start_offset": pos,
                "from_start": bool(from_start),
                "title": card.title,
                "episode_mode": ep_mode,
            }
            self._start_playback(url, cid=card.cid, session=session, seek_to=pos, notify_spec=notify_spec)

    def _alt_action(self):
        card = getattr(self, "modal_card", None) if self._modal_open() else self._focused_card()
        if card is None:
            return
        if card.kind in ("show_vod", "show_epg", "show_tv", "series"):
            self._open_show_modal(card)
            return
        if card.alt_url:
            self._play_card(card, from_start=True, close_detail=(getattr(self, "modal_kind", "") == "detail"))

    # -- playback & resume --

    def _start_playback(self, url="", cid="", session=None, seek_to=0, notify_spec=None):
        if self.demo:
            ui.notify(words.tr("Demo: nothing is played."))
            return
        if not url and not notify_spec:
            return
        now = self._now()
        if PREVIEW_VIDEO and cid and session is None and self.previewing == cid and playing():
            xbmc.executebuiltin("Action(FullScreen)")
            self.play_at = now
            return
        spec = dict(notify_spec) if notify_spec else {
            "url": url,
            "start_offset": seek_to,
            "from_start": seek_to == 0,
        }
        payload_json = play.notify_request(**spec)
        with self._lock:
            if cid:
                self.state = saved.record_played(self.state, cid, now)
                self._update_menu()
            self.session = session
            self._autoplay_candidate = None
        if self.writer is not None and cid:
            self.writer.submit(self.state)
        self.play_at = now
        self._in_worker(self._start_stream, payload_json, session)

    def _start_stream(self, payload_json, session):
        xbmc.executeJSONRPC(payload_json)
        if session is not None:
            play.follow(session, self._player(), self._stop, self._report)

    def _player(self):
        if self._io is None:
            self._io = play.PlayerIO()
        return self._io

    def _next_episode_after(self, session):
        if self.modal_kind != "show" or not self.modal_seasons or session is None:
            return None
        s_url = session.url.split("?", 1)[0]
        for si, season in enumerate(self.modal_seasons):
            eps = season.get("episodes") or ()
            for ei, ep in enumerate(eps):
                ep_url = str(ep.get("vod_url") or ep.get("url") or "").split("?", 1)[0]
                match_url = bool(s_url and ep_url and ep_url == s_url)
                match_epg = bool(session.cid and session.epg
                                 and str(ep.get("cid") or "") == session.cid
                                 and str(ep.get("epg") or "") == session.epg)
                if match_url or match_epg:
                    if not self.modal_flat_tv:
                        if ei + 1 < len(eps):
                            return dict(eps[ei + 1]), int(season.get("number") or (si + 1))
                        if si + 1 < len(self.modal_seasons):
                            nxt_season = self.modal_seasons[si + 1]
                            nxt_eps = nxt_season.get("episodes") or ()
                            if nxt_eps:
                                return dict(nxt_eps[0]), int(nxt_season.get("number") or (si + 2))
                    elif ei > 0:
                        return dict(eps[ei - 1]), 1
                    return None
        return None

    def _cancel_autoplay(self) -> bool:
        had = bool(self._timers.get("autoplay") or self._autoplay_candidate or self._window_props.get("autoplay_text"))
        self._cancel("autoplay")
        self._autoplay_candidate = None
        self._prop("autoplay_text", "")
        return had

    def _start_autoplay(self, row, season_num, remaining=AUTOPLAY_SECONDS):
        if self._stop.is_set() or self.modal_kind != "show":
            self._cancel_autoplay()
            return
        if remaining <= 0:
            self._prop("autoplay_text", "")
            self._play_modal_row(row, season_num=season_num)
            return
        self._prop("autoplay_text", words.tr("Next episode in {n}s").format(n=remaining))
        self._later("autoplay", 1.0, lambda: self._start_autoplay(row, season_num, remaining - 1))

    def _report(self, session, pos, total):
        with self._lock:
            if self.session is not session:
                return
            self.session = None
            now = self._now()
            natural_end = bool(total > 0 and (total - pos <= mr.END_MARGIN or pos >= 0.97 * total))
            if natural_end and getattr(session, "episode_mode", False) and self.modal_kind == "show":
                self._autoplay_candidate = self._next_episode_after(session)
            else:
                self._autoplay_candidate = None
            if session.url:
                meta = {"title": session.title, "start": session.start, "stop": session.stop}
                if getattr(session, "season", 0) > 0:
                    meta["season"] = session.season
                if getattr(session, "episode", 0) > 0:
                    meta["episode"] = session.episode
                if getattr(session, "thumb", ""):
                    meta["thumb"] = session.thumb
                self.resume_doc = mr.record(self.resume_doc, session.url, pos, total, now, meta)
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
        if self.modal_kind == "show":
            self._refresh_show_modal_progress()
            with self._lock:
                cand = self._autoplay_candidate
                self._autoplay_candidate = None
            if cand is not None:
                self._start_autoplay(cand[0], cand[1])
        elif self.section == "continue" and not self._modal_open():
            self._show_continue()
        if self.mode == data.DATA and self._focus() not in (MENU, ROW, WIDE_ROW, PAGE_SEARCH, HERO_PLAY, HERO_ALT,
                                                             HERO_GUIDE, HERO_FAV, RESUME, BTN_ALT, GUIDE_BUTTON,
                                                             BTN_FAV, GUIDE):
            self._focus_on(GUIDE if self._modal_open() else self._grid_id())

    def _preview_start(self):
        card = self._focused_card()
        url = card.play_url if (card and card.kind == "channel" and not self.demo) else ""
        if url and self.mode == data.DATA and not self._modal_open():
            self.previewing = card.cid
            xbmc.Player().play(url, None, True)

    def _toggle_favourite(self):
        in_modal = self._modal_open()
        card = getattr(self, "modal_card", None) if in_modal else self._focused_card()
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
            updated = card._replace(fav=added)
            if in_modal:
                self.modal_card = updated
                self._sync_hero(updated, immediate=True)
                if self.modal_kind == "show":
                    self._sync_show_cta(self.modal_next_up)
                elif self.modal_kind == "guide" and self.modal_channel is not None:
                    self._sync_channel_hub_ctas(self.modal_channel, updated)
            pos = self._active_grid_pos()
            if self.section == "favourites" and not added and not in_modal:
                self._show_favourites()
                if self.cards:
                    self._select_grid(min(pos, len(self.cards) - 1))
            elif 0 <= pos < len(self.cards) and self.cards[pos].key == card.key:
                self.cards[pos] = updated
                for cid in (ROW, WIDE_ROW):
                    is_wide = cid == WIDE_ROW
                    try:
                        ctrl = self.getControl(cid)
                        li = ctrl.getListItem(pos) if hasattr(ctrl, "getListItem") else ctrl.items[pos]
                        self._shown_props[(cid, pos)] = items.apply_card(
                            li, updated, self._shown_props.get((cid, pos)), wide=is_wide
                        )
                    except Exception:
                        pass
                if not in_modal:
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
