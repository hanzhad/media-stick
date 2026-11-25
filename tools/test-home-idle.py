#!/usr/bin/env python3
"""Offline test of the home screen's idle mode and the dropped screensaver (no Kodi needed):
python3 tools/test-home-idle.py

Idle mode: launcher.py sets Window.Property(idle) after IDLE_S seconds without input; the skin
dims and lowers the row of cards and shows a small QR in the corner. The skin is checked
without Kodi by reading the XML; launcher.py runs against stand-ins for xbmc, xbmcgui and the rest.
"""
import os
import re
import runpy
import subprocess
import sys
import tempfile
import time
import types
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
ADDON = os.path.join(ROOT, "device", "kodi-addons", "script.media-stick.home")
SKIN = os.path.join(ADDON, "resources", "skins", "default")
HOME_XML = os.path.join(SKIN, "1080i", "script-media-stick-home.xml")
MEDIA = os.path.join(SKIN, "media")
BOOTSTRAP = os.path.join(ROOT, "device", "bootstrap.sh")
KODI_SETTINGS = os.path.join(ROOT, "device", "files", "usr", "local", "bin", "kodi-settings")

IDLE_COND = "String.IsEqual(Window.Property(idle),1)"
TEXTURE_FILES_MAX = 16                  # distinct static textures the home window loads (12 before idle mode)
TEXTURE_BYTES_MAX = 1 << 20             # decoded RGBA of those files together (about 0.5 MB before)
FULLSCREEN_MAX = 4                      # the boot picture, two wallpaper multiimages (only one visible) and the drawer's dim layer
SPLASH = "special://home/media/splash.png"   # the picture from power-on (device/files/home/media/.kodi/media/splash.png)
ANIMATION_MS_MAX = 400                  # every idle transition is short, no per-frame animation

# --- stand-ins for the Kodi modules launcher.py imports -------------------------------------
now = [1000.0]
kodi_idle = [False]
loop = types.SimpleNamespace(ticks=[], tick=0, step=10.0, seen=[])   # the service loop's script, see Service
xbmc = types.ModuleType("xbmc")
xbmc.LOGWARNING = xbmc.LOGERROR = xbmc.LOGINFO = 0
xbmc.log = lambda *a, **k: None
xbmc.executebuiltin = lambda cmd: None


def cond_visible(cond):
    if cond.startswith("System.IdleTime("):
        return kodi_idle[0]
    if cond.startswith("System.ScreenSaverActive"):      # the service's BLOCKED: a dialog or screensaver
        return loop.ticks[min(loop.tick, len(loop.ticks) - 1)][1] if loop.ticks else False
    return False


class Monitor:
    """One waitForAbort() is one pass of the service loop; it ends after the scripted passes."""
    def abortRequested(self):
        return loop.tick >= len(loop.ticks)

    def waitForAbort(self, timeout):
        loop.seen.append(loop.instance.getProperty("idle") if hasattr(loop, "instance") else None)
        loop.tick += 1
        now[0] += loop.step
        return loop.tick >= len(loop.ticks)


xbmc.getCondVisibility = cond_visible
xbmc.Monitor = Monitor
xbmc.getIPAddress = lambda: ""
xbmcvfs = types.ModuleType("xbmcvfs")
xbmcvfs.translatePath = lambda p: tempfile.gettempdir() + "/"
xbmcaddon = types.ModuleType("xbmcaddon")
xbmcaddon.Addon = lambda: types.SimpleNamespace(getAddonInfo=lambda key: ADDON)
xbmcgui = types.ModuleType("xbmcgui")
handled = []


class WindowXML:
    """Window properties and the default onAction, which is what a swallowed key skips."""
    def __init__(self, *args):
        self.props = {}

    def setProperty(self, key, value):
        self.props[key] = value

    def getProperty(self, key):
        return self.props.get(key, "")

    def onAction(self, action):
        handled.append(action.getId())


xbmcgui.WindowXML = WindowXML
xbmcgui.getCurrentWindowId = lambda: loop.ticks[min(loop.tick, len(loop.ticks) - 1)][0]
xbmcgui.WindowXMLDialog = type("WindowXMLDialog", (), {})
sys.modules.update(xbmc=xbmc, xbmcvfs=xbmcvfs, xbmcaddon=xbmcaddon, xbmcgui=xbmcgui)
sys.path.insert(0, ADDON)

from resources.lib import launcher  # noqa: E402

