#!/usr/bin/env python3
"""Print the key structure of the SWEET.TV channel list (SweetStore SQLite DB or JSON): names, types and counts, never values.

Usage: python3 tools/sweettv-shape.py [/var/cache/media-stick/sweettv/sweettv.db | /home/media/.kodi/temp/channelList.json]

Run it on the device (or on a copy of the DB/file) once SWEET.TV is signed in, and compare with what
device/kodi-addons/script.media-stick.home/resources/lib/sweettv_data.py reads (its header): the lines marked
"not seen" are fields the app reads when present but whose existence is only a guess."""
import json
import os
import statistics
import sys
import time
from collections import Counter

DEFAULT_DB = "/var/cache/media-stick/sweettv/sweettv.db"
DEFAULT = "/home/media/.kodi/temp/channelList.json"
# what sweettv_data reads: (path, key, sure) - "sure" means the plugin's own source uses it
READ = [("top", "status", True), ("top", "list", True), ("top", "categories", True),
        ("list", "id", True), ("list", "name", True), ("list", "icon_v2_url", True), ("list", "icon_url", False),
        ("list", "category", True), ("list", "catchup", True), ("list", "available", True), ("list", "epg", True),
        ("list", "number", False),
        ("epg", "id", True), ("epg", "time_start", True), ("epg", "time_stop", True), ("epg", "text", True),
        ("epg", "available", True), ("epg", "description", False),
        ("categories", "id", True), ("categories", "caption", True)]


def type_name(value):
    return type(value).__name__ if not isinstance(value, bool) else "bool"


def describe(label, items, out):
    """One block: every key of the dicts in `items` with how many have it and its value types."""
    items = [i for i in items if isinstance(i, dict)]
    keys = Counter()
    kinds = {}
    for item in items:
        for key, value in item.items():
            keys[key] += 1
            kinds.setdefault(key, Counter())[type_name(value)] += 1
    out.append(f"{label}: {len(items)} objects")
    for key in sorted(keys):
        types = ", ".join(f"{t} x{n}" if len(kinds[key]) > 1 else t for t, n in kinds[key].most_common())
        out.append(f"  {key:<22} {keys[key]:>6}/{len(items):<6} {types}")
    return keys


def _load_payload(path):
    if path.endswith(".db"):
        lib_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "device", "files", "usr", "local", "lib", "media-stick"))
        for candidate in ("/usr/local/lib/media-stick", lib_dir):
            if os.path.isdir(candidate) and candidate not in sys.path:
                sys.path.insert(0, candidate)
        import mediastick_sweetstore as sweetstore
        st = sweetstore.SweetStore(path)
        try:
            data = st.get_channels_payload()
        finally:
            st.close()
        return os.path.getsize(path), data
    with open(path, "rb") as f:
        raw = f.read()
    return len(raw), json.loads(raw)


def main(path):
    out = []
    try:
        size_bytes, data = _load_payload(path)
    except (OSError, ValueError) as e:
        sys.exit(f"cannot read {path}: {e}")
    age = time.time() - os.stat(path).st_mtime
    out.append(f"{path}: {size_bytes} bytes, written {int(age)} s ago")
    if not isinstance(data, dict):
        sys.exit(f"top level is a {type_name(data)}, expected an object")
    out.append("top level: " + ", ".join(f"{k} ({type_name(v)}{f' x{len(v)}' if isinstance(v, (list, dict)) else ''})"
                                         for k, v in data.items()))
    seen = {"top": set(data)}
    channels = data.get("list") if isinstance(data.get("list"), list) else []
    seen["list"] = set(describe("list[]", channels, out))
    epg = [e for c in channels if isinstance(c, dict) and isinstance(c.get("epg"), list) for e in c["epg"]]
    sizes = [len(c["epg"]) for c in channels if isinstance(c, dict) and isinstance(c.get("epg"), list)]
    if sizes:
        out.append(f"list[].epg: per channel min {min(sizes)}, median {statistics.median(sizes)}, max {max(sizes)}")
    seen["epg"] = set(describe("list[].epg[]", epg, out))
    cats = Counter(len(c["category"]) for c in channels if isinstance(c, dict) and isinstance(c.get("category"), list))
    out.append("list[].category[]: element types " + ", ".join(sorted({type_name(x) for c in channels if isinstance(c, dict)
                                                                    and isinstance(c.get("category"), list) for x in c["category"]}))
               + "; per channel " + ", ".join(f"{n} x{c}" for n, c in sorted(cats.items())))
    seen["categories"] = set(describe("categories[]", data.get("categories") if isinstance(data.get("categories"), list) else [], out))
    ids = [c.get("id") for c in channels if isinstance(c, dict)]
    out.append(f"channel ids: {len(set(map(str, ids)))} distinct of {len(ids)}")
    out.append("category 1000 used by channels: " + str(any(1000 in c.get("category", []) for c in channels
                                                           if isinstance(c, dict) and isinstance(c.get("category"), list))))
    out.append("")
    for where, key, sure in READ:
        if key not in seen.get(where, ()):
            out.append(f"not seen: {where}.{key} ({'the plugin uses it, so this is a surprise' if sure else 'guessed field'})")
    print("\n".join(out))


if __name__ == "__main__":
    default_target = DEFAULT_DB if os.path.exists(DEFAULT_DB) else DEFAULT
    main(sys.argv[1] if len(sys.argv) > 1 else default_target)
