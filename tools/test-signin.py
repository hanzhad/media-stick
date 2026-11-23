#!/usr/bin/env python3
"""Offline test of the sign-in state and the add-on overlays (no Kodi, no device):
python3 tools/test-signin.py"""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in device/skin-overlay

import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import unittest  # noqa: E402
import unittest.mock  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
OVERLAY = os.path.join(ROOT, "device", "skin-overlay")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
sys.path.insert(0, LIB)

import mediastick_signin as ms  # noqa: E402


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


class State(unittest.TestCase):
    def setUp(self):
        for service in ms.SERVICES:
            ms.begin(service)

    def test_waiting_state_carries_the_code_and_a_link_that_opens_with_it_typed_in(self):
        self.assertTrue(ms.publish("youtube", "waiting", code="ABC-DEF-GHI", url="https://www.youtube.com/activate",
                                   step=2, steps=4))
        s = ms.read("youtube")
        self.assertEqual((s["state"], s["code"], s["step"], s["steps"]), ("waiting", "ABC-DEF-GHI", 2, 4))
        self.assertEqual(s["link"], "https://www.youtube.com/activate?user_code=ABC-DEF-GHI")
        self.assertEqual(s["name"], "YouTube")
        self.assertGreater(s["left"], 0)
        ms.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice")
        self.assertEqual(ms.read("sweettv")["link"], "https://sweet.tv/addDevice?connectCode=12345")

    def test_the_link_is_what_the_providers_answer_gives(self):
        """A personal Google client answers google.com/device and no complete link: the QR holds that page, the code is
        not put into an address that does not take it. A complete link wins. YouTube's own page and SWEET.TV's keep
        the code in the address; no page at all falls back to the YouTube page."""
        def link(service, url="", complete="", code="ABCD-EFGH"):
            ms.publish(service, "waiting", code=code, url=url, link=complete)
            return ms.read(service)["link"]
        self.assertEqual(link("youtube", "https://www.google.com/device"), "https://www.google.com/device")
        full = "https://www.google.com/device?user_code=ABCD-EFGH"
        self.assertEqual(link("youtube", "https://www.google.com/device", full), full)
        self.assertEqual(link("youtube", "https://www.youtube.com/activate", full), full)
        self.assertEqual(link("youtube", "https://www.youtube.com/activate"), "https://www.youtube.com/activate?user_code=ABCD-EFGH")
        self.assertEqual(link("youtube"), "https://www.youtube.com/activate?user_code=ABCD-EFGH")
        self.assertEqual(link("youtube", "https://accounts.google.com/o/oauth2/device/usercode"),
                         "https://accounts.google.com/o/oauth2/device/usercode")
        self.assertEqual(link("sweettv", "https://sweet.tv/addDevice", code="12345"), "https://sweet.tv/addDevice?connectCode=12345")
        self.assertEqual(link("sweettv", "https://sweet.tv/addDevice", "https://sweet.tv/x?c=1", code="12345"), "https://sweet.tv/x?c=1")
        for bad in ("javascript:alert(1)", "http://www.google.com/device", "https://a b", "x" * 400, 5, None):
            self.assertEqual(ms.link_for("youtube", "A-B", "https://www.google.com/device", bad), "https://www.google.com/device", bad)
        self.assertEqual(ms.link_for("youtube", "A-B", "ftp://x"), "https://www.youtube.com/activate?user_code=A-B")

    def test_a_code_cannot_break_out_of_the_link(self):
        ms.publish("youtube", "waiting", code="A&b=c d", url="https://www.youtube.com/activate")
        self.assertEqual(ms.read("youtube")["link"], "https://www.youtube.com/activate?user_code=A%26b%3Dc%20d")

    def test_unknown_service_or_state_is_refused(self):
        self.assertFalse(ms.publish("netflix", "waiting", code="x"))
        self.assertFalse(ms.publish("youtube", "sleeping"))
        self.assertFalse(ms.request_cancel("netflix"))
        self.assertIsNone(ms.read("netflix"))

    def test_a_waiting_state_nobody_touches_goes_stale(self):
        ms.publish("youtube", "waiting", code="AAA")
        now = time.time()
        self.assertIsNotNone(ms.read("youtube", now + ms.HEARTBEAT - 1))
        self.assertIsNone(ms.read("youtube", now + ms.HEARTBEAT + 5))

    def test_touch_keeps_it_alive_but_never_revives_a_finished_one(self):
        ms.publish("youtube", "waiting", code="AAA")
        later = time.time() + ms.HEARTBEAT + 5
        self.assertIsNone(ms.read("youtube", later))
        self.assertTrue(ms.touch("youtube"))                 # the add-on is still polling
        self.assertIsNotNone(ms.read("youtube", time.time() + 1))
        ms.publish("youtube", "done")
        self.assertFalse(ms.touch("youtube"))

    def test_a_waiting_state_expires_with_the_code(self):
        ms.publish("youtube", "waiting", code="AAA", ttl=30)
        s = ms.read("youtube")
        self.assertLessEqual(s["left"], 30)
        self.assertIsNone(ms.read("youtube", time.time() + 31))

    def test_a_result_is_visible_for_a_short_while_only(self):
        ms.publish("youtube", "done")
        self.assertEqual(ms.read("youtube")["state"], "done")
        self.assertEqual(ms.read("youtube")["left"], 0)
        self.assertIsNone(ms.read("youtube", time.time() + ms.RESULT_KEEP + 5))

    def test_active_lists_only_what_waits_for_a_person(self):
        ms.publish("youtube", "waiting", code="AAA")
        ms.publish("sweettv", "done")
        self.assertEqual([s["service"] for s in ms.active()], ["youtube"])

    def test_cancel_request_lives_until_the_next_sign_in_begins(self):
        self.assertFalse(ms.cancel_requested("youtube"))
        self.assertTrue(ms.request_cancel("youtube"))
        self.assertTrue(ms.cancel_requested("youtube"))
        self.assertFalse(ms.cancel_requested("sweettv"))
        ms.begin("youtube")
        self.assertFalse(ms.cancel_requested("youtube"))

    def test_begin_forgets_the_last_result(self):
        ms.publish("youtube", "failed")
        ms.begin("youtube")
        self.assertIsNone(ms.read("youtube"))

    def test_a_broken_file_reads_as_nothing(self):
        put(os.path.join(ms.DIR, "youtube.json"), "{not json")
        self.assertIsNone(ms.read("youtube"))
        put(os.path.join(ms.DIR, "youtube.json"), json.dumps({"state": "sleeping"}))
        self.assertIsNone(ms.read("youtube"))
        put(os.path.join(ms.DIR, "youtube.json"), json.dumps([1, 2]))
        self.assertIsNone(ms.read("youtube"))

    def test_publishing_never_raises_when_the_directory_is_not_writable(self):
        blocked = os.path.join(TMP, "file-not-dir")
        put(blocked, "x")
        old, ms.DIR = ms.DIR, os.path.join(blocked, "signin")     # a file where a directory should be
        try:
            self.assertFalse(ms.publish("youtube", "waiting", code="AAA"))
            self.assertFalse(ms.touch("youtube"))
            self.assertFalse(ms.request_cancel("youtube"))
            self.assertIsNone(ms.read("youtube"))
        finally:
            ms.DIR = old

    def test_the_files_are_world_readable_for_the_panel(self):
        ms.publish("youtube", "waiting", code="AAA")
        self.assertEqual(os.stat(os.path.join(ms.DIR, "youtube.json")).st_mode & 0o777, 0o644)
        self.assertEqual([n for n in os.listdir(ms.DIR) if n.endswith(".tmp")], [])


