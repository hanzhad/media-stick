#!/usr/bin/env python3
"""Offline test of mediastick_ytchannel (no network: Google is a fake urlopen):
python3 tools/test-ytchannel.py"""
import io
import json
import os
import sys
import tempfile
import time
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_YTCHANNEL_CACHE"] = os.path.join(TMP, "run", "ytchannel.json")
os.environ.pop("MEDIASTICK_YTCHANNEL_OFF", None)
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

import mediastick_ytchannel as yc  # noqa: E402

TOKENS = "ya29.SECRET-TV|ya29.SECRET-USER||"


def users(u, current=0):
    path = os.path.join(yc.USERDATA, "plugin.video.youtube", "access_manager.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"access_manager": {"current_user": current, "users": u}}, f)


def signed(refresh="1//SECRET-R1|1//SECRET-R2||", access=TOKENS):
    return {"name": "Default", "refresh_token": refresh, "access_token": access}


class Google:
    """A fake urlopen: `answers` maps a token to a JSON body or an HTTP status; records what it saw."""
    def __init__(self, answers):
        self.answers, self.seen = answers, []

    def __call__(self, req, timeout=None):
        token = req.get_header("Authorization").split(" ", 1)[1]
        self.seen.append((req.full_url, token))
        a = self.answers.get(token, 401)
        if isinstance(a, int):
            raise urllib.error.HTTPError(req.full_url, a, "no", {}, io.BytesIO(b"{}"))
        if isinstance(a, Exception):
            raise a
        return io.BytesIO(json.dumps(a).encode())


CHANNEL = {"items": [{"id": "UC1", "snippet": {"title": "  Мой\n канал\x07 "}}]}
NONE = {"kind": "youtube#channelListResponse", "pageInfo": {"totalResults": 0}}


class Check(unittest.TestCase):
    def setUp(self):
        try:
            os.unlink(yc.CACHE)
        except OSError:
            pass
        users({"0": signed()})

    def run_with(self, answers, fn=yc.check, pid="0"):
        g = Google(answers)
        with mock.patch("urllib.request.urlopen", g):
            return fn(pid), g

    def test_a_channel_is_yes_with_its_title_cleaned(self):
        got, g = self.run_with({"ya29.SECRET-TV": CHANNEL})
        self.assertEqual(got, {"state": "yes", "title": "Мой канал"})
        self.assertTrue(g.seen[0][0].startswith("https://www.googleapis.com/youtube/v3/channels?"))
        self.assertIn("mine=true", g.seen[0][0])

    def test_no_items_is_no(self):
        got, _ = self.run_with({"ya29.SECRET-TV": NONE})
        self.assertEqual(got, {"state": "no", "title": ""})

    def test_a_refused_token_tries_the_next_one(self):
        got, g = self.run_with({"ya29.SECRET-TV": 401, "ya29.SECRET-USER": NONE})
        self.assertEqual(got["state"], "no")
        self.assertEqual([t for _, t in g.seen], ["ya29.SECRET-TV", "ya29.SECRET-USER"])

    def test_every_token_refused_or_no_network_is_unknown(self):
        self.assertEqual(self.run_with({})[0]["state"], "unknown")
        self.assertEqual(self.run_with({"ya29.SECRET-TV": OSError("down")})[0]["state"], "unknown")

    def test_not_signed_in_or_no_file_is_unknown_and_google_is_not_asked(self):
        users({"0": {"name": "Default", "refresh_token": "|||", "access_token": ""}})
        got, g = self.run_with({"ya29.SECRET-TV": CHANNEL})
        self.assertEqual((got["state"], g.seen), ("unknown", []))
        os.unlink(os.path.join(yc.USERDATA, "plugin.video.youtube", "access_manager.json"))
        self.assertEqual(self.run_with({}, pid="0")[0]["state"], "unknown")
        users({"0": signed()})
        self.assertEqual(self.run_with({}, pid="7")[0]["state"], "unknown")

    def test_no_token_in_the_cache(self):
        self.run_with({"ya29.SECRET-TV": CHANNEL})
        with open(yc.CACHE, encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("SECRET", text)
        self.assertIn("yes", text)

    def test_the_off_switch_never_asks(self):
        with mock.patch.dict(os.environ, {"MEDIASTICK_YTCHANNEL_OFF": "1"}):
            got, g = self.run_with({"ya29.SECRET-TV": CHANNEL})
            got2, g2 = self.run_with({"ya29.SECRET-TV": CHANNEL}, fn=yc.peek)
        self.assertEqual((got["state"], g.seen, got2["state"], g2.seen), ("unknown", [], "unknown", []))


class Peek(unittest.TestCase):
    def setUp(self):
        try:
            os.unlink(yc.CACHE)
        except OSError:
            pass
        users({"0": signed()})

    def tearDown(self):
        self.wait_idle()

    def wait_idle(self):
        for _ in range(100):
            with yc._lock:
                if not yc._busy:
                    return
            time.sleep(0.02)

    def wait_cache(self):
        for _ in range(100):
            if os.path.exists(yc.CACHE):
                return
            time.sleep(0.02)

    def test_peek_never_waits_and_answers_from_the_background_check(self):
        g = Google({"ya29.SECRET-TV": NONE})
        with mock.patch("urllib.request.urlopen", g):
            first = yc.peek("0")
            self.wait_cache()
            self.wait_idle()
            second = yc.peek("0")
        self.assertEqual(first["state"], "unknown")
        self.assertEqual(second, {"state": "no", "title": ""})

    def test_a_fresh_answer_is_not_asked_again_and_an_old_one_is(self):
        g = Google({"ya29.SECRET-TV": CHANNEL})
        with mock.patch("urllib.request.urlopen", g):
            yc.check("0")
            n = len(g.seen)
            self.assertEqual(yc.peek("0")["state"], "yes")
            time.sleep(0.05)
            self.assertEqual(len(g.seen), n)
            with open(yc.CACHE, encoding="utf-8") as f:
                data = json.load(f)
            for v in data.values():
                v["t"] -= yc.TTL["yes"] + 1
            with open(yc.CACHE, "w", encoding="utf-8") as f:
                json.dump(data, f)
            self.assertEqual(yc.peek("0")["state"], "yes")   # the old answer still shows meanwhile
            for _ in range(100):
                if len(g.seen) > n:
                    break
                time.sleep(0.02)
            self.wait_idle()
        self.assertGreater(len(g.seen), n)

    def test_signing_in_again_is_a_new_question(self):
        g = Google({"ya29.SECRET-TV": NONE, "ya29.OTHER": CHANNEL})
        with mock.patch("urllib.request.urlopen", g):
            yc.check("0")
            users({"0": signed(refresh="1//OTHER-R|||", access="ya29.OTHER|||")})
            self.assertEqual(yc.peek("0")["state"], "unknown")   # not the old account's "no"
            self.assertEqual(yc.check("0")["state"], "yes")

    def test_a_broken_cache_is_not_an_error(self):
        os.makedirs(os.path.dirname(yc.CACHE), exist_ok=True)
        with open(yc.CACHE, "w") as f:
            f.write("{not json")
        with mock.patch("urllib.request.urlopen", Google({"ya29.SECRET-TV": NONE})):
            self.assertEqual(yc.peek("0")["state"], "unknown")
            self.assertEqual(yc.check("0")["state"], "no")


if __name__ == "__main__":
    unittest.main(verbosity=1)
