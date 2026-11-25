"""Zero-fork system telemetry and cached status collector for the panel.

Pure Core:
  - parse_meminfo_mb, format_uptime, parse_thermal_temp, parse_fib_trie_ips
  - parse_throttled, parse_nmcli_dev, sd_minutes, screen_owner_from_flags

Thin I/O Shell:
  - StateHub: reads /proc & /sys directly, caches git commit at startup, vcgencmd (60s),
    nmcli (15s), and systemd timer metadata (60s), keeping /api/status JSON shape intact.
"""
import os
import re
import subprocess
import threading
import time

DEFAULT_MEMINFO = "/proc/meminfo"
DEFAULT_UPTIME = "/proc/uptime"
DEFAULT_THERMAL = "/sys/class/thermal/thermal_zone0/temp"
DEFAULT_FIB_TRIE = "/proc/net/fib_trie"
DEFAULT_SCREEN_DIR = "/run/media-stick"
DEFAULT_REPO = "/opt/media-stick"
DEFAULT_STATE_DIR = "/var/lib/media-stick"

WIFI_TTL = 15.0
THROTTLED_TTL = 60.0
SYSTEMD_TTL = 60.0
DISPLAY_TTL = 2.0

DEFAULT_ACTIONS = frozenset({
    "up", "down", "left", "right", "select", "back", "contextmenu", "info",
    "playpause", "stop", "volumeup", "volumedown", "mute", "fastforward",
    "rewind", "osd", "skipnext", "skipprevious", "fullscreen",
})
DEFAULT_WEB_KEYS = frozenset({
    "up", "down", "left", "right", "select", "back", "playpause",
    "fastforward", "rewind", "fullscreen", "mute",
})


# --- Pure Core ------------------------------------------------------------------------------------


def parse_meminfo_mb(raw: str) -> int:
    """Extract MemAvailable in MiB from /proc/meminfo contents."""
    for line in raw.splitlines():
        if line.startswith("MemAvailable:"):
            parts = line.split(":", 1)[1].strip().split()
            if parts:
                try:
                    return int(parts[0]) // 1024
                except ValueError:
                    return 0
    return 0


