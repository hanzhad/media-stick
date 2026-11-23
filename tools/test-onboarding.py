#!/usr/bin/env python3
"""Offline test of the onboarding channel (the library, the sign-in guide and how the sign-in state feeds it):
python3 tools/test-onboarding.py"""
import sys

sys.dont_write_bytecode = True  # before any import: no __pycache__ in device/files

import json  # noqa: E402
import os  # noqa: E402
import stat  # noqa: E402
import tempfile  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
sys.path.insert(0, LIB)

import mediastick_onboarding as ob  # noqa: E402
import mediastick_signin as ms  # noqa: E402
import mediastick_signin_guide as guide  # noqa: E402

NOW = 1_700_000_000
AIZA = "AIza" + "Sy" + "A" * 33
SECRET = "GOCSPX-" + "a1B2c3D4e5F6"
CLIENT = "1234567890-abcdefghij.apps.googleusercontent.com"


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


def keys_doc(**over):
    doc = {"flow": "keys", "state": "active", "title": {"tv": "Follow along on your phone", "phone": "Ключи"},
           "step": 2, "steps": [{"id": "a", "tv": "Project and API", "phone": "Проект"},
                                {"id": "b", "tv": "Allow TV sign-in", "phone": "Вход"}],
           "chips": [[{"t": "Get started", "s": "done"}, {"t": "Create", "s": "now"}]],
           "items": [{"id": "api_key", "label": "API key", "s": "ok"}, {"id": "client", "label": "Client ID", "s": "wait"}],
           "warn": {"tv": "Publish it, or the TV gets signed out after 7 days.", "phone": "Опубликуйте"}}
    doc.update(over)
    return doc


