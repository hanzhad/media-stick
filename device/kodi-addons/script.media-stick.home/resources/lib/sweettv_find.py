"""SWEET.TV app: Global Search and top-of-page scoped search per section."""
import re
import threading

import xbmcgui

import mediastick_sweetapi as sweetapi
from resources.lib import page_cache, sweettv_demo, sweettv_files as files, sweettv_pages as pages, \
    sweettv_sections as sections, sweettv_text as words, ui

_SERIES_SUBTITLE_RE = re.compile(r"(?:сериал|серіал|series|сезон)", re.I)


class Find:
    def _find_setup(self):
        self.search_query = ""
        self.page_query = ""
        self.search_cards = []
        self.search_filter = "all"
        self._search_gen = 0

    def _sync_page_search_label(self):
        q = self.search_query if self.section == "search" else getattr(self, "page_query", "")
        self._prop("page_search_label", words.page_search_label(self.section, q))

    def _load_top_search(self):
        with self._lock:
            self._search_gen += 1
            gen = self._search_gen
            demo = self.demo
            raw = self.raw_catalog
            resume_doc = self.resume_doc
            favs = self.fav_keys
            ns = None if demo else pages.namespace()
            ckey = pages.catalog_key("top_search") if ns else None
            hit = page_cache.get(ns, ckey, ttl=pages.PAGE_TTL, max_age=pages.PAGE_MAX_AGE) if (ns and ckey) else None
            if hit:
                parsed = pages.from_value("top_search", hit.value)
                if parsed:
                    _, rows, _ = parsed
                    cards = [sections.search_card(r, resume_doc, favs) for r in rows]
                    self.search_cards = cards
                    self._apply_cards(
                        sections.filter_search(cards, self.search_filter),
                        empty_msg=words.tr("Press OK to type what to look for."),
                    )
                    if not hit.stale:
                        return
                    t = threading.Timer(0.02, self._run_top_search, args=(gen, demo, raw, resume_doc, favs))
                    t.daemon = True
                    t.start()
                    return
            self._apply_cards(sections.skeleton_cards(5), empty_msg="")
        threading.Thread(target=self._run_top_search, args=(gen, demo, raw, resume_doc, favs), daemon=True).start()

    def _run_top_search(self, gen, demo, raw, resume_doc, favs):
        try:
            res = sweettv_demo.demo_top_search(self._now(), self.DEMO_LOGOS) if demo else sweetapi.top_search(
                raw or {}, now=self._now(), tr=words.tr, tr_n=words.tr_n)
            rows = res.get("items") or [] if res.get("ok") else []
            if not demo and rows:
                ns = pages.namespace()
                ckey = pages.catalog_key("top_search") if ns else None
                if ns and ckey:
                    sliced = list(rows)[:pages.MAX_SLICE]
                    page_cache.put(ns, ckey, pages.to_value("top_search", sliced, len(sliced)))
            cards = [sections.search_card(r, resume_doc, favs) for r in rows]
        except Exception as e:
            ui.log(f"SWEET.TV top_search failed: {e!r}")
            cards = []
        with self._lock:
            if self._stop.is_set() or gen != self._search_gen or self.section != "search" or self.search_query:
                return
            self.search_cards = cards
            self._apply_cards(sections.filter_search(cards, self.search_filter), empty_msg=words.tr("Press OK to type what to look for."))

    def _ask_search(self):
        with self._lock:
            default = self.search_query
        typed = xbmcgui.Dialog().input(words.tr("Search programmes and channels"), default)
        if typed is None:
            return
        query = typed.strip()
        if not query:
            return
        with self._lock:
            self.search_query = query
            self._sync_page_search_label()
            self._search_gen += 1
            gen = self._search_gen
            demo = self.demo
            raw = self.raw_catalog
            resume_doc = self.resume_doc
            favs = self.fav_keys
            self._prop("emptycat", words.tr("Searching…"))
        threading.Thread(target=self._run_search, args=(gen, query, demo, raw, resume_doc, favs), daemon=True).start()

    def _run_search(self, gen, query, demo, raw, resume_doc, favs):
        try:
            res = sweettv_demo.demo_search(query, self._now(), self.DEMO_LOGOS) if demo else sweetapi.search(
                query, raw or {}, now=self._now(), tr=words.tr, tr_n=words.tr_n)
            if not res.get("ok"):
                cards = []
                msg = res.get("message") or words.tr("The list could not be loaded. Try again in a minute.")
            elif res.get("short"):
                cards = []
                msg = words.tr("Type at least 2 letters.")
            else:
                cards = [sections.search_card(r, resume_doc, favs) for r in (res.get("items") or ())]
                msg = words.tr('Nothing found for "{q}".').format(q=query) if not cards else ""
        except Exception as e:
            ui.log(f"SWEET.TV search failed: {e!r}")
            cards = []
            msg = words.tr("The list could not be loaded. Try again in a minute.")
        with self._lock:
            if self._stop.is_set() or gen != self._search_gen or self.section != "search":
                return
            self.search_cards = cards
            self._apply_cards(sections.filter_search(cards, self.search_filter), empty_msg=msg)

    def _ask_page_search(self):
        if self.section == "search":
            self._ask_search()
            return
        with self._lock:
            sec = self.section
            default = self.page_query
        typed = xbmcgui.Dialog().input(words.page_search_prompt(sec), default)
        if typed is None:
            return
        query = typed.strip()
        if not query:
            with self._lock:
                self.page_query = ""
                self._sync_page_search_label()
            self._restore_section_view()
            return
        with self._lock:
            self.page_query = query
            self._sync_page_search_label()
            if sec == "channels" and self.catalog:
                ql = query.lower()
                matched = []
                for ch in sections.filter_channels(self.catalog.channels, self.filter_key):
                    if ql in ch.name.lower() or any(ql in p.title.lower() for p in ch.epg):
                        matched.append(ch)
                now = self._now()
                cards = [sections.channel_card(c, self.cat_names, now, self.resume_doc, self.fav_keys) for c in matched]
                self._apply_cards(cards, empty_msg=words.tr('Nothing found for "{q}".').format(q=query))
                return
            if sec == "continue":
                cards = self._continue_cards()
                filtered = sections.filter_local_cards(cards, query)
                self._apply_cards(filtered, empty_msg=words.tr('Nothing found for "{q}".').format(q=query))
                return
            if sec == "favourites":
                recall = None if self.demo else files.recall_title_detail
                cards = sections.favourites_cards(
                    self.favs_doc, self.catalog, self.cat_names, self._now(), self.resume_doc, recall_title=recall
                )
                filtered = sections.filter_local_cards(cards, query)
                self._apply_cards(filtered, empty_msg=words.tr('Nothing found for "{q}".').format(q=query))
                return
            self._search_gen += 1
            gen = self._search_gen
            demo = self.demo
            raw = self.raw_catalog
            resume_doc = self.resume_doc
            favs = self.fav_keys
            shows_raw = list(self.shows_raw)
            cat_items = list(self.cat_items)
            self._prop("emptycat", words.tr("Searching…"))
        threading.Thread(
            target=self._run_scoped_search,
            args=(gen, sec, query, demo, raw, resume_doc, favs, shows_raw, cat_items),
            daemon=True,
        ).start()

    def _run_scoped_search(self, gen, sec, query, demo, raw, resume_doc, favs, shows_raw, cat_items):
        ql = query.lower()
        cards = []
        msg = ""
        try:
            res = sweettv_demo.demo_search(query, self._now(), self.DEMO_LOGOS) if demo else sweetapi.search(
                query, raw or {}, now=self._now(), tr=words.tr, tr_n=words.tr_n)
            if res.get("ok") and not res.get("short"):
                known_series = {str(r.get("id") or "") for r in cat_items if r.get("kind") == "series"}
                raw_cards = []
                for row in (res.get("items") or ()):
                    if sec == "series" and row.get("kind") == "movie":
                        mid = str(row.get("id") or "")
                        if mid in known_series or _SERIES_SUBTITLE_RE.search(str(row.get("subtitle") or "")):
                            row = {**row, "kind": "series"}
                    raw_cards.append(sections.search_card(row, resume_doc, favs))
                cards = sections.filter_section_search(raw_cards, sec)
            elif not res.get("ok"):
                msg = res.get("message") or words.tr("The list could not be loaded. Try again in a minute.")
        except Exception as e:
            ui.log(f"SWEET.TV scoped search failed: {e!r}")
            msg = words.tr("The list could not be loaded. Try again in a minute.")

        # Merge cached section items matching title locally so loaded shows/series/movies are always discoverable
        seen = {c.key for c in cards}
        seen_titles = {c.title.lower() for c in cards}
        if sec == "shows":
            for row in shows_raw:
                if ql in str(row.get("title") or "").lower():
                    c = sections.show_card(row, favs)
                    if c.key not in seen and c.title.lower() not in seen_titles:
                        cards.append(c)
                        seen.add(c.key)
                        seen_titles.add(c.title.lower())
        elif sec in ("series", "movies"):
            want_kind = "series" if sec == "series" else "movie"
            for row in cat_items:
                if ql in str(row.get("title") or "").lower():
                    c = sections.vod_card(row, kind=want_kind, resume_doc=resume_doc, favs=favs)
                    if c.key not in seen and c.title.lower() not in seen_titles:
                        cards.append(c)
                        seen.add(c.key)
                        seen_titles.add(c.title.lower())

        if not cards and not msg:
            msg = words.tr('Nothing found for "{q}".').format(q=query)
        with self._lock:
            if self._stop.is_set() or gen != self._search_gen or self.section != sec or self.page_query != query:
                return
            self._apply_cards(cards, empty_msg=msg)
