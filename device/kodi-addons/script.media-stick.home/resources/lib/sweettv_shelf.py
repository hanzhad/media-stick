"""SWEET.TV app: the row of cards along the bottom when the menu is on "Shows and series" or "Films": a card per show or per
film, and after OK on a show a card per episode. The channels (the other entries of the menu) are the window's own.

A mixin of the window (sweettv_app.SweetTV), kept apart to keep that file small. It relies on what the window has: _lock,
_stop, _prop, _later, _cancel, _in_worker, _focus_on, _update_menu, _hint, _start, _demo_raw, _now, _playing, getControl, the
attributes catalog, shown, cat_key, demo and GRID_ID (the row). The rows are sweettv_sections', the cards sweettv_items'.

What the row holds (row_kind) is CHANNELS or one of sweettv_sections.SECTIONS. A list is made lazily on a worker thread (the
index reads the file) and "Loading..." is said in the empty row meanwhile; it is let go two minutes after the row is back on
channels. The lists that were made are also kept on disk (page_cache, namespace "sweettv:main", see sweettv_pages): a list
seen before shows at once, even in the next launch; one older than five minutes is made again in the background and swapped
in only if the person is still on it and it changed (the cursor stays on its card); a list that cannot be made leaves the one
on screen, a section that is empty now drops its page. Right after the catalog is shown the shows and the films are made one
after the other (prefetch, at a low priority, only while nothing is loading and no video plays), so that their counts are in
the menu and their cards are there when the person gets to them. Signed out, the pages of the account go. The channels are not
kept: they are the file the plugin keeps already.
"""
import xbmc

from resources.lib import page_cache, prefetch, sweettv_files as files, sweettv_items as items, sweettv_pages as pages, \
    sweettv_sections as sections, sweettv_text as words, sweettv_view as view, ui

CHANNELS, SHOWS, FILMS, EPISODES = sections.CHANNELS, sections.SHOWS, sections.FILMS, sections.EPISODES
LIBRARY_KEEP = 120               # s the index of the shows and films is kept after the row is back on channels
PAGES = True                     # the lists are kept on disk (page_cache) and the shows and films are made at start-up (prefetch)
LOAD_FAILED = "The list could not be loaded. Try again in a minute."


