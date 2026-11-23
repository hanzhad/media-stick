#!/usr/bin/env python3
"""Offline test of the panel's frame (no Kodi, no device):
python3 tools/test-panel-tabs.py

Three tabs (Смотреть, Пульт, Настройки), the remote's mode switch (Кнопки, Указка, Экран) and the links that open
them, the settings cards in their order, the header that says what the TV is doing, the `screen` field of the
status, one palette. The page is checked as text (there is no node here); the one script check is that every
<script> of it has balanced brackets and no marker left."""
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
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
PANEL = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "panel")
TMP = tempfile.mkdtemp()
os.environ["MEDIASTICK_SIGNIN_DIR"] = os.path.join(TMP, "signin")
os.environ["MEDIASTICK_ONBOARDING_DIR"] = os.path.join(TMP, "onboarding")
os.environ["MEDIASTICK_YTCHANNEL_OFF"] = "1"       # never ask Google from a test
os.environ["MEDIASTICK_ADDON_DATA"] = os.path.join(TMP, "addon_data")
os.environ["MEDIASTICK_SCREEN_DIR"] = os.path.join(TMP, "screen")
os.environ["PANEL_STATE_DIR"] = os.path.join(TMP, "state")
sys.dont_write_bytecode = True
sys.path.insert(0, LIB)


def load_panel(name, screen=True):
    """The real `panel` as a module; `screen=False`: the import of mediastick_screen fails, as on a device without it."""
    saved = sys.modules.get("mediastick_screen")
    if not screen:
        sys.modules["mediastick_screen"] = None
    try:
        loader = importlib.machinery.SourceFileLoader(name, PANEL)
        spec = importlib.util.spec_from_loader(loader.name, loader)
        mod = importlib.util.module_from_spec(spec)
        loader.exec_module(mod)
    finally:
        if saved is not None:
            sys.modules["mediastick_screen"] = saved
        elif not screen:
            sys.modules.pop("mediastick_screen", None)
    return mod


def unbalanced(js):
    """The first bracket that does not match, or None. Skips strings, template literals, comments and regex
    literals (a regex is taken where an operand is expected: after `( , = : [ ! & | ? { } ;` or at the start)."""
    stack, i, n, prev = [], 0, len(js), ""
    pairs = {")": "(", "]": "[", "}": "{"}
    while i < n:
        c = js[i]
        if c in "'\"`":
            j = i + 1
            while j < n and js[j] != c:
                j += 2 if js[j] == "\\" else 1
            i, prev = j + 1, "x"
            continue
        if js.startswith("//", i):
            i = js.find("\n", i)
            i = n if i < 0 else i
            continue
        if js.startswith("/*", i):
            i = js.find("*/", i) + 2
            continue
        if c == "/" and (prev == "" or prev in "(,=:[!&|?{};"):
            j, cls = i + 1, False
            while j < n and (cls or js[j] != "/"):
                if js[j] == "\\":
                    j += 1
                elif js[j] == "[":
                    cls = True
                elif js[j] == "]":
                    cls = False
                j += 1
            i, prev = j + 1, "x"
            continue
        if c in "([{":
            stack.append((c, i))
        elif c in pairs:
            if not stack or stack.pop()[0] != pairs[c]:
                return js[max(0, i - 60):i + 20]
        if not c.isspace():
            prev = c
        i += 1
    return js[stack[-1][1]:stack[-1][1] + 80] if stack else None


