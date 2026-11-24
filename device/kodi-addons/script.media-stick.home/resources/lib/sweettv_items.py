"""SWEET.TV app: the ListItems of the screen. One item per channel, made once per catalog; a minute's tick writes
into them only the properties that changed (a property write makes Kodi redraw the card). Menu entries and the
rows of the programme guide are made here too.
"""
import os

import xbmcgui

from resources.lib import sweettv_view as view, ui


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


def menu_items(entries, active_key):
    """One item per menu entry: its name, how many channels, the heading the preview shows over the channel,
    and a mark on the category the row shows."""
    out = []
    for entry in entries:
        item = xbmcgui.ListItem(entry.name, str(entry.count), offscreen=True)
        item.setProperty("heading", view.category_heading(entry.name, entry.count))
        item.setProperty("active", "1" if entry.key == active_key else "")
        out.append(item)
    return out


def update_menu(items, entries, active_key):
    """Counts, headings and the marked category, in place."""
    for entry, item in zip(entries, items):
        item.setLabel2(str(entry.count))
        item.setProperty("heading", view.category_heading(entry.name, entry.count))
        item.setProperty("active", "1" if entry.key == active_key else "")


def home_items(entries):
    """The three cards of the first screen: the section's name, what is behind it, how many, its colours."""
    out = []
    for entry in entries:
        item = xbmcgui.ListItem(entry.title, offscreen=True)
        for key, value in (("desc", entry.desc), ("count", entry.count), ("plate", entry.plate), ("plate_hi", entry.plate_hi)):
            item.setProperty(key, value)
        out.append(item)
    return out


def row_items(rows):
    """The lines of a list of shows, episodes or films (sweettv_sections.Row): the title, its second line, the note on the right,
    the channel's picture or its badge, and `dim` for what cannot be watched now."""
    out = []
    for row in rows:
        item = xbmcgui.ListItem(row.title, row.side, offscreen=True)
        if row.icon:
            item.setArt({"icon": row.icon})
        item.setProperty("sub", row.sub)
        item.setProperty("initials", view.initials(row.mark))
        item.setProperty("plate", view.colours(row.mark)["plate"])
        item.setProperty("dim", "" if row.playable else "1")
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