launcher.time = types.SimpleNamespace(monotonic=lambda: now[0])


class Action:
    def __init__(self, action_id):
        self.action_id = action_id

    def getId(self):
        return self.action_id


def window():
    w = launcher.Launcher()
    w._focus = lambda: launcher.CAROUSEL
    w.getFocusId = lambda: launcher.CAROUSEL
    w.setFocusId = lambda control_id: handled.append(f"focus {control_id}")
    w._last_input = now[0]
    w.setProperty("idle", "")
    return w


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def controls(root):
    """Every <control> with its parent control (None at the top)."""
    out = []

    def walk(node, parent):
        for child in node:
            if child.tag == "control":
                out.append((child, parent))
                walk(child, child)
            else:
                walk(child, parent)
    walk(root, None)
    return out


def text(control, tag):
    node = control.find(tag)
    return (node.text or "").strip() if node is not None else ""


class IdleProperty(unittest.TestCase):
    """launcher.py: when the property is set and cleared, and that a key only wakes."""

    def setUp(self):
        now[0] = 1000.0
        kodi_idle[0] = False
        handled.clear()
        self.w = window()

    def test_constant(self):
        self.assertEqual(launcher.IDLE_S, 30)
        self.assertNotIn("IdleTime", read(HOME_XML))        # the one place the time is named is launcher.IDLE_S

    def test_idle_needs_both_clocks(self):
        now[0] += launcher.IDLE_S - 1
        kodi_idle[0] = True
        self.w.refresh_idle()
        self.assertEqual(self.w.getProperty("idle"), "")
        now[0] += 1
        kodi_idle[0] = False                                 # Kodi saw input in another window
        self.w.refresh_idle()
        self.assertEqual(self.w.getProperty("idle"), "")
        kodi_idle[0] = True
        self.w.refresh_idle()
        self.assertEqual(self.w.getProperty("idle"), "1")

    def test_back_when_kodi_sees_input(self):
        now[0] += launcher.IDLE_S
        kodi_idle[0] = True
        self.w.refresh_idle()
        kodi_idle[0] = False
        self.w.refresh_idle()
        self.assertEqual(self.w.getProperty("idle"), "")

    def test_first_key_only_wakes(self):
        for key in sorted(launcher.WAKE_ONLY):
            handled.clear()
            self.w._last_input = now[0] - launcher.IDLE_S
            self.w.setProperty("idle", "1")
            self.w.onAction(Action(key))
            self.assertEqual(self.w.getProperty("idle"), "", key)
            self.assertEqual(handled, [], f"action {key} must neither activate nor move focus while waking")
            self.w.onAction(Action(key))                     # the second one is a normal key
            self.assertEqual(handled, [f"focus {launcher.DRAWER}"] if key == launcher.ACTION_CONTEXT_MENU else [key])

    def test_other_input_wakes_and_goes_on(self):
        self.w.setProperty("idle", "1")
        self.w.onAction(Action(90))                          # pointer move
        self.assertEqual(self.w.getProperty("idle"), "")
        self.assertEqual(handled, [90])

    def test_input_restarts_the_clock(self):
        now[0] += launcher.IDLE_S - 1
        self.w.onAction(Action(2))
        now[0] += launcher.IDLE_S - 1
        kodi_idle[0] = True
        self.w.refresh_idle()
        self.assertEqual(self.w.getProperty("idle"), "")

    def test_nav_keys_are_wake_keys(self):
        self.assertTrue(launcher.NAV_ACTIONS <= launcher.WAKE_ONLY)
        self.assertIn(launcher.ACTION_CONTEXT_MENU, launcher.WAKE_ONLY)

    def test_qr_property_follows_the_card(self):
        launcher.remote.qr_png = lambda url: "/tmp/qr-" + url.replace("/", "_")
        self.assertEqual(self.w._card_qr("http://10.0.0.5/"), "/tmp/qr-http:__10.0.0.5_")
        self.assertEqual(self.w.getProperty("qr"), "/tmp/qr-http:__10.0.0.5_")
        self.assertEqual(self.w._card_qr(""), "")
        self.assertEqual(self.w.getProperty("qr"), "")       # offline: no corner QR

        def broken(url):
            raise OSError("no qrencode")
        launcher.remote.qr_png = broken
        self.assertEqual(self.w._card_qr("http://10.0.0.5/"), "")
        self.assertEqual(self.w.getProperty("qr"), "")

    def test_service_drives_it(self):
        service = read(os.path.join(ADDON, "service.py"))
        self.assertIn("launcher.refresh_idle(", service)

    def test_not_on_screen_clears_it(self):
        now[0] += launcher.IDLE_S
        kodi_idle[0] = True
        self.w.refresh_idle()
        self.assertEqual(self.w.getProperty("idle"), "1")
        self.w.refresh_idle(False)
        self.assertEqual(self.w.getProperty("idle"), "")

    def test_window_id_is_the_windows_own(self):
        self.assertEqual(self.w.window_id(), launcher.WINDOW_ID)         # a window that cannot say it
        launcher.Launcher.getId = lambda self: 13042
        try:
            self.assertEqual(self.w.window_id(), 13042)
        finally:
            del launcher.Launcher.getId


