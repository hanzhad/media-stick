"""Pure Core UI context schema, secret guard, deterministic trimming, and command validation.

Shared by Kodi UI context publishers and Panel v2 WebSocket/tmpfs handlers so
the Phone Remote Touch Bar and Contextual Search stay strictly bounded, secret-free,
and deterministic on Pi 3B+ (stdlib-only).
"""
import json
import math
import re

from mediastick_onboarding import Refused, looks_secret

CONTEXT_VERSION = 1
MAX_CONTEXT_BYTES = 8192

VALID_APPS = ("", "sweettv", "youtube")
VALID_VIEWS = ("none", "section", "show", "guide", "detail")
VALID_CMD_APPS = ("sweettv", "youtube")
VALID_CMDS = frozenset({
    "set_section",
    "set_filter",
    "sort",
    "search",
    "play",
    "play_from_start",
    "toggle_fav",
    "select_tab",
    "play_episode",
    "play_epg",
})

MAX_SECTIONS = 16
MAX_CHIPS = 16
MAX_DEMO_ITEMS = 25
MAX_SEASON_OR_DAY = 25
MAX_CMD_IDX = 1000

SECRET_KEY_RE = re.compile(
    r"(secret|token|cookie|password|passwd|api_?key|authorization)",
    re.I,
)

# Field string limits for initial normalization
_DEFAULT_LIMITS = {
    "id": 64,
    "section": 64,
    "label": 64,
    "search_query": 128,
    "search_hint": 128,
    "modal_title": 120,
    "modal_label": 48,
    "item_title": 80,
}

# Command schema: (required_fields, optional_fields) where each entry maps name -> ("str", max_len, allow_empty) | ("int", min_v, max_v) | ("bool",)
_CMD_SCHEMA = {
    "set_section": ({"section": ("str", 64, False)}, {}),
    "set_filter": ({"id": ("str", 64, True)}, {"active": ("bool",)}),
    "sort": ({"sort": ("str", 64, False)}, {}),
    "search": ({"query": ("str", 160, True)}, {}),
    "play": ({}, {"id": ("str", 64, False), "cid": ("str", 64, False), "show_id": ("str", 64, False)}),
    "play_from_start": ({}, {"id": ("str", 64, False), "cid": ("str", 64, False), "show_id": ("str", 64, False)}),
    "toggle_fav": ({}, {"fav_key": ("str", 64, False)}),
    "select_tab": ({"idx": ("int", 0, MAX_CMD_IDX)}, {}),
    "play_episode": ({"idx": ("int", 0, MAX_CMD_IDX)}, {"season": ("int", 0, MAX_CMD_IDX)}),
    "play_epg": ({"idx": ("int", 0, MAX_CMD_IDX)}, {}),
}


def empty_context() -> dict:
    """Return a fresh normalized empty UI context document."""
    return {
        "v": CONTEXT_VERSION,
        "app": "",
        "view": "none",
        "section": "",
        "sections": [],
        "chips": [],
        "sort": None,
        "can_search": False,
        "search_query": "",
        "search_hint": "",
        "modal": None,
    }


def _scan_secrets(obj, _ancestors: set[int] | None = None) -> None:
    """Recursively reject secret keys or token-like string values before any truncation."""
    if _ancestors is None:
        _ancestors = set()

    if isinstance(obj, dict):
        oid = id(obj)
        if oid in _ancestors:
            return
        _ancestors.add(oid)
        try:
            for k, v in obj.items():
                if isinstance(k, str):
                    if SECRET_KEY_RE.search(k) or looks_secret(k):
                        raise Refused("forbidden secret key in ui context")
                _scan_secrets(v, _ancestors)
        finally:
            _ancestors.discard(oid)
    elif isinstance(obj, (list, tuple)):
        oid = id(obj)
        if oid in _ancestors:
            return
        _ancestors.add(oid)
        try:
            for item in obj:
                _scan_secrets(item, _ancestors)
        finally:
            _ancestors.discard(oid)
    elif isinstance(obj, str):
        if looks_secret(obj):
            raise Refused("secret-like value in ui context")


