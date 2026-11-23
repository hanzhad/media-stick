"""SWEET.TV app: the programme guide of a channel. A card over the screen with a list of what is on now and what
the archive still holds, the newest first; OK on the live programme watches live, OK on a finished one plays it
from the archive (the plugin's `playvid/<channel>|<epg id>`).

A mixin of the window (sweettv_app.SweetTV), kept apart to keep that file small. It relies on what the window
has: _prop, _focus_on, _selected, _play, getControl, clock and the constants ROW, GUIDE_BUTTON, GUIDE. The choices
(which programmes, how they read) are in sweettv_view.
"""
from resources.lib import sweettv_items as items, sweettv_view as view

GUIDE = 400                      # the list of programmes
GUIDE_BUTTON = 211               # "Programme guide" in the preview


class Guide:
    guide_cid = ""
    guide_rows = ()

    @property
    def guide_open(self) -> bool:
        return bool(self.guide_cid)

    def _guide_show(self):
        """Open the guide of the focused channel; nothing happens when it has nothing to show."""
        channel = self._selected()
        if channel is None:
            return
        rows = view.guide_rows(channel, self._now())
        if not any(r.kind == "archive" for r in rows):
            return
        with self._lock:
            self.guide_cid, self.guide_rows = channel.cid, rows
            control = self.getControl(GUIDE)
            control.reset()
            control.addItems(items.guide_items(rows))
            control.selectItem(0)
            self._prop("guide_title", channel.name)
            self._prop("guide", "1")
        self._focus_on(GUIDE)

    def _guide_close(self):
        with self._lock:
            self.guide_cid, self.guide_rows = "", ()
            self._prop("guide", "")
        self._focus_on(GUIDE_BUTTON) or self._focus_on(self.GRID_ID)

    def _guide_play(self):
        """OK on a row of the guide."""
        position = self.getControl(GUIDE).getSelectedPosition()
        channel = next((c for c in self.catalog.channels if c.cid == self.guide_cid), None)
        if channel is None or not 0 <= position < len(self.guide_rows):
            return
        row = self.guide_rows[position]
        self._play(channel, row if row.kind == "archive" else None)
