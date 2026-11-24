"""SWEET.TV app: the search entry of the menu. Ready data in, rows out; nothing here touches Kodi.

What is looked for is SWEET.TV own search (mediastick_sweetapi, the code the phone page asks too), not the channel list: the
list holds only a few days of the guide around now, so a show that aired on Friday is not in it on Tuesday. The API rows
(programmes, channels, films, people) become the cards of the row (sweettv_sections.Row), the same cards as the shows and the
films have, so OK on one plays it like any other: a programme from the archive, a channel (or a programme that is on now) live.
Only programmes and channels are shown: a film of the library or a person cannot be played from here yet.

  channels_of(catalog)                         the lookup the API module wants (name, archive) made from the TV channels
  rows(items, now, logos)                      the cards of the API rows
  demo_reply(catalog, needle, now)             invented results in the shape of the API reply, from the demo channels
"""
from resources.lib import sweettv_data as data, sweettv_sections as sections, sweettv_text as words

MAX_RESULTS = 60                  # cards kept (the API module cuts too)
KINDS = ("programme", "channel")  # what the row can play


def _libs():
    """mediastick_sweetapi of the device library; None when it is not there."""
    try:
        from resources.lib import store
        return store.sweetapi
    except Exception:
        return None


def channels_of(catalog) -> dict:
    """{channel id: {id, name, catchup, catchup_duration, available}}: the channel lookup of mediastick_sweetapi, from the channels
    the screen knows (those the account may watch), in the shape of the slimmed channel list."""
    return {c.cid: {"id": c.cid, "name": c.name, "catchup": c.catchup, "catchup_duration": c.days, "available": True}
            for c in (catalog.channels if catalog else ())}


def _line(*parts) -> str:
    return "  ·  ".join(p for p in parts if p)


def _programme(item, now, logos) -> sections.Row:
    title = data.clean_text(item["title"], 120)
    channel = data.clean_text(item["channel_name"], 80)
    live, playable = bool(item["live"]), bool(item["playable"])
    future = not playable and item["start"] > now
    note = words.tr("Live") if live and playable else "" if playable else words.tr("Soon" if future else "Not in the archive")
    return sections.Row("", title, _line(channel, data.clean_text(item["more"], 60)), data.clean_text(item["when"], 60),
                        data.logo_of(item["preview"], logos.get(item["cid"], "")), channel or title, playable, future, item["cid"],
                        "" if live else item["epg"], item["start"], item["stop"], title, note)


def _channel(item, logos) -> sections.Row:
    title = data.clean_text(item["channel_name"] or item["title"], 80)
    playable = bool(item["playable"])
    return sections.Row("", title, words.tr("Channel"), "", data.logo_of(logos.get(item["cid"], "")), title, playable, False,
                        item["cid"], "", 0, 0, title, words.tr("Live") if playable else words.tr("Not in the list"))


def rows(items, now, logos) -> list:
    """The cards of `items` (mediastick_sweetapi's rows) in their order, programmes and channels only; `logos` maps a channel id
    to its picture (the card has the programme's own picture when the API gave one)."""
    out = []
    for item in items if isinstance(items, list) else ():
        if isinstance(item, dict) and item.get("kind") in KINDS:
            out.append(_programme(item, now, logos) if item["kind"] == "programme" else _channel(item, logos))
    return out[:MAX_RESULTS]


def demo_reply(catalog, needle, now) -> dict:
    """What SWEET.TV would answer to `needle` if its programmes were those of the demo channels: a programme whose title holds
    the needle, a channel whose name does (the shape of SearchService/Search.json; nothing is asked of the network)."""
    wanted = " ".join(str(needle).casefold().split())
    found = []
    for channel in catalog.channels if catalog else ():
        if wanted and wanted in channel.name.casefold():
            found.append({"type": "Channel", "id": channel.cid, "text": channel.name, "subtext": "", "slug": ""})
        for p in channel.epg:
            if wanted and p.epg_id and wanted in p.title.casefold():
                found.append({"type": "EpgRecord", "id": p.epg_id, "sub_id": channel.cid, "text": p.title,
                              "time_start": str(p.start), "time_stop": str(p.stop), "slug": ""})
    return {"result": found}