HOME, OWN, OTHER = 10000, 13000, 10004      # Home, the launcher's own window, Settings


class Service(unittest.TestCase):
    """service.py's loop, run for a script of passes (window id, blocked) against the stand-ins:
    once the launcher is shown, the current window is its own id, not Home, and idle must go on."""

    def setUp(self):
        now[0] = 1000.0
        kodi_idle[0] = True
        loop.tick, loop.seen, loop.ticks = 0, [], []
        loop.__dict__.pop("instance", None)
        self.calls = []
        self.patches = [
            mock.patch.object(launcher.Launcher, "show", lambda w: self.show(w), create=True),
            mock.patch.object(launcher.Launcher, "close", lambda w: self.calls.append("close"), create=True),
            mock.patch.object(launcher.Launcher, "refresh_status", lambda w, force=False: self.calls.append("status")),
            mock.patch.object(time, "monotonic", lambda: now[0]),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def show(self, w):
        loop.instance = w
        w._last_input = now[0]
        self.calls.append("show")

    def run_service(self, *ticks):
        loop.ticks = list(ticks)
        runpy.run_path(os.path.join(ADDON, "service.py"), run_name="service_under_test")

    def test_idle_is_set_while_the_launcher_is_the_current_window(self):
        self.run_service((HOME, False), *[(OWN, False)] * 6)
        self.assertEqual(self.calls.count("show"), 1)                    # shown from Home only, not again
        self.assertEqual(loop.seen[:3], ["", "", ""])                    # not before IDLE_S
        self.assertEqual(loop.seen[-1], "1")                             # Kodi counted 30 s idle, the row dims

    def test_refresh_idle_is_called_from_the_launchers_own_window(self):
        calls = []
        refresh = launcher.Launcher.refresh_idle
        with mock.patch.object(launcher.Launcher, "refresh_idle", lambda w, *a: calls.append(a) or refresh(w, *a)):
            self.run_service((HOME, False), (OWN, False), (OWN, False))
        self.assertEqual(len(calls), 3)

    def test_status_goes_on_from_the_launchers_own_window(self):
        self.run_service((HOME, False), *[(OWN, False)] * 3)
        self.assertGreaterEqual(self.calls.count("status"), 2)

    def test_the_id_comes_from_the_window_when_it_has_one(self):
        launcher.Launcher.getId = lambda w: 13007
        try:
            self.run_service((HOME, False), *[(13007, False)] * 6)
        finally:
            del launcher.Launcher.getId
        self.assertEqual(loop.seen[-1], "1")

    def test_a_dialog_or_screensaver_clears_it(self):
        self.run_service((HOME, False), *[(OWN, False)] * 5, (OWN, True), (OWN, True))
        self.assertEqual(loop.seen[4], "1")
        self.assertEqual(loop.seen[-1], "")

    def test_leaving_the_window_clears_it(self):
        self.run_service((HOME, False), *[(OWN, False)] * 5, (OTHER, False), (OTHER, False))
        self.assertEqual(loop.seen[4], "1")
        self.assertEqual(loop.seen[-1], "")

    def test_idle_never_sets_in_another_window(self):
        self.run_service((HOME, False), *[(OTHER, False)] * 6)
        self.assertEqual(set(loop.seen), {""})


class IdleSkin(unittest.TestCase):
    """The skin: what animates in idle, and that nothing else does."""

    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(HOME_XML).getroot()
        cls.all = controls(cls.root)

    def by_id(self, control_id):
        found = [c for c, _ in self.all if c.get("id") == str(control_id)]
        self.assertEqual(len(found), 1, f"control {control_id}")
        return found[0]

    def test_every_property_the_skin_reads_is_set(self):
        source = read(os.path.join(ADDON, "resources", "lib", "launcher.py"))
        names = set(re.findall(r"Window\.Property\((\w+)\)", read(HOME_XML)))
        self.assertTrue({"idle", "qr"} <= names)
        for name in names:
            self.assertRegex(source, rf'setProperty\("{name}"', name)

    def test_conditional_animations_are_the_row_only(self):
        found = [(c, a) for c, _ in self.all for a in c.findall("animation") if (a.text or "").strip() == "Conditional"]
        self.assertEqual([c.get("id") for c, _ in found], ["100", "100"])      # the carousel, nothing else
        effects = {}
        for _, a in found:
            self.assertEqual(a.get("condition"), IDLE_COND)
            self.assertNotEqual(a.get("reversible"), "false")                  # any input restores
            effects[a.get("effect")] = a
        fade, slide = effects["fade"], effects["slide"]
        self.assertEqual(fade.get("end"), "30")                                # opacity 0.3
        self.assertEqual(fade.get("start"), "100")                             # not the default: see IdleWake
        self.assertEqual(slide.get("start"), "0,0")
        down = [int(v) for v in slide.get("end").split(",")]
        self.assertEqual(down[0], 0)
        self.assertGreater(down[1], 0)                                         # down, not sideways or up
        self.assertLess(down[1], 330)                                          # the row's strip stays on screen

    def test_every_animation_is_short_and_finite(self):
        for control, _ in self.all:
            for a in control.findall("animation"):
                self.assertLessEqual(int(a.get("time")), ANIMATION_MS_MAX)
                self.assertIsNone(a.get("loop"))
                self.assertIsNone(a.get("pulse"))
                self.assertNotIn(a.get("effect"), ("rotate", "rotatex", "rotatey"))
                self.assertNotIn(a.get("tween"), ("elastic", "bounce"))

    def test_visible_hidden_animations_have_a_visible_condition(self):
        """An animation on Visible/Hidden only runs when the control has a condition to flip."""
        for control, _ in self.all:
            kinds = {(a.text or "").strip() for a in control.findall("animation")}
            if kinds & {"Visible", "Hidden"}:
                self.assertTrue(text(control, "visible"), f"{control.get('type')} {control.get('id')}")

    def test_corner_qr_exists_only_in_idle(self):
        group = self.by_id(410)
        condition = text(group, "visible")
        self.assertIn(IDLE_COND, condition)
        self.assertIn("!String.IsEmpty(Window.Property(qr))", condition)       # nothing to scan offline: no empty box
        self.assertNotIn("|", condition)
        image = self.by_id(411)
        self.assertEqual(text(image, "texture"), "$INFO[Window.Property(qr)]")
        card = int(text(self.by_id(100).find("itemlayout/control/control[@type='image'][3]"), "width"))
        size = int(text(group, "width"))
        self.assertEqual(size, int(text(group, "height")))
        self.assertLess(size, card)                                             # smaller than the card was
        self.assertGreaterEqual(size, 128)                                      # but still scannable
        left, top = int(text(group, "left")), int(text(group, "top"))
        self.assertLessEqual(left, 64)                                          # nearer the corner than the card was
        self.assertLessEqual(1080 - (top + size), 64)
        self.assertGreater(top, 740 + 40)                                       # lower than the card was

    def test_remote_card_leaves_the_row_while_the_corner_has_it(self):
        row = self.by_id(100)
        for layout, group in (("itemlayout", "control"), ("focusedlayout", "control[@type='group']")):
            node = row.find(f"{layout}/{group}")
            condition = text(node, "visible")
            self.assertIn("!" + IDLE_COND, condition, layout)
            self.assertIn("!String.IsEqual(ListItem.Property(card),remote)", condition, layout)
            self.assertIn("String.IsEmpty(Window.Property(qr))", condition, layout)   # offline: keep the card
            self.assertEqual(condition.count("|"), 2, layout)
            self.assertTrue(any((a.text or "").strip() == "Hidden" for a in node.findall("animation")))
        # the same card is never in the row and the corner at once
        self.assertIn("!String.IsEmpty(Window.Property(qr))", text(self.by_id(410), "visible"))

    def test_menu_hint_goes_with_the_row(self):
        hints = [c for c, _ in self.all if "Container(100).CurrentItem,1" in text(c, "visible")]
        self.assertEqual(len(hints), 1)
        self.assertIn("!" + IDLE_COND, text(hints[0], "visible"))

    def test_every_control_that_mentions_idle_is_accounted_for(self):
        """The row (animation), the corner QR, the row's two layouts and the menu hint: nothing else."""
        mentioning = []
        for control, _ in self.all:
            own = [text(control, "visible")] + [a.get("condition") or "" for a in control.findall("animation")]
            if any("Property(idle)" in c for c in own):
                mentioning.append(control)
        kinds = sorted((c.get("type"), c.get("id") or "") for c in mentioning)
        self.assertEqual(kinds, [("group", ""), ("group", ""), ("group", ""), ("group", "410"), ("list", "100")])

    def test_texture_budget(self):
        """Idle mode adds no bitmap: the corner QR is the png the card already loads and the
        shadow is the card's. The home window's static textures stay within a fixed budget."""
        refs = set()
        for control, _ in self.all:
            for tag in ("texture", "texturefocus", "texturenofocus"):
                for node in control.findall(tag):
                    for name in [(node.text or "").strip(), node.get("diffuse") or ""]:
                        if name and "$INFO" not in name and name != SPLASH:   # one texture of its own, see test_boot_picture_is_the_bottom_layer
                            refs.add(name)
        self.assertLessEqual(len(refs), TEXTURE_FILES_MAX)
        total = 0
        try:
            from PIL import Image
        except ImportError:
            Image = None
        for name in refs:
            path = os.path.join(MEDIA, name)
            self.assertTrue(os.path.exists(path), name)
            if Image:
                with Image.open(path) as im:
                    total += im.size[0] * im.size[1] * 4
        self.assertLessEqual(total, TEXTURE_BYTES_MAX)
        full = [c for c, _ in self.all
                if text(c, "width") == "1920" and text(c, "height") == "1080"]
        self.assertLessEqual(len(full), FULLSCREEN_MAX)

    def test_boot_picture_is_the_bottom_layer(self):
        """Power-on to home shows only our picture: the first control is the boot splash, so the
        wallpaper fades in over it, and no other control draws it (one texture, nothing after)."""
        top = list(ET.parse(HOME_XML).getroot().find("controls"))
        self.assertEqual(top[0].get("type"), "image")
        self.assertEqual(text(top[0], "texture"), SPLASH)
        self.assertEqual((text(top[0], "left"), text(top[0], "top")), ("0", "0"))
        self.assertEqual((text(top[0], "width"), text(top[0], "height")), ("1920", "1080"))
        self.assertEqual(text(top[0], "visible"), "")               # never hidden by a condition, nothing to flip
        self.assertFalse(top[0].findall("animation"))
        self.assertEqual(read(HOME_XML).count(SPLASH), 1)
        self.assertTrue(os.path.exists(os.path.join(ROOT, "device", "files", "home", "media", ".kodi", "media", "splash.png")))
        # the wallpapers that cover it are never dimmed: idle only dims the row of cards
        for c, _ in self.all:
            if c.get("type") == "multiimage":
                self.assertFalse(c.findall("animation"))
                self.assertEqual(text(c, "colordiffuse"), "")

    def test_wallpapers_keep_rotating_from_the_bing_cache(self):
        """No screensaver: the home screen's own multiimage cycles the cached Bing photos."""
        cache = [c for c, _ in self.all if text(c, "imagepath") == "/var/cache/media-stick/wallpapers/"]
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache[0].get("type"), "multiimage")
        self.assertEqual(text(cache[0], "timeperimage"), "300000")
        self.assertEqual(text(cache[0], "loop"), "yes")
        self.assertEqual(text(cache[0], "visible"), "String.IsEqual(Window.Property(wallpaper),cache)")
        self.assertFalse(cache[0].findall("animation"))        # idle does not touch the wallpaper
        self.assertIn("media-stick-wallpapers.timer", read(BOOTSTRAP))
        self.assertIn("bing.com", read(os.path.join(ROOT, "device", "files", "usr", "local", "bin", "media-stick-wallpapers")))


