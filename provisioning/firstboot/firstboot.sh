#!/bin/bash
# First boot of a fresh card. Copied to /boot/firmware/media-stick/ by prepare-bootfs.sh
# and started once by cloud-init. Gets the device online (cable, saved Wi-Fi, or the
# setup hotspot), then clones the repository and hands over to device/bootstrap.sh.
set -u
DIR=$(cd "$(dirname "$0")" && pwd)
REPO_URL=https://github.com/hanzhad/media-stick
DEST=/opt/media-stick
exec >>/var/log/media-stick-firstboot.log 2>&1
echo "=== firstboot $(date)"

tv() {  # big text on the TV console
  setfont -C /dev/tty1 /usr/share/consolefonts/Uni2-Terminus32x16.psf.gz 2>/dev/null
  { printf '\033[2J\033[H\n  Media Stick\n\n'; printf '  %s\n' "$@"; } >/dev/tty1 2>/dev/null
}

systemctl stop getty@tty1.service 2>/dev/null
nmcli radio wifi on

# Wait only for a connection that has something to wait for.
wait=0
if [ "$(cat /sys/class/net/eth0/carrier 2>/dev/null)" = 1 ]; then wait=20
elif nmcli -t -f TYPE con show | grep -q 802-11-wireless; then wait=30; fi
tv "Подключаюсь к сети…"
python3 "$DIR/wifi-setup" --if-offline --wait "$wait"

tv "Сеть есть. Устанавливаю систему, это 10-15 минут." "Не выключайте питание."
for i in $(seq 1 30); do
  apt-get update -q && apt-get install -y -q git && break
  sleep 10
done
for i in $(seq 1 60); do
  [ -d "$DEST/.git" ] || git clone -q "$REPO_URL" "$DEST"
  [ -d "$DEST/.git" ] && break
  tv "Не могу скачать $REPO_URL, повторяю…"; sleep 10
done
if "$DEST/device/bootstrap.sh"; then
  echo "bootstrap ok"
else
  tv "Установка не удалась." "Журнал: /var/log/media-stick-firstboot.log"; exit 1
fi
grep -q 'REBOOT NEEDED' /var/log/media-stick-firstboot.log && { tv "Перезагружаюсь…"; reboot; }
