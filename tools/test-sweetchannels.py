#!/usr/bin/env python3
"""Offline tests for Pure Core 9-tab TV channel taxonomy helper (mediastick_sweetchannels.py).

Covers:
  - Pure Core stdlib-only / zero-xbmc, zero-disk, zero-network import invariants
  - Exported constants: DEFAULT_TAB == "main", HERO_SKIP_META_CATS
  - Duck-typed inputs: sweettv_data.Channel-like objects and channel dicts
  - Curated 9-tab taxonomy (main, g:cinema, g:knowledge, g:kids, g:sport, g:news, g:music, fast, all)
  - Localization ("ru", "uk", "en"), empty-tab omission, and `all` always last in (number == 0, number) order
  - SD-twin deduplication (`sd_twin_dedup`) and 4K/UHD name exclusion boundaries
  - `is_curated_taxonomy`, unknown category auto-append (>= 3 unmapped non-fast), and synthetic fallback
  - Legacy `"live"` alias in `filter_channels_for_tab` and `classify_channels` (tabs, by_tab, tabs_by_cid)
"""
import sys

sys.dont_write_bytecode = True

import ast  # noqa: E402
import importlib  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402
import unittest  # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
LIB = os.path.join(ROOT, "device", "files", "usr", "local", "lib", "media-stick")
SWEETCHANNELS_PY = os.path.join(LIB, "mediastick_sweetchannels.py")

if LIB not in sys.path:
    sys.path.insert(0, LIB)


def _require_sweetchannels(tc: unittest.TestCase):
    if not os.path.isfile(SWEETCHANNELS_PY):
        tc.fail(f"Missing Pure Core module: {SWEETCHANNELS_PY}")
    try:
        return importlib.import_module("mediastick_sweetchannels")
    except Exception as exc:
        tc.fail(f"Failed to import mediastick_sweetchannels: {exc!r}")


def _obj_ch(cid, name, number=0, cats=(), fast=False, available=True, with_available=True):
    ns = types.SimpleNamespace(
        cid=str(cid),
        name=name,
        number=number,
        cats=tuple(str(c) for c in cats),
        fast=bool(fast),
    )
    if with_available:
        ns.available = available
    return ns


def _dict_ch(cid, name, number=0, cats=(), fast=False, available=True, api_keys=False):
    if api_keys:
        return {
            "id": cid,
            "name": name,
            "number": number,
            "category": list(cats),
            "is_fast_channel": fast,
            "available": available,
        }
    return {
        "cid": str(cid),
        "name": name,
        "number": number,
        "cats": tuple(str(c) for c in cats),
        "fast": fast,
        "available": available,
    }


def _cids(channels):
    out = []
    for ch in channels:
        if isinstance(ch, dict):
            out.append(str(ch.get("cid") if "cid" in ch else ch.get("id")))
        else:
            out.append(str(ch.cid))
    return out


SWEETTV_CAT_NAMES = {
    "1": "18+",
    "2": "Детские",
    "4": "Фильмовые",
    "6": "Музыка",
    "8": "Новости",
    "9": "Познавательные",
    "12": "Бесплатное ТВ",
    "15": "Религиозные",
    "16": "Спортивные",
    "20": "Национальные",
    "22": "Премиальные",
    "23": "Рекомендованные",
    "24": "Ultra HD",
    "25": "Региональные",
    "27": "SWEET.TV Originals",
    "28": "Наука",
    "29": "Развлекательные",
    "30": "Сериалы",
    "33": "Телемагазины",
    "36": "Другое",
    "40": "Топ",
    "1000": "Hidden",
}


class TestSweetChannelsModuleHygiene(unittest.TestCase):
    """Pure Core stdlib-only, zero-xbmc/disk/network invariants and exported constants."""

    def test_pure_core_imports_and_constants(self):
        self.assertTrue(os.path.isfile(SWEETCHANNELS_PY), "mediastick_sweetchannels.py must exist")
        with open(SWEETCHANNELS_PY, encoding="utf-8") as f:
            src = f.read()
        tree = ast.parse(src, filename=SWEETCHANNELS_PY)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        forbidden = {
            "xbmc",
            "xbmcgui",
            "xbmcaddon",
            "xbmcvfs",
            "urllib",
            "http",
            "socket",
            "sqlite3",
            "subprocess",
            "pathlib",
            "requests",
        }
        self.assertEqual(imported & forbidden, set(), f"Pure Core must not import I/O/Kodi modules: {imported & forbidden}")

        sc = _require_sweetchannels(self)
        self.assertEqual(sc.DEFAULT_TAB, "main")
        self.assertEqual(sc.HERO_SKIP_META_CATS, frozenset({"12", "23", "27", "40", "1000"}))
        self.assertIsInstance(sc.HERO_SKIP_META_CATS, frozenset)


