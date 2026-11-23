#!/usr/bin/env python3
"""Offline test of "this Google account has no YouTube channel" on the TV side (no Kodi, no device, no network):
python3 tools/test-no-channel-tv.py

The card of the YouTube screen has its own tests in tools/test-youtube-app.py (NoChannel); here the Kodi-free text and
rule, the library shim, the Accounts screen's line and the hint of the finished sign-in. The stubbed Kodi and the temp
directories are those of tools/test-accounts-tv.py. mediastick_ytchannel is never the real one: it asks Google."""
import importlib.util
import os
import sys
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("accounts_tv", os.path.join(HERE, "test-accounts-tv.py"))
tv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tv)

from resources.lib import accounts_screen, store, youtube_data as D, youtube_files  # noqa: E402

ms, ob, guide = tv.lib, store.onboarding, tv.lib.guide
tv.Control.getSelectedPosition = lambda self: max(self.selected, 0)      # the stubbed list the Accounts window moves in
NOW = 1_700_000_000
TEXT = ("This Google account has no YouTube channel, so this is empty. Create one in the YouTube app on your phone "
        "(avatar → Create channel), or add another Google account on the phone remote.")


class Fake:
    """mediastick_ytchannel as a test double: what peek and check answer, and what was asked."""

    def __init__(self, peek="unknown", check="unknown", fail=False):
        self.answers, self.fail, self.calls = {"peek": peek, "check": check}, fail, []

    def peek(self, profile_id):
        self.calls.append(("peek", profile_id))
        if self.fail:
            raise RuntimeError("boom")
        return {"state": self.answers["peek"], "title": ""}

    def check(self, profile_id):
        self.calls.append(("check", profile_id))
        return {"state": self.answers["check"], "title": ""}


class Card(unittest.TestCase):
    def view(self, key):
        return D.section_view(key)

    def test_only_a_known_no_in_the_sections_of_the_account_and_only_for_an_empty_or_failed_card(self):
        for key in D.NEEDS_CHANNEL:
            for mode in (D.EMPTY, D.ERROR, D.UNAVAILABLE):
                self.assertTrue(D.no_channel(self.view(key), mode, "no"), (key, mode))
                for state in ("yes", "unknown", ""):
                    self.assertFalse(D.no_channel(self.view(key), mode, state), (key, mode, state))
            for mode in (D.SIGNIN, D.NEEDKEY, D.PROMPT, D.LOADING, D.DATA):
                self.assertFalse(D.no_channel(self.view(key), mode, "no"), (key, mode))
        for key in ("rec", "history", "trend", D.SEARCH):
            self.assertFalse(D.no_channel(self.view(key), D.EMPTY, "no"), key)
        self.assertFalse(D.no_channel(None, D.EMPTY, "no"))
        self.assertEqual(D.NEEDS_CHANNEL, ("subs", "later", "lists"))

    def test_the_card_says_it_in_english_and_short(self):
        message = D.message(D.EMPTY, self.view("subs"), True, "", "no")
        self.assertEqual((message.title, message.text, message.action), ("No YouTube channel", TEXT, "Try again"))
        self.assertLess(len(message.text), 200)
        self.assertEqual(D.message(D.ERROR, self.view("lists"), True, "Network", "no"), message)

    def test_every_other_card_is_as_it_was(self):
        for key in D.SECTION_KEYS:
            for mode in (D.EMPTY, D.ERROR, D.UNAVAILABLE, D.SIGNIN, D.NEEDKEY, D.PROMPT):
                plain = D.message(mode, self.view(key), True, "x")
                for state in ("yes", "unknown", ""):
                    self.assertEqual(D.message(mode, self.view(key), True, "x", state), plain, (key, mode, state))
                if not D.no_channel(self.view(key), mode, "no"):
                    self.assertEqual(D.message(mode, self.view(key), True, "x", "no"), plain, (key, mode))
        self.assertEqual(D.message(D.EMPTY, self.view("subs"), True).text, D.EMPTY_TEXT["subs"])


