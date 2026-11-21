#!/bin/bash
# Build a ready SD card from nothing: official image + this repo's first-boot config.
# Usage: make-card.sh <diskN> [public key]   (asks before erasing; needs your Mac password)
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
DISK=${1:?diskN, see: diskutil list external physical}; PUB=${2:-$HOME/.ssh/mediastick.pub}
REL=${RPIOS_RELEASE:-raspios_lite_arm64-2026-10-06}
NAME=${RPIOS_IMAGE:-2026-10-06-raspios-trixie-arm64-lite.img.xz}
URL=https://downloads.raspberrypi.com/raspios_lite_arm64/images/$REL/$NAME
CACHE=${XDG_CACHE_HOME:-$HOME/.cache}/media-stick; mkdir -p "$CACHE"
[ -f "$PUB" ] || { echo "no public key $PUB (ssh-keygen -t ed25519 -f ${PUB%.pub})"; exit 1; }
if [ ! -f "$CACHE/$NAME" ]; then curl -fL -o "$CACHE/$NAME.part" "$URL" && mv "$CACHE/$NAME.part" "$CACHE/$NAME"; fi
curl -fsSL "$URL.sha256" | (cd "$CACHE" && shasum -a 256 -c -)
"$here/flash-sd.sh" "$CACHE/$NAME" "$DISK"
for i in $(seq 1 30); do [ -d /Volumes/bootfs ] && break; sleep 1; done
"$here/prepare-bootfs.sh" /Volumes/bootfs "$PUB"
sync; diskutil eject "/dev/$DISK"
echo "Card ready: put it in the Pi, connect network, power on."
