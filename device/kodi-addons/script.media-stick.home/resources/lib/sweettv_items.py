"""SWEET.TV app: building Kodi ListItems for the 7-section rail, 4x2 card grid, and modals."""
import xbmcgui

from resources.lib import sweettv_data as data, sweettv_sections as sections, sweettv_text as words


def rail_items(active_section, counts=None) -> list:
    counts = counts or {}
    out = []
    for key, msgid in sections.RAIL:
        name = words.tr(msgid)
        count = counts.get(key)
        li = xbmcgui.ListItem(name, str(count) if count is not None else "", offscreen=True)
        li.setProperty("section", key)
        li.setProperty("key", key)
        li.setProperty("active", "1" if key == active_section else "")
        li.setProperty("heading", name)
        out.append(li)
    return out


def _card_art(card: sections.Card, wide=False) -> tuple:
    if wide:
        backdrop = card.wide_art or (card.banner if card.art_mode != "logo" else "")
        if backdrop:
            return backdrop, ""
    return card.art, card.art_mode


def card_props(card: sections.Card, wide=False) -> dict:
    _, art_mode = _card_art(card, wide=wide)
    return {
        "kind": card.kind,
        "key": card.key,
        "fav_key": card.fav_key,
        "title": card.title,
        "small": "1" if card.small else "",
        "meta": card.meta,
        "desc": card.desc,
        "bar": card.bar,
        "pbar": card.pbar,
        "fav": "1" if card.fav else "",
        "catchup": "1" if card.catchup else "",
        "guide": "1" if card.kind == "channel" else "",
        "dim": "1" if card.dim else "",
        "num": card.num,
        "initials": card.initials,
        "plate": card.plate,
        "plate_hi": card.plate_hi,
        "bg": card.bg,
        "tint": card.tint,
        "now": card.now,
        "nowline": card.nowline,
        "next": card.next,
        "nextline": card.nextline,
        "resume": card.resume_label,
        "art_mode": art_mode,
    }


def apply_card(li, card: sections.Card, prev=None, wide=False) -> dict:
    if hasattr(li, "setLabel"):
        li.setLabel(card.title)
    icon, _ = _card_art(card, wide=wide)
    props = card_props(card, wide=wide)
    if prev is None:
        for k, v in props.items():
            li.setProperty(k, v)
    else:
        for k, v in props.items():
            if prev.get(k) != v:
                li.setProperty(k, v)
    if icon:
        li.setArt({"icon": icon})
    elif prev is not None and hasattr(li, "setArt"):
        li.setArt({"icon": ""})
    return props


def card_item(card: sections.Card, wide=False) -> xbmcgui.ListItem:
    li = xbmcgui.ListItem(card.title, offscreen=True)
    apply_card(li, card, wide=wide)
    return li


def chip_items(chips, active_key="") -> list:
    out = []
    for key, label in (chips or ()):
        li = xbmcgui.ListItem(str(label), offscreen=True)
        li.setProperty("key", str(key))
        li.setProperty("active", "1" if key == active_key else "")
        out.append(li)
    return out


def modal_tab_items(tabs, active_idx=0) -> list:
    out = []
    for idx, (_, label) in enumerate(tabs):
        li = xbmcgui.ListItem(str(label), offscreen=True)
        li.setProperty("active", "1" if idx == active_idx else "")
        out.append(li)
    return out


def episode_items(episodes, fallback_art="") -> list:
    out = []
    for idx, ep in enumerate(episodes):
        title = str(ep.get("title") or "").strip()
        num = int(ep.get("number") or 0)
        if not title:
            title = words.tr("{n} episode").format(n=num or (idx + 1))
        dur = int(ep.get("duration") or 0)
        res = int(ep.get("resume") or 0)
        done = bool(ep.get("watched"))
        soon = bool(ep.get("coming_soon")) or (ep.get("playable") is False)
        release_date = str(ep.get("release_date") or "").strip()
        when = words.tr("E{n}").format(n=num) if num else ""
        if soon:
            soon_word = words.tr("Soon")
            badge = f"{soon_word} · {release_date}" if release_date else soon_word
            label2 = badge
            bar = ""
            kind = "future"
            sub = badge
        else:
            badge = words.tr("Watched") if done else ""
            if res > 0:
                label2 = words.tr("Continue from {time}").format(time=sections.fmt_mmss(res))
                kind = "resume"
            elif done:
                label2 = badge
                kind = "done"
            elif dur >= 60:
                label2 = words.tr("{n} min").format(n=dur // 60)
                kind = ""
            else:
                label2 = ""
                kind = ""
            if done:
                bar = data.bar_name(data.BAR_STEPS)
            elif res > 0 and dur > 0:
                bar = sections._bar_from_fraction(min(1.0, res / dur))
            else:
                bar = ""
            sub = label2
        now_line = "  ·  ".join(p for p in (when, sub) if p)
        icon = str(ep.get("preview") or ep.get("image_url") or fallback_art or "")
        li = xbmcgui.ListItem(title, label2, offscreen=True)
        li.setProperty("when", when)
        li.setProperty("now", now_line)
        li.setProperty("badge", badge)
        li.setProperty("bar", bar)
        li.setProperty("coming_soon", "1" if soon else "")
        li.setProperty("kind", kind)
        if icon:
            li.setArt({"icon": icon})
        out.append(li)
    return out


def guide_items(rows) -> list:
    out = []
    for r in rows:
        title = str(r.get("title") or "")
        if r.get("live"):
            badge = words.tr("Live")
            kind = "live"
        elif r.get("can_archive"):
            badge = words.tr("Archive")
            kind = "archive"
        else:
            badge = words.tr("Soon") if r.get("start", 0) > 0 else ""
            kind = "future"
        li = xbmcgui.ListItem(title, badge, offscreen=True)
        li.setProperty("when", str(r.get("when") or ""))
        li.setProperty("kind", kind)
        out.append(li)
    return out
