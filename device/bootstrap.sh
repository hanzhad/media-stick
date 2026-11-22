#!/bin/bash
# Bring the device to the state this repository describes. Safe to run again:
# every step checks before it changes. Runs as root on the Pi.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
FILES="$REPO/device/files"
log() { echo "[bootstrap] $*"; }
reboot_needed=0

[ "$(id -u)" = 0 ] || exec sudo -E "$0" "$@"

log "settings"
set -a; . "$REPO/device/config.env"; [ -f /etc/media-stick/local.env ] && . /etc/media-stick/local.env; set +a
install -d -m 0755 /var/lib/media-stick

log "packages"
export DEBIAN_FRONTEND=noninteractive
pkgs=(kodi kodi-inputstream-adaptive kodi-inputstream-ffmpegdirect ffmpeg git jq curl unzip
      chromium libwidevinecdm0 cage wtype grim
      fonts-noto-core fonts-noto-mono fonts-roboto-unhinted)
missing=()
for p in "${pkgs[@]}"; do dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p"); done
if [ ${#missing[@]} -gt 0 ]; then
  apt-get update -q
  apt-get install -y -q --no-install-recommends "${missing[@]}"
fi

log "boot config"
cfg=/boot/firmware/config.txt
# 256 MB of contiguous memory for the video decoder; the default is too small for 1080p in Kodi.
if grep -q '^dtoverlay=vc4-kms-v3d$' "$cfg"; then
  sed -i 's/^dtoverlay=vc4-kms-v3d$/dtoverlay=vc4-kms-v3d,cma-256/' "$cfg"; reboot_needed=1
fi
grep -q 'video=HDMI-A-1:' /boot/firmware/cmdline.txt || {
  sed -i '1s|$| video=HDMI-A-1:1920x1080@60D|' /boot/firmware/cmdline.txt; reboot_needed=1; }

log "secrets dir"
install -d -m 0750 -o root -g media /etc/media-stick
[ -f /etc/media-stick/secrets.env ] || install -m 0640 -o root -g media /dev/null /etc/media-stick/secrets.env

log "files"
# Everything under device/files goes to the same path on the device.
changed_units=()
while IFS= read -r -d '' src; do
  rel=${src#"$FILES"/}; dst=/$rel; mode=0644
  [[ $rel == usr/local/bin/* ]] && mode=0755
  if ! cmp -s "$src" "$dst"; then
    install -D -m "$mode" "$src" "$dst"; log "  updated /$rel"
    [[ $rel == etc/systemd/system/* ]] && changed_units+=("$(basename "$rel")")
    # a program with a service of the same name: restart that service too
    [[ $rel == usr/local/bin/* && -f "$FILES/etc/systemd/system/$(basename "$rel").service" ]] \
      && changed_units+=("$(basename "$rel").service")
  fi
done < <(find "$FILES" -type f -print0)
systemd-tmpfiles --create /etc/tmpfiles.d/media-stick.conf

log "services"
if [ ${#changed_units[@]} -gt 0 ]; then systemctl daemon-reload; fi
systemctl disable --now getty@tty1.service 2>/dev/null || true
nmcli radio wifi on 2>/dev/null || true
# Retired pieces: gone from the repository, so remove them from the device too.
for old in screen-view; do
  if [ -e /etc/systemd/system/$old.service ]; then
    systemctl disable --now $old.service 2>/dev/null || true
    rm -f /etc/systemd/system/$old.service /usr/local/bin/$old; systemctl daemon-reload
    log "  removed $old"
  fi
done
for unit in kodi.service panel.service wifi-fallback.service media-stick-update.timer; do
  systemctl enable -q "$unit"
done

# Self-update schedule from UPDATE_SCHEDULE.
dropin=/etc/systemd/system/media-stick-update.timer.d/schedule.conf
want=$(printf '[Timer]\nOnCalendar=\nOnCalendar=%s\n' "$UPDATE_SCHEDULE")
if [ "$(cat "$dropin" 2>/dev/null)" != "$want" ] || [[ " ${changed_units[*]-} " == *" media-stick-update.timer "* ]]; then
  install -d "$(dirname "$dropin")"; printf '%s\n' "$want" > "$dropin"
  systemctl daemon-reload; systemctl restart media-stick-update.timer
  log "  update schedule: $UPDATE_SCHEDULE"
fi
systemctl is-active -q media-stick-update.timer || systemctl start media-stick-update.timer
for unit in kodi.service panel.service; do
  # Kodi is stopped on purpose while a web app has the screen.
  [ $unit = kodi.service ] && systemctl is-active -q 'web-app@*' && continue
  if [[ " ${changed_units[*]-} " == *" $unit "* ]] || ! systemctl is-active -q "$unit"; then
    systemctl restart "$unit"
  fi
done

log "kodi settings and add-ons"
wait_kodi() { for i in $(seq 1 30); do kodi-rpc JSONRPC.Ping 2>/dev/null | grep -q pong && return 0; sleep 2; done; return 1; }
wait_kodi || log "  kodi is not answering"
# Settings are written into guisettings.xml and add-ons unpacked with Kodi stopped,
# not done over RPC: switching some settings over RPC puts a confirmation dialog on
# the TV and hangs the call, and an add-on dropped in while Kodi runs comes up disabled.
#  - look: Fire TV-style skin, Bing photos as the screensaver after 5 idle minutes
#  - casting: UPnP/DLNA renderer ("Cast to device", BubbleUPnP), AirPlay over zeroconf
#  - Kodi's web server on :8080 for the Kodi phone apps (Kore, Official Kodi Remote,
#    Yatse), always behind a password made on the device once and kept in
#    secrets.env; read it with: sudo grep KODI_WEB /etc/media-stick/secrets.env
#  - screenshots to tmpfs for the page and tools/screenshot.sh
# Add-ons: device/kodi-addons.list (from tools/kodi-addons-lock.py) and device/kodi-addons/.
SECRETS=/etc/media-stick/secrets.env
grep -q '^KODI_WEB_PASSWORD=.' "$SECRETS" \
  || echo "KODI_WEB_PASSWORD=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" >> "$SECRETS"
web_pass=$(sed -n 's/^KODI_WEB_PASSWORD=//p' "$SECRETS" | tail -1)
on_settings=(services.zeroconf services.upnp services.upnprenderer services.airplay
  services.webserver services.webserverauthentication)
kodi_wanted=("${on_settings[@]/%/=true}" services.webserverusername=kodi "services.webserverpassword=$web_pass"
  lookandfeel.skin=skin.ftv screensaver.mode=screensaver.bing screensaver.time=5 input.enablemouse=false
  lookandfeel.startupwindow=10060
  debug.screenshotpath=/run/media-stick/shots/)
as_media() { setpriv --reuid=media --regid=media --init-groups "$@"; }
FAVS="$REPO/device/kodi-favourites.xml"
addons_ok=1; kodi-addons --check "$REPO" || addons_ok=0
settings_ok=1; kodi-settings --check "${kodi_wanted[@]}" || settings_ok=0
favs_ok=1; kodi-favourites --check "$FAVS" || favs_ok=0
if [ $addons_ok = 0 ] || [ $settings_ok = 0 ] || [ $favs_ok = 0 ]; then
  systemctl stop kodi
  [ $addons_ok = 1 ] || kodi-addons --install "$REPO"
  [ $settings_ok = 1 ] || log "  kodi settings changed: $(as_media kodi-settings "${kodi_wanted[@]}")"
  [ $favs_ok = 1 ] || log "  home tiles changed: $(as_media kodi-favourites --apply "$FAVS")"
  systemctl start kodi
  wait_kodi || log "  kodi did not come back"
fi
# First install on a fresh card: Kodi had no add-on database yet, so enable over RPC.
addon_ids=(inputstream.adaptive inputstream.ffmpegdirect $(awk '!/^#/ && NF==4 {print $1}' "$REPO/device/kodi-addons.list"))
for d in "$REPO"/device/kodi-addons/*/; do addon_ids+=("$(basename "$d")"); done
for id in "${addon_ids[@]}"; do
  kodi-rpc Addons.GetAddonDetails "{\"addonid\":\"$id\",\"properties\":[\"enabled\"]}" 2>/dev/null | grep -q '"enabled":true' && continue
  kodi-rpc Addons.SetAddonEnabled "{\"addonid\":\"$id\",\"enabled\":true}" >/dev/null || log "  could not enable $id"
done
# Kodi drops a setting its build does not support; say so instead of retrying forever.
for s in "${on_settings[@]}"; do
  kodi-rpc Settings.GetSettingValue "{\"setting\":\"$s\"}" | grep -q '"value":true' || log "  kodi has $s off"
done
kodi-rpc Settings.GetSettingValue '{"setting":"lookandfeel.skin"}' | grep -q skin.ftv || log "  kodi is not on skin.ftv"

chown -R media:media "$REPO"
log "done"
[ $reboot_needed = 1 ] && log "REBOOT NEEDED for boot config" || true
