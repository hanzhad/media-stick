#!/usr/bin/env python3
"""Contract tests for the native 1080p Kodi skin (device/kodi-addons/skin.media-stick)."""
import copy
import os
import re
import shutil
import subprocess
import unittest
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKIN_DIR = os.path.join(ROOT, "device", "kodi-addons", "skin.media-stick")
SKIN_XML_DIR = os.path.join(SKIN_DIR, "xml")
HOME_ADDON_XML_DIR = os.path.join(
    ROOT,
    "device",
    "kodi-addons",
    "script.media-stick.home",
    "resources",
    "skins",
    "default",
    "1080i",
)

FORBIDDEN_DEPS = (
    "themoviedb",
    "tmdbhelper",
    "skinshortcuts",
    "skinvariables",
    "jurialmunkey",
    "favourites",
    "globalsearch",
)

FORBIDDEN_XML_REFS = (
    "tmdbhelper",
    "skinshortcuts",
    "skinvariables",
    "jurialmunkey",
    "globalsearch",
)

REQUIRED_FONTS = (
    "font13",
    "Bold25",
    "Bold34",
    "Light40",
    "Light60",
    "Med28",
    "Med32",
    "Med40",
    "MsHeading",
    "MsTitle",
    "Reg22",
    "Reg25",
)

REQUIRED_WINDOW_XMLS = (
    "Home.xml",
    "Startup.xml",
    "Pointer.xml",
    "VideoFullScreen.xml",
    "VideoOSD.xml",
    "DialogSeekBar.xml",
    "DialogKeyboard.xml",
    "DialogSelect.xml",
    "DialogConfirm.xml",
    "DialogNotification.xml",
    "DialogBusy.xml",
    "DialogContextMenu.xml",
    "DialogButtonMenu.xml",
    "Settings.xml",
    "SettingsCategory.xml",
    "SettingsSystemInfo.xml",
    "AddonBrowser.xml",
    "MyVideoNav.xml",
    "FileBrowser.xml",
    "DialogProgress.xml",
    "DialogExtendedProgressBar.xml",
    "DialogTextViewer.xml",
)


EXPECTED_SKIN_PNGS = (
    "app-fallback.png",
    "card-glow.png",
    "card-mask.png",
    "card-shadow.png",
    "gradient-bottom.png",
    "gradient-left.png",
    "gradient-top.png",
    "icon-accounts.png",
    "icon-chevron-left.png",
    "icon-ethernet.png",
    "icon-phone.png",
    "icon-power.png",
    "icon-search.png",
    "icon-settings.png",
    "icon-wifi.png",
    "ms-bar.png",
    "ms-card.png",
    "ms-circle.png",
    "ms-pill.png",
    "ms-pointer.png",
    "ms-tag.png",
    "ms-toggle-off-fo.png",
    "ms-toggle-off-nf.png",
    "ms-toggle-on-fo.png",
    "ms-toggle-on-nf.png",
    "pill-80.png",
    "pill.png",
    "white.png",
)


def _all_skin_xml_files():
    xmls = []
    if not os.path.isdir(SKIN_DIR):
        return xmls
    for dirpath, _dirnames, filenames in os.walk(SKIN_DIR):
        for name in sorted(filenames):
            if name.endswith(".xml"):
                xmls.append(os.path.join(dirpath, name))
    return xmls


def _parse_opt_int(val):
    if val is None:
        return None
    s = val.strip()
    if re.fullmatch(r"-?\d+", s):
        return int(s)
    return None


def _norm_kodi_info_key(key):
    s = key.strip()
    m = re.fullmatch(r"Window\((?i:home)\)\.Property\(([^)]+)\)", s)
    if m:
        prop = m.group(1).strip().strip('"').strip("'")
        return f"Window(home).Property({prop})"
    return s


def _tokenize_kodi_bool(expr):
    tokens, buf, paren = [], [], 0
    for ch in expr:
        if ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            paren -= 1
            buf.append(ch)
        elif paren == 0 and ch in "!+|[]":
            tok = "".join(buf).strip()
            if tok:
                tokens.append(tok)
            buf = []
            tokens.append(ch)
        else:
            buf.append(ch)
    tok = "".join(buf).strip()
    if tok:
        tokens.append(tok)
    return tokens


def _split_top_commas(text):
    parts, buf, paren = [], [], 0
    for ch in text:
        if ch == "(":
            paren += 1
            buf.append(ch)
        elif ch == ")":
            paren -= 1
            buf.append(ch)
        elif paren == 0 and ch == ",":
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    parts.append("".join(buf))
    return parts