class Partner(unittest.TestCase):
    """The mode of a sign-in, its time to live, the phone's request for it, and the waiting rules."""

    def setUp(self):
        for service in ms.SERVICES:
            ms.begin(service)
            ms.clear_mode(service)

    def test_a_sign_in_is_normal_unless_it_says_partner_and_each_lives_as_long_as_its_mode_allows(self):
        ms.publish("sweettv", "waiting", code="12345")
        s = ms.read("sweettv")
        self.assertEqual(s["mode"], "normal")
        self.assertLessEqual(s["left"], 10 * 60)
        self.assertGreater(s["left"], 10 * 60 - 5)
        ms.publish("sweettv", "waiting", code="12345", mode="partner")
        s = ms.read("sweettv")
        self.assertEqual(s["mode"], "partner")
        self.assertLessEqual(s["left"], 6 * 60 * 60)
        self.assertGreater(s["left"], 6 * 60 * 60 - 5)
        ms.publish("sweettv", "waiting", code="12345", mode="partner", ttl=30)   # an explicit ttl still wins
        self.assertLessEqual(ms.read("sweettv")["left"], 30)

    def test_an_unknown_mode_is_normal_and_a_result_reads_with_its_mode(self):
        ms.publish("sweettv", "waiting", code="1", mode="admin")
        self.assertEqual(ms.read("sweettv")["mode"], "normal")
        ms.publish("sweettv", "done", mode="partner")
        self.assertEqual((ms.read("sweettv")["mode"], ms.read("sweettv")["left"]), ("partner", 0))
        put(os.path.join(ms.DIR, "sweettv.json"), json.dumps({"state": "waiting", "updated": time.time(), "expires": time.time() + 9}))
        self.assertEqual(ms.read("sweettv")["mode"], "normal")                    # a state written before modes existed

    def test_the_partner_state_goes_stale_when_nobody_touches_it_however_long_its_code_lives(self):
        ms.publish("sweettv", "waiting", code="12345", mode="partner")
        self.assertIsNone(ms.read("sweettv", time.time() + ms.HEARTBEAT + 5))
        self.assertTrue(ms.touch("sweettv"))
        self.assertEqual(ms.read("sweettv")["mode"], "partner")                   # touching keeps the mode

    def test_the_phone_asks_for_a_mode_and_the_add_on_takes_it_once(self):
        self.assertEqual(ms.take_mode("sweettv"), "normal")
        self.assertTrue(ms.request_mode("sweettv", "partner"))
        self.assertEqual(ms.requested_mode("sweettv"), "partner")
        self.assertEqual(ms.requested_mode("youtube"), "normal")
        self.assertEqual(os.stat(os.path.join(ms.DIR, "sweettv.mode")).st_mode & 0o777, 0o644)
        self.assertEqual(ms.take_mode("sweettv"), "partner")
        self.assertEqual(ms.take_mode("sweettv"), "normal")                       # used up

    def test_a_request_nobody_took_is_forgotten_and_a_plain_one_withdraws_it(self):
        ms.request_mode("sweettv", "partner")
        self.assertEqual(ms.requested_mode("sweettv", time.time() + ms.MODE_KEEP - 5), "partner")
        self.assertEqual(ms.requested_mode("sweettv", time.time() + ms.MODE_KEEP + 5), "normal")
        self.assertEqual(ms.requested_mode("sweettv", time.time() - ms.MODE_KEEP - 5), "normal")   # nor a clock far in the other direction
        self.assertTrue(ms.request_mode("sweettv", "normal"))
        self.assertEqual(ms.requested_mode("sweettv"), "normal")
        self.assertFalse(os.path.exists(os.path.join(ms.DIR, "sweettv.mode")))
        self.assertFalse(ms.request_mode("netflix", "partner"))

    def test_a_broken_request_is_normal(self):
        for text in ("", "partner", "partner x", "admin 5", "partner 1 2"):
            put(os.path.join(ms.DIR, "sweettv.mode"), text)
            self.assertEqual(ms.requested_mode("sweettv"), "normal", text)

    def test_begin_keeps_a_request_for_the_sign_in_it_starts(self):
        ms.request_mode("sweettv", "partner")
        ms.begin("sweettv")
        self.assertEqual(ms.take_mode("sweettv"), "partner")

    def test_waiting_any_is_true_only_for_a_live_waiting_state(self):
        self.assertFalse(ms.waiting_any())
        ms.publish("sweettv", "done")
        self.assertFalse(ms.waiting_any())
        ms.publish("sweettv", "waiting", code="1", mode="partner")
        self.assertTrue(ms.waiting_any())
        self.assertFalse(ms.waiting_any(time.time() + ms.HEARTBEAT + 5))          # nobody touches it: Kodi is gone
        ms.publish("youtube", "waiting", code="A", ttl=30)
        ms.begin("sweettv")
        self.assertTrue(ms.waiting_any())
        self.assertFalse(ms.waiting_any(time.time() + 31))                        # ran out

    def test_the_update_script_asks_through_the_command_line(self):
        import contextlib
        import io
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(ms.main(["waiting"]), 0)
        self.assertEqual(out.getvalue(), "")
        ms.publish("sweettv", "waiting", code="12345", mode="partner")
        with contextlib.redirect_stdout(out):
            self.assertEqual(ms.main(["waiting"]), 3)
        self.assertRegex(out.getvalue(), r"SWEET\.TV sign-in waits for a code \(partner, 3[56]\d min left\)")
        self.assertNotIn("12345", out.getvalue())                                 # the code stays out of the update's log
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ms.main([]), 2)
            self.assertEqual(ms.main(["x"]), 2)

    def test_checks_come_every_three_seconds_for_ten_minutes_then_every_twelve(self):
        poll = ms.PartnerPoll(1000.0)
        self.assertEqual([poll.delay(1000.0 + t) for t in (0, 3, 599)], [3, 3, 3])
        self.assertEqual([poll.delay(1000.0 + t) for t in (600, 601, 6 * 3600)], [12, 12, 12])
        self.assertTrue(10 <= ms.POLL_SLOW <= 15)

    def test_no_answer_is_retried_after_five_then_longer_up_to_a_minute_and_never_gives_up(self):
        poll = ms.PartnerPoll(0)
        waits = [poll.no_answer(1.0 * i)[0] for i in range(1, 12)]
        self.assertEqual(waits, [5, 10, 20, 40, 60, 60, 60, 60, 60, 60, 60])
        self.assertEqual(poll.no_answer(99)[0], 60)
        poll.answer({"result": "PENDING"}, 100)                                   # an answer, whatever it says, starts the count again
        self.assertEqual(poll.no_answer(101)[0], 5)

    def test_no_answer_is_logged_at_the_start_of_a_streak_and_then_every_tenth(self):
        poll = ms.PartnerPoll(0)
        notes = [poll.no_answer(i)[1] for i in range(1, 22)]
        self.assertEqual([i + 1 for i, n in enumerate(notes) if n], [1, 10, 20])
        self.assertIn("no answer", notes[0])

    def test_completed_is_completed_and_nothing_else_is(self):
        poll = ms.PartnerPoll(0)
        self.assertEqual(poll.answer({"result": "COMPLETED", "access_token": "SECRET"}, 1), ("completed", ""))
        for reply in ({"result": "completed"}, {"result": "OK"}, {}, {"status": "COMPLETED"}):
            self.assertEqual(poll.answer(reply, 1)[0], "unknown", reply)

    def test_an_answer_nobody_described_is_logged_once_and_waited_on(self):
        poll = ms.PartnerPoll(0)
        verdict, note = poll.answer({"result": "WAITING_FOR_PARTNER", "code": 13}, 10)
        self.assertEqual(verdict, "unknown")
        self.assertIn("WAITING_FOR_PARTNER", note)
        self.assertIn("'code': 13", note)                                          # a status code is not a secret
        self.assertEqual(poll.answer({"result": "WAITING_FOR_PARTNER", "code": 13}, 13), ("unknown", ""))
        self.assertEqual(poll.answer({"result": "WAITING_FOR_PARTNER", "code": 13}, 10 + ms.LOG_AGAIN - 1), ("unknown", ""))
        self.assertIn("WAITING_FOR_PARTNER", poll.answer({"result": "WAITING_FOR_PARTNER", "code": 13}, 10 + ms.LOG_AGAIN)[1])
        self.assertIn("OTHER", poll.answer({"result": "OTHER"}, 11)[1])           # a different one is logged at once

    def test_no_text_means_refused_until_one_is_named(self):
        self.assertEqual(ms.SWEETTV_REFUSED, frozenset())
        self.assertEqual(ms.PartnerPoll(0).answer({"result": "CODE_EXPIRED"}, 1)[0], "unknown")
        with unittest.mock.patch.object(ms, "SWEETTV_REFUSED", frozenset({"CODE_EXPIRED"})):
            verdict, note = ms.PartnerPoll(0).answer({"result": "CODE_EXPIRED"}, 1)
        self.assertEqual(verdict, "refused")
        self.assertIn("CODE_EXPIRED", note)
        self.assertEqual(ms.PartnerPoll(0, refused={"NO"}).answer({"result": "NO"}, 1)[0], "refused")
        self.assertEqual(ms.PartnerPoll(0, refused={"NO"}).answer({"result": ["NO"]}, 1)[0], "unknown")   # not even a text

    def test_a_logged_reply_is_short_and_hides_what_looks_like_a_secret(self):
        reply = {"result": "ODD", "access_token": "SECRET-1", "refresh_token": "SECRET-2", "auth_code": "SECRET-3",
                 "Authorization": "SECRET-4", "cookie": "SECRET-5", "detail": "x" * 500}
        text = ms.describe(reply)
        self.assertLessEqual(len(text), ms.NOTE_MAX)
        self.assertNotIn("SECRET", text)
        self.assertIn("ODD", text)
        note = ms.PartnerPoll(0).answer(reply, 1)[1]
        self.assertNotIn("SECRET", note)
        self.assertLessEqual(len(note), ms.NOTE_MAX + 120)
        self.assertEqual(ms.describe(["SECRET"]), "<list>")
        self.assertNotIn("SECRET", ms.describe("SECRET"))
        self.assertNotIn("SECRET", ms.describe(None) + ms.describe(7))


