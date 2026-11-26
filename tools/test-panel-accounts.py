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

    def test_the_page_is_told_whether_the_link_has_the_code_and_which_approval_it_is(self):
        s = {"service": "youtube", "name": "YouTube", "state": "waiting", "code": "ABCD-EFGH",
             "url": "https://www.google.com/device", "link": "https://www.google.com/device", "step": 3, "steps": 4,
             "left": 300, "updated": 5, "prefilled": False, "round": 2, "rounds": 3}
        out = pa.public_signin(s)
        self.assertEqual((out["prefilled"], out["round"], out["rounds"]), (False, 2, 3))
        self.assertEqual((out["step"], out["steps"]), (3, 4))
        carried = dict(s, link="https://www.google.com/device?user_code=ABCD-EFGH", prefilled=True)
        self.assertIs(pa.public_signin(carried)["prefilled"], True)
        # a state from before the add-on said so: worked out from the link; never "prefilled" without a link
        old = {k: v for k, v in carried.items() if k not in ("prefilled", "round", "rounds")}
        self.assertEqual((pa.public_signin(old)["prefilled"], pa.public_signin(old)["round"], pa.public_signin(old)["rounds"]), (True, 1, 1))
        bare = {k: v for k, v in s.items() if k not in ("prefilled", "round", "rounds")}
        self.assertIs(pa.public_signin(bare)["prefilled"], False)
        self.assertIs(pa.public_signin(dict(carried, link="https://evil.example/?c=ABCD-EFGH"))["prefilled"], False)
        self.assertIs(pa.public_signin(dict(carried, prefilled="yes"))["prefilled"], True)      # not a bool: the link decides
        # the numbers are held inside their range, and a round is never past its rounds
        odd = pa.public_signin(dict(s, round=9, rounds=3))
        self.assertEqual((odd["round"], odd["rounds"]), (3, 3))
        self.assertEqual((pa.public_signin(dict(s, round="x", rounds=-4))["round"], pa.public_signin(dict(s, round="x", rounds=-4))["rounds"]), (1, 1))

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

    def test_a_failed_state_tells_the_page_only_a_reason_it_knows(self):
        s = {"service": "sweettv", "name": "SWEET.TV", "state": "failed", "reason": "expired", "updated": 5}
        self.assertEqual(pa.public_signin(s)["reason"], "expired")
        for odd in ("<script>", "", None, 1):
            self.assertEqual(pa.public_signin(dict(s, reason=odd))["reason"], "", odd)
        self.assertEqual(pa.public_signin({k: v for k, v in s.items() if k != "reason"})["reason"], "")

    def test_the_mode_of_a_sign_in(self):
        for value in (None, "", "normal"):
            self.assertEqual(pa.clean_mode(value, "sweettv"), "normal")
            self.assertEqual(pa.clean_mode(value, "youtube"), "normal")
        for value, service in (("partner", "youtube"), ("partner", "sweettv"), ("Partner", "sweettv"),
                               ("admin", "sweettv"), (1, "sweettv"), (["partner"], "sweettv"), (True, "sweettv")):
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

    def test_a_waiting_sign_in_says_whether_the_onboarding_sheet_draws_it(self):
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI", url="https://www.google.com/device", round=2, rounds=3)
        w = pa.view()["waiting"][0]
        self.assertIs(w["guided"], True)                                  # a live sign-in document: the old sheet stays shut
        self.assertEqual((w["prefilled"], w["round"], w["rounds"]), (False, 2, 3))
        pa.onboarding.clear("youtube")                                    # no document (it could not be written): the old sheet
        self.assertIs(pa.view()["waiting"][0]["guided"], False)
        ms.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice", mode="partner")
        self.assertIs([x for x in pa.view()["waiting"] if x["service"] == "sweettv"][0]["guided"], False)   # partner: nobody follows it on the phone
        ms.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice")
        pa.onboarding.write("sweettv", {"flow": "keys", "title": "t", "steps": [{"phone": "a"}]})
        self.assertIs([x for x in pa.view()["waiting"] if x["service"] == "sweettv"][0]["guided"], False)   # another flow's document is not this sign-in's

    def test_without_the_onboarding_library_the_old_sheet_is_the_sheet(self):
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI", url="https://www.youtube.com/activate")
        saved, pa.onboarding = pa.onboarding, None
        try:
            self.assertIs(pa.view()["waiting"][0]["guided"], False)
            boom = mock.Mock()
            boom.read.side_effect = RuntimeError("x")
            pa.onboarding = boom
            self.assertIs(pa.view()["waiting"][0]["guided"], False)
        finally:
            pa.onboarding = saved

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
        page = pa.inject("@@ACC_SECTION@@<body>@@ACC_TAIL@@</body>")
        self.assertIn("нет канала YouTube", page)
        self.assertIn("«Создать канал»", page)
        self.assertIn("«Добавить аккаунт»", page)
        self.assertNotIn("«Войти другим аккаунтом»", page)
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
                 ("add", {"service": "youtube", "name": " Гости "}, ["accounts", "add", "youtube", "Гости"]),
                 ("signout", {"service": "sweettv"}, ["accounts", "signout", "sweettv"])]
        for action, body, params in cases:
            self.k.calls.clear()
            reply, code = self.post(action, body)
            self.assertEqual((code, reply), (200, {"ok": True}), action)
            self.assertEqual(self.k.calls, [("Addons.ExecuteAddon", {"addonid": "script.media-stick.home", "params": params})])

    def test_a_sweettv_sign_in_with_no_mode_is_the_one_sign_in_and_asks_for_no_other_mode(self):
        reply, code = self.post("signin", {"service": "sweettv"})
        self.assertEqual((code, reply), (200, {"ok": True}))
        self.assertEqual(self.k.calls, [("Addons.ExecuteAddon", {"addonid": "script.media-stick.home",
                                                                  "params": ["accounts", "signin", "sweettv"]})])
        self.assertEqual(ms.requested_mode("sweettv"), "normal")

    def test_the_partner_button_is_gone_an_explicit_partner_mode_is_refused(self):
        reply, code = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual((code, reply["ok"]), (400, False))
        self.assertEqual(self.k.calls, [])
        self.assertEqual(ms.requested_mode("sweettv"), "normal")

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

    def test_a_sign_in_that_is_already_waiting_is_left_alone(self):
        ms.publish("sweettv", "waiting", code="12345")
        reply, code = self.post("signin", {"service": "sweettv"})
        self.assertEqual((code, reply.get("already")), (200, True))
        self.assertEqual((self.k.calls, ms.requested_mode("sweettv")), ([], "normal"))

    def test_a_kodi_that_is_down_leaves_no_mode_request_behind(self):
        self.k.down = True
        reply, code = self.post("signin", {"service": "sweettv"})
        self.assertEqual((code, reply["error"]), (503, pa.KODI_DOWN))
        self.assertEqual(ms.requested_mode("sweettv"), "normal")        # or the next, plain sign-in would become one

    def test_a_request_that_cannot_be_written_is_an_error_not_a_quiet_normal_sign_in(self):
        with mock.patch.object(ms, "request_mode", return_value=False):
            reply, code = self.post("signin", {"service": "sweettv"})
        self.assertEqual((code, reply["ok"]), (500, False))
        self.assertEqual(self.k.calls, [])

    def addon_answers(self, then):
        """The add-on's side of a request for a new code: when it is asked, `then()` is what it does next."""
        real = ms.request_renew
        def request_renew(service):
            ok = real(service)
            then()
            return ok
        return mock.patch.object(ms, "request_renew", request_renew)

    def test_renew_asks_the_running_sign_in_for_a_new_code_and_starts_no_second_one(self):
        ms.publish("sweettv", "waiting", code="12345")
        with self.addon_answers(lambda: ms.publish("sweettv", "waiting", code="67890")):
            reply, code = self.post("renew", {"service": "sweettv"})
        self.assertEqual((code, reply), (200, {"ok": True}))
        self.assertEqual(ms.read("sweettv")["code"], "67890")
        self.assertEqual(self.k.calls, [])                                  # no launch: the TV's first screen is still up and would turn it away
        self.assertFalse(ms.cancel_requested("sweettv"))                    # and the old sign-in is not cancelled
        self.assertTrue(ms.renew_requested("sweettv"))                      # (the add-on uses the request up; this stand-in does not)

    def test_renew_when_the_sign_in_ends_while_asking_starts_one(self):
        ms.publish("sweettv", "waiting", code="12345")
        with self.addon_answers(lambda: ms.publish("sweettv", "cancelled")):
            reply, code = self.post("renew", {"service": "sweettv"})
        self.assertEqual((code, reply), (200, {"ok": True}))
        self.assertFalse(ms.renew_requested("sweettv"))
        self.assertEqual(self.k.calls[0][1]["params"], ["accounts", "signin", "sweettv"])

    def test_renew_with_nothing_waiting_just_starts_a_sign_in(self):
        ms.publish("sweettv", "failed", reason="expired")
        reply, code = self.post("renew", {"service": "sweettv"})
        self.assertEqual((code, reply), (200, {"ok": True}))
        self.assertFalse(ms.cancel_requested("sweettv"))
        self.assertEqual(len(self.k.calls), 1)

    def test_renew_is_for_sweettv_only(self):
        for body in ({"service": "youtube"}, {"service": "nope"}, {}):
            reply, code = self.post("renew", body)
            self.assertEqual((code, reply["ok"]), (400, False), body)
        self.assertEqual(self.k.calls, [])

    def test_renew_that_the_add_on_does_not_answer_is_an_error_and_starts_nothing(self):
        ms.publish("sweettv", "waiting", code="12345")
        with mock.patch.object(pa, "RENEW_WAIT", 0.3):
            reply, code = self.post("renew", {"service": "sweettv"})
        self.assertEqual((code, reply["ok"]), (504, False))
        self.assertEqual(self.k.calls, [])
        self.assertFalse(ms.renew_requested("sweettv"))                     # a late add-on does not renew a code nobody asked for any more
        self.assertEqual(ms.read("sweettv")["code"], "12345")

    def test_nothing_renews_a_code_by_itself(self):
        ms.publish("sweettv", "waiting", code="12345")
        self.post("signin", {"service": "sweettv"})                         # a second tap on «Войти» is left alone
        self.assertEqual((ms.read("sweettv")["code"], ms.cancel_requested("sweettv"), self.k.calls), ("12345", False, []))

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

    def test_a_switch_answers_when_the_tv_is_on_that_profile_and_says_which(self):
        k = AddingKodi()                                                  # the add-on makes the profile current a moment after the call
        reply, code = pa.post(pa.PREFIX + "switch", {"service": "youtube", "id": "2"}, k)
        self.assertEqual((code, reply), (200, {"ok": True, "current": "2"}))
        self.assertEqual([c[1]["params"] for c in k.calls], [["accounts", "switch", "youtube", "2"]])
        self.assertEqual([p["id"] for p in ms.youtube_accounts() if p["current"]], ["2"])   # what the phone's check and the TV read

    def test_a_switch_waits_for_a_slow_tv(self):
        class Slow(AddingKodi):
            """The profile changes some time after the call, as the add-on's own process does."""
            def __call__(self, method, params=None, timeout=3):
                out = FakeKodi.__call__(self, method, params, timeout)
                args = (params or {}).get("params") or []
                if args[:2] == ["accounts", "switch"]:
                    threading.Timer(0.3, lambda: yt({"0": {"name": "Основной", "refresh_token": "a|b|c|d"},
                                                     "2": {"name": "Дети", "refresh_token": ""}}, "2")).start()
                return out
        with mock.patch.object(pa, "SWITCH_STEP", 0.02):
            reply, code = pa.post(pa.PREFIX + "switch", {"service": "youtube", "id": "2"}, Slow())
        self.assertEqual((code, reply), (200, {"ok": True, "current": "2"}))

    def test_a_tv_that_does_not_switch_is_a_504_with_the_calm_words_not_an_ok(self):
        with mock.patch.object(pa, "SWITCH_WAIT", 0.2), mock.patch.object(pa, "SWITCH_STEP", 0.02):
            reply, code = pa.post(pa.PREFIX + "switch", {"service": "youtube", "id": "2"}, self.k)   # FakeKodi changes nothing
        self.assertEqual(code, 504)
        self.assertFalse(reply["ok"])
        self.assertEqual(reply["error"], "Телевизор не переключил профиль. Посмотрите на ТВ.")
        self.assertEqual([c[1]["params"] for c in self.k.calls], [["accounts", "switch", "youtube", "2"]])   # it was asked once
        self.assertEqual([p["id"] for p in ms.youtube_accounts() if p["current"]], ["0"])

    def test_a_switch_to_the_profile_the_tv_is_on_asks_nothing(self):
        reply, code = self.post("switch", {"service": "youtube", "id": "0"})
        self.assertEqual((code, reply), (200, {"ok": True, "current": "0"}))
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