def _eval_kodi_bool(expr, bools, strings):
    if not expr or not expr.strip():
        return True
    tokens = _tokenize_kodi_bool(expr)
    pos = [0]
    lower_bools = {k.lower(): v for k, v in bools.items()}

    def peek():
        return tokens[pos[0]] if pos[0] < len(tokens) else None

    def take():
        tok = tokens[pos[0]]
        pos[0] += 1
        return tok

    def eval_leaf(tok):
        low = tok.lower()
        if low == "true":
            return True
        if low == "false":
            return False
        m_empty = re.fullmatch(r"(?i:String\.IsEmpty)\((.+)\)", tok)
        if m_empty:
            key = _norm_kodi_info_key(m_empty.group(1))
            if key not in strings:
                raise KeyError(f"Unknown string infolabel {key!r} in {expr!r}")
            return strings[key] == ""
        m_eq = re.fullmatch(r"(?i:String\.IsEqual)\((.+)\)", tok)
        if m_eq:
            parts = _split_top_commas(m_eq.group(1))
            if len(parts) != 2:
                raise ValueError(f"Malformed String.IsEqual in {expr!r}")
            key = _norm_kodi_info_key(parts[0])
            rhs = parts[1].strip().strip('"').strip("'")
            if key not in strings:
                raise KeyError(f"Unknown string infolabel {key!r} in {expr!r}")
            return strings[key] == rhs
        if low in lower_bools:
            return lower_bools[low]
        raise KeyError(f"Unknown boolean infobool {tok!r} in {expr!r}")

    def either():
        val = both()
        while peek() == "|":
            take()
            rhs = both()
            val = val or rhs
        return val

    def both():
        val = unary()
        while peek() == "+":
            take()
            rhs = unary()
            val = val and rhs
        return val

    def unary():
        tok = take()
        if tok == "!":
            return not unary()
        if tok == "[":
            val = either()
            if take() != "]":
                raise ValueError(f"Unclosed '[' in {expr!r}")
            return val
        return eval_leaf(tok)

    res = either()
    if peek() is not None:
        raise ValueError(f"Unexpected trailing token {peek()!r} in {expr!r}")
    return res


def _render_kodi_label(template, strings):
    if not template:
        return ""

    def repl_info(m):
        parts = _split_top_commas(m.group(1))
        key = _norm_kodi_info_key(parts[0])
        if key not in strings:
            raise KeyError(f"Unknown $INFO key {key!r} in {template!r}")
        val = strings[key]
        if len(parts) == 1:
            return val
        if len(parts) == 2:
            return (parts[1] + val) if val else ""
        return (parts[1] + val + parts[2]) if val else ""

    out = re.sub(r"\$INFO\[([^\[\]]+)\]", repl_info, template)
    out = re.sub(r"\$LOCALIZE\[(\d+)\]", r"LOC:\1", out)
    return out


def _load_includes():
    includes_xml = os.path.join(SKIN_XML_DIR, "Includes.xml")
    root = ET.parse(includes_xml).getroot()
    return {
        inc.attrib["name"]: inc
        for inc in root.findall("./include")
        if inc.attrib.get("name")
    }


def _expand_includes(elem, includes_map):
    cloned = copy.deepcopy(elem)

    def _expand_in_place(node):
        i = 0
        while i < len(node):
            child = node[i]
            if child.tag == "include":
                inc_name = (child.text or child.attrib.get("content") or "").strip()
                if inc_name not in includes_map:
                    raise KeyError(f"Undefined <include>{inc_name}</include>")
                expanded_children = [
                    copy.deepcopy(sub) for sub in list(includes_map[inc_name])
                ]
                node[i : i + 1] = expanded_children
                continue
            _expand_in_place(child)
            i += 1

    _expand_in_place(cloned)
    return cloned


def _collect_window_controls(window_name, includes_map):
    path = os.path.join(SKIN_XML_DIR, window_name)
    raw_root = ET.parse(path).getroot()
    root = _expand_includes(raw_root, includes_map)
    win_vis = tuple(
        v.text.strip() for v in root.findall("./visible") if v.text and v.text.strip()
    )
    items = []
    counter = [0]

    def _walk(container, anc_vis, ox, oy):
        for ctrl in container.findall("./control"):
            own_vis = tuple(
                v.text.strip()
                for v in ctrl.findall("./visible")
                if v.text and v.text.strip()
            )
            vis = anc_vis + own_vis
            order = counter[0]
            counter[0] += 1
            items.append(
                {
                    "ctrl": ctrl,
                    "vis": vis,
                    "ox": ox,
                    "oy": oy,
                    "order": order,
                }
            )
            if ctrl.attrib.get("type") == "group":
                gx = _parse_opt_int(ctrl.findtext("left")) or 0
                gy = _parse_opt_int(ctrl.findtext("top")) or 0
                _walk(ctrl, vis, ox + gx, oy + gy)

    controls_el = root.find("./controls")
    if controls_el is not None:
        _walk(controls_el, win_vis, 0, 0)
    return raw_root, items


def _is_visible(vis_exprs, bools, strings):
    return all(_eval_kodi_bool(expr, bools, strings) for expr in vis_exprs)


def _active_zoom(ctrl, bools, strings):
    matched = []
    for anim in ctrl.findall("./animation"):
        is_cond = (anim.text or "").strip() == "Conditional" or anim.attrib.get("type") == "Conditional"
        if not is_cond:
            continue
        cond = anim.attrib.get("condition", "")
        effects = [anim] if anim.attrib.get("effect") else list(anim.findall("./effect"))
        for eff in effects:
            kind = eff.attrib.get("effect") or eff.attrib.get("type")
            if kind != "zoom":
                continue
            if _eval_kodi_bool(cond, bools, strings):
                sx, sy = eff.attrib["end"].split(",", 1)
                matched.append((int(sx), int(sy)))
    if len(matched) > 1:
        raise AssertionError(f"Multiple Conditional zoom animations active simultaneously: {matched}")
    return matched[0] if matched else (100, 100)