class TestSdTwinDedup(unittest.TestCase):
    """sd_twin_dedup removes SD twin only when exact '<casefold_name> hd' exists."""

    def test_sd_twin_dedup_table(self):
        sc = _require_sweetchannels(self)
        cases = (
            (
                "drops_discovery_and_animal_planet_sd_twins",
                [
                    _obj_ch("1", "Discovery Channel", number=10, cats=("9", "20")),
                    _obj_ch("2", "Discovery Channel HD", number=11, cats=("9", "20")),
                    _obj_ch("3", "Animal Planet", number=12, cats=("9",)),
                    _obj_ch("4", "ANIMAL PLANET HD", number=13, cats=("9",)),
                ],
                ["2", "4"],
            ),
            (
                "keeps_sd_when_no_exact_hd_twin_and_does_not_overmatch_prefix",
                [
                    _obj_ch("10", "Discovery", number=1, cats=("9",)),
                    _obj_ch("11", "Discovery Science HD", number=2, cats=("9",)),
                    _obj_ch("12", "National Geographic", number=3, cats=("9",)),
                ],
                ["10", "11", "12"],
            ),
            (
                "works_with_api_style_dicts",
                [
                    _dict_ch(20, "1+1", number=1, cats=[20], api_keys=True),
                    _dict_ch(21, "1+1 HD", number=2, cats=[20], api_keys=True),
                    _dict_ch(22, "ICTV", number=3, cats=[20], api_keys=True),
                ],
                ["21", "22"],
            ),
        )
        for label, inputs, want_cids in cases:
            with self.subTest(case=label):
                self.assertEqual(_cids(sc.sd_twin_dedup(inputs)), want_cids)