class Accounts(unittest.TestCase):
    def setUp(self):
        ms.begin("youtube")
        ms.begin("sweettv")
        for rel in ("plugin.video.youtube/access_manager.json", "plugin.video.sweettv/settings.xml"):
            try:
                os.unlink(os.path.join(ms.USERDATA, rel))
            except OSError:
                pass

    def yt(self, data):
        put(os.path.join(ms.USERDATA, "plugin.video.youtube", "access_manager.json"), json.dumps(data))

    def test_youtube_profiles_say_how_many_of_the_four_codes_each_has(self):
        self.yt({"access_manager": {"current_user": 1, "users": {
            "0": {"name": "Default", "refresh_token": ""},
            "1": {"name": "Mum", "refresh_token": "a|b||"},
            "2": {"name": "Dad", "refresh_token": "a|b|c|d"}}}})
        got = {p["id"]: p for p in ms.youtube_accounts()}
        self.assertEqual([p["id"] for p in ms.youtube_accounts()], ["0", "1", "2"])
        self.assertEqual((got["0"]["signed_in"], got["0"]["tokens"]), (False, 0))
        self.assertEqual((got["1"]["signed_in"], got["1"]["tokens"], got["1"]["current"]), (True, 2, True))
        self.assertEqual((got["2"]["tokens"], got["2"]["current"]), (4, False))

    def test_profiles_sort_by_number_not_text(self):
        self.yt({"access_manager": {"current_user": 0, "users": {str(i): {"name": f"u{i}"} for i in (10, 2, 1, 0)}}})
        self.assertEqual([p["id"] for p in ms.youtube_accounts()], ["0", "1", "2", "10"])

    def test_no_file_or_a_bad_one_is_no_profiles(self):
        self.assertEqual(ms.youtube_accounts(), [])
        put(os.path.join(ms.USERDATA, "plugin.video.youtube", "access_manager.json"), "{")
        self.assertEqual(ms.youtube_accounts(), [])
        self.yt({"access_manager": {"users": {"0": "not a dict"}}})
        self.assertEqual(ms.youtube_accounts()[0]["signed_in"], False)

    def test_no_secret_leaves_the_module(self):
        self.yt({"access_manager": {"current_user": 0, "users": {"0": {"name": "A", "refresh_token": "SECRET-1|SECRET-2",
                                                                        "access_token": "SECRET-3"}}}})
        self.assertNotIn("SECRET", json.dumps(ms.accounts()))

    def test_sweettv_is_signed_in_when_the_add_on_says_logged(self):
        path = os.path.join(ms.USERDATA, "plugin.video.sweettv", "settings.xml")
        self.assertFalse(ms.sweettv_signed_in())
        put(path, '<settings version="2"><setting id="logged">true</setting><setting id="bearer">SECRET</setting></settings>')
        self.assertTrue(ms.sweettv_signed_in())
        put(path, '<settings version="2"><setting id="logged">false</setting></settings>')
        self.assertFalse(ms.sweettv_signed_in())
        put(path, "<settings")
        self.assertFalse(ms.sweettv_signed_in())
        self.assertNotIn("SECRET", json.dumps(ms.accounts()))

    def test_accounts_lists_every_service_with_its_sign_in(self):
        ms.publish("sweettv", "waiting", code="999")
        by = {a["service"]: a for a in ms.accounts()}
        self.assertEqual(sorted(by), ["sweettv", "youtube"])
        self.assertEqual(by["sweettv"]["signin"]["code"], "999")
        self.assertIsNone(by["youtube"]["signin"])


