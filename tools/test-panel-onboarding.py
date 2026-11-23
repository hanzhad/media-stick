#!/usr/bin/env python3
"""Offline test of the phone side of the shared onboarding channel (no Kodi, no device):
python3 tools/test-panel-onboarding.py

The panel's status carries the live documents of mediastick_onboarding (schema fields only, no TV-only chips),
works without the library, and the injected page has the one universal sheet whose script reaches links only
through the Accounts page's whitelist helper."""
import http.client
import importlib.machinery
import importlib.util
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)

import mediastick_onboarding as mo  # noqa: E402
import panel_onboarding_ui as ui  # noqa: E402


def load_panel(name, library=True):
    """The real `panel` as a module; `library=False`: the import of mediastick_onboarding fails, as on a device without it."""
    saved = sys.modules.get("mediastick_onboarding")
    if not library:
        sys.modules["mediastick_onboarding"] = None
    try:
        loader = importlib.machinery.SourceFileLoader(name, PANEL)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["mediastick_onboarding"] = saved
    return mod


def doc(service="youtube", **kw):
    d = {"flow": "signin", "kicker": {"tv": "YouTube", "phone": "ТВ попросил вход"},
         "title": {"tv": "Continue on your phone", "phone": "Войти в YouTube"}, "step": 2,
         "steps": [{"id": "open", "tv": "Open", "phone": "Откройте страницу"},
                   {"id": "account", "tv": "Account", "phone": "Выберите аккаунт"},
                   {"id": "allow", "tv": "Allow", "phone": "Разрешите доступ"}],
         "code": "KQX-7MD-P4W", "link": "https://www.google.com/device?user_code=KQX-7MD-P4W",
         "action": {"kind": "link", "label": "Вернуться на страницу входа", "url": "https://accounts.google.com/x"},
         "hint": {"tv": "Hint", "phone": "Подсказка"}, "chips": [[{"t": "Get started", "s": "now"}]],
         "items": [{"id": "api_key", "label": "Ключ", "s": "ok"}]}
    d.update(kw)
    assert mo.write(service, d, ttl=600)
    return d


def clear_all():
    for name in (os.listdir(mo.DIR) if os.path.isdir(mo.DIR) else []):
        os.unlink(os.path.join(mo.DIR, name))


class Status(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel("panel_ob_with")
        cls.bare = load_panel("panel_ob_without", library=False)

    def setUp(self):
        clear_all()

    def test_no_document_is_an_empty_list(self):
        self.assertEqual(self.panel.onboarding_docs(), [])

    def test_active_documents_only_with_schema_fields(self):
        doc("youtube")
        mo.write("sweettv", {"flow": "signin", "state": "done", "title": "x", "steps": [{"phone": "a"}]})
        got = self.panel.onboarding_docs()
        self.assertEqual([d["service"] for d in got], ["youtube"])
        d = got[0]
        self.assertNotIn("chips", d)
        self.assertTrue(set(d) <= set(self.panel.ONBOARDING_FIELDS))
        self.assertEqual((d["flow"], d["step"], d["code"]), ("signin", 2, "KQX-7MD-P4W"))
        self.assertEqual(d["steps"][1]["phone"], "Выберите аккаунт")

    def test_unknown_fields_of_a_foreign_file_are_dropped(self):
        os.makedirs(mo.DIR, exist_ok=True)
        data = mo.build("youtube", {"flow": "keys", "title": "t", "steps": [{"phone": "a"}]})
        data["extra"] = "nope"
        with open(os.path.join(mo.DIR, "youtube.json"), "w", encoding="utf-8") as f:
            json.dump(data, f)
        self.assertNotIn("extra", self.panel.onboarding_docs()[0])

    def test_without_the_library(self):
        doc("youtube")
        self.assertIsNone(self.bare.mediastick_onboarding)
        self.assertEqual(self.bare.onboarding_docs(), [])

    def test_a_broken_library_does_not_break_status(self):
        class Boom:
            @staticmethod
            def list_active():
                raise RuntimeError("x")
        saved, self.panel.mediastick_onboarding = self.panel.mediastick_onboarding, Boom
        try:
            self.assertEqual(self.panel.onboarding_docs(), [])
        finally:
            self.panel.mediastick_onboarding = saved


class FakeKodi:
    def __call__(self, method, params=None, timeout=3):
        if method.startswith("Player."):
            return []
        return {}


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel("panel_ob_served")
        cls.panel.kodi = FakeKodi()
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.panel.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def setUp(self):
        clear_all()
        self.panel.status_cache.update(t=0.0, s=None)

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Host": "localhost:%d" % self.port})
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        return r.status, raw

    def test_status_has_the_key_and_it_is_empty(self):
        status, raw = self.get("/api/status")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(raw)["onboarding"], [])

    def test_status_carries_the_active_document(self):
        doc("youtube")
        status, raw = self.get("/api/status")
        body = json.loads(raw)
        self.assertEqual([d["service"] for d in body["onboarding"]], ["youtube"])
        self.assertNotIn("chips", raw)

    def test_page_has_the_sheet_and_the_poll_hook(self):
        status, raw = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(raw.count('id="ob-sheet"'), 1)
        self.assertIn("if(window.obNote)obNote(s.onboarding)", raw)
        self.assertEqual(raw.count("</body>"), 1)
        self.assertNotIn("@@ACC_", raw)


