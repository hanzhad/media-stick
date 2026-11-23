# shellcheck shell=bash disable=SC2034
# Sourced by tools/*. Override with env: MEDIASTICK_HOST, MEDIASTICK_KEY.
# Changing the device needs the device lease (tools/device-lease.sh): MEDIASTICK_HOLDER is who you
# are ("name [session id]"); MEDIASTICK_NO_LEASE=1 is the owner's way past it.
HOST=${MEDIASTICK_HOST:-mediastick.local}
KEY=${MEDIASTICK_KEY:-$HOME/.ssh/mediastick}
DEST=/opt/media-stick
SSH=(ssh -i "$KEY" -o IdentitiesOnly=yes -o ConnectTimeout=8 "media@$HOST")
RSYNC_E=(-e "ssh -i $KEY -o IdentitiesOnly=yes")
LEASE_BIN=/usr/local/bin/media-stick-lease

# lease_remote ARGS...: run the lease helper on the device; its output and exit code pass through.
lease_remote() { "${SSH[@]}" "$LEASE_BIN $(printf '%q ' "$@")"; }

# lease_note: for read-only tools; says who has the device, never refuses.
lease_note() {
  local out
  out=$(lease_remote check 2>/dev/null) || [ $? -ne 3 ] || echo "NOTE  $out" >&2
}

# require_lease: for tools that change the device. Exits 3 unless this session holds a live lease
# (a tool run with the right holder extends it by 15 minutes). A device that has not got the
# helper yet (the deploy that installs it) is let through with a warning.
require_lease() {
  local out rc
  if [ "${MEDIASTICK_NO_LEASE:-}" = 1 ]; then
    echo "!!! MEDIASTICK_NO_LEASE=1: changing the device WITHOUT the lease (owner only) !!!" >&2
    return 0
  fi
  if [ -n "${MEDIASTICK_HOLDER:-}" ]; then
    out=$(lease_remote renew --for "$MEDIASTICK_HOLDER" --ttl 15m 2>&1) && rc=0 || rc=$?  # callers run under set -e
  else
    out=$(lease_remote check 2>&1) && rc=0 || rc=$?
    [ $rc -eq 0 ] && rc=4
  fi
  case $rc in
    0) return 0 ;;
    127) echo "WARN  the lease tool is not installed on the device yet; this deploy installs it" >&2; return 0 ;;
    3) echo "refused: $out" >&2
       echo "      wait for it, or ask the holder; never steal (only the owner: tools/device-lease.sh steal)" >&2
       exit 3 ;;
    4) [ -n "$out" ] && echo "$out" >&2
       echo "refused: you hold no device lease. Take one:" >&2
       echo "      MEDIASTICK_HOLDER=\"name [session id]\" tools/device-lease.sh acquire --why \"what for\" --ttl 30m" >&2
       echo "      then run this tool with the same MEDIASTICK_HOLDER set" >&2
       exit 3 ;;
    *) echo "refused: could not check the device lease (rc=$rc): $out" >&2; exit 1 ;;
  esac
}

# require_fresh_base ROOT: exits 4 unless origin/main is an ancestor of HEAD in the repository ROOT
# (after a fetch). --local uploads whole files, so a tree behind origin/main would roll back what
# another session has pushed. MEDIASTICK_NO_BASE_CHECK=1 is the owner's way past it.
require_fresh_base() {
  local root=$1
  if [ "${MEDIASTICK_NO_BASE_CHECK:-}" = 1 ]; then
    echo "!!! MEDIASTICK_NO_BASE_CHECK=1: not checking this tree against origin/main (owner only) !!!" >&2
    return 0
  fi
  git -C "$root" fetch -q origin main 2>/dev/null \
    || echo "WARN  could not fetch origin/main; checking against the last one fetched" >&2
  if ! git -C "$root" rev-parse -q --verify origin/main >/dev/null; then
    echo "refused: no origin/main to compare this tree with" >&2; exit 4
  fi
  if ! git -C "$root" merge-base --is-ancestor origin/main HEAD; then
    echo "refused: local tree lacks commits from origin/main, rebase/merge first (git pull --rebase)" >&2; exit 4
  fi
}

# only_check ROOT PATH...: sets ONLY to the paths to send; each must exist inside the repository
# ROOT, relative, with no "..", and not touch .git, secrets.env or a *.local file.
# Returns 1 and says why otherwise.
only_check() {
  local root p rootp parent
  root=$1; shift; ONLY=()
  rootp=$(cd "$root" && pwd -P) || return 1
  for p in "$@"; do
    p=${p#./}
    case "/$p/" in
      //*) echo "refusing '$p': an absolute path or empty" >&2; return 1 ;;
      */../*|*/./*) echo "refusing '$p': '.' and '..' are not allowed" >&2; return 1 ;;
      */.git/*) echo "refusing '$p': .git is never sent" >&2; return 1 ;;
      */secrets.env/*|*/*.local/*) echo "refusing '$p': secrets and *.local files stay where they are" >&2; return 1 ;;
    esac
    [ -e "$root/$p" ] || [ -L "$root/$p" ] || { echo "refusing '$p': not in the repository" >&2; return 1; }
    parent=$(cd "$(dirname "$root/$p")" && pwd -P)
    case "$parent/" in "$rootp"/*) ;; *) echo "refusing '$p': resolves outside the repository" >&2; return 1 ;; esac
    ONLY+=("$p")
  done
}

# only_push ROOT DEST PATH...: copy just these paths, keeping their place under ROOT, creating the
# directories on the way and deleting nothing. DEST is [user@host:]dir/, RSYNC_E the transport.
# --checksum: rsync alone skips a file whose size and mtime (whole seconds) equal the device copy,
# so an edit of the same size made within that second would silently not be sent.
only_push() {
  local root=$1 dest=$2 srcs p; shift 2; srcs=()
  for p in "$@"; do srcs+=("./$p"); done
  (cd "$root" && rsync -azRv --checksum "${RSYNC_E[@]}" --exclude .git --exclude '*.local' --exclude secrets.env \
    -- "${srcs[@]}" "$dest")
}