def _truncate(text: str, limit: int) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return text[:1]
    return text[: limit - 1].rstrip() + "…"


def _clean_str(val, limit: int) -> str:
    if isinstance(val, bool) or not isinstance(val, (str, int, float)):
        return ""
    if isinstance(val, float) and not math.isfinite(val):
        return ""
    text = " ".join("".join(c if c.isprintable() else " " for c in str(val)).split())
    return _truncate(text, limit)


def _is_int(val) -> bool:
    return isinstance(val, int) and not isinstance(val, bool)


def _encode_bytes(doc: dict) -> bytes:
    return json.dumps(doc, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _norm_labeled_list(items, max_items: int, label_limit: int, include_active: bool) -> list[dict]:
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for raw in items[:max_items]:
        if not isinstance(raw, dict):
            continue
        item_id = _clean_str(raw.get("id"), _DEFAULT_LIMITS["id"])
        label = _clean_str(raw.get("label"), label_limit)
        if not item_id and not label:
            continue
        entry: dict = {"id": item_id, "label": label}
        if include_active or isinstance(raw.get("active"), bool):
            entry["active"] = bool(raw.get("active", False))
        out.append(entry)
    return out


def _norm_sort(raw_sort, label_limit: int) -> dict | None:
    if isinstance(raw_sort, str):
        s = _clean_str(raw_sort, label_limit)
        return {"id": s, "label": s} if s else None
    if not isinstance(raw_sort, dict):
        return None
    sid = _clean_str(raw_sort.get("id"), _DEFAULT_LIMITS["id"])
    label = _clean_str(raw_sort.get("label"), label_limit)
    out: dict = {}
    if sid or label:
        out["id"] = sid
        out["label"] = label
    if isinstance(raw_sort.get("options"), list):
        opts = _norm_labeled_list(raw_sort["options"], MAX_CHIPS, label_limit, include_active=False)
        if opts:
            out["options"] = opts
    return out or None


def _norm_demo_items(items, title_limit: int) -> list[dict]:
    if not isinstance(items, list):
        return []
    out: list[dict] = []
    for raw in items[:MAX_DEMO_ITEMS]:
        if not isinstance(raw, dict):
            continue
        entry: dict = {}
        item_id = _clean_str(raw.get("id"), _DEFAULT_LIMITS["id"])
        title = _clean_str(raw.get("title"), title_limit)
        if item_id:
            entry["id"] = item_id
        if title:
            entry["title"] = title
        for str_key in ("subtitle", "time", "duration", "channel"):
            val = _clean_str(raw.get(str_key), 32)
            if val:
                entry[str_key] = val
        for int_key in ("season", "episode", "number"):
            val = raw.get(int_key)
            if _is_int(val):
                entry[int_key] = val
        if isinstance(raw.get("live"), bool):
            entry["live"] = raw["live"]
        if isinstance(raw.get("can_play"), bool):
            entry["can_play"] = raw["can_play"]
        if entry:
            out.append(entry)
    return out


def _norm_scalar_list(items, max_items: int) -> list:
    if not isinstance(items, list):
        return []
    out = []
    for item in items[:max_items]:
        if _is_int(item):
            out.append(item)
        else:
            s = _clean_str(item, 32)
            if s:
                out.append(s)
    return out


def _norm_modal(raw_modal) -> dict | None:
    if not isinstance(raw_modal, dict):
        return None
    modal: dict = {
        "kind": _clean_str(raw_modal.get("kind"), 32),
        "title": _clean_str(raw_modal.get("title"), _DEFAULT_LIMITS["modal_title"]),
        "fav": bool(raw_modal.get("fav", False)),
        "can_play": bool(raw_modal.get("can_play", False)),
        "can_archive": bool(raw_modal.get("can_archive", False)),
        "demo": bool(raw_modal.get("demo", False)),
    }
    for key in ("show_id", "cid", "fav_key"):
        val = _clean_str(raw_modal.get(key), _DEFAULT_LIMITS["id"])
        if val:
            modal[key] = val
    for key in ("play_label", "alt_label"):
        val = _clean_str(raw_modal.get(key), _DEFAULT_LIMITS["modal_label"])
        if val:
            modal[key] = val
    if "seasons" in raw_modal:
        seasons = _norm_scalar_list(raw_modal.get("seasons"), MAX_SEASON_OR_DAY)
        if seasons:
            modal["seasons"] = seasons
    if "days" in raw_modal:
        days = _norm_scalar_list(raw_modal.get("days"), MAX_SEASON_OR_DAY)
        if days:
            modal["days"] = days
    for sel_key in ("selected_season", "selected_day"):
        sel = raw_modal.get(sel_key)
        if _is_int(sel):
            modal[sel_key] = sel
        elif isinstance(sel, str):
            cleaned = _clean_str(sel, 32)
            if cleaned:
                modal[sel_key] = cleaned

    # episodes and programs are strictly allowed ONLY when demo=True
    if modal["demo"]:
        if "episodes" in raw_modal:
            eps = _norm_demo_items(raw_modal.get("episodes"), _DEFAULT_LIMITS["item_title"])
            if eps:
                modal["episodes"] = eps
        if "programs" in raw_modal:
            progs = _norm_demo_items(raw_modal.get("programs"), _DEFAULT_LIMITS["item_title"])
            if progs:
                modal["programs"] = progs

    return modal


def _shrink_labels(doc: dict, label_limit: int, text_limit: int, item_limit: int) -> None:
    doc["section"] = _truncate(doc["section"], text_limit)
    doc["search_query"] = _truncate(doc["search_query"], text_limit)
    doc["search_hint"] = _truncate(doc["search_hint"], text_limit)
    for item in doc["sections"]:
        item["id"] = _truncate(item["id"], label_limit)
        item["label"] = _truncate(item["label"], label_limit)
    for item in doc["chips"]:
        item["id"] = _truncate(item["id"], label_limit)
        item["label"] = _truncate(item["label"], label_limit)
    if isinstance(doc["sort"], dict):
        if "id" in doc["sort"]:
            doc["sort"]["id"] = _truncate(doc["sort"]["id"], label_limit)
        if "label" in doc["sort"]:
            doc["sort"]["label"] = _truncate(doc["sort"]["label"], label_limit)
        if isinstance(doc["sort"].get("options"), list):
            for opt in doc["sort"]["options"]:
                opt["id"] = _truncate(opt["id"], label_limit)
                opt["label"] = _truncate(opt["label"], label_limit)
    modal = doc["modal"]
    if isinstance(modal, dict):
        modal["title"] = _truncate(modal["title"], text_limit)
        for key in ("play_label", "alt_label"):
            if key in modal:
                modal[key] = _truncate(modal[key], label_limit)
        for list_key in ("episodes", "programs"):
            if isinstance(modal.get(list_key), list):
                for entry in modal[list_key]:
                    if "title" in entry:
                        entry["title"] = _truncate(entry["title"], item_limit)
                    if "subtitle" in entry:
                        entry["subtitle"] = _truncate(entry["subtitle"], label_limit)


def _trim_to_budget(doc: dict) -> dict:
    """Deterministically reduce labels, caps, and non-essential modal fields until <= MAX_CONTEXT_BYTES."""
    if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
        return doc

    # Stage 1: Trim long labels and text fields progressively
    for label_lim, text_lim, item_lim in ((40, 64, 48), (24, 40, 28), (16, 28, 18)):
        _shrink_labels(doc, label_lim, text_lim, item_lim)
        if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
            return doc

    # Stage 2: Trim non-essential modal fields
    modal = doc["modal"]
    if isinstance(modal, dict):
        for list_key in ("episodes", "programs"):
            if isinstance(modal.get(list_key), list):
                for cap in (12, 5, 0):
                    if cap == 0:
                        modal.pop(list_key, None)
                    else:
                        modal[list_key] = modal[list_key][:cap]
                    if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
                        return doc

        for list_key in ("seasons", "days"):
            if isinstance(modal.get(list_key), list):
                for cap in (10, 0):
                    if cap == 0:
                        modal.pop(list_key, None)
                    else:
                        modal[list_key] = modal[list_key][:cap]
                    if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
                        return doc

        for opt_key in ("alt_label", "play_label", "fav_key", "selected_season", "selected_day", "can_archive"):
            if opt_key in modal:
                modal.pop(opt_key, None)
                if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
                    return doc

    # Stage 3: Bound list lengths if still over budget
    while len(doc["chips"]) > 0 or len(doc["sections"]) > 0:
        if len(doc["chips"]) >= len(doc["sections"]) and doc["chips"]:
            doc["chips"] = doc["chips"][: len(doc["chips"]) // 2]
        elif doc["sections"]:
            doc["sections"] = doc["sections"][: len(doc["sections"]) // 2]
        if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
            return doc

    # Final safety fallback
    if doc["modal"] is not None:
        doc["modal"] = None
        if len(_encode_bytes(doc)) <= MAX_CONTEXT_BYTES:
            return doc
    doc["sort"] = None
    doc["search_hint"] = ""
    doc["search_query"] = ""
    doc["section"] = ""
    return doc


def normalize_context(raw) -> dict:
    """Validate, reject secrets before truncation, normalize, and bound a UI context dict."""
    _scan_secrets(raw)
    if not isinstance(raw, dict):
        return empty_context()

    app = raw.get("app")
    view = raw.get("view")
    out = {
        "v": CONTEXT_VERSION,
        "app": app if isinstance(app, str) and app in VALID_APPS else "",
        "view": view if isinstance(view, str) and view in VALID_VIEWS else "none",
        "section": _clean_str(raw.get("section"), _DEFAULT_LIMITS["section"]),
        "sections": _norm_labeled_list(
            raw.get("sections"), MAX_SECTIONS, _DEFAULT_LIMITS["label"], include_active=False
        ),
        "chips": _norm_labeled_list(
            raw.get("chips"), MAX_CHIPS, _DEFAULT_LIMITS["label"], include_active=True
        ),
        "sort": _norm_sort(raw.get("sort"), _DEFAULT_LIMITS["label"]),
        "can_search": bool(raw.get("can_search", False)),
        "search_query": _clean_str(raw.get("search_query"), _DEFAULT_LIMITS["search_query"]),
        "search_hint": _clean_str(raw.get("search_hint"), _DEFAULT_LIMITS["search_hint"]),
        "modal": _norm_modal(raw.get("modal")),
    }
    return _trim_to_budget(out)


def _validate_field(value, spec, name: str):
    kind = spec[0]
    if kind == "str":
        _, max_len, allow_empty = spec
        if not isinstance(value, str):
            raise ValueError(f"field {name} must be a string")
        cleaned = _clean_str(value, max_len)
        if not allow_empty and not cleaned:
            raise ValueError(f"field {name} must be non-empty")
        return cleaned
    if kind == "int":
        _, min_v, max_v = spec
        if not _is_int(value):
            raise ValueError(f"field {name} must be an integer")
        if value < min_v or value > max_v:
            raise ValueError(f"field {name} out of range [{min_v}, {max_v}]")
        return value
    if kind == "bool":
        if not isinstance(value, bool):
            raise ValueError(f"field {name} must be a boolean")
        return value
    raise ValueError(f"unsupported field spec for {name}")


def validate_cmd(data) -> dict:
    """Strictly validate a Phone -> TV `ui_cmd` payload and return a clean copy."""
    if not isinstance(data, dict):
        raise ValueError("ui_cmd payload must be an object")
    _scan_secrets(data)

    app = data.get("app")
    if not isinstance(app, str) or app not in VALID_CMD_APPS:
        raise ValueError(f"invalid app: {app!r}")

    cmd = data.get("cmd")
    if not isinstance(cmd, str) or cmd not in VALID_CMDS:
        raise ValueError(f"unknown ui_cmd: {cmd!r}")

    required, optional = _CMD_SCHEMA[cmd]
    out: dict = {"app": app, "cmd": cmd}

    for field, spec in required.items():
        if field not in data:
            raise ValueError(f"missing required field {field!r} for {cmd}")
        out[field] = _validate_field(data[field], spec, field)

    for field, spec in optional.items():
        if field in data and data[field] is not None:
            out[field] = _validate_field(data[field], spec, field)

    return out
