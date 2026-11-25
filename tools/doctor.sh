#!/bin/bash
# One screen of health: is the device up, is Kodi running, is power/heat/disk fine.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
lease_note
"${SSH[@]}" 'bash -s' <<'R'
ok()   { printf "OK    %s\n" "$*"; }
bad()  { printf "FAIL  %s\n" "$*"; }
warn() { printf "WARN  %s\n" "$*"; }
chk()  { if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
echo "host $(hostname)  up $(uptime -p)  $(cd /opt/media-stick 2>/dev/null && git log -1 --format='%h %s' 2>/dev/null)"
chk "mediastick-displayd.service active" "systemctl is-active -q mediastick-displayd.service"
chk "kodi.service active"        "systemctl is-active -q kodi.service"
chk "ssh password login off"     "sudo sshd -T | grep -qx 'passwordauthentication no'"
t=$(vcgencmd get_throttled | cut -d= -f2); [ "$t" = 0x0 ] && ok "power/throttle $t" || bad "power/throttle $t (undervoltage or heat)"
echo "      temp $(vcgencmd measure_temp | cut -d= -f2)  mem $(free -m | awk '/Mem/{print $7" MB free"}')  disk $(df -h / | awk 'NR==2{print $4" free"}')"
if grep -q zram0 /proc/swaps 2>/dev/null; then
  ok "zram0 swap active"
else
  warn "zram0 swap inactive"
fi
chk "launcher add-on enabled"    "kodi-rpc Addons.GetAddonDetails '{\"addonid\":\"script.media-stick.home\",\"properties\":[\"enabled\"]}' | grep -q '\"enabled\":true'"
chk "skin.media-stick active"    "kodi-rpc Settings.GetSettingValue '{\"setting\":\"lookandfeel.skin\"}' | grep -q skin.media-stick"
chk "python3-evdev installed"    'python3 -c "import evdev"'
chk "/dev/uinput group input 0660" 'test "$(stat -c %G%a /dev/uinput)" = input660'
chk "media-stick-healthcheck executable" "test -x /usr/local/bin/media-stick-healthcheck"
chk "panel /manifest.webmanifest HTTP 200" "curl -s --max-time 3 -o /dev/null -w '%{http_code}' http://127.0.0.1/manifest.webmanifest | grep -qx 200"
chk "sign-in state dir"          "test -d /run/media-stick/signin"
# Files kept in device/skin-overlay/<addon>/ must be what the installed add-on really has.
ov=/opt/media-stick/device/skin-overlay
while IFS= read -r f; do
  [ -d "/home/media/.kodi/addons/${f%%/*}" ] || continue
  chk "overlay in place: ${f%%/*} ${f##*/}" "cmp -s '$ov/$f' '/home/media/.kodi/addons/$f'"
done < <(cd "$ov" 2>/dev/null && find . -type f | sed 's|^\./||')
echo "      wallpapers cached $(ls /var/cache/media-stick/wallpapers/*.jpg 2>/dev/null | wc -l)"
if [ -s /var/lib/media-stick/panel-url ]; then
  end=$(openssl x509 -noout -enddate -in /etc/media-stick/tls/fullchain.pem 2>/dev/null | cut -d= -f2)
  if [ -z "$end" ]; then bad "https: certificate unreadable ($(cat /var/lib/media-stick/panel-url))"
  else
    days=$(( ( $(date -d "$end" +%s) - $(date +%s) ) / 86400 ))
    msg="https certificate: $days days left ($(cat /var/lib/media-stick/panel-url))"
    if [ "$days" -lt 7 ]; then bad "$msg"; elif [ "$days" -lt 20 ]; then warn "$msg"; else ok "$msg"; fi
  fi
else
  echo "      https not configured"
fi
chk "internet"                   "curl -sfI --max-time 5 https://github.com"
echo "      next update $(systemctl list-timers media-stick-update.timer --no-legend | awk '{print $1, $2, $3}')"
[ -f /var/lib/media-stick/bad-commit ] && bad "last update rolled back: $(cut -c1-7 /var/lib/media-stick/bad-commit)"
echo "--- last updates"; sudo journalctl -u media-stick-update -n 4 --no-pager -o cat 2>/dev/null | grep -vE '^\[bootstrap\]' || true
echo "--- kodi errors (last 10)"
grep -E ' error ' ~media/.kodi/temp/kodi.log 2>/dev/null | tail -10 || echo "(no kodi.log yet)"
echo "--- failed units"; systemctl --failed --no-legend || true
R