class Shim(unittest.TestCase):
    def test_peek_answers_pass_through_and_anything_else_claims_nothing(self):
        for answer, want in (("yes", "yes"), ("no", "no"), ("unknown", "unknown"), ("weird", "unknown")):
            with mock.patch.object(store, "ytchannel", Fake(peek=answer)) as fake:
                self.assertEqual(store.channel_state("0"), want)
                self.assertEqual(fake.calls, [("peek", "0")])           # never check(): that waits for Google
        with mock.patch.object(store, "ytchannel", Fake(fail=True)):
            self.assertEqual(store.channel_state("0"), "unknown")

    def test_a_device_without_the_library_claims_nothing(self):
        with mock.patch.object(store, "ytchannel", None):
            self.assertEqual(store.channel_state("0"), "unknown")
            with mock.patch.object(youtube_files, "_current_profile", return_value={"id": "0", "signed_in": True}):
                self.assertEqual(youtube_files.channel_state(), "unknown")
            self.assertEqual(accounts_screen._channel_of([self.entry(True)]), "unknown")

    @staticmethod
    def entry(signed_in, current=True):
        return {"service": "youtube", "name": "YouTube", "signed_in": signed_in, "signin": None,
                "profiles": [{"id": "3", "name": "Anna", "current": current, "tokens": 4 if signed_in else 0,
                              "signed_in": signed_in}]}

    def test_the_files_ask_for_the_current_signed_in_profile_only(self):
        for state in ("yes", "no", "unknown"):
            with mock.patch.object(store, "ytchannel", Fake(peek=state)) as fake, \
                    mock.patch.object(youtube_files, "_current_profile", return_value={"id": "3", "signed_in": True}):
                self.assertEqual(youtube_files.channel_state(), state)
                self.assertEqual(fake.calls, [("peek", "3")])
        with mock.patch.object(store, "ytchannel", Fake(peek="no")) as fake:
            with mock.patch.object(youtube_files, "_current_profile", return_value={"id": "3", "signed_in": False}):
                self.assertEqual(youtube_files.channel_state(), "unknown")
            with mock.patch.object(youtube_files, "_current_profile", return_value=None):
                self.assertEqual(youtube_files.channel_state(), "unknown")
            with mock.patch.object(youtube_files, "_current_profile", side_effect=RuntimeError("no library")):
                self.assertEqual(youtube_files.channel_state(), "unknown")
            self.assertEqual(fake.calls, [])


class AccountsLine(unittest.TestCase):
    entry = staticmethod(Shim.entry)

    def rows(self, state, signed_in=True, tokens=4):
        entry = self.entry(signed_in)
        entry["profiles"][0]["tokens"] = tokens
        return accounts_screen.rows([entry], None, state)

    def details(self, rows):
        return [r.detail for r in rows]

    def test_a_signed_in_profile_without_a_channel_has_the_dim_line(self):
        rows = self.rows("no")
        signout = next(r for r in rows if r.action == "signout")
        self.assertEqual(signout.detail, "Anna: signed in · No YouTube channel on this account")
        self.assertEqual(sum("No YouTube channel" in d for d in self.details(rows)), 1)
        partial = next(r for r in self.rows("no", tokens=2) if r.action == "signout")
        self.assertEqual(partial.detail, "Anna: 2 of 4 codes entered · No YouTube channel on this account")

    def test_a_channel_an_unknown_answer_and_a_signed_out_profile_add_nothing(self):
        plain = self.details(self.rows("unknown"))
        self.assertEqual(plain, self.details(self.rows("yes")))
        self.assertEqual(plain, self.details(accounts_screen.rows([self.entry(True)], None)))
        self.assertFalse(any("channel" in d.lower() for d in plain))
        out = self.rows("no", signed_in=False, tokens=0)
        self.assertFalse(any("channel" in d.lower() for d in self.details(out)))

    def test_the_state_is_asked_for_the_current_signed_in_profile(self):
        with mock.patch.object(store, "ytchannel", Fake(peek="no")) as fake:
            self.assertEqual(accounts_screen._channel_of([self.entry(True)]), "no")
            self.assertEqual(fake.calls, [("peek", "3")])
            fake.calls.clear()
            self.assertEqual(accounts_screen._channel_of([self.entry(False)]), "unknown")
            self.assertEqual(accounts_screen._channel_of([self.entry(True, current=False)]), "unknown")
            self.assertEqual(accounts_screen._channel_of([{"service": "sweettv", "profiles": []}]), "unknown")
            self.assertEqual(fake.calls, [])

    def test_the_window_shows_the_line_and_survives_a_failing_library(self):
        accts = [self.entry(True)]
        window = accounts_screen.AccountsDialog()
        window.setup()
        with mock.patch.object(ms, "accounts", return_value=accts), mock.patch.object(store, "ytchannel", Fake(peek="no")):
            window._refresh()
        labels = [i.label for i in window.getControl(accounts_screen.LIST).items]
        self.assertIn("Sign out of YouTube", labels)
        self.assertIn("No YouTube channel on this account", window.rows[labels.index("Sign out of YouTube")].detail)
        window = accounts_screen.AccountsDialog()
        window.setup()
        with mock.patch.object(ms, "accounts", return_value=accts), mock.patch.object(store, "ytchannel", Fake(fail=True)):
            window._refresh()
        self.assertEqual([r.action for r in window.rows], ["signout", "switch"])
        self.assertFalse(any("channel" in r.detail.lower() for r in window.rows))