def _osd_state(
    ms_tv_osd="",
    ms_tv_progress="",
    ms_tv_time_label="",
    ms_tv_sublabel="",
    player_time="12:34",
    player_duration="1:45:00",
    title="Интерстеллар",
    tvshow_title="",
    seek_offset="",
    seeking=False,
    forwarding=False,
    rewinding=False,
    paused=True,
):
    bools = {
        "Window.IsVisible(visualisation)": False,
        "VideoPlayer.IsFullscreen": True,
        "Player.Seeking": seeking,
        "Player.HasPerformedSeek(3)": seeking,
        "Player.Paused": paused,
        "Player.Forwarding": forwarding,
        "Player.Rewinding": rewinding,
        "Player.HasGame": False,
        "Player.FrameAdvance": False,
        "Window.IsActive(videoosd)": False,
        "Window.IsActive(musicosd)": False,
        "Window.IsActive(subtitlesearch)": False,
        "System.IdleTime(3)": False,
        "Player.Caching": False,
    }
    strings = {
        "Window(home).Property(ms.tv_osd)": ms_tv_osd,
        "Window(home).Property(ms.tv_progress)": ms_tv_progress,
        "Window(home).Property(ms.tv_time_label)": ms_tv_time_label,
        "Window(home).Property(ms.tv_sublabel)": ms_tv_sublabel,
        "Player.Time": player_time,
        "Player.Duration": player_duration,
        "Player.SeekOffset": seek_offset,
        "VideoPlayer.Title": title,
        "VideoPlayer.TVShowTitle": tvshow_title,
    }
    return bools, strings