class Overlays(unittest.TestCase):
    """The overlays replace files of third-party add-ons pinned in device/kodi-addons.list."""
    FILES = {
        "plugin.video.youtube/resources/lib/youtube_plugin/youtube/helper/yt_login.py": "plugin.video.youtube",
        "plugin.video.youtube/resources/lib/youtube_plugin/kodion/script_actions.py": "plugin.video.youtube",
        "plugin.video.sweettv/resources/lib/sweettv.py": "plugin.video.sweettv",
    }

    @staticmethod
    def pinned():
        out = {}
        with open(os.path.join(ROOT, "device", "kodi-addons.list"), encoding="utf-8") as lines:
            for line in lines:
                f = line.split()
                if len(f) == 4 and not f[0].startswith("#"):
                    out[f[0]] = f[1]
        return out

    def text(self, rel):
        with open(os.path.join(OVERLAY, rel), encoding="utf-8") as f:
            return f.read()

    def test_each_overlay_was_made_for_the_version_that_is_pinned(self):
        pinned = self.pinned()
        for rel, addon in self.FILES.items():
            m = re.match(r"# media-stick overlay of \S+ \(([\d.]+), upstream sha256 [0-9a-f]{64}\)", self.text(rel))
            self.assertIsNotNone(m, rel)
            self.assertEqual(m.group(1), pinned[addon],
                             f"{rel} was made for {m.group(1)} but {addon} is pinned at {pinned[addon]}: redo the overlay")

    def test_overlays_compile_and_every_change_is_fenced(self):
        for rel in self.FILES:
            text = self.text(rel)
            compile(text, rel, "exec")
            begins = len(re.findall(r"^\s*# media-stick begin", text, re.M))
            ends = len(re.findall(r"^\s*# media-stick end", text, re.M))
            self.assertEqual(begins, ends, rel)
            self.assertGreater(begins, 0, rel)

    def test_the_add_on_still_runs_without_the_library(self):
        for rel in ("plugin.video.youtube/resources/lib/youtube_plugin/youtube/helper/yt_login.py",
                    "plugin.video.sweettv/resources/lib/sweettv.py"):
            text = self.text(rel)
            self.assertIn("except Exception:", text)
            self.assertIn("_ms = None", text)
            self.assertIn("/usr/local/lib/media-stick", text)

    def test_every_use_of_the_library_is_guarded(self):
        for rel in self.FILES:
            lines = self.text(rel).splitlines()
            for i, line in enumerate(lines):
                if "_ms." in line and "import" not in line:
                    context = "\n".join(lines[max(0, i - 3):i + 1])
                    self.assertRegex(context, r"if _ms|_ms is None|ms_", f"{rel}:{i + 1} unguarded: {line.strip()}")


def load_overlay_tool():
    spec = importlib.util.spec_from_file_location("make_skin_overlays", os.path.join(ROOT, "tools", "make-skin-overlays.py"))
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool


class OverlayTool(unittest.TestCase):
    """tools/make-skin-overlays.py rebuilds the overlays from the pinned zips. That needs the network,
    so `python3 tools/make-skin-overlays.py --check` stays a manual step; here only what needs no zip."""
    tool = load_overlay_tool()

    def text(self, rel):
        with open(os.path.join(OVERLAY, rel), encoding="utf-8", newline="") as f:
            return f.read()

    def test_it_makes_the_overlays_of_the_pinned_add_ons_and_leaves_no_bytecode_behind(self):
        self.assertEqual({f"{addon}/{path}" for addon, path, _ in self.tool.OVERLAYS}, set(Overlays.FILES))
        for folder, _, names in os.walk(OVERLAY):  # (skin.ftv's pointer files there are ours, not made from upstream)
            self.assertNotIn("__pycache__", folder)
            self.assertEqual([n for n in names if n.endswith(".pyc")], [])

    def test_every_edit_of_the_tool_sits_in_its_committed_overlay_once(self):
        for addon, path, edits in self.tool.OVERLAYS:
            text = self.text(f"{addon}/{path}")
            for _, new in edits:
                self.assertEqual(text.count(new), 1, f"{addon}/{path}: the tool and the overlay disagree on:\n{new}")

    def test_the_header_names_the_file_the_version_and_the_upstream_hash(self):
        for addon, path, _ in self.tool.OVERLAYS:
            name, version, sha = self.tool.parse_header(self.text(f"{addon}/{path}"))
            self.assertEqual(name, os.path.basename(path))
            self.assertEqual(version, Overlays.pinned()[addon])
            self.assertEqual(len(sha), 64)

    def test_build_hashes_the_upstream_bytes_and_keeps_them_after_the_header(self):
        upstream = b"a = 1\r\nb = 2\r\n"
        built = self.tool.build(upstream, [("b = 2\n", "b = 3\n")], "x.py", "1.0")
        head, body = built.split("\n", 1)
        self.assertEqual(self.tool.parse_header(head),
                         ("x.py", "1.0", hashlib.sha256(upstream).hexdigest()))
        self.assertEqual(body, "a = 1\nb = 3\n")

    def test_an_anchor_that_is_missing_or_repeated_stops_the_rebuild(self):
        for upstream in (b"nothing here\n", b"x\nx\n"):
            with self.assertRaises(self.tool.Stop):
                self.tool.build(upstream, [("x\n", "y\n")], "x.py", "1.0")


class LoginException(Exception):
    pass


class Dialog:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def set_total(self, n):
        pass

    def update(self):
        pass

    def is_aborted(self):
        return False


class UI:
    def __init__(self):
        self.ok = []
        self.dialogs = []                                 # every progress dialog the add-on opened

    def on_ok(self, *a):
        self.ok.append(a)

    def bold(self, text):
        return text

    def show_notification(self, *a):
        pass

    def create_progress_dialog(self, **kw):
        self.dialogs.append(kw)
        return Dialog()


