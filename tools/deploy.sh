#!/bin/bash
# Deliver the repository to the device and apply it. Every form needs this tree to contain
# origin/main (else: rebase first) and the device lease (tools/device-lease.sh, MEDIASTICK_HOLDER);
# see AGENTS.md.
#   deploy.sh          device pulls origin/main and runs bootstrap (the normal path)
#   deploy.sh --local  copy this working tree as-is, uncommitted edits included (quick fix);
#                      the next normal deploy resets the device back to origin/main.
#                      Replaces the whole tree on the device: uncommitted edits another session
#                      put there are lost (use --only while someone else works on the device)
#   deploy.sh --only PATH...
#                      copy just these files or directories (relative to the repository root),
#                      delete nothing, touch nothing else, then run bootstrap
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
gate() { require_fresh_base "$here/.."; require_lease; }
case "${1:-}" in
  --local)
    gate
    rsync -az --delete --exclude .git --exclude '*.local' --exclude secrets.env --exclude '__pycache__/' --exclude '*.pyc' --exclude '.devcontainer/' --exclude '.claude/' --exclude 'project.env' --exclude 'tools/emulator/.state/' --exclude '.github/' \
      "${RSYNC_E[@]}" "$here/../" "media@$HOST:$DEST/"
    "${SSH[@]}" "sudo $DEST/device/bootstrap.sh"
    ;;
  --only)
    shift
    [ $# -gt 0 ] || { echo "usage: deploy.sh --only PATH..." >&2; exit 2; }
    only_check "$here/.." "$@" || exit 2
    gate
    echo "sending only: ${ONLY[*]}"
    only_push "$here/.." "media@$HOST:$DEST/" "${ONLY[@]}"
    "${SSH[@]}" "sudo $DEST/device/bootstrap.sh"
    ;;
  "")
    gate
    "${SSH[@]}" "cd $DEST && git fetch -q origin && git reset -q --hard origin/main && git log -1 --oneline && sudo $DEST/device/bootstrap.sh"
    ;;
  *) echo "usage: deploy.sh [--local | --only PATH...]" >&2; exit 2 ;;
esac
