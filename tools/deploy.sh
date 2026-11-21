#!/bin/bash
# Deliver the repository to the device and apply it.
#   deploy.sh          device pulls origin/main and runs bootstrap (the normal path)
#   deploy.sh --local  copy this working tree as-is, uncommitted edits included (quick fix);
#                      the next normal deploy resets the device back to origin/main
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
if [ "${1:-}" = --local ]; then
  rsync -az --delete --exclude .git --exclude '*.local' --exclude secrets.env \
    -e "ssh -i $KEY -o IdentitiesOnly=yes" "$here/../" "media@$HOST:$DEST/"
  "${SSH[@]}" "sudo $DEST/device/bootstrap.sh"
else
  "${SSH[@]}" "cd $DEST && git fetch -q origin && git reset -q --hard origin/main && git log -1 --oneline && sudo $DEST/device/bootstrap.sh"
fi