class AccessManager:
    def get_access_tokens(self):
        return ["", "", "", ""], 0, 0

    def get_refresh_tokens(self):
        return ["", "", "", ""], 0

    def update_access_token(self, addon_id, *args):
        self.saved = args


class Client:
    """Hands out one code per token type; a code is approved after `pending` polls."""
    def __init__(self, pending=1, on_poll=None, answer=None, reply=None):
        self.pending, self.on_poll, self.answer, self.reply = pending, on_poll, answer, reply or {}
        self.codes, self.polls = [], {}

    def internet_available(self):
        return True

    def request_device_and_user_code(self, idx):
        self.codes.append(idx)
        return {"device_code": f"dev{idx}", "user_code": f"CODE-{idx}", "interval": 5,
                "verification_url": "https://www.youtube.com/activate", **self.reply}

    def request_access_token(self, idx, device_code):
        n = self.polls[idx] = self.polls.get(idx, 0) + 1
        if self.on_poll:
            self.on_poll(idx, n)
        if self.answer:
            return self.answer
        if n <= self.pending:
            return {"error": "authorization_pending"}
        return {"access_token": f"a{idx}", "refresh_token": f"r{idx}", "expires_in": 3600}


class Provider:
    FORCE_REFRESH = "refresh"

    def __init__(self, client):
        self.client = client

    def get_client(self, context):
        return self.client

    def reset_client(self, **kw):
        pass


class Context:
    def __init__(self):
        self.ui, self.am = UI(), AccessManager()

    def get_access_manager(self):
        return self.am

    def get_param(self, key, default=None):
        return default

    def localize(self, key, *a):
        return key

    def get_function_cache(self):
        return type("Cache", (), {"ONE_MINUTE": 60, "run": staticmethod(lambda fn, ttl, _refresh=False: True)})()

    def get_ui(self):
        return self.ui

    def get_name(self):
        return "YouTube"

    def sleep(self, seconds):
        pass