class GivenUpAnother(unittest.TestCase):
    """«Войти другим аккаунтом» that ends without success puts the TV back, from the device, once."""
    def setUp(self):
        reset()
        yt({"0": {"name": "Основной", "refresh_token": "a|b|c"}}, 0)
        self.k = AddingKodi()
        reply, code = pa.post(pa.PREFIX + "another", {"service": "youtube"}, self.k)
        self.assertEqual((code, reply["previous"]), (200, "0"), reply)
        self.k.calls.clear()

    def switches(self):
        return [c[1]["params"] for c in self.k.calls if c[1]["params"][:2] == ["accounts", "switch"]]

    def test_asking_for_it_leaves_a_note_for_the_device(self):
        self.assertEqual(ms._return_rec("youtube")["previous"], "0")
        self.assertEqual(ms._return_rec("youtube")["target"], "1")

    def test_while_the_code_is_waited_for_nothing_happens(self):
        ms.publish("youtube", "waiting", code="ABC-DEF-GHI")
        self.assertEqual(pa.settle(self.k), "wait")
        self.assertEqual(self.switches(), [])
        self.assertIsNotNone(ms._return_rec("youtube"))

    def test_before_the_add_on_has_said_anything_it_is_waited_for_a_while(self):
        self.assertEqual(pa.settle(self.k), "wait")
        later = time.time() + ms.RETURN_GRACE + 5
        self.assertEqual(ms.return_decision(ms._return_rec("youtube"), None, ms.youtube_accounts(), later), "back")

    def test_cancelled_switches_back_once(self):
        ms.publish("youtube", "cancelled")
        self.assertEqual(pa.settle(self.k), "back")
        self.assertEqual(self.switches(), [["accounts", "switch", "youtube", "0"]])
        self.assertEqual(pa.settle(self.k), None)           # the note is used up: no second switch
        self.assertEqual(len(self.switches()), 1)

    def test_failed_and_expired_and_a_silent_add_on_switch_back(self):
        for how in ("failed", "expired", "silent"):
            with self.subTest(how):
                self.setUp()
                if how == "failed":
                    ms.publish("youtube", "failed")
                    now = None
                elif how == "expired":
                    ms.publish("youtube", "waiting", code="X", ttl=-5)
                    now = None
                else:
                    ms.publish("youtube", "waiting", code="X")
                    now = time.time() + ms.HEARTBEAT + 5
                rec = ms._return_rec("youtube")
                verdict = ms.return_decision(rec, ms._load("youtube"), ms.youtube_accounts(), now or time.time())
                self.assertEqual(verdict, "back")
                if now is None:
                    self.assertEqual(pa.settle(self.k), "back")
                    self.assertEqual(self.switches(), [["accounts", "switch", "youtube", "0"]])

    def test_success_does_not_switch_back(self):
        ms.publish("youtube", "done")
        self.assertEqual(pa.settle(self.k), "drop")
        self.assertEqual(self.switches(), [])
        self.assertIsNone(ms._return_rec("youtube"))

    def test_a_signed_in_profile_is_success_even_when_the_state_is_gone(self):
        yt({"0": {"name": "Основной", "refresh_token": "a|b|c"}, "1": {"name": "Аккаунт 2", "refresh_token": "x|y"}}, 1)
        ms.publish("youtube", "cancelled")
        self.assertEqual(pa.settle(self.k), "drop")
        self.assertEqual(self.switches(), [])

    def test_a_profile_chosen_by_hand_is_left_alone(self):
        yt({"0": {"name": "Основной", "refresh_token": "a|b|c"}, "1": {"name": "Аккаунт 2", "refresh_token": ""}}, 0)
        ms.publish("youtube", "cancelled")
        self.assertEqual(pa.settle(self.k), "drop")
        self.assertEqual(self.switches(), [])

    def test_a_tv_that_does_not_answer_is_tried_again(self):
        ms.publish("youtube", "cancelled")
        self.k.down = True
        self.assertIsNone(pa.settle(self.k))
        self.assertIsNotNone(ms._return_rec("youtube"))
        self.k.down = False
        self.assertEqual(pa.settle(self.k), "back")
        self.assertEqual(len(self.switches()), 1)

    def test_the_page_no_longer_switches_back_itself_and_refreshes_after_a_switch(self):
        import panel_accounts_ui as ui
        page = ui.tail(pa.LINK_HOSTS)
        self.assertNotIn("accBackTo", page)
        self.assertNotIn("accSettle", page)
        self.assertIn("accWatch(20000)", page)                      # after a switch, a cancel and a closed sheet
        self.assertIn("try{await accCall('cancel',{service:accSheet.svc});accWatch(20000)}", page)
        self.assertIn("const accLive=()=>!document.hidden&&(accShown()||tab==='settings'||wide())", page)   # also the wide card
        self.assertIn("accShown()||Date.now()<accFastUntil?1500:5000", page)   # every 5 s when idle, hidden pages stop
        self.assertIn("const accShown=()=>accSheet||accTrk", page)         # a sign-in the onboarding sheet draws is on screen too
        self.assertIn("accWaiting[svc]=false;accMsg(svc,expired?ACC_EXPIRED:'',expired)", page)   # «Жду код…» goes with the sign-in
        self.assertIn("if(accWaiting[svc]&&!accShown()", page)