class Page(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel("panel_tabs_page")
        cls.page = cls.panel.PAGE

    def test_three_tabs_watch_first_and_default(self):
        tabs = re.findall(r'<button data-go="(\w+)"', self.page)
        self.assertEqual(tabs, ["watch", "remote", "settings"])
        self.assertIn('<button data-go="watch" class="on">', self.page)
        self.assertIn("let tab='watch'", self.page)
        for gone in ('data-go="screen"', 'data-go="info"', 'data-go="accounts"', 'data-tab="screen"', 'data-tab="info"'):
            self.assertNotIn(gone, self.page)

    def test_the_tab_and_the_mode_are_remembered_and_read_back(self):
        for s in ("lsSet('tab',tab)", "lsSet('mode',m)", "lsGet('mode')", "lsGet('tab')"):
            self.assertIn(s, self.page)
        self.assertIn("try{return localStorage.getItem(k)}catch(e){return null}", self.page)
        self.assertIn("try{localStorage.setItem(k,v)}catch(e){}", self.page)
        self.assertIn("TABS.includes(t)&&t!=='watch'", self.page)    # a phone opens on the tab used last, watch otherwise
        self.assertNotIn("localStorage.setItem('tab'", self.page)   # the write that was never read is gone
        self.assertNotIn("tab==='air'", self.page)
        self.assertNotIn("airmode", self.page)

    def test_the_remote_has_a_mode_switch_of_three(self):
        sw = self.page.split('class="modes"', 1)[1].split("</div>", 1)[0]
        self.assertEqual(re.findall(r'data-m="(\w+)"[^>]*>([^<]+)<', sw), [("keys", "Кнопки"), ("air", "Указка"), ("screen", "Экран")])
        self.assertLess(self.page.index('class="modes"'), self.page.index('class="card rc"'))
        self.assertNotIn('id="mode"', self.page)                    # the round air toggle is gone
        self.assertNotIn("airSet", self.page)
        self.assertNotIn("airMode", self.page)
        self.assertIn("function setMode(m)", self.page)

    def test_the_screen_is_the_third_mode_of_the_remote(self):
        remote = self.page.split('<section id="t-remote"', 1)[1].split("</section>", 1)[0]
        self.assertIn('id="t-screen"', remote)
        for i in ('id="shot-box"', 'id="live-btn"', 'id="full-btn"'):
            self.assertIn(i, remote)
        self.assertIn("#t-remote[data-mode=screen] .rc{display:none}", self.page)
        # live starts when the mode is shown on a phone and stops when it is left, as the tab did
        self.assertIn("const screenOn=()=>tab==='remote'&&mode==='screen'", self.page)
        self.assertIn("function screenSync(){if(!wide())setLive(screenOn())}", self.page)

    def test_the_hash_links(self):
        js = self.page
        self.assertIn("if(h==='#air'||h==='#screen'){document.querySelector('[data-go=remote]').click();setMode(h.slice(1));return}", js)
        self.assertIn("if(h==='#accounts'){openAccounts();return}", js)
        self.assertIn("if(h.slice(0,6)!=='#https')return;", js)
        self.assertIn("[?&]sub=([a-z0-9-]+)", js)
        self.assertIn("document.querySelector('[data-go=settings]').click();\n  setTimeout(()=>{$('t-https').scrollIntoView", js)
        self.assertIn("$('t-acc').scrollIntoView", js)
        # booted last: hashGo needs everything above it (it used to run before `let airMode` existed)
        self.assertGreater(js.index("\nhashGo();\n</script>"), js.index("function airUi()"))
        self.assertEqual(js.count("\nhashGo();"), 1)

    def test_every_link_the_device_makes_still_has_its_target(self):
        for root, _, files in os.walk(os.path.join(ROOT, "device")):
            for name in files:
                if name.endswith((".py", ".xml", ".sh")) and root != os.path.join(ROOT, "device", "files", "usr", "local", "bin"):
                    text = open(os.path.join(root, name), encoding="utf-8", errors="ignore").read()
                    for h in re.findall(r"/#(\w+)", text):
                        self.assertIn(h, ("https", "air", "screen", "accounts"), (name, h))

    def test_the_keyboard_jumps_to_the_buttons(self):
        self.assertIn("(tab!=='remote'||mode==='screen')){setMode('keys');", self.page)

    def test_settings_cards_in_order_with_their_headings(self):
        order = ["t-acc", "t-wifi", "t-https", "t-info", "t-act"]
        pos = [self.page.index('<section id="%s" data-tab="settings"' % i) for i in order]
        self.assertEqual(pos, sorted(pos))
        for i, h in (("t-acc", "Аккаунты"), ("t-wifi", "Wi-Fi"), ("t-https", "Пульт как приложение (HTTPS)"),
                     ("t-info", "О приставке"), ("t-act", "Обслуживание")):
            sec = self.page.split('<section id="%s"' % i, 1)[1].split("</section>", 1)[0]
            self.assertIn("<h2>%s</h2>" % h, sec)
        self.assertIn("Обновить сейчас", self.page.split('id="t-act"', 1)[1])

    def test_the_header_says_what_the_tv_is_doing(self):
        js = self.page
        self.assertIn("function tvState(s,now)", js)
        for s in ("'ТВ занят трансляцией с компьютера'", "'ТВ занят трансляцией AirPlay'", "'На ТВ открыто приложение'",
                  "'ТВ не отвечает'", "'ТВ свободен'", "'нет связи с приставкой'", "'ТВ: '+s.playing+' · '", "'пауза'", "'играет'"):
            self.assertIn(s, js)
        self.assertIn("now&&now.playing&&now.speed===0", js)        # the pause comes from what Смотреть knows
        self.assertIn("lastStatus=s;hdrDraw();", js)
        self.assertIn("catch(e){lastStatus=null;hdrDraw()}", js)
        self.assertIn(".dot.warn{background:var(--warn)}", js)
        self.assertNotIn("s.temp+' · '+s.time", js)                  # the Wi-Fi and the temperature left the pill
        self.assertIn("['Сеть',", js)                                # and are in «О приставке»
        self.assertIn("['Температура',", js)

    def test_one_palette(self):
        for gone in ("wt-on", "--wb", "--wc", "--wl", "#0f1115", "#1b1d28"):
            self.assertNotIn(gone, self.page)

    def test_wide_screen_shows_everything_without_the_bar(self):
        wide = self.page.split("@media (min-width:900px){\n  #app{max-width:1360px", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('"top top" "watch watch" "screen remote" "acc acc" "https wifi" "info act"', wide)
        self.assertIn(".tabs,.modes{display:none}", wide)
        self.assertIn("#t-remote{display:contents!important}", wide)
        self.assertIn("#t-screen{display:block!important", wide)

    def test_scripts_have_balanced_brackets_and_no_marker(self):
        scripts = re.findall(r"<script>(.*?)</script>", self.page, re.S)
        self.assertGreaterEqual(len(scripts), 4)
        for s in scripts:
            self.assertIsNone(unbalanced(s))
        self.assertEqual(re.findall(r"@@\w+@@", self.page), [])

    def test_the_balance_check_sees_a_broken_script(self):
        self.assertIsNotNone(unbalanced("function f(){ if(a){ } "))
        self.assertIsNotNone(unbalanced("f(]"))
        self.assertIsNone(unbalanced("a('}'); b(/[)]\"/g); // {\n`x${y}`; /* ( */"))


class Screen(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel("panel_tabs_screen")
        cls.bare = load_panel("panel_tabs_bare", screen=False)

    def test_the_owner_goes_into_the_status_field(self):
        for who in ("miracast", "airplay", "web-app", ""):
            with mock.patch.object(self.panel.mediastick_screen, "owner", return_value=who):
                self.assertEqual(self.panel.screen_owner(), who)

    def test_a_broken_library_or_none_is_an_empty_owner(self):
        with mock.patch.object(self.panel.mediastick_screen, "owner", side_effect=RuntimeError):
            self.assertEqual(self.panel.screen_owner(), "")
        self.assertIsNone(self.bare.mediastick_screen)
        self.assertEqual(self.bare.screen_owner(), "")


class Served(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel("panel_tabs_served")

        def kodi(method, params=None, timeout=3):
            return [] if method.startswith("Player.") else {}
        cls.panel.kodi = kodi
        cls.srv = ThreadingHTTPServer(("127.0.0.1", 0), cls.panel.H)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()

    def get(self, path):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("GET", path, headers={"Host": "localhost:%d" % self.port})
        r = c.getresponse()
        raw = r.read().decode("utf-8")
        c.close()
        return r.status, raw

    def test_status_has_the_screen_field(self):
        for who in ("miracast", ""):
            self.panel.status_cache.update(t=0.0, s=None)
            with mock.patch.object(self.panel.mediastick_screen, "owner", return_value=who):
                status, raw = self.get("/api/status")
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(raw)["screen"], who)

    def test_the_served_page_has_the_tabs(self):
        status, raw = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(re.findall(r'<button data-go="(\w+)"', raw), ["watch", "remote", "settings"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