def load_yt_login():
    """The overlay, imported under a stand-in for the add-on's package tree."""
    import importlib.util
    import types
    for name in ("youtube_plugin", "youtube_plugin.youtube", "youtube_plugin.youtube.helper", "youtube_plugin.kodion"):
        module = types.ModuleType(name)
        module.__path__ = []
        sys.modules[name] = module
    exceptions = types.ModuleType("youtube_plugin.youtube.youtube_exceptions")
    exceptions.LoginException = LoginException
    sys.modules["youtube_plugin.youtube.youtube_exceptions"] = exceptions
    quiet = lambda *a, **k: None  # noqa: E731
    sys.modules["youtube_plugin.kodion"].logging = types.SimpleNamespace(debug=quiet, error_trace=quiet, error=quiet)
    path = os.path.join(OVERLAY, "plugin.video.youtube", "resources", "lib", "youtube_plugin", "youtube", "helper", "yt_login.py")
    spec = importlib.util.spec_from_file_location("youtube_plugin.youtube.helper.yt_login", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class YouTubeSignIn(unittest.TestCase):
    """The overlay's own logic, run against stand-ins for everything the add-on brings."""

    def setUp(self):
        sys.modules["mediastick_signin"] = ms
        self.yt = load_yt_login()
        ms.begin("youtube")
        self.seen = []
        real = ms.publish
        self.addCleanup(setattr, ms, "publish", real)
        ms.publish = lambda *a, **k: (self.seen.append((a, k)), real(*a, **k))[1]

    def run_login(self, client):
        context = Context()
        return self.yt._do_login(Provider(client), context), context

    def states(self):
        return [(a[1], k.get("step")) for a, k in self.seen]

    def test_four_codes_are_published_one_after_another_and_the_end_says_done(self):
        client = Client(pending=2)
        ok, context = self.run_login(client)
        self.assertTrue(ok)
        self.assertEqual(self.states(), [("waiting", 1), ("waiting", 2), ("waiting", 3), ("waiting", 4), ("done", None)])
        self.assertEqual([k["code"] for a, k in self.seen[:4]], [f"CODE-{i}" for i in range(4)])
        self.assertEqual({k["steps"] for a, k in self.seen[:4]}, {4})
        self.assertEqual(self.seen[0][1]["url"], "https://www.youtube.com/activate")
        self.assertEqual(self.seen[0][1]["link"], "")                  # the answer had no complete link
        self.assertEqual(context.ui.ok, [])               # the upstream "sign in several times" dialog is skipped
        self.assertEqual(context.ui.dialogs, [])          # and the code is not shown in a dialog either: the TV screen has it
        self.assertEqual(ms.read("youtube")["state"], "done")

    def test_a_personal_client_answer_gives_its_own_page_and_complete_link_to_the_screens(self):
        client = Client(pending=1, reply={"verification_url": "https://www.google.com/device"})
        self.run_login(client)
        self.assertEqual(self.seen[0][1]["url"], "https://www.google.com/device")
        self.assertEqual(ms.read("youtube")["state"], "done")
        ms.begin("youtube")
        self.seen.clear()
        client = Client(pending=1, reply={"verification_url": "https://www.google.com/device",
                                          "verification_url_complete": "https://www.google.com/device?user_code=CODE-0"})
        self.run_login(client)
        self.assertEqual(self.seen[0][1]["link"], "https://www.google.com/device?user_code=CODE-0")

    def test_a_stop_request_ends_the_whole_sign_in_not_just_one_code(self):
        client = Client(pending=99, on_poll=lambda idx, n: ms.request_cancel("youtube") if idx == 1 and n == 2 else None)
        ok, context = self.run_login(client)
        self.assertFalse(ok)
        self.assertEqual(context.ui.dialogs, [])
        self.assertEqual(client.codes, [0, 1])            # no third code was asked for
        self.assertEqual(self.states()[-1][0], "cancelled")
        self.assertEqual(ms.read("youtube")["state"], "cancelled")

    def test_a_stop_asked_for_before_the_first_poll_still_ends_it_and_asks_for_no_token(self):
        self.addCleanup(setattr, ms, "begin", ms.begin)
        ms.begin = lambda service: None                   # begin() would forget the request: keep it, as if it came during the first code
        ms.request_cancel("youtube")
        client = Client(pending=99)
        ok, context = self.run_login(client)
        self.assertFalse(ok)
        self.assertEqual(client.polls, {})
        self.assertEqual(context.ui.dialogs, [])
        self.assertEqual(ms.read("youtube")["state"], "cancelled")

    def test_a_refused_code_is_not_reported_as_signed_in(self):
        client = Client(answer={"error": "access_denied"})
        ok, context = self.run_login(client)
        self.assertEqual(ms.read("youtube")["state"], "failed")
        self.assertEqual(context.ui.dialogs, [])

    def test_the_stand_in_for_the_dialog_does_nothing_and_never_aborts(self):
        with self.yt._MsNoDialog() as dialog:
            dialog.set_total(60)
            dialog.update()
            self.assertFalse(dialog.is_aborted())

    def test_each_poll_keeps_the_waiting_state_alive(self):
        beats = []
        client = Client(pending=3, on_poll=lambda idx, n: beats.append(ms.read("youtube")["updated"]) if idx == 0 else None)
        self.run_login(client)
        self.assertEqual(len(beats), 4)
        self.assertTrue(all(b > 0 for b in beats))

    def test_without_the_library_it_is_the_upstream_flow(self):
        sys.modules["mediastick_signin"] = None           # makes `import mediastick_signin` fail
        yt = load_yt_login()
        self.assertIsNone(yt._ms)
        context = Context()
        ok = yt._do_login(Provider(Client(pending=0)), context)
        self.assertTrue(ok)
        self.assertEqual(len(context.ui.ok), 1)           # the upstream dialog is back
        self.assertEqual(len(context.ui.dialogs), 4)      # one progress dialog per code, as upstream
        self.assertEqual(context.ui.dialogs[0]["heading"], "sign.in")
        self.assertIn("CODE-0", context.ui.dialogs[0]["message"])
        self.assertEqual(self.seen, [])

    def test_without_the_library_an_aborted_dialog_still_gives_up_on_the_code(self):
        sys.modules["mediastick_signin"] = None
        yt = load_yt_login()
        context = Context()
        aborted = type("Aborted", (Dialog,), {"is_aborted": lambda self: True})
        context.ui.create_progress_dialog = lambda **kw: aborted()
        client = Client(pending=99)
        yt._do_login(Provider(client), context)
        self.assertEqual(client.polls, {0: 1, 1: 1, 2: 1, 3: 1})    # upstream: one poll per code, then the abort ends it


class SweetResponse:
    def __init__(self, status_code=200, content=b"png"):
        self.status_code, self.content = status_code, content


class SweetHelper:
    """Stand-in for the add-on's Helper: records what the login asks for and what it stores."""
    auth_url, check_auth_url, base_api_url = "https://sweet/auth", "https://sweet/check", "https://sweet/{}"
    headers, json_data = {}, {}

    def __init__(self, base_url, handle):
        self.settings, self.requests, self.notes, self.refreshed = {}, [], [], 0
        self.checks, self.on_check, self.auth_reply = [], None, {"result": "OK", "auth_code": "12345"}

    def request_sess(self, url, method="get", **kw):
        self.requests.append(url)
        if url == self.auth_url:
            return self.auth_reply
        if url == self.check_auth_url:
            if self.on_check:
                self.on_check(self.requests.count(self.check_auth_url))
            return self.checks.pop(0) if self.checks else {"result": "PENDING"}
        return SweetResponse()                            # the QR image

    def get_setting(self, key):
        return self.settings.get(key, "")

    def set_setting(self, key, value):
        self.settings[key] = value

    def notification(self, *a):
        self.notes.append(a)

    def refresh(self):
        self.refreshed += 1


class Clock:
    """A clock the login's sleeps move forward: ten minutes of waiting take no time."""
    def __init__(self):
        self.now = time.time()

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


COMPLETED = {"result": "COMPLETED", "access_token": "tok", "refresh_token": "ref", "expires_in": 3600}


def load_sweettv(with_library):
    """The overlay, imported under stand-ins for Kodi, its helper and the add-on's package."""
    import types
    from unittest import mock

    class WindowDialog:
        made = []

        def __init__(self):
            WindowDialog.made.append(self)

        def doModal(self):                                # modal until the login thread ends or the user closes it
            for _ in range(500):
                if sweet.QRPopup.exit_flag or not sweet.QRPopup.running:
                    break
                time.sleep(0.01)

        def close(self):
            pass

        def __getattr__(self, name):                      # addControl, setFocus, ...
            return lambda *a, **k: None

    class Plugin:
        def route(self, path):
            return lambda fn: fn

    vfs = types.SimpleNamespace(
        deleted=[], written=[],
        translatePath=lambda p: "/tmp/",
        delete=lambda path: vfs.deleted.append(path),
        File=lambda path, mode: type("F", (), {"write": lambda self, data: vfs.written.append(path),
                                               "close": lambda self: None})())
    gui = types.SimpleNamespace(
        WindowDialog=WindowDialog, ListItem=object, Dialog=object, NOTIFICATION_INFO=0, NOTIFICATION_ERROR=1,
        ControlLabel=lambda *a, **k: None, ControlImage=lambda *a, **k: None, ControlButton=lambda *a, **k: None)
    parse = types.ModuleType("six.moves.urllib.parse")
    parse.urlencode = lambda *a, **k: ""
    logs = []
    package = types.ModuleType("sweettv_addon")
    package.__path__ = []
    helper_module = types.ModuleType("sweettv_addon.helper")
    helper_module.Helper = SweetHelper
    stubs = {
        "routing": types.SimpleNamespace(Plugin=Plugin),
        "urllib3": types.SimpleNamespace(disable_warnings=lambda: None),
        "xbmc": types.SimpleNamespace(log=lambda msg, level=0: logs.append((level, msg)), LOGDEBUG=0, LOGERROR=1,
                                      LOGWARNING=2, translatePath=lambda p: "/tmp/"),
        "xbmcgui": gui, "xbmcplugin": types.SimpleNamespace(), "xbmcvfs": vfs,
        "six": types.ModuleType("six"), "six.moves": types.ModuleType("six.moves"),
        "six.moves.urllib": types.ModuleType("six.moves.urllib"), "six.moves.urllib.parse": parse,
        "sweettv_addon": package, "sweettv_addon.helper": helper_module,
        "mediastick_signin": ms if with_library else None,
    }
    path = os.path.join(OVERLAY, "plugin.video.sweettv", "resources", "lib", "sweettv.py")
    spec = importlib.util.spec_from_file_location("sweettv_addon.sweettv", path)
    sweet = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, stubs), mock.patch.object(sys, "argv", ["plugin://plugin.video.sweettv/", "1"]):
        sys.modules[spec.name] = sweet
        spec.loader.exec_module(sweet)
    sweet.vfs, sweet.WindowDialog, sweet.logs = vfs, WindowDialog, logs
    sweet.channel_refreshes = []
    sweet.refreshChannelList = lambda: sweet.channel_refreshes.append(1)    # needs the whole API: not what is tested
    return sweet