class Library(unittest.TestCase):
    def setUp(self):
        for name in os.listdir(ob.DIR) if os.path.isdir(ob.DIR) else []:
            os.unlink(os.path.join(ob.DIR, name))

    def test_write_then_read_gives_the_schema_back(self):
        self.assertTrue(ob.write("youtube", keys_doc(), now=NOW))
        d = ob.read("youtube", now=NOW + 1)
        self.assertEqual((d["v"], d["service"], d["flow"], d["state"], d["step"]), (1, "youtube", "keys", "active", 2))
        self.assertEqual(d["title"], {"tv": "Follow along on your phone", "phone": "Ключи"})
        self.assertEqual([s["id"] for s in d["steps"]], ["a", "b"])
        self.assertEqual(d["chips"][0][1], {"t": "Create", "s": "now"})
        self.assertEqual(d["items"][1], {"id": "client", "label": "Client ID", "s": "wait"})
        self.assertEqual((d["updated"], d["expires"]), (NOW, NOW + ob.TTL))

    def test_file_is_world_readable_and_there_is_no_tmp_left(self):
        ob.write("youtube", keys_doc(), now=NOW)
        path = os.path.join(ob.DIR, "youtube.json")
        self.assertEqual(stat.S_IMODE(os.stat(path).st_mode), 0o644)
        self.assertEqual(os.listdir(ob.DIR), ["youtube.json"])

    def test_expires_is_mandatory_and_enforced(self):
        ob.write("youtube", keys_doc(), now=NOW, ttl=60)
        self.assertIsNotNone(ob.read("youtube", now=NOW + 59))
        self.assertIsNone(ob.read("youtube", now=NOW + 60))
        path = os.path.join(ob.DIR, "youtube.json")
        d = load(path)
        del d["expires"]
        save(path, d)
        self.assertIsNone(ob.read("youtube", now=NOW))

    def test_a_finished_document_lives_a_short_while(self):
        ob.write("youtube", keys_doc(state="done"), now=NOW)
        self.assertEqual(ob.read("youtube", now=NOW)["expires"], NOW + ob.RESULT_TTL)
        self.assertEqual(ob.list_active(now=NOW), [])

    def test_missing_corrupt_and_foreign_files_read_as_none(self):
        self.assertIsNone(ob.read("youtube"))
        os.makedirs(ob.DIR, exist_ok=True)
        path = os.path.join(ob.DIR, "youtube.json")
        for text in ("", "{not json", "[]", "null", json.dumps({"v": 2, "service": "youtube", "state": "active", "expires": NOW + 9}),
                     json.dumps({"v": True, "service": "youtube", "state": "active", "expires": NOW + 9}),
                     json.dumps({"v": 1, "service": "other", "state": "active", "expires": NOW + 9}),
                     json.dumps({"v": 1, "service": "youtube", "state": "weird", "expires": NOW + 9})):
            with open(path, "w") as f:
                f.write(text)
            self.assertIsNone(ob.read("youtube", now=NOW), text)

    def test_unknown_fields_are_tolerated_on_read(self):
        ob.write("youtube", keys_doc(), now=NOW)
        path = os.path.join(ob.DIR, "youtube.json")
        d = load(path)
        d["future"] = {"x": 1}
        save(path, d)
        self.assertEqual(ob.read("youtube", now=NOW)["future"], {"x": 1})

    def test_service_names_are_checked(self):
        for bad in ("", "You Tube", "../x", "a" * 33, "YouTube", None, 5):
            self.assertFalse(ob.write(bad, keys_doc(), now=NOW), bad)
            self.assertIsNone(ob.read(bad))
            self.assertFalse(ob.clear(bad))
        self.assertTrue(ob.write("a" * 32, keys_doc(), now=NOW))
        self.assertTrue(ob.write("tv_1-x", keys_doc(), now=NOW))

    def test_clear_and_list_active(self):
        ob.write("youtube", keys_doc(), now=NOW)
        ob.write("sweettv", keys_doc(flow="signin"), now=NOW)
        ob.write("old", keys_doc(), now=NOW - 10_000)
        self.assertEqual([d["service"] for d in ob.list_active(now=NOW)], ["sweettv", "youtube"])
        self.assertTrue(ob.clear("youtube"))
        self.assertFalse(ob.clear("youtube"))
        self.assertEqual([d["service"] for d in ob.list_active(now=NOW)], ["sweettv"])

    def test_limits_cut_long_texts_and_lists(self):
        doc = keys_doc(title={"tv": "T" * 200, "phone": "p"}, hint={"tv": "h " * 200, "phone": ""},
                       steps=[{"id": f"s{n}", "tv": "w" * 300, "phone": "x"} for n in range(12)],
                       chips=[[{"t": f"c{n}", "s": "todo"} for n in range(10)] for _ in range(6)],
                       items=[{"id": f"i{n}", "label": f"L{n}", "s": "ok"} for n in range(9)])
        d = ob.build("youtube", doc, now=NOW)
        self.assertEqual(len(d["title"]["tv"]), 80)
        self.assertTrue(d["title"]["tv"].endswith("…"))
        self.assertLessEqual(len(d["hint"]["tv"]), 160)
        self.assertEqual(len(d["steps"]), 8)
        self.assertEqual(len(d["steps"][0]["tv"]), 120)
        self.assertLessEqual(len(d["chips"]), 4)
        self.assertEqual(sum(len(r) for r in d["chips"]), 12)
        self.assertEqual(len(d["items"]), 6)

    def test_bad_values_are_made_safe(self):
        d = ob.build("youtube", keys_doc(step=99, chips=[[{"t": "x", "s": "bogus"}]], items=[{"label": "A", "s": "??"}],
                                         action={"kind": "bogus"}, link="javascript:alert(1)"), now=NOW)
        self.assertEqual(d["step"], 2)
        self.assertEqual(d["chips"][0][0]["s"], "todo")
        self.assertEqual(d["items"][0]["s"], "wait")
        self.assertNotIn("action", d)
        self.assertNotIn("link", d)
        with self.assertRaises(ob.Refused):
            ob.build("youtube", keys_doc(state="paused"))
        with self.assertRaises(ob.Refused):
            ob.build("youtube", keys_doc(flow="Bad Flow"))
        self.assertTrue(ob.write("youtube", keys_doc(flow="other-flow"), now=NOW))

    def test_secrets_are_refused_wherever_they_could_hide(self):
        for secret in (AIZA, SECRET, CLIENT, "ya29." + "a" * 20, "Paste AIza" + "b" * 30 + " here"):
            for doc in (keys_doc(title={"tv": secret, "phone": "x"}), keys_doc(hint=secret), keys_doc(warn={"tv": "a", "phone": secret}),
                        keys_doc(steps=[{"id": "a", "tv": secret, "phone": "x"}]),
                        keys_doc(chips=[[{"t": secret, "s": "now"}]]), keys_doc(items=[{"label": secret, "s": "ok"}]),
                        keys_doc(action={"kind": "paste", "label": secret})):
                self.assertFalse(ob.write("youtube", doc, now=NOW), secret)
        self.assertFalse(ob.write("youtube", keys_doc(code=AIZA), now=NOW))
        self.assertFalse(ob.write("youtube", keys_doc(link="https://x.example/?k=" + AIZA), now=NOW))
        self.assertFalse(ob.write("youtube", keys_doc(link="https://x.example/?k=" + SECRET), now=NOW))
        self.assertEqual(os.listdir(ob.DIR) if os.path.isdir(ob.DIR) else [], [])

    def test_a_document_somebody_else_wrote_with_a_secret_is_not_read(self):
        ob.write("youtube", keys_doc(), now=NOW)
        path = os.path.join(ob.DIR, "youtube.json")
        d = load(path)
        d["hint"] = {"tv": "key " + AIZA, "phone": ""}
        save(path, d)
        self.assertIsNone(ob.read("youtube", now=NOW))

    def test_ordinary_text_is_not_mistaken_for_a_secret(self):
        for text in ("Publish it, or the TV gets signed out after 7 days.", "App name: TV", "KQX-7MD-P4W", "Step 2 of 4",
                     "https://www.youtube.com/activate?user_code=KQX-7MD-P4W"):
            self.assertFalse(ob.looks_secret(text, texty=not text.startswith("http") and "-" not in text[:4]), text)
        self.assertTrue(ob.write("youtube", keys_doc(code="KQX-7MD-P4W", link="https://www.youtube.com/activate?user_code=KQX-7MD-P4W"), now=NOW))

    def test_advance_moves_the_step_and_keeps_the_lifetime(self):
        ob.write("youtube", keys_doc(step=1), now=NOW, ttl=100)
        self.assertTrue(ob.advance("youtube", 2, now=NOW + 10))
        d = ob.read("youtube", now=NOW + 11)
        self.assertEqual((d["step"], d["expires"]), (2, NOW + 100))
        self.assertFalse(ob.advance("missing", 2))
        ob.write("youtube", keys_doc(state="done"), now=NOW)
        self.assertFalse(ob.advance("youtube", 1, now=NOW))

    def test_extend_is_a_heartbeat_that_never_revives_or_overshoots(self):
        ob.write("youtube", keys_doc(), now=NOW, ttl=30)
        self.assertTrue(ob.extend("youtube", 90, until=NOW + 500, now=NOW + 20))
        self.assertEqual(ob.read("youtube", now=NOW + 21)["expires"], NOW + 110)
        self.assertTrue(ob.extend("youtube", 90, until=NOW + 100, now=NOW + 40))
        self.assertEqual(ob.read("youtube", now=NOW + 41)["expires"], NOW + 100)
        self.assertFalse(ob.extend("youtube", 90, now=NOW + 200))        # expired: stays gone
        ob.write("sweettv", keys_doc(state="failed"), now=NOW)
        self.assertFalse(ob.extend("sweettv", 90, now=NOW))

    def test_an_unwritable_directory_is_not_an_error(self):
        old = ob.DIR
        try:
            ob.DIR = os.path.join(TMP, "file-in-the-way")
            open(ob.DIR, "w").close()
            self.assertFalse(ob.write("youtube", keys_doc(), now=NOW))
        finally:
            ob.DIR = old


