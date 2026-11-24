"""SWEET.TV app: Search section (popular top_search before typing, keyboard -> API.search)."""
import threading

import xbmcgui

import mediastick_sweetapi as sweetapi
from resources.lib import sweettv_demo, sweettv_sections as sections, sweettv_text as words, ui


class Find:
    def _find_setup(self):
        self.search_query = ""
        self.search_cards = []
        self._search_gen = 0

    def _load_top_search(self):
        with self._lock:
            self._search_gen += 1
            gen = self._search_gen
            demo = self.demo
            raw = self.raw_catalog
            resume_doc = self.resume_doc
            favs = self.fav_keys
            self._prop("emptycat", words.tr("Loading…"))
        threading.Thread(target=self._run_top_search, args=(gen, demo, raw, resume_doc, favs), daemon=True).start()

    def _run_top_search(self, gen, demo, raw, resume_doc, favs):
        try:
            res = sweettv_demo.demo_top_search(self._now(), self.DEMO_LOGOS) if demo else sweetapi.top_search(
                raw or {}, now=self._now(), tr=words.tr, tr_n=words.tr_n)
            rows = res.get("items") or [] if res.get("ok") else []
            cards = [sections.search_card(r, resume_doc, favs) for r in rows]
        except Exception as e:
            ui.log(f"SWEET.TV top_search failed: {e!r}")
            cards = []
        with self._lock:
            if self._stop.is_set() or gen != self._search_gen or self.section != "search" or self.search_query:
                return
            self.search_cards = cards
            self._apply_cards(cards, empty_msg=words.tr("Press OK to type what to look for."))

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
            self._apply_cards(cards, empty_msg=msg)
