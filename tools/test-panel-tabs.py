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
        self.assertNotIn('class="modes"', self.page)
        self.assertNotIn(".modes [data-m]", self.page)
        self.assertIn("MODES = ['keys', 'air', 'screen']", self.page.replace('"', "'"))
        self.assertNotIn('id="mode"', self.page)                    # the round air toggle is gone
        self.assertNotIn("airSet", self.page)
        self.assertNotIn("airMode", self.page)
        self.assertIn("function setMode(m)", self.page)

        # Mobile-only .mode-corners at top of .rc (above .dwrap) and at top of #t-screen > .card (above .head)
        rc_html = self.rc()
        self.assertIn('class="mode-corners"', rc_html)
        self.assertLess(rc_html.index('class="mode-corners"'), rc_html.index('id="stage"'))
        screen = self.page.split('<div id="t-screen">', 1)[1].split("</section>", 1)[0]
        self.assertIn('class="mode-corners"', screen)
        self.assertLess(screen.index('class="mode-corners"'), screen.index('class="head"'))

        # Corner mode switchers cycle keys <-> air <-> screen with data-mode-go + icon + label
        for mode_go in ("keys", "air", "screen"):
            self.assertIn(f'data-mode-go="{mode_go}"', self.page)
        for icon in ("#i-cam", "#i-air", "#i-remote"):
            self.assertIn(icon, self.page)

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
        # every settings page has its hash; a hash opens the tab and the page; no hash on the tab is the list
        self.assertIn("const SP_HASH={acc:'accounts',lang:'language',wifi:'wifi',https:'https',info:'device',act:'maintenance'}", js)
        self.assertIn("SP_OF.apps='acc'", js)
        self.assertIn("const p=SP_OF[h.replace(/[?].*$/,'').slice(1)];", js)
        self.assertIn("if(!p){if(tab==='settings'&&spage)setPage('');return}", js)
        self.assertIn("function openAccounts(){goPage('acc')}", js)
        self.assertIn("[?&]sub=([a-z0-9-]+)", js)
        self.assertIn("openSettings(p);", js)
        self.assertIn("if(wide())setTimeout(()=>$(SP_ID[p]).scrollIntoView", js)
        # booted last: hashGo needs everything above it (it used to run before `let airMode` existed)
        self.assertGreater(js.index("\nhashGo();\n</script>"), js.index("function airUi()"))
        self.assertEqual(js.count("\nhashGo();"), 1)

    def test_every_link_the_device_makes_still_has_its_target(self):
        for root, _, files in os.walk(os.path.join(ROOT, "device")):
            for name in files:
                if name.endswith((".py", ".xml", ".sh")) and root != os.path.join(ROOT, "device", "files", "usr", "local", "bin"):
                    with open(os.path.join(root, name), encoding="utf-8", errors="ignore") as f:
                        text = f.read()
                    for h in re.findall(r"/#(\w+)", text):
                        self.assertIn(h, ("https", "air", "screen", "accounts"), (name, h))

    def test_the_keyboard_jumps_to_the_buttons(self):
        self.assertIn("(tab!=='remote'||mode==='screen')){setMode('keys');", self.page)

    def test_settings_cards_in_order_with_their_headings(self):
        order = ["t-acc", "t-wifi", "t-https", "t-info", "t-act"]
        pos = [self.page.index('<section id="%s" data-tab="settings"' % i) for i in order]
        self.assertEqual(pos, sorted(pos))
        for i, h in (("t-acc", "Приложения"), ("t-wifi", "Wi-Fi"), ("t-https", "Пульт как приложение (HTTPS)"),
                     ("t-info", "О приставке"), ("t-act", "Обслуживание")):
            sec = self.page.split('<section id="%s"' % i, 1)[1].split("</section>", 1)[0]
            self.assertRegex(sec, r"<h2[^>]*>%s</h2>" % re.escape(h))
        self.assertIn("Обновить сейчас", self.page.split('id="t-act"', 1)[1])

    def test_the_header_says_what_the_tv_is_doing(self):
        js = self.page
        self.assertIn("function tvState(s,now)", js)
        for s in ("'ТВ занят трансляцией с компьютера'", "'ТВ занят трансляцией AirPlay'", "'На ТВ открыто приложение'",
                  "'ТВ не отвечает'", "'ТВ свободен'", "'нет связи с приставкой'", "'Пауза: ':'Играет: ')+s.playing"):
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
        self.assertIn('"top top" "watch watch" "screen remote" "acc acc" "https wifi" "info act" "lang lang"', wide)
        self.assertIn(".mode-corners", wide)
        self.assertIn("display:none!important", wide)
        self.assertIn("#t-remote{display:contents!important}", wide)
        self.assertIn("#t-remote .rc-shell{display:flex!important;flex-direction:column;gap:8px;grid-area:remote}", wide)
        self.assertIn("#t-screen{display:block!important", wide)

    def rc(self):
        return self.page.split('<div class="card rc">', 1)[1].split('<div id="t-screen">', 1)[0]

    def test_the_remote_card_is_never_replaced_by_the_player(self):
        for gone in ("wtdp", "wtnp", "wt-npbox", "wt-pback", "wt-pfull", "Крестовина", "W.rp"):
            self.assertNotIn(gone, self.page)
        self.assertEqual(self.page.count('<div data-wtbar'), 2)       # the bar of «Смотреть» and the bar of «Пульт»
        # the bar is above .rc-shell (#touchbar + .rc), and .rc fits iPhone SE (min-height:340px) + .tb-on height rules
        remote = self.page.split('<section id="t-remote"', 1)[1]
        self.assertIn('class="rc-shell"', remote)
        self.assertIn('id="touchbar"', remote)
        self.assertLess(remote.index("data-wtbar"), remote.index('class="rc-shell"'))
        self.assertLess(remote.index('id="touchbar"'), remote.index('class="card rc"'))
        self.assertIn("min-height:340px", self.page)
        self.assertNotIn("min-height:400px", self.page)
        self.assertIn(".rc-shell.tb-on .rc", self.page)
        self.assertIn("body.np .rc-shell.tb-on .rc", self.page)

    def test_the_buttons_mode_rows(self):
        rows = [re.findall(r'(?:data-a|id)="([\w-]+)"', g) for g in self.rc().split('<div class="grp">')[1:]]
        self.assertEqual(rows, [["back", "home", "contextmenu", "txt-open", "btn-search-rc"], ["volumedown", "mute", "volumeup"]])
        self.assertIn('data-a="contextmenu" aria-label="Ещё"', self.rc())
        self.assertIn('id="txt-open" aria-label="Текст"', self.rc())
        self.assertIn('id="btn-search-rc"', self.rc())
        self.assertIn('aria-label="Поиск"', self.rc())
        self.assertIn('<symbol id="i-search"', self.page)
        self.assertNotIn("shot-save-rc", self.rc())
        for gone in ("rewind", "fastforward", "playpause", '"stop"', '"info"', '"osd"', "Инфо", "Панель"):
            self.assertNotIn(gone, self.rc())
        self.assertIn('data-a="select"', self.rc())                  # the D-pad stays

    def test_the_screen_mode_row(self):
        screen = self.page.split('<div id="t-screen">', 1)[1].split("</section>", 1)[0]
        row = screen.split('<div class="grp">', 1)[1].split("</div>", 1)[0]
        self.assertEqual(re.findall(r'data-a="(\w+)"', row), ["back", "home", "contextmenu"])

    def test_the_computer_keyboard_shortcuts_stay(self):
        self.assertIn("const KEYS={ArrowUp:'up',ArrowDown:'down',ArrowLeft:'left',ArrowRight:'right',Enter:'select',Backspace:'back',"
                      "Escape:'back',' ':'playpause',c:'contextmenu',i:'info',h:'home','+':'volumeup','-':'volumedown',m:'mute'};", self.page)

    def test_the_text_field_is_gone_and_the_button_opens_the_overlay(self):
        for gone in ('id="txt"', "Текст в поиск Kodi", "sendText"):
            self.assertNotIn(gone, self.page)
        js = self.page
        self.assertIn("function kbManual()", js)
        self.assertIn("$('txt-open').addEventListener('click',()=>{buzz();kbManual()})", js)
        self.assertIn("$('kb-t').textContent='Текст на ТВ';$('kb-x').textContent='Закрыть'", js)
        self.assertIn("if(!k&&kbMan)return;", js)                    # the status poll does not close it
        self.assertIn("if(kbMan){kbMan=false;kbOpen=false;", js)     # the TV's own keyboard takes over
        self.assertIn("function kbClose(){kbMan=false;kbUi(null);", js)     # «Готово» (done:true) closes it
        self.assertIn("kbSend(true);kbClose()", js)
        self.assertIn("api('/api/text',{text:v,done:!!done}).catch(keyFailed)", js)
        # «Закрыть» only hides it
        self.assertIn("$('kb-x').addEventListener('click',()=>{if(kbMan){kbMan=false;kbOpen=false;$('kb-in').blur();"
                      "$('kb').classList.add('hide')", js)

    def test_contextual_search_isolates_kb_mode_and_submits_only_on_enter(self):
        js = self.page
        self.assertIn("btn-search-rc", js)
        self.assertIn("ctx_search", js)
        self.assertIn("kbMode", js)
        self.assertIn("ui_cmd", js)
        self.assertIn("can_search", js)
        self.assertIn("search_query", js)
        self.assertIn("search_hint", js)

    def test_one_toast_and_failed_keys_say_so(self):
        js = self.page
        self.assertEqual(js.count('id="toast"'), 1)
        self.assertIn("function toast(text)", js)
        self.assertIn("function keyFailed(e){const now=Date.now();if(now-failAt<2000)return;failAt=now;toast(tvErr(e))}", js)
        self.assertIn("return 'ТВ не ответил'", js)
        self.assertIn("if(!e||!e.http)return 'ТВ не ответил';", js)  # unreachable box: no server message to quote
        self.assertIn("e.http=r.status", js)                         # a rejected reply carries its status and text
        self.assertIn("api('/api/key',{action:a}).then(", js)
        self.assertIn(".catch(keyFailed);\n  clearTimeout(tickSoon)", js)
        self.assertIn("function pressKey(a)", js)
        self.assertIn(".toast{position:fixed", js)
        self.assertNotIn("wt-toast", js)

    def test_settings_is_a_list_of_rows_and_each_opens_a_page(self):
        lst = self.page.split('id="t-setlist"', 1)[1].split("</section>", 1)[0]
        self.assertEqual(re.findall(r'data-sp="(\w+)"', lst), ["acc", "wifi", "https", "lang", "info", "act"])
        self.assertEqual(re.findall(r'class="sname">([^<]+)<', lst),
                         ["Приложения", "Wi-Fi", "Пульт как приложение", "Язык", "О приставке", "Обслуживание"])
        self.assertEqual(lst.count('class="chev" aria-hidden="true">›<'), 6)
        self.assertNotIn("wt-resume", lst)
        self.assertNotIn("@@RESUME_ROW@@", lst)
        self.assertNotIn("До 720p", lst)
        for i in ("sv-acc", "sv-wifi", "sv-https", "sv-info"):
            self.assertIn('id="%s"' % i, lst)
        for page, sec in (("acc", "t-acc"), ("wifi", "t-wifi"), ("https", "t-https"), ("info", "t-info"), ("act", "t-act")):
            self.assertRegex(self.page, r'<section id="%s" data-tab="settings" data-spage="%s"' % (sec, page))
        self.assertLess(self.page.index('id="t-setlist"'), self.page.index('id="t-acc"'))
        js = self.page
        self.assertIn("function setPage(p)", js)
        self.assertIn("b.textContent='‹ Настройки'", js)
        self.assertIn("function spBack()", js)
        self.assertIn("history.back()", js)                          # the browser's back button works through the hash
        self.assertIn("if(again&&spage)spBack();", js)               # a second tap on the tab comes back to the list
        # the states on the right of the rows
        self.assertIn("function accRowText()", js)
        self.assertIn("'YouTube: '+(cur?accName(cur):'не выполнен вход')+' · SWEET.TV: '+(sw&&sw.signed_in?'вход выполнен':'нет')", js)
        self.assertIn("v('sv-wifi',s.wifi.ssid||'кабель')", js)
        self.assertIn("HTTPS_RE.test(httpsUrl)?'включено':'выключено'", js)
        self.assertIn("need?'нужно внимание':'всё в порядке'", js)
        self.assertIn("needAttention=s=>powerState(s)===true||tempC(s)>HOT_C||s.disk_free_gb<1", js)

    def test_device_info_in_plain_words(self):
        js = self.page
        for s in ("function ruUptime(up)", "function ruNextCheck(next,mins)", "const ruDate=", "const ruDur=", "'меньше минуты'",
                  "function ruAgo(mins)", "'слабый блок питания — приставка может тормозить'", "dot(true)+'в норме'",
                  "const POWER_NOW=0x1|0x2|0x4,", "const HOT_C=75;", "' · '+dot(false)+'высокая'",
                  "class=\"dsub\"", "ruDate(s.commit_date)", "['Версия',", "['Сеть',", "['Температура',"):
            self.assertIn(s, js)
        for hex_or_english in ("esc(s.throttled)", "просадка", "esc(s.uptime)", "esc(s.next_update", "['Kodi',"):
            self.assertNotIn(hex_or_english, js)

    def test_one_confirmation_phrase(self):
        labels = re.findall(r"armed\([^,()]+,\s*'([^']+)'\)", self.page)
        labels += re.findall(r"ask='([^']+)'", self.page)   # the sign-out rows keep the phrase in a variable
        self.assertGreaterEqual(len(labels), 6)
        for l in labels:
            self.assertTrue(l.startswith("Нажмите ещё раз, чтобы "), l)
        for want in ("перезагрузить", "сменить", "отключить", "выйти", "удалить", "обновить код"):
            self.assertIn("Нажмите ещё раз, чтобы " + want, labels)
        for gone in ("Точно ", "чтобы подтвердить"):
            self.assertNotIn(gone, self.page)

    def test_sheets_share_one_look(self):
        css = self.page
        self.assertIn(".sheet{position:fixed;inset:0;z-index:var(--z-sheet)", css)
        self.assertIn(".sheet-box::before{content:", css)             # the handle bar
        self.assertIn("@media (min-width:900px){.sheet{align-items:center}.sheet-box{max-width:480px;border-radius:24px}}", css)
        for sid, back in (("acc-sheet", "acc-back"), ("ob-sheet", "ob-back"), ("acc-yk", "acc-yk-back")):
            self.assertRegex(css, r'<div id="%s" class="sheet [^"]*hide"' % sid)
            self.assertRegex(css, r'<div class="sheet-back [^"]*" id="%s"></div>\s*<div class="sheet-box ' % back)
        self.assertIn("'sheet wt-sheet wt-psheet hide'", css)
        for gone in (".acc-sheet{position:fixed", ".ob-sheet{position:fixed", ".wt-sheet{position:fixed", ".acc-box{position:relative",
                     ".ob-box{position:relative"):
            self.assertNotIn(gone, css)
        # minimise is «Свернуть», its bar «Показать», dismiss «Закрыть»
        self.assertIn('id="acc-hide" class="acc-x">Свернуть<', css)
        self.assertIn('id="ob-hide" class="ob-x" type="button">Свернуть<', css)
        self.assertNotIn(">Скрыть<", css)
        self.assertEqual(css.count("<span>Показать</span>"), 2)
        self.assertIn('class="acc-x" aria-label="Закрыть мастер ключей">Закрыть<', css)

    def test_results_of_actions_go_to_the_toast(self):
        js = self.page
        self.assertIn("toast(what==='reboot'?'Перезагружаю…':what==='restart-kodi'?'Перезапускаю плеер…':'Обновление запущено')", js)
        self.assertNotIn('id="a-msg"', js)
        self.assertIn("hideMsg('w-msg');toast('Подключено к «'+ssid+'»", js)
        self.assertIn("toast('HTTPS включён')", js)
        self.assertIn("toast('Не получилось: '+tvErr(e).split(token).join('***'))", js)
        self.assertIn("Math.min(7000,1500+text.length*50)", js)        # a long text stays longer

    def test_the_wording(self):
        js = self.page
        for s in ('<span id="live-t">Показать</span>', "on?'Стоп':'Показать'", "'ТВ не отвечает',true", 'placeholder="Например: название фильма"',
                  'placeholder="Пароль сети"', "'Пауза: ':'Играет: '"):
            self.assertIn(s, js)
        for gone in ("Kodi не отвечает", "Нажмите «Смотреть»", "'LIVE'", '<span id="live-t">Смотреть</span>'):
            self.assertNotIn(gone, js)
        self.assertIn("TVs and Limited Input devices", js)           # Google's own words stay as they are

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


