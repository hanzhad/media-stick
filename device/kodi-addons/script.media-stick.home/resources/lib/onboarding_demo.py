"""The onboarding screens without a real flow: invented documents for
`RunScript(script.media-stick.home,onboarding,demo,signin|keys)`, so they can be looked at on the TV. Nothing is
written anywhere, nothing real is touched: the sources here answer the screens in place of the device's files.

The words are the ones the real writers use (the sign-in's are in mediastick_signin_guide, the key wizard's are the
phone page's); the code is made up and the Google steps are only an example of what a wizard may show."""
import time

from resources.lib import store

SCENARIOS = ("signin", "keys")
CODE = "KQX-7MD-P4W"
SIGNIN_LINK = "https://www.youtube.com/activate?user_code=" + CODE
LIVES = 120                 # s a document lives after each look: it never runs out while the demo is up


def signin_doc(now):
    """The real sign-in writer's own document for YouTube, at its second step."""
    doc = store.lib.guide.document("youtube", "active", CODE, SIGNIN_LINK)
    doc.update(v=1, service="youtube", step=2, updated=now, expires=now + LIVES)
    return doc


def keys_doc(now):
    chip = lambda text, state: {"t": text, "s": state}    # noqa: E731
    return {
        "v": 1, "service": "youtube", "flow": "keys", "state": "active",
        "kicker": {"tv": "YouTube · one-time setup", "phone": ""},
        "title": {"tv": "Follow along on your phone", "phone": ""},
        "step": 2,
        "steps": [{"id": "project", "tv": "Project and API", "phone": ""},
                  {"id": "consent", "tv": "Allow TV sign-in", "phone": ""},
                  {"id": "api_key", "tv": "API key", "phone": ""},
                  {"id": "client", "tv": "TV client", "phone": ""}],
        "hint": {"tv": "on the Google page tap", "phone": ""},
        "chips": [[chip("Get started", "done"), chip("App name: TV", "done"), chip("Audience: External", "now"),
                   chip("Create", "todo")],
                  [chip("Audience", "todo"), chip("Publish app", "todo")]],
        "warn": {"tv": "Publish it, or the TV gets signed out after 7 days.", "phone": ""},
        "items": [{"id": "api_key", "label": "API key", "s": "wait"}, {"id": "client_id", "label": "Client ID", "s": "wait"},
                  {"id": "client_secret", "label": "Secret", "s": "wait"}],
        "updated": now, "expires": now + LIVES}


class KeysSource:
    """What the onboarding window reads in the demo: the key wizard's document, always fresh."""

    def read(self, service):
        return keys_doc(int(time.time()))


class SigninSource:
    """What the sign-in window reads in the demo (the same four questions as signin.LibSource): a waiting sign-in that
    ends as cancelled when the window asks to stop it."""

    def __init__(self, qr=""):
        self.cancelled = False
        self.qr = qr

    def read(self, service):
        now = int(time.time())
        state = {"service": service, "state": "cancelled" if self.cancelled else "waiting", "mode": "normal", "step": 1,
                 "steps": 1, "updated": now, "expires": now + LIVES, "left": LIVES, "name": "YouTube"}
        if not self.cancelled:
            state.update(code=CODE, url="https://www.youtube.com/activate", link=SIGNIN_LINK)
        return state

    def onboarding(self, service):
        return None if self.cancelled else signin_doc(int(time.time()))

    def request_cancel(self, service):
        self.cancelled = True

    def asked_partner(self, service):
        return False

    def phone_qr(self):
        return self.qr
