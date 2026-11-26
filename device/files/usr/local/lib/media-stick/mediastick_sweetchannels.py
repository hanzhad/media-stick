"""Pure Core 9-tab TV channel taxonomy for SWEET.TV (shared by Kodi TV UI and Phone Remote).

Ready channel data in -> tabs, filtered lists, and per-channel tab indices out.
Standard library only: zero Kodi, disk, or network imports.
"""
import re
from typing import Dict, List, Tuple

DEFAULT_TAB = "main"
HERO_SKIP_META_CATS = frozenset({"12", "23", "27", "40", "1000"})

HIDDEN_CAT_ID = "1000"
SIGNATURE_CAT_IDS = frozenset({"8", "9", "16", "20", "25", "27", "29", "30", "33", "40"})
KNOWN_CAT_IDS = frozenset({
    "1", "2", "4", "6", "8", "9", "12", "15", "16", "20", "22", "23", "24", "25", "27", "28", "29", "30", "33", "36", "40",
})
MAIN_INCLUDE_CATS = frozenset({"20", "23", "29"})
MAIN_EXCLUDE_CATS = frozenset({"1", "15", "24", "25", "33"})
CINEMA_CATS = frozenset({"4", "30"})
KNOWLEDGE_CATS = frozenset({"9", "28"})
UNKNOWN_CAT_MIN_CHANNELS = 3

_FOUR_K_RE = re.compile(r"\b(?:4k|uhd)\b", re.I)

_TAB_LABELS = {
    "main": {"ru": "Основные", "uk": "Основні", "en": "Main"},
    "g:cinema": {"ru": "Кино и сериалы", "uk": "Кіно та серіали", "en": "Movies & Series"},
    "g:knowledge": {"ru": "Познавательные", "uk": "Пізнавальні", "en": "Knowledge"},
    "g:kids": {"ru": "Детские", "uk": "Дитячі", "en": "Kids"},
    "g:sport": {"ru": "Спорт", "uk": "Спорт", "en": "Sport"},
    "g:news": {"ru": "Новости", "uk": "Новини", "en": "News"},
    "g:music": {"ru": "Музыка", "uk": "Музика", "en": "Music"},
    "fast": {"ru": "24/7", "uk": "24/7", "en": "24/7"},
    "all": {"ru": "Все", "uk": "Усі", "en": "All"},
}


def _normalize_lang(lang) -> str:
    if not isinstance(lang, str) or not lang.strip():
        return "ru"
    base = lang.strip().replace("-", "_").split("_", 1)[0].lower()
    if base in ("ru", "uk", "en"):
        return base
    if base == "be":
        return "ru"
    return "en"


def _tab_label(tab_key: str, lang_code: str) -> str:
    entry = _TAB_LABELS.get(tab_key)
    if not entry:
        return tab_key
    return entry.get(lang_code) or entry["en"]


def _cat_key(raw_key) -> str:
    if raw_key is None or isinstance(raw_key, bool):
        return ""
    s = str(raw_key).strip()
    if s.startswith("c:"):
        s = s[2:]
    return s


def _normalize_cat_names(cat_names) -> Dict[str, str]:
    if not cat_names:
        return {}
    out: Dict[str, str] = {}
    if isinstance(cat_names, dict):
        for k, v in cat_names.items():
            ck = _cat_key(k)
            if ck:
                out[ck] = "" if v is None else str(v)
        return out
    if isinstance(cat_names, (list, tuple)):
        for item in cat_names:
            if isinstance(item, dict):
                ck = _cat_key(item.get("id"))
                val = item.get("caption") if item.get("caption") is not None else item.get("name")
                if ck:
                    out[ck] = "" if val is None else str(val)
            elif isinstance(item, (list, tuple)) and len(item) >= 2:
                ck = _cat_key(item[0])
                if ck:
                    out[ck] = "" if item[1] is None else str(item[1])
    return out