class Settings(unittest.TestCase):
    """The settings list and its pages, the status of the last check, the power rule (stage 4). The page's script
    cannot run here (no node): its formatters are checked as text, the server's side as code."""
    @classmethod
    def setUpClass(cls):
        cls.panel = load_panel("panel_tabs_settings")
        cls.page = cls.panel.PAGE

    def test_the_list_has_these_rows_and_every_row_has_its_page(self):
        rows = re.findall(r'<button class="srow" data-sp="(\w+)">.*?<span class="sname">([^<]+)</span>', self.page)
        self.assertEqual(sorted(r[0] for r in rows), ["acc", "act", "https", "info", "lang", "wifi"])
        names = dict(rows)
        self.assertEqual(names["info"], "О приставке")
        self.assertEqual(names["act"], "Обслуживание")
        for key, _ in rows:
            self.assertRegex(self.page, r'data-spage="%s"' % key)
        pages = re.findall(r'<section id="(t-\w+)"[^>]*data-spage="(\w+)"', self.page)
        self.assertTrue({"acc", "lang", "wifi", "https", "info", "act"} <= {p[1] for p in pages}, pages)

    def test_each_hash_maps_to_its_page_and_its_section_id(self):
        m = re.search(r"const SP_HASH=\{([^}]*)\}, SP_OF=\{\}, SP_ID=\{([^}]*)\}", self.page)
        hashes = dict(re.findall(r"(\w+):'(\w+)'", m.group(1)))
        ids = dict(re.findall(r"(\w+):'([\w-]+)'", m.group(2)))
        self.assertEqual(hashes, {"acc": "accounts", "lang": "language", "wifi": "wifi", "https": "https", "info": "device",
                                  "act": "maintenance"})
        self.assertEqual(set(ids), set(hashes))
        for page, sid in ids.items():
            self.assertRegex(self.page, r'<section id="%s"[^>]*data-spage="%s"' % (sid, page))
        self.assertIn("SP_OF[h.replace(/[?].*$/,'').slice(1)]", self.page)   # #https?sub=x still finds the page
        for h in ("#air", "#screen"):
            self.assertIn("h==='#air'||h==='#screen'", self.page)

    def test_leaving_settings_clears_the_hash_of_a_page(self):
        js = self.page.split("document.querySelectorAll('[data-go]')", 1)[1].split("// The remote has three modes", 1)[0]
        self.assertIn("tab!=='settings'&&SP_OF[location.hash", js)
        self.assertIn("history.replaceState(null,'',location.pathname+location.search);spPushed=false;setPage('')", js)

    def test_an_empty_value_is_a_dash(self):
        self.assertIn("const dash=(v,html)=>v?html:'—'", self.page)
        self.assertIn("['Температура',dash(s.temp,", self.page)
        self.assertIn("['Версия',dash(hash,", self.page)

    def test_the_power_rule_looks_at_the_bits_of_now_only(self):
        self.assertIn("const POWER_NOW=0x1|0x2|0x4,", self.page)
        self.assertIn("POWER_PAST=0x10000|0x20000|0x40000|0x80000", self.page)
        self.assertIn("(t&POWER_NOW)!==0", self.page)
        self.assertIn("const needAttention=s=>powerState(s)===true||", self.page)
        self.assertNotIn("needAttention=s=>powerPast", self.page)
        self.assertIn("были просадки питания с момента включения", self.page)

    def test_the_maintenance_row_and_page_say_when_the_last_check_was(self):
        self.assertIn('<span class="sval" id="sv-act"></span>', self.page)
        self.assertIn('id="act-last"', self.page)
        self.assertIn("v('sv-act',s.last_check_min==null?'—':'проверено '+ruAgo(s.last_check_min))", self.page)
        for s in ("через '+mins+' мин", "через '+Math.round(mins/60)+' ч", "'завтра в '+c[1]", "' мин назад'", "' ч назад'", "' дн назад'"):
            self.assertIn(s, self.page)

    def test_keys_row_moved_to_apps_and_screenshot_moved_to_maintenance(self):
        act = self.page.split('<section id="t-act"', 1)[1].split("</section>", 1)[0]
        self.assertNotIn("keys-row", act)
        self.assertNotIn("Ключи Google", act)
        self.assertIn('id="shot-save-act"', act)
        self.assertIn("Скриншот экрана", act)
        self.assertIn("#i-cam", act)
        self.assertLess(act.index('id="cec-wake"'), act.index('id="shot-save-act"'))
        acc = self.page.split('<section id="t-acc"', 1)[1].split("</section>", 1)[0]
        self.assertIn("acc-keys-row", acc)
        self.assertIn("ykOpen()", acc)
        self.assertIn("Ключи Google", acc)
        self.assertIn("document.querySelectorAll('.srow[data-sp]')", self.page)   # the keys row is not a page link

    def test_ios_standalone_pwa_safe_area(self):
        p = self.page
        self.assertIn('<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">', p)
        app_css = re.search(r"#app\{([^}]+)\}", p).group(1)
        self.assertIn("env(safe-area-inset-top)", app_css)
        self.assertIn("env(safe-area-inset-left)", app_css)
        self.assertIn("env(safe-area-inset-right)", app_css)
        self.assertIn("env(safe-area-inset-bottom)", app_css)
        sheet_css = re.search(r"\.sheet-box\{([^}]+)\}", p).group(1)
        self.assertIn("env(safe-area-inset-top)", sheet_css)
        setup_tag = re.search(r'<div id="setup"[^>]*>', p).group(0)
        self.assertIn("env(safe-area-inset-top)", setup_tag)
        rc_lines = [line for line in p.splitlines() if ".rc{" in line]
        self.assertTrue(any("100vh" in l and "env(safe-area-inset-top)" in l for l in rc_lines))
        self.assertTrue(any("100svh" in l and "env(safe-area-inset-top)" in l for l in rc_lines))
        np_lines = [line for line in p.splitlines() if "body.np .rc{" in line]
        self.assertTrue(any("100vh" in l and "env(safe-area-inset-top)" in l for l in np_lines))
        self.assertTrue(any("100svh" in l and "env(safe-area-inset-top)" in l for l in np_lines))

    def test_dead_leftovers_are_gone(self):
        for gone in ("AIR_SMOOTH", "show('a-msg'", 'id="a-msg"'):
            self.assertNotIn(gone, self.page)

    def test_minutes_from_a_systemd_timestamp(self):
        sd, now = self.panel.sd_minutes, time.mktime((2026, 11, 23, 12, 0, 0, 0, 0, -1))
        self.assertEqual(sd("Mon 2026-11-23 15:05:00 UTC", now), 185)
        self.assertEqual(sd("Mon 2026-11-23 11:55:30 UTC", now), -5)
        self.assertEqual(sd("Tue 2026-11-24 04:00:00 UTC", now), 960)
        for empty in ("", "n/a", None, "0"):
            self.assertIsNone(sd(empty, now))

    def test_the_status_has_the_last_check_and_the_next_one(self):
        out = {"systemctl": ""}

        def fake_run(cmd, stdin=None, timeout=20):
            if cmd[:2] == ["systemctl", "show"]:
                unit = cmd[2]
                return 0, out.get(unit, "")
            return 0, ""
        t = time.time()
        stamp = lambda dt: time.strftime("Mon %Y-%m-%d %H:%M:%S UTC", time.localtime(t + dt))
        out["media-stick-update.timer"] = stamp(3 * 3600)
        out["media-stick-update.service"] = stamp(-20 * 60)
        with mock.patch.object(self.panel, "run", fake_run):
            st = self.panel._status()
        self.assertIn(st["next_update_min"], range(178, 182))
        self.assertIn(st["last_check_min"], range(19, 22))
        out["media-stick-update.service"] = ""
        with mock.patch.object(self.panel, "run", fake_run):
            st = self.panel._status()
        self.assertIsNone(st["last_check_min"])

    def test_maintenance_buttons_wrap_and_update_is_wide(self):
        self.assertIn(".row.wrap{flex-wrap:wrap}", self.page)
        self.assertIn(".row.wrap>*{flex:1 1 130px;min-width:0}", self.page)
        self.assertIn(".row.wrap .btn{padding:8px 12px;text-align:center}", self.page)

        act = self.page.split('<section id="t-act"', 1)[1].split("</section>", 1)[0]
        self.assertRegex(act, r'<p class="dsub" id="act-last"></p>\s*<button class="btn wide" onclick="act\(\'update\'\)">Обновить сейчас</button>')
        self.assertNotRegex(act, r'<div class="row[^"]*">[^<]*act\(\'update\'\)')
        self.assertRegex(act, r'<div class="row wrap gap">\s*<button id="rk-btn"[^>]*>Перезапустить плеер</button>\s*<button id="r-btn"[^>]*>Перезагрузить</button>\s*</div>')
        self.assertRegex(act, r'<div class="row wrap gap">\s*<button id="cec-standby"[^>]*>ТВ Standby</button>\s*<button id="cec-wake"[^>]*>ТВ Wake</button>\s*</div>')
        self.assertIn("armed('rk-btn','Нажмите ещё раз, чтобы перезапустить плеер')", act)
        self.assertIn("armed('r-btn','Нажмите ещё раз, чтобы перезагрузить')", act)


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

    def test_an_app_icon_is_served_as_bytes_with_a_day_of_cache(self):
        def fetch(path, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", path, headers=dict({"Host": "localhost:%d" % self.port}, **(headers or {})))
            r = c.getresponse()
            body = r.read()
            out = (r.status, dict(r.getheaders()), body)
            c.close()
            return out
        status, h, body = fetch("/api/watch/art?id=webapp%3Anetflix")
        self.assertEqual((status, h["Content-Type"], h["Cache-Control"]), (200, "image/png", "public, max-age=86400"))
        self.assertTrue(body.startswith(b"\x89PNG"))
        self.assertEqual(int(h["Content-Length"]), len(body))
        status, h2, body = fetch("/api/watch/art?id=webapp%3Anetflix", {"If-None-Match": h["ETag"]})
        self.assertEqual((status, body), (304, b""))
        for bad in ("/api/watch/art?id=../../etc/passwd", "/api/watch/art?id=webapp:nothere", "/api/watch/art"):
            self.assertEqual(fetch(bad)[0], 404, bad)

    def test_the_served_page_has_the_tabs(self):
        status, raw = self.get("/")
        self.assertEqual(status, 200)
        self.assertEqual(re.findall(r'<button data-go="(\w+)"', raw), ["watch", "remote", "settings"])

    def test_sweettv_post_routes_require_x_panel_and_valid_host(self):
        def post(path, body, headers):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("POST", path, body=json.dumps(body).encode("utf-8"), headers=headers)
            r = c.getresponse()
            r.read()
            c.close()
            return r.status

        host = "localhost:%d" % self.port
        for route in ("play", "ctl", "favourite", "settings"):
            # missing X-Panel -> 403
            self.assertEqual(post("/api/sweettv/" + route, {}, {"Host": host, "Content-Type": "application/json"}), 403, route)
            # bad Host -> 403
            self.assertEqual(post("/api/sweettv/" + route, {}, {"Host": "evil.example", "X-Panel": "1",
                                                                "Content-Type": "application/json"}), 403, route)
        # delegation counts in bin/panel remain intact
        with open(PANEL, encoding="utf-8") as f:
            src = f.read()
        self.assertEqual(src.count("panel_sweettv.PREFIX"), 2)
        self.assertEqual(src.count("panel_sweettv.get(") + src.count("panel_sweettv.post("), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
