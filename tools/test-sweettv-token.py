#!/usr/bin/env python3
"""Offline test of how the SWEET.TV add-on (our overlay) gets its channel list right after a sign-in (no Kodi, no device,
no network): python3 tools/test-sweettv-token.py

Upstream builds `helper = Helper(...)` once, when the module is imported, and the Helper reads the bearer and builds its
request headers right then. The sign-in runs in a process whose helper was built before the new bearer was stored, and the
add-on's service lives for days: both asked SWEET.TV for the channel list without (or with an old) authorization. The
overlay reads the bearer again before that request; and the service asks again after a minute when a fetch failed."""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in device/skin-overlay

import json  # noqa: E402
import os  # noqa: E402
import runpy  # noqa: E402
import tempfile  # noqa: E402
import time  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402
from unittest import mock  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
ADDON = os.path.join(ROOT, "device", "skin-overlay", "plugin.video.sweettv")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
sys.path.insert(0, LIB)

import mediastick_signin as ms  # noqa: E402

WARNING, ERROR, DEBUG, INFO = 2, 1, 0, 3
TOKEN = "TOKEN-VALUE-NEVER-LOGGED"
BODY = "BODY-TEXT-NEVER-LOGGED"
CHANNELS = {"status": "OK", "categories": [{"id": 1, "caption": "News"}],
            "list": [{"id": 7, "name": "One", "icon_url": "u", "available": True, "category": [1]}]}


class Settings:
    """Kodi settings of the add-on: one store for every process, whichever Helper reads it."""
    values = {}


class Reply:
    """What request_sess(..., result=False) gives back: a requests response."""
    def __init__(self, body):
        self.body = body
        self.content = json.dumps(body).encode()

    def json(self):
        return self.body


class StaleHelper:
    """The add-on Helper as far as this is concerned: the bearer is read and the headers are built once, in __init__.
    The API answers the channel list to the bearer it knows and with an error status to anything else."""
    auth_url, check_auth_url = "https://sweet/auth", "https://sweet/check"
    base_api_url, channelListPath, countryCode = "https://sweet/{}", "/tmp/channelList.json", "ua"
    addon_name = "plugin.video.sweettv"
    calls = []                                        # (url, copy of the headers) of every request
    api_answer = None                                 # None: the real one (by the bearer), else a fixed reply

    def __init__(self, base_url=None, handle=None):
        self.bearer = self.get_setting("bearer")
        self.headers = {"user-agent": "ua"}
        if self.bearer:
            self.headers.update({"authorization": self.bearer})
        self.json_data = {}

    def get_setting(self, key):
        value = Settings.values.get(key, "")
        return {"true": True, "false": False}.get(value, value)    # as the real one does

    def set_setting(self, key, value):
        Settings.values[key] = value

    def notification(self, *a):
        pass

    def refresh(self):
        pass

    def request_sess(self, url, method="get", headers=None, **kw):
        StaleHelper.calls.append((url, dict(headers or {})))
        if url == self.auth_url:
            return {"result": "OK", "auth_code": "12345"}
        if url == self.check_auth_url:
            return {"result": "COMPLETED", "access_token": TOKEN, "refresh_token": "ref", "expires_in": 3600}
        if StaleHelper.api_answer is not None:
            return StaleHelper.api_answer
        if (headers or {}).get("authorization") == "Bearer " + Settings.values.get("valid", TOKEN):
            return Reply(CHANNELS)
        return Reply({"status": "UNAUTHORIZED"})


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def load_sweettv(with_library=True, bearer_at_import="", helper_class=None, xbmcplugin=None, translate=None):
    """The overlay, imported (so helper is built) while the settings hold bearer_at_import. helper_class stands in for
    the add-on's Helper, xbmcplugin for Kodi's, translate for xbmcvfs.translatePath."""
    Settings.values = {"bearer": bearer_at_import, "logged": True} if bearer_at_import else {}
    StaleHelper.calls, StaleHelper.api_answer = [], None
    logs, written = [], []
    clock = Clock()

    class Plugin:
        def route(self, path):
            return lambda fn: fn

    vfs = types.SimpleNamespace(
        translatePath=translate or (lambda p: "/tmp/"), delete=lambda path: None,
        File=lambda path, mode: type("F", (), {"write": lambda self, data: written.append(path),
                                               "close": lambda self: None})())
    parse = types.ModuleType("six.moves.urllib.parse")
    parse.urlencode = lambda *a, **k: ""
    package = types.ModuleType("sweettv_addon")
    package.__path__ = []
    helper_module = types.ModuleType("sweettv_addon.helper")
    helper_module.Helper = helper_class or StaleHelper
    stubs = {
        "routing": types.SimpleNamespace(Plugin=Plugin),
        "urllib3": types.SimpleNamespace(disable_warnings=lambda: None),
        "xbmc": types.SimpleNamespace(log=lambda msg, level=0: logs.append((level, msg)), LOGDEBUG=DEBUG,
                                      LOGERROR=ERROR, LOGWARNING=WARNING, LOGINFO=INFO),
        "xbmcgui": types.SimpleNamespace(WindowDialog=object, ListItem=object, Dialog=object),
        "xbmcplugin": xbmcplugin or types.SimpleNamespace(), "xbmcvfs": vfs,
        "six": types.ModuleType("six"), "six.moves": types.ModuleType("six.moves"),
        "six.moves.urllib": types.ModuleType("six.moves.urllib"), "six.moves.urllib.parse": parse,
        "sweettv_addon": package, "sweettv_addon.helper": helper_module,
        "mediastick_signin": ms if with_library else None,
    }
    path = os.path.join(ADDON, "resources", "lib", "sweettv.py")
    import importlib.util
    spec = importlib.util.spec_from_file_location("sweettv_addon.sweettv", path)
    sweet = importlib.util.module_from_spec(spec)
    with mock.patch.dict(sys.modules, stubs), mock.patch.object(sys, "argv", ["plugin://plugin.video.sweettv/", "1"]):
        sys.modules[spec.name] = sweet
        spec.loader.exec_module(sweet)
    sweet.time = types.SimpleNamespace(time=clock.time, sleep=clock.sleep, strftime=time.strftime, localtime=time.localtime)
    sweet.logs, sweet.written = logs, written
    return sweet


