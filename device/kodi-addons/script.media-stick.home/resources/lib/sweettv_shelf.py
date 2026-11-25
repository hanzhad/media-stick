"""SWEET.TV app: section switching, filter chips (401..408), Shows, paginated Movies/Series, and infinite scroll."""
import threading

import mediastick_sweetapi as sweetapi
from resources.lib import page_cache, prefetch, sweettv_demo, sweettv_pages as pages, sweettv_sections as sections, \
    sweettv_text as words, ui

PAGE_SIZE = 30
CHIP_FIRST, CHIP_LAST = 401, 408


class Shelf:
    def _shelf_setup(self):
        self.section = ""
        self.filter_key = "all"
        self.genre_id = 0
        self.sort_idx = 0
        self.sort_modes = list(sections.SORT_MODES_DEFAULT)
        self.genres = []
        self.chips = []
        self.cat_items = []
        self.cat_total = 0
        self.cat_loading = False
        self.cards = []
        self._section_gen = 0
        self._warm_handle = None

    def _cancel_warm(self):
        if self._warm_handle is not None:
            self._warm_handle.cancel()
            self._warm_handle = None

    def _set_chips(self, section, chips):
        self.chips = list(chips)
        visible = section in sections.FILTERED_SECTIONS
        self._prop("filters", "1" if visible else "")
        for idx, cid in enumerate(range(CHIP_FIRST, CHIP_LAST + 1)):
            label = chips[idx][1] if (visible and idx < len(chips)) else ""
            self.getControl(cid).setLabel(label)
            self._prop(f"chip_{cid}", label)
            if visible and idx < len(chips):
                key = chips[idx][0]
                active = (key == self.filter_key) or (section in ("movies", "series") and (
                    (key == "all" and self.genre_id == 0) or key == f"g:{self.genre_id}"))
                self._prop(f"chip_active_{cid}", "1" if active else "")
            else:
                self._prop(f"chip_active_{cid}", "")

    def _chip_click(self, cid):
        idx = cid - CHIP_FIRST
        with self._lock:
            if idx < 0 or idx >= len(self.chips):
                return
            key, _ = self.chips[idx]
            sec = self.section
        if sec == "search":
            self._ask_search()
            return
        if sec == "channels":
            with self._lock:
                self.filter_key = key
            self._show_channels()
            return
        if sec in ("movies", "series"):
            with self._lock:
                if key == "all":
                    self.genre_id = 0
                elif key == "sort":
                    self.sort_idx = (self.sort_idx + 1) % max(1, len(self.sort_modes))
                elif key.startswith("g:"):
                    gid = int(key[2:])
                    self.genre_id = 0 if self.genre_id == gid else gid
                self.cat_items = []
                self.cat_total = 0
            self._load_catalog(sec, offset=0)

    def _load_shows(self):
        with self._lock:
            self._section_gen += 1
            gen = self._section_gen
            demo = self.demo
            raw = self.raw_catalog
            favs = self.fav_keys
            now = self._now()
            self._prop("emptycat", words.tr("Loading…"))
        threading.Thread(target=self._run_shows, args=(gen, demo, raw, favs, now), daemon=True).start()

    def _run_shows(self, gen, demo, raw, favs, now):
        try:
            res = sweettv_demo.demo_shows(now, self.DEMO_LOGOS) if demo else sweetapi.shows(
                raw or {}, now=now, tr=words.tr)
            rows = res.get("items") or [] if res.get("ok") else []
            cards = [sections.show_card(r, favs) for r in rows]
            msg = words.tr("No shows with episodes in the archive yet.") if not cards else ""
        except Exception as e:
            ui.log(f"SWEET.TV shows failed: {e!r}")
            cards = []
            msg = words.tr("The list could not be loaded. Try again in a minute.")
        with self._lock:
            if self._stop.is_set() or gen != self._section_gen or self.section != "shows":
                return
            self._apply_cards(cards, empty_msg=msg)

    def _load_catalog(self, section, offset=0):
        with self._lock:
            if offset == 0:
                self._section_gen += 1
                self.cat_items = []
                self.cat_total = 0
                self._prop("emptycat", words.tr("Loading…"))
            gen = self._section_gen
            self.cat_loading = True
            demo = self.demo
            gid = self.genre_id
            modes = self.sort_modes or sections.SORT_MODES_DEFAULT
            sort_id = modes[self.sort_idx % len(modes)]["id"]
            resume_doc = self.resume_doc
            favs = self.fav_keys
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
                    cfg_modes = cfg.get("sort_modes") or list(sections.SORT_MODES_DEFAULT)
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
            if self.section not in ("movies", "series") or self.cat_loading:
                return
            if len(self.cards) >= self.cat_total or not self.cards:
                return
            pos = self.getControl(self.GRID_ID).getSelectedPosition()
            if pos < max(0, len(self.cards) - 4):
                return
            sec = self.section
            offset = len(self.cat_items)
        self._load_catalog(sec, offset=offset)
