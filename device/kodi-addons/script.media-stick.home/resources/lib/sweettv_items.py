"""SWEET.TV app: the ListItems of the screen. One item per channel, made once per catalog; a minute's tick writes
into them only the properties that changed (a property write makes Kodi redraw the card). Menu entries, the cards of
the shows, episodes and films, and the rows of the programme guide are made here too.
"""
import os

import xbmcgui

from resources.lib import sweettv_data as data, sweettv_sections as sections, sweettv_text as words, sweettv_view as view, ui

DIMMED = "55"                    # the alpha of a card that cannot be watched now


def build(catalog, now, state):
    """(items by channel id, the properties each item has now, category names). The slow part: no lock held."""
    names = dict(catalog.categories)
    items, shown = {}, {}
    for channel in catalog.channels:
        item = xbmcgui.ListItem(channel.name, offscreen=True)
        if channel.logo:
            item.setArt({"icon": channel.logo})
        items[channel.cid] = item
        write_props(item, channel, now, state, names, shown)
    return items, shown, names


def refresh(items, channels, now, state, names, shown):
    """The same channels a minute later."""
    for channel in channels:
        write_props(items[channel.cid], channel, now, state, names, shown)


def write_props(item, channel, now, state, names, shown):
    props = view.card_props(channel, now, channel.cid in state["favourites"], names, view.resume_for(state, channel, now))
    for key in ("bar", "pbar"):
        if props[key]:
            props[key] = os.path.join(ui.MEDIA, props[key])
    old = shown.setdefault(channel.cid, {})
    for key, value in props.items():
        if old.get(key) != value:
            item.setProperty(key, value)
            old[key] = value


def _section(entry) -> bool:
    return entry.group == data.SECTION_GROUP


def _menu_props(item, entry, active_key):
    """What the skin reads from an entry of the menu: the count, the heading the preview shows over the cards, the mark on the
    entry the row follows, and `section` for the second group (Shows and series, Films), drawn in the accent colour."""
    item.setLabel2("" if entry.count is None else str(entry.count))
    item.setProperty("heading", view.section_heading(words.tr(entry.name), entry.count) if _section(entry)
                     else view.category_heading(entry.name, entry.count))
    item.setProperty("active", "1" if entry.key == active_key else "")
    item.setProperty("section", "1" if _section(entry) else "")


def menu_items(entries, active_key):
    """One item per menu entry (sweettv_data.rail): its name (the sections' is translated), how many, and the properties above."""
    out = []
    for entry in entries:
        item = xbmcgui.ListItem(words.tr(entry.name) if _section(entry) else entry.name, offscreen=True)
        _menu_props(item, entry, active_key)
        out.append(item)
    return out


def update_menu(items, entries, active_key):
    """Counts, headings and the marked entry, in place."""
    for entry, item in zip(entries, items):
        _menu_props(item, entry, active_key)


def card_items(rows):
    """The cards of shows, episodes or films (sweettv_sections.Row), made like the channel cards: the channel's picture or its
    badge, the title under it, the colours of the card and of the screen behind it, and what the preview over the row says
    (title, meta, cap, line). `dim` is for what cannot be watched now: its plate is let through."""
    out = []
    for row in rows:
        texts = sections.card_texts(row)
        colours = view.colours(row.mark)
        item = xbmcgui.ListItem(texts.pop("caption"), offscreen=True)
        if row.icon:
            item.setArt({"icon": row.icon})
        props = {**texts, "initials": view.initials(row.mark), "bg": colours["bg"], "dim": "" if row.playable else "1",
                 "plate": colours["plate"] if row.playable else DIMMED + colours["plate"][2:],
                 "plate_hi": colours["plate_hi"] if row.playable else DIMMED + colours["plate_hi"][2:]}
        for key, value in props.items():
            item.setProperty(key, value)
        out.append(item)
    return out


def guide_items(rows):
    out = []
    for row in rows:
        item = xbmcgui.ListItem(row.title, "Live" if row.kind == "live" else "", offscreen=True)
        item.setProperty("when", row.when)
        item.setProperty("kind", row.kind)
        out.append(item)
    return out
