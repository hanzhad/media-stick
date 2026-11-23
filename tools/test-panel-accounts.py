#!/usr/bin/env python3
"""Offline test of the Accounts part of the panel (no Kodi, no device):
python3 tools/test-panel-accounts.py

First the module (validation, what each action sends to Kodi, the link whitelist, no secret in a
reply), then the real `panel` served on a free local port with a fake Kodi."""
import http.client
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"   # never ask Google from a test
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

import mediastick_signin as ms  # noqa: E402
import panel_accounts as pa  # noqa: E402

SECRET = "ya29.SECRET-ACCESS|1//SECRET-REFRESH|SECRET-VR"


def put(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def yt(users, current=0):
    put(os.path.join(ms.USERDATA, "plugin.video.youtube", "access_manager.json"),
        json.dumps({"access_manager": {"current_user": current, "users": users}}))


class FakeKodi:
    """The panel's kodi(): remembers the calls; `down` makes it behave like a Kodi that is off."""
    def __init__(self):
        self.calls, self.down, self.result = [], False, "OK"

    def __call__(self, method, params=None, timeout=3):
        if self.down:
            raise ConnectionRefusedError("kodi is off")
        if method.startswith("Player."):   # the panel's own status polls
            return []
        if method in ("GUI.GetProperties", "XBMC.GetInfoLabels"):   # and its keyboard-card poll
            return {}
        self.calls.append((method, params))
        return self.result


class AddingKodi(FakeKodi):
    """A Kodi whose launcher adds and switches YouTube profiles the way the add-on does."""
    switch_to = None

    def __call__(self, method, params=None, timeout=3):
        out = super().__call__(method, params, timeout)
        args = (params or {}).get("params") or []
        if args[:2] in (["accounts", "add"], ["accounts", "switch"]):
            path = os.path.join(ms.USERDATA, "plugin.video.youtube", "access_manager.json")
            with open(path, encoding="utf-8") as f:
                m = json.load(f)["access_manager"]
            if args[1] == "add":
                uid = str(max([int(u) for u in m["users"]] + [-1]) + 1)
                m["users"][uid] = {"name": args[3], "refresh_token": ""}
            else:
                uid = args[3]
            m["current_user"] = uid
            put(path, json.dumps({"access_manager": m}))
        return out


def reset():
    for s in ms.SERVICES:
        ms.begin(s)
        ms.clear_mode(s)
    for rel in ("plugin.video.youtube/access_manager.json", "plugin.video.sweettv/settings.xml"):
        try:
            os.unlink(os.path.join(ms.USERDATA, rel))
        except OSError:
            pass


class Validation(unittest.TestCase):
    def test_link_whitelist(self):
        good = ["https://www.youtube.com/activate?user_code=ABC-DEF-GHI", "https://youtube.com/activate",
                "https://accounts.google.com/o/oauth2/device/usercode", "https://sweet.tv/addDevice?connectCode=123",
                "https://www.sweet.tv/x", "https://www.youtube.com:443/activate", "https://www.google.com/device",
                "https://www.google.com/device?user_code=ABC-DEF-GHI"]
        bad = ["http://www.youtube.com/activate", "https://evil.example/activate", "https://youtube.com.evil.example/x",
               "https://www.youtube.com@evil.example/x", "https://evil.example@www.youtube.com/x",
               "https://www.youtube.com:8443/x", "https://google.com/device", "https://www.google.com.evil.example/device",
               "javascript:alert(1)", "data:text/html,x", "//www.youtube.com/x",
               "https://www.youtube.com/a b", "https://www.youtube.com/а", "https://www.youtube.com/x\n",
               "", None, 5, "https://" + "a" * 600 + ".youtube.com/"]
        for u in good:
            self.assertEqual(pa.safe_link(u), u, u)
        for u in bad:
            self.assertEqual(pa.safe_link(u), "", repr(u))

    def test_service(self):
        self.assertEqual(pa.clean_service("youtube"), "youtube")
        for v in ("netflix", "", None, 1, ["youtube"], "YouTube", "youtube "):
            with self.assertRaises(pa.Refused):
                pa.clean_service(v)

    def test_profile_id_is_digits_only(self):
        self.assertEqual(pa.clean_profile_id("12"), "12")
        self.assertEqual(pa.clean_profile_id(3), "3")
        for v in ("", "-1", "1a", "1 2", "1234567", "٣", None, True, 1.5, ["1"], "../1"):
            with self.assertRaises(pa.Refused, msg=repr(v)):
                pa.clean_profile_id(v)

    def test_name_is_one_to_32_characters_without_control_characters(self):
        self.assertEqual(pa.clean_name("  Дети  "), "Дети")
        self.assertEqual(pa.clean_name("x" * 32), "x" * 32)
        self.assertEqual(pa.clean_name("Мама и папа 🙂"), "Мама и папа 🙂")
        for v in ("", "   ", "x" * 33, "a\nb", "a\x00b", "a\tb", "a b", "a\x7fb", None, 5, ["a"]):
            with self.assertRaises(pa.Refused, msg=repr(v)):
                pa.clean_name(v)

    def test_a_state_is_cleaned_before_the_page_sees_it(self):
        s = {"service": "youtube", "name": "YouTube", "state": "waiting", "code": "ABC-DEF-GHI",
             "url": "https://www.youtube.com/activate", "link": "https://evil.example/?c=ABC-DEF-GHI", "step": 2,
             "steps": 4, "left": 300, "updated": 5, "token": "SECRET", "extra": {"a": 1}}
        out = pa.public_signin(s)
        self.assertEqual(out["link"], "")
        self.assertEqual(out["url"], "https://www.youtube.com/activate")
        self.assertEqual((out["code"], out["step"], out["steps"]), ("ABC-DEF-GHI", 2, 4))
        self.assertNotIn("token", out)
        self.assertNotIn("extra", out)
        weird = pa.public_signin(dict(s, code="<script>", link="https://www.youtube.com/activate?user_code=x", step="x"))
        self.assertEqual((weird["code"], weird["link"], weird["step"]), ("", "", 1))
        self.assertIsNone(pa.public_signin(None))
        self.assertEqual(out["mode"], "normal")

    def test_a_partner_state_reaches_the_page_without_the_link_that_the_qr_holds(self):
        s = {"service": "sweettv", "name": "SWEET.TV", "state": "waiting", "mode": "partner", "code": "12345",
             "url": "https://sweet.tv/addDevice", "link": "https://sweet.tv/addDevice?connectCode=12345", "step": 1,
             "steps": 1, "left": 21000, "updated": 5}
        out = pa.public_signin(s)
        self.assertEqual((out["mode"], out["code"], out["left"]), ("partner", "12345", 21000))
        self.assertEqual((out["link"], out["url"]), ("", ""))
        normal = pa.public_signin(dict(s, mode="normal"))
        self.assertEqual(normal["link"], s["link"])
        self.assertEqual(pa.public_signin(dict(s, mode="admin"))["mode"], "normal")
        self.assertEqual(pa.public_signin({k: v for k, v in s.items() if k != "mode"})["mode"], "normal")

    def test_the_mode_of_a_sign_in(self):
        for value in (None, "", "normal"):
            self.assertEqual(pa.clean_mode(value, "sweettv"), "normal")
            self.assertEqual(pa.clean_mode(value, "youtube"), "normal")
        self.assertEqual(pa.clean_mode("partner", "sweettv"), "partner")
        for value, service in (("partner", "youtube"), ("Partner", "sweettv"), ("admin", "sweettv"), (1, "sweettv"),
                               (["partner"], "sweettv"), (True, "sweettv")):
            with self.assertRaises(pa.Refused, msg=repr((value, service))):
                pa.clean_mode(value, service)


class Reading(unittest.TestCase):
    def setUp(self):
        reset()

    def test_accounts_and_waiting(self):
        yt({"0": {"name": "Основной", "refresh_token": SECRET + "|X|Y"}, "1": {"name": "Дети", "refresh_token": "a||"}}, 1)
        put(os.path.join(ms.USERDATA, "plugin.video.sweettv", "settings.xml"), '<settings><setting id="logged">true</setting></settings>')
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI", url="https://www.youtube.com/activate", step=2, steps=4)
        v = pa.view()
        by = {a["service"]: a for a in v["accounts"]}
        self.assertEqual([p["tokens"] for p in by["youtube"]["profiles"]], [4, 1])
        self.assertEqual([p["current"] for p in by["youtube"]["profiles"]], [False, True])
        self.assertTrue(by["sweettv"]["signed_in"])
        self.assertEqual([w["service"] for w in v["waiting"]], ["youtube"])
        self.assertEqual(v["waiting"][0]["link"], "https://www.youtube.com/activate?user_code=ABC-DEF-GHI")
        self.assertEqual(by["youtube"]["signin"]["step"], 2)

    def test_a_profile_says_whether_its_google_account_has_a_channel(self):
        yt({"0": {"name": "Основной", "refresh_token": SECRET}, "1": {"name": "Дети", "refresh_token": ""}})
        answers = {"0": {"state": "no", "title": ""}}
        with mock.patch.object(pa.ytchannel, "peek", side_effect=lambda pid: answers[pid]) as peek:
            prof = {p["id"]: p for p in pa.view()["accounts"][0]["profiles"]}
            self.assertEqual((prof["0"]["channel"], prof["0"]["channel_title"]), ("no", ""))
            self.assertEqual(prof["1"]["channel"], "unknown")   # not signed in: Google is not asked
            self.assertEqual([c.args for c in peek.call_args_list], [("0",)])
            answers["0"] = {"state": "yes", "title": "Мой\x07 канал " + "x" * 80}
            p0 = pa.view()["accounts"][0]["profiles"][0]
            self.assertEqual(p0["channel"], "yes")
            self.assertEqual(p0["channel_title"], ("Мой канал " + "x" * 80)[:64])
            answers["0"] = {"state": "maybe", "title": "x"}
            self.assertEqual(pa.view()["accounts"][0]["profiles"][0]["channel"], "unknown")
        with mock.patch.object(pa.ytchannel, "peek", side_effect=RuntimeError("boom")):
            self.assertEqual(pa.view()["accounts"][0]["profiles"][0]["channel"], "unknown")
        self.assertEqual(pa.view()["accounts"][1]["profiles"], [])

    def test_the_page_explains_a_missing_channel(self):
        page = pa.inject("<nav>@@ACC_NAV@@</nav>@@ACC_SECTION@@<body>@@ACC_TAIL@@</body>")
        self.assertIn("нет канала YouTube", page)
        self.assertIn("«Создать канал»", page)
        self.assertIn("«Войти другим аккаунтом»", page)
        self.assertIn("accLabel", page)
        self.assertIn("ch.textContent=", page)   # the title is text, never markup
        self.assertNotIn("ch.innerHTML", page)

    def test_no_secret_in_any_reply(self):
        yt({"0": {"name": "Основной", "refresh_token": SECRET, "access_token": SECRET, "client_secret": SECRET}})
        put(os.path.join(ms.USERDATA, "plugin.video.sweettv", "settings.xml"),
            '<settings><setting id="logged">true</setting><setting id="token">SECRET-SWEET</setting></settings>')
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI")
        text = json.dumps(pa.view()) + json.dumps(pa.with_signin({"kodi": "up"}))
        self.assertNotIn("SECRET", text)

    def test_with_signin_lists_names_and_leaves_the_cached_status_alone(self):
        cached = {"kodi": "up"}
        self.assertEqual(pa.with_signin(cached), {"kodi": "up", "signin": []})
        ms.publish("sweettv", "waiting", code="12345")
        ms.publish("youtube", "done")
        self.assertEqual(pa.with_signin(cached)["signin"], ["sweettv"])
        self.assertNotIn("signin", cached)

    def test_nothing_signed_in_and_no_files_is_not_an_error(self):
        v = pa.view()
        self.assertEqual([a["signed_in"] for a in v["accounts"]], [False, False])
        self.assertEqual(v["waiting"], [])


class Actions(unittest.TestCase):
    def setUp(self):
        reset()
        self.k = FakeKodi()
        yt({"0": {"name": "Основной", "refresh_token": "a|b|c|d"}, "2": {"name": "Дети", "refresh_token": ""}})

    def post(self, action, body):
        return pa.post(pa.PREFIX + action, body, self.k)

    def test_each_action_sends_the_launcher_exactly_its_vocabulary(self):
        cases = [("signin", {"service": "youtube"}, ["accounts", "signin", "youtube"]),
                 ("signin", {"service": "sweettv"}, ["accounts", "signin", "sweettv"]),
                 ("switch", {"service": "youtube", "id": "2"}, ["accounts", "switch", "youtube", "2"]),
                 ("add", {"service": "youtube", "name": " Гости "}, ["accounts", "add", "youtube", "Гости"]),
                 ("signout", {"service": "sweettv"}, ["accounts", "signout", "sweettv"])]
        for action, body, params in cases:
            self.k.calls.clear()
            reply, code = self.post(action, body)
            self.assertEqual((code, reply), (200, {"ok": True}), action)
            self.assertEqual(self.k.calls, [("Addons.ExecuteAddon", {"addonid": "script.media-stick.home", "params": params})])

    def test_a_partner_sign_in_asks_for_the_mode_in_a_file_and_sends_the_launcher_the_same_words_as_ever(self):
        reply, code = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual((code, reply), (200, {"ok": True}))
        self.assertEqual(self.k.calls, [("Addons.ExecuteAddon", {"addonid": "script.media-stick.home",
                                                                  "params": ["accounts", "signin", "sweettv"]})])
        self.assertEqual(ms.requested_mode("sweettv"), "partner")
        self.assertEqual(ms.requested_mode("youtube"), "normal")

    def test_a_plain_sign_in_withdraws_a_partner_request_nobody_took(self):
        ms.request_mode("sweettv", "partner")
        for body in ({"service": "sweettv"}, {"service": "sweettv", "mode": "normal"}):
            ms.request_mode("sweettv", "partner")
            self.assertEqual(self.post("signin", body)[1], 200)
            self.assertEqual(ms.requested_mode("sweettv"), "normal", body)

    def test_the_partner_mode_is_for_sweettv_only_and_only_known_modes_pass(self):
        for body in ({"service": "youtube", "mode": "partner"}, {"service": "sweettv", "mode": "admin"},
                     {"service": "sweettv", "mode": 1}, {"service": "sweettv", "mode": ["partner"]}):
            reply, code = self.post("signin", body)
            self.assertEqual((code, reply["ok"]), (400, False), body)
        self.assertEqual(self.k.calls, [])
        self.assertEqual(ms.requested_mode("sweettv"), "normal")
        self.assertEqual(ms.requested_mode("youtube"), "normal")
        self.assertFalse(os.path.exists(os.path.join(ms.DIR, "youtube.mode")))

    def test_a_partner_sign_in_that_is_already_waiting_is_left_alone(self):
        ms.publish("sweettv", "waiting", code="12345")
        reply, code = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual((code, reply.get("already")), (200, True))
        self.assertEqual((self.k.calls, ms.requested_mode("sweettv")), ([], "normal"))

    def test_a_kodi_that_is_down_leaves_no_partner_request_behind(self):
        self.k.down = True
        reply, code = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual((code, reply["error"]), (503, pa.KODI_DOWN))
        self.assertEqual(ms.requested_mode("sweettv"), "normal")        # or the next, plain sign-in would become one

    def test_a_request_that_cannot_be_written_is_an_error_not_a_quiet_normal_sign_in(self):
        with mock.patch.object(ms, "request_mode", return_value=False):
            reply, code = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual((code, reply["ok"]), (500, False))
        self.assertEqual(self.k.calls, [])

    def test_cancel_is_a_file_not_a_kodi_call(self):
        self.k.down = True   # works with Kodi off
        reply, code = self.post("cancel", {"service": "youtube"})
        self.assertEqual((code, reply), (200, {"ok": True}))
        self.assertTrue(ms.cancel_requested("youtube"))
        self.assertFalse(ms.cancel_requested("sweettv"))
        self.assertEqual(self.k.calls, [])

    def test_signin_is_not_started_twice(self):
        ms.publish("youtube", "waiting", code="AAA")
        reply, code = self.post("signin", {"service": "youtube"})
        self.assertEqual((code, reply.get("already")), (200, True))
        self.assertEqual(self.k.calls, [])

    def test_bad_input_is_refused_and_kodi_hears_nothing(self):
        bad = [("signin", {"service": "netflix"}), ("signin", {}), ("signout", {"service": ["youtube"]}),
               ("cancel", {"service": "x"}), ("switch", {"service": "youtube", "id": "x"}),
               ("switch", {"service": "youtube", "id": "../2"}), ("switch", {"service": "sweettv", "id": "2"}),
               ("add", {"service": "youtube", "name": ""}), ("add", {"service": "youtube", "name": "a\nb"}),
               ("add", {"service": "youtube", "name": "x" * 33}), ("add", {"service": "sweettv", "name": "a"}),
               ("signin", [1]), ("signin", "youtube"), ("signin", None)]
        for action, body in bad:
            reply, code = self.post(action, body)
            self.assertEqual(code, 400, (action, body))
            self.assertFalse(reply["ok"])
            self.assertTrue(reply["error"])
        self.assertEqual(self.k.calls, [])

    def test_switch_to_a_profile_that_does_not_exist(self):
        reply, code = self.post("switch", {"service": "youtube", "id": "9"})
        self.assertEqual(code, 404)
        self.assertEqual(self.k.calls, [])

    def test_another_account_adds_a_profile_switches_to_it_and_starts_its_sign_in(self):
        yt({"0": {"name": "Основной", "refresh_token": "a|b|c"}}, 0)
        k = AddingKodi()
        reply, code = pa.post(pa.PREFIX + "another", {"service": "youtube"}, k)
        self.assertEqual((code, reply.get("ok"), reply.get("previous")), (200, True, "0"), reply)
        self.assertEqual([c[1]["params"] for c in k.calls],
                         [["accounts", "add", "youtube", "Аккаунт 2"], ["accounts", "signin", "youtube"]])

    def test_another_account_uses_an_empty_profile_before_adding_one(self):
        k = AddingKodi()
        yt({"0": {"name": "Основной", "refresh_token": "a|b"}, "1": {"name": "Аккаунт 2", "refresh_token": ""}}, 0)
        k.switch_to = "1"
        reply, code = pa.post(pa.PREFIX + "another", {"service": "youtube"}, k)
        self.assertEqual((code, reply["previous"]), (200, "0"), reply)
        self.assertEqual([c[1]["params"][:2] for c in k.calls], [["accounts", "switch"], ["accounts", "signin"]])
        reset()
        k = AddingKodi()
        yt({"0": {"name": "Основной", "refresh_token": ""}}, 0)   # the TV's profile is empty already
        reply, code = pa.post(pa.PREFIX + "another", {"service": "youtube"}, k)
        self.assertEqual((code, reply["previous"]), (200, None), reply)
        self.assertEqual([c[1]["params"] for c in k.calls], [["accounts", "signin", "youtube"]])

    def test_another_account_names_skip_taken_ones_and_a_slow_tv_is_a_calm_error(self):
        yt({"0": {"name": "Основной", "refresh_token": "a"}, "1": {"name": "Аккаунт 3", "refresh_token": "b"}}, 0)
        k = AddingKodi()
        pa.post(pa.PREFIX + "another", {"service": "youtube"}, k)
        self.assertEqual(k.calls[0][1]["params"][3], "Аккаунт 4")
        reset()
        yt({"0": {"name": "Основной", "refresh_token": "a"}}, 0)
        k = FakeKodi()   # never adds the profile
        with mock.patch.object(pa, "ANOTHER_WAIT", 0.3):
            reply, code = pa.post(pa.PREFIX + "another", {"service": "youtube"}, k)
        self.assertEqual((code, reply["ok"]), (504, False))
        self.assertIn("Посмотрите на ТВ", reply["error"])
        self.assertEqual(len(k.calls), 1)   # no sign-in on a profile that is not there

    def test_another_account_is_youtube_only_and_not_twice(self):
        reply, code = pa.post(pa.PREFIX + "another", {"service": "sweettv"}, FakeKodi())
        self.assertEqual(code, 400)
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI")
        k = AddingKodi()
        reply, code = pa.post(pa.PREFIX + "another", {"service": "youtube"}, k)
        self.assertEqual((code, reply.get("already"), k.calls), (200, True, []))

    def test_unknown_action_and_paths(self):
        for path in ("/api/accounts/", "/api/accounts/nope", "/api/accounts/signin/extra", "/api/accounts/../key", "/api/accounts"):
            reply, code = pa.post(path, {"service": "youtube"}, self.k)
            self.assertEqual((code, reply["ok"]), (404, False), path)
        self.assertEqual(self.k.calls, [])

    def test_a_kodi_that_is_down_gives_a_calm_russian_error(self):
        self.k.down = True
        for action, body in (("signin", {"service": "youtube"}), ("switch", {"service": "youtube", "id": "2"}),
                             ("add", {"service": "youtube", "name": "A"}), ("signout", {"service": "sweettv"})):
            reply, code = self.post(action, body)
            self.assertEqual(code, 503, action)
            self.assertEqual(reply, {"ok": False, "error": pa.KODI_DOWN})
        self.assertRegex(pa.KODI_DOWN, "[а-я]")

    def test_other_oserrors_and_garbage_from_kodi_do_not_crash(self):
        def boom(*a, **k):
            raise ValueError("garbage")
        self.assertEqual(pa.post(pa.PREFIX + "signin", {"service": "youtube"}, boom)[1], 503)
        self.k.result = None   # an unreadable reply: the page's own timeout covers it
        self.assertEqual(self.post("signin", {"service": "youtube"})[1], 200)


class Page(unittest.TestCase):
    def test_inject_fills_the_three_markers_and_the_whitelist(self):
        page = pa.inject("<nav>@@ACC_NAV@@</nav>@@ACC_SECTION@@<body>@@ACC_TAIL@@</body>")
        self.assertNotIn("@@", page)
        self.assertIn('data-go="accounts"', page)
        self.assertIn('id="t-acc"', page)
        for host in pa.LINK_HOSTS:
            self.assertIn('"%s"' % host, page)
        self.assertIn("Точно выйти?", page)
        self.assertIn("Открыть страницу входа", page)
        self.assertIn('rel="noopener"', page)
        self.assertIn("Готово — вы вошли", page)

    def test_the_page_has_the_partner_action_and_its_hint_and_no_qr_link_for_it(self):
        page = pa.inject("@@ACC_NAV@@@@ACC_SECTION@@@@ACC_TAIL@@")
        self.assertIn("Через партнёра", page)
        self.assertIn("accStart(svc,'partner')", page)
        self.assertIn("{service:svc,mode}", page)
        self.assertIn("Код передан партнёру. Держите ТВ включённым. Поддержка партнёра работает 14:00–00:00", page)
        self.assertIn("partner=s.mode==='partner', link=partner?'':accSafe(s.link)", page)   # the sheet never opens addDevice
        self.assertIn("acc-partner", page)
        self.assertIn("armed('acc-cancel'", page)                      # cancelling a partner's wait asks for a second tap
        self.assertIn("'Войти'", page)                                 # the old sign-in stays

    def test_the_accounts_tab_has_a_hidden_bar_for_an_unfinished_keys_wizard(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        bar = page.split('id="acc-yk-cont"', 1)[1].split(">", 1)[0]
        self.assertIn("hide", bar)                                      # hidden until the wizard script shows it
        self.assertLess(page.index('id="acc-yk-cont"'), page.index('id="acc-list"'))
        self.assertIn("bkeys.onclick=()=>ykOpen()", page)               # the card's button still opens the wizard

    def test_no_browser_dialogs(self):
        page = pa.inject("@@ACC_NAV@@@@ACC_SECTION@@@@ACC_TAIL@@")
        for word in ("confirm(", "alert(", "prompt("):
            self.assertNotIn(word, page)

    def test_every_id_and_class_of_the_fragment_is_prefixed(self):
        import re
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        for i in re.findall(r'\bid="([^"]+)"', page):
            self.assertTrue(i.startswith(("acc-", "t-acc")), i)


class Served(unittest.TestCase):
    """The real panel on a free port; the fake Kodi stands in for Kodi."""
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
        reset()
        self.kodi.calls.clear()
        self.kodi.down = False
        self.panel.status_cache.update(t=0.0, s=None)

    def req(self, method, path, body=None, headers=None, host=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        h = {"Host": host or "localhost:%d" % self.port}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body)
            h["Content-Type"] = "application/json"
        c.request(method, path, data, h)
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        return r.status, raw

    def post(self, action, body, **kw):
        status, raw = self.req("POST", "/api/accounts/" + action, body, {"X-Panel": "1"}, **kw)
        return status, json.loads(raw)

    def test_the_page_has_the_tab_the_section_and_no_leftover_marker(self):
        status, raw = self.req("GET", "/")
        self.assertEqual(status, 200)
        self.assertNotIn("@@ACC_", raw)
        self.assertEqual(raw.count('data-go="accounts"'), 1)
        self.assertEqual(raw.count('id="t-acc"'), 1)
        self.assertEqual(raw.count('id="acc-sheet"'), 1)
        self.assertIn('if(window.accNote)accNote(s.signin)', raw)
        for line in raw.splitlines():   # the page's own comment mentions confirm(); no call anywhere
            if "confirm(" in line or "alert(" in line or "prompt(" in line:
                self.assertTrue(line.lstrip().startswith("//"), line)

    def test_get_accounts(self):
        yt({"0": {"name": "Основной", "refresh_token": SECRET}})
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI", step=1, steps=4)
        status, raw = self.req("GET", "/api/accounts")
        self.assertEqual(status, 200)
        self.assertNotIn("SECRET", raw)
        d = json.loads(raw)
        self.assertEqual([a["service"] for a in d["accounts"]], ["youtube", "sweettv"])
        self.assertEqual(d["waiting"][0]["code"], "ABC-DEF-GHI")

    def test_a_partner_sign_in_goes_through_http_and_its_state_comes_back_without_a_link(self):
        status, d = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual((status, d), (200, {"ok": True}))
        self.assertEqual(self.kodi.calls[0][1]["params"], ["accounts", "signin", "sweettv"])
        self.assertEqual(ms.requested_mode("sweettv"), "partner")
        ms.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice", mode="partner")
        status, raw = self.req("GET", "/api/accounts")
        d = json.loads(raw)
        w = d["waiting"][0]
        self.assertEqual((w["mode"], w["code"], w["link"], w["url"]), ("partner", "12345", "", ""))
        self.assertGreater(w["left"], 6 * 3600 - 10)
        self.assertNotIn("addDevice", raw)
        status, d = self.post("signin", {"service": "youtube", "mode": "partner"})
        self.assertEqual(status, 400)

    def test_status_carries_only_the_names_of_waiting_sign_ins(self):
        status, raw = self.req("GET", "/api/status")
        self.assertEqual((status, json.loads(raw)["signin"]), (200, []))
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI")
        status, raw = self.req("GET", "/api/status")   # inside the 3 s status cache, still fresh
        self.assertEqual(json.loads(raw)["signin"], ["youtube"])
        self.assertNotIn("ABC-DEF-GHI", raw)

    def test_post_needs_the_panel_header(self):
        status, raw = self.req("POST", "/api/accounts/cancel", {"service": "youtube"})
        self.assertEqual(status, 403)
        status, raw = self.req("POST", "/api/accounts/signin", {"service": "youtube"}, {"X-Panel": "0"})
        self.assertEqual(status, 403)
        self.assertFalse(ms.cancel_requested("youtube"))
        self.assertEqual(self.kodi.calls, [])

    def test_a_foreign_host_is_refused(self):
        status, raw = self.req("POST", "/api/accounts/cancel", {"service": "youtube"}, {"X-Panel": "1"}, host="evil.example")
        self.assertEqual(status, 403)
        self.assertFalse(ms.cancel_requested("youtube"))
        status, raw = self.req("GET", "/api/accounts", host="evil.example")
        self.assertEqual(status, 421)

    def test_post_works_and_reaches_the_launcher(self):
        status, d = self.post("signin", {"service": "sweettv"})
        self.assertEqual((status, d), (200, {"ok": True}))
        self.assertEqual(self.kodi.calls[0][1]["params"], ["accounts", "signin", "sweettv"])
        status, d = self.post("cancel", {"service": "sweettv"})
        self.assertEqual((status, d), (200, {"ok": True}))
        self.assertTrue(ms.cancel_requested("sweettv"))

    def test_kodi_down_is_a_calm_503_and_the_server_lives(self):
        self.kodi.down = True
        status, d = self.post("signin", {"service": "youtube"})
        self.assertEqual((status, d["ok"]), (503, False))
        self.assertIn("Kodi", d["error"])
        status, raw = self.req("GET", "/api/accounts")
        self.assertEqual(status, 200)

    def test_bad_json_is_a_clean_400(self):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/accounts/signin", "{nope", {"Host": "localhost", "X-Panel": "1"})
        r = c.getresponse()
        d = json.loads(r.read())
        c.close()
        self.assertEqual((r.status, d["ok"]), (400, False))

    def test_existing_routes_still_work(self):
        self.assertEqual(self.req("GET", "/api/https")[0], 200)
        status, d = self.post("nope", {})
        self.assertEqual(status, 404)
        status, raw = self.req("POST", "/api/key", {"action": "up"}, {"X-Panel": "1"})
        self.assertEqual(status, 200)
        self.assertEqual(self.req("POST", "/api/key", {"action": "sudo"}, {"X-Panel": "1"})[0], 400)


if __name__ == "__main__":
    unittest.main(verbosity=1)
