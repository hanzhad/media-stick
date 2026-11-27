"""Fetch an app screen's first pages while it starts, into page_cache, so that the user finds them there.

  handle = prefetch.warm("youtube:7", [(key, fetch), ...], ttl=300, idle=screen_is_idle)
  handle.cancel()                    # when the window closes or the account changes

fetch() returns the JSON value to keep, or None for nothing worth keeping (an error, an empty list, a sign-in card). The
jobs run one after another (a Pi 3B+ has no room for two) in ONE daemon thread, at a lower priority, in the order given. A key
whose page is still fresh (younger than ttl) is skipped. idle(), when given, is asked before each job: the screen says
the user is waiting for something, not now by answering False, and the run waits (up to IDLE_TIMEOUT) instead of competing
with it. Background prefetch never runs while Kodi is playing or AirPlay/Miracast/WebApp owns the screen.

start() is warm() under the other name.
"""
import os
import threading
import time

from resources.lib import page_cache

INITIAL_DELAY = 4.0            # s to wait before starting background warm-up after boot/open
JOB_TIMEOUT = 30.0               # s: a job that took longer ends the run and its answer is dropped
IDLE_TIMEOUT = 60.0              # s the run waits for the screen to be idle before it gives up
IDLE_POLL = 0.2
PAUSE = 0.3                      # s between two jobs: the screen's own requests get in between
NICE = 10                        # added to the thread's niceness (Linux: per thread)
LOG = "[script.media-stick.home]"

_lock = threading.Lock()
_running = {}                    # namespace -> Handle of the run in progress
_serial = threading.Lock()       # one run at a time across apps


class Handle:
    """A run of warm(): cancel() it, wait() for it, ask what it did."""

    def __init__(self, namespace):
        self.namespace = namespace
        self.stored = []                         # keys stored by this run
        self.skipped = 0                         # fresh already, or nothing worth keeping
        self.failed = 0
        self.note = ""                           # why the run ended early: cancelled, busy, slow
        self.done = threading.Event()
        self._cancel = threading.Event()

    def cancel(self):
        self._cancel.set()

    @property
    def cancelled(self):
        return self._cancel.is_set()

    @property
    def running(self):
        return not self.done.is_set()

    def wait(self, timeout=None):
        """True when the run has ended."""
        return self.done.wait(timeout)


def _log(text):
    try:
        import xbmc
        xbmc.log(f" {LOG} {text}".lstrip(), xbmc.LOGINFO)
    except Exception:
        pass


def _lower_priority(nice):
    if nice and hasattr(os, "nice"):
        try:
            os.nice(nice)
        except OSError:
            pass


def _is_playback_or_cast_active():
    """True when Kodi is playing audio/video or AirPlay/Miracast/WebApp owns the screen."""
    try:
        import xbmc
        if xbmc.Player().isPlaying():
            return True
    except Exception:
        pass
    screen_dir = os.environ.get("MEDIASTICK_SCREEN_DIR", "/run/media-stick")
    for flag in ("airplay", "miracast", "webapp"):
        try:
            if os.path.exists(os.path.join(screen_dir, flag)):
                return True
        except OSError:
            pass
    return False


def _acquire(handle):
    """Wait for the run in progress of another namespace; False when cancelled while waiting."""
    while not _serial.acquire(timeout=IDLE_POLL):
        if handle.cancelled:
            return False
    return True


def _wait_idle(handle, idle, timeout):
    """True when the screen is idle and no playback/cast is active; False when cancelled or busy for timeout."""
    end = time.monotonic() + timeout
    while True:
        try:
            busy = _is_playback_or_cast_active()
        except Exception:
            busy = False
        if not busy:
            if idle is None:
                return True
            try:
                if idle():
                    return True
            except Exception:
                return True
        if handle.cancelled or time.monotonic() >= end:
            return False
        handle._cancel.wait(IDLE_POLL)


def _job(handle, key, fetch, job_timeout):
    """One job: fetch and store. Counts in the handle; False when the run is to end."""
    started = time.monotonic()
    try:
        value = fetch()
    except Exception:
        handle.failed += 1
        return True
    if handle.cancelled:
        return False
    if time.monotonic() - started > job_timeout:
        handle.failed += 1
        handle.note = "slow"
        return False
    if value is None:
        handle.skipped += 1
    elif page_cache.put(handle.namespace, key, value):
        handle.stored.append(key)
    else:
        handle.failed += 1
    return True


def _run(handle, jobs, job_timeout, idle, idle_timeout, pause, nice, log, ttl, delay=0.0):
    began = time.monotonic()
    try:
        _lower_priority(nice)
        if delay and delay > 0:
            if handle._cancel.wait(delay):
                handle.note = "cancelled"
                return
        if not _acquire(handle):
            handle.note = "cancelled"
            return
        try:
            for key, fetch in jobs:
                if handle.cancelled:
                    handle.note = "cancelled"
                    break
                if page_cache.fresh(handle.namespace, key, ttl):
                    handle.skipped += 1
                    continue
                if not _wait_idle(handle, idle, idle_timeout):
                    handle.note = "cancelled" if handle.cancelled else "busy"
                    break
                if not _job(handle, key, fetch, job_timeout):
                    handle.note = handle.note or "cancelled"
                    break
                if pause:
                    handle._cancel.wait(pause)
        finally:
            _serial.release()
    except Exception as e:
        handle.failed += 1
        handle.note = f"error {type(e).__name__}"
    finally:
        with _lock:
            if _running.get(handle.namespace) is handle:
                del _running[handle.namespace]
        handle.done.set()
        try:
            (log or _log)(f"prefetch {handle.namespace}: {len(handle.stored)} stored, {handle.skipped} skipped, "
                          f"{handle.failed} failed in {time.monotonic() - began:.1f} s" + (f" ({handle.note})" if handle.note else ""))
        except Exception:
            pass


def warm(namespace, jobs, ttl=page_cache.DEFAULT_TTL, job_timeout=JOB_TIMEOUT, idle=None, idle_timeout=IDLE_TIMEOUT,
         pause=PAUSE, nice=NICE, log=None, delay=0.0):
    """Run jobs ([(key, fetch), ...]) for namespace in the background; the Handle at once. Never raises."""
    handle = Handle(namespace)
    try:
        jobs = list(jobs)
        with _lock:
            running = _running.get(namespace)
            if running is not None:
                return running
            _running[namespace] = handle
        threading.Thread(target=_run, name="prefetch", daemon=True,
                         args=(handle, jobs, job_timeout, idle, idle_timeout, pause, nice, log, ttl, delay)).start()
        return handle
    except Exception:
        with _lock:
            if _running.get(namespace) is handle:
                del _running[namespace]
        handle.note = "not started"
        handle.done.set()
        return handle


start = warm
