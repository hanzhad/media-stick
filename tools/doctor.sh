#!/bin/bash
# One screen of health: is the device up, is Kodi running, is power/heat/disk fine.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
"${SSH[@]}" 'bash -s' <<'R'
ok()   { printf "OK    %s\n" "$*"; }
bad()  { printf "FAIL  %s\n" "$*"; }
chk()  { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
echo "host $(hostname)  up $(uptime -p)  $(cd /opt/media-stick 2>/dev/null && git log -1 --format='%h %s' 2>/dev/null)"
chk "kodi.service active"        "systemctl is-active -q kodi.service"
chk "ssh password login off"     "sudo sshd -T | grep -qx 'passwordauthentication no'"
t=$(vcgencmd get_throttled | cut -d= -f2); [ "$t" = 0x0 ] && ok "power/throttle $t" || bad "power/throttle $t (undervoltage or heat)"
echo "      temp $(vcgencmd measure_temp | cut -d= -f2)  mem $(free -m | awk '/Mem/{print $7" MB free"}')  disk $(df -h / | awk 'NR==2{print $4" free"}')"
chk "internet"                   "curl -sfI --max-time 5 https://github.com"
echo "--- kodi errors (last 10)"
grep -E ' error ' ~media/.kodi/temp/kodi.log 2>/dev/null | tail -10 || echo "(no kodi.log yet)"
echo "--- failed units"; systemctl --failed --no-legend || true
R