class Guide(unittest.TestCase):
    def test_signin_document_has_three_steps_in_both_languages(self):
        doc = guide.document("youtube", "active", "KQX-7MD-P4W", "https://www.youtube.com/activate?user_code=KQX-7MD-P4W")
        d = ob.build("youtube", doc, now=NOW)
        self.assertEqual([s["id"] for s in d["steps"]], ["open", "account", "allow"])
        self.assertEqual((d["flow"], d["step"], d["code"]), ("signin", 1, "KQX-7MD-P4W"))
        self.assertEqual(d["title"]["tv"], "Continue on your phone")
        self.assertEqual(d["kicker"]["tv"], "YouTube · sign in")
        self.assertEqual(d["action"]["kind"], "link")
        self.assertTrue(all(s["tv"] and s["phone"] for s in d["steps"]))

    def test_codes_in_a_row_are_counted_in_the_kicker(self):
        d = guide.document("youtube", "active", "A", "", step=2, steps=4)
        self.assertEqual(d["kicker"]["tv"], "YouTube · sign in · code 2 of 4")
        self.assertNotIn("action", d)

    def test_results_and_unknown_services(self):
        done = guide.document("sweettv", "done")
        self.assertEqual((done["step"], done["title"]["tv"]), (3, "Signed in"))
        self.assertNotIn("hint", done)
        self.assertEqual(guide.document("sweettv", "failed")["title"]["tv"], "Sign-in did not work")
        self.assertEqual(guide.document("sweettv", "cancelled")["title"]["tv"], "Sign-in cancelled")
        self.assertIsNone(guide.document("nope", "active"))
        self.assertFalse(guide.known("nope"))


