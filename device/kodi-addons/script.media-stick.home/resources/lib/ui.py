"""Shared bits of the launcher's own full-screen dialogs."""
import os

import xbmc
import xbmcaddon
import xbmcgui

LOG = "[script.media-stick.home]"
ADDON_PATH = xbmcaddon.Addon().getAddonInfo("path")
MEDIA = os.path.join(ADDON_PATH, "resources", "skins", "default", "media")
HOME = 10000                             # the Home window: its properties are shared by every script
ACTION_PREVIOUS_MENU = 10
ACTION_NAV_BACK = 92
BACK_ACTIONS = (ACTION_PREVIOUS_MENU, ACTION_NAV_BACK)


def log(text, level=xbmc.LOGWARNING):
    xbmc.log(f"{LOG} {text}", level)


def notify(text):
    xbmcgui.Dialog().notification("Media Stick", text, xbmcgui.NOTIFICATION_INFO, 4000)


def load(dialog_class, xml):
    """A dialog of the launcher skin, ready for doModal()."""
    return dialog_class(xml, ADDON_PATH, "default", "1080i")


def fill_list(window, control_id, rows, select=0):
    """Replace the items of the list control `control_id` with one item per row (a dict of item properties; the label
    is the row's "t1" when it has one) and put the cursor on `select`, which also scrolls a long list to it."""
    control = window.getControl(control_id)
    control.reset()
    items = []
    for row in rows:
        item = xbmcgui.ListItem(row.get("t1", ""), offscreen=True)
        for key, value in row.items():
            item.setProperty(key, value)
        items.append(item)
    control.addItems(items)
    if items:
        control.selectItem(max(0, min(select, len(items) - 1)))
