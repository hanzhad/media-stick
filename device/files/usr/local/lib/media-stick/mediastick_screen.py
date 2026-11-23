"""Who has the TV screen when Kodi does not answer, said in words for the phone page.

A cast (Win+K / Miracast, AirPlay) or a web app stops Kodi while it has the screen, so the panel's
"Kodi не отвечает" is then wrong: the TV is busy, not broken. kodi_down() names what has it.

  /run/media-stick/miracast   exists while a Win+K cast has the screen
  /run/media-stick/airplay    exists while AirPlay has the screen (see /usr/local/bin/airplay)
  web-app@*.service           active while a web app has the screen

Standard library only, nothing happens on import. MEDIASTICK_SCREEN_DIR moves the flag directory
(for tests).
"""
import os
import subprocess

KODI_DOWN = "ТВ не отвечает. Подождите минуту и попробуйте снова."
MIRACAST = "Телевизор сейчас показывает экран компьютера (Win+K). Закончите трансляцию и попробуйте снова."
AIRPLAY = "Телевизор сейчас показывает экран iPhone или Mac (AirPlay). Закончите трансляцию и попробуйте снова."
WEB_APP = "На телевизоре открыто приложение не из Kodi. Закройте его и попробуйте снова."


def _flag(name):
    return os.path.exists(os.path.join(os.environ.get("MEDIASTICK_SCREEN_DIR", "/run/media-stick"), name))


def _web_app():
    try:
        return subprocess.run(["systemctl", "is-active", "-q", "web-app@*"], timeout=2,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def owner():
    """"miracast", "airplay", "web-app" or "" (Kodi's, or nobody's)."""
    if _flag("miracast"):
        return "miracast"
    if _flag("airplay"):
        return "airplay"
    return "web-app" if _web_app() else ""


def kodi_down():
    """What to tell the phone when Kodi does not answer."""
    try:
        who = owner()
    except Exception:
        who = ""
    return {"miracast": MIRACAST, "airplay": AIRPLAY, "web-app": WEB_APP}.get(who, KODI_DOWN)
