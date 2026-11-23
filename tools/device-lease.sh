#!/bin/bash
# The device is one: take the lease before you change it, give it back when done (see AGENTS.md).
#   device-lease.sh acquire --for "name [session id]" --why "what for" [--ttl 30m] [--wait 5m]
#   device-lease.sh renew   [--for HOLDER] [--ttl 30m]
#   device-lease.sh release [--for HOLDER]
#   device-lease.sh status  [--json]
#   device-lease.sh steal   --for HOLDER --force         the owner's; never automatic
# --for defaults to $MEDIASTICK_HOLDER. Exit: 0 ok, 2 bad usage, 3 held by someone else.
# Runs /usr/local/bin/media-stick-lease on the device (installed by the first deploy).
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
usage() { sed -n '2,8p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
cmd=${1:-}
case $cmd in acquire|renew|release|status|steal) shift ;; *) usage ;; esac

holder=${MEDIASTICK_HOLDER:-}; args=(); has_for=0; prev=
for a in "$@"; do
  [ "$prev" = --for ] && { holder=$a; has_for=1; }
  args+=("$a"); prev=$a
done
if [ "$cmd" != status ] && [ $has_for = 0 ]; then
  [ -n "$holder" ] || { echo "who are you? --for \"name [session id]\" or MEDIASTICK_HOLDER" >&2; exit 2; }
  args+=(--for "$holder")
fi

lease_remote "$cmd" ${args[@]+"${args[@]}"}; rc=$?
case $rc in
  0) case $cmd in acquire|renew) echo "tools use it with: MEDIASTICK_HOLDER=\"$holder\"" ;; esac ;;
  127) echo "the lease tool is not installed on the device yet: run tools/deploy.sh once (it installs it)" >&2 ;;
esac
exit $rc
