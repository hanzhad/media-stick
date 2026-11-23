#!/bin/bash
# Smoke test of the Accounts feature on the real device, run from the owner's computer.
#   smoke-accounts.sh [--shots DIR]
#       read-only: lease, deployed files equal this tree, sign-in state dir, panel, GET /api/accounts
#   smoke-accounts.sh --live [--shots DIR]
#       also starts a SWEET.TV sign-in on the TV through the phone API, waits for its code, saves a
#       screenshot of the TV into DIR, cancels it and checks that nothing stays waiting. No login is
#       completed; the cancel is also sent from a trap when a check fails or the run is interrupted.
# Needs the device lease (MEDIASTICK_HOLDER, AGENTS.md), a tree that contains origin/main, and python3.
# Exit: 0 every check passed, 1 a check failed, 2 bad usage, 3 lease refused, 4 tree behind origin/main.
set -uo pipefail
here=$(cd "$(dirname "$0")" && pwd); . "$here/common.sh"
root=$(cd "$here/.." && pwd)

POLL=${MEDIASTICK_SMOKE_POLL:-2}   # s between two looks at the state (the tests set 0)
SIGNIN_TRIES=20                    # 20 looks, POLL apart: about 40 s for the code to appear
CANCEL_TRIES=10                    # about 20 s for the cancel to show
SERVICE=sweettv
LINK_PREFIX=https://sweet.tv/

usage() { sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//' >&2; exit 2; }
live=0; shots=
while [ $# -gt 0 ]; do
  case $1 in
    --live) live=1 ;;
    --shots) [ $# -ge 2 ] || usage; shots=$2; shift ;;
    *) usage ;;
  esac
  shift
done
command -v python3 >/dev/null 2>&1 || { echo "needs python3 on this computer" >&2; exit 2; }
if [ $live = 1 ] && [ -z "$shots" ]; then shots=$(mktemp -d "${TMPDIR:-/tmp}/smoke-accounts.XXXXXX"); fi

pass=0; fail=0
ok()  { printf 'PASS  %s\n' "$*"; pass=$((pass + 1)); }
bad() { printf 'FAIL  %s\n' "$*"; fail=$((fail + 1)); }

# ---- what is checked, and where each file lives on the device --------------------------------
KODI_ADDONS=/home/media/.kodi/addons
SIGNIN_DIR=/run/media-stick/signin
FILES=(
  device/files/usr/local/lib/media-stick/mediastick_signin.py
  device/files/usr/local/bin/panel
  device/files/usr/local/lib/media-stick/panel_accounts.py
  device/files/usr/local/lib/media-stick/panel_accounts_ui.py
  device/files/usr/local/lib/media-stick/mediastick_ytkeys.py
  device/files/usr/local/lib/media-stick/panel_ytkeys.py
  device/files/usr/local/lib/media-stick/panel_ytkeys_ui.py
  device/kodi-addons/script.media-stick.home/resources/lib/accounts.py
  device/kodi-addons/script.media-stick.home/resources/lib/signin.py
  device/kodi-addons/script.media-stick.home/resources/lib/ytkeys.py
  # the sign-in overlays: bootstrap copies them over the installed add-ons (doctor.sh checks all overlays)
  device/skin-overlay/plugin.video.sweettv/resources/lib/sweettv.py
  device/skin-overlay/plugin.video.youtube/resources/lib/youtube_plugin/kodion/script_actions.py
  device/skin-overlay/plugin.video.youtube/resources/lib/youtube_plugin/youtube/helper/yt_login.py
)