def channel_requests():
    return [h for url, h in StaleHelper.calls if url.endswith("TvService/GetChannels.json")]


class FreshBearer(unittest.TestCase):
    def setUp(self):
        ms.begin("sweettv")

    def test_a_helper_built_before_the_sign_in_sends_the_new_bearer_after_it(self):
        """The bug: the login ran in the process whose helper was built without a bearer."""
        sweet = load_sweettv()
        self.assertNotIn("authorization", sweet.helper.headers)
        sweet.login()
        self.assertEqual(Settings.values["logged"], "true")
        sent = channel_requests()
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0].get("authorization"), "Bearer " + TOKEN)
        self.assertEqual(sweet.written, ["/tmp/channelList.json"])                 # the list was saved: the TV screen has it
        self.assertEqual([m for lvl, m in sweet.logs if lvl in (ERROR, WARNING)], [])
        self.assertEqual(sweet.helper.bearer, "Bearer " + TOKEN)

    def test_the_same_without_the_media_stick_library(self):
        sweet = load_sweettv(with_library=False)
        self.assertIsNone(sweet._ms)
        Settings.values.update(bearer="Bearer " + TOKEN, logged=True)
        self.assertEqual(sweet.refreshChannelList()["status"], "OK")
        self.assertEqual(channel_requests()[0].get("authorization"), "Bearer " + TOKEN)

    def test_a_bearer_that_changed_since_the_helper_was_built_is_the_one_sent(self):
        """The service: built at Kodi start with the old bearer, then a new sign-in stored another one."""
        sweet = load_sweettv(bearer_at_import="Bearer old")
        self.assertEqual(sweet.helper.headers["authorization"], "Bearer old")
        Settings.values["bearer"] = "Bearer " + TOKEN
        self.assertEqual(sweet.refreshChannelList()["status"], "OK")
        self.assertEqual(channel_requests()[0]["authorization"], "Bearer " + TOKEN)
        self.assertEqual(sweet.helper.headers["authorization"], "Bearer " + TOKEN)

    def test_a_bearer_that_is_gone_is_not_sent(self):
        sweet = load_sweettv(bearer_at_import="Bearer " + TOKEN)
        Settings.values["bearer"] = ""                                             # signed out, still marked as logged in
        sweet.refreshChannelList()
        self.assertNotIn("authorization", channel_requests()[0])

    def test_other_headers_and_the_alias_the_login_holds_are_kept(self):
        sweet = load_sweettv()
        alias = sweet.helper.headers                                              # the login does: headers = helper.headers
        Settings.values.update(bearer="Bearer " + TOKEN, logged=True)
        sweet.refreshChannelList()
        self.assertIs(sweet.helper.headers, alias)
        self.assertEqual(alias["user-agent"], "ua")

    def test_not_logged_in_asks_for_nothing(self):
        sweet = load_sweettv()
        self.assertIsNone(sweet.refreshChannelList())
        self.assertEqual(channel_requests(), [])