class SweetTVSignIn(unittest.TestCase):
    """The SWEET.TV overlay's login, run against stand-ins: on the device no popup and no QR request."""

    def setUp(self):
        ms.begin("sweettv")
        self.seen = []
        real = ms.publish
        self.addCleanup(setattr, ms, "publish", real)
        ms.publish = lambda *a, **k: (self.seen.append((a, k)), real(*a, **k))[1]

    def states(self):
        return [a[1] for a, k in self.seen]

    def device(self):
        sweet = load_sweettv(True)
        clock = Clock()
        sweet.time = type("T", (), {"time": staticmethod(clock.time), "sleep": staticmethod(clock.sleep)})
        return sweet, clock

    def test_on_the_device_no_popup_is_made_and_the_qr_is_not_requested(self):
        sweet, _ = self.device()
        sweet.helper.checks = [{"result": "PENDING"}, COMPLETED]
        sweet.login()
        self.assertEqual(sweet.WindowDialog.made, [])
        self.assertEqual(sweet.helper.requests, [sweet.helper.auth_url] + [sweet.helper.check_auth_url] * 2)
        self.assertEqual(sweet.vfs.written, [])
        self.assertEqual(self.states(), ["waiting", "done"])
        self.assertEqual(ms.read("sweettv")["state"], "done")
        self.assertEqual((sweet.helper.settings["logged"], sweet.helper.settings["bearer"]), ("true", "Bearer tok"))
        self.assertEqual(sweet.helper.refreshed, 1)
        self.assertEqual(sweet.channel_refreshes, [1])
        self.assertEqual(self.seen[0][1]["code"], "12345")

    def test_each_poll_keeps_the_waiting_state_alive(self):
        sweet, _ = self.device()
        beats = []
        sweet.helper.on_check = lambda n: beats.append(ms.read("sweettv")["updated"])
        sweet.helper.checks = [{"result": "PENDING"}, {"result": "PENDING"}, COMPLETED]
        sweet.login()
        self.assertEqual(len(beats), 3)
        self.assertTrue(all(b > 0 for b in beats))

    def test_a_stop_request_cancels_it_with_no_popup_to_close(self):
        sweet, _ = self.device()
        sweet.helper.on_check = lambda n: ms.request_cancel("sweettv") if n == 2 else None
        sweet.login()
        self.assertEqual(self.states(), ["waiting", "cancelled"])
        self.assertEqual(ms.read("sweettv")["state"], "cancelled")
        self.assertEqual(sweet.helper.settings["logged"], "false")
        self.assertEqual(sweet.helper.requests.count(sweet.helper.check_auth_url), 2)   # it stopped asking
        self.assertEqual(sweet.WindowDialog.made, [])
        self.assertEqual(sweet.helper.notes, [])          # "Login interrupted" needs a popup
        self.assertEqual(sweet.helper.refreshed, 1)

    def test_a_stop_asked_for_before_the_first_poll_ends_it_at_once(self):
        sweet, _ = self.device()
        self.addCleanup(setattr, ms, "begin", ms.begin)
        ms.begin = lambda service: None                   # begin() would forget the request: keep it
        ms.request_cancel("sweettv")
        sweet.login()
        self.assertEqual(self.states(), ["waiting", "cancelled"])
        self.assertEqual(sweet.helper.requests, [sweet.helper.auth_url])

    def test_a_code_nobody_enters_ends_as_failed_not_forever(self):
        sweet, clock = self.device()
        start = clock.now
        sweet.login()
        self.assertEqual(self.states(), ["waiting", "failed"])
        self.assertEqual(sweet.helper.settings["logged"], "false")
        self.assertGreaterEqual(clock.now - start, 10 * 60)
        self.assertLess(clock.now - start, 10 * 60 + 10)

    def test_a_check_that_gets_no_answer_ends_as_failed(self):
        sweet, _ = self.device()
        sweet.helper.checks = [None]
        sweet.login()
        self.assertEqual(self.states(), ["waiting", "failed"])
        self.assertEqual(ms.read("sweettv")["state"], "failed")

    def test_a_refused_code_request_ends_as_failed(self):
        sweet, _ = self.device()
        sweet.helper.auth_reply = {"result": "ERROR"}
        sweet.login()
        self.assertEqual(self.states(), ["failed"])
        self.assertEqual(sweet.helper.requests, [sweet.helper.auth_url])
        self.assertEqual(sweet.WindowDialog.made, [])

    def test_without_the_library_it_is_the_upstream_flow_popup_and_qr_included(self):
        sweet = load_sweettv(False)
        self.assertIsNone(sweet._ms)
        sweet.helper.checks = [COMPLETED]
        sweet.login()
        self.assertEqual(len(sweet.WindowDialog.made), 1)
        self.assertTrue(any("api.qrserver.com" in u for u in sweet.helper.requests))
        self.assertEqual(len(sweet.vfs.written), 1)       # the QR image was fetched and saved
        self.assertEqual(sweet.helper.settings["logged"], "true")
        self.assertEqual(self.seen, [])


