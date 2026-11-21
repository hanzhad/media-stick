#!/bin/bash
# Write a Raspberry Pi OS image to an SD card. Run by a person: needs sudo.
# Usage: flash-sd.sh <image.img.xz> <diskN>
set -euo pipefail
IMG=${1:?image.img.xz}; DISK=${2:?diskN, e.g. disk8}
info=$(diskutil info "/dev/$DISK")
echo "$info" | grep -qE 'Device Location:\s+External' || { echo "refuse: /dev/$DISK is not external"; exit 1; }
echo "$info" | grep -E 'Device / Media Name|Disk Size'
read -r -p "Erase /dev/$DISK completely? type yes: " ok; [ "$(echo "$ok" | tr A-Z a-z)" = yes ] || exit 1
diskutil unmountDisk "/dev/$DISK"
xz -dc "$IMG" | sudo dd of="/dev/r$DISK" bs=4m status=progress
sync
sleep 2
diskutil mountDisk "/dev/$DISK" || true
echo "FLASH DONE"
