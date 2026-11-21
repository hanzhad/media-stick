#!/bin/bash
# Put first-boot config onto a freshly flashed card's boot partition.
# Usage: prepare-bootfs.sh <bootfs mount> <public key file>
set -euo pipefail
BOOT=${1:-/Volumes/bootfs}; PUB=${2:-$HOME/.ssh/mediastick.pub}
here=$(cd "$(dirname "$0")" && pwd)
[ -f "$BOOT/cmdline.txt" ] && [ -f "$BOOT/meta-data" ] || { echo "not a Pi OS boot partition: $BOOT"; exit 1; }
key=$(cat "$PUB")
sed "s|@SSH_PUBKEY@|$key|" "$here/cloud-init/user-data" > "$BOOT/user-data"
cp "$here/cloud-init/network-config" "$BOOT/network-config"
touch "$BOOT/ssh"
# First-boot scripts: network setup (hotspot) and hand-over to the repository.
mkdir -p "$BOOT/media-stick"
cp "$here/firstboot/firstboot.sh" "$here/../device/files/usr/local/bin/wifi-setup" "$BOOT/media-stick/"
# Fixed 1080p output even with no TV attached (D = force connector on).
grep -q 'video=HDMI-A-1' "$BOOT/cmdline.txt" || \
  sed -i '' '1s|$| video=HDMI-A-1:1920x1080@60D|' "$BOOT/cmdline.txt"
echo "bootfs ready"