class TestSkinMediaStick(unittest.TestCase):
    def test_skin_directory_and_xml_files_valid_with_xmllint(self):
        xmls = _all_skin_xml_files()
        self.assertGreater(
            len(xmls),
            0,
            f"Expected XML files under {SKIN_DIR}, found none",
        )
        for path in xmls:
            ET.parse(path)
        if shutil.which("xmllint"):
            res = subprocess.run(
                ["xmllint", "--noout", *xmls],
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                res.returncode,
                0,
                f"xmllint failed:\n{res.stderr}\n{res.stdout}",
            )

    def test_addon_xml_metadata_1080p_and_zero_third_party_deps(self):
        addon_xml = os.path.join(SKIN_DIR, "addon.xml")
        self.assertTrue(os.path.isfile(addon_xml), f"Missing {addon_xml}")
        tree = ET.parse(addon_xml)
        root = tree.getroot()
        self.assertEqual(root.tag, "addon")
        self.assertEqual(root.attrib.get("id"), "skin.media-stick")

        requires = root.find("requires")
        self.assertIsNotNone(requires, "addon.xml must have <requires>")
        imports = requires.findall("import")
        import_ids = [imp.attrib.get("addon", "") for imp in imports]
        self.assertEqual(
            import_ids,
            ["xbmc.gui"],
            f"<requires> must contain ONLY xbmc.gui, got {import_ids}",
        )
        self.assertEqual(imports[0].attrib.get("version"), "5.17.0")

        raw = open(addon_xml, encoding="utf-8").read().lower()
        for dep in FORBIDDEN_DEPS:
            self.assertNotIn(dep, raw, f"Forbidden dependency {dep!r} in addon.xml")

        skin_ext = root.find("./extension[@point='xbmc.gui.skin']")
        self.assertIsNotNone(skin_ext, "Missing xbmc.gui.skin extension")
        res = skin_ext.find("res")
        self.assertIsNotNone(res, "Missing <res> in xbmc.gui.skin extension")
        self.assertEqual(res.attrib.get("width"), "1920")
        self.assertEqual(res.attrib.get("height"), "1080")
        self.assertEqual(res.attrib.get("aspect"), "16:9")
        self.assertEqual(res.attrib.get("default"), "true")
        self.assertEqual(res.attrib.get("folder"), "xml")

    def test_colors_and_pointer_media_exist(self):
        colors_xml = os.path.join(SKIN_DIR, "colors", "defaults.xml")
        self.assertTrue(os.path.isfile(colors_xml), f"Missing {colors_xml}")
        root = ET.parse(colors_xml).getroot()
        self.assertEqual(root.tag, "colors")

        pointer_png = os.path.join(SKIN_DIR, "media", "ms-pointer.png")
        self.assertTrue(os.path.isfile(pointer_png), f"Missing {pointer_png}")

    def test_required_support_and_window_xmls_exist_with_valid_roots(self):
        defaults_xml = os.path.join(SKIN_XML_DIR, "Defaults.xml")
        self.assertTrue(os.path.isfile(defaults_xml), f"Missing {defaults_xml}")
        self.assertIn(
            ET.parse(defaults_xml).getroot().tag,
            ("includes", "defaults"),
        )

        includes_xml = os.path.join(SKIN_XML_DIR, "Includes.xml")
        self.assertTrue(os.path.isfile(includes_xml), f"Missing {includes_xml}")
        self.assertEqual(ET.parse(includes_xml).getroot().tag, "includes")

        for name in REQUIRED_WINDOW_XMLS:
            path = os.path.join(SKIN_XML_DIR, name)
            self.assertTrue(os.path.isfile(path), f"Missing required window {path}")
            root = ET.parse(path).getroot()
            self.assertEqual(
                root.tag,
                "window",
                f"{name} must have <window> root, got <{root.tag}>",
            )

        pointer_raw = open(
            os.path.join(SKIN_XML_DIR, "Pointer.xml"), encoding="utf-8"
        ).read()
        self.assertIn("ms-pointer.png", pointer_raw)

    def test_extended_progress_bar_toast_conventions(self):
        ext_xml = os.path.join(SKIN_XML_DIR, "DialogExtendedProgressBar.xml")
        self.assertTrue(os.path.isfile(ext_xml), f"Missing {ext_xml}")
        raw = open(ext_xml, encoding="utf-8").read()
        self.assertIn("ms-card.png", raw)
        self.assertIn("DialogBackColour", raw)
        self.assertIn("MsHeading", raw)
        self.assertIn("Reg25", raw)
        root = ET.parse(ext_xml).getroot()
        control_ids = {
            el.attrib.get("id")
            for el in root.findall(".//control")
            if el.attrib.get("id")
        }
        for req_id in ("30", "31", "32"):
            self.assertIn(
                req_id,
                control_ids,
                f"DialogExtendedProgressBar.xml missing required control id={req_id!r}",
            )

    def test_font_xml_defines_all_home_addon_and_required_fonts(self):
        font_xml = os.path.join(SKIN_XML_DIR, "Font.xml")
        self.assertTrue(os.path.isfile(font_xml), f"Missing {font_xml}")
        root = ET.parse(font_xml).getroot()
        self.assertEqual(root.tag, "fonts")

        defined_fonts = {}
        for font_el in root.findall(".//fontset/font"):
            name_el = font_el.find("name")
            file_el = font_el.find("filename")
            size_el = font_el.find("size")
            if name_el is not None and name_el.text:
                defined_fonts[name_el.text.strip()] = (
                    file_el.text.strip() if file_el is not None and file_el.text else "",
                    size_el.text.strip() if size_el is not None and size_el.text else "",
                )

        for req in REQUIRED_FONTS:
            self.assertIn(req, defined_fonts, f"Font {req!r} missing from Font.xml")
            filename, size = defined_fonts[req]
            self.assertTrue(
                filename.lower().endswith(".ttf"),
                f"Font {req!r} filename must be .ttf, got {filename!r}",
            )
            self.assertTrue(
                size.isdigit() and int(size) > 0,
                f"Font {req!r} must have positive integer size, got {size!r}",
            )

        home_xmls = [
            os.path.join(HOME_ADDON_XML_DIR, f)
            for f in sorted(os.listdir(HOME_ADDON_XML_DIR))
            if f.endswith(".xml")
        ]
        self.assertGreater(len(home_xmls), 0, "No home addon 1080i XMLs found")

        referenced_by_home = set()
        for path in home_xmls:
            for font_el in ET.parse(path).getroot().findall(".//font"):
                if font_el.text and font_el.text.strip():
                    referenced_by_home.add(font_el.text.strip())

        missing = sorted(referenced_by_home - set(defined_fonts))
        self.assertEqual(
            missing,
            [],
            f"Fonts referenced by script.media-stick.home missing from Font.xml: {missing}",
        )

    def test_skin_xmls_do_not_reference_fonts_missing_from_font_xml(self):
        font_xml = os.path.join(SKIN_XML_DIR, "Font.xml")
        self.assertTrue(os.path.isfile(font_xml), f"Missing {font_xml}")
        defined = {
            el.text.strip()
            for el in ET.parse(font_xml).getroot().findall(".//fontset/font/name")
            if el.text and el.text.strip()
        }
        for path in _all_skin_xml_files():
            if os.path.basename(path) in ("Font.xml", "addon.xml"):
                continue
            for font_el in ET.parse(path).getroot().findall(".//control//font"):
                if font_el.text and font_el.text.strip():
                    name = font_el.text.strip()
                    self.assertIn(
                        name,
                        defined,
                        f"{os.path.basename(path)} references undefined font {name!r}",
                    )

    def test_startup_xml_replaces_home_without_external_scripts(self):
        startup_xml = os.path.join(SKIN_XML_DIR, "Startup.xml")
        self.assertTrue(os.path.isfile(startup_xml), f"Missing {startup_xml}")
        raw = open(startup_xml, encoding="utf-8").read()
        self.assertRegex(raw, r"ReplaceWindow\([Hh]ome\)")
        self.assertNotIn("RunScript(", raw)
        self.assertNotIn("RunPlugin(", raw)

    def test_pointer_xml_hidden_on_startup(self):
        pointer_xml = os.path.join(SKIN_XML_DIR, "Pointer.xml")
        self.assertTrue(os.path.isfile(pointer_xml), f"Missing {pointer_xml}")
        root = ET.parse(pointer_xml).getroot()
        top_controls = root.findall("./controls/control")
        self.assertEqual(
            [el.get("id") for el in top_controls],
            ["1", "2", "3", "4"],
            "Pointer.xml must expose id=1..4 directly under <controls> without a group wrapper",
        )
        for el in top_controls:
            vis = el.findtext("visible") or ""
            self.assertIn("!Window.IsActive(startup)", vis)
            self.assertNotIn("!Window.IsActive(home)", vis)

    def test_home_xml_native_1080p_structure_and_idle_dimming(self):
        home_xml = os.path.join(SKIN_XML_DIR, "Home.xml")
        self.assertTrue(os.path.isfile(home_xml), f"Missing {home_xml}")
        root = ET.parse(home_xml).getroot()
        if "id" in root.attrib:
            self.assertEqual(root.attrib["id"], "10000")

        raw = open(home_xml, encoding="utf-8").read()
        self.assertIn("/var/cache/media-stick/wallpapers/", raw)
        self.assertIn("multiimage", raw)
        self.assertIn("System.Time(hh:mm)", raw)
        self.assertIn("Window(Home).Property(ip)", raw)
        self.assertIn("Window(Home).Property(net)", raw)
        self.assertIn("System.IdleTime(30)", raw)

        self.assertIn("<onload>NotifyAll(script.media-stick.home,home_shown)</onload>", raw)
        list100 = next(c for c in root.findall(".//control[@id='100']"))
        self.assertIn("Window(Home).Property(launcher_ready)", list100.findtext("visible") or "")

        control_ids = {
            el.attrib.get("id")
            for el in root.findall(".//control")
            if el.attrib.get("id")
        }
        for req_id in ("100", "200", "201"):
            self.assertIn(
                req_id,
                control_ids,
                f"Home.xml missing required control id={req_id!r}",
            )

    def test_no_forbidden_third_party_invocations_and_no_4k_scaling(self):
        xmls = _all_skin_xml_files()
        self.assertGreater(len(xmls), 0, "Expected skin XML files")
        for path in xmls:
            raw = open(path, encoding="utf-8").read()
            lowered = raw.lower()
            for ref in FORBIDDEN_XML_REFS:
                self.assertNotIn(
                    ref,
                    lowered,
                    f"Forbidden reference {ref!r} found in {os.path.relpath(path, ROOT)}",
                )
            for dim in ("3840", "2160"):
                self.assertNotRegex(
                    raw,
                    rf"<(?:width|height)>{dim}</(?:width|height)>",
                    f"4K virtual coordinate {dim} found in {os.path.relpath(path, ROOT)}",
                )

    def test_includes_ms_tv_progress_zoom_covers_1_to_99_horizontally(self):
        includes = _load_includes()
        self.assertIn(
            "MsTvProgressZoom",
            includes,
            "Includes.xml must define <include name='MsTvProgressZoom'>",
        )
        inc = includes["MsTvProgressZoom"]
        anims = inc.findall("./animation")
        self.assertEqual(
            len(anims),
            99,
            f"MsTvProgressZoom must define 99 zoom animations (P=1..99), got {len(anims)}",
        )
        seen_p = []
        for anim in anims:
            is_cond = (
                (anim.text or "").strip() == "Conditional"
                or anim.attrib.get("type") == "Conditional"
            )
            self.assertTrue(is_cond, "MsTvProgressZoom animations must be Conditional")
            self.assertEqual(anim.attrib.get("effect"), "zoom")
            self.assertEqual(anim.attrib.get("start"), "100,100")
            self.assertEqual(anim.attrib.get("center"), "96,0")
            self.assertEqual(anim.attrib.get("time"), "0")
            self.assertNotEqual(anim.attrib.get("reversible"), "false")
            end = anim.attrib.get("end", "")
            parts = end.split(",")
            self.assertEqual(len(parts), 2, f"Invalid zoom end={end!r}")
            sx, sy = int(parts[0]), int(parts[1])
            self.assertEqual(
                sy,
                100,
                f"Vertical zoom sy must remain 100 across any top, got end={end!r}",
            )
            seen_p.append(sx)
        self.assertEqual(seen_p, list(range(1, 100)))

        probe = ET.fromstring("<control type='image'><include>MsTvProgressZoom</include></control>")
        expanded_probe = _expand_includes(probe, includes)
        for p in range(1, 100):
            bools, strings = _osd_state(ms_tv_osd="1", ms_tv_progress=str(p))
            self.assertEqual(_active_zoom(expanded_probe, bools, strings), (p, 100))
        for boundary in ("", "0", "-1", "100", "101"):
            bools, strings = _osd_state(ms_tv_osd="1", ms_tv_progress=boundary)
            self.assertEqual(
                _active_zoom(expanded_probe, bools, strings),
                (100, 100),
                f"Expected unscaled (100, 100) for ms.tv_progress={boundary!r}",
            )

    def test_video_osd_and_seek_bar_tv_timeline_and_vod_gating(self):
        for path in _all_skin_xml_files():
            root = ET.parse(path).getroot()
            for prog in root.findall(".//control[@type='progress']"):
                info = prog.findtext("info") or ""
                self.assertNotIn(
                    "property(",
                    info.lower(),
                    f"{os.path.basename(path)} progress <info> must not reference Window.Property: {info!r}",
                )

        for check_name in ("Includes.xml", "VideoOSD.xml", "DialogSeekBar.xml"):
            raw = open(os.path.join(SKIN_XML_DIR, check_name), encoding="utf-8").read()
            self.assertNotRegex(
                raw,
                r"(?i)Integer\.[A-Za-z]+\([^)]*Property\(",
                f"{check_name} must not use Integer.* infobools on Window.Property strings",
            )

        media_dir = os.path.join(SKIN_DIR, "media")
        actual_pngs = sorted(
            f for f in os.listdir(media_dir) if f.lower().endswith(".png")
        )
        self.assertEqual(
            actual_pngs,
            sorted(EXPECTED_SKIN_PNGS),
            "No extra PNG textures should be added to skin.media-stick/media",
        )

        includes = _load_includes()
        for win_name, bar_top in (("VideoOSD.xml", 892), ("DialogSeekBar.xml", 900)):
            raw_root, items = _collect_window_controls(win_name, includes)
            for tex_el in raw_root.findall(".//texture"):
                if tex_el.text and tex_el.text.strip():
                    tex_file = os.path.join(media_dir, tex_el.text.strip())
                    self.assertTrue(
                        os.path.isfile(tex_file),
                        f"{win_name} references missing texture {tex_el.text.strip()!r}",
                    )

            prog_items = [
                it
                for it in items
                if it["ctrl"].attrib.get("type") == "progress"
                and it["ctrl"].attrib.get("id") == "400"
            ]
            self.assertEqual(len(prog_items), 1, f"{win_name} must preserve progress id='400'")
            prog400 = prog_items[0]
            self.assertEqual((prog400["ctrl"].findtext("info") or "").strip(), "Player.Progress")
            self.assertEqual(_parse_opt_int(prog400["ctrl"].findtext("left")), 96)
            self.assertEqual(_parse_opt_int(prog400["ctrl"].findtext("top")), bar_top)
            self.assertEqual(_parse_opt_int(prog400["ctrl"].findtext("width")), 1728)
            self.assertEqual(_parse_opt_int(prog400["ctrl"].findtext("height")), 10)
            self.assertTrue(_is_visible(prog400["vis"], *_osd_state(ms_tv_osd="")))
            self.assertFalse(
                _is_visible(prog400["vis"], *_osd_state(ms_tv_osd="1")),
                f"{win_name} progress id='400' must be hidden when ms.tv_osd is set",
            )

            if win_name == "DialogSeekBar.xml":
                slider_items = [
                    it
                    for it in items
                    if it["ctrl"].attrib.get("type") == "slider"
                    and it["ctrl"].attrib.get("id") == "401"
                ]
                self.assertEqual(len(slider_items), 1, "DialogSeekBar.xml must preserve slider id='401'")
                slider401 = slider_items[0]
                for tv_osd in ("", "1"):
                    for fwd in (False, True):
                        for rew in (False, True):
                            for seek in (False, True):
                                want = (tv_osd == "") and (not fwd) and (not rew) and seek
                                got = _is_visible(
                                    slider401["vis"],
                                    *_osd_state(
                                        ms_tv_osd=tv_osd,
                                        forwarding=fwd,
                                        rewinding=rew,
                                        seeking=seek,
                                        paused=True,
                                    ),
                                )
                                self.assertEqual(
                                    got,
                                    want,
                                    f"slider 401 visibility mismatch for tv_osd={tv_osd!r}, fwd={fwd}, rew={rew}, seek={seek}",
                                )

            bar_images = [
                it
                for it in items
                if it["ctrl"].attrib.get("type") == "image"
                and _parse_opt_int(it["ctrl"].findtext("left")) == 96
                and _parse_opt_int(it["ctrl"].findtext("top")) == bar_top
                and _parse_opt_int(it["ctrl"].findtext("width")) == 1728
                and _parse_opt_int(it["ctrl"].findtext("height")) == 10
                and (it["ctrl"].findtext("texture") or "").strip() == "white.png"
            ]
            self.assertEqual(
                len(bar_images),
                2,
                f"{win_name} must define Track and Fill white.png images at (96, {bar_top}, 1728, 10)",
            )
            track, fill = bar_images[0], bar_images[1]
            self.assertLess(track["order"], fill["order"])
            self.assertEqual((track["ox"], track["oy"]), (0, 0))
            self.assertEqual((fill["ox"], fill["oy"]), (0, 0))
            self.assertEqual(
                (track["ctrl"].find("texture").attrib.get("colordiffuse") or "").lower(),
                "33ffffff",
            )
            self.assertEqual(
                (fill["ctrl"].find("texture").attrib.get("colordiffuse") or "").lower(),
                "ffffffff",
            )
            raw_includes_on_images = [
                (inc.text or inc.attrib.get("content") or "").strip()
                for img in raw_root.findall(".//control[@type='image']")
                for inc in img.findall("./include")
            ]
            self.assertIn(
                "MsTvProgressZoom",
                raw_includes_on_images,
                f"{win_name} Fill image must include MsTvProgressZoom",
            )

            for p_str in ("", "50", "100"):
                b_vod, s_vod = _osd_state(ms_tv_osd="", ms_tv_progress=p_str)
                self.assertFalse(_is_visible(track["vis"], b_vod, s_vod))
                self.assertFalse(_is_visible(fill["vis"], b_vod, s_vod))

            for empty_or_zero in ("", "0"):
                b_tv0, s_tv0 = _osd_state(ms_tv_osd="1", ms_tv_progress=empty_or_zero)
                self.assertTrue(_is_visible(track["vis"], b_tv0, s_tv0))
                self.assertFalse(
                    _is_visible(fill["vis"], b_tv0, s_tv0),
                    f"{win_name} Fill image must hide when ms.tv_progress={empty_or_zero!r}",
                )

            for p_val in (1, 50, 99, 100):
                b_tv, s_tv = _osd_state(ms_tv_osd="1", ms_tv_progress=str(p_val))
                self.assertTrue(_is_visible(track["vis"], b_tv, s_tv))
                self.assertTrue(_is_visible(fill["vis"], b_tv, s_tv))
                self.assertEqual(_active_zoom(fill["ctrl"], b_tv, s_tv), (p_val, 100))

    def test_video_osd_and_seek_bar_wall_clock_labels_and_title_width(self):
        includes = _load_includes()
        for win_name in ("VideoOSD.xml", "DialogSeekBar.xml"):
            _raw_root, items = _collect_window_controls(win_name, includes)
            label_items = [
                it for it in items if it["ctrl"].attrib.get("type") == "label"
            ]

            title_items = [
                it
                for it in label_items
                if (it["ctrl"].findtext("label") or "").strip() == "$INFO[VideoPlayer.Title]"
            ]
            self.assertEqual(len(title_items), 1, f"{win_name} missing VideoPlayer.Title label")
            title_it = title_items[0]
            title_left = title_it["ox"] + (_parse_opt_int(title_it["ctrl"].findtext("left")) or 0)
            title_width = _parse_opt_int(title_it["ctrl"].findtext("width"))
            self.assertEqual(title_left, 96)
            self.assertEqual(
                title_width,
                1140,
                f"{win_name} title width must be narrowed to 1140 to avoid overlapping left=1264 time readout",
            )
            self.assertLessEqual(title_left + title_width, 1264)

            def visible_labels(bools, strings):
                out = []
                for it in label_items:
                    if _is_visible(it["vis"], bools, strings):
                        raw_lbl = it["ctrl"].findtext("label") or ""
                        out.append((it, raw_lbl, _render_kodi_label(raw_lbl, strings)))
                return out

            # 1) VOD / YouTube mode (ms.tv_osd empty, even with stale TV properties set)
            b_vod, s_vod = _osd_state(
                ms_tv_osd="",
                player_time="12:34",
                player_duration="1:45:00",
                ms_tv_time_label="22:58 · −27 мин от эфира",
                ms_tv_sublabel="22:00–23:30",
            )
            vod_vis = visible_labels(b_vod, s_vod)
            vod_med24 = [
                (it, txt)
                for it, _raw, txt in vod_vis
                if (it["ctrl"].findtext("font") or "").strip() == "Med24"
                and (it["ctrl"].findtext("align") or "").strip() == "right"
                and txt == "12:34 / 1:45:00"
            ]
            self.assertEqual(
                len(vod_med24),
                1,
                f"{win_name} must render right-aligned Med24 '$INFO[Player.Time] / $INFO[Player.Duration]' when ms.tv_osd is empty",
            )
            vod_it = vod_med24[0][0]
            vod_left = vod_it["ox"] + (_parse_opt_int(vod_it["ctrl"].findtext("left")) or 0)
            vod_width = _parse_opt_int(vod_it["ctrl"].findtext("width")) or 0
            self.assertGreaterEqual(vod_left, 1264)
            self.assertEqual(vod_left + vod_width, 1824)
            for _it, _raw, txt in vod_vis:
                self.assertNotIn("22:58 · −27 мин от эфира", txt)
                self.assertNotIn("22:00–23:30", txt)

            # 2) TV mode with empty ms.tv_sublabel
            b_tv_nosub, s_tv_nosub = _osd_state(
                ms_tv_osd="1",
                ms_tv_progress="50",
                ms_tv_time_label="22:58 · −27 мин от эфира",
                ms_tv_sublabel="",
                player_time="00:10",
                player_duration="01:00",
            )
            tv_nosub_vis = visible_labels(b_tv_nosub, s_tv_nosub)
            tv_med24 = [
                (it, txt)
                for it, _raw, txt in tv_nosub_vis
                if (it["ctrl"].findtext("font") or "").strip() == "Med24"
                and (it["ctrl"].findtext("align") or "").strip() == "right"
                and (it["ox"] + (_parse_opt_int(it["ctrl"].findtext("left")) or 0)) == 1264
                and _parse_opt_int(it["ctrl"].findtext("width")) == 560
            ]
            self.assertEqual(
                len(tv_med24),
                1,
                f"{win_name} must render right-aligned Med24 time readout at left=1264, width=560 when ms.tv_osd is set",
            )
            self.assertEqual(tv_med24[0][1], "22:58 · −27 мин от эфира")
            for _it, raw_lbl, txt in tv_nosub_vis:
                self.assertNotIn("00:10 / 01:00", txt)
                if "ms.tv_sublabel" in raw_lbl and "ms.tv_time_label" not in raw_lbl:
                    self.fail(
                        f"{win_name} dedicated ms.tv_sublabel control must hide when ms.tv_sublabel is empty: {raw_lbl!r}"
                    )

            # 3) TV mode with non-empty ms.tv_sublabel
            b_tv_sub, s_tv_sub = _osd_state(
                ms_tv_osd="1",
                ms_tv_progress="100",
                ms_tv_time_label="22:58 · В эфире",
                ms_tv_sublabel="22:00–23:30",
                player_time="00:10",
                player_duration="01:00",
            )
            tv_sub_vis = visible_labels(b_tv_sub, s_tv_sub)
            tv_sub_med24 = [
                txt
                for it, _raw, txt in tv_sub_vis
                if (it["ctrl"].findtext("font") or "").strip() == "Med24"
                and (it["ctrl"].findtext("align") or "").strip() == "right"
                and (it["ox"] + (_parse_opt_int(it["ctrl"].findtext("left")) or 0)) == 1264
                and _parse_opt_int(it["ctrl"].findtext("width")) == 560
            ]
            self.assertEqual(len(tv_sub_med24), 1)
            self.assertIn("22:58 · В эфире", tv_sub_med24[0])
            self.assertTrue(
                any("22:00–23:30" in txt for _it, _raw, txt in tv_sub_vis),
                f"{win_name} must render ms.tv_sublabel when both ms.tv_osd and ms.tv_sublabel are non-empty",
            )
            for _it, _raw, txt in tv_sub_vis:
                self.assertNotIn("00:10 / 01:00", txt)

    def test_dialog_keyboard_compact_mode_and_localization(self):
        includes = _load_includes()
        raw_root = ET.parse(os.path.join(SKIN_XML_DIR, "DialogKeyboard.xml")).getroot()
        root = _expand_includes(raw_root, includes)
        items = []

        def _walk_all(container, anc_vis):
            for ctrl in container.findall("./control"):
                own_vis = tuple(
                    v.text.strip()
                    for v in ctrl.findall("./visible")
                    if v.text and v.text.strip()
                )
                vis = anc_vis + own_vis
                items.append({"ctrl": ctrl, "vis": vis})
                if ctrl.attrib.get("type") in ("group", "grouplist"):
                    _walk_all(ctrl, vis)

        controls_el = root.find("./controls")
        if controls_el is not None:
            _walk_all(controls_el, ())

        all_ids = {
            it["ctrl"].attrib.get("id")
            for it in items
            if it["ctrl"].attrib.get("id")
        }
        for req_id in ("300", "301", "309", "311", "312", "7000", "9101", "1000", "2000", "3000", "4000", "5000", "6000"):
            self.assertIn(req_id, all_ids, f"DialogKeyboard.xml missing required control id={req_id!r}")

        lang_cases = (
            ("", "Введите текст с телефона в пульте или нажмите «Клавиатура»", "Клавиатура", "Скрыть"),
            ("ru", "Введите текст с телефона в пульте или нажмите «Клавиатура»", "Клавиатура", "Скрыть"),
            ("de", "Введите текст с телефона в пульте или нажмите «Клавиатура»", "Клавиатура", "Скрыть"),
            ("uk", "Введіть текст з телефона в пульті або натисніть «Клавіатура»", "Клавіатура", "Сховати"),
            ("en", "Type on your phone: the remote shows a text box", "Keyboard", "Hide keys"),
        )
        key_rows = ("1000", "2000", "3000", "4000", "5000", "6000")

        for lang, want_hint, want_show, want_hide in lang_cases:
            strings = {"Window(home).Property(media-stick.lang)": lang}

            # Compact mode (default: !Skin.HasSetting(ms_tvkeys))
            bools_compact = {"Skin.HasSetting(ms_tvkeys)": False}
            for row_id in key_rows:
                row_items = [it for it in items if it["ctrl"].attrib.get("id") == row_id]
                self.assertEqual(len(row_items), 1)
                self.assertFalse(
                    _is_visible(row_items[0]["vis"], bools_compact, strings),
                    f"Key row {row_id} must be hidden in compact mode (lang={lang!r})",
                )

            vis_hints = [
                _render_kodi_label(it["ctrl"].findtext("label") or "", strings)
                for it in items
                if it["ctrl"].attrib.get("type") == "label"
                and it["ctrl"].attrib.get("id") != "311"
                and _is_visible(it["vis"], bools_compact, strings)
            ]
            self.assertEqual(
                vis_hints,
                [want_hint],
                f"Compact hint mismatch for lang={lang!r}: got {vis_hints!r}",
            )

            vis_toggles = [
                it["ctrl"]
                for it in items
                if it["ctrl"].attrib.get("id") == "9101"
                and _is_visible(it["vis"], bools_compact, strings)
            ]
            self.assertEqual(
                len(vis_toggles),
                1,
                f"Expected exactly 1 visible 9101 toggle in compact mode for lang={lang!r}",
            )
            self.assertEqual(
                _render_kodi_label(vis_toggles[0].findtext("label") or "", strings),
                want_show,
                f"9101 label mismatch for lang={lang!r}",
            )
            self.assertEqual(
                _render_kodi_label(vis_toggles[0].findtext("altlabel") or "", strings),
                want_hide,
                f"9101 altlabel mismatch for lang={lang!r}",
            )

            # Expanded mode (Skin.HasSetting(ms_tvkeys))
            bools_expanded = {"Skin.HasSetting(ms_tvkeys)": True}
            for row_id in key_rows:
                row_items = [it for it in items if it["ctrl"].attrib.get("id") == row_id]
                self.assertTrue(
                    _is_visible(row_items[0]["vis"], bools_expanded, strings),
                    f"Key row {row_id} must be visible in expanded mode (lang={lang!r})",
                )
            vis_hints_exp = [
                it for it in items
                if it["ctrl"].attrib.get("type") == "label"
                and it["ctrl"].attrib.get("id") != "311"
                and _is_visible(it["vis"], bools_expanded, strings)
            ]
            self.assertEqual(vis_hints_exp, [], f"Compact hint must hide in expanded mode (lang={lang!r})")

            vis_toggles_exp = [
                it["ctrl"]
                for it in items
                if it["ctrl"].attrib.get("id") == "9101"
                and _is_visible(it["vis"], bools_expanded, strings)
            ]
            self.assertEqual(len(vis_toggles_exp), 1)
            self.assertEqual(
                _render_kodi_label(vis_toggles_exp[0].findtext("altlabel") or "", strings),
                want_hide,
            )


if __name__ == "__main__":
    unittest.main()
