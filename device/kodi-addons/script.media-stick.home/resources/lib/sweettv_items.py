"""SWEET.TV app: building Kodi ListItems for the 7-section rail, 4x2 card grid, and modals."""
import xbmcgui

from resources.lib import sweettv_sections as sections, sweettv_text as words


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


def card_props(card: sections.Card) -> dict:
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
        "art_mode": card.art_mode,
    }


def apply_card(li, card: sections.Card, prev=None) -> dict:
    props = card_props(card)
    if prev is None:
        for k, v in props.items():
            li.setProperty(k, v)
    else:
        for k, v in props.items():
            if prev.get(k) != v:
                li.setProperty(k, v)
    if card.art:
        li.setArt({"icon": card.art})
    return props


def card_item(card: sections.Card) -> xbmcgui.ListItem:
    li = xbmcgui.ListItem(card.title, offscreen=True)
    apply_card(li, card)
    return li


def modal_tab_items(tabs, active_idx=0) -> list:
    out = []
    for idx, (_, label) in enumerate(tabs):
        li = xbmcgui.ListItem(str(label), offscreen=True)
        li.setProperty("active", "1" if idx == active_idx else "")
        out.append(li)
    return out


def episode_items(episodes) -> list:
    out = []
    for idx, ep in enumerate(episodes):
        title = str(ep.get("title") or "").strip()
        num = int(ep.get("number") or 0)
        if not title:
            title = words.tr("{n} episode").format(n=num or (idx + 1))
        dur = int(ep.get("duration") or 0)
        res = int(ep.get("resume") or 0)
        done = bool(ep.get("watched"))
        if res > 0:
            badge = words.tr("Continue from {time}").format(time=sections.fmt_mmss(res))
        elif done:
            badge = words.tr("Watched")
        elif dur >= 60:
            badge = words.tr("{n} min").format(n=dur // 60)
        else:
            badge = ""
        li = xbmcgui.ListItem(title, badge, offscreen=True)
        li.setProperty("when", words.tr("E{n}").format(n=num) if num else "")
        li.setProperty("kind", "resume" if res > 0 else ("done" if done else ""))
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
