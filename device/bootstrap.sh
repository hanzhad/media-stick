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
pkgs=(kodi kodi-inputstream-adaptive kodi-inputstream-ffmpegdirect ffmpeg git jq curl
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
  if [[ " ${changed_units[*]-} " == *" $unit "* ]] || ! systemctl is-active -q "$unit"; then
    systemctl restart "$unit"
  fi
done

log "kodi settings"
for i in $(seq 1 30); do kodi-rpc JSONRPC.Ping | grep -q pong && break; sleep 2; done
kodi-rpc Settings.SetSettingValue '{"setting":"debug.screenshotpath","value":"/run/media-stick/shots/"}' >/dev/null
for a in inputstream.adaptive inputstream.ffmpegdirect; do
  kodi-rpc Addons.GetAddonDetails "{\"addonid\":\"$a\",\"properties\":[\"enabled\"]}" | grep -q '"enabled":true' \
    || { kodi-rpc Addons.SetAddonEnabled "{\"addonid\":\"$a\",\"enabled\":true}" >/dev/null; kodi-rpc Input.Back >/dev/null; }
done

chown -R media:media "$REPO"
log "done"
[ $reboot_needed = 1 ] && log "REBOOT NEEDED for boot config" || true
