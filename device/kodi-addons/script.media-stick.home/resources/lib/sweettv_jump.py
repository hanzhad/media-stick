"""SWEET.TV app: the number keys. Typed digits show in a chip at the top, then the row jumps to that channel.

A mixin of the window (sweettv_app.SweetTV), kept apart to keep that file small. It relies on what the window
has: _lock, _prop, _later, _cancel, _fill_row, _focus_on, getControl, and the attributes catalog, shown,
digits and GRID_ID (the row). The choices (which digit, which channel, when to wait) are in sweettv_data.
"""
from resources.lib import sweettv_data as data


class DigitJump:
    def _digit(self, digit):
        with self._lock:
            self.digits = data.push_digit(self.digits, digit)
            self._cancel("digits")
            if not self.digits:
                return
            self._prop("jump", f"Channel {self.digits}")
            if data.could_grow(self.catalog.channels, self.digits):
                self._later("digits", data.DIGIT_WAIT, self._digits_commit)
            else:
                self._digits_commit()

    def _digits_clear(self):
        with self._lock:
            self._cancel("digits")
            self.digits = ""
            self._prop("jump", "")

    def _digits_commit(self):
        with self._lock:
            typed, self.digits = self.digits, ""
            channel = data.channel_numbered(self.catalog.channels, typed) if typed and self.catalog else None
            if channel is None:
                if typed:
                    self._prop("jump", f"No channel {typed}")
                    self._later("digits", data.DIGIT_WAIT, lambda: self._prop("jump", ""))
                return
            self._prop("jump", "")
            if channel not in self.shown:
                self._fill_row(data.ALL, channel.cid, sync_menu=True)      # the menu follows to All
            else:
                self.getControl(self.GRID_ID).selectItem(self.shown.index(channel))
        self._focus_on(self.GRID_ID)