class SweetTVPartnerSignIn(unittest.TestCase):
    """The SWEET.TV overlay in partner mode: the code lives six hours, nobody gives up on a bad network,
    and only a named refusal ends it early. The same stand-ins as above; the clock is the login's own."""
    WARNING = 2

    def setUp(self):
        ms.begin("sweettv")
        ms.clear_mode("sweettv")
        self.addCleanup(ms.clear_mode, "sweettv")
        self.seen = []
        real = ms.publish
        self.addCleanup(setattr, ms, "publish", real)
        ms.publish = lambda *a, **k: (self.seen.append((a, k)), real(*a, **k))[1]
        self.touches = []
        touch = ms.touch
        self.addCleanup(setattr, ms, "touch", touch)

    def states(self):
        return [a[1] for a, k in self.seen]

    def device(self):
        sweet = load_sweettv(True)
        clock = Clock()
        sweet.time = type("T", (), {"time": staticmethod(clock.time), "sleep": staticmethod(clock.sleep)})
        real = ms.touch
        ms.touch = lambda service: (self.touches.append(clock.now), real(service))[1]
        self.checked = []                                   # the clock at each check
        sweet.helper.on_check = lambda n: self.checked.append(clock.now)
        return sweet, clock

    def warnings(self, sweet):
        return [m for level, m in sweet.logs if level == self.WARNING]

    def gaps(self):
        return [round(b - a, 3) for a, b in zip(self.checked, self.checked[1:])]

    def test_the_partner_code_is_published_with_its_mode_and_six_hours(self):
        sweet, _ = self.device()
        states = []
        sweet.helper.on_check = lambda n: states.append(ms.read("sweettv"))
        sweet.helper.checks = [COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual((states[0]["mode"], states[0]["state"], states[0]["code"]), ("partner", "waiting", "12345"))
        self.assertGreater(states[0]["left"], 6 * 60 * 60 - 5)
        self.assertLessEqual(states[0]["left"], 6 * 60 * 60)
        self.assertEqual(self.seen[0][1]["mode"], "partner")

    def test_the_phones_request_makes_it_partner_once_and_the_next_sign_in_is_normal_again(self):
        ms.request_mode("sweettv", "partner")
        sweet, _ = self.device()
        sweet.helper.checks = [COMPLETED]
        sweet.login()
        self.assertEqual(self.seen[0][1]["mode"], "partner")
        self.assertEqual(ms.requested_mode("sweettv"), "normal")
        self.seen.clear()
        sweet, _ = self.device()
        sweet.helper.checks = [COMPLETED]
        sweet.login()
        self.assertEqual(self.seen[0][1]["mode"], "normal")

    def test_a_normal_sign_in_is_what_it_was(self):
        sweet, clock = self.device()
        start = clock.now
        left = []
        sweet.helper.on_check = lambda n: left.append(ms.read("sweettv")["left"])
        sweet.login()
        self.assertEqual(self.states(), ["waiting", "failed"])
        self.assertEqual(self.seen[0][1]["mode"], "normal")
        self.assertLessEqual(left[0], 10 * 60)
        self.assertLess(clock.now - start, 10 * 60 + 10)

    def test_checks_come_every_three_seconds_then_every_twelve_after_ten_minutes(self):
        sweet, clock = self.device()
        sweet.helper.on_check = lambda n: (self.checked.append(clock.now),
                                           setattr(sweet.helper, "checks", [COMPLETED]) if n == 230 else None)[0]
        sweet.login(ms_mode="partner")
        gaps = self.gaps()
        self.assertEqual(self.states(), ["waiting", "done"])
        self.assertEqual(len(gaps), 229)
        self.assertEqual(gaps[:200], [3.0] * 200)                            # 200 checks 3 s apart are the first ten minutes
        self.assertEqual(gaps[200:], [12.0] * 29)

    def test_no_answer_is_retried_with_longer_pauses_and_the_login_survives_to_complete(self):
        sweet, _ = self.device()
        sweet.helper.checks = [None, None, None, None, None, None, COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.gaps(), [5.0, 10.0, 20.0, 40.0, 60.0, 60.0])
        self.assertEqual(self.states(), ["waiting", "done"])
        self.assertEqual(sweet.helper.settings["logged"], "true")
        self.assertEqual(len(self.warnings(sweet)), 1)                       # the first miss, not every one

    def test_a_check_that_raises_is_no_answer_too(self):
        sweet, clock = self.device()

        def on_check(n):
            self.checked.append(clock.now)
            if n <= 2:
                raise AttributeError("'NoneType' object has no attribute 'json'")   # what upstream does without a network
            if n == 3:
                raise ValueError("not json")
        sweet.helper.on_check = on_check
        sweet.helper.checks = [COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "done"])
        self.assertEqual(self.gaps(), [5.0, 10.0, 20.0])
        self.assertTrue(any("check failed" in m for m in self.warnings(sweet)))

    def test_a_normal_sign_in_does_not_swallow_an_exception(self):
        sweet, _ = self.device()

        def on_check(n):
            raise AttributeError("no response")
        sweet.helper.on_check = on_check
        with self.assertRaises(AttributeError):
            sweet.login()

    def test_without_an_answer_all_the_way_it_ends_failed_at_the_deadline_and_not_before(self):
        sweet, clock = self.device()
        start = clock.now
        sweet.helper.checks = [None] * 2000
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "failed"])
        self.assertGreaterEqual(clock.now - start, 6 * 60 * 60)
        self.assertLess(clock.now - start, 6 * 60 * 60 + 70)
        self.assertEqual(sweet.helper.settings["logged"], "false")

    def test_the_heartbeat_never_goes_quiet_for_as_long_as_the_state_would_be_read_as_dead(self):
        sweet, clock = self.device()
        sweet.helper.checks = [None] * 12 + [COMPLETED]                      # pauses of a minute in the middle
        sweet.login(ms_mode="partner")
        gaps = [b - a for a, b in zip(self.touches, self.touches[1:])]
        self.assertLessEqual(max(gaps), 3.0 + 1e-6)
        self.assertLess(max(gaps), ms.HEARTBEAT)
        self.assertGreater(len(self.touches), 20)

    def test_an_answer_nobody_described_is_logged_and_the_wait_goes_on(self):
        sweet, _ = self.device()
        odd = {"result": "AWAITING_PARTNER", "access_token": "SECRET-TOKEN", "code": 7}
        sweet.helper.checks = [odd, dict(odd), dict(odd), COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "done"])
        warnings = self.warnings(sweet)
        self.assertEqual(len(warnings), 1)                                   # once, not on every check
        self.assertIn("AWAITING_PARTNER", warnings[0])
        self.assertNotIn("SECRET", warnings[0])
        self.assertLess(len(warnings[0]), 320)

    def test_a_reply_that_is_not_an_object_is_an_unknown_answer(self):
        sweet, _ = self.device()
        sweet.helper.checks = [["x"], "nope", COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "done"])
        self.assertTrue(any("unexpected_reply" in m and "list" in m for m in self.warnings(sweet)))

    def test_a_refusal_that_was_named_ends_it_as_failed(self):
        sweet, _ = self.device()
        sweet.helper.checks = [{"result": "PENDING"}, {"result": "CODE_REFUSED"}, COMPLETED]
        with unittest.mock.patch.object(ms, "SWEETTV_REFUSED", frozenset({"CODE_REFUSED"})):
            sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "failed"])
        self.assertEqual(len(self.checked), 2)                               # it stopped asking
        self.assertEqual(sweet.helper.settings["logged"], "false")
        self.assertTrue(any("CODE_REFUSED" in m for m in self.warnings(sweet)))
        self.assertEqual(sweet.helper.refreshed, 1)

    def test_that_text_is_only_a_refusal_when_it_has_been_named(self):
        sweet, _ = self.device()
        sweet.helper.checks = [{"result": "CODE_REFUSED"}, COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "done"])

    def test_completed_is_done(self):
        sweet, _ = self.device()
        sweet.helper.checks = [{"result": "PENDING"}, COMPLETED]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "done"])
        self.assertEqual(ms.read("sweettv")["state"], "done")
        self.assertEqual((sweet.helper.settings["logged"], sweet.helper.settings["bearer"]), ("true", "Bearer tok"))
        self.assertEqual(sweet.channel_refreshes, [1])
        self.assertEqual(sweet.WindowDialog.made, [])
        self.assertEqual(sweet.helper.requests.count("https://api.qrserver.com/v1/create-qr-code/"), 0)

    def test_a_stop_request_ends_it_even_in_the_middle_of_a_long_pause(self):
        sweet, clock = self.device()

        def on_check(n):
            self.checked.append(clock.now)
            if n == 3:
                ms.request_cancel("sweettv")
        sweet.helper.on_check = on_check
        sweet.helper.checks = [None, None, None, None, None]
        sweet.login(ms_mode="partner")
        self.assertEqual(self.states(), ["waiting", "cancelled"])
        self.assertEqual(len(self.checked), 3)
        self.assertLess(clock.now - self.checked[-1], 3.5)                   # seen within a slice, not after the 20 s pause


if __name__ == "__main__":
    unittest.main(verbosity=1)