# remote_path REL: where bootstrap puts the repository file REL on the device
remote_path() {
  case $1 in
    device/files/*) echo "${1#device/files}" ;;
    device/kodi-addons/*) echo "$KODI_ADDONS/${1#device/kodi-addons/}" ;;
    device/skin-overlay/*) echo "$KODI_ADDONS/${1#device/skin-overlay/}" ;;
  esac
}

sha_of() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1"; else shasum -a 256 "$1"; fi | cut -d' ' -f1
}

# The kodi log: where doctor.sh and AGENTS.md read it. Wanted: a line of the launcher add-on, a Traceback.
KODI_LOG='~media/.kodi/temp/kodi.log'
LOG_AWK='/\[script\.media-stick\.home\]/ {print; next} /Traceback/ {print; n = 6; next} n > 0 {print; n--}'
# whatever a log line may carry of a token never reaches this screen
redact() { sed -E 's/(refresh_token|access_token|[Bb]earer)[=: "]+[^ ,}"]+/\1 ***/g'; }
# indent HEADING: stdin, redacted, under a heading
indent() { echo "      $1:"; redact | sed 's/^/        /'; }

# the sign-in states as the panel sees them (the shared library reads the state files; stale ones are gone)
STATE_CMD='cd /usr/local/lib/media-stick && python3 -c "import json, mediastick_signin as s; print(json.dumps({n: s.read(n) for n in s.SERVICES}))"'

# python3 reading the API body on stdin. Prints "json" or "notjson", then what leaks, or "-"
PY_BODY='
import json, re, sys
raw = sys.stdin.read()
leaks = [s for s in ("refresh_token", "access_token", "Bearer ") if s in raw]
KEY = re.compile(r"token|secret|passw|bearer|authoriz|credential|cookie|api[_-]?key", re.I)
VAL = re.compile(r"^(ya29\.|1//|eyJ[\w-]+\.)")
def walk(x, path):
    if isinstance(x, dict):
        for k, v in x.items():
            # "tokens" is how many tokens a profile has: a count, never a token
            if KEY.search(k) and not (k == "tokens" and isinstance(v, int) and not isinstance(v, bool)):
                leaks.append("key " + path + "/" + k)
            walk(v, path + "/" + k)
    elif isinstance(x, list):
        for i, v in enumerate(x):
            walk(v, path + "/" + str(i))
    elif isinstance(x, str) and VAL.match(x):
        leaks.append("token-like value at " + path)
try:
    data = json.loads(raw)
except ValueError:
    data = None
walk(data, "")
print("json" if isinstance(data, dict) and isinstance(data.get("accounts"), list) else "notjson", ",".join(leaks) or "-")
'

# python3 reading the states on stdin; argv: service, link prefix. Prints: state, code length, link ok, waiting services
PY_STATE='
import json, sys
try:
    d = json.load(sys.stdin)
    s = d.get(sys.argv[1]) or {}
    waiting = ",".join(n for n, v in d.items() if v and v.get("state") == "waiting") or "-"
    print(s.get("state") or "none", len(str(s.get("code") or "")), 1 if str(s.get("link") or "").startswith(sys.argv[2]) else 0, waiting)
except (ValueError, AttributeError):
    print("error 0 0 -")
'

jfield() {  # JSON KEY: the value of a top-level key, "None" when there is none
  python3 -I -c 'import json, sys
try: print(json.loads(sys.argv[1]).get(sys.argv[2]))
except (ValueError, AttributeError): print(None)' "$1" "$2"
}

# ---- the phone API ---------------------------------------------------------------------------
# The panel wants X-Panel: 1 on a change, and a Host it knows (an IP, mediastick, mediastick.local, localhost).
case $HOST in *:*) BASE="http://[$HOST]" ;; *) BASE="http://$HOST" ;; esac
API_CODE=000; API_BODY=
api() {  # METHOD PATH [JSON]: sets API_CODE (000: no answer) and API_BODY
  local out rc args
  args=(-sS -L --max-time 15 -H 'X-Panel: 1' -w '\n%{http_code}')
  [ "$1" = POST ] && args+=(-H 'Content-Type: application/json' -d "$3")
  out=$(curl "${args[@]}" "$BASE$2" 2>&1) && rc=0 || rc=$?
  API_CODE=${out##*$'\n'}; API_BODY=${out%$'\n'*}
  if [ $rc -ne 0 ] || ! [[ $API_CODE =~ ^[0-9]{3}$ ]]; then API_CODE=000; fi
}

ST=none; CODELEN=0; LINK_OK=0; WAITING=-
read_state() {  # sets ST CODELEN LINK_OK WAITING for $SERVICE
  local json
  json=$("${SSH[@]}" "$STATE_CMD" 2>/dev/null) || json=
  read -r ST CODELEN LINK_OK WAITING <<<"$(printf '%s' "$json" | python3 -I -c "$PY_STATE" "$SERVICE" "$LINK_PREFIX")"
}

# ---- the cancel that always happens ----------------------------------------------------------
cancel_pending=0
cleanup() {
  if [ "$cancel_pending" = 1 ]; then
    echo "cleanup: cancelling the $SERVICE sign-in"
    api POST /api/accounts/cancel "{\"service\": \"$SERVICE\"}"
    [ "$API_CODE" = 200 ] || echo "WARN  cleanup: the cancel was not accepted (HTTP $API_CODE): press Back on the TV" >&2
  fi
}
trap cleanup EXIT
trap 'exit 130' INT TERM

# ---- 0: say what will happen, refuse without the lease or a fresh tree ------------------------
echo "smoke test of the accounts feature on $HOST"
echo "  read-only: device lease, deployed files = this tree (${#FILES[@]} files), $SIGNIN_DIR, panel.service, GET $BASE/api/accounts (no tokens in it)"
if [ $live = 1 ]; then
  echo "  --live: starts a $SERVICE sign-in on the TV (POST /api/accounts/signin), waits for its code, saves a screenshot to $shots,"
  echo "          cancels it (POST /api/accounts/cancel; also from a trap), checks nothing stays waiting, reads the Kodi log. No login is completed."
else
  echo "  no --live: nothing is started on the TV"
fi
require_fresh_base "$root"
if [ "${MEDIASTICK_NO_BASE_CHECK:-}" = 1 ]; then ok "tree: not compared with origin/main (owner, MEDIASTICK_NO_BASE_CHECK=1)"
else ok "tree: contains origin/main"; fi
require_lease
if [ "${MEDIASTICK_NO_LEASE:-}" = 1 ]; then ok "lease: bypassed by the owner (MEDIASTICK_NO_LEASE=1)"
else ok "lease: held by ${MEDIASTICK_HOLDER:-?}"; fi

# ---- 1: read-only ----------------------------------------------------------------------------
list=
for rel in "${FILES[@]}"; do list="$list $(remote_path "$rel")"; done
sums=$("${SSH[@]}" "for f in $list; do sha256sum -- \"\$f\" 2>/dev/null || echo \"missing  \$f\"; done" 2>/dev/null) || sums=
for rel in "${FILES[@]}"; do
  rp=$(remote_path "$rel")
  if [ ! -f "$root/$rel" ]; then bad "file: $rel is not in this tree"; continue; fi
  have=$(printf '%s\n' "$sums" | awk -v p="$rp" '$2 == p && $1 != "missing" {print $1}')
  if [ -z "$have" ]; then bad "file: $rp is not on the device"
  elif [ "$have" = "$(sha_of "$root/$rel")" ]; then ok "file: $rp equals $rel"
  else bad "file: $rp differs from $rel (deploy it)"; fi
done

if "${SSH[@]}" "test -d $SIGNIN_DIR && test -w $SIGNIN_DIR" >/dev/null 2>&1; then ok "dir: $SIGNIN_DIR exists and media can write it"
else bad "dir: $SIGNIN_DIR is missing or not writable by media"; fi

state=$("${SSH[@]}" 'systemctl is-active panel.service' 2>/dev/null) || state=${state:-unknown}
if [ "$state" = active ]; then ok "panel: panel.service active"; else bad "panel: panel.service is ${state:-unknown}"; fi

api GET /api/accounts
api_up=0
if [ "$API_CODE" = 200 ]; then
  api_up=1
  read -r shape leaks <<<"$(printf '%s' "$API_BODY" | python3 -I -c "$PY_BODY")"
  if [ "$shape" = json ]; then ok "api: GET /api/accounts is JSON with accounts"; else bad "api: GET /api/accounts is not the expected JSON"; fi
  if [ "$leaks" = - ]; then ok "api: no token in the body"; else bad "api: the body leaks: $leaks"; fi
else
  bad "api: GET $BASE/api/accounts answered HTTP $API_CODE (000: no answer)"
fi

# ---- 2: live ---------------------------------------------------------------------------------
live_check() {
  local i seen=0 shot out log_n log_ts klog jlog
  read_state
  if [ "$WAITING" != - ]; then bad "live: a sign-in is already waiting ($WAITING); not touching it, finish or cancel it first"; return; fi
  read -r log_n log_ts <<<"$("${SSH[@]}" "echo \$(wc -l < $KODI_LOG) \$(date '+%Y-%m-%d %H:%M:%S')" 2>/dev/null)"
  if ! [[ $log_n =~ ^[0-9]+$ && -n $log_ts ]]; then bad "live: cannot read where the Kodi log stands"; log_ts=; fi

  echo "  --- live: starting the $SERVICE sign-in on the TV"
  cancel_pending=1   # from here on, whatever happens, the trap cancels it
  api POST /api/accounts/signin "{\"service\": \"$SERVICE\"}"
  if [ "$API_CODE" != 200 ] || [ "$(jfield "$API_BODY" ok)" != True ]; then
    bad "live: POST /api/accounts/signin answered HTTP $API_CODE"; return
  fi
  if [ "$(jfield "$API_BODY" already)" = True ]; then
    cancel_pending=0; bad "live: a sign-in was already running; left alone"; return
  fi

  for ((i = 0; i < SIGNIN_TRIES; i++)); do
    read_state
    if [ "$ST" = waiting ] && [ "${CODELEN:-0}" -gt 0 ] && [ "$LINK_OK" = 1 ]; then seen=1; break; fi
    sleep "$POLL"
  done
  if [ $seen = 1 ]; then ok "live: state waiting with a code of $CODELEN characters and a ${LINK_PREFIX}... link"
  else bad "live: no waiting state with a code and a ${LINK_PREFIX} link in $((SIGNIN_TRIES * 2)) s (last state: $ST)"; fi

  mkdir -p "$shots"
  shot="$shots/accounts-$SERVICE-code.png"
  if out=$("$here/screenshot.sh" "$shot" 2>&1); then ok "live: TV screenshot saved: $shot (look at it: code and QR on screen)"
  else bad "live: TV screenshot failed: $(printf '%s' "$out" | tail -n 1)"; fi

  echo "  --- live: cancelling"
  api POST /api/accounts/cancel "{\"service\": \"$SERVICE\"}"
  if [ "$API_CODE" = 200 ] && [ "$(jfield "$API_BODY" ok)" = True ]; then
    cancel_pending=0; ok "live: POST /api/accounts/cancel accepted"
  else bad "live: POST /api/accounts/cancel answered HTTP $API_CODE"; fi
  for ((i = 0; i < CANCEL_TRIES; i++)); do
    read_state
    [ "$ST" = cancelled ] && break
    sleep "$POLL"
  done
  if [ "$ST" = cancelled ]; then ok "live: state is cancelled"; else bad "live: state is $ST, not cancelled, $((CANCEL_TRIES * 2)) s after the cancel"; fi
  read_state
  if [ "$WAITING" = - ]; then ok "live: no sign-in is waiting any more"; else bad "live: still waiting: $WAITING"; fi

  [ -n "$log_ts" ] || return
  # a restart of Kodi starts a new log: then everything in it is new
  klog=$("${SSH[@]}" 'bash -s' 2>/dev/null <<R
n=$log_n
[ "\$(wc -l < $KODI_LOG)" -ge "\$n" ] || n=0
tail -n +\$((n + 1)) $KODI_LOG | awk '$LOG_AWK'
R
  ) || { bad "live: cannot read kodi.log"; return; }
  jlog=$("${SSH[@]}" 'bash -s' 2>/dev/null <<R
set -o pipefail
sudo -n journalctl -u kodi --since '$log_ts' --no-pager -o cat | awk '$LOG_AWK'
R
  ) || { bad "live: cannot read the journal of kodi.service"; return; }
  if [ -z "$klog$jlog" ]; then ok "live: no new [script.media-stick.home] or Traceback line in kodi.log and the journal"
  else
    [ -z "$klog" ] || printf '%s\n' "$klog" | indent "kodi.log: new lines of the add-on or a Traceback"
    [ -z "$jlog" ] || printf '%s\n' "$jlog" | indent "journalctl -u kodi: the same"
    bad "live: the log has new [script.media-stick.home] or Traceback lines (above)"
  fi
}

if [ $live = 1 ]; then
  if [ $api_up = 1 ]; then live_check; else bad "live: not started, the panel API did not answer"; fi
fi

echo "summary: $pass passed, $fail failed"
[ $fail -eq 0 ]
