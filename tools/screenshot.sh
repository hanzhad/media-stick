#!/bin/bash
# Save what Kodi shows right now as a PNG on this computer (Kodi renders it itself,
# so it is the real picture at the real resolution).
# Usage: screenshot.sh [out.png]
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
lease_note
out=${1:-./screen.png}
remote=$("${SSH[@]}" 'rm -f /run/media-stick/shots/*.png; kodi-rpc Input.ExecuteAction "{\"action\":\"screenshot\"}" >/dev/null; for i in 1 2 3 4 5 6 7 8 9 10; do f=$(ls /run/media-stick/shots/*.png 2>/dev/null | head -1); [ -n "$f" ] && { sleep 0.5; echo "$f"; exit 0; }; sleep 0.5; done; exit 1')
scp -q -i "$KEY" -o IdentitiesOnly=yes "media@$HOST:$remote" "$out"
echo "$out"