class FailureIsVisible(unittest.TestCase):
    def warnings(self, sweet):
        return [m for lvl, m in sweet.logs if lvl == WARNING]

    def test_a_refused_request_logs_a_warning_with_the_status_and_nothing_secret(self):
        sweet = load_sweettv(bearer_at_import="Bearer " + TOKEN)
        StaleHelper.api_answer = Reply({"status": "UNAUTHORIZED", "detail": BODY, "access_token": TOKEN})
        reply = sweet.refreshChannelList()
        self.assertEqual(reply["status"], "UNAUTHORIZED")                          # what the service reads
        warnings = self.warnings(sweet)
        self.assertEqual(len(warnings), 1)
        self.assertIn("status='UNAUTHORIZED'", warnings[0])
        self.assertIn("authorization sent: True", warnings[0])
        for lvl, message in sweet.logs:
            if lvl in (WARNING, ERROR):
                self.assertNotIn(TOKEN, message)
                self.assertNotIn(BODY, message)
        self.assertEqual(sweet.written, [])

    def test_a_request_that_was_sent_without_a_bearer_says_so(self):
        sweet = load_sweettv()
        Settings.values["logged"] = True
        sweet.refreshChannelList()
        self.assertEqual(len(self.warnings(sweet)), 1)
        self.assertIn("status='UNAUTHORIZED'", self.warnings(sweet)[0])
        self.assertIn("authorization sent: False", self.warnings(sweet)[0])

    def test_no_answer_at_all_is_a_warning_too(self):
        sweet = load_sweettv(bearer_at_import="Bearer " + TOKEN)
        sweet.helper.request_sess = lambda *a, **k: None                           # what the helper gives on a network error
        self.assertIsNone(sweet.refreshChannelList())
        self.assertEqual(len(self.warnings(sweet)), 1)
        self.assertIn("no answer", self.warnings(sweet)[0])
        self.assertIn("authorization sent: True", self.warnings(sweet)[0])

    def test_the_status_is_cut_and_a_strange_one_is_named_by_type(self):
        sweet = load_sweettv()
        self.assertEqual(sweet._ms_status({"status": "X" * 100}), repr("X" * 100)[:40])
        self.assertEqual(sweet._ms_status({"status": {"a": TOKEN}}), "dict")
        self.assertEqual(sweet._ms_status({}), "NoneType")
        self.assertEqual(sweet._ms_status([TOKEN]), "NoneType")


class ServiceRetry(unittest.TestCase):
    """service.py: the channel list is fetched every 15 minutes; one that failed is asked for again on the next pass."""

    def run_service(self, answers, passes):
        """Run the service loop for some minutes; answers are what refreshChannelList gives, one per call (the last
        one repeats). Returns the minutes, counted from the start, at which it asked."""
        clock, asked = Clock(), []
        start = clock.now

        class Monitor:
            n = 0

            def abortRequested(self):
                return False

            def waitForAbort(self, seconds):
                clock.sleep(seconds)
                Monitor.n += 1
                return Monitor.n >= passes

        def refresh():
            asked.append(round((clock.now - start) / 60))
            return answers[min(len(asked) - 1, len(answers) - 1)]

        lib = types.ModuleType("resources.lib.sweettv")
        lib.refreshToken, lib.initSettings, lib.refreshChannelList = (lambda: True), (lambda: None), refresh
        stubs = {"xbmc": types.SimpleNamespace(Monitor=Monitor, Player=type("Player", (), {}), log=lambda *a: None,
                                               LOGERROR=1, LOGWARNING=2),
                 "xbmcgui": types.SimpleNamespace(),
                 "resources": types.ModuleType("resources"), "resources.lib": types.ModuleType("resources.lib"),
                 "resources.lib.helper": types.SimpleNamespace(Helper=lambda: object()), "resources.lib.sweettv": lib}
        with mock.patch.dict(sys.modules, stubs), mock.patch.object(time, "time", clock.time):
            runpy.run_path(os.path.join(ADDON, "service.py"), run_name="__main__")
        return asked

    def test_a_list_that_loads_is_asked_for_every_quarter_of_an_hour(self):
        self.assertEqual(self.run_service([CHANNELS], 50), [0, 16, 32, 48])

    def test_a_failed_fetch_is_asked_for_again_after_a_minute_until_it_works(self):
        failed = {"status": "UNAUTHORIZED"}
        self.assertEqual(self.run_service([failed, failed, CHANNELS], 20), [0, 1, 2, 18])
        self.assertEqual(self.run_service([None, CHANNELS], 20), [0, 1, 17])         # no answer at all counts as failed

    def test_a_list_that_never_loads_is_not_asked_for_every_minute_forever(self):
        asked = self.run_service([{"status": "NO"}], 40)
        self.assertEqual(asked[:6], [0, 1, 2, 3, 4, 5])                              # the first try and five quick ones
        self.assertEqual(asked[6:], [21, 37])                                         # then back to the quarter of an hour

    def test_one_success_gives_the_quick_retries_back(self):
        failed = {"status": "NO"}
        asked = self.run_service([failed] * 6 + [CHANNELS, failed], 40)
        self.assertEqual(asked[6:], [21, 37, 38, 39])


if __name__ == "__main__":
    unittest.main()
