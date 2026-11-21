#!/bin/bash
# Grab what the HDMI output shows right now into a PNG on this computer.
# Usage: screenshot.sh [out.png]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
out=${1:-./screen.png}
"${SSH[@]}" "sudo ffmpeg -loglevel error -y -f kmsgrab -i - -frames:v 1 -vf 'hwdownload,format=bgr0' /tmp/screen.png"
scp -q -i "$KEY" -o IdentitiesOnly=yes "media@$HOST:/tmp/screen.png" "$out"
echo "$out"
