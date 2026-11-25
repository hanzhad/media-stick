#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-/workspace}"
EMU_HOME="${EMU_HOME:-/tmp/emu-home}"
KODI_HOME="$EMU_HOME/.kodi"
USERDATA_TMP="/run/emu-userdata"
ADDONS_CACHE="${ADDONS_CACHE:-/tmp/emu-addons-cache}"
PANEL_PORT=${PANEL_PORT:-18080}
EMU_DISPLAY="${EMU_DISPLAY:-auto}"

mkdir -p "$KODI_HOME/addons" "$KODI_HOME/userdata/addon_data/plugin.video.youtube" "$KODI_HOME/temp" "$USERDATA_TMP" "$ADDONS_CACHE"
mkdir -p /var/lib/media-stick/prefs /var/lib/media-stick/resume /run/media-stick
mkdir -p /home/media
rm -rf /home/media/.kodi
ln -s "$KODI_HOME" /home/media/.kodi

# Stage device/files into /usr/local (read-only mount friendly)
if [ -d "$REPO/device/files/usr/local/lib/media-stick" ]; then
    mkdir -p /usr/local/lib/media-stick
    cp -a "$REPO/device/files/usr/local/lib/media-stick/." /usr/local/lib/media-stick/
fi
if [ -d "$REPO/device/files/usr/local/bin" ]; then
    cp -a "$REPO/device/files/usr/local/bin/." /usr/local/bin/
    chmod +x /usr/local/bin/*
fi
if [ -d "$REPO/device/files/usr/local/share/media-stick" ]; then
    mkdir -p /usr/local/share/media-stick
    cp -a "$REPO/device/files/usr/local/share/media-stick/." /usr/local/share/media-stick/
fi

# Unpack locked kodi-addons.list zips into $KODI_HOME/addons
if [ -f "$REPO/device/kodi-addons.list" ]; then
    while IFS=' ' read -r addon_id _ver url sha; do
        [ -z "${addon_id:-}" ] && continue
        case "$addon_id" in \#*) continue ;; esac
        zip="$ADDONS_CACHE/${addon_id}.zip"
        if [ ! -f "$zip" ]; then
            curl -fsSL "$url" -o "$zip"
            echo "$sha  $zip" | sha256sum -c -
        fi
        if [ ! -d "$KODI_HOME/addons/$addon_id" ]; then
            unzip -q "$zip" -d "$KODI_HOME/addons"
        fi
    done < "$REPO/device/kodi-addons.list"
fi

# Stage repo custom addons + skin overlays
if [ -d "$REPO/device/kodi-addons" ]; then
    cp -a "$REPO/device/kodi-addons/." "$KODI_HOME/addons/"
fi
if [ -d "$REPO/device/skin-overlay" ]; then
    cp -a "$REPO/device/skin-overlay/." "$KODI_HOME/addons/"
fi

# Mount external SWEET.TV settings.xml into tmpfs /run/emu-userdata without touching repo files
if [ -n "${SWEETTV_SETTINGS:-}" ] && [ -f "$SWEETTV_SETTINGS" ]; then
    mkdir -p "$USERDATA_TMP/plugin.video.sweettv"
    cp "$SWEETTV_SETTINGS" "$USERDATA_TMP/plugin.video.sweettv/settings.xml"
    chmod 600 "$USERDATA_TMP/plugin.video.sweettv/settings.xml"
    rm -rf "$KODI_HOME/userdata/addon_data/plugin.video.sweettv"
    ln -s "$USERDATA_TMP/plugin.video.sweettv" "$KODI_HOME/userdata/addon_data/plugin.video.sweettv"
fi

if [ -n "${SWEETTV_CHANNELS:-}" ] && [ -f "$SWEETTV_CHANNELS" ]; then
    cp "$SWEETTV_CHANNELS" "$KODI_HOME/temp/channelList.json"
fi
if [ -n "${SWEETTV_STATE_DB:-}" ] && [ -f "$SWEETTV_STATE_DB" ]; then
    cp "$SWEETTV_STATE_DB" /var/lib/media-stick/resume/state.db
    chmod 600 /var/lib/media-stick/resume/state.db
fi
if [ -n "${SWEETTV_RESUME:-}" ] && [ -f "$SWEETTV_RESUME" ]; then
    cp "$SWEETTV_RESUME" /var/lib/media-stick/resume/positions.json
fi
if [ -n "${SWEETTV_FAVS:-}" ] && [ -f "$SWEETTV_FAVS" ]; then
    cp "$SWEETTV_FAVS" /var/lib/media-stick/resume/sweettv-favourites.json
fi

# Suppress YouTube first-run setup wizard in emulator
if [ ! -f "$KODI_HOME/userdata/addon_data/plugin.video.youtube/settings.xml" ]; then
    cat > "$KODI_HOME/userdata/addon_data/plugin.video.youtube/settings.xml" <<'EOF'
<settings version="2"><setting id="kodion.setup_wizard">false</setting></settings>
EOF
fi

# Decide display mode: WSLg/host X11 when available unless EMU_DISPLAY=xvfb
USE_XVFB=0
if [ "$EMU_DISPLAY" = "xvfb" ] || [ -z "${DISPLAY:-}" ] || [ ! -d /tmp/.X11-unix ]; then
    USE_XVFB=1
fi

if [ "$USE_XVFB" = "1" ]; then
    export DISPLAY=":99"
    Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
    XVFB_PID=$!
    SCREEN_MODE="0192001080060.00000pstd"
else
    export DISPLAY="${DISPLAY:-:0}"
    [ -e /dev/dri ] || export LIBGL_ALWAYS_SOFTWARE=1
    if [ -S /mnt/wslg/PulseServer ]; then
        export PULSE_SERVER="unix:/mnt/wslg/PulseServer"
    fi
    XVFB_PID=""
    SCREEN_MODE="WINDOW"
fi

# Pre-seed Kodi GUI settings so skin.media-stick and mouse are active without popups
if [ -x /usr/local/bin/kodi-settings ]; then
    /usr/local/bin/kodi-settings \
        lookandfeel.skin=skin.media-stick \
        lookandfeel.startupwindow=10000 \
        screensaver.mode= \
        input.enablemouse=true \
        addons.unknownsources=true \
        "videoscreen.screenmode=$SCREEN_MODE" \
        filecache.buffermode=2 \
        window.width=1920 \
        window.height=1080 >/dev/null
fi

# Enable JSON-RPC on :9090 (disable webserver to avoid passwordless-webserver dialog)
cat > "$KODI_HOME/userdata/advancedsettings.xml" <<'EOF'
<advancedsettings version="1.0">
  <services>
    <esallinterfaces>true</esallinterfaces>
    <webserver>false</webserver>
    <zeroconf>false</zeroconf>
  </services>
  <jsonrpc>
    <compactoutput>false</compactoutput>
    <tcpport>9090</tcpport>
  </jsonrpc>
  <network>
    <curlclienttimeout>5</curlclienttimeout>
    <curllowspeedtime>5</curllowspeedtime>
    <curlretries>1</curlretries>
  </network>
</advancedsettings>
EOF

export HOME="$EMU_HOME"

# Enable bundled addons over JSON-RPC on first boot so Kodi does not prompt
(
    python3 - <<'PYEOF'
import json, socket, time

def rpc(method, params=None):
    s = socket.create_connection(("127.0.0.1", 9090), 2)
    req = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        req["params"] = params
    s.sendall((json.dumps(req) + "\n").encode())
    s.settimeout(2)
    try:
        data = s.recv(8192).decode(errors="ignore")
    except Exception:
        data = ""
    s.close()
    return data

for _ in range(40):
    try:
        rpc("JSONRPC.Ping")
        break
    except Exception:
        time.sleep(0.5)
else:
    raise SystemExit(0)

time.sleep(0.8)
for aid in ("skin.media-stick", "script.media-stick.home", "plugin.video.sweettv", "plugin.video.youtube", "inputstream.adaptive"):
    try:
        rpc("Addons.SetAddonEnabled", {"addonid": aid, "enabled": True})
    except Exception:
        pass
try:
    cur = rpc("Settings.GetSettingValue", {"setting": "lookandfeel.skin"})
    if "skin.media-stick" not in cur:
        rpc("Settings.SetSettingValue", {"setting": "lookandfeel.skin", "value": "skin.media-stick"})
        time.sleep(0.6)
        rpc("Input.Left")
        time.sleep(0.2)
        rpc("Input.Select")
except Exception:
    pass
for _ in range(10):
    try:
        win = json.loads(rpc("GUI.GetProperties", {"properties": ["currentwindow"]}) or "{}")
        wid = ((win.get("result") or {}).get("currentwindow") or {}).get("id", 0)
        if wid >= 10100:
            rpc("Input.Back")
            time.sleep(0.3)
        else:
            break
    except Exception:
        break
try:
    win = json.loads(rpc("GUI.GetProperties", {"properties": ["currentwindow"]}) or "{}")
    wid = ((win.get("result") or {}).get("currentwindow") or {}).get("id", 0)
    if wid in (10000, 10025):
        rpc("Addons.ExecuteAddon", {"addonid": "script.media-stick.home"})
except Exception:
    pass
PYEOF
) >/dev/null 2>&1 &

# Start phone panel on $PANEL_PORT if present
if [ -f /usr/local/bin/panel ]; then
    PANEL_PORT="$PANEL_PORT" python3 /usr/local/bin/panel &
fi

cleanup() {
    if [ -n "$XVFB_PID" ]; then
        kill "$XVFB_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

exec kodi --standalone