class TestCuratedTabsAndFacts(unittest.TestCase):
    """Table-driven Facts tests for all 9 curated tabs, exclusions, ordering, and localization."""

    def _realistic_catalog(self):
        return [
            # main eligible (cats 20, 23, 29)
            _obj_ch("101", "1+1 HD", number=1, cats=("20",)),
            _obj_ch("102", "Discovery Channel", number=15, cats=("20", "9")),
            _obj_ch("103", "Discovery Channel HD", number=16, cats=("20", "9")),
            _obj_ch("104", "Animal Planet", number=17, cats=("23", "9")),
            _obj_ch("105", "Animal Planet HD", number=18, cats=("23", "9")),
            _obj_ch("106", "TET", number=5, cats=("29",)),
            _obj_ch("107", "4Kino", number=19, cats=("29",)),  # boundary: "4Kino" is NOT \b4k\b
            # main excluded by category {1, 15, 24, 25, 33}
            _obj_ch("201", "Adult 18+", number=90, cats=("23", "1")),
            _obj_ch("202", "Faith TV", number=91, cats=("20", "15")),
            _obj_ch("203", "Ultra Channel", number=92, cats=("23", "24")),
            _obj_ch("204", "Kyiv Regional", number=93, cats=("20", "25")),
            _obj_ch("205", "Shop TV", number=94, cats=("29", "33")),
            # main excluded by explicit 4K / UHD name
            _obj_ch("206", "EuroSport 4K", number=95, cats=("23", "16")),
            _obj_ch("207", "Insight UHD", number=96, cats=("23", "9")),
            # main excluded by fast=True
            _obj_ch("208", "Comedy 24/7", number=0, cats=("29", "4"), fast=True),
            # thematic tabs
            _obj_ch("301", "TV1000", number=20, cats=("4",)),
            _obj_ch("302", "HBO Series", number=21, cats=("30",)),
            _obj_ch("303", "History", number=22, cats=("28",)),
            _obj_ch("304", "Nickelodeon", number=30, cats=("2",)),
            _obj_ch("305", "Setanta Sports", number=40, cats=("16",)),
            _obj_ch("306", "24 Канал", number=50, cats=("8",)),
            _obj_ch("307", "M1", number=60, cats=("6",)),
            # fast loops in thematic categories (must be quarantined to `fast`, excluded from thematic)
            _obj_ch("401", "Kids Marathon", number=0, cats=("2",), fast=True),
            _obj_ch("402", "Sport Loop", number=0, cats=("16",), fast=True),
            # unavailable channel (must be excluded everywhere including `all`)
            _obj_ch("999", "Unavailable TV", number=2, cats=("20",), available=False),
        ]

    def test_facts_tab_filtering_table(self):
        sc = _require_sweetchannels(self)
        catalog = self._realistic_catalog()
        cases = (
            ("main", ["101", "103", "105", "106", "107"]),
            ("live", ["101", "103", "105", "106", "107"]),  # legacy alias for main
            ("g:cinema", ["301", "302"]),
            ("g:knowledge", ["103", "105", "207", "303"]),  # cats 9 & 28 non-fast + SD-twin dedup
            ("g:kids", ["304"]),
            ("g:sport", ["206", "305"]),
            ("g:news", ["306"]),
            ("g:music", ["307"]),
            ("fast", ["208", "401", "402"]),
        )
        for tab_key, want_cids in cases:
            with self.subTest(tab_key=tab_key):
                got = sc.filter_channels_for_tab(catalog, tab_key, cat_names=SWEETTV_CAT_NAMES)
                self.assertEqual(_cids(got), want_cids)

    def test_all_tab_always_last_and_ordered_by_number_then_zero(self):
        sc = _require_sweetchannels(self)
        catalog = self._realistic_catalog()
        tabs = sc.channel_tabs(catalog, cat_names=SWEETTV_CAT_NAMES, lang="ru")
        self.assertEqual(
            [k for k, _ in tabs],
            ["main", "g:cinema", "g:knowledge", "g:kids", "g:sport", "g:news", "g:music", "fast", "all"],
        )
        all_channels = sc.filter_channels_for_tab(catalog, "all", cat_names=SWEETTV_CAT_NAMES)
        all_cids = _cids(all_channels)
        self.assertNotIn("999", all_cids)
        # Numbered channels ascending (1, 5, 15, ... 96), followed by number=0 fast channels
        numbers = [ch.number for ch in all_channels]
        nonzero = [n for n in numbers if n > 0]
        zeros = [n for n in numbers if n == 0]
        self.assertEqual(nonzero, sorted(nonzero))
        self.assertEqual(numbers, nonzero + zeros)
        self.assertEqual(len(zeros), 3)

    def test_localization_ru_uk_en_and_empty_tab_omission(self):
        sc = _require_sweetchannels(self)
        catalog = self._realistic_catalog()
        expected_labels = {
            "ru": {
                "main": "Основные",
                "g:cinema": "Кино и сериалы",
                "g:knowledge": "Познавательные",
                "g:kids": "Детские",
                "g:sport": "Спорт",
                "g:news": "Новости",
                "g:music": "Музыка",
                "fast": "24/7",
                "all": "Все",
            },
            "uk": {
                "main": "Основні",
                "g:cinema": "Кіно та серіали",
                "g:knowledge": "Пізнавальні",
                "g:kids": "Дитячі",
                "g:sport": "Спорт",
                "g:news": "Новини",
                "g:music": "Музика",
                "fast": "24/7",
                "all": "Усі",
            },
            "en": {
                "main": "Main",
                "g:cinema": "Movies & Series",
                "g:knowledge": "Knowledge",
                "g:kids": "Kids",
                "g:sport": "Sport",
                "g:news": "News",
                "g:music": "Music",
                "fast": "24/7",
                "all": "All",
            },
        }
        for lang, want_map in expected_labels.items():
            with self.subTest(lang=lang):
                tabs = dict(sc.channel_tabs(catalog, cat_names=SWEETTV_CAT_NAMES, lang=lang))
                self.assertEqual(tabs, want_map)

        # Empty curated tabs are omitted while `all` remains last
        minimal = [_obj_ch("1", "News 1", number=1, cats=("8",))]
        min_tabs = sc.channel_tabs(minimal, cat_names=SWEETTV_CAT_NAMES, lang="en")
        self.assertEqual(min_tabs, [("g:news", "News"), ("all", "All")])