def _extract_cid(ch) -> str:
    if isinstance(ch, dict):
        raw = ch.get("cid") if ("cid" in ch and ch.get("cid") is not None) else ch.get("id")
    else:
        raw = getattr(ch, "cid", None)
        if raw is None:
            raw = getattr(ch, "id", None)
    return "" if raw is None else str(raw)


def _extract_name(ch) -> str:
    raw = ch.get("name") if isinstance(ch, dict) else getattr(ch, "name", "")
    return "" if raw is None else str(raw)


def _extract_number(ch) -> int:
    raw = ch.get("number") if isinstance(ch, dict) else getattr(ch, "number", 0)
    if isinstance(raw, bool) or raw is None:
        return 0
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _extract_cats(ch) -> Tuple[str, ...]:
    if isinstance(ch, dict):
        raw = ch.get("cats") if ("cats" in ch and ch.get("cats") is not None) else ch.get("category")
    else:
        raw = getattr(ch, "cats", None)
        if raw is None:
            raw = getattr(ch, "category", None)
    if not isinstance(raw, (list, tuple, set, frozenset)):
        return ()
    return tuple(dict.fromkeys(
        s for c in raw if c is not None and not isinstance(c, bool)
        for s in (str(c).strip(),) if s
    ))


def _extract_fast(ch) -> bool:
    if isinstance(ch, dict):
        val = ch.get("fast") if ("fast" in ch and ch.get("fast") is not None) else ch.get("is_fast_channel")
        return bool(val)
    if hasattr(ch, "fast"):
        return bool(getattr(ch, "fast"))
    return bool(getattr(ch, "is_fast_channel", False))


def _extract_available(ch) -> bool:
    val = ch.get("available", True) if isinstance(ch, dict) else getattr(ch, "available", True)
    return val is not False


def _norm_channel_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def sd_twin_dedup(channels) -> list:
    """Drop non-HD channel when an exact '<casefold_name> hd' exists in `channels`."""
    items = list(channels or ())
    names = {_norm_channel_name(_extract_name(ch)) for ch in items}
    out = []
    for ch in items:
        cf = _norm_channel_name(_extract_name(ch))
        if cf and not cf.endswith(" hd") and f"{cf} hd" in names:
            continue
        out.append(ch)
    return out


def is_curated_taxonomy(cat_names) -> bool:
    """Return True when `cat_names` contains any SWEET.TV signature category ID."""
    cmap = _normalize_cat_names(cat_names)
    return bool(set(cmap.keys()) & SIGNATURE_CAT_IDS)


def _group_non_fast_by_cat(cmap: Dict[str, str], entries: list, skip_ids: frozenset) -> Dict[str, list]:
    buckets: Dict[str, list] = {}
    for cid_cat in cmap:
        if cid_cat not in skip_ids:
            buckets.setdefault(cid_cat, [])
    for ch, _, _, cats, _, fast in entries:
        if fast:
            continue
        for cid_cat in cats:
            if cid_cat not in skip_ids:
                buckets.setdefault(cid_cat, []).append(ch)
    return buckets


