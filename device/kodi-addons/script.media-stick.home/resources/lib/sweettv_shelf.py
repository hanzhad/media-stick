"""SWEET.TV app: section switching, filter chips list (409), Shows, paginated Movies/Series, and infinite scroll."""
import threading

import mediastick_sweetapi as sweetapi
from resources.lib import page_cache, prefetch, sweettv_demo, sweettv_items as items, sweettv_pages as pages, \
    sweettv_sections as sections, sweettv_text as words, ui

PAGE_SIZE = 30
CHIPS = 409
CHIP_LOCAL_DELAY = 0.12
CHIP_REMOTE_DELAY = 0.28
ACTION_CHIPS = frozenset(("new", "sort"))


class Shelf:
    def _shelf_setup(self):
        self.section = ""
        self.filter_key = "main"
        self.genre_id = 0
        self.sort_idx = 0
        self.sort_modes = list(sections.SORT_MODES_DEFAULT)
        self.genres = []
        self.chips = []
        self._chip_sig = None
        self._pending_chip_key = ""
        self.cat_items = []
        self.cat_total = 0
        self.cat_loading = False
        self.cards = []
        self.show_filter = "all"
        self.shows_raw = []
        self.shows_all = []
        self._sec_cache = {}
        self._section_gen = 0
        self._warm_handle = None

    def _cancel_warm(self):
        if self._warm_handle is not None:
            self._warm_handle.cancel()
            self._warm_handle = None

    def _active_chip_key(self, section=None) -> str:
        sec = self.section if section is None else section
        if sec == "search":
            return getattr(self, "search_filter", "all")
        if sec == "shows":
            return self.show_filter
        if sec == "channels":
            return self.filter_key
        if sec in ("movies", "series"):
            return "all" if self.genre_id == 0 else f"g:{self.genre_id}"
        return ""

    def _selected_chip_key(self) -> str:
        try:
            pos = self.getControl(CHIPS).getSelectedPosition()
        except RuntimeError:
            return ""
        return self.chips[pos][0] if 0 <= pos < len(self.chips) else ""

    def _set_chips(self, section, chips):
        self.chips = list(chips)
        visible = section in sections.FILTERED_SECTIONS and bool(self.chips)
        self._prop("filters", "1" if visible else "")
        try:
            ctrl = self.getControl(CHIPS)
        except RuntimeError:
            return
        if not visible:
            self._chip_sig = None
            ctrl.reset()
            return
        active_key = self._active_chip_key(section)
        sig = (section, tuple(k for k, _ in self.chips))
        size = ctrl.size() if hasattr(ctrl, "size") else len(ctrl.items)
        if self._chip_sig == sig and size == len(self.chips):
            for idx, (key, label) in enumerate(self.chips):
                li = ctrl.getListItem(idx) if hasattr(ctrl, "getListItem") else ctrl.items[idx]
                li.setLabel(str(label))
                li.setProperty("active", "1" if key == active_key else "")
            return
        self._chip_sig = sig
        ctrl.reset()
        ctrl.addItems(items.chip_items(self.chips, active_key))
        sel = next((i for i, (k, _) in enumerate(self.chips) if k == active_key), 0)
        ctrl.selectItem(sel)

    def _cancel_chip(self):
        self._pending_chip_key = ""
        self._cancel("chip")

    def _on_chip_timer(self, expected_sec, key):
        if self._stop.is_set() or self.section != expected_sec:
            return
        self._apply_chip_key(key, allow_action=False)

    def _flush_chip(self):
        with self._lock:
            pending = self._pending_chip_key
            had_timer = self._timers.get("chip") is not None
            self._cancel_chip()
            key = pending if had_timer else self._selected_chip_key()
            active = self._active_chip_key()
        if key and key not in ACTION_CHIPS and key != active:
            self._apply_chip_key(key, allow_action=False)

    def _apply_chip_key(self, key, allow_action=False):
        if not key or (not allow_action and key in ACTION_CHIPS):
            return
        with self._lock:
            self._pending_chip_key = ""
            sec = self.section
        if sec == "search":
            if key == "new":
                self._ask_search()
                return
            with self._lock:
                if self.search_filter != key:
                    self.page_query = ""
                    self._sync_page_search_label()
                self.search_filter = key
                self._set_chips("search", sections.search_chips())
                self._apply_cards(sections.filter_search(self.search_cards, self.search_filter),
                                  empty_msg=words.tr("Press OK to type what to look for."))
            return
        if sec == "shows":
            with self._lock:
                if self.show_filter != key:
                    self.page_query = ""
                    self._sync_page_search_label()
                self.show_filter = key
                self._set_chips("shows", sections.show_chips())
                filtered = sections.filter_shows(self.shows_raw, self.show_filter)
                cards = [sections.show_card(r, self.fav_keys) for r in filtered]
                self.shows_all = cards
                msg = words.tr("No shows with episodes in the archive yet.") if not cards else ""
                self._apply_cards(cards[:PAGE_SIZE], empty_msg=msg)
            return
        if sec == "channels":
            with self._lock:
                if self.filter_key != key:
                    self.page_query = ""
                    self._sync_page_search_label()
                self.filter_key = key
            self._show_channels()
            return
        if sec in ("movies", "series"):
            with self._lock:
                if key == "sort":
                    self.sort_idx = (self.sort_idx + 1) % max(1, len(self.sort_modes))
                    self.page_query = ""
                    self._sync_page_search_label()
                    self.cat_items = []
                    self.cat_total = 0
                    self._set_chips(sec, sections.catalog_chips(self.genres, self.sort_modes, self.sort_idx))
                elif key == "all" or key.startswith("g:"):
                    gid = 0 if key == "all" else int(key[2:])
                    if self.genre_id == gid and not self.page_query:
                        return
                    self.genre_id = gid
                    self.page_query = ""
                    self._sync_page_search_label()
                    self.cat_items = []
                    self.cat_total = 0
                    self._set_chips(sec, sections.catalog_chips(self.genres, self.sort_modes, self.sort_idx))
                else:
                    return
            self._load_catalog(sec, offset=0)

    def _chip_click(self):
        self._cancel_chip()
        self._apply_chip_key(self._selected_chip_key(), allow_action=True)

    def _load_shows(self):
        with self._lock:
            self._section_gen += 1
            gen = self._section_gen
            demo = self.demo
            raw = self.raw_catalog
            favs = self.fav_keys
            now = self._now()
            mem = self._sec_cache.get("shows")
            if mem and now - mem[0] < 600:
                rows, msg = mem[1], mem[2]
                self.shows_raw = list(rows)
                filtered = sections.filter_shows(rows, self.show_filter)
                cards = [sections.show_card(r, favs) for r in filtered]
                self.shows_all = cards
                self._apply_cards(cards[:PAGE_SIZE], empty_msg=msg)
                return
            ns = None if demo else pages.namespace()
            ckey = pages.catalog_key("shows") if ns else None
            hit = page_cache.get(ns, ckey, ttl=pages.PAGE_TTL, max_age=pages.PAGE_MAX_AGE) if (ns and ckey) else None
            if hit:
                parsed = pages.from_value("shows", hit.value)
                if parsed:
                    _, rows, _ = parsed
                    self.shows_raw = list(rows)
                    filtered = sections.filter_shows(rows, self.show_filter)
                    cards = [sections.show_card(r, favs) for r in filtered]
                    self.shows_all = cards
                    self._sec_cache["shows"] = (now, rows, "")
                    self._apply_cards(cards[:PAGE_SIZE], empty_msg="")
                    if not hit.stale:
                        return
                    threading.Thread(target=self._run_shows, args=(gen, demo, raw, favs, now), daemon=True).start()
                    return
            self.shows_raw = []
            self.shows_all = []
            self._apply_cards(sections.skeleton_cards(5), empty_msg="")
        threading.Thread(target=self._run_shows, args=(gen, demo, raw, favs, now), daemon=True).start()

    def _run_shows(self, gen, demo, raw, favs, now):
        try:
            res = sweettv_demo.demo_shows(now, self.DEMO_LOGOS) if demo else sweetapi.shows(
                raw or {}, now=now, tr=words.tr)
            rows = res.get("items") or [] if res.get("ok") else []
            msg = words.tr("No shows with episodes in the archive yet.") if not rows else ""
            if not demo and rows:
                ns = pages.namespace()
                ckey = pages.catalog_key("shows") if ns else None
                if ns and ckey:
                    page_cache.put(ns, ckey, pages.to_value("shows", rows[:pages.MAX_SLICE], len(rows)))
        except Exception as e:
            ui.log(f"SWEET.TV shows failed: {e!r}")
            rows = []
            msg = words.tr("The list could not be loaded. Try again in a minute.")
        with self._lock:
            if rows:
                self._sec_cache["shows"] = (self._now(), rows, msg)
                self.shows_raw = list(rows)
            if self._stop.is_set() or gen != self._section_gen or self.section != "shows":
                return
            filtered = sections.filter_shows(rows, self.show_filter)
            cards = [sections.show_card(r, favs) for r in filtered]
            self.shows_all = cards
            fmsg = words.tr("No shows with episodes in the archive yet.") if not cards else msg
            self._apply_cards(cards[:PAGE_SIZE], empty_msg=fmsg)

    def _load_catalog(self, section, offset=0):
        with self._lock:
            demo = self.demo
            gid = self.genre_id
            modes = self.sort_modes or sections.SORT_MODES_DEFAULT
            sort_id = modes[self.sort_idx % len(modes)]["id"]
            resume_doc = self.resume_doc
            favs = self.fav_keys
            now = self._now()
            kind = "series" if section == "series" else "movie"
            if offset == 0:
                self._section_gen += 1
                self.cat_items = []
                self.cat_total = 0
                mem = self._sec_cache.get((section, gid, sort_id))
                if mem and now - mem[0] < 600:
                    self.cat_items, self.cat_total = list(mem[1]), mem[2]
                    cards = [sections.vod_card(x, kind, resume_doc, favs) for x in self.cat_items]
                    self._apply_cards(cards, empty_msg=words.tr("No films in the archive yet."))
                    if not self.genres:
                        gen = self._section_gen
                        threading.Thread(target=self._refresh_catalog_meta, args=(gen, section, demo), daemon=True).start()
                    return
                ns = None if demo else pages.namespace()
                ckey = pages.catalog_key(section, gid, sort_id, 0)
                hit = page_cache.get(ns, ckey, ttl=pages.PAGE_TTL, max_age=pages.PAGE_MAX_AGE) if (ns and ckey) else None
                if hit:
                    parsed = pages.from_value(section, hit.value)
                    if parsed:
                        _, items, total = parsed
                        self.cat_items, self.cat_total = list(items), total
                        self._sec_cache[(section, gid, sort_id)] = (now, list(items), total)
                        cards = [sections.vod_card(x, kind, resume_doc, favs) for x in self.cat_items]
                        self._apply_cards(cards, empty_msg=words.tr("No films in the archive yet."))
                        gen = self._section_gen
                        if not self.genres:
                            threading.Thread(target=self._refresh_catalog_meta, args=(gen, section, demo), daemon=True).start()
                        if hit.stale:
                            threading.Thread(target=self._revalidate_catalog,
                                             args=(gen, section, gid, sort_id, 0, ns, ckey, resume_doc, favs), daemon=True).start()
                        return
                self._apply_cards(sections.skeleton_cards(5), empty_msg="")
            gen = self._section_gen
            self.cat_loading = True
            need_cfg = not self.genres
        threading.Thread(
            target=self._run_catalog,
            args=(gen, section, gid, sort_id, offset, demo, resume_doc, favs, need_cfg),
            daemon=True,
        ).start()

    def _run_catalog(self, gen, section, gid, sort_id, offset, demo, resume_doc, favs, need_cfg):
        cfg_genres = cfg_modes = None
        if need_cfg:
            try:
                cfg = sweettv_demo.demo_config() if demo else sweetapi.configuration(tr=words.tr)
                if cfg.get("ok"):
                    cfg_genres = cfg.get("genres") or []
                    cfg_modes = sections.valid_sort_modes(cfg.get("sort_modes"))
            except Exception as e:
                ui.log(f"SWEET.TV config failed: {e!r}")

        ns = None if demo else pages.namespace()
        ckey = pages.catalog_key(section, gid, sort_id, offset)
        cached = None
        hit_stale = False
        if ns and ckey:
            hit = page_cache.get(ns, ckey, ttl=pages.PAGE_TTL, max_age=pages.PAGE_MAX_AGE)
            if hit:
                parsed = pages.from_value(section, hit.value)
                if parsed:
                    cached = parsed
                    hit_stale = bool(hit.stale)
                elif isinstance(hit.value, dict) and hit.value.get("lang") != words.LANG:
                    parsed = pages.from_value(section, {**hit.value, "lang": words.LANG})
                    if parsed:
                        cached = parsed
                        hit_stale = True
        if cached is not None:
            _, items, total = cached
            ok = True
        else:
            try:
                res = (sweettv_demo.demo_catalog_page(section, gid, sort_id, offset, PAGE_SIZE, self.DEMO_LOGOS)
                       if demo else sweetapi.catalog_page(section, genre_id=gid, sort_mode_id=sort_id,
                                                          offset=offset, limit=PAGE_SIZE, tr=words.tr))
                ok = bool(res.get("ok"))
                items = list(res.get("items") or ()) if ok else []
                total = int(res.get("total") or len(items)) if ok else 0
                if ok and items and ns and ckey and len(items) <= pages.MAX_SLICE:
                    page_cache.put(ns, ckey, pages.to_value(section, items, total))
            except Exception as e:
                ui.log(f"SWEET.TV catalog failed: {e!r}")
                ok, items, total = False, [], 0

        with self._lock:
            self.cat_loading = False
            if self._stop.is_set() or gen != self._section_gen or self.section != section:
                return
            if cfg_genres is not None:
                self.genres = cfg_genres
            if cfg_modes:
                self.sort_modes = cfg_modes
            self._set_chips(section, sections.catalog_chips(self.genres, self.sort_modes, self.sort_idx))
            if offset == 0:
                self.cat_items = items
                if ok and items:
                    self._sec_cache[(section, gid, sort_id)] = (self._now(), list(items), total)
            else:
                seen = {str(x.get("id")) for x in self.cat_items}
                self.cat_items.extend(x for x in items if str(x.get("id")) not in seen)
            self.cat_total = total
            kind = "series" if section == "series" else "movie"
            cards = [sections.vod_card(x, kind, resume_doc, favs) for x in self.cat_items]
            msg = "" if cards else (words.tr("No films in the archive yet.") if ok
                                    else words.tr("The list could not be loaded. Try again in a minute."))
            self._apply_cards(cards, empty_msg=msg, keep_pos=(offset > 0))
        if hit_stale:
            t = threading.Timer(
                0.01,
                self._revalidate_catalog,
                args=(gen, section, gid, sort_id, offset, ns, ckey, resume_doc, favs),
            )
            t.daemon = True
            t.start()
        if ok and not demo:
            self._start_warm()

    def _revalidate_catalog(self, gen, section, gid, sort_id, offset, ns, ckey, resume_doc, favs):
        try:
            res = sweetapi.catalog_page(section, genre_id=gid, sort_mode_id=sort_id,
                                        offset=offset, limit=PAGE_SIZE, tr=words.tr)
            if not res.get("ok"):
                return
            items = list(res.get("items") or ())
            total = int(res.get("total") or len(items))
            if items and len(items) <= pages.MAX_SLICE:
                page_cache.put(ns, ckey, pages.to_value(section, items, total))
            if offset != 0 or not items:
                return
            with self._lock:
                if self._stop.is_set() or gen != self._section_gen or self.section != section:
                    return
                self.cat_items = items
                self.cat_total = total
                self._sec_cache[(section, gid, sort_id)] = (self._now(), list(items), total)
                kind = "series" if section == "series" else "movie"
                cards = [sections.vod_card(x, kind, resume_doc, favs) for x in self.cat_items]
                self._apply_cards(cards, keep_pos=True)
        except Exception as e:
            ui.log(f"SWEET.TV revalidate failed: {e!r}")

    def _shelf_idle(self):
        return not self._stop.is_set() and not self.cat_loading and not self._playing()

    def _start_warm(self):
        if self.demo or not getattr(self, "signed", False):
            return
        ns = pages.namespace()
        if not ns:
            return
        jobs = []
        for sec in ("movies", "series"):
            ckey = pages.catalog_key(sec, 0, 1, 0)
            if ckey:
                def _fetch(s=sec):
                    res = sweetapi.catalog_page(s, genre_id=0, sort_mode_id=1, offset=0, limit=PAGE_SIZE, tr=words.tr)
                    if res.get("ok") and res.get("items"):
                        items = list(res["items"])
                        return pages.to_value(s, items, int(res.get("total") or len(items)))
                    return None
                jobs.append((ckey, _fetch))
        if jobs:
            self._warm_handle = prefetch.warm(ns, jobs, ttl=pages.PAGE_TTL, idle=self._shelf_idle)

    def _maybe_paginate(self):
        with self._lock:
            if self.section == "shows":
                if not self.cards or len(self.cards) >= len(self.shows_all):
                    return
                pos = self.getControl(self._grid_id()).getSelectedPosition()
                if pos < max(0, len(self.cards) - 10):
                    return
                nxt = min(len(self.shows_all), len(self.cards) + PAGE_SIZE)
                self._apply_cards(self.shows_all[:nxt], empty_msg="", keep_pos=True)
                return
            if self.section not in ("movies", "series") or self.cat_loading:
                return
            if len(self.cards) >= self.cat_total or not self.cards:
                return
            pos = self.getControl(self._grid_id()).getSelectedPosition()
            if pos < max(0, len(self.cards) - 10):
                return
            sec = self.section
            offset = len(self.cat_items)
        self._load_catalog(sec, offset=offset)

    def _refresh_catalog_meta(self, gen, section, demo):
        try:
            cfg = sweettv_demo.demo_config() if demo else sweetapi.configuration(tr=words.tr)
            if not cfg.get("ok"):
                return
            cfg_genres = cfg.get("genres") or []
            cfg_modes = sections.valid_sort_modes(cfg.get("sort_modes"))
        except Exception:
            return
        with self._lock:
            if self._stop.is_set() or gen != self._section_gen or self.section != section:
                return
            self.genres = cfg_genres
            self.sort_modes = cfg_modes
            self._set_chips(section, sections.catalog_chips(self.genres, self.sort_modes, self.sort_idx))
