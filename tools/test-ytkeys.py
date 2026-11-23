#!/usr/bin/env python3
"""Offline test of the "Google key for YouTube" wizard (no Kodi, no network, no device): python3 tools/test-ytkeys.py

The values (validation, what a pasted text is), the hand-over files (mode 0600, deleted after reading), Google's verdict
on a key and on a client ID (the network call is replaced), the actions of the panel with the add-on's own script run
for real against a stub of Kodi's settings, the step file and the onboarding document the TV reads (no value in them),
the links that open in the phone's browser (Android intent, Safari form), the page, and the real `panel` served on a
local port. Every value used here carries the word MARKER (the client ID, which must be lower case, the tag CIDTAG):
none of them may appear in any log, reply, result file, step file, onboarding document or page."""
import contextlib
import http.client
import importlib.machinery
import importlib.util
import io
import json
import os
import socket
import stat
import sys
import tempfile
import threading
import types
import unittest
import urllib.error
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_YTKEYS_DIR"] = os.path.join(TMP, "run")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
sys.dont_write_bytecode = True

CIDTAG = "abcdef0123456789cid"                  # a client ID is lower case, so its marker is this
KEY = "AIzaMARKER-0123456789abcdefghijklmnWXYZ"                    # AIza + 35
CID = "123456789012-%s.apps.googleusercontent.com" % CIDTAG
SECRET = "GOCSPX-MARKER-SECRET-0123456789"
GOOD = {"api_key": KEY, "client_id": CID, "client_secret": SECRET}
LEAKS = ("MARKER", CIDTAG)
YT = "plugin.video.youtube"


def no_leak(test, text, where=""):
    for word in LEAKS + (KEY, CID, SECRET):
        test.assertNotIn(word, text, where)


class Fake:
    """What the stubbed Kodi shows and does, one place for every test to look at and set."""
    logs = []                     # every line xbmc.log was given
    settings = {}                 # the YouTube add-on's settings, as Kodi holds them
    missing = False               # no such add-on
    refuse = False                # setSettingString says False
    explode = False               # setSettingString raises an exception that holds a value


xbmc = types.ModuleType("xbmc")
xbmc.LOGINFO, xbmc.LOGWARNING, xbmc.LOGERROR = 1, 2, 3
xbmc.log = lambda msg, level=2: Fake.logs.append(str(msg))
xbmc.executebuiltin = lambda cmd: None
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda p: TMP + "/"
xbmcgui = types.ModuleType("xbmcgui")
xbmcgui.Dialog = lambda: types.SimpleNamespace(notification=lambda *a, **k: None)
xbmcgui.NOTIFICATION_INFO = "info"
xbmcaddon = types.ModuleType("xbmcaddon")


def settings_path():
    return os.path.join(os.environ["MEDIASTICK_ADDON_DATA"], YT, "settings.xml")


def write_settings(values):
    """settings.xml the way Kodi leaves it after a save: the three of ours among others."""
    os.makedirs(os.path.dirname(settings_path()), exist_ok=True)
    root = ET.Element("settings", version="2")
    ET.SubElement(root, "setting", id="youtube.language").text = "ru"
    for sid, value in values.items():
        ET.SubElement(root, "setting", id=sid).text = value
    ET.ElementTree(root).write(settings_path(), encoding="utf-8")


class StubYoutube:
    def setSettingString(self, sid, value):
        if Fake.explode:
            raise ValueError("cannot store %s" % value)
        if Fake.refuse:
            return False
        Fake.settings[sid] = value
        write_settings(Fake.settings)
        return True


def addon_factory(addon_id=None):
    if addon_id is None:
        return types.SimpleNamespace(getAddonInfo=lambda key: ADDON)
    if addon_id != YT or Fake.missing:
        raise RuntimeError("unknown add-on")
    return StubYoutube()


xbmcaddon.Addon = addon_factory
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcgui=xbmcgui, xbmcaddon=xbmcaddon)
sys.path.insert(0, ADDON)
sys.path.insert(0, LIB)

import mediastick_ytkeys as ky  # noqa: E402
import panel_accounts as pa  # noqa: E402
import panel_accounts_ui  # noqa: E402,F401
import panel_ytkeys as pk  # noqa: E402
import panel_ytkeys_steps as steps  # noqa: E402
from resources.lib import apps, ytkeys  # noqa: E402


def request_path():
    return os.path.join(ky.DIR, ky.REQUEST)


def result_path():
    return os.path.join(ky.DIR, ky.RESULT)


def run_default(argv):
    """What Kodi does for RunScript(script.media-stick.home,<argv>): default.py, run for real."""
    with mock.patch.object(sys, "argv", ["default.py"] + argv):
        with open(os.path.join(ADDON, "default.py"), encoding="utf-8") as f:
            exec(compile(f.read(), "default.py", "exec"), {"__name__": "__main__"})


def reset():
    Fake.logs.clear()
    Fake.settings = {}
    Fake.missing = Fake.refuse = Fake.explode = False
    pk.PROGRESS.reset()
    for path in (request_path(), result_path(), settings_path()):
        try:
            os.unlink(path)
        except OSError:
            pass
    os.makedirs(ky.DIR, exist_ok=True)
    for name in os.listdir(ky.DIR):
        os.unlink(os.path.join(ky.DIR, name))


def preset(**values):
    """The add-on already holds keys (an earlier save)."""
    Fake.settings = {ky.SETTINGS[name]: v for name, v in values.items()}
    write_settings(Fake.settings)


class FakeKodi:
    """The panel's kodi(): runs the add-on's script when asked, like Kodi would, and notes what it saw."""
    def __init__(self):
        self.calls, self.modes, self.down, self.script = [], [], False, True

    def __call__(self, method, params=None, timeout=3):
        if self.down:
            raise ConnectionRefusedError("kodi is off")
        if method.startswith("Player."):
            return []
        if method in ("GUI.GetProperties", "XBMC.GetInfoLabels"):
            return {}
        self.calls.append((method, params))
        if method == "Addons.ExecuteAddon" and self.script and params["params"] == ["ytkeys"]:
            self.modes.append(stat.S_IMODE(os.stat(request_path()).st_mode))
            run_default(["ytkeys"])
        return "OK"


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status = body, status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self, n=-1):
        return self.body


def google_error(code, reason, where="errors", message="GOOGLE-MESSAGE-TEXT"):
    """Google's error body: the reason sits under error.errors[] (old style) or error.details[] (new style)."""
    item = {"reason": reason}
    err = {"code": code, "message": message, where: [item]}
    return code, json.dumps({"error": err}).encode()


def oauth_error(code, error, description="x"):
    """The device-code endpoint's error body."""
    return code, json.dumps({"error": error, "error_description": description}).encode()


DEVICE_OK = (200, json.dumps({"device_code": "DEVICE-CODE-TO-DROP", "user_code": "ABCD-EFGH",
                              "verification_url": "https://www.google.com/device", "expires_in": 1800,
                              "interval": 5}).encode())


class Net:
    """urlopen in place: answers with (code, body) or raises what it is given; remembers what was asked."""
    def __init__(self):
        self.urls, self.timeouts, self.answer, self.posts = [], [], (200, b"{}"), []

    def urlopen(self, url, timeout=None):
        if hasattr(url, "full_url"):                       # a Request: the POST to the device-code endpoint
            self.posts.append((url.full_url, url.data, url.get_method(), dict(url.header_items())))
            url = url.full_url
        self.urls.append(url)
        self.timeouts.append(timeout)
        if isinstance(self.answer, BaseException):
            raise self.answer
        code, body = self.answer
        if code == 200:
            return Resp(body)
        raise urllib.error.HTTPError(url, code, "denied", {}, io.BytesIO(body))

    def io(self, clock=None):
        return pk.Io(self.urlopen, lambda s: None, clock or (lambda: 0.0))


class FakeOnboarding:
    """The TV side's library, in place: keeps what it was given."""
    def __init__(self):
        self.written, self.cleared = [], []

    def write(self, service, doc):
        self.written.append((service, json.loads(json.dumps(doc))))

    def clear(self, service):
        self.cleared.append(service)

    @property
    def last(self):
        return self.written[-1][1] if self.written else None


def check_doc(test, doc):
    """The shape of onboarding schema v1, and no value in it."""
    test.assertEqual((doc["v"], doc["service"], doc["flow"], doc["state"]), (1, "youtube", "keys", "active"))
    test.assertEqual(set(doc["title"]), {"tv", "phone"})
    test.assertTrue(all(isinstance(t, str) and 0 < len(t) <= 80 for t in doc["title"].values()))
    test.assertIn(doc["step"], range(1, 5))
    test.assertEqual(len(doc["steps"]), 4)
    test.assertLessEqual(len(doc["steps"]), 8)
    for s in doc["steps"]:
        test.assertEqual(set(s), {"id", "tv", "phone"})
        test.assertTrue(0 < len(s["tv"]) <= 120 and 0 < len(s["phone"]) <= 120)
    test.assertEqual(set(doc["hint"]), {"tv", "phone"})
    test.assertTrue(all(0 < len(t) <= 160 for t in doc["hint"].values()))
    test.assertLessEqual(len(doc["items"]), 6)
    test.assertEqual([i["id"] for i in doc["items"]], ["api_key", "client_id", "secret"])
    test.assertEqual([i["label"] for i in doc["items"]], ["API key", "Client ID", "Secret"])
    test.assertTrue(all(i["s"] in ("ok", "wait") for i in doc["items"]))
    test.assertEqual(doc["expires"] - doc["updated"], 1800)
    if doc["step"] == 2:
        test.assertEqual(doc["warn"], {"tv": "Publish it, or the TV gets signed out after 7 days.",
                                       "phone": "Без публикации вход на ТВ слетает через 7 дней."})
        test.assertEqual(len(doc["chips"]), 2)
        for row in doc["chips"]:
            test.assertLessEqual(len(row), 12)
            test.assertTrue(all(set(c) == {"t", "s"} and c["s"] in ("done", "now", "todo") for c in row))
    else:
        test.assertNotIn("warn", doc)
        test.assertNotIn("chips", doc)
    no_leak(test, json.dumps(doc), "onboarding document")


class Base(unittest.TestCase):
    """Fresh state for each test, and every byte printed during it kept to see that no value was."""
    def setUp(self):
        reset()
        self.ob = FakeOnboarding()
        for name, fn in (("ob_write", self.ob.write), ("ob_clear", self.ob.clear)):
            patch = mock.patch.object(pk, name, fn)
            patch.start()
            self.addCleanup(patch.stop)
        self.out = io.StringIO()
        for ctx in (contextlib.redirect_stdout(self.out), contextlib.redirect_stderr(self.out)):
            ctx.__enter__()
            self.addCleanup(ctx.__exit__, None, None, None)
        self.addCleanup(self.no_marker_anywhere)

    def no_marker_anywhere(self):
        no_leak(self, self.out.getvalue(), "output")
        no_leak(self, "\n".join(Fake.logs), "log")
        no_leak(self, json.dumps(self.ob.written), "onboarding")
        for name in os.listdir(ky.DIR):      # nothing left behind by a finished test but an answer
            with open(os.path.join(ky.DIR, name), encoding="utf-8") as f:
                no_leak(self, f.read(), name)


# ---- the values -------------------------------------------------------------------------------