def kodi_visible(expr, state):
    """Evaluate a skin <visible> expression the way Kodi reads it: ! not, + and, | or, [ ] groups
    (+ binds tighter than |). state maps each leaf infobool to its value; an unknown leaf fails."""
    tokens = [t.strip() for t in re.split(r"([!+|\[\]])", expr) if t.strip()]
    pos = [0]

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        pos[0] += 1
        return tokens[pos[0] - 1]

    def either():
        value = both()
        while peek() == "|":
            take()
            value = both() or value
        return value

    def both():
        value = unary()
        while peek() == "+":
            take()
            value = unary() and value
        return value

    def unary():
        token = take()
        if token == "!":
            return not unary()
        if token == "[":
            value = either()
            assert take() == "]", expr
            return value
        if token not in state:
            raise KeyError(f"no value for {token!r} in {expr!r}")
        return state[token]

    result = either()
    assert peek() is None, f"trailing {peek()!r} in {expr!r}"
    return result


def states():
    """Every combination of what the skin reads: the idle property, the QR png, the item's card
    kind, the row's focus and the focused position."""
    for idle in ("", "1"):
        for qr in ("", "/tmp/qr.png"):
            for card in ("remote", ""):
                for focus in (True, False):
                    for current in (1, 2):
                        yield dict(idle=idle, qr=qr, card=card, focus=focus, current=current)


