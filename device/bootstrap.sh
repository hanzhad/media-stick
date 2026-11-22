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
# A subdomain proposed for DuckDNS (the panel's HTTPS card and the TV dialog show it). Made
# once per device and never changed; world-readable, it is only a name.
if [ ! -s /var/lib/media-stick/https-suggest ]; then
  suffix=$(head -c 8 /dev/urandom | base32 | tr '[:upper:]' '[:lower:]' | tr -dc 'a-z2-7')
  printf 'mediastick-%s\n' "${suffix:0:5}" > /var/lib/media-stick/https-suggest
  chmod 0644 /var/lib/media-stick/https-suggest
fi

log "packages"
export DEBIAN_FRONTEND=noninteractive
pkgs=(kodi kodi-inputstream-adaptive kodi-inputstream-ffmpegdirect ffmpeg git jq curl unzip
      chromium libwidevinecdm0 cage wtype grim qrencode
      fonts-noto-core fonts-noto-mono fonts-roboto-unhinted
      python3-evdev lego)
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

log "uinput"
# The panel makes a virtual mouse through /dev/uinput (tap on the picture of the TV).
# modules-load.d loads the module at boot; load it now if this boot has not yet. The udev
# rule makes the node group input, mode 0660 (the panel runs as media, in group input).
[ -e /dev/uinput ] || modprobe uinput 2>/dev/null || log "  uinput module is not available"
if [ -e /dev/uinput ] && [ "$(stat -c '%G %a' /dev/uinput)" != "input 660" ]; then
  udevadm control --reload
  udevadm trigger --action=add --subsystem-match=misc --sysname-match=uinput
  udevadm settle --timeout=10 || true
  log "  /dev/uinput is $(stat -c '%G %a' /dev/uinput)"
fi

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
# The favourites home is replaced by the launcher add-on.
for old in /usr/local/bin/kodi-favourites /home/media/.kodi/media/web-apps; do
  if [ -e "$old" ]; then rm -rf "$old"; log "  removed $old"; fi
done
# HTTPS: media-stick-cert.timer runs the service daily and a minute after boot. Bootstrap
# never issues a certificate itself, and the service does nothing until DUCKDNS_DOMAIN and
# DUCKDNS_TOKEN are in secrets.env (the panel's HTTPS card writes them).
for unit in kodi.service panel.service wifi-fallback.service media-stick-update.timer media-stick-wallpapers.timer media-stick-cert.timer; do
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
systemctl is-active -q media-stick-wallpapers.timer || systemctl start media-stick-wallpapers.timer
systemctl is-active -q media-stick-cert.timer || systemctl start media-stick-cert.timer
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
#  - the mouse on: the page's tap-on-picture is a virtual mouse (panel, /dev/uinput); its
#    pointer is the dot from device/skin-overlay, since the skin's own is a warning badge
# Add-ons: device/kodi-addons.list (from tools/kodi-addons-lock.py) and device/kodi-addons/.
SECRETS=/etc/media-stick/secrets.env
grep -q '^KODI_WEB_PASSWORD=.' "$SECRETS" \
  || echo "KODI_WEB_PASSWORD=$(head -c 18 /dev/urandom | base64 | tr -dc 'A-Za-z0-9')" >> "$SECRETS"
web_pass=$(sed -n 's/^KODI_WEB_PASSWORD=//p' "$SECRETS" | tail -1)
on_settings=(services.zeroconf services.upnp services.upnprenderer services.airplay
  services.webserver services.webserverauthentication)
kodi_wanted=("${on_settings[@]/%/=true}" services.webserverusername=kodi "services.webserverpassword=$web_pass"
  lookandfeel.skin=skin.ftv screensaver.mode=screensaver.bing screensaver.time=5
  lookandfeel.startupwindow=10000 input.enablemouse=true
  # 1080p60 explicitly; left alone Kodi picks the 1024x768 "DESKTOP" mode on the TV
  videoscreen.screenmode=0192001080060.00000pstd
  debug.screenshotpath=/run/media-stick/shots/)
as_media() { setpriv --reuid=media --regid=media --init-groups "$@"; }
# Files kept in device/skin-overlay/<addon>/ are copied over the installed add-on of that
# name, after any (re)install, since an install replaces the whole folder. Kodi stopped.
OVERLAY="$REPO/device/skin-overlay"
overlay_ok() {
  local f rel
  while IFS= read -r -d '' f; do
    rel=${f#"$OVERLAY"/}
    [ -d "/home/media/.kodi/addons/${rel%%/*}" ] || continue  # not installed: the install applies it
    cmp -s "$f" "/home/media/.kodi/addons/$rel" || return 1
  done < <(find "$OVERLAY" -type f -print0)
}
overlay_apply() {
  local f rel
  while IFS= read -r -d '' f; do
    rel=${f#"$OVERLAY"/}
    [ -d "/home/media/.kodi/addons/${rel%%/*}" ] || continue
    install -D -o media -g media -m 0644 "$f" "/home/media/.kodi/addons/$rel"
  done < <(find "$OVERLAY" -type f -print0)
}
# Retired add-ons: gone from device/kodi-addons/, so remove them from the device (Kodi stopped).
retired_addons=(service.media-stick.qr)
addons_ok=1; kodi-addons --check "$REPO" || addons_ok=0
settings_ok=1; kodi-settings --check "${kodi_wanted[@]}" || settings_ok=0
overlay_fresh=1; overlay_ok || overlay_fresh=0
retired_ok=1
for old in "${retired_addons[@]}"; do
  if [ -e "/home/media/.kodi/addons/$old" ]; then retired_ok=0; fi
done
if [ $addons_ok = 0 ] || [ $settings_ok = 0 ] || [ $retired_ok = 0 ] || [ $overlay_fresh = 0 ]; then
  systemctl stop kodi
  [ $addons_ok = 1 ] || kodi-addons --install "$REPO"
  overlay_apply; [ $overlay_fresh = 1 ] || log "  skin overlay applied"
  [ $settings_ok = 1 ] || log "  kodi settings changed: $(as_media kodi-settings "${kodi_wanted[@]}")"
  for old in "${retired_addons[@]}"; do
    if [ -e "/home/media/.kodi/addons/$old" ]; then rm -rf "/home/media/.kodi/addons/$old"; log "  removed kodi add-on $old"; fi
  done
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