class Values(unittest.TestCase):
    def test_good_values_pass_trimmed(self):
        padded = {k: "  " + v + "\n" for k, v in GOOD.items()}
        self.assertEqual(ky.clean_values(padded), GOOD)

    def refused(self, **change):
        body = dict(GOOD, **change)
        with self.assertRaises(ky.Invalid) as c:
            ky.clean_values(body)
        no_leak(self, str(c.exception))        # a message never repeats a value
        return str(c.exception)

    def test_each_value_is_needed(self):
        for name in GOOD:
            for bad in ("", "   ", None, 5, ["x"]):
                self.assertIn("Заполните", self.refused(**{name: bad}))
        with self.assertRaises(ky.Invalid):
            ky.clean_values({})

    def test_lengths_are_limited_per_value(self):
        self.assertEqual(ky.clean_values(dict(GOOD, api_key="k" * 128))["api_key"], "k" * 128)
        self.assertIn("длинное", self.refused(api_key="k" * 129))
        sid = "i" * (256 - len(ky.ID_SUFFIX)) + ky.ID_SUFFIX
        self.assertEqual(ky.clean_values(dict(GOOD, client_id=sid))["client_id"], sid)
        self.assertIn("длинное", self.refused(client_id="i" + sid))
        self.assertEqual(ky.clean_values(dict(GOOD, client_secret="s" * 128))["client_secret"], "s" * 128)
        self.assertIn("длинное", self.refused(client_secret="s" * 129))

    def test_no_spaces_line_breaks_or_non_ascii_inside(self):
        for name in GOOD:
            for bad in ("ab cd", "ab\ncd", "ab\r\ncd", "ab\tcd", "ab\x00cd", "abв" + "x" * 30, "ab cd"):
                value = GOOD[name][:12] + bad + GOOD[name][12:]
                self.assertIn("не должно быть", self.refused(**{name: value}), repr(bad))

    def test_the_key_is_not_a_stub_and_the_id_ends_as_google_ids_do(self):
        self.assertIn("короткий", self.refused(api_key="AIzaMARKER"))
        self.assertIn(ky.ID_SUFFIX, self.refused(client_id="123-MARKER.example.com"))
        self.assertIn(ky.ID_SUFFIX, self.refused(client_id=ky.ID_SUFFIX))
        self.assertEqual(ky.clean_values(dict(GOOD, client_secret="x"))["client_secret"], "x")   # any secret that is not empty

    def test_what_may_be_shown(self):
        self.assertEqual(ky.tail4(KEY), "WXYZ")
        self.assertEqual(ky.tail4(None), "")
        self.assertEqual(ky.describe(None), {"set": False, "partial": False, "last4": ""})
        self.assertEqual(ky.describe({"api_key": KEY, "client_id": CID, "client_secret": SECRET}),
                         {"set": True, "partial": False, "last4": "WXYZ"})
        self.assertEqual(ky.describe({"api_key": KEY, "client_id": "", "client_secret": ""}),
                         {"set": False, "partial": True, "last4": ""})
        self.assertEqual(ky.describe({"api_key": "", "client_id": "", "client_secret": ""})["partial"], False)


class Detect(unittest.TestCase):
    """What a pasted text is: strict, whole, trimmed, capped."""
    def test_the_three_kinds(self):
        self.assertEqual(steps.detect(KEY), ("api_key", KEY))
        self.assertEqual(steps.detect(CID), ("client_id", CID))
        self.assertEqual(steps.detect(SECRET), ("client_secret", SECRET))
        self.assertEqual(steps.detect("  \n" + KEY + "\t\n"), ("api_key", KEY))             # trimmed

    def test_the_patterns_are_the_ones_agreed(self):
        self.assertEqual(dict(steps.PATTERNS), {
            "api_key": r"^AIza[0-9A-Za-z_-]{35}$",
            "client_id": r"^[0-9]+-[0-9a-z]+\.apps\.googleusercontent\.com$",
            "client_secret": r"^GOCSPX-[0-9A-Za-z_-]{20,40}$"})
        self.assertEqual(pk.WIZARD["patterns"], dict(steps.PATTERNS))     # the page gets the same sources

    def test_lengths_at_the_edges(self):
        self.assertIsNotNone(steps.detect("AIza" + "a" * 35))
        for n in (34, 36):
            self.assertIsNone(steps.detect("AIza" + "a" * n), n)
        self.assertIsNotNone(steps.detect("GOCSPX-" + "a" * 20))
        self.assertIsNotNone(steps.detect("GOCSPX-" + "a" * 40))
        for n in (19, 41):
            self.assertIsNone(steps.detect("GOCSPX-" + "a" * n), n)

    def test_unknown_or_sloppy_text_is_nothing(self):
        for text in ("", "   ", "hello", "AIza", KEY + KEY, KEY + " x", KEY[:10] + " " + KEY[10:], KEY + "\n" + KEY,
                     CID.upper(), "x" + CID, CID + "x", "123456789012-abc.apps.googleusercontent.com.evil.com",
                     "-abc.apps.googleusercontent.com", SECRET + "!", "gocspx-" + "a" * 25, "AIza" + "é" * 35,
                     "AIza" + "a" * 34 + "\n", None, 5, ["x"], {"a": 1}, True):
            self.assertIsNone(steps.detect(text), repr(text)[:40])

    def test_the_length_is_capped_before_matching(self):
        self.assertIsNone(steps.detect("a" * 100000))
        self.assertIsNone(steps.detect(" " * 100000 + KEY))
        self.assertIsNone(steps.detect("1" * steps.PASTE_MAX + "-a.apps.googleusercontent.com"))
        self.assertEqual(steps.detect(" " * 100 + KEY + " " * 100)[0], "api_key")

    def test_matches_wants_the_right_kind_and_the_whole_value(self):
        self.assertTrue(steps.matches("api_key", KEY))
        self.assertFalse(steps.matches("client_id", KEY))
        self.assertFalse(steps.matches("api_key", " " + KEY))


# ---- the hand-over files ------------------------------------------------------------------------

