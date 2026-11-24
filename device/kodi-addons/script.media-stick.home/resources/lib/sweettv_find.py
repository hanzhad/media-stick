"""SWEET.TV app: the menu entry "Search". OK on it asks for words with Kodi on-screen keyboard (on a worker thread: a dialog
never blocks the UI), asks SWEET.TV own search for them (mediastick_sweetapi: the guide of the last days, not only the few
programmes the channel list holds) and puts the cards of what it found in the row (sweettv_search makes them). OK on a card
plays it: a programme from its start in the archive, a channel or a programme that is on now live; one that is not in the
archive (or not on air yet) says so. Over the row the focused card says its title, channel, date and time, and "Live" when it
is on now.

A mixin of the window (sweettv_app.SweetTV), kept apart to keep that file small. It relies on what the window has: _lock, _stop,
_prop, _in_worker, _focus_on, _hint, _update_menu, _fill_cards, _start, _now, catalog, demo, list_token, row_kind, shown, rows,
trail, cat_key, GRID_ID (the row) and MENU_ID (the menu). The last query and what it found are kept while the window is open: the menu going
back to Search shows them again, and the row stays on them until another entry is chosen.
"""
from resources.lib import sweettv_search as search, sweettv_text as words, sweettv_view as view, ui
from resources.lib.sweettv_sections import SEARCH

IDLE = "Press OK to type what to look for."
SHORT = "Type at least 2 letters."
NOTHING = "Nothing found for \"{q}\"."
HEADING = "Search programmes and channels"


class Find:
    def _find_setup(self):
        self.query = ""                          # the last words typed, kept while the window is open
        self.found = []                          # the cards they found (sweettv_sections.Row)
        self.found_note = ""                     # what the empty row says about them: nothing found, an error
        self.find_token = 0                      # a search is dropped when a newer one has begun

    def _menu_key(self) -> str:
        """The key of the menu entry under the cursor ("" for none)."""
        position = self.getControl(self.MENU_ID).getSelectedPosition()
        return self.entries[position].key if 0 <= position < len(self.entries) else ""

    def _open_search(self):
        """The row shows the cards of the last search (under the lock): the menu has come to Search."""
        self.list_token += 1                     # a list that is being made for another entry is dropped
        self.row_kind, self.shown, self.cat_key = SEARCH, [], SEARCH
        self._fill_cards(SEARCH, "", self.found, len(self.found), self.found_note or words.tr(IDLE), None)
        self._prop("hint", self._hint())
        self._update_menu()

    def _search_ask(self):
        """OK on the menu's Search: the keyboard, then the search, on a worker."""
        self._in_worker(self._search_dialog)

    def _search_dialog(self):
        query = " ".join(str(self._ask_text(self.query) or "").split())
        if query:                                # cancelled, or nothing typed: what is on screen stays
            self._search_run(query)

    def _ask_text(self, default) -> str:
        """The words the person types on the on-screen keyboard; "" when it is cancelled."""
        import xbmcgui
        return xbmcgui.Dialog().input(words.tr(HEADING), default or "")

    def _search_run(self, query):
        """Look for `query` and show what was found, unless another search has begun, or the row is on another entry by then
        (the cards are kept for the next visit)."""
        now = self._now()
        with self._lock:
            self.find_token += 1
            token, self.query = self.find_token, query
            if self.row_kind == SEARCH:
                self._fill_cards(SEARCH, "", [], 0, words.tr("Searching…"), None)
        rows, note = self._search_rows(query, now)
        with self._lock:
            if token != self.find_token or self._stop.is_set():
                return
            self.found, self.found_note = rows, note
            drawn = self.row_kind == SEARCH
            if drawn:
                self._fill_cards(SEARCH, "", rows, len(rows), note, None)
        if drawn and rows:
            self._focus_on(self.GRID_ID)

    def _search_rows(self, query, now):
        """(cards, what to say when there are none) for `query`. Slow, nothing held: the network."""
        api = search._libs()
        if api is None:
            return [], words.tr("SWEET.TV is not available on this device.")
        channels = search.channels_of(self.catalog)
        if self.demo:
            if len(query) < api.MIN_NEEDLE:
                return [], words.tr(SHORT)
            items = api.normalize_search(search.demo_reply(self.catalog, query, now), channels, now, words.tr, words.tr_n)
            found = {"ok": True, "items": items}
        else:
            found = api.search(query, channels, now, tr=words.tr, tr_n=words.tr_n)
        if not found["ok"]:
            return [], found["message"]
        if found.get("short"):
            return [], words.tr(SHORT)
        logos = {c.cid: c.logo for c in self.catalog.channels if c.logo} if self.catalog else {}
        cards = search.rows(found["items"], now, logos)
        return cards, "" if cards else words.tr(NOTHING).format(q=query)

    def _ok_result(self, row):
        """OK on a card of the search: play it (a programme from the archive, a channel or what is on now live), or say why not."""
        if row.playable and row.epg:
            self._start(row.cid, view.GuideRow(row.epg, row.name or row.title, "", "archive", row.start, row.stop))
        elif row.playable:
            self._start(row.cid)
        else:
            ui.notify(words.tr("This programme has not aired yet." if row.future else
                               "This programme is not in the archive." if row.epg else "This channel is not in the list."))
