"""SWEET.TV app: the one place that writes the state file, and it does so on a thread of its own, so an fsync on the
SD card never stops the picture. The window hands over its newest state (a dict nobody changes afterwards);
what was handed over while a write ran is written next, once, so a burst of changes costs one write.
"""
import threading

from resources.lib import sweettv_state as saved


class StateWriter:
    def __init__(self, path, save=None):
        self.path = path
        self._save = save                        # the function that writes; saved.save_state unless a test gives one
        self._cond = threading.Condition()
        self._pending = None
        self._closing = False
        self._thread = None
        self.writes = 0                          # finished writes (a test waits on it)

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def submit(self, state):
        with self._cond:
            self._pending = state
            self._cond.notify()

    def stop(self, timeout=3):
        """Write what is waiting, then end the thread."""
        with self._cond:
            self._closing = True
            self._cond.notify()
        if self._thread is not None:
            self._thread.join(timeout)

    def _run(self):
        while True:
            with self._cond:
                while self._pending is None and not self._closing:
                    self._cond.wait()
                state, self._pending = self._pending, None
                done = self._closing and state is None
            if done:
                return
            if state is not None:
                try:
                    (self._save or saved.save_state)(self.path, state)
                finally:
                    self.writes += 1