class HandOver(Base):
    def test_the_request_is_private_whole_and_alone(self):
        rid = ky.send_request("save", GOOD)
        self.assertEqual(stat.S_IMODE(os.stat(request_path()).st_mode), 0o600)
        self.assertEqual(os.listdir(ky.DIR), [ky.REQUEST])            # no half-written file next to it
        with open(request_path(), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual((data["id"], data["op"], data["values"]), (rid, "save", GOOD))
        os.unlink(request_path())

    def test_taking_the_request_deletes_it(self):
        rid = ky.send_request("save", GOOD)
        self.assertEqual(ky.take_request(), {"id": rid, "op": "save", "values": GOOD})
        self.assertFalse(os.path.exists(request_path()))
        with self.assertRaises(ky.BadRequest) as c:
            ky.take_request()
        self.assertEqual(c.exception.code, "no_request")

    def test_the_file_is_deleted_even_when_it_is_refused(self):
        rid = ky.send_request("save", GOOD)
        os.chmod(request_path(), 0o644)                              # somebody else could have read it
        with self.assertRaises(ky.BadRequest) as c:
            ky.take_request()
        self.assertEqual((c.exception.code, c.exception.id), ("insecure", rid))
        self.assertFalse(os.path.exists(request_path()))

    def test_a_stale_request_is_not_acted_on(self):
        rid = ky.send_request("clear")
        with self.assertRaises(ky.BadRequest) as c:
            ky.take_request(now=os.stat(request_path()).st_mtime + ky.MAX_AGE + 5)
        self.assertEqual((c.exception.code, c.exception.id), ("stale", rid))
        self.assertFalse(os.path.exists(request_path()))

    def test_garbage_is_refused(self):
        def plant(text):
            fd = os.open(request_path(), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)
        for text, rid in (("{nope", ""), ("[]", ""), (json.dumps({"id": "a1", "op": "format-disk"}), "a1"),
                          (json.dumps({"id": "a1", "op": "save", "values": {"api_key": "x"}}), "a1"),
                          (json.dumps({"id": "a1", "op": "save", "values": "x"}), "a1"),
                          (json.dumps({"op": "clear"}), ""), (json.dumps({"id": 5, "op": "clear"}), ""),
                          (json.dumps({"id": "a" * 33, "op": "clear"}), ""),
                          (json.dumps({"id": "a1", "op": "clear", "pad": "x" * ky.MAX_BYTES}), "")):
            plant(text)
            with self.assertRaises(ky.BadRequest) as c:
                ky.take_request()
            self.assertEqual((c.exception.code, c.exception.id), ("bad_request", rid), text[:40])
            self.assertFalse(os.path.exists(request_path()))

    def test_clear_needs_no_values(self):
        rid = ky.send_request("clear")
        self.assertEqual(ky.take_request(), {"id": rid, "op": "clear", "values": {}})

    def test_the_answer_holds_no_value_but_the_last_four_characters(self):
        self.assertTrue(ky.send_result("abc", True, last4=KEY))
        self.assertEqual(stat.S_IMODE(os.stat(result_path()).st_mode), 0o600)
        with open(result_path(), encoding="utf-8") as f:
            text = f.read()
        self.assertEqual(json.loads(text), {"id": "abc", "ok": True, "error": "", "last4": "WXYZ"})
        self.assertNotIn(KEY[:-4], text)
        self.assertEqual(ky.read_result("abc"), {"ok": True, "error": "", "last4": "WXYZ"})
        self.assertFalse(os.path.exists(result_path()))              # used up

    def test_somebody_elses_answer_is_not_mine_and_stays(self):
        ky.send_result("other", True)
        self.assertIsNone(ky.read_result("mine"))
        self.assertTrue(os.path.exists(result_path()))
        self.assertEqual(ky.read_result("other")["ok"], True)

    def test_a_new_request_forgets_an_old_answer(self):
        ky.send_result("old", True)
        ky.send_request("clear")
        self.assertFalse(os.path.exists(result_path()))
        ky.withdraw_request()
        self.assertEqual(os.listdir(ky.DIR), [])

    def test_an_unknown_error_word_is_dropped(self):
        ky.send_result("x", False, "rm -rf")
        self.assertEqual(ky.read_result("x"), {"ok": False, "error": "", "last4": ""})

    def test_what_the_addon_holds_is_read_without_touching_it(self):
        self.assertIsNone(ky.read_settings())
        preset(api_key=KEY, client_id=CID, client_secret=SECRET)
        self.assertEqual(ky.read_settings(), GOOD)
        preset(api_key=KEY)
        self.assertEqual(ky.read_settings(), {"api_key": KEY, "client_id": "", "client_secret": ""})
        with open(settings_path(), "w") as f:
            f.write("<settings")
        self.assertIsNone(ky.read_settings())


# ---- Google's verdict -----------------------------------------------------------------------------

class Verdict(Base):
    def verdict(self, answer):
        net = Net()
        net.answer = answer
        return pk.check_key(KEY, net.io()), net

    def test_200_is_a_working_key(self):
        (verdict, code), net = self.verdict((200, b'{"items":[]}'))
        self.assertEqual((verdict, code), ("ok", 200))
        self.assertEqual(pk.hint(verdict, code), "Ключ работает.")

    def test_one_request_with_the_documented_shape_and_a_timeout(self):
        (_, _), net = self.verdict((200, b"{}"))
        self.assertEqual(len(net.urls), 1)
        url = net.urls[0]
        self.assertTrue(url.startswith("https://www.googleapis.com/youtube/v3/videos?"), url[:60])
        for part in ("part=id", "chart=mostPopular", "maxResults=1", "key=" + KEY):
            self.assertIn(part, url)
        self.assertEqual(net.timeouts, [10])

    def test_the_key_is_url_encoded(self):
        net = Net()
        pk.check_key("a&b=c d/é", net.io())
        self.assertIn("key=a%26b%3Dc+d%2F%C3%A9", net.urls[0])
        self.assertEqual(net.urls[0].count("&key="), 1)

    def test_what_google_says_about_a_refused_key(self):
        cases = [
            (google_error(400, "API_KEY_INVALID", "details"), "invalid"),
            (google_error(400, "keyInvalid"), "invalid"),
            (google_error(403, "accessNotConfigured"), "disabled"),
            (google_error(403, "SERVICE_DISABLED", "details"), "disabled"),
            (google_error(403, "quotaExceeded"), "quota"),
            (google_error(403, "API_KEY_HTTP_REFERRER_BLOCKED", "details"), "blocked"),
            (google_error(403, "API_KEY_SERVICE_BLOCKED", "details"), "blocked"),
            (google_error(403, "somethingNew"), "other"),
            ((400, b"not json"), "other"),
            ((403, b"[]"), "other"),
            ((403, b'{"error":"x"}'), "other"),
            ((500, b""), "other"),
            ((404, b""), "other"),
        ]
        for answer, expected in cases:
            (verdict, code), _ = self.verdict(answer)
            self.assertEqual((verdict, code), (expected, answer[0]), answer)

    def test_each_verdict_says_what_to_do(self):
        self.assertIn("YouTube Data API v3", pk.hint("disabled"))
        self.assertIn("Включите", pk.hint("disabled"))
        self.assertIn("ограничения", pk.hint("blocked"))
        self.assertIn("целиком", pk.hint("invalid"))
        self.assertIn("лимит", pk.hint("quota"))
        self.assertIn("интернет", pk.hint("net"))
        self.assertIn("(код 500)", pk.hint("other", 500))
        self.assertEqual(pk.SAVABLE, ("ok", "quota"))

    def test_no_answer_is_the_network(self):
        for failure in (urllib.error.URLError("no route to https://x/?key=" + KEY), socket.timeout("timed out " + KEY),
                        ConnectionResetError(KEY), ValueError(KEY), OSError(KEY)):
            (verdict, code), _ = self.verdict(failure)
            self.assertEqual((verdict, code), ("net", 0), repr(failure))

    def test_google_s_own_words_are_not_passed_on(self):
        net = Net()
        net.answer = google_error(403, "accessNotConfigured", message="GOOGLE-MESSAGE-TEXT " + KEY)
        preset(**GOOD)
        reply, code = pk.handle({"action": "check"}, FakeKodi(), net.io())
        self.assertEqual(code, 200)
        self.assertNotIn("GOOGLE-MESSAGE-TEXT", json.dumps(reply))


class ClientVerdict(Base):
    """A client ID is tried at the device-code endpoint: a TV client gets a device code (dropped at once)."""
    def verdict(self, answer):
        net = Net()
        net.answer = answer
        return pk.check_client(CID, net.io()), net

    def test_a_device_code_means_a_client_for_tvs(self):
        (verdict, code), net = self.verdict(DEVICE_OK)
        self.assertEqual((verdict, code), ("ok", 200))
        self.assertEqual(pk.hint(verdict, kind="client_id"), "Клиент для ТВ найден.")

    def test_one_post_with_the_id_and_the_scope_in_the_body_not_in_the_url(self):
        _, net = self.verdict(DEVICE_OK)
        self.assertEqual(len(net.posts), 1)
        url, data, method, headers = net.posts[0]
        self.assertEqual((url, method), ("https://oauth2.googleapis.com/device/code", "POST"))
        self.assertEqual(sorted(data.decode().split("&")), sorted([
            "client_id=" + CID, "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fyoutube.readonly"]))
        self.assertNotIn(CIDTAG, url)
        self.assertNotIn("?", url)
        self.assertEqual(net.timeouts, [10])
        self.assertEqual(headers.get("Content-type"), "application/x-www-form-urlencoded")

    def test_what_google_says_about_a_client(self):
        cases = [
            (oauth_error(401, "invalid_client", "The OAuth client was not found."), "client_missing"),
            (oauth_error(400, "invalid_client"), "client_missing"),
            (oauth_error(401, "unauthorized_client"), "client_type"),
            (oauth_error(400, "unauthorized_client", "Unauthorized"), "client_type"),
            (oauth_error(400, "invalid_request", "Invalid client type."), "client_type"),
            (oauth_error(400, "invalid_request", "Missing required parameter"), "other"),
            (oauth_error(400, "invalid_scope"), "other"),
            (oauth_error(400, "access_denied"), "other"),
            ((200, b"{}"), "other"),                                          # a 200 without a device code is no proof
            ((200, b'{"device_code": ""}'), "other"),
            ((200, b"not json"), "other"),
            ((400, b"not json"), "other"),
            ((500, b""), "other"),
        ]
        for answer, expected in cases:
            (verdict, code), _ = self.verdict(answer)
            self.assertEqual((verdict, code), (expected, answer[0]), answer)

    def test_the_words_for_the_page(self):
        self.assertEqual(pk.hint("client_missing"), "ID не найден")
        self.assertEqual(pk.hint("client_type"),
                         "Это не клиент для ТВ: выберите тип TVs and Limited Input devices")

    def test_no_answer_is_the_network_and_no_text_of_it_leaks(self):
        for failure in (urllib.error.URLError("no route " + CID), socket.timeout(CID), ConnectionResetError(CID),
                        ValueError(CID), OSError(CID)):
            (verdict, code), _ = self.verdict(failure)
            self.assertEqual((verdict, code), ("net", 0), repr(failure))


# ---- the actions, with the add-on's own script behind them -----------------------------------------

class Actions(Base):
    def setUp(self):
        super().setUp()
        self.kodi, self.net = FakeKodi(), Net()

    def do(self, body, net=None):
        reply, code = pk.handle(body, self.kodi, (net or self.net).io())
        no_leak(self, json.dumps(reply))                            # no reply carries a value
        return reply, code

    def save(self, **extra):
        return self.do(dict(GOOD, action="save", **extra))

    def test_nothing_set_yet(self):
        self.assertEqual(self.do({"action": "status"}), ({"ok": True, "set": False, "partial": False, "last4": ""}, 200))

    def test_save_checks_the_key_then_hands_the_three_values_to_kodi(self):
        reply, code = self.save()
        self.assertEqual((code, reply["ok"], reply["saved"], reply["last4"], reply["check"]), (200, True, True, "WXYZ", "ok"))
        self.assertEqual(Fake.settings, {"youtube.api.key": KEY, "youtube.api.id": CID, "youtube.api.secret": SECRET})
        self.assertEqual(self.kodi.calls, [("Addons.ExecuteAddon", {"addonid": "script.media-stick.home", "params": ["ytkeys"]})])
        self.assertEqual(len(self.net.urls), 1)

    def test_the_request_file_was_private_when_kodi_read_it_and_nothing_is_left_after(self):
        self.save()
        self.assertEqual(self.kodi.modes, [0o600])
        self.assertEqual(os.listdir(ky.DIR), [])                    # the request deleted, the answer used up

    def test_no_value_reaches_the_log_or_what_kodi_is_asked(self):
        self.save()
        no_leak(self, json.dumps(self.kodi.calls))
        self.assertTrue(any("ytkeys save: done" in line for line in Fake.logs))
        no_leak(self, "".join(Fake.logs))

    def test_the_page_sees_saved_and_the_last_four_characters(self):
        self.save()
        reply, code = self.do({"action": "status"})
        self.assertEqual(reply, {"ok": True, "set": True, "partial": False, "last4": "WXYZ"})

    def test_keys_already_set(self):
        preset(api_key=KEY, client_id=CID, client_secret=SECRET)
        reply, _ = self.do({"action": "status"})
        self.assertEqual((reply["set"], reply["last4"]), (True, "WXYZ"))
        reply, code = self.do({"action": "check"})                  # checks the stored key
        self.assertEqual((code, reply["works"], reply["check"]), (200, True, "ok"))
        self.assertIn("key=" + KEY, self.net.urls[0])

    def test_check_tells_what_to_do(self):
        preset(api_key=KEY, client_id=CID, client_secret=SECRET)
        self.net.answer = google_error(403, "accessNotConfigured")
        reply, code = self.do({"action": "check"})
        self.assertEqual((code, reply["ok"], reply["works"], reply["check"]), (200, True, False, "disabled"))
        self.assertIn("YouTube Data API v3", reply["message"])
        self.net.answer = google_error(400, "API_KEY_INVALID", "details")
        reply, _ = self.do({"action": "check"})
        self.assertEqual((reply["works"], reply["check"]), (False, "invalid"))

    def test_check_without_a_key_has_nothing_to_check(self):
        reply, code = self.do({"action": "check"})
        self.assertEqual((code, reply["ok"]), (409, False))
        self.assertEqual(self.net.urls, [])
        preset(api_key=KEY)                                         # a half set is not a key to check
        self.assertEqual(self.do({"action": "check"})[1], 409)

    def test_a_refused_key_is_not_saved_and_kodi_is_not_asked(self):
        for answer, check in ((google_error(400, "API_KEY_INVALID", "details"), "invalid"),
                              (google_error(403, "accessNotConfigured"), "disabled"),
                              (google_error(403, "API_KEY_HTTP_REFERRER_BLOCKED", "details"), "blocked"),
                              ((500, b""), "other")):
            self.net.answer = answer
            reply, code = self.save()
            self.assertEqual((code, reply["ok"], reply["check"]), (422, False, check), answer)
            self.assertTrue(reply["error"])
        self.assertEqual(self.kodi.calls, [])
        self.assertEqual((Fake.settings, os.listdir(ky.DIR)), ({}, []))

    def test_a_key_over_its_quota_is_still_the_key(self):
        self.net.answer = google_error(403, "quotaExceeded")
        reply, code = self.save()
        self.assertEqual((code, reply["saved"], reply["check"]), (200, True, "quota"))
        self.assertIn("лимит", reply["message"])

    def test_no_network_offers_saving_unchecked_and_that_does_not_ask_google(self):
        self.net.answer = urllib.error.URLError("down")
        reply, code = self.save()
        self.assertEqual((code, reply["ok"], reply["check"]), (422, False, "net"))
        self.assertEqual(Fake.settings, {})
        self.net.urls.clear()
        reply, code = self.save(skip_check=True)
        self.assertEqual((code, reply["saved"], reply["check"], self.net.urls), (200, True, "skipped", []))
        self.assertEqual(Fake.settings["youtube.api.key"], KEY)
        self.save(skip_check="yes")                                 # only a real true skips the check
        self.assertEqual(len(self.net.urls), 1)

    def test_bad_values_stop_before_anything_happens(self):
        for body in (dict(GOOD, api_key="short"), dict(GOOD, client_id="x.example.com"), dict(GOOD, client_secret=""),
                     dict(GOOD, api_key=KEY + " " + KEY), {}, dict(GOOD, client_secret="s" * 129)):
            reply, code = self.do(dict(body, action="save"))
            self.assertEqual((code, reply["ok"]), (400, False), body)
        self.assertEqual((self.net.urls, self.kodi.calls, os.listdir(ky.DIR)), ([], [], []))

    def test_the_server_does_not_trust_values_that_pass_the_old_rules_but_look_like_nothing(self):
        for body in (dict(GOOD, api_key="AIza" + "a" * 34), dict(GOOD, api_key="AIza" + "a" * 36),
                     dict(GOOD, api_key="x" * 40), dict(GOOD, client_id="123-ABC" + ky.ID_SUFFIX),
                     dict(GOOD, client_id="abc-def" + ky.ID_SUFFIX), dict(GOOD, client_secret="x"),
                     dict(GOOD, client_secret="GOCSPX-short"), dict(GOOD, client_secret="GOCSPX-" + "a" * 41),
                     dict(GOOD, client_secret=KEY)):
            reply, code = self.do(dict(body, action="save"))
            self.assertEqual((code, reply["ok"]), (400, False), body)
            self.assertIn("не похоже", reply["error"])
        self.assertEqual((self.net.urls, self.kodi.calls, os.listdir(ky.DIR), Fake.settings), ([], [], [], {}))

    def test_replace_overwrites(self):
        self.save()
        other = dict(GOOD, api_key="AIzaMARKER-OTHER-0123456789abcdefghABCD")
        reply, _ = self.do(dict(other, action="save"))
        self.assertEqual(reply["last4"], "ABCD")
        self.assertEqual(Fake.settings["youtube.api.key"], other["api_key"])

    def test_clear_writes_empty_values(self):
        self.save()
        reply, code = self.do({"action": "clear"})
        self.assertEqual((code, reply["ok"]), (200, True))
        self.assertEqual(Fake.settings, {"youtube.api.key": "", "youtube.api.id": "", "youtube.api.secret": ""})
        self.assertEqual(self.do({"action": "status"})[0]["set"], False)
        self.assertEqual(os.listdir(ky.DIR), [])
        self.assertEqual(len(self.net.urls), 1)                     # only the save asked Google; clearing asks nobody

    def test_a_half_set_is_told_apart(self):
        preset(api_key=KEY)
        self.assertEqual(self.do({"action": "status"})[0], {"ok": True, "set": False, "partial": True, "last4": ""})

    def test_kodi_down_is_a_calm_503_and_leaves_no_file(self):
        self.kodi.down = True
        reply, code = self.save()
        self.assertEqual((code, reply["ok"]), (503, False))
        self.assertIn("ТВ", reply["error"])
        self.assertEqual(os.listdir(ky.DIR), [])

    def test_a_script_that_never_answers_times_out_and_withdraws_the_request(self):
        self.kodi.script = False
        ticks = iter(range(0, 1000, 5))
        reply, code = pk.handle(dict(GOOD, action="save"), self.kodi, self.net.io(lambda: next(ticks)))
        self.assertEqual((code, reply["ok"]), (504, False))
        self.assertEqual(os.listdir(ky.DIR), [])                    # the values must not lie in /run
        no_leak(self, json.dumps(reply))

    def test_it_waits_for_the_script_as_long_as_it_takes_within_the_limit(self):
        later = []
        self.kodi.script = False
        sleeps = []

        def sleep(s):
            sleeps.append(s)
            if len(sleeps) == 3:                                    # the script answers on the third look
                rid = json.load(open(request_path()))["id"]
                later.append(rid)
                ky.send_result(rid, True, last4=KEY)

        io_ = pk.Io(self.net.urlopen, sleep, lambda: len(sleeps) * 0.25)
        reply, code = pk.handle(dict(GOOD, action="save"), self.kodi, io_)
        self.assertEqual((code, reply["saved"], reply["last4"], len(sleeps)), (200, True, "WXYZ", 3))

    def test_the_add_on_missing_or_refusing_is_said_plainly(self):
        Fake.missing = True
        reply, code = self.save()
        self.assertEqual((code, reply["error"]), (500, "Дополнение YouTube не установлено."))
        Fake.missing, Fake.refuse = False, True
        reply, code = self.save()
        self.assertEqual(code, 500)
        self.assertIn("не смог записать", reply["error"])
        self.assertEqual(os.listdir(ky.DIR), [])

    def test_an_exception_that_holds_a_value_is_logged_by_its_type_only(self):
        Fake.explode = True
        reply, code = self.save()
        self.assertEqual(code, 500)
        self.assertTrue(any("ValueError" in line for line in Fake.logs))

    def test_one_hand_over_at_a_time(self):
        with pk.LOCK:
            reply, code = self.save()
        self.assertEqual((code, reply["ok"]), (409, False))
        self.assertEqual((self.kodi.calls, os.listdir(ky.DIR)), ([], []))

    def test_unknown_actions(self):
        for body in ({}, {"action": "format"}, {"action": 5}, {"action": None}, {"action": ["save"]}):
            self.assertEqual(self.do(body)[1], 404, body)


class Verify(Base):
    """The instant check of one pasted text: what it is, and Google's word on it."""
    def setUp(self):
        super().setUp()
        self.kodi, self.net = FakeKodi(), Net()

    def verify(self, text):
        reply, code = pk.handle({"action": "verify", "value": text}, self.kodi, self.net.io())
        no_leak(self, json.dumps(reply))
        return reply, code

    def test_a_key_is_tried_with_the_one_videos_request(self):
        reply, code = self.verify(KEY)
        self.assertEqual((code, reply["ok"], reply["kind"], reply["check"], reply["works"]), (200, True, "api_key", "ok", True))
        self.assertEqual(len(self.net.urls), 1)
        self.assertTrue(self.net.urls[0].startswith(pk.CHECK_URL + "?"))
        self.assertEqual(self.net.posts, [])

    def test_a_refused_key_says_why_and_is_not_working(self):
        self.net.answer = google_error(403, "accessNotConfigured")
        reply, _ = self.verify("  " + KEY + "\n")                     # trimmed
        self.assertEqual((reply["kind"], reply["check"], reply["works"]), ("api_key", "disabled", False))
        self.assertIn("YouTube Data API v3", reply["message"])

    def test_a_key_over_its_quota_still_counts(self):
        self.net.answer = google_error(403, "quotaExceeded")
        reply, _ = self.verify(KEY)
        self.assertEqual((reply["check"], reply["works"]), ("quota", True))

    def test_a_client_id_is_tried_at_the_device_code_endpoint(self):
        self.net.answer = DEVICE_OK
        reply, code = self.verify(CID)
        self.assertEqual((code, reply["kind"], reply["check"], reply["works"], reply["message"]),
                         (200, "client_id", "ok", True, "Клиент для ТВ найден."))
        self.assertEqual(len(self.net.posts), 1)
        self.assertNotIn("DEVICE-CODE-TO-DROP", json.dumps(reply))      # the code is dropped
        self.assertNotIn("DEVICE-CODE-TO-DROP", self.out.getvalue() + "".join(Fake.logs))

    def test_the_client_verdicts_have_the_agreed_words(self):
        for answer, check, message in (
                (oauth_error(401, "invalid_client"), "client_missing", "ID не найден"),
                (oauth_error(401, "unauthorized_client"), "client_type",
                 "Это не клиент для ТВ: выберите тип TVs and Limited Input devices"),
                (oauth_error(400, "invalid_request", "Invalid client type"), "client_type",
                 "Это не клиент для ТВ: выберите тип TVs and Limited Input devices")):
            self.net.answer = answer
            reply, _ = self.verify(CID)
            self.assertEqual((reply["check"], reply["works"], reply["message"]), (check, False, message))

    def test_a_secret_is_only_checked_for_its_shape_and_asks_nobody(self):
        reply, code = self.verify(SECRET)
        self.assertEqual((code, reply["kind"], reply["works"]), (200, "client_secret", True))
        self.assertEqual((self.net.urls, self.net.posts), ([], []))

    def test_no_network_is_not_a_refusal(self):
        self.net.answer = urllib.error.URLError("down " + CID)
        for text in (KEY, CID):
            reply, _ = self.verify(text)
            self.assertEqual((reply["check"], reply["works"]), ("net", False), text)
            self.assertIn("интернет", reply["message"])

    def test_what_is_not_a_key_an_id_or_a_secret_is_refused_and_asks_nobody(self):
        for text in ("", "hello", KEY + KEY, "AIza" + "a" * 34, CID.upper(), "x" * 5000, None, 5, ["x"], {"a": CID}):
            reply, code = self.verify(text)
            self.assertEqual((code, reply["ok"], reply["error"]), (400, False, "Не похоже ни на ключ, ни на ID, ни на secret"), text)
        self.assertEqual((self.net.urls, self.net.posts), ([], []))

    def test_the_body_may_not_name_the_kind(self):
        reply, code = pk.handle({"action": "verify", "kind": "api_key", "value": CID}, self.kodi, self.net.io())
        self.assertEqual((code, reply.get("kind")), (200, "client_id"))      # the server decides what it is

    def test_the_urls_asked_never_log_and_the_key_is_in_one_get_only(self):
        self.net.answer = DEVICE_OK
        self.verify(KEY)
        self.verify(CID)
        self.verify(SECRET)
        self.assertEqual(len(self.net.urls), 2)
        self.assertEqual(len(self.net.posts), 1)
        self.assertNotIn(CIDTAG, self.net.urls[1])

    def test_the_checks_go_to_the_step_file_and_the_tv_as_booleans_only(self):
        pk.handle({"action": "step", "step": 4}, self.kodi, self.net.io())
        self.net.answer = DEVICE_OK
        self.verify(CID)
        self.assertEqual(ky.read_step()["checks"], {"key": None, "client_id": True, "secret": None})
        self.verify(SECRET)
        self.net.answer = google_error(403, "API_KEY_INVALID", "details")
        self.verify(KEY)
        self.assertEqual(ky.read_step()["checks"], {"key": False, "client_id": True, "secret": True})
        self.assertEqual([i["s"] for i in self.ob.last["items"]], ["wait", "ok", "ok"])
        self.net.answer = (200, b"{}")
        self.verify(KEY)
        self.assertEqual(ky.read_step()["checks"], {"key": True, "client_id": True, "secret": True})
        self.assertEqual([i["s"] for i in self.ob.last["items"]], ["ok", "ok", "ok"])
        self.net.answer = urllib.error.URLError("down")
        self.verify(KEY)
        self.assertEqual(ky.read_step()["checks"]["key"], None)                # not known is not wrong
        for _, doc in self.ob.written:
            check_doc(self, doc)

    def test_nothing_is_written_for_the_tv_while_the_wizard_is_closed(self):
        self.verify(KEY)
        self.assertEqual(os.listdir(ky.DIR), [])
        self.assertEqual((self.ob.written, self.ob.cleared), ([], []))


class Script(Base):
    """ytkeys.main by itself: the add-on's side of the hand-over."""
    def test_no_request_is_logged_and_answers_nobody(self):
        self.assertFalse(ytkeys.main([]))
        self.assertTrue(any("no_request" in line for line in Fake.logs))
        self.assertFalse(os.path.exists(result_path()))

    def test_a_refused_request_is_answered_so_the_panel_need_not_wait(self):
        rid = ky.send_request("save", GOOD)
        os.chmod(request_path(), 0o640)
        self.assertFalse(ytkeys.main([]))
        self.assertEqual(ky.read_result(rid), {"ok": False, "error": "insecure", "last4": ""})
        self.assertEqual(Fake.settings, {})

    def test_the_request_is_gone_before_the_settings_are_written(self):
        seen = []
        original = StubYoutube.setSettingString

        def watching(self_, sid, value):
            seen.append(os.path.exists(request_path()))
            return original(self_, sid, value)

        ky.send_request("save", GOOD)
        with mock.patch.object(StubYoutube, "setSettingString", watching):
            self.assertTrue(ytkeys.main([]))
        self.assertEqual(seen, [False, False, False])

    def test_a_failure_in_the_middle_is_an_error_not_a_pretend_success(self):
        rid = ky.send_request("save", GOOD)
        calls = []

        def second_fails(self_, sid, value):
            calls.append(sid)
            return len(calls) < 2

        with mock.patch.object(StubYoutube, "setSettingString", second_fails):
            self.assertFalse(ytkeys.main([]))
        self.assertEqual(ky.read_result(rid), {"ok": False, "error": "write_failed", "last4": ""})


class Dispatch(Base):
    def test_default_py_runs_the_script_for_ytkeys_only(self):
        ky.send_request("save", GOOD)
        run_default(["ytkeys"])
        self.assertEqual(Fake.settings["youtube.api.key"], KEY)
        Fake.settings = {}
        for argv in (["ytkeys-x"], [], ["launch"]):
            with mock.patch.object(ytkeys, "main") as main, mock.patch.object(xbmc, "executebuiltin"):
                run_default(argv)
            main.assert_not_called()

    def test_an_exception_in_the_script_is_logged_by_type_and_never_raised(self):
        with mock.patch.object(ytkeys, "main", side_effect=KeyError(KEY)):
            run_default(["ytkeys"])
        self.assertTrue(any("KeyError" in line for line in Fake.logs))

    def test_the_argv_has_no_room_for_keys(self):
        with mock.patch.object(ytkeys, "main") as main:
            run_default(["ytkeys", "extra"])
        main.assert_called_once_with(["extra"])                     # ignored by main; the values are in the file


# ---- the step file: where the owner is in the wizard, for the TV --------------------------------------

def step_path():
    return os.path.join(ky.DIR, ky.STEP)


class StepFile(Base):
    NOW = 1_800_000_000

    def put(self, **over):
        data = {"step": 3, "total": 6, "title": "T", "hint": "H", "updated": self.NOW}
        data.update(over)
        with open(step_path(), "w", encoding="utf-8") as f:
            json.dump(data, f)

    def test_written_whole_world_readable_and_alone(self):
        ky.write_step(4, 6, "Создайте ключ API", "Вставьте ключ", now=self.NOW)
        self.assertEqual(stat.S_IMODE(os.stat(step_path()).st_mode), 0o644)
        self.assertEqual(os.listdir(ky.DIR), [ky.STEP])                 # no half-written file next to it
        with open(step_path(), encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"step": 4, "total": 6, "title": "Создайте ключ API", "hint": "Вставьте ключ",
                                            "updated": self.NOW})

    def test_a_failed_write_leaves_the_old_file_and_no_leftover(self):
        ky.write_step(2, 6, "A", "B", now=self.NOW)
        with mock.patch("os.replace", side_effect=OSError("disk")):
            with self.assertRaises(OSError):
                ky.write_step(3, 6, "C", "D", now=self.NOW)
        self.assertEqual(os.listdir(ky.DIR), [ky.STEP])
        self.assertEqual(ky.read_step(now=self.NOW)["step"], 2)         # a reader never sees a half-written file

    def test_a_new_step_replaces_the_old_one(self):
        ky.write_step(2, 6, "A", "B", now=self.NOW)
        ky.write_step(5, 6, "C", "D", now=self.NOW + 5)
        self.assertEqual(ky.read_step(now=self.NOW + 5), {"step": 5, "total": 6, "title": "C", "hint": "D", "updated": self.NOW + 5})

    def test_it_is_read_back_by_the_path_it_is_given(self):
        ky.write_step(1, 6, "A", "B", now=self.NOW)
        self.assertEqual(ky.read_step(step_path(), self.NOW)["step"], 1)
        self.assertEqual(ky.read_step(step_path(), self.NOW)["total"], 6)
        self.assertIsNone(ky.read_step(os.path.join(ky.DIR, "nothing.json"), self.NOW))

    def test_no_file_is_none(self):
        self.assertIsNone(ky.read_step(now=self.NOW))
        self.assertIsNone(ky.read_step(step_path(), self.NOW))

    def test_a_file_older_than_thirty_minutes_is_stale(self):
        self.put()
        self.assertIsNotNone(ky.read_step(step_path(), self.NOW + 30 * 60))
        self.assertIsNone(ky.read_step(step_path(), self.NOW + 30 * 60 + 1))
        self.assertIsNone(ky.read_step(step_path(), self.NOW + 86400))

    def test_a_clock_that_jumped_back_does_not_keep_it_alive_for_ever(self):
        self.put()
        self.assertIsNone(ky.read_step(step_path(), self.NOW - 3600))

    def test_the_time_comes_from_the_clock_when_not_given(self):
        ky.write_step(2, 6, "A", "B")
        self.assertEqual(ky.read_step()["step"], 2)
        self.put(updated=1)
        self.assertIsNone(ky.read_step())

    def test_rubbish_is_none_not_an_error(self):
        for raw in (b"", b"{", b"[]", b"null", b'"x"', b"\xff\xfe\x00", b"{}", b'{"step": NaN}',
                    b'{"step": 3, "total": 6, "title": "T", "hint": "H", "updated": NaN}',
                    b'{"step": 3, "total": 6, "title": "T", "hint": "H", "updated": 1e999}',
                    b'{"step": 3, "total": 6, "title": "T", "hint": "H", "updated": 1' + b"0" * 500 + b"}",
                    b"x" * 10000):
            with open(step_path(), "wb") as f:
                f.write(raw)
            self.assertIsNone(ky.read_step(step_path(), self.NOW), raw[:30])

    def test_wrong_shapes_are_none(self):
        for over in ({"step": "3"}, {"step": 3.0}, {"step": True}, {"step": None}, {"total": "6"}, {"total": None},
                     {"title": None}, {"title": 5}, {"hint": None}, {"hint": ["x"]}, {"updated": "now"},
                     {"updated": None}, {"updated": True}):
            self.put(**over)
            self.assertIsNone(ky.read_step(step_path(), self.NOW), over)

    def test_a_step_outside_one_to_total_is_none(self):
        for over in ({"step": 0}, {"step": -1}, {"step": 7}, {"step": 99}, {"total": 0, "step": 0}, {"total": 10, "step": 3},
                     {"total": -6}):
            self.put(**over)
            self.assertIsNone(ky.read_step(step_path(), self.NOW), over)
        for step in range(1, 7):
            self.put(step=step)
            self.assertEqual(ky.read_step(step_path(), self.NOW)["step"], step)

    def test_the_text_is_cut_to_what_fits_on_the_screen(self):
        self.put(title="t" * 500, hint="h" * 500)
        got = ky.read_step(step_path(), self.NOW)
        self.assertEqual((len(got["title"]), len(got["hint"])), (ky.STEP_TITLE_MAX, ky.STEP_HINT_MAX))

    def test_write_refuses_what_it_could_not_read_back(self):
        for args in ((0, 6, "a", "b"), (7, 6, "a", "b"), (True, 6, "a", "b"), ("3", 6, "a", "b"), (1, 10, "a", "b"),
                     (1, 6, None, "b"), (1, 6, "a", 5)):
            with self.assertRaises(ValueError, msg=args):
                ky.write_step(*args)
        self.assertEqual(os.listdir(ky.DIR), [])

    def test_clear_removes_it_and_is_fine_without_it(self):
        ky.clear_step()
        ky.write_step(2, 6, "A", "B")
        ky.clear_step()
        self.assertEqual(os.listdir(ky.DIR), [])

    def test_the_checks_are_booleans_or_null_and_nothing_else(self):
        good = {"key": True, "client_id": None, "secret": False}
        ky.write_step(3, 4, "A", "B", now=self.NOW, checks=good)
        with open(step_path(), encoding="utf-8") as f:
            self.assertEqual(json.load(f)["checks"], good)
        self.assertEqual(ky.read_step(now=self.NOW)["checks"], good)
        for bad in ({"key": "yes"}, {"key": 1}, {"key": KEY}, {"value": True}, [True], "x", {"key": ["x"]}):
            with self.assertRaises(ValueError, msg=bad):
                ky.write_step(3, 4, "A", "B", now=self.NOW, checks=bad)
        self.assertEqual(ky.read_step(now=self.NOW)["checks"], good)             # the refused write changed nothing

    def test_a_partial_checks_object_is_filled_with_nulls(self):
        ky.write_step(3, 4, "A", "B", now=self.NOW, checks={"key": True})
        self.assertEqual(ky.read_step(now=self.NOW)["checks"], {"key": True, "client_id": None, "secret": None})

    def test_a_file_with_bad_checks_still_reads_without_them(self):
        self.put(total=4, checks={"key": "AIza-a-value"})
        got = ky.read_step(step_path(), self.NOW)
        self.assertNotIn("checks", got)
        self.assertEqual(got["step"], 3)