class ListPage(unittest.TestCase):
    """The accounts page as an iOS-style list: groups of rows, no chips, no big buttons (text level; the script is not run)."""
    page = None

    @classmethod
    def setUpClass(cls):
        cls.page = pa.inject("@@ACC_SECTION@@<body>@@ACC_TAIL@@</body>")

    def test_a_page_title_and_no_card_label(self):
        sec = self.page.split('<section id="t-acc"', 1)[1].split("</section>", 1)[0]
        self.assertIn('<h2 class="acc-title">Приложения</h2>', sec)
        self.assertNotIn('class="card"', sec)

    def test_all_ids_prefixed_and_no_markers(self):
        import re
        import panel_accounts_ui as ui
        raw = ui.SECTION + ui.TAIL
        for elem_id in re.findall(r'\bid="([^"]+)"', raw):
            self.assertTrue(elem_id.startswith(("acc-", "t-acc")), elem_id)
        self.assertEqual(re.findall(r"@@\w+@@", self.page), [])

    def test_eager_youtube_and_sweettv_app_settings(self):
        p = self.page
        self.assertIn("accCard('youtube')", p)
        self.assertIn("acc-keys-row", p)
        self.assertIn("Ключи Google", p)
        self.assertIn("ykOpen()", p)
        self.assertIn("acc-sw-cfg", p)
        self.assertIn("acc-sw-qseg", p)
        for q in ("720p", "1080p", "unlimited"):
            self.assertIn(q, p)
        self.assertIn("acc-sw-preview", p)
        self.assertIn("Предпросмотр эфира в фоне", p)
        self.assertIn("/api/sweettv/settings", p)
        self.assertIn("data-go=settings", p)
        self.assertIn("toast(tvErr(e))", p)

    def test_three_groups_in_order(self):
        for title in ("YouTube на ТВ", "SWEET.TV", "Выход"):
            self.assertIn("'%s'" % title, self.page)
        self.assertLess(self.page.index("['youtube','YouTube на ТВ']"), self.page.index("['sweettv','SWEET.TV']"))
        self.assertLess(self.page.index("['sweettv','SWEET.TV']"), self.page.index("['out','Выход']"))

    def test_youtube_rows(self):
        p = self.page
        self.assertIn("p.name==='Default'?'Основной':p.name", p)                 # the add-on's first profile
        self.assertIn("const accInit=", p)                                       # initials in the avatar
        self.assertIn("'Нажмите, чтобы включить на ТВ'", p)
        self.assertIn("'Аккаунт Google без канала'", p)
        self.assertIn("signed=a.profiles.filter(p=>p.signed_in)", p)             # empty profiles are not rows
        self.assertIn("accRow({av:'+',title:'Новый аккаунт',sub:'ждёт входа'})", p)
        self.assertIn("'+ Добавить аккаунт'", p)
        self.assertIn("go:()=>accAnother(a.service)", p)
        self.assertIn("'Войти в YouTube'", p)
        self.assertIn("go:()=>accStart(a.service)", p)
        self.assertIn("Пустые профили не показываются, приставка использует их сама.", p)

    def test_a_switch_is_a_toast_said_only_from_what_the_tv_confirmed_and_the_check_is_the_polled_profile(self):
        p = self.page
        self.assertIn("const accChosen=p=>'На ТВ: '+accName(p)", p)
        self.assertIn("accWatch(20000)", p)
        self.assertNotIn("выбран.'", p)                                          # no standing «Профиль … выбран»
        self.assertNotIn("acc-chip", p)
        # nothing holds the check on the tapped profile before the TV is on it
        self.assertNotIn("accPend", p)
        self.assertNotIn("accHold", p)
        self.assertNotRegex(p, r"current:p\.id===")
        sw = p.split("async function accSwitch(svc,p){", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("accRun(svc,'switch'", sw)                              # the generic runner said "done" at once
        self.assertIn("accMsg(svc,'Переключаю на «'+accName(p)+'»…')", sw)
        self.assertEqual(sw.count("accChosen(p)"), 1)                            # the toast is in one place, behind the TV's answer
        self.assertIn("if(r&&r.current===p.id){delete accWant[svc];toast(accChosen(p))}", sw)
        self.assertLess(sw.index("await accCall('switch'"), sw.index("accChosen(p)"))
        self.assertIn("catch(e){w.busy=false;accMsg(svc,e.message,true)}", sw)   # a failure shows its error text
        self.assertIn("accWatch(20000)", sw)
        # the polled list is the other witness; a switch that is not over is not confirmed by it
        late = p.split("function accSwitched(list){", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if(!w||w.busy)return", late)
        self.assertIn("cur&&cur.id===w.id", late)
        self.assertIn("toast(accChosen(cur))", late)
        self.assertIn("accSwitched(d.accounts||[])", p.split("function accApply(d){", 1)[1].split("\n", 1)[0])

    def test_the_tapped_row_says_switching_and_the_others_cannot_be_tapped_meanwhile(self):
        p = self.page
        self.assertIn("const accSwId=svc=>accWant[svc]&&accWant[svc].busy?accWant[svc].id:''", p)
        self.assertIn("const busy=accSwId(a.service);", p)
        self.assertIn("sub:busy===p.id?'переключаю…':p.current?accSub(p):'Нажмите, чтобы включить на ТВ'", p)
        self.assertIn("(busy===p.id?' wait':'')", p)
        self.assertIn("off:!!busy})));", p)                                       # every profile row waits
        self.assertIn("off:waiting||!!busy", p)                                   # and so does «Добавить аккаунт»
        self.assertIn("accSwId(a.service)]", p)                                   # the rows are drawn again when it starts and ends
        self.assertIn("button.acc-row.wait:disabled{opacity:1}", p)

    def test_sweettv_rows_and_the_way_out(self):
        p = self.page
        self.assertIn("accRow({title:'Вход выполнен',tick:true})", p)
        self.assertIn("'Войти'", p)
        self.assertNotIn("Friendly Share", p)                                    # the partner sign-in no longer exists
        self.assertIn("'Выйти из «'+accName(cur)+'» на ТВ'", p)
        self.assertIn("'Выйти из SWEET.TV'", p)
        self.assertIn("ask='Нажмите ещё раз, чтобы выйти'", p)
        self.assertIn("if(armed(id,ask))accOut(svc)", p)
        self.assertIn("cls:'red'", p)
        self.assertIn(".acc-row.red{color:var(--bad)}", p)

    def test_no_big_buttons_and_nothing_wraps(self):
        p = self.page
        for gone in ("bother", "bin=", "bout", "acc-btns", "acc-chips", "acc-who"):
            self.assertNotIn(gone, p)
        self.assertIn("white-space:nowrap", p)
        self.assertIn("#acc-g-out{grid-column:1/-1}", p)                         # the wide layout

    def test_a_profile_is_named_by_its_channel_in_every_place(self):
        # what the device gave: Default (no channel, current), «Аккаунт 2» (channel «Dmytro Hanzha»), «Аккаунт 3» (empty)
        yt({"0": {"name": "Default", "refresh_token": "a|b|c"}, "1": {"name": "Аккаунт 2", "refresh_token": "a|b"},
            "2": {"name": "Аккаунт 3", "refresh_token": ""}}, 0)
        with mock.patch.object(pa.ytchannel, "peek", side_effect=lambda pid: {"state": "yes", "title": "Dmytro Hanzha"} if pid == "1" else {"state": "no"}):
            profiles = pa.view()["accounts"][0]["profiles"]
        self.assertEqual([(p["name"], p["channel"], p["channel_title"], p["current"]) for p in profiles],
                         [("Default", "no", "", True), ("Аккаунт 2", "yes", "Dmytro Hanzha", False), ("Аккаунт 3", "unknown", "", False)])
        p = self.page
        self.assertIn("const accName=p=>p.channel_title||(p.name==='Default'?'Основной':p.name)", p)
        self.assertIn("const accSub=p=>p.channel_title?'Канал YouTube':", p)
        # every place that names a profile goes through the one helper, none reads p.name itself
        for use in ("av:accInit(accName(p)),title:accName(p)", "'На ТВ: '+accName(p)", "'Выйти из «'+accName(cur)+'» на ТВ'",
                    "(cur?accName(cur):'не выполнен вход')", "'Переключаю на «'+accName(p)+'»…'"):
            self.assertIn(use, p)
        self.assertNotRegex(p, r"title:p\.name|accInit\(p\.name")

    def test_the_title_is_a_plain_page_title(self):
        css = self.page.split(".acc-title{", 1)[1].split("}", 1)[0]
        for want in ("font-size:24px", "font-weight:600", "letter-spacing:0", "text-transform:none", "color:inherit", "margin:0 6px"):
            self.assertIn(want, css)

    def test_the_no_channel_hint_is_one_line_that_opens_and_closes(self):
        p = self.page
        self.assertIn("'На ТВ пусто в «Подписках»? Как исправить ›'", p)
        self.assertIn("ch.classList.toggle('hide')===false", p)                  # a second tap collapses it
        self.assertIn("g.querySelector('.acc-help').classList.toggle('hide',!none)", p)   # only for a profile with no channel
        self.assertNotIn("classList.toggle('warn'", p)                           # no big block any more
        self.assertLess(p.index("e.append(n,h)"), p.index("if(k!=='out')e.append(accEl('div','acc-m'))"))
        self.assertIn("e.append(n,h)", p)                                        # the footnote first, then the hint

    def test_all_avatars_look_alike(self):
        self.assertNotIn(".acc-row.cur .acc-av", self.page)
        self.assertIn(".acc-av{flex:none;width:40px;height:40px;border-radius:50%;background:var(--card2)", self.page)

    def test_the_list_row_says_the_same(self):
        self.assertIn("'YouTube: '+(cur?accName(cur):'не выполнен вход')+' · SWEET.TV: '+(sw&&sw.signed_in?'вход выполнен':'нет')", self.page)


class Page(unittest.TestCase):
    def test_inject_fills_the_two_markers_and_the_whitelist(self):
        page = pa.inject("@@ACC_SECTION@@<body>@@ACC_TAIL@@</body>")
        self.assertNotIn("@@", page)
        self.assertNotIn('data-go="accounts"', page)                    # no tab of its own: a card in the Настройки tab
        self.assertIn('<section id="t-acc" data-tab="settings"', page)
        for host in pa.LINK_HOSTS:
            self.assertIn('"%s"' % host, page)
        self.assertIn("Нажмите ещё раз, чтобы выйти", page)
        self.assertIn("Открыть страницу входа", page)
        self.assertIn('rel="noopener"', page)
        self.assertIn("Готово — вы вошли", page)

    def test_the_old_sheet_opens_only_when_the_onboarding_sheet_does_not_draw_the_sign_in(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        sync = page.split("function accSync(d){", 1)[1].split("\n}\n", 1)[0]
        # the only accOpen in accSync is the last branch, and it is behind accGuided
        self.assertEqual(sync.count("accOpen("), 1)
        self.assertRegex(sync, r"if\(accGuided\(s\)\)\{[^}]*accTrk=\{svc:s\.service")
        self.assertRegex(sync, r"\}else accOpen\(s\)\s*\}\s*$")
        guided = page.split("function accGuided(s){", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("if(s.guided)return true", guided)                        # the server's word ...
        self.assertIn("lastStatus.onboarding", guided)                          # ... and the status the page polls: an active sign-in document
        self.assertIn("x.service===s.service&&x.flow==='signin'&&(!x.state||x.state==='active')", guided)
        # only the end of such a sign-in is the old sheet's: the result, and a SWEET.TV code that ran out
        self.assertIn("if(w.some(x=>x.service===accTrk.svc))return;", sync)
        self.assertIn("accEnd(", sync.split("accTrk=null", 1)[1])
        self.assertIn("if(typeof obClose==='function')obClose()", sync)        # one sheet at a time, the result's or the sign-in's
        self.assertEqual(page.count("accTrk={svc:"), 1)

    def test_the_old_sheet_as_a_fallback_has_no_code_n_of_4_and_a_hint_that_follows_prefilled(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        self.assertNotIn("'Код '+s.step", page)
        self.assertNotIn("' · код '+s.step", page)
        self.assertNotIn("из '+s.steps", page)                                  # the add-on's slots are nobody's counter
        self.assertIn("s.rounds>1?'подтверждение '+s.round+' из '+s.rounds:''", page)
        self.assertIn("link&&s.prefilled?'Страница откроется с уже введённым кодом.'", page)
        self.assertNotIn("(link?'Страница откроется", page)                     # a link alone says nothing about the code
        self.assertIn("link&&s.prefilled?'Новый код: нажмите «Открыть страницу входа» ещё раз.':'Новый код: введите его на странице входа.'", page)

    def test_the_page_has_one_sweettv_sign_in_and_no_friendly_share_button(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        for gone in ("Через Friendly Share", "accStart(svc,'partner')", "{service:svc,mode}", "Connection code", "ждём подключения",
                     "acc-partner", "partner"):
            self.assertNotIn(gone, page)
        self.assertIn("'Войти'", page)                                 # the one button of the card, as for YouTube
        self.assertIn("link=accSafe(s.link), url=accSafe(s.url)", page)   # the normal sheet: the link, the code, «Открыть страницу входа»

    def test_the_page_can_renew_a_sweettv_code_while_waiting_and_when_it_has_run_out(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        self.assertIn('<button id="acc-renew" class="btn wide hide">Обновить код</button>', page)   # on the sheet, SWEET.TV only
        self.assertIn("$('acc-renew').classList.toggle('hide',s.service!=='sweettv')", page)
        self.assertIn("accCall('renew',{service:svc})", page)
        self.assertIn("armed('acc-renew'", page)                       # the old code stops working: a second tap
        self.assertIn("const ACC_EXPIRED='Код устарел, нажмите «Обновить код»'", page)
        self.assertIn("st.reason==='expired'", page)                   # only what the add-on says ran out, not any failure
        self.assertIn('id="acc-fin-renew"', page)                      # the end of an expired sheet has the button too
        self.assertIn("if(!expired)accCloseT=setTimeout", page)        # and stays until the person chooses
        self.assertIn("go:()=>accRenew(a.service)", page)              # the row of the group, after the sheet is gone
        self.assertIn("if(accSheet.renew&&Date.now()-accSheet.renew<20000)return", page)   # the sheet is kept while the new code comes

    def test_the_accounts_tab_has_a_hidden_bar_for_an_unfinished_keys_wizard(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
        bar = page.split('id="acc-yk-cont"', 1)[1].split(">", 1)[0]
        self.assertIn("hide", bar)                                      # hidden until the wizard script shows it
        self.assertLess(page.index('id="acc-yk-cont"'), page.index('id="acc-list"'))
        self.assertIn('id="acc-keys-row"', page)
        self.assertIn("Ключи Google", page)                          # the keys row lives inside YouTube on Apps page

    def test_no_browser_dialogs(self):
        page = pa.inject("@@ACC_SECTION@@@@ACC_TAIL@@")
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
        self.assertEqual(raw.count('data-go="accounts"'), 0)
        self.assertEqual(raw.count('data-go="settings"'), 1)
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

    def test_a_sweettv_sign_in_goes_through_http_with_its_link_and_the_long_wait(self):
        status, d = self.post("signin", {"service": "sweettv"})
        self.assertEqual((status, d), (200, {"ok": True}))
        self.assertEqual(self.kodi.calls[0][1]["params"], ["accounts", "signin", "sweettv"])
        ms.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice")
        status, raw = self.req("GET", "/api/accounts")
        w = json.loads(raw)["waiting"][0]
        self.assertEqual((w["mode"], w["code"], w["link"]), ("normal", "12345", "https://sweet.tv/addDevice?connectCode=12345"))
        self.assertGreater(w["left"], 6 * 3600 - 10)                   # the code is not given up on our side for six hours
        status, d = self.post("signin", {"service": "sweettv", "mode": "partner"})
        self.assertEqual(status, 400)

    def test_a_failed_sweettv_code_says_it_ran_out_and_renew_starts_a_new_one(self):
        ms.publish("sweettv", "failed", reason="expired")
        status, raw = self.req("GET", "/api/accounts")
        sweet = [a for a in json.loads(raw)["accounts"] if a["service"] == "sweettv"][0]
        self.assertEqual((sweet["signin"]["state"], sweet["signin"]["reason"]), ("failed", "expired"))
        self.kodi.calls.clear()
        status, d = self.post("renew", {"service": "sweettv"})
        self.assertEqual((status, d), (200, {"ok": True}))
        self.assertEqual(self.kodi.calls[0][1]["params"], ["accounts", "signin", "sweettv"])

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
        self.assertIn("ТВ", d["error"])
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