class DoneHint(unittest.TestCase):
    """After a successful YouTube sign-in whose account has no channel the finished document says what will be empty."""

    def setUp(self):
        ms.begin("youtube")
        self.profile = mock.patch.object(ms, "youtube_accounts", return_value=[
            {"id": "0", "name": "Default", "current": False, "tokens": 0, "signed_in": False},
            {"id": "2", "name": "Anna", "current": True, "tokens": 4, "signed_in": True}])
        self.profile.start()
        self.addCleanup(self.profile.stop)

    def finish(self, fake):
        with mock.patch.object(ms, "ytchannel", fake):
            ms.publish("youtube", "waiting", code="ABCD-EFGH", url="https://www.google.com/device")
            ms.publish("youtube", "done")
        return ob.read("youtube")

    def test_a_known_no_adds_the_hint_in_both_languages(self):
        fake = Fake(peek="no")
        d = self.finish(fake)
        self.assertEqual(d["state"], "done")
        self.assertEqual(d["hint"]["tv"], "This Google account has no YouTube channel, so Subscriptions, Watch later and "
                                          "Playlists will be empty.")
        self.assertIn("нет канала YouTube", d["hint"]["phone"])
        self.assertLessEqual(max(len(d["hint"]["tv"]), len(d["hint"]["phone"])), 160)
        self.assertEqual(fake.calls, [("peek", "2")])                  # the current profile; the answer was already there

    def test_an_unknown_answer_is_asked_for_once_right_now(self):
        fake = Fake(peek="unknown", check="no")
        self.assertIn("hint", self.finish(fake))
        self.assertEqual(fake.calls, [("peek", "2"), ("check", "2")])
        ms.begin("youtube")
        self.assertNotIn("hint", self.finish(Fake(peek="unknown", check="unknown")))

    def test_a_channel_or_anything_else_leaves_the_document_as_it_was(self):
        for fake in (Fake(peek="yes"), Fake(peek="unknown", check="yes"), Fake(fail=True)):
            ms.begin("youtube")
            d = self.finish(fake)
            self.assertEqual(d["state"], "done")
            self.assertNotIn("hint", d)

    def test_a_device_without_the_library_signs_in_as_always(self):
        d = self.finish(None)
        self.assertEqual((d["state"], d.get("hint")), ("done", None))
        self.assertEqual(ms.read("youtube")["state"], "done")

    def test_only_a_youtube_sign_in_that_succeeded_asks(self):
        fake = Fake(peek="no")
        with mock.patch.object(ms, "ytchannel", fake):
            ms.publish("youtube", "waiting", code="A-B", url="https://www.google.com/device")
            ms.publish("youtube", "failed")
            ms.publish("youtube", "cancelled")
            ms.publish("sweettv", "done")
        self.assertEqual(fake.calls, [])
        self.assertNotIn("hint", ob.read("sweettv") or {})

    def test_a_newer_sign_in_is_not_given_the_old_hint(self):
        class Late(Fake):
            def check(self, profile_id):
                ms.begin("youtube")                     # the person starts again while Google is being asked
                ms.publish("youtube", "waiting", code="NEW-CODE", url="https://www.google.com/device")
                return {"state": "no", "title": ""}
        d = self.finish(Late(peek="unknown"))
        self.assertEqual((d["state"], d["hint"]["tv"]), ("active", guide.HINT_TYPED))

    def test_the_end_does_not_wait_longer_than_the_limit_for_a_slow_answer(self):
        import threading
        import time
        release = threading.Event()

        class Slow(Fake):
            def check(self, profile_id):
                release.wait(5)
                return {"state": "no", "title": ""}
        started = time.monotonic()
        with mock.patch.object(ms, "CHANNEL_WAIT", 0.1):
            d = self.finish(Slow(peek="unknown"))
        release.set()
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(d["state"], "done")

    def test_the_guide_hint_is_only_for_a_finished_youtube_sign_in_with_no_channel(self):
        self.assertIn("hint", guide.document("youtube", "done", channel="no"))
        for doc in (guide.document("youtube", "done", channel="yes"), guide.document("youtube", "done"),
                    guide.document("youtube", "failed", channel="no"), guide.document("sweettv", "done", channel="no"),
                    guide.document("youtube", "active", "A-B", "https://www.google.com/device", channel="no")):
            self.assertNotEqual(doc.get("hint", {}).get("tv"), guide.NO_CHANNEL_HINT["tv"])
        self.assertTrue(ob.write("youtube", guide.document("youtube", "done", channel="no"), now=NOW))


if __name__ == "__main__":
    unittest.main()