class Links(unittest.TestCase):
    """What a step's link looks like on an Android phone (intent) and on an iPhone (x-safari-https): pure."""
    URL = "https://console.cloud.google.com/apis/credentials/oauthclient?project=my-tv&x=1"

    def test_the_android_intent_is_the_url_without_its_scheme_and_the_whole_url_as_the_fallback(self):
        self.assertEqual(
            pk.android_intent(self.URL),
            "intent://console.cloud.google.com/apis/credentials/oauthclient?project=my-tv&x=1"
            "#Intent;scheme=https;action=android.intent.action.VIEW;"
            "S.browser_fallback_url=https%3A%2F%2Fconsole.cloud.google.com%2Fapis%2Fcredentials%2Foauthclient%3Fproject%3Dmy-tv%26x%3D1;end")

    def test_the_fallback_decodes_to_the_original_url_and_has_nothing_that_ends_a_field(self):
        import urllib.parse
        intent = pk.android_intent(self.URL)
        head, tail = intent.split("#Intent;", 1)
        fields = tail.split(";")
        self.assertEqual(fields[-1], "end")
        fallback = [f for f in fields if f.startswith("S.browser_fallback_url=")]
        self.assertEqual(len(fallback), 1)
        self.assertEqual(urllib.parse.unquote(fallback[0].split("=", 1)[1]), self.URL)
        self.assertEqual(fields[:3], ["scheme=https", "action=android.intent.action.VIEW", fallback[0]])
        self.assertEqual("https://" + head[len("intent://"):], self.URL)
        self.assertEqual(intent.count("#"), 1)

    def test_the_safari_link_is_the_url_behind_x_safari(self):
        self.assertEqual(pk.safari_link("https://console.cloud.google.com/auth/overview"),
                         "x-safari-https://console.cloud.google.com/auth/overview")

    def test_a_url_that_cannot_stand_inside_another_scheme_gives_nothing(self):
        for url in ("http://console.cloud.google.com/", "https://", "https://a/b;c", "https://a/b#frag", "ftp://a/b",
                    "https://a/b c", "https://a/б", "https://a/<b>", 'https://a/"b"', "https://a/b'c", "https://a/b\\c",
                    "https://a/\n", "//a/b", "", None, 5, ["https://a/"], "https://a/" + "x" * 600):
            self.assertEqual((pk.android_intent(url), pk.safari_link(url)), ("", ""), url)

    def test_every_step_and_the_doc_link_carry_both_forms_and_they_agree_with_the_url(self):
        for item in list(pk.WIZARD["steps"]) + [pk.WIZARD["doc"]]:
            self.assertEqual(item["intent"], pk.android_intent(item["url"]))
            self.assertEqual(item["safari"], "x-safari-" + item["url"])
            self.assertTrue(item["intent"].startswith("intent://" + item["url"][len("https://"):] + "#Intent;"), item["url"])
            self.assertEqual(pa.safe_link(item["url"]), item["url"])

    def test_the_wizard_says_what_the_page_may_claim(self):
        t = pk.WIZARD["texts"]
        self.assertEqual(t["open"], "Откроется в браузере. Вернитесь в пульт и нажмите «Сделано, дальше».")
        self.assertIn("Скопировать ссылку", t["copy"])
        self.assertEqual(t["safari"], "Открыть в Safari")
        self.assertEqual(t["ios_standalone"],
                         "Ссылки открываются внутри приложения. Чтобы открывать их в Safari, откройте пульт в Safari, "
                         "а не с экрана «Домой». Вернуться сюда можно кнопкой «Закрыть» вверху.")
        self.assertEqual(t["resume"] % (3, 4), "Продолжить настройку ключей (шаг 3 из 4)")
        self.assertEqual(t["header"], "Ключ Google для YouTube")
        self.assertEqual(t["intro"] % "pult.local",
                         "Нужен один раз, минут пять. С компьютера удобнее: откройте pult.local в браузере ноутбука — шаги те же.")


