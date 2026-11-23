"""The "Who's watching" picker: a row of cards, one per YouTube profile, plus "Add account"."""
import xbmcgui

from resources.lib import ui

LIST = 500
ADD_ID = "add"
PALETTE = ("FFE5484D", "FF3E8EF7", "FF30A46C", "FFF5A524", "FF8E4EC6", "FF12A594")
SIGNED, UNSIGNED = "Signed in", "Not signed in"
MARK_COLOR = {True: "FF7BD88F", False: "99FFFFFF"}


def initial(name):
    return next((c.upper() for c in name if c.isalnum()), "?")


def color(uid):
    return PALETTE[int(uid) % len(PALETTE)] if str(uid).isdigit() else PALETTE[0]


def cards(profiles):
    """What each card shows, in order: the profiles, then the Add account card."""
    out = [{"id": str(p["id"]), "name": p["name"], "initial": initial(p["name"]), "color": color(p["id"]),
            "mark": SIGNED if p["signed_in"] else UNSIGNED, "markcolor": MARK_COLOR[bool(p["signed_in"])],
            "current": bool(p.get("current"))} for p in profiles]
    out.append({"id": ADD_ID, "name": "Add account", "initial": "+", "color": "40FFFFFF", "mark": "",
                "markcolor": MARK_COLOR[False], "current": False})
    return out


def first_index(card_list):
    """The card to focus: the current profile, else the first."""
    return next((i for i, c in enumerate(card_list) if c["current"]), 0)


class ProfilesDialog(xbmcgui.WindowXMLDialog):
    """Set up with setup() after construction. `choice` is a profile id, ADD_ID, or None (Back)."""

    def setup(self, profiles):
        self.cards = cards(profiles)
        self.choice = None

    def onInit(self):
        items = []
        for card in self.cards:
            item = xbmcgui.ListItem(card["name"], offscreen=True)
            for key in ("id", "initial", "color", "mark", "markcolor"):
                item.setProperty(key, card[key])
            items.append(item)
        control = self.getControl(LIST)
        control.reset()
        control.addItems(items)
        control.selectItem(first_index(self.cards))
        # No setFocusId here: the list is not shown yet (Kodi shows it when onInit returns), so asking only logs
        # "asked to focus, but it can't". The skin's <defaultcontrol always="true"> puts the focus on it.

    def onClick(self, controlId):
        if controlId == LIST:
            item = self.getControl(LIST).getSelectedItem()
            self.choice = item.getProperty("id") if item else None
            self.close()

    def onAction(self, action):
        if action.getId() in ui.BACK_ACTIONS:
            self.close()
        else:
            super().onAction(action)


def pick(profiles):
    """Show the picker; the chosen profile id, ADD_ID, or None when backed out."""
    dialog = ui.load(ProfilesDialog, "script-media-stick-profiles.xml")
    dialog.setup(profiles)
    dialog.doModal()
    choice = dialog.choice
    del dialog
    return choice