def leaves(s):
    return {
        "String.IsEqual(Window.Property(idle),1)": s["idle"] == "1",
        "String.IsEmpty(Window.Property(qr))": s["qr"] == "",
        "String.IsEqual(ListItem.Property(card),remote)": s["card"] == "remote",
        "String.IsEmpty(ListItem.Property(glyph))": True,
        "Control.HasFocus(100)": s["focus"],
        "Integer.IsEqual(Container(100).CurrentItem,1)": s["current"] == 1,
    }


class IdleWake(unittest.TestCase):
    """The row must come back whole when idle clears. Found on the TV: after a key the row did
    not return, only the wallpaper, because the Conditional fade had end="30" and no start, and
    Kodi's default start for a Conditional fade is 0: the reverse that runs when the condition
    turns false ends at 0 % opacity. So every Conditional fade or zoom names both ends."""

    @classmethod
    def setUpClass(cls):
        cls.root = ET.parse(HOME_XML).getroot()
        cls.all = controls(cls.root)

    def row(self):
        return [c for c, _ in self.all if c.get("id") == "100"][0]

    def test_every_conditional_effect_names_both_ends(self):
        folder = os.path.dirname(HOME_XML)
        names = sorted(n for n in os.listdir(folder) if n.endswith(".xml"))
        self.assertIn(os.path.basename(HOME_XML), names)
        seen = 0
        for name in names:
            for anim in ET.parse(os.path.join(folder, name)).getroot().iter("animation"):
                if (anim.text or "").strip() != "Conditional" and anim.get("type") != "Conditional":
                    continue
                effects = [anim] if anim.get("effect") else list(anim.findall("effect"))
                for effect in effects:
                    kind = effect.get("effect") or effect.get("type")
                    if kind in ("fade", "zoom"):          # their defaults are not "no change"
                        seen += 1
                        self.assertTrue(effect.get("start") is not None and effect.get("end") is not None,
                                        f"{name}: Conditional {kind} needs start and end")
        self.assertGreaterEqual(seen, 1)

    def test_the_row_dims_from_full_and_back_to_full(self):
        row = self.row()
        fade = [a for a in row.findall("animation") if a.get("effect") == "fade"]
        self.assertEqual(len(fade), 1)
        self.assertEqual((fade[0].get("start"), fade[0].get("end")), ("100", "30"))
        self.assertNotEqual(fade[0].get("reversible"), "false")     # the reverse is the way back
        self.assertEqual(fade[0].get("condition"), IDLE_COND)       # one condition: no second animation to clash
        slide = [a for a in row.findall("animation") if a.get("effect") == "slide"]
        self.assertEqual(slide[0].get("start"), "0,0")              # the row's own place
        self.assertIsNone(row.find("visible"))                      # the list itself is never hidden
        self.assertNotIn("Hidden", {(a.text or "").strip() for a in row.findall("animation")})

    def test_the_row_shows_its_cards_whenever_idle_is_empty(self):
        row = self.row()
        for layout, path in (("itemlayout", "control"), ("focusedlayout", "control[@type='group']")):
            expr = text(row.find(f"{layout}/{path}"), "visible")
            for s in states():
                if s["idle"] == "" or s["card"] != "remote":
                    self.assertTrue(kodi_visible(expr, leaves(s)), f"{layout} hides a card: {s}")

    def test_the_remote_card_is_in_the_row_or_the_corner_never_both_never_neither(self):
        row, corner = self.row(), self.root.find(".//control[@id='410']")
        for layout, path in (("itemlayout", "control"), ("focusedlayout", "control[@type='group']")):
            expr = text(row.find(f"{layout}/{path}"), "visible")
            for s in states():
                in_row = kodi_visible(expr, leaves(s))
                in_corner = kodi_visible(text(corner, "visible"), leaves(s))
                self.assertEqual(in_corner, s["idle"] == "1" and s["qr"] != "", s)
                if s["card"] == "remote":
                    self.assertNotEqual(in_row, in_corner, f"{layout} {s}")

    def test_idle_hides_the_menu_hint_and_awake_shows_it(self):
        hint = [c for c, _ in self.all if "Container(100).CurrentItem,1" in text(c, "visible")][0]
        for s in states():
            want = s["focus"] and s["current"] == 1 and s["idle"] == ""
            self.assertEqual(kodi_visible(text(hint, "visible"), leaves(s)), want, s)

    def test_the_evaluator_itself(self):
        state = {"a": True, "b": False, "c": True}
        for expr, want in (("a + b", False), ("a | b", True), ("!b + a", True), ("b | a + c", True),
                           ("b + a | c", True), ("[b | a] + !c", False), ("!a | !b", True)):
            self.assertEqual(kodi_visible(expr, state), want, expr)
        with self.assertRaises(KeyError):
            kodi_visible("a + nope", state)


