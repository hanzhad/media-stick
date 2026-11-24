"""SWEET.TV app: search response rows turned into Cards (via sweettv_sections.search_card)."""
from resources.lib import sweettv_sections as sections


def build_cards(rows, resume_doc=None, favs=()) -> list:
    return [sections.search_card(r, resume_doc, favs) for r in (rows or ())]
