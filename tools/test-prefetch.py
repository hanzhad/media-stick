#!/usr/bin/env python3
"""Offline test of the start-up fetch (no Kodi, no device): python3 tools/test-prefetch.py

The jobs are plain functions; page_cache keeps its pages in a temp directory."""
import os
import shutil
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

sys.dont_write_bytecode = True

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
sys.path.insert(0, ADDON)

from resources.lib import page_cache, prefetch  # noqa: E402

NS = "app:1"


def wait_for(condition, timeout=3.0):
    end = time.monotonic() + timeout
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.005)
    return True


class Case(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        patch = mock.patch.object(page_cache, "DIR", self.dir)
        patch.start()
        self.addCleanup(patch.stop)
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        page_cache._memo.clear()
        self.lines, self.order, self.threads = [], [], set()
        self.handles = []

    def tearDown(self):
        for handle in self.handles:
            handle.cancel()
            handle.wait(3)

    def job(self, key, value=None, delay=0.0, boom=None):
        def run():
            self.order.append(key)
            self.threads.add(threading.current_thread())
            if delay:
                time.sleep(delay)
            if boom:
                raise boom
            return {"page": key} if value is None else value
        return key, run

    def warm(self, jobs, ns=NS, **kw):
        kw.setdefault("pause", 0)
        kw.setdefault("nice", 0)
        kw.setdefault("log", self.lines.append)
        handle = prefetch.warm(ns, jobs, **kw)
        self.handles.append(handle)
        return handle

    def kept(self, key, ns=NS):
        hit = page_cache.get(ns, key, ttl=10 ** 9)
        return None if hit is None else hit.value


class Running(Case):
    def test_the_jobs_run_in_the_order_given_and_their_values_are_kept(self):
        handle = self.warm([self.job("c"), self.job("a"), self.job("b")])
        self.assertTrue(handle.wait(3))
        self.assertEqual((self.order, handle.stored), (["c", "a", "b"], ["c", "a", "b"]))
        self.assertEqual([self.kept(k) for k in "abc"], [{"page": "a"}, {"page": "b"}, {"page": "c"}])
        self.assertEqual((handle.skipped, handle.failed, handle.note, handle.running), (0, 0, "", False))

    def test_one_daemon_thread_runs_all_of_them_one_after_another(self):
        active, most = [0], [0]

        def job(key):
            def run():
                active[0] += 1
                most[0] = max(most[0], active[0])
                time.sleep(0.02)
                active[0] -= 1
                self.threads.add(threading.current_thread())
                return key
            return key, run
        before = threading.active_count()
        handle = self.warm([job(k) for k in "abcde"])
        self.assertTrue(handle.wait(3))
        self.assertEqual(most[0], 1)
        self.assertEqual(len(self.threads), 1)
        thread, = self.threads
        self.assertTrue(thread.daemon)
        self.assertTrue(wait_for(lambda: threading.active_count() == before), "nothing left running")

    def test_a_key_whose_page_is_still_fresh_is_not_fetched_a_stale_one_is(self):
        page_cache.put(NS, "fresh", {"old": 1}, now=time.time() - 10)
        page_cache.put(NS, "stale", {"old": 1}, now=time.time() - 1000)
        handle = self.warm([self.job("fresh"), self.job("stale"), self.job("new")], ttl=300)
        self.assertTrue(handle.wait(3))
        self.assertEqual(self.order, ["stale", "new"])
        self.assertEqual((self.kept("fresh"), self.kept("stale"), handle.skipped), ({"old": 1}, {"page": "stale"}, 1))

    def test_a_job_with_nothing_worth_keeping_is_left_out_and_does_not_stop_the_others(self):
        handle = self.warm([("a", lambda: None), self.job("b")])
        self.assertTrue(handle.wait(3))
        self.assertEqual((self.kept("a"), self.kept("b"), handle.skipped), (None, {"page": "b"}, 1))

    def test_a_job_that_raises_is_swallowed_and_the_run_goes_on(self):
        handle = self.warm([self.job("a", boom=RuntimeError("down")), self.job("b"), ("c", lambda: {1, 2}), self.job("d")])
        self.assertTrue(handle.wait(3))
        self.assertEqual((self.kept("b"), self.kept("d")), ({"page": "b"}, {"page": "d"}))
        self.assertEqual((self.kept("a"), self.kept("c"), handle.failed), (None, None, 2))      # a set is no JSON: refused

    def test_a_run_never_raises_into_the_caller(self):
        handle = self.warm(5)                                                     # jobs that are not a list of jobs
        self.assertTrue(handle.wait(3))
        self.assertEqual(handle.note, "not started")
        handle = self.warm([("bad",)])                                            # a job of the wrong shape
        self.assertTrue(handle.wait(3))
        self.assertEqual(handle.stored, [])
        with mock.patch.object(page_cache, "fresh", side_effect=RuntimeError("x")):
            handle = self.warm([self.job("a")])
            self.assertTrue(handle.wait(3))
        self.assertTrue(handle.note.startswith("error"))
        self.assertEqual(prefetch._running, {})

    def test_a_run_logs_one_line(self):
        handle = self.warm([self.job("a"), ("b", lambda: None), self.job("c", boom=ValueError("x"))])
        self.assertTrue(handle.wait(3))
        self.assertTrue(wait_for(lambda: self.lines))
        self.assertEqual(len(self.lines), 1)
        self.assertRegex(self.lines[0], r"^prefetch app:1: 1 stored, 1 skipped, 1 failed in \d+\.\d s$")

    def test_a_log_that_raises_changes_nothing(self):
        handle = self.warm([self.job("a")], log=mock.Mock(side_effect=RuntimeError("x")))
        self.assertTrue(handle.wait(3))
        self.assertEqual(self.kept("a"), {"page": "a"})

    def test_start_is_warm_under_the_other_name(self):
        self.assertIs(prefetch.start, prefetch.warm)


class Cancelling(Case):
    def test_cancel_stops_before_the_next_job(self):
        started, release = threading.Event(), threading.Event()

        def first():
            started.set()
            release.wait(3)
            return {"page": "a"}
        handle = self.warm([("a", first), self.job("b"), self.job("c")])
        self.assertTrue(started.wait(3))
        handle.cancel()
        release.set()
        self.assertTrue(handle.wait(3))
        self.assertEqual(self.order, [])
        self.assertEqual((self.kept("b"), handle.cancelled, handle.note), (None, True, "cancelled"))
        self.assertIsNone(self.kept("a"), "the answer that came after the cancel is not kept")

    def test_a_cancel_before_the_first_job_runs_nothing(self):
        gate = threading.Event()
        handle = self.warm([self.job("a")], idle=gate.is_set)
        handle.cancel()
        self.assertTrue(handle.wait(3))
        self.assertEqual((self.order, handle.note), ([], "cancelled"))

    def test_the_run_is_over_for_the_registry_once_it_ended(self):
        handle = self.warm([self.job("a")])
        self.assertTrue(handle.wait(3))
        self.assertEqual(prefetch._running, {})
        again = self.warm([self.job("a"), self.job("b")])                         # a new run is allowed now
        self.assertIsNot(again, handle)
        self.assertTrue(again.wait(3))
        self.assertEqual(again.skipped, 1)                                        # a is fresh


class Duplicates(Case):
    def test_a_second_warm_for_a_running_namespace_is_a_no_op_and_gives_the_running_handle(self):
        started, release = threading.Event(), threading.Event()

        def slow():
            started.set()
            release.wait(3)
            return 1
        first = self.warm([("a", slow)])
        self.assertTrue(started.wait(3))
        second = self.warm([self.job("x"), self.job("y")])
        self.assertIs(second, first)
        release.set()
        self.assertTrue(first.wait(3))
        self.assertEqual(self.order, [], "the second list was not run")

    def test_two_namespaces_take_turns_never_run_together(self):
        active, most = [0], [0]

        def job():
            active[0] += 1
            most[0] = max(most[0], active[0])
            time.sleep(0.05)
            active[0] -= 1
            return 1
        one = self.warm([("a", job)], ns="app:1")
        two = self.warm([("a", job)], ns="app:2")
        self.assertTrue(one.wait(3) and two.wait(3))
        self.assertEqual((most[0], one.stored, two.stored), (1, ["a"], ["a"]))


class Waiting(Case):
    def test_the_run_waits_while_the_screen_is_busy_and_goes_on_when_it_is_idle(self):
        idle = threading.Event()
        with mock.patch.object(prefetch, "IDLE_POLL", 0.01):
            handle = self.warm([self.job("a")], idle=idle.is_set)
            time.sleep(0.15)
            self.assertEqual(self.order, [])
            idle.set()
            self.assertTrue(handle.wait(3))
        self.assertEqual(self.order, ["a"])

    def test_a_screen_that_stays_busy_ends_the_run_after_the_idle_timeout(self):
        with mock.patch.object(prefetch, "IDLE_POLL", 0.01):
            handle = self.warm([self.job("a"), self.job("b")], idle=lambda: False, idle_timeout=0.1)
            self.assertTrue(handle.wait(3))
        self.assertEqual((self.order, handle.note), ([], "busy"))

    def test_an_idle_that_raises_counts_as_idle(self):
        handle = self.warm([self.job("a")], idle=mock.Mock(side_effect=RuntimeError("x")))
        self.assertTrue(handle.wait(3))
        self.assertEqual(self.order, ["a"])

    def test_the_screen_is_asked_before_each_job(self):
        asked = []
        handle = self.warm([self.job("a"), self.job("b")], idle=lambda: asked.append(len(self.order)) or True)
        self.assertTrue(handle.wait(3))
        self.assertEqual(asked, [0, 1])


class TimeBound(Case):
    def test_a_job_that_overran_ends_the_run_and_its_late_answer_is_dropped(self):
        handle = self.warm([self.job("a"), self.job("slow", delay=0.15), self.job("c")], job_timeout=0.05)
        self.assertTrue(handle.wait(3))
        self.assertEqual(self.order, ["a", "slow"])
        self.assertEqual((self.kept("a"), self.kept("slow"), self.kept("c")), ({"page": "a"}, None, None))
        self.assertEqual((handle.note, handle.failed), ("slow", 1))

    def test_the_pause_between_jobs_is_kept_and_is_cut_short_by_a_cancel(self):
        handle = self.warm([self.job("a"), self.job("b")], pause=5)
        self.assertTrue(wait_for(lambda: self.order == ["a"]))
        began = time.monotonic()
        handle.cancel()
        self.assertTrue(handle.wait(3))
        self.assertLess(time.monotonic() - began, 2)
        self.assertEqual(self.order, ["a"])

    def test_the_thread_asks_to_be_nicer(self):
        with mock.patch.object(prefetch.os, "nice", create=True) as nice:
            handle = self.warm([self.job("a")], nice=10)
            self.assertTrue(handle.wait(3))
        nice.assert_called_once_with(10)
        with mock.patch.object(prefetch.os, "nice", create=True, side_effect=OSError("no")):
            handle = self.warm([self.job("a")], nice=10)
            self.assertTrue(handle.wait(3))                                      # refused: the run goes on

    def test_initial_delay_constant_and_default_zero_delay(self):
        import inspect

        self.assertTrue(hasattr(prefetch, "INITIAL_DELAY"), "prefetch.INITIAL_DELAY is not defined")
        self.assertEqual(prefetch.INITIAL_DELAY, 4.0)
        sig = inspect.signature(prefetch.warm)
        self.assertIn("delay", sig.parameters)
        self.assertEqual(sig.parameters["delay"].default, 0.0)

        events = []
        orig_acquire = prefetch._acquire
        orig_wait = threading.Event.wait

        def spy_acquire(h):
            events.append(("acquire",))
            return orig_acquire(h)

        def spy_wait(ev, timeout=None):
            if timeout == 0.02:
                events.append(("delay_wait", timeout))
            return orig_wait(ev, timeout)

        with (
            mock.patch.object(prefetch, "_acquire", side_effect=spy_acquire),
            mock.patch.object(threading.Event, "wait", spy_wait),
        ):
            # Default delay=0.0 skips initial wait before _acquire
            h0 = self.warm([self.job("a")])
            self.assertTrue(h0.wait(3))
            self.assertEqual(events, [("acquire",)])

            # Positive delay waits BEFORE _acquire(handle) and then runs jobs
            events.clear()
            h_delayed = self.warm([self.job("b")], delay=0.02)
            self.assertTrue(h_delayed.wait(3))
            self.assertEqual(events, [("delay_wait", 0.02), ("acquire",)])
            self.assertEqual(h_delayed.stored, ["b"])
            self.assertEqual(h_delayed.note, "")

    def test_cancelling_during_delay_exits_immediately_with_zero_jobs_and_no_acquire(self):
        import inspect

        self.assertIn("delay", inspect.signature(prefetch.warm).parameters, "prefetch.warm must accept delay=")
        acquire_calls = []
        orig_acquire = prefetch._acquire

        def spy_acquire(h):
            acquire_calls.append(h)
            return orig_acquire(h)

        with mock.patch.object(prefetch, "_acquire", side_effect=spy_acquire):
            handle = self.warm([self.job("a"), self.job("b")], delay=0.5)
            handle.cancel()
            self.assertTrue(handle.wait(3))

        self.assertEqual(self.order, [])
        self.assertEqual(handle.stored, [])
        self.assertTrue(handle.cancelled)
        self.assertEqual(handle.note, "cancelled")
        self.assertEqual(acquire_calls, [], "cancel during delay must return before _acquire(handle)")
        self.assertEqual(prefetch._running, {})

    def test_sweettv_shelf_and_youtube_app_pass_initial_delay_to_warm(self):
        import importlib
        import types

        lib_dir = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
        fake_xbmc = types.ModuleType("xbmc")
        fake_xbmc.LOGINFO, fake_xbmc.LOGWARNING, fake_xbmc.LOGERROR = 1, 2, 3
        fake_xbmc.log = lambda *a, **k: None
        fake_xbmc.Monitor = object
        fake_xbmc.Player = lambda: types.SimpleNamespace(isPlaying=lambda: False)
        fake_xbmc.getCondVisibility = lambda _c: False

        fake_xbmcaddon = types.ModuleType("xbmcaddon")
        fake_xbmcaddon.Addon = lambda *_a: types.SimpleNamespace(
            getAddonInfo=lambda _k: ADDON,
            getSettingString=lambda _s: "",
        )

        fake_xbmcgui = types.ModuleType("xbmcgui")
        fake_xbmcgui.WindowXML = object
        fake_xbmcgui.WindowXMLDialog = object
        fake_xbmcgui.Window = lambda *_a: types.SimpleNamespace(getProperty=lambda _k: "", setProperty=lambda *_x: None)
        fake_xbmcgui.Dialog = lambda: types.SimpleNamespace(notification=lambda *a, **k: None)
        fake_xbmcgui.ListItem = object
        fake_xbmcgui.NOTIFICATION_INFO = "info"

        fake_xbmcvfs = types.ModuleType("xbmcvfs")
        fake_xbmcvfs.translatePath = lambda _p: self.dir + "/"

        with (
            mock.patch.dict(
                sys.modules,
                {
                    "xbmc": fake_xbmc,
                    "xbmcaddon": fake_xbmcaddon,
                    "xbmcgui": fake_xbmcgui,
                    "xbmcvfs": fake_xbmcvfs,
                },
            ),
            mock.patch.object(sys, "path", [ADDON, lib_dir, *sys.path]),
        ):
            sw_shelf = importlib.import_module("resources.lib.sweettv_shelf")
            yt_app = importlib.import_module("resources.lib.youtube_app")
            yt_data = importlib.import_module("resources.lib.youtube_data")

            with mock.patch.object(prefetch, "warm", return_value=prefetch.Handle("sweettv:main")) as mock_sw_warm:
                shelf_dummy = types.SimpleNamespace(
                    demo=False,
                    signed=True,
                    _warm_started=False,
                    raw_catalog={},
                    _now=lambda: 1000,
                    _shelf_idle=lambda: True,
                    _warm_handle=None,
                )
                sw_shelf.Shelf._start_warm(shelf_dummy)
                mock_sw_warm.assert_called_once()
                self.assertEqual(mock_sw_warm.call_args.kwargs.get("delay"), getattr(prefetch, "INITIAL_DELAY", 4.0))

            with mock.patch.object(prefetch, "warm", return_value=prefetch.Handle("youtube:default")) as mock_yt_warm:
                yt_dummy = types.SimpleNamespace(
                    profile="default",
                    _ns=lambda _p: "youtube:default",
                    view=yt_data.section_view("home", {}),
                    routes={},
                    _warm_page=lambda _v, _p: None,
                    _idle=lambda: True,
                    warming=None,
                )
                yt_app.YouTube._start_warm(yt_dummy)
                mock_yt_warm.assert_called_once()
                self.assertEqual(mock_yt_warm.call_args.kwargs.get("delay"), getattr(prefetch, "INITIAL_DELAY", 4.0))


if __name__ == "__main__":
    unittest.main()