class SigninFeedsOnboarding(unittest.TestCase):
    def setUp(self):
        for service in ms.SERVICES:
            ms.begin(service)

    def test_waiting_publishes_an_active_document_and_leaves_the_old_state_alone(self):
        ms.publish("youtube", "waiting", code="KQX-7MD-P4W", url="https://www.youtube.com/activate")
        d = ob.read("youtube")
        self.assertEqual((d["state"], d["flow"], d["code"]), ("active", "signin", "KQX-7MD-P4W"))
        self.assertEqual(d["link"], "https://www.youtube.com/activate?user_code=KQX-7MD-P4W")
        old = ms.read("youtube")
        self.assertEqual((old["state"], old["code"]), ("waiting", "KQX-7MD-P4W"))
        self.assertNotIn("flow", old)        # the old file keeps its own shape

    def test_lifetime_is_short_and_a_heartbeat_extends_it(self):
        ms.publish("youtube", "waiting", code="A-B", url="https://www.youtube.com/activate")
        d = ob.read("youtube")
        self.assertEqual(d["expires"] - d["updated"], ms.ONBOARD_ALIVE)
        ms.publish("sweettv", "waiting", code="12345", url="https://sweet.tv/addDevice", ttl=20)
        d = ob.read("sweettv")
        self.assertEqual(d["expires"] - d["updated"], 20)
        self.assertTrue(ms.touch("youtube"))
        self.assertIsNotNone(ob.read("youtube"))

    def test_results_are_published_and_begin_clears(self):
        for state in ("done", "failed", "cancelled"):
            ms.publish("youtube", "waiting", code="A-B", url="https://www.youtube.com/activate")
            ms.publish("youtube", state)
            d = ob.read("youtube")
            self.assertEqual(d["state"], state)
            self.assertEqual(d["expires"] - d["updated"], ob.RESULT_TTL)
        ms.begin("youtube")
        self.assertIsNone(ob.read("youtube"))

    def test_a_partner_sign_in_has_nobody_on_the_phone(self):
        ms.publish("youtube", "waiting", code="A-B", url="https://www.youtube.com/activate")
        ms.publish("youtube", "waiting", code="A-B", url="https://www.youtube.com/activate", mode=ms.PARTNER)
        self.assertIsNone(ob.read("youtube"))
        self.assertEqual(ms.read("youtube")["state"], "waiting")

    def test_a_broken_onboarding_never_breaks_the_sign_in(self):
        old = ob.DIR
        try:
            ob.DIR = os.path.join(TMP, "file-in-the-way")
            open(ob.DIR, "w").close()
            self.assertTrue(ms.publish("youtube", "waiting", code="A-B", url="https://www.youtube.com/activate"))
            self.assertEqual(ms.read("youtube")["state"], "waiting")
        finally:
            ob.DIR = old


if __name__ == "__main__":
    unittest.main()