class Shelf:
    def _shelf_setup(self):
        self.library = sections.Library()        # the index of the shows and films, while they are looked at
        self.row_kind = CHANNELS                 # what the row holds: CHANNELS, SHOWS, EPISODES or FILMS
        self.rows = []                           # the cards of the row when it is not channels (sweettv_sections.Row)
        self.trail = []                          # where Back goes from the episodes of a show: [(kind, show id, cursor)]
        self.page = ("", 0)                      # (title, how many) of the list on screen
        self.list_token = 0                      # a list that is being made for an older token is dropped
        self.list_loading = 0                    # lists being made on a worker (the start-up prefetch waits for it to be 0)
        self.warming = None                      # the prefetch run (prefetch.Handle) that makes the shows and films at start-up
        self.counts = None                       # (shows, films) when they are known, for the menu
        self.enter_row = False                   # Right or OK on the menu found the row empty: the focus goes in when it has cards
        self.signed = False                      # the plugin is signed in (the disk cache is the account's, kept only while it is)
        self.dropped = False                     # the pages of a signed-out account are gone

    # -- what is on screen --

    def _row_size(self) -> int:
        return len(self.shown) or len(self.rows)

    def _card(self):
        """(position, Row) under the cursor of the row while it holds shows, films or episodes; None otherwise."""
        try:
            position = self.getControl(self.GRID_ID).getSelectedPosition()
        except RuntimeError:
            return None
        return (position, self.rows[position]) if 0 <= position < len(self.rows) else None

    def _open_section(self, kind, sid="", select=None):
        """Show the cards of `kind` (the shows, the episodes of show `sid`, the films). A list kept on disk shows at once; one
        older than its ttl (or that is not there: an empty row that says "Loading...") is made on a worker thread and replaces
        it when it differs. `select` is the card the cursor goes to when the cards are there."""
        with self._lock:
            self._cancel("library")
            self.list_token += 1
            token, self.row_kind, self.shown = self.list_token, kind, []
            if kind != EPISODES:
                self.cat_key = kind
            stored = self._stored(kind, sid)
            if stored is not None:
                self._fill_cards(kind, stored[0], stored[1], stored[2], "", select)
            else:
                self.rows, self.page = [], ("", 0)
                self.getControl(self.GRID_ID).reset()
                self._prop("emptycat", words.tr("Loading…"))
            self._prop("hint", self._hint())
            self._update_menu()
            asking = stored is None or stored[3]
            if asking:
                self.list_loading += 1
        if asking:
            self._in_worker(self._load_list, kind, sid, token, select, stored is not None)

    def _fill_cards(self, kind, title, rows, total, message, select):
        """The cards on screen (under the lock). `select` is the cursor's card; without one it is the first card, or on a
        show's episodes the first that can be watched."""
        self.rows, self.page = rows, (title, total)
        control = self.getControl(self.GRID_ID)
        control.reset()
        control.addItems(items.card_items(rows))
        if rows:
            control.selectItem(select if select is not None and 0 <= select < len(rows) else
                               sections.first_playable(rows) if kind == EPISODES else 0)
        self._prop("emptycat", "" if rows else message)

    def _leave_shelf(self):
        """The row goes back to channels: a list that is being made is dropped, and the index goes after a while (the person
        may come straight back)."""
        self.list_token += 1
        self.rows, self.trail, self.row_kind, self.enter_row = [], [], CHANNELS, False
        self._later("library", LIBRARY_KEEP, self.library.release)

    def _ok_card(self):
        """OK on a card of the shows, the episodes or the films: a show opens its episodes, an episode or a film plays from
        its start in the archive."""
        found = self._card()
        if found is None:
            return
        position, row = found
        if self.row_kind == SHOWS:
            self.trail.append((SHOWS, "", position))
            self._open_section(EPISODES, row.key)
        elif row.playable:
            self._start(row.cid, view.GuideRow(row.epg, row.name or row.title, "", "archive", row.start, row.stop))
        else:
            ui.notify(words.tr("This programme has not aired yet." if row.future else "This programme is not in the archive."))

    def _episodes_back(self):
        """Back from the episodes of a show: the shows, the cursor on the same show."""
        kind, sid, position = self.trail.pop()
        self._open_section(kind, sid, select=position)

    # -- making the lists (worker thread) --

    def _load_list(self, kind, sid, token, select, shown=False):
        """Make a list on a worker and show it. `shown`: the list on screen is the one kept on disk, asked for again: a
        failure leaves it, a list that is the same changes nothing, one that changed replaces it with the cursor kept."""
        now, filled = self._now(), False
        try:
            try:
                title, rows, total, message, ok = self._list_rows(kind, sid, now)
            except Exception as e:
                ui.log(f"SWEET.TV {kind} failed: {e!r}", xbmc.LOGERROR)
                title, rows, total, message, ok = "", [], 0, words.tr(LOAD_FAILED), False
            if ok:
                self._keep(kind, sid, title, rows, total, now)
            with self._lock:
                filled = self._show_made(kind, token, select, shown, (title, rows, total, message, ok))
        finally:
            with self._lock:
                self.list_loading -= 1
        if ok:
            self.library.warm(now)               # so that the menu can say how many shows and films there are
            self._keep_counts(now)
            self._counts_changed()
        if filled and rows and self.enter_row:
            self.enter_row = False
            self._focus_on(self.GRID_ID)

    def _show_made(self, kind, token, select, shown, made) -> bool:
        """The list a worker made, on screen (under the lock) unless the person has gone elsewhere or it is no better than the
        list from the disk cache that is on screen. True when the cards were drawn."""
        title, rows, total, message, ok = made
        if token != self.list_token or self._stop.is_set():
            return False
        if shown:
            if not ok or rows and (title, total) == self.page and rows == self.rows:
                return False
            select = self._same_card(rows)
        self._fill_cards(kind, title, rows, total, message, select)
        return True

    def _same_card(self, rows):
        """Where the cursor goes in `rows` when they replace the ones on screen: on the same programme (or show), else on the
        same place."""
        found = self._card()
        position, old = found if found else (0, None)
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
            key, read = ("demo",), lambda: self._demo_raw(now)
        else:
            path = files.channel_path()
            key, read = files.file_stamp(path) or ("missing",), lambda: files.read_raw(path)
        if not library.load(key, read):
            return "", [], 0, words.tr(LOAD_FAILED), False
        logos = {c.cid: c.logo for c in self.catalog.channels if c.logo} if self.catalog else {}
        if kind == SHOWS:
            rows, total = library.shows(now)
            return "", rows, total, words.tr("No shows with episodes in the archive yet."), True
        if kind == FILMS:
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
        """(shows, films) the disk cache kept, for the menu; None for none."""
        ns = self._ns()
        hit = page_cache.get(ns, pages.COUNTS, pages.PAGE_TTL, pages.PAGE_MAX_AGE, now=self._now()) if ns else None
        return pages.counts_from_value(hit.value) if hit else None

    def _keep(self, kind, sid, title, rows, total, now):
        """A list that was made goes to the disk cache (it has cards), or goes from it (the section is empty now). Never a
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
            page_cache.put(ns, pages.COUNTS, pages.counts_value(*counts), now=now)

    def _counts_changed(self):
        """The shows and films are counted: said in the menu."""
        with self._lock:
            counts = self.library.counts(self._now())
            if counts and counts != self.counts and self.catalog is not None and not self._stop.is_set():
                self.counts = counts
                self._update_menu()

    def _start_warm(self):
        """After a catalog is shown: the shows and the films are made one after the other in the background and kept on disk
        (prefetch: at a low priority, only while nothing is loading and no video plays, a page that is fresh is skipped), so
        that the menu has their counts and the cards are there when the person gets to them."""
        ns = self._ns()
        if ns is None or not self.library.available():
            return
        jobs = [(pages.key_of(kind), lambda kind=kind: self._warm_list(kind)) for kind in (SHOWS, FILMS)]
        self.warming = prefetch.warm(ns, jobs, ttl=pages.PAGE_TTL, idle=self._idle)

    def _cancel_warm(self):
        warming, self.warming = self.warming, None
        if warming is not None:
            warming.cancel()

    def _idle(self):
        """Whether the window is waiting for nothing: no list being made, no video playing."""
        return not self._stop.is_set() and not self.list_loading and not self._playing()

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
        self._counts_changed()
        if self.row_kind == CHANNELS:
            self._later("library", LIBRARY_KEEP, self.library.release)       # nobody is looking at the lists: the index goes
        if not rows:
            ns, key = self._ns(), pages.key_of(kind)
            if ns is not None:
                page_cache.remove(ns, key)
            return None
        return pages.to_value(title, rows, total)

    def _signed_out(self):
        """Signed out (or the account changed under the window): the pages kept for the account go, the start-up run stops."""
        self.dropped = True
        self._cancel_warm()
        self.library.release()
        if not self.demo:
            page_cache.drop_service(pages.SERVICE)
