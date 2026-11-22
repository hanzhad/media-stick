"""Network facts for the launcher pill and the phone-remote dialog."""
import os
import re
import subprocess

import xbmc

BACKSLASH = chr(92)
ESCAPED = re.compile(re.escape(BACKSLASH) + "(.)")      # a backslash and the character it protects


def address():
    """The LAN address, or "" (no network, loopback, or the setup hotspot 10.42.*)."""
    ip = xbmc.getIPAddress()
    return ip if ip and not ip.startswith("127.") and not ip.startswith("10.42.") else ""


def _read(path):
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def kind():
    """"ethernet", "wifi" or "" from the interfaces that are up."""
    try:
        up = [n for n in sorted(os.listdir("/sys/class/net"))
              if _read(f"/sys/class/net/{n}/operstate") == "up"]
    except OSError:
        return ""
    if any(n.startswith(("eth", "en")) for n in up):
        return "ethernet"
    return "wifi" if any(n.startswith("wl") for n in up) else ""


def unescape(text):
    """nmcli -t escapes ":" and the backslash itself with a backslash."""
    return ESCAPED.sub(lambda m: m.group(1), text)


def ssid():
    """Name of the connected Wi-Fi network, or ""."""
    try:
        out = subprocess.run(["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi", "list", "--rescan", "no"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
    for line in out.splitlines():
        if line.startswith("yes:"):
            return unescape(line[4:])
    return ""