class Page(unittest.TestCase):
    def test_sheet_markup_and_hooks(self):
        page = ui.inject("<html><body>x</body></html>")
        for needle in ('id="ob-sheet"', 'role="dialog"', 'aria-live="polite"', 'id="ob-mini"', 'id="ob-hide"',
                       "function obNote", "ykOpen(true)", "copyText(", "acc-yk", "ob-min", "ob-spin",
                       "Код, если спросят", "Скопировать", "Готово", "шаг "):
            self.assertIn(needle, page, needle)
        self.assertEqual(page.count("</body>"), 1)
        self.assertEqual(ui.inject("<html></html>"), "<html></html>")

    def test_chips_are_not_drawn(self):
        self.assertNotIn("chips", ui.TAIL)

    def test_buttons_are_real_buttons(self):
        self.assertNotRegex(ui.TAIL, r"<div[^>]*onclick")
        for i in ("ob-hide", "ob-copy", "ob-paste", "ob-mini", "ob-cancel", "ob-renew"):
            self.assertRegex(ui.TAIL, r'<button id="%s"' % i)

    def test_links_only_through_the_safe_helper(self):
        js = ui.TAIL
        self.assertIn("accSafe(", js)
        self.assertNotRegex(js, r"window\.open|location\.(href|assign|replace)|\.src\s*=")
        # the one place a href is set takes the checked value, and that value comes from obSafe()
        hrefs = re.findall(r"\.href\s*=\s*([^;}]+)", js)
        self.assertEqual(hrefs, ["url"])
        self.assertRegex(js, r"url=kind==='link'\?obSafe\(")
        self.assertEqual(js.count("innerHTML"), 1)      # only the check mark, a constant; texts are textContent

    def test_rules_of_the_page(self):
        self.assertNotRegex(ui.TAIL, r"confirm\(|alert\(|prompt\(")
        self.assertNotIn("fetch(", ui.TAIL)       # it only draws what the status poll brings

    def test_does_not_pop_up_over_the_key_wizard_but_the_sign_in_is_never_held_back_by_the_old_sheet(self):
        js = ui.TAIL
        self.assertRegex(js, r"d\.flow==='keys'&&!!y&&!y\.classList\.contains\('hide'\)")
        suppressed = js.split("function obSuppressed(d){", 1)[1].split("\n}\n", 1)[0]
        self.assertNotIn("acc-sheet", suppressed)                    # the old sheet no longer makes this one yield ...
        self.assertNotIn("accSheet", suppressed)
        self.assertNotIn("acc-sheet", js)                            # ... nor is it looked at anywhere here
        self.assertNotIn("accSheet", js)
        self.assertIn("!obSuppressed(d)", js)

    def test_a_new_code_brings_a_minimized_sheet_back_and_buzzes(self):
        js = ui.TAIL
        self.assertIn("const obKey=d=>d.service+'|'+d.flow+'|'+(d.step|0)+'|'+obStr(d.code);", js)
        self.assertIn("if(obHid[d.service]&&obHid[d.service]!==obKey(d))delete obHid[d.service]", js)
        self.assertIn("prevKey=obCurKey", js)
        self.assertIn("if(!hid&&(fresh||wasMin||(prevKey&&prevKey!==obCurKey)))buzz()", js)    # also when it was already up
        self.assertIn("obSig=sig;obRender(d)", js)                                             # the new code replaces the old in the same sheet
        self.assertIn("d.code,d.link", js.split("sig=JSON.stringify(", 1)[1].split(")", 1)[0])

    def test_the_sign_in_sheet_can_cancel_and_sweettv_can_renew(self):
        js = ui.TAIL
        self.assertIn("accCall('cancel',{service:svc})", js)         # the Accounts page's own call, no fetch here
        self.assertIn("accCall('renew',{service:obCur})", js)
        self.assertIn("armed('ob-renew','Нажмите ещё раз, чтобы обновить код')", js)   # the old code dies: two taps, the same words
        self.assertIn("bc.classList.toggle('hide',!signin)", js)
        self.assertIn("br.classList.toggle('hide',!(signin&&d.service==='sweettv'))", js)
        self.assertIn('<button id="ob-cancel" class="btn wide hide" type="button">Отмена</button>', js)
        self.assertIn('<button id="ob-renew" class="btn wide hide" type="button">Обновить код</button>', js)
        self.assertIn("Скопировать", js)                                                   # nothing else is lost
        self.assertIn('id="ob-open"', js)

    def test_a_sign_in_counts_by_its_kicker_only_not_by_steps(self):
        js = ui.TAIL
        self.assertIn("const prog=n&&cur&&!signin?'шаг '+cur+' из '+n:''", js)           # a key wizard keeps its step counter
        self.assertIn("kick.match(/подтверждение \\d+ из \\d+/)", js)                     # the minimized bar says which approval
        self.assertIn("Введите этот код на странице входа", js)                         # a link without the code: the code is needed

    def test_hidden_doc_stays_hidden_until_the_step_changes(self):
        self.assertIn("obHid[d.service]!==obKey(d)", ui.TAIL)

    def test_no_leftover_marker(self):
        self.assertEqual(re.findall(r"@@\w+@@", ui.TAIL), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