class StepActions(Base):
    def setUp(self):
        super().setUp()
        self.kodi, self.net = FakeKodi(), Net()

    def do(self, body):
        reply, code = pk.handle(body, self.kodi, self.net.io())
        no_leak(self, json.dumps(reply))
        return reply, code

    def test_every_step_writes_its_own_title_and_hint_in_english(self):
        self.assertEqual(pk.STEP_TOTAL, 4)
        expected = [
            ("Project and API", "On your phone: open the Google link and tap Enable."),
            ("Allow TV sign-in", "Get started › App name: TV › External › Create › Branding: two links › Audience › Publish app."),
            ("API key", "Create an API key and paste it on your phone."),
            ("TV client", "Create a client of type TVs and Limited Input devices, paste its ID and secret on your phone."),
        ]
        for n in range(1, 5):
            self.assertEqual(self.do({"action": "step", "step": n}), ({"ok": True, "step": n}, 200))
            got = ky.read_step()
            self.assertEqual((got["step"], got["total"], got["title"], got["hint"]), (n, 4, *expected[n - 1]))
            self.assertEqual(pk.step_text(n), expected[n - 1])
            self.assertLessEqual(len(got["hint"]), 120)
            self.assertLessEqual(len(got["title"]), ky.STEP_TITLE_MAX)
            self.assertEqual(stat.S_IMODE(os.stat(step_path()).st_mode), 0o644)
            self.assertEqual(got["checks"], {"key": None, "client_id": None, "secret": None})
        self.assertEqual(self.kodi.calls, [])                       # no Kodi call: the TV reads the file itself

    def test_the_file_has_the_old_shape_plus_checks(self):
        self.do({"action": "step", "step": 3})
        with open(step_path(), encoding="utf-8") as f:
            self.assertEqual(set(json.load(f)), {"step", "total", "title", "hint", "updated", "checks"})

    def test_the_words_come_from_the_wizard_description(self):
        for n, s in enumerate(steps.STEPS, 1):
            self.assertEqual(pk.step_text(n), (s["tv"], s["tv_hint"]))
            self.assertLessEqual(len(s["tv_hint"]), 120)
            self.assertLessEqual(len(s["hint"]), 160)
            self.assertTrue(s["tv"].isascii() and s["tv_hint"].isascii() or "›" in s["tv_hint"])   # the TV's words are English

    def test_step_zero_removes_the_file_and_is_fine_without_one(self):
        self.do({"action": "step", "step": 3})
        self.assertTrue(os.path.exists(step_path()))
        self.assertEqual(self.do({"action": "step", "step": 0}), ({"ok": True, "step": 0}, 200))
        self.assertFalse(os.path.exists(step_path()))
        self.assertIsNone(ky.read_step())
        self.assertEqual(self.do({"action": "step", "step": 0})[1], 200)

    def test_a_step_outside_zero_to_four_or_not_a_whole_number_is_refused_and_changes_nothing(self):
        self.do({"action": "step", "step": 2})
        before = ky.read_step()
        for bad in (5, 6, -1, 100, "3", "", 2.0, 2.5, True, False, None, [3], {"a": 1}):
            reply, code = self.do({"action": "step", "step": bad})
            self.assertEqual((code, reply["ok"]), (400, False), bad)
        reply, code = self.do({"action": "step"})
        self.assertEqual(code, 400)
        self.assertEqual(ky.read_step(), before)

    def test_nothing_from_the_body_reaches_the_file_or_the_reply(self):
        body = dict(GOOD, action="step", step=3, title="MARKER-TITLE", hint="MARKER-HINT", url="MARKER-URL")
        reply, code = self.do(body)
        self.assertEqual((code, reply), (200, {"ok": True, "step": 3}))
        with open(step_path(), encoding="utf-8") as f:
            text = f.read()
        for secret in (KEY, CID, SECRET, "MARKER", CIDTAG):
            self.assertNotIn(secret, text)
        self.assertEqual(set(json.loads(text)), {"step", "total", "title", "hint", "updated", "checks"})

    def test_the_file_never_holds_a_value_even_after_a_failed_save(self):
        self.do({"action": "step", "step": 4})
        self.net.answer = google_error(403, "API_KEY_INVALID", message="MARKER-GOOGLE")
        reply, code = self.do(dict(GOOD, action="save"))
        self.assertEqual(code, 422)
        with open(step_path(), encoding="utf-8") as f:
            self.assertNotIn("MARKER", f.read())
        self.assertEqual(ky.read_step()["step"], 4)                  # not saved: the wizard goes on

    def test_a_saved_key_ends_the_wizard_on_the_tv_too(self):
        self.do({"action": "step", "step": 4})
        reply, code = self.do(dict(GOOD, action="save"))
        self.assertEqual(code, 200)
        self.assertIsNone(ky.read_step())
        self.assertFalse(os.path.exists(step_path()))
        self.assertEqual(self.ob.cleared, ["youtube"])

    def test_a_save_that_kodi_refuses_leaves_the_step(self):
        self.do({"action": "step", "step": 4})
        Fake.refuse = True
        reply, code = self.do(dict(GOOD, action="save"))
        self.assertEqual(code, 500)
        self.assertEqual(ky.read_step()["step"], 4)
        self.assertEqual(self.ob.cleared, [])

    def test_check_status_and_clear_leave_it_alone(self):
        self.do({"action": "step", "step": 4})
        self.do({"action": "status"})
        self.do(dict(GOOD, action="save", skip_check=True))
        self.do({"action": "step", "step": 1})
        self.do({"action": "clear"})
        self.assertEqual(ky.read_step()["step"], 1)

    def test_a_step_file_that_cannot_be_written_is_a_calm_500(self):
        with mock.patch.object(ky, "_write_private", side_effect=OSError("tmpfs full")):
            reply, code = self.do({"action": "step", "step": 2})
        self.assertEqual((code, reply["ok"]), (500, False))
        self.assertIn("шаг", reply["error"])