class TestTaxonomyDetectionUnknownCatsAndFallback(unittest.TestCase):
    """is_curated_taxonomy, unknown category auto-append (>=3 non-fast), and synthetic fallback."""

    def test_is_curated_taxonomy_signature_ids(self):
        sc = _require_sweetchannels(self)
        for sig in ("8", "9", "16", "20", "25", "27", "29", "30", "33", "40"):
            with self.subTest(sig=sig):
                self.assertTrue(sc.is_curated_taxonomy({sig: "Label"}))
        for non_sig in (None, {}, {"1": "News", "2": "Sport", "1000": "Hidden"}):
            with self.subTest(non_sig=non_sig):
                self.assertFalse(sc.is_curated_taxonomy(non_sig))

    def test_unknown_category_auto_append_threshold_and_placement(self):
        sc = _require_sweetchannels(self)
        cat_names = dict(SWEETTV_CAT_NAMES)
        cat_names["99"] = "Podcasts"
        cat_names["98"] = "TooFew"
        cat_names["97"] = "MostlyFast"

        channels = [
            _obj_ch("1", "M1", number=1, cats=("6",)),
            # 3 unmapped non-fast in cat "99" -> MUST append ("c:99", "Podcasts") between g:music and fast
            _obj_ch("10", "Pod 1", number=10, cats=("99",)),
            _obj_ch("11", "Pod 2", number=11, cats=("99",)),
            _obj_ch("12", "Pod 3", number=12, cats=("99",)),
            # boundary: only 2 unmapped non-fast in cat "98" -> must NOT append
            _obj_ch("20", "Few 1", number=20, cats=("98",)),
            _obj_ch("21", "Few 2", number=21, cats=("98",)),
            # boundary: 2 non-fast + 1 fast in cat "97" -> only 2 non-fast, must NOT append
            _obj_ch("30", "Mix 1", number=30, cats=("97",)),
            _obj_ch("31", "Mix 2", number=31, cats=("97",)),
            _obj_ch("32", "Mix Fast", number=0, cats=("97",), fast=True),
            # known SWEET.TV ID "22" and hidden "1000" with >= 3 channels -> must NOT append
            _obj_ch("40", "Prem 1", number=40, cats=("22",)),
            _obj_ch("41", "Prem 2", number=41, cats=("22",)),
            _obj_ch("42", "Prem 3", number=42, cats=("22",)),
            _obj_ch("50", "Hid 1", number=50, cats=("1000",)),
            _obj_ch("51", "Hid 2", number=51, cats=("1000",)),
            _obj_ch("52", "Hid 3", number=52, cats=("1000",)),
        ]
        tabs = sc.channel_tabs(channels, cat_names=cat_names, lang="ru")
        self.assertEqual(
            tabs,
            [
                ("g:music", "Музыка"),
                ("c:99", "Podcasts"),
                ("fast", "24/7"),
                ("all", "Все"),
            ],
        )
        self.assertEqual(_cids(sc.filter_channels_for_tab(channels, "c:99", cat_names=cat_names)), ["10", "11", "12"])

    def test_synthetic_catalog_fallback_preserves_cat_1_and_hides_1000(self):
        sc = _require_sweetchannels(self)
        synth_cats = {"1": "News", "2": "Movies", "1000": "Hidden"}
        channels = [
            _dict_ch(1, "Alpha News", number=1, cats=[1], api_keys=True),
            _dict_ch(2, "Beta Movies", number=2, cats=[2], api_keys=True),
            _dict_ch(3, "Hidden Ch", number=3, cats=[1000], api_keys=True),
            _dict_ch(4, "Fast Loop", number=0, cats=[1], fast=True, api_keys=True),
        ]
        tabs = sc.channel_tabs(channels, cat_names=synth_cats, lang="en")
        self.assertEqual(
            tabs,
            [
                ("main", "Main"),
                ("c:1", "News"),
                ("c:2", "Movies"),
                ("fast", "24/7"),
                ("all", "All"),
            ],
        )
        self.assertEqual(_cids(sc.filter_channels_for_tab(channels, "main", cat_names=synth_cats)), ["1", "2", "3"])
        self.assertEqual(_cids(sc.filter_channels_for_tab(channels, "c:1", cat_names=synth_cats)), ["1"])
        self.assertEqual(_cids(sc.filter_channels_for_tab(channels, "fast", cat_names=synth_cats)), ["4"])
        self.assertEqual(_cids(sc.filter_channels_for_tab(channels, "all", cat_names=synth_cats)), ["1", "2", "3", "4"])


class TestClassifyChannelsAndDuckTyping(unittest.TestCase):
    """classify_channels returns (tabs, by_tab, tabs_by_cid) for mixed dict/object inputs."""

    def test_classify_channels_mixed_inputs_and_object_without_available_attr(self):
        sc = _require_sweetchannels(self)
        channels = [
            _obj_ch("1", "1+1 HD", number=1, cats=("20", "8"), with_available=False),
            _dict_ch("2", "Cartoon", number=2, cats=("2",), api_keys=False),
            _dict_ch(3, "Loop 24/7", number=0, cats=[4], fast=True, api_keys=True),
        ]
        tabs, by_tab, tabs_by_cid = sc.classify_channels(channels, cat_names=SWEETTV_CAT_NAMES, lang="en")
        self.assertEqual(
            tabs,
            [
                ("main", "Main"),
                ("g:kids", "Kids"),
                ("g:news", "News"),
                ("fast", "24/7"),
                ("all", "All"),
            ],
        )
        self.assertEqual(set(by_tab.keys()), {"main", "g:kids", "g:news", "fast", "all"})
        self.assertEqual(_cids(by_tab["main"]), ["1"])
        self.assertEqual(_cids(by_tab["g:kids"]), ["2"])
        self.assertEqual(_cids(by_tab["g:news"]), ["1"])
        self.assertEqual(_cids(by_tab["fast"]), ["3"])
        self.assertEqual(_cids(by_tab["all"]), ["1", "2", "3"])
        self.assertEqual(tabs_by_cid["1"], ["main", "g:news", "all"])
        self.assertEqual(tabs_by_cid["2"], ["g:kids", "all"])
        self.assertEqual(tabs_by_cid["3"], ["fast", "all"])


if __name__ == "__main__":
    unittest.main()