def format_uptime(raw: str) -> str:
    """Format /proc/uptime seconds into `uptime -p` style (without 'up ')."""
    try:
        secs = float(raw.strip().split()[0])
    except (ValueError, IndexError):
        return ""
    total_mins = max(0, int(secs // 60))
    if total_mins == 0:
        return "0 minutes"
    weeks, rem = divmod(total_mins, 10080)
    days, rem = divmod(rem, 1440)
    hours, mins = divmod(rem, 60)
    parts = []
    for count, unit in ((weeks, "week"), (days, "day"), (hours, "hour"), (mins, "minute")):
        if count:
            parts.append(f"{count} {unit}" + ("" if count == 1 else "s"))
    return ", ".join(parts)


def parse_thermal_temp(raw: str) -> str:
    """Format millidegree sysfs thermal value (e.g. '48500') as '48.5°C'."""
    s = raw.strip()
    if not s:
        return ""
    try:
        milli = float(s)
    except ValueError:
        return ""
    return f"{milli / 1000.0:.1f}°C"


def parse_fib_trie_ips(raw: str) -> list[str]:
    """Extract unique non-loopback local IPv4 addresses from /proc/net/fib_trie."""
    ips: list[str] = []
    seen: set[str] = set()
    prev_ip = None
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith("|-- "):
            cand = stripped[4:].strip()
            if re.match(r"^\d{1,3}(\.\d{1,3}){3}$", cand):
                prev_ip = cand
            else:
                prev_ip = None
        elif "/32 host LOCAL" in stripped and prev_ip:
            if not prev_ip.startswith("127.") and prev_ip not in seen:
                seen.add(prev_ip)
                ips.append(prev_ip)
            prev_ip = None
    return ips


def parse_throttled(raw: str) -> tuple[str, bool]:
    """Parse `vcgencmd get_throttled` output into (hex_str, power_ok)."""
    val = (raw or "").split("=")[-1].strip()
    return val, val == "0x0"


def parse_nmcli_dev(out: str) -> tuple[str, bool]:
    """Extract active wlan0 connection name and AP mode flag from `nmcli -t dev` output."""
    for line in (out or "").splitlines():
        if line.startswith("wlan0:"):
            parts = line.split(":", 2)
            con = parts[2] if len(parts) > 2 else ""
            return con, con == "ms-setup"
    return "", False


def sd_minutes(ts: str | None, now: float | None = None) -> int | None:
    """Whole minutes from `now` to a systemd timestamp; negative = past, None = unset."""
    m = re.search(r"(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)", ts or "")
    if not m:
        return None
    target = time.mktime(tuple(int(x) for x in m.groups()) + (0, 0, -1))
    ref = time.time() if now is None else now
    return int((target - ref) // 60)


def screen_owner_from_flags(screen_dir: str, display_state: str = "") -> str:
    """Determine active screen owner from flag files and optional displayd state."""
    if screen_dir:
        for name in ("miracast", "airplay", "web-app"):
            if os.path.exists(os.path.join(screen_dir, name)):
                return name
    mapping = {
        "CAST_MIRACAST": "miracast",
        "CAST_AIRPLAY": "airplay",
        "WEB_APP": "web-app",
    }
    return mapping.get(display_state or "", "")


# --- Thin I/O Shell -------------------------------------------------------------------------------


def _default_run(cmd, stdin=None, timeout=20):
    try:
        p = subprocess.run(cmd, input=stdin, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout.strip()
    except (subprocess.TimeoutExpired, OSError):
        return 124, ""


def _read_text(path: str, default: str = "") -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return default


class StateHub:
    """Zero-fork /proc & /sys telemetry collector with TTL-cached slow queries."""

    def __init__(
        self,
        proc_meminfo: str = DEFAULT_MEMINFO,
        proc_uptime: str = DEFAULT_UPTIME,
        thermal_temp: str = DEFAULT_THERMAL,
        proc_fib_trie: str = DEFAULT_FIB_TRIE,
        screen_dir: str | None = None,
        repo: str = DEFAULT_REPO,
        state_dir: str = DEFAULT_STATE_DIR,
        disk_path: str = "/",
        display_sock: str | None = None,
        run_cmd=None,
        kodi_call=None,
        now_fn=None,
        lang_fn=None,
        page_ver: str = "",
        item_title_fn=None,
        kb_state_fn=None,
        web_app_on_fn=None,
        onboarding_fn=None,
        screen_owner_fn=None,
        actions=None,
        web_keys=None,
        wifi_ttl: float = WIFI_TTL,
        throttled_ttl: float = THROTTLED_TTL,
        systemd_ttl: float = SYSTEMD_TTL,
    ):
        self.proc_meminfo = proc_meminfo
        self.proc_uptime = proc_uptime
        self.thermal_temp = thermal_temp
        self.proc_fib_trie = proc_fib_trie
        self.screen_dir = screen_dir
        self.repo = repo
        self.state_dir = state_dir
        self.disk_path = disk_path
        self.display_sock = display_sock
        self.run_cmd = run_cmd or _default_run
        self.kodi_call = kodi_call
        self.now_fn = now_fn or time.time
        self.lang_fn = lang_fn or (lambda: "")
        self.page_ver = page_ver
        self.item_title_fn = item_title_fn or (lambda item: (item or {}).get("title") or (item or {}).get("label") or "")
        self.kb_state_fn = kb_state_fn
        self.web_app_on_fn = web_app_on_fn
        self.onboarding_fn = onboarding_fn or (lambda: [])
        self.screen_owner_fn = screen_owner_fn
        self.actions = frozenset(actions) if actions is not None else DEFAULT_ACTIONS
        self.web_keys = frozenset(web_keys) if web_keys is not None else DEFAULT_WEB_KEYS

        self.wifi_ttl = wifi_ttl
        self.throttled_ttl = throttled_ttl
        self.systemd_ttl = systemd_ttl

        self._lock = threading.Lock()
        self._commit_loaded = False
        self._commit = ""
        self._commit_date = ""

        self._wifi_at: float | None = None
        self._wifi_val: dict = {"online": False, "ap": False, "ssid": ""}

        self._throttled_at: float | None = None
        self._throttled_val: tuple[str, bool] = ("", False)

        self._systemd_at: float | None = None
        self._systemd_val: tuple[str, str] = ("", "")

        self._display_at: float | None = None
        self._display_state: str = ""

    def _effective_screen_dir(self) -> str:
        if self.screen_dir is not None:
            return self.screen_dir
        return os.environ.get("MEDIASTICK_SCREEN_DIR", DEFAULT_SCREEN_DIR)

    def cached_wifi(self) -> dict:
        """Return the last known Wi-Fi dict without forking nmcli."""
        with self._lock:
            return dict(self._wifi_val)

    def _get_commit(self) -> tuple[str, str]:
        with self._lock:
            if self._commit_loaded:
                return self._commit, self._commit_date
        _, cm = self.run_cmd(["git", "-C", self.repo, "log", "-1", "--format=%h %s"])
        _, dt = self.run_cmd(["git", "-C", self.repo, "log", "-1", "--format=%cs"])
        with self._lock:
            self._commit = cm
            self._commit_date = dt
            self._commit_loaded = True
            return self._commit, self._commit_date

    def _get_throttled(self, now: float) -> tuple[str, bool]:
        with self._lock:
            if self._throttled_at is not None and (now - self._throttled_at) < self.throttled_ttl:
                return self._throttled_val
        _, out = self.run_cmd(["vcgencmd", "get_throttled"])
        val = parse_throttled(out)
        with self._lock:
            self._throttled_at = now
            self._throttled_val = val
        return val

    def wifi_status(self, force: bool = False) -> dict:
        """Read Wi-Fi status via nmcli, cached for `wifi_ttl` seconds."""
        now = self.now_fn()
        with self._lock:
            if not force and self._wifi_at is not None and (now - self._wifi_at) < self.wifi_ttl:
                return dict(self._wifi_val)
        _, out = self.run_cmd(["nmcli", "-t", "-f", "DEVICE,STATE,CONNECTION", "dev"])
        con, ap = parse_nmcli_dev(out)
        ssid = ""
        if con and not ap:
            _, ssid = self.run_cmd(["nmcli", "-g", "802-11-wireless.ssid", "con", "show", con])
        _, conn_out = self.run_cmd(["nmcli", "-t", "networking", "connectivity"])
        val = {"online": conn_out == "full", "ap": ap, "ssid": ssid}
        with self._lock:
            self._wifi_at = now
            self._wifi_val = val
        return dict(val)

    def _get_systemd_timers(self, now: float, force: bool = False) -> tuple[str, str]:
        with self._lock:
            if not force and self._systemd_at is not None and (now - self._systemd_at) < self.systemd_ttl:
                return self._systemd_val
        _, nxt = self.run_cmd([
            "systemctl", "show", "media-stick-update.timer",
            "-p", "NextElapseUSecRealtime", "--value",
        ])
        _, last = self.run_cmd([
            "systemctl", "show", "media-stick-update.service",
            "-p", "ExecMainExitTimestamp", "--value",
        ])
        with self._lock:
            self._systemd_at = now
            self._systemd_val = (nxt, last)
        return nxt, last

    def _get_display_state(self, now: float) -> str:
        sock_path = self.display_sock
        if not sock_path:
            sock_path = os.environ.get("DISPLAYD_SOCK", "/run/media-stick/display.sock")
        if not os.path.exists(sock_path):
            return ""
        with self._lock:
            if self._display_at is not None and (now - self._display_at) < DISPLAY_TTL:
                return self._display_state
        state = ""
        try:
            from mediastick_display import DisplayClient
            with DisplayClient(sock_path=sock_path, timeout=1.0) as dc:
                resp = dc.status()
                state = str(resp.get("state") or "")
        except Exception:
            state = ""
        with self._lock:
            self._display_at = now
            self._display_state = state
        return state

    def screen_owner(self, now: float | None = None) -> str:
        now = self.now_fn() if now is None else now
        sdir = self._effective_screen_dir()
        owner = screen_owner_from_flags(sdir)
        if owner:
            return owner
        dstate = self._get_display_state(now)
        owner = screen_owner_from_flags("", dstate)
        if owner:
            return owner
        if self.screen_owner_fn is not None:
            try:
                return self.screen_owner_fn() or ""
            except Exception:
                return ""
        return ""

    def collect(self, refresh_timers: bool = False) -> dict:
        """Collect complete `/api/status` dictionary without unnecessary process forks."""
        now = self.now_fn()
        s: dict = {"time": time.strftime("%H:%M", time.localtime(now))}
        s["wifi"] = self.wifi_status()
        s["uptime"] = format_uptime(_read_text(self.proc_uptime))
        s["temp"] = parse_thermal_temp(_read_text(self.thermal_temp))

        throttled, power_ok = self._get_throttled(now)
        s["throttled"] = throttled
        s["power_ok"] = power_ok

        s["mem_free_mb"] = parse_meminfo_mb(_read_text(self.proc_meminfo))
        try:
            st = os.statvfs(self.disk_path)
            s["disk_free_gb"] = round(st.f_bavail * st.f_frsize / 1e9, 1)
        except OSError:
            s["disk_free_gb"] = 0.0

        s["ip"] = parse_fib_trie_ips(_read_text(self.proc_fib_trie))
        s["https_url"] = _read_text(os.path.join(self.state_dir, "panel-url"))
        s["page"] = self.page_ver
        try:
            s["lang"] = self.lang_fn()
        except Exception:
            s["lang"] = ""

        commit, commit_date = self._get_commit()
        s["commit"] = commit
        s["commit_date"] = commit_date
        s["bad_commit"] = _read_text(os.path.join(self.state_dir, "bad-commit"))[:7]

        nxt, last = self._get_systemd_timers(now, force=refresh_timers)
        s["next_update"] = nxt
        s["next_update_min"] = sd_minutes(nxt, now)
        s["last_check"] = last
        last_sd = sd_minutes(last, now)
        s["last_check_min"] = None if last_sd is None else -last_sd

        s["playing"] = ""
        s["kb"] = None
        players = []
        if self.kodi_call is not None:
            try:
                players = self.kodi_call("Player.GetActivePlayers", None) or []
                s["kodi"] = "up"
                if players:
                    item = self.kodi_call(
                        "Player.GetItem",
                        {"playerid": players[0]["playerid"], "properties": ["title", "showtitle", "file"]},
                    ) or {}
                    s["playing"] = self.item_title_fn(item.get("item", {}))
                if self.kb_state_fn is not None:
                    s["kb"] = self.kb_state_fn()
            except OSError:
                s["kodi"] = "down"
        else:
            s["kodi"] = "down"

        screen = self.screen_owner(now)
        web_on = screen == "web-app"
        if not web_on and self.web_app_on_fn is not None:
            try:
                web_on = bool(self.web_app_on_fn())
            except Exception:
                web_on = False

        if web_on:
            s["dead"] = sorted(self.actions - self.web_keys - {"home"})
        elif not players:
            s["dead"] = ["fastforward", "osd", "playpause", "rewind", "stop"]
        else:
            s["dead"] = []

        s["screen"] = screen
        try:
            s["onboarding"] = self.onboarding_fn()
        except Exception:
            s["onboarding"] = []
        return s