def _build_taxonomy(channels, cat_names=None, lang="ru") -> Tuple[List[Tuple[str, str]], Dict[str, list]]:
    lang_code = _normalize_lang(lang)
    cmap = _normalize_cat_names(cat_names)
    entries = []
    for ch in (channels or ()):
        if not _extract_available(ch):
            continue
        cats = _extract_cats(ch)
        entries.append((
            ch,
            _extract_name(ch),
            _extract_number(ch),
            cats,
            frozenset(cats),
            _extract_fast(ch),
        ))

    all_channels = [e[0] for e in sorted(entries, key=lambda e: (e[2] == 0, e[2]))]
    fast_channels = [e[0] for e in entries if e[5]]
    tabs: List[Tuple[str, str]] = []
    by_tab: Dict[str, list] = {}

    if set(cmap.keys()) & SIGNATURE_CAT_IDS:
        main_raw = [
            e[0] for e in entries
            if not e[5]
            and (e[4] & MAIN_INCLUDE_CATS)
            and not (e[4] & MAIN_EXCLUDE_CATS)
            and not _FOUR_K_RE.search(e[1])
        ]
        curated_groups = (
            ("main", sd_twin_dedup(main_raw)),
            ("g:cinema", [e[0] for e in entries if not e[5] and (e[4] & CINEMA_CATS)]),
            ("g:knowledge", sd_twin_dedup([e[0] for e in entries if not e[5] and (e[4] & KNOWLEDGE_CATS)])),
            ("g:kids", [e[0] for e in entries if not e[5] and "2" in e[4]]),
            ("g:sport", [e[0] for e in entries if not e[5] and "16" in e[4]]),
            ("g:news", [e[0] for e in entries if not e[5] and "8" in e[4]]),
            ("g:music", [e[0] for e in entries if not e[5] and "6" in e[4]]),
        )
        for tab_key, ch_list in curated_groups:
            if ch_list:
                tabs.append((tab_key, _tab_label(tab_key, lang_code)))
                by_tab[tab_key] = ch_list

        unknown_buckets = _group_non_fast_by_cat(cmap, entries, KNOWN_CAT_IDS | {HIDDEN_CAT_ID})
        for cid_cat, ch_list in unknown_buckets.items():
            if len(ch_list) >= UNKNOWN_CAT_MIN_CHANNELS:
                tab_key = f"c:{cid_cat}"
                tabs.append((tab_key, cmap.get(cid_cat) or cid_cat))
                by_tab[tab_key] = ch_list
    else:
        main_channels = [e[0] for e in entries if not e[5]]
        if main_channels:
            tabs.append(("main", _tab_label("main", lang_code)))
            by_tab["main"] = main_channels

        for cid_cat, ch_list in _group_non_fast_by_cat(cmap, entries, frozenset({HIDDEN_CAT_ID})).items():
            if ch_list:
                tab_key = f"c:{cid_cat}"
                tabs.append((tab_key, cmap.get(cid_cat) or cid_cat))
                by_tab[tab_key] = ch_list

    if fast_channels:
        tabs.append(("fast", _tab_label("fast", lang_code)))
        by_tab["fast"] = fast_channels

    tabs.append(("all", _tab_label("all", lang_code)))
    by_tab["all"] = all_channels
    return tabs, by_tab


def channel_tabs(channels, cat_names=None, lang="ru") -> List[Tuple[str, str]]:
    """Return ordered `(tab_key, label)` pairs for `channels`."""
    tabs, _ = _build_taxonomy(channels, cat_names=cat_names, lang=lang)
    return tabs


def filter_channels_for_tab(channels, tab_key, cat_names=None) -> list:
    """Return filtered channels for `tab_key` (accepting legacy `'live'` as alias for `'main'`)."""
    key = DEFAULT_TAB if tab_key == "live" else tab_key
    _, by_tab = _build_taxonomy(channels, cat_names=cat_names)
    return list(by_tab.get(key) or ())


def classify_channels(
    channels, cat_names=None, lang="ru"
) -> Tuple[List[Tuple[str, str]], Dict[str, list], Dict[str, List[str]]]:
    """Return `(tabs, by_tab, tabs_by_cid)` for TV and Phone Remote consumers."""
    tabs, by_tab = _build_taxonomy(channels, cat_names=cat_names, lang=lang)
    tabs_by_cid: Dict[str, List[str]] = {}
    for tab_key, _ in tabs:
        for ch in by_tab[tab_key]:
            cid = _extract_cid(ch)
            if not cid:
                continue
            bucket = tabs_by_cid.setdefault(cid, [])
            if tab_key not in bucket:
                bucket.append(tab_key)
    return tabs, by_tab, tabs_by_cid