class Ticks(Base):
    """Step 2's checklist: the ticks stay on the panel with the step and turn into the TV's chips."""
    def setUp(self):
        super().setUp()
        self.kodi, self.net = FakeKodi(), Net()

    def do(self, body):
        reply, code = pk.handle(body, self.kodi, self.net.io())
        no_leak(self, json.dumps(reply))
        return reply, code

    def states(self):
        return [[c["s"] for c in row] for row in self.ob.last["chips"]]

    def test_the_seven_boxes_are_the_seven_chips(self):
        self.assertEqual(steps.TICK_IDS, ("start", "name", "external", "create", "links", "audience", "publish"))
        self.assertEqual([[c["t"] for c in row] for row in steps.chip_rows([])],
                         [["Get started", "App name: TV", "Audience: External", "Create"],
                          ["Branding: links", "Audience", "Publish app"]])
        self.assertEqual([t["label"] for t in pk.WIZARD["ticks"]][0], "Нажмите «Начать»")

    def test_step_two_offers_the_pages_google_needs_to_publish(self):
        s = pk.WIZARD["steps"][1]
        self.assertEqual([c["value"] for c in s["copies"]],
                         ["https://hanzhad.github.io/media-stick/", "https://hanzhad.github.io/media-stick/privacy.html",
                          "hanzhad.github.io"])
        for c in s["copies"][:2]:
            self.assertTrue(c["value"].startswith("https://" + steps.PAGES_DOMAIN + "/"))

    def test_step_four_warns_the_secret_is_shown_once_and_explains_the_unverified_screen(self):
        lines = " ".join(steps.STEPS[3]["lines"])
        self.assertIn("один раз", lines)
        self.assertIn("Download JSON", lines)
        self.assertIn("не проверено", lines)

    def test_the_first_open_chip_is_now_the_ticked_are_done_the_rest_todo(self):
        self.do({"action": "step", "step": 2})
        self.assertEqual(self.states(), [["now", "todo", "todo", "todo"], ["todo", "todo", "todo"]])
        self.assertEqual(self.do({"action": "tick", "id": "start", "on": True}), ({"ok": True, "ticks": ["start"]}, 200))
        self.assertEqual(self.states(), [["done", "now", "todo", "todo"], ["todo", "todo", "todo"]])
        self.do({"action": "tick", "id": "external", "on": True})
        self.assertEqual(self.states(), [["done", "now", "done", "todo"], ["todo", "todo", "todo"]])
        for i in ("name", "create", "links", "audience"):
            reply, _ = self.do({"action": "tick", "id": i, "on": True})
        self.assertEqual(reply["ticks"], ["start", "name", "external", "create", "links", "audience"])
        self.assertEqual(self.states(), [["done"] * 4, ["done", "done", "now"]])
        self.do({"action": "tick", "id": "publish", "on": True})
        self.assertEqual(self.states(), [["done"] * 4, ["done", "done", "done"]])
        self.do({"action": "tick", "id": "start", "on": False})
        self.assertEqual(self.states()[0][0], "now")

    def test_every_change_is_written_and_every_document_has_the_shape(self):
        for body in ({"action": "step", "step": 2}, {"action": "tick", "id": "start", "on": True},
                     {"action": "tick", "id": "name", "on": True}, {"action": "step", "step": 3}):
            self.do(body)
        self.assertEqual([d["step"] for _, d in self.ob.written], [2, 2, 2, 3])
        self.assertEqual({s for s, _ in self.ob.written}, {"youtube"})
        for _, doc in self.ob.written:
            check_doc(self, doc)

    def test_the_ticks_are_kept_when_the_owner_goes_to_another_step_and_back(self):
        self.do({"action": "step", "step": 2})
        self.do({"action": "tick", "id": "start", "on": True})
        self.do({"action": "step", "step": 3})
        self.do({"action": "step", "step": 2})
        self.assertEqual(self.states()[0][0], "done")
        self.assertEqual(self.do({"action": "resume"})[0]["ticks"], ["start"])

    def test_only_a_known_box_and_a_real_boolean(self):
        for bad in ({"id": "x", "on": True}, {"id": None, "on": True}, {"id": 1, "on": True}, {"id": "start", "on": 1},
                    {"id": "start", "on": "true"}, {"id": "start"}, {"on": True}, {"id": ["start"], "on": True}):
            reply, code = self.do(dict(bad, action="tick"))
            self.assertEqual((code, reply["ok"]), (400, False), bad)
        self.assertEqual(pk.PROGRESS.ticks, set())

    def test_a_tick_while_the_wizard_is_closed_writes_nothing_for_the_tv(self):
        self.do({"action": "tick", "id": "start", "on": True})
        self.assertEqual((self.ob.written, os.listdir(ky.DIR)), ([], []))

    def test_a_tick_that_cannot_be_written_for_the_tv_is_still_taken(self):
        self.do({"action": "step", "step": 2})
        with mock.patch.object(ky, "_write_private", side_effect=OSError("full")):
            reply, code = self.do({"action": "tick", "id": "start", "on": True})
        self.assertEqual((code, reply["ticks"]), (200, ["start"]))


class Resume(Base):
    def setUp(self):
        super().setUp()
        self.kodi, self.net = FakeKodi(), Net()

    def do(self, body):
        reply, code = pk.handle(body, self.kodi, self.net.io())
        no_leak(self, json.dumps(reply))
        return reply, code

    def test_a_page_that_was_away_gets_the_step_back(self):
        self.assertEqual(self.do({"action": "resume"})[0],
                         {"ok": True, "step": 1, "open": False, "ticks": [], "checks": {"key": None, "client_id": None, "secret": None}})
        self.do({"action": "step", "step": 3})
        self.assertEqual(self.do({"action": "resume"})[0]["step"], 3)
        self.do({"action": "step", "step": 0})                       # closed: the step is kept for the next «Ключи»
        reply, _ = self.do({"action": "resume"})
        self.assertEqual((reply["step"], reply["open"]), (3, False))

    def test_after_a_panel_restart_the_step_file_still_knows(self):
        ky.write_step(4, 4, "x", "y")
        pk.PROGRESS.reset()
        reply, _ = self.do({"action": "resume"})
        self.assertEqual((reply["step"], reply["open"]), (4, True))

    def test_a_page_with_no_values_forgets_what_was_found_good(self):
        self.do({"action": "step", "step": 4})
        self.net.answer = DEVICE_OK
        self.do({"action": "verify", "value": CID})
        self.assertTrue(self.do({"action": "resume"})[0]["checks"]["client_id"])       # the page still holds it
        reply, _ = self.do({"action": "resume", "fresh": True})
        self.assertEqual(reply["checks"], {"key": None, "client_id": None, "secret": None})
        self.assertEqual(ky.read_step()["checks"], {"key": None, "client_id": None, "secret": None})
        self.assertEqual([i["s"] for i in self.ob.last["items"]], ["wait"] * 3)

    def test_a_save_forgets_everything(self):
        self.do({"action": "step", "step": 2})
        self.do({"action": "tick", "id": "start", "on": True})
        self.do(dict(GOOD, action="save"))
        reply, _ = self.do({"action": "resume"})
        self.assertEqual((reply["step"], reply["open"], reply["ticks"]), (1, False, []))