class NoScreensaver(unittest.TestCase):
    def wanted(self):
        body = re.search(r"kodi_wanted=\((.*?)\n\s*debug\.screenshotpath=[^\n]*\)", read(BOOTSTRAP), re.S)
        self.assertTrue(body, "kodi_wanted not found")
        lines = [ln.split("#")[0] for ln in body.group(0).splitlines()]
        return " ".join(lines).split()

    def test_bootstrap_sets_an_empty_screensaver(self):
        wanted = self.wanted()
        self.assertIn("screensaver.mode=", wanted)
        self.assertEqual([w for w in wanted if w.startswith("screensaver.") and w != "screensaver.mode="], [])
        self.assertIn("lookandfeel.skin=skin.media-stick", wanted)

    def test_bootstrap_comment_says_what_it_does(self):
        comment = re.search(r"#  - look:[^\n]*(\n#    [^\n]*)*", read(BOOTSTRAP)).group(0)
        self.assertIn("no screensaver", comment)
        self.assertNotIn("5 idle minutes", comment)

    def test_the_launcher_service_does_not_need_one(self):
        # System.ScreenSaverActive is simply always false with no screensaver; an
        # InhibitScreensaver builtin elsewhere is a no-op then, and still holds the display on
        service = read(os.path.join(ADDON, "service.py"))
        self.assertIn("System.ScreenSaverActive", service)
        self.assertNotIn("screensaver.bing", service)

    def test_kodi_settings_writes_and_checks_an_empty_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            guisettings = os.path.join(tmp, "guisettings.xml")
            tool = os.path.join(tmp, "kodi-settings")
            source = read(KODI_SETTINGS)
            self.assertIn('PATH = "/home/media/.kodi/userdata/guisettings.xml"', source)
            with open(tool, "w") as f:
                f.write(source.replace("/home/media/.kodi/userdata/guisettings.xml", guisettings))
            with open(guisettings, "w") as f:
                f.write('<settings version="2"><setting id="screensaver.mode" default="false">screensaver.bing</setting>'
                        '<setting id="screensaver.time">5</setting></settings>')

            def run(*args):
                return subprocess.run([sys.executable, tool, *args], capture_output=True, text=True)

            want = ["screensaver.mode="] + [w for w in self.wanted() if w.startswith("lookandfeel.skin")]
            self.assertEqual(run("--check", *want).returncode, 1)               # the old value differs
            self.assertIn("screensaver.mode", run(*want).stdout)
            self.assertEqual(run("--check", *want).returncode, 0)               # and now it matches
            self.assertEqual(run(*want).stdout.strip(), "")                     # idempotent: nothing to change
            setting = [e for e in ET.parse(guisettings).getroot().iter("setting") if e.get("id") == "screensaver.mode"]
            self.assertEqual(len(setting), 1)
            self.assertEqual(setting[0].text or "", "")
            self.assertNotEqual(setting[0].get("default"), "true")


if __name__ == "__main__":
    unittest.main()
