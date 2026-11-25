#!/usr/bin/env python3
"""Contract tests for the native 1080p Kodi skin (device/kodi-addons/skin.media-stick)."""
import os
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


def _all_skin_xml_files():
    xmls = []
    if not os.path.isdir(SKIN_DIR):
        return xmls
    for dirpath, _dirnames, filenames in os.walk(SKIN_DIR):
        for name in sorted(filenames):
            if name.endswith(".xml"):
                xmls.append(os.path.join(dirpath, name))
    return xmls


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

    def test_pointer_xml_hidden_on_startup_and_home(self):
        pointer_xml = os.path.join(SKIN_XML_DIR, "Pointer.xml")
        self.assertTrue(os.path.isfile(pointer_xml), f"Missing {pointer_xml}")
        root = ET.parse(pointer_xml).getroot()
        visibles = [
            el.text.strip()
            for el in root.findall(".//control/visible")
            if el.text and el.text.strip()
        ]
        self.assertTrue(visibles, "Pointer.xml must define a <visible> guard on its pointer control")
        combined = " ".join(visibles)
        self.assertIn("!Window.IsActive(startup)", combined)
        self.assertIn("!Window.IsActive(home)", combined)

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


if __name__ == "__main__":
    unittest.main()