class Onboarding(Base):
    """The document for the TV (mediastick_onboarding, when it is there): its shape, its words, no value in it."""
    def setUp(self):
        super().setUp()
        self.kodi, self.net = FakeKodi(), Net()

    def do(self, body):
        return pk.handle(body, self.kodi, self.net.io())

    def test_each_step_has_the_shape_of_schema_one(self):
        for n in range(1, 5):
            self.do({"action": "step", "step": n})
            doc = self.ob.last
            check_doc(self, doc)
            self.assertEqual(doc["step"], n)
            self.assertEqual(doc["title"], {"tv": "Follow along on your phone", "phone": "Ключ Google для YouTube"})
            self.assertEqual(doc["steps"][n - 1]["tv"], pk.step_text(n)[0])
            self.assertEqual(doc["hint"]["tv"], pk.step_text(n)[1])
            self.assertEqual(doc["hint"]["phone"], steps.STEPS[n - 1]["hint"])

    def test_the_four_steps_in_both_languages(self):
        self.do({"action": "step", "step": 1})
        self.assertEqual([(s["id"], s["tv"], s["phone"]) for s in self.ob.last["steps"]], [
            ("project", "Project and API", "Проект и YouTube API"),
            ("consent", "Allow TV sign-in", "Разрешить вход с ТВ"),
            ("api_key", "API key", "Ключ API"),
            ("client", "TV client", "Клиент для ТВ")])

    def test_the_warning_and_the_chips_are_on_step_two_only(self):
        for n in (1, 3, 4):
            self.do({"action": "step", "step": n})
            self.assertNotIn("warn", self.ob.last)
            self.assertNotIn("chips", self.ob.last)
        self.do({"action": "step", "step": 2})
        self.assertIn("warn", self.ob.last)
        self.assertEqual(self.ob.last["warn"]["phone"], "Без публикации вход на ТВ слетает через 7 дней.")

    def test_the_time_fields(self):
        with mock.patch("time.time", return_value=1_900_000_000.7):
            self.do({"action": "step", "step": 1})
        self.assertEqual((self.ob.last["updated"], self.ob.last["expires"]), (1_900_000_000, 1_900_001_800))

    def test_finishing_or_closing_clears_it(self):
        self.do({"action": "step", "step": 4})
        self.do({"action": "step", "step": 0})
        self.assertEqual(self.ob.cleared, ["youtube"])
        self.do({"action": "step", "step": 4})
        self.do(dict(GOOD, action="save"))
        self.assertEqual(self.ob.cleared, ["youtube", "youtube"])

    def test_no_value_ever_reaches_the_library(self):
        self.net.answer = DEVICE_OK
        for body in ({"action": "step", "step": 4}, {"action": "verify", "value": KEY},
                     {"action": "verify", "value": CID}, {"action": "verify", "value": SECRET},
                     dict(GOOD, action="save")):
            self.do(body)
        self.assertTrue(self.ob.written)
        text = json.dumps(self.ob.written) + json.dumps(self.ob.cleared)
        no_leak(self, text)
        for _, doc in self.ob.written:
            check_doc(self, doc)

    def test_without_the_library_the_wizard_works_as_before(self):
        with mock.patch.object(pk, "ob_write", None), mock.patch.object(pk, "ob_clear", None):
            self.assertEqual(self.do({"action": "step", "step": 3})[1], 200)
            self.assertEqual(ky.read_step()["step"], 3)
            self.assertEqual(self.do({"action": "step", "step": 0})[1], 200)
            self.assertEqual(self.do(dict(GOOD, action="save"))[1], 200)

    def test_a_library_that_fails_does_not_fail_the_wizard(self):
        def boom(*a):
            raise RuntimeError("tv side broke " + KEY)
        with mock.patch.object(pk, "ob_write", boom), mock.patch.object(pk, "ob_clear", boom):
            self.assertEqual(self.do({"action": "step", "step": 2})[1], 200)
            self.assertEqual(self.do({"action": "tick", "id": "start", "on": True})[1], 200)
            self.assertEqual(self.do({"action": "step", "step": 0})[1], 200)

    def test_the_import_is_guarded(self):
        with open(os.path.join(LIB, "panel_ytkeys.py"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("try:\n    from mediastick_onboarding import write as ob_write, clear as ob_clear\n"
                      "except ImportError:", text)
        self.assertIn("ob_write = ob_clear = None", text)


# ---- the page ----------------------------------------------------------------------------------

class Page(unittest.TestCase):
    PAGE = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")

    def test_the_wizard_is_part_of_the_accounts_page(self):
        page = self.PAGE
        self.assertNotIn("@@", page)
        for text in ("Ключ Google для YouTube", "Сохранить и войти", "Вставить из буфера", "Сделано, дальше",
                     "Открыть страницу Google", "Или загрузить скачанный JSON клиента", "Добавить", "Нажмите ещё раз, чтобы удалить",
                     "Ключи заданы (…", "Заменить", "Проверить", "Сохранить без проверки",
                     "Не похоже ни на ключ, ни на ID, ни на secret", "Нужен один раз, минут пять.",
                     "Без публикации вход на ТВ слетает через 7 дней.",
                     "Интерфейс Google меняется. Если надписи отличаются, ищите похожие.", "Описание от Google",
                     "ждём · начинается с AIza", "ждём · начинается с GOCSPX-", "клиент для ТВ", "работает"):
            self.assertIn(text, page)
        self.assertNotIn("Ключи Google", page)                              # its row is on the maintenance page (test-panel-tabs)
        self.assertIn("accStart('youtube')", page)                  # saving goes on to the existing sign-in

    def script(self):
        return self.PAGE.split("// ---- the YouTube key wizard", 1)[1].split("</script>", 1)[0]

    def wizard(self):
        return json.loads(self.PAGE.split("const YK=", 1)[1].split(";\nlet ykStep", 1)[0])

    def test_the_colours_and_touch_targets_of_the_mockup(self):
        for colour in ("#1f2433", "#3a4258", "#2f6b4c", "#f2f3f5", "#f0c674"):
            self.assertIn(colour, self.PAGE)
        for token in ("background:var(--bg)", "background:var(--card)"):   # one palette: the page's own tokens, not #0f1115 / #1b1d28
            self.assertIn(token, self.PAGE)
        for gone in ("#0f1115", "#1b1d28"):
            self.assertNotIn(gone, self.PAGE)
        self.assertIn("min-height:52px", self.PAGE)                  # a step's header is a big button
        self.assertIn("min-height:44px", self.PAGE)

    def test_steps_are_real_buttons_with_labels_and_three_states(self):
        js = self.script()
        self.assertIn("accEl('button','acc-yk-sh')", js)
        self.assertIn("h.setAttribute('aria-expanded'", js)
        self.assertIn("cls=n<ykStep?'done':n===ykStep?'cur':'pend'", js)      # done folds to a check, pending is dimmed
        self.assertIn("cls==='done'?'✓'", js)
        self.assertIn("if(n!==ykStep)h.onclick=()=>{buzz();ykGo(n)}", js)     # any step can be opened again
        self.assertIn("aria-label", js)
        self.assertIn(".acc-yk-st.pend{opacity:.55}", self.PAGE)
        self.assertIn("ykBtn('Сделано, дальше'", js)
        self.assertIn("b.type='button'", js)

    def test_the_wizard_has_four_steps_with_a_checklist_on_the_second_and_paste_on_the_last_two(self):
        w = self.wizard()
        self.assertEqual(len(w["steps"]), 4)
        self.assertEqual([bool(s.get("ticks")) for s in w["steps"]], [False, True, False, False])
        self.assertEqual([bool(s.get("paste")) for s in w["steps"]], [False, False, True, True])
        self.assertEqual(len(w["ticks"]), 7)
        self.assertEqual(w["steps"][1]["warn"], "Без публикации вход на ТВ слетает через 7 дней.")
        self.assertEqual(w["patterns"], dict(steps.PATTERNS))
        self.assertEqual({f["name"]: f["secret"] for f in w["fields"]},
                         {"api_key": False, "client_id": False, "client_secret": True})
        self.assertEqual({f["name"]: f["max"] for f in w["fields"]},
                         {"api_key": 128, "client_id": 256, "client_secret": 128})

    def test_the_paste_box_reads_the_clipboard_or_offers_a_field_and_detects_the_kind(self):
        js = self.script()
        self.assertIn("navigator.clipboard.readText()", js)
        self.assertIn("if(ykFallback||!(navigator.clipboard&&navigator.clipboard.readText))", js)
        self.assertIn("ykPaste.type='text';ykPaste.autocomplete='off'", js)
        self.assertIn("ykBtn('Добавить'", js)
        self.assertIn("t.length>YK.paste_max*2", js)                          # capped before it is matched
        self.assertIn("t.length>YK.paste_max", js)
        self.assertIn("new RegExp(YK.patterns[k])", js)
        self.assertIn("YK.texts.unknown", js)
        self.assertIn("'AIza…'+v.slice(-4)", js)                              # only the last four of the key
        self.assertIn("v.slice(0,4)+'…apps.googleusercontent.com · клиент для ТВ'", js)
        self.assertIn("'GOCSPX-… · принят'", js)
        self.assertIn("ждём · начинается с GOCSPX-", js)

    def test_the_client_json_is_read_on_the_phone_and_never_sent_as_a_file(self):
        js = self.script()
        self.assertIn("f.type='file';f.accept='application/json,.json'", js)
        self.assertIn("file.size>YK.json_max", js)
        self.assertIn("JSON.parse(await file.text())", js)
        self.assertIn("j&&(j.installed||j.web)", js)
        self.assertNotIn("FormData", js)
        self.assertNotIn("fetch(", js)                                         # accCall is the one way out, with JSON text
        self.assertEqual(self.wizard()["json_max"], 16384)

    def test_the_values_are_sent_only_to_be_checked_or_saved_and_never_kept(self):
        js = self.script()
        self.assertEqual(js.count("action:'verify'"), 1)
        self.assertIn("accCall('ytkeys',{action:'verify',value:v})", js)
        self.assertIn("const body={action:'save'};Object.keys(ykVal).forEach(k=>{body[k]=ykVal[k]})", js)
        self.assertIn("ykWipe();ykSt={set:true", js)                           # emptied after a save
        self.assertIn("if(ykInfo[k].s==='bad')ykVal[k]=''", js)                # a refused value is dropped
        for word in ("sessionStorage", "document.cookie", "location.search", "location.hash", "history.", "console.log",
                     "indexedDB", "innerHTML", "navigator.sendBeacon"):
            self.assertNotIn(word, js, word)
        for line in js.splitlines():
            if "localStorage" in line:
                self.assertNotIn("ykVal", line)
                self.assertNotIn("ykPaste", line)
        self.assertNotIn("confirm(", js)

    def test_save_waits_for_three_good_values_and_then_signs_in(self):
        js = self.script()
        self.assertIn("Object.keys(ykInfo).every(k=>ykInfo[k]&&ykInfo[k].s==='ok')", js)
        self.assertIn("go.disabled=!all", js)
        self.assertIn("ykSay('');ykHide();buzz();accStart('youtube')", js)
        self.assertIn("ykBtn('Сохранить без проверки'", js)                    # only offered when Google could not be asked
        self.assertIn("'Проверить снова'", js)

    def test_no_browser_dialogs(self):
        for word in ("confirm(", "alert(", "prompt("):
            self.assertNotIn(word, self.PAGE)

    def test_the_page_finds_out_which_phone_it_is_on(self):
        js = self.script()
        self.assertIn("navigator.standalone===true", js)
        self.assertIn("matchMedia('(display-mode: standalone)')", js)
        self.assertIn("/iPhone|iPad|iPod/.test(ykUA)", js)
        self.assertIn("/Android/i.test(ykUA)", js)

    def test_each_link_is_a_real_new_tab_link_and_android_hands_it_to_the_browser_by_intent(self):
        js = self.script()
        self.assertIn("a.target='_blank';a.rel='noopener'", js)             # the way out for everyone but Android
        self.assertIn("if(!ykAndroid||!intent)return;", js)
        self.assertIn("location.href=intent;e.preventDefault()", js)         # one open, not two
        self.assertIn("s.intent.indexOf('intent://'+u.slice(8)+'#Intent;')===0", js)   # the page checks what the server built
        first = self.wizard()["steps"][0]
        self.assertEqual(first["intent"], pk.android_intent(first["url"]))
        self.assertEqual(first["safari"], "x-safari-" + first["url"])
        self.assertEqual(self.wizard()["doc"]["intent"], pk.android_intent(pk.DOC_URL))

    def test_beside_each_link_there_is_copy_and_on_an_iphone_open_in_safari(self):
        js = self.script()
        self.assertIn("copyText(u)", js)                         # the page's own copy (clipboard, else a hidden field)
        self.assertIn("YK.texts.copy", js)
        self.assertIn("ykIOS?ykSafari(s):null", js)
        self.assertIn("s.safari!=='x-safari-'+u", js)
        self.assertIn("a.href=s.safari", js)
        self.assertIn("b.append(...ykLinks(s))", js)
        self.assertIn("ykCopyVal(c.label,c.value)", js)          # step 2: our pages and the domain, to copy
        self.assertIn("YK.texts.open", js)
        self.assertIn("Скопировать ссылку", self.PAGE)
        self.assertIn("Открыть в Safari", self.PAGE)
        self.assertIn("Откроется в браузере. Вернитесь в пульт и нажмите «Сделано, дальше».", self.PAGE)
        self.assertEqual(self.PAGE.count("acc-yk-url"), 5)       # the styles (2), the link shown when copying fails, a value to copy

    def test_an_iphone_in_the_home_screen_app_is_told_where_the_links_open(self):
        js = self.script()
        self.assertIn("if(ykIOS&&ykStandalone)b.append(accEl('p','acc-yk-p',YK.texts.ios_standalone))", js)
        self.assertIn("откройте пульт в Safari, а не с экрана «Домой»", self.PAGE)
        self.assertIn("ykIOS&&ykStandalone?YK.texts.back:YK.texts.open", js)  # no "opens in the browser" where it does not

    def test_only_the_unfinished_flag_is_kept_on_the_phone_and_kept_safely(self):
        js = self.script()
        self.assertIn("localStorage.setItem('acc-yk-open','1')", js)
        self.assertEqual(js.count("localStorage.setItem"), 1)
        self.assertEqual(js.count("localStorage.setItem") + js.count("localStorage.getItem")
                         + js.count("localStorage.removeItem"), 3)
        self.assertNotIn("acc-yk-step", js)                      # the step is the panel's
        for line in js.splitlines():
            if "localStorage" in line:
                self.assertIn("try{", line)                      # private mode or a full store must not break the page
                self.assertIn("catch(e)", line)

    def test_the_wizard_comes_back_by_itself_until_it_is_closed_or_finished(self):
        js = self.script()
        self.assertIn("document.addEventListener('visibilitychange',ykResume)", js)
        self.assertIn("addEventListener('pageshow',ykResume)", js)
        self.assertIn("\nykResume();\n", js)                      # at load, too
        self.assertIn("if(ykPending()&&!ykHidden)ykOpen(true);else ykBanner()", js)
        self.assertIn("accCall('ytkeys',{action:'resume',fresh:!ykHas()})", js)   # to the step the panel kept
        self.assertIn("else ykGo(ykStep)", js)
        self.assertIn("function ykClose(){ykHidden=false;ykDrop();ykTell(0);ykHide()}", js)
        self.assertIn("$('acc-yk-x').onclick=ykClose", js)       # «Закрыть»
        self.assertIn("ykDrop();   // finished", js)             # saved: the flag goes
        self.assertIn("$('acc-yk-back').onclick=ykAside", js)    # a tap beside the sheet only puts it aside

    def test_an_unfinished_wizard_has_a_bar_on_the_accounts_tab(self):
        self.assertEqual(self.PAGE.count('id="acc-yk-cont"'), 1)
        self.assertIn("Продолжить настройку ключей (шаг %d из %d)", self.PAGE)
        js = self.script()
        self.assertIn("YK.texts.resume.replace('%d',ykStep).replace('%d',YK.steps.length)", js)
        self.assertIn("ykPending()&&$('acc-yk').classList.contains('hide')", js)
        section = self.PAGE.split('id="t-acc"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="acc-yk-cont"', section)

    def test_the_tv_is_told_the_step_when_it_changes_and_when_it_ends(self):
        js = self.script()
        self.assertIn("accCall('ytkeys',{action:'step',step:n})", js)
        self.assertIn("function ykGo(n){ykStep=n;ykKeep();ykTell(n);ykShow('step')}", js)
        self.assertEqual(js.count("ykTell(0)"), 2)               # closing, and keys found saved meanwhile
        self.assertIn("if(ykView==='step')ykTell(ykStep)", js)  # returning to the page says "still here"
        self.assertEqual(js.count("{action:'step',step:n}"), 1)     # no other body carries a step
        self.assertEqual(js.count("action:'step'"), 1)
        tell = js.split("function ykTell(n){", 1)[1].split("}\n", 1)[0]
        self.assertNotIn("ykVal", tell)
        self.assertNotIn(".value", tell)
        self.assertIn("{action:'tick',id:t.id,on}", js)

    def test_every_step_opens_a_page_the_whitelist_allows_in_a_new_tab(self):
        self.assertEqual(len(steps.STEPS), 4)
        for step in steps.STEPS:
            self.assertEqual(pa.safe_link(step["url"]), step["url"], step["url"])
            self.assertTrue(step["title"] and step["lines"] and step["button"] == "Открыть страницу Google")
        self.assertEqual(pa.safe_link(pk.DOC_URL), pk.DOC_URL)
        self.assertIn("a.target='_blank';a.rel='noopener'", self.PAGE)
        self.assertEqual([s["url"] for s in steps.STEPS], [
            "https://console.cloud.google.com/flows/enableapi?apiid=youtube.googleapis.com",
            "https://console.cloud.google.com/auth/overview",
            "https://console.cloud.google.com/apis/credentials",
            "https://console.cloud.google.com/auth/clients/create"])
        for host in ("console.cloud.google.com", "developers.google.com"):
            self.assertIn('"%s"' % host, self.PAGE)

    def test_the_steps_say_what_the_owner_needs_to_do(self):
        text = json.dumps(list(steps.STEPS) + list(pk.WIZARD["ticks"]), ensure_ascii=False)
        for word in ("Confirm project", "Enable API", "Next", "Enable", "TV", "Начать", "Внешняя", "Создать",
                     "Опубликовать приложение", "7 дней", "Ключ API", "Создать учётные данные",
                     "TVs and Limited Input devices", "Client ID"):
            self.assertIn(word, text)
        self.assertIn("Google покажет два шага: «Confirm project» → «Enable API». Если проекта нет — создайте его в "
                      "списке проектов сверху (имя любое, например TV), затем «Next» и «Enable».", steps.STEPS[0]["lines"])

    def test_every_id_is_prefixed(self):
        import re
        for i in re.findall(r'\bid="([^"]+)"', self.PAGE):
            self.assertTrue(i.startswith(("acc-", "t-acc")), i)

    def test_the_script_is_valid_javascript(self):
        import shutil
        import subprocess
        node = shutil.which("node")
        if not node:
            self.skipTest("no node on this machine")
        scripts = [s.split("</script>")[0] for s in self.PAGE.split("<script>")[1:]]
        self.assertEqual(len(scripts), 2)
        for script in scripts:
            path = os.path.join(TMP, "check.js")
            with open(path, "w", encoding="utf-8") as f:
                f.write(script)
            p = subprocess.run([node, "--check", path], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr)


# ---- the real panel ------------------------------------------------------------------------------

class Served(Base):
    @classmethod
    def setUpClass(cls):
        loader = importlib.machinery.SourceFileLoader("panel_under_test", PANEL)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        cls.panel = importlib.util.module_from_spec(spec)
        loader.exec_module(cls.panel)
        cls.kodi = FakeKodi()
        cls.panel.kodi = cls.kodi
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.panel.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        super().setUp()
        self.kodi.calls.clear()
        self.kodi.modes.clear()
        self.kodi.down = False
        self.net = Net()
        patch = mock.patch.object(pk, "REAL", self.net.io())
        patch.start()
        self.addCleanup(patch.stop)

    def req(self, method, path, body=None, headers=None, host=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or "localhost:%d" % self.port}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body) if body is not None else None)
        c.request(method, path, data, h)
        r = c.getresponse()
        text = r.read().decode("utf-8")
        c.close()
        return r.status, text

    def post(self, body=None, **kw):
        status, text = self.req("POST", "/api/accounts/ytkeys", body, {"X-Panel": "1"}, **kw)
        no_leak(self, text)
        return status, json.loads(text)

    def test_the_served_page_has_the_wizard_once(self):
        status, text = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertEqual(text.count('id="acc-yk"'), 1)
        self.assertEqual(text.count("const YK="), 1)
        self.assertNotIn("@@", text)

    def test_save_through_http_reaches_kodi_and_comes_back_without_values(self):
        status, d = self.post(dict(GOOD, action="save"))
        self.assertEqual((status, d["saved"], d["last4"]), (200, True, "WXYZ"))
        self.assertEqual(Fake.settings["youtube.api.secret"], SECRET)
        status, d = self.post({"action": "status"})
        self.assertEqual((status, d["set"], d["last4"]), (200, True, "WXYZ"))
        status, text = self.req("GET", "/api/accounts")                 # and the accounts list is as it was
        self.assertEqual(status, 200)
        no_leak(self, text)

    def test_verify_through_http_asks_google_and_answers_without_values(self):
        self.net.answer = DEVICE_OK
        status, d = self.post({"action": "verify", "value": CID})
        self.assertEqual((status, d["kind"], d["works"]), (200, "client_id", True))
        status, d = self.post({"action": "verify", "value": "nonsense"})
        self.assertEqual((status, d["ok"]), (400, False))
        self.assertEqual(d["check"], "unknown")                        # the refusal carries the verdict for the page

    def test_the_step_goes_through_http_into_a_file_for_the_tv_and_zero_removes_it(self):
        status, d = self.post({"action": "step", "step": 4})
        self.assertEqual((status, d), (200, {"ok": True, "step": 4}))
        self.assertEqual(stat.S_IMODE(os.stat(step_path()).st_mode), 0o644)
        got = ky.read_step()
        self.assertEqual((got["step"], got["total"], got["title"], got["hint"]), (4, 4, *pk.step_text(4)))
        status, d = self.post({"action": "step", "step": 3})
        self.assertEqual(ky.read_step()["step"], 3)
        status, d = self.post({"action": "step", "step": 0})
        self.assertEqual((status, d), (200, {"ok": True, "step": 0}))
        self.assertIsNone(ky.read_step())
        self.assertEqual(os.listdir(ky.DIR), [])
        self.assertEqual((self.kodi.calls, self.net.urls), ([], []))

    def test_ticks_and_resume_through_http(self):
        self.post({"action": "step", "step": 2})
        status, d = self.post({"action": "tick", "id": "start", "on": True})
        self.assertEqual((status, d["ticks"]), (200, ["start"]))
        status, d = self.post({"action": "resume"})
        self.assertEqual((status, d["step"], d["ticks"]), (200, 2, ["start"]))
        status, d = self.post({"action": "tick", "id": "nope", "on": True})
        self.assertEqual((status, d["ok"]), (400, False))

    def test_a_bad_step_through_http_is_a_400_and_the_file_stays(self):
        self.post({"action": "step", "step": 2})
        for bad in (5, -1, "2", None, True, 1.5):
            status, d = self.post({"action": "step", "step": bad})
            self.assertEqual((status, d["ok"]), (400, False), bad)
        status, _ = self.req("POST", "/api/accounts/ytkeys", None, {"X-Panel": "1"}, raw='{"action":"step","step":')
        self.assertIn(status, (400, 404))
        self.assertEqual(ky.read_step()["step"], 2)

    def test_the_step_route_is_guarded_like_the_others_and_carries_no_value(self):
        status, _ = self.req("POST", "/api/accounts/ytkeys", {"action": "step", "step": 3})      # no X-Panel
        self.assertEqual(status, 403)
        status, _ = self.req("POST", "/api/accounts/ytkeys", {"action": "step", "step": 3}, {"X-Panel": "1"}, host="evil.example")
        self.assertIn(status, (403, 421))
        self.assertFalse(os.path.exists(step_path()))
        status, d = self.post(dict(GOOD, action="step", step=4))
        self.assertEqual(status, 200)
        with open(step_path(), encoding="utf-8") as f:
            no_leak(self, f.read())

    def test_the_other_routes_are_guarded_too(self):
        for body in ({"action": "verify", "value": KEY}, {"action": "tick", "id": "start", "on": True}, {"action": "resume"}):
            status, _ = self.req("POST", "/api/accounts/ytkeys", body)
            self.assertEqual(status, 403, body)
            status, _ = self.req("POST", "/api/accounts/ytkeys", body, {"X-Panel": "1"}, host="evil.example")
            self.assertIn(status, (403, 421), body)
        self.assertEqual((self.net.urls, self.net.posts), ([], []))

    def test_a_saved_key_through_http_removes_the_step(self):
        self.post({"action": "step", "step": 4})
        status, d = self.post(dict(GOOD, action="save"))
        self.assertEqual((status, d["saved"]), (200, True))
        self.assertIsNone(ky.read_step())

    def test_clear_through_http(self):
        self.post(dict(GOOD, action="save"))
        status, d = self.post({"action": "clear"})
        self.assertEqual((status, d["ok"]), (200, True))
        self.assertFalse(self.post({"action": "status"})[1]["set"])

    def test_a_refusal_carries_the_verdict_for_the_page(self):
        self.net.answer = google_error(403, "accessNotConfigured")
        status, d = self.post(dict(GOOD, action="save"))
        self.assertEqual((status, d["ok"], d["check"]), (422, False, "disabled"))
        self.assertIn("YouTube Data API v3", d["error"])

    def test_the_route_is_guarded_like_the_others(self):
        body = dict(GOOD, action="save")
        status, _ = self.req("POST", "/api/accounts/ytkeys", body)               # no X-Panel
        self.assertEqual(status, 403)
        status, _ = self.req("POST", "/api/accounts/ytkeys", body, {"X-Panel": "1"}, host="evil.example")
        self.assertIn(status, (403, 421))
        status, _ = self.req("POST", "/api/accounts/ytkeys", body, {"X-Panel": "2"})
        self.assertEqual(status, 403)
        self.assertEqual((Fake.settings, self.kodi.calls, self.net.urls), ({}, [], []))

    def test_a_body_over_the_limit_does_nothing(self):
        raw = json.dumps(dict(GOOD, action="save", pad="x" * 9000))
        status, text = self.req("POST", "/api/accounts/ytkeys", None, {"X-Panel": "1"}, raw=raw)
        self.assertIn(status, (400, 404))
        self.assertEqual((Fake.settings, self.kodi.calls, self.net.urls), ({}, [], []))
        status, _ = self.req("POST", "/api/accounts/ytkeys", None, {"X-Panel": "1"}, raw="{nope")
        self.assertIn(status, (400, 404))

    def test_oversized_values_are_refused_by_field(self):
        for name, limit in ky.LIMITS.items():
            status, d = self.post(dict(GOOD, action="save", **{name: "k" * (limit + 1)}))
            self.assertEqual((status, d["ok"]), (400, False), name)
        self.assertEqual((Fake.settings, self.kodi.calls, self.net.urls), ({}, [], []))

    def test_a_kodi_that_is_down_is_a_calm_503_and_the_server_lives(self):
        self.kodi.down = True
        status, d = self.post(dict(GOOD, action="save"))
        self.assertEqual((status, d["ok"]), (503, False))
        self.assertEqual(os.listdir(ky.DIR), [])
        self.assertEqual(self.req("GET", "/api/accounts")[0], 200)


if __name__ == "__main__":
    unittest.main(verbosity=1)
