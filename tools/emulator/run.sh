#!/usr/bin/env bash
set -euo pipefail

REPO="${REPO:-/workspace}"
EMU_HOME="${EMU_HOME:-/tmp/emu-home}"
KODI_HOME="$EMU_HOME/.kodi"
USERDATA_TMP="/run/emu-userdata"
ADDONS_CACHE="${ADDONS_CACHE:-/tmp/emu-addons-cache}"

mkdir -p "$KODI_HOME/addons" "$KODI_HOME/userdata/addon_data" "$USERDATA_TMP" "$ADDONS_CACHE"
mkdir -p /var/lib/media-stick/prefs /var/lib/media-stick/resume /run/media-stick

# Stage device/files into /usr/local (read-only mount friendly)
if [ -d "$REPO/device/files/usr/local/lib/media-stick" ]; then
    mkdir -p /usr/local/lib/media-stick
    cp -a "$REPO/device/files/usr/local/lib/media-stick/." /usr/local/lib/media-stick/
fi
if [ -d "$REPO/device/files/usr/local/bin" ]; then
    cp -a "$REPO/device/files/usr/local/bin/." /usr/local/bin/
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

# Enable JSON-RPC on :9090
cat > "$KODI_HOME/userdata/advancedsettings.xml" <<'EOF'
<advancedsettings version="1.0">
  <services>
    <esallinterfaces>true</esallinterfaces>
    <webserver>true</webserver>
    <webserverport>8080</webserverport>
    <zeroconf>false</zeroconf>
  </services>
  <jsonrpc>
    <compactoutput>false</compactoutput>
    <tcpport>9090</tcpport>
  </jsonrpc>
</advancedsettings>
EOF

export HOME="$EMU_HOME"
export DISPLAY=":99"

Xvfb :99 -screen 0 1920x1080x24 -nolisten tcp &
XVFB_PID=$!

# Start phone panel on :8080 if present
if [ -x /usr/local/bin/panel ]; then
    MEDIASTICK_PANEL_PORT=8080 /usr/local/bin/panel &
fi

cleanup() {
    kill "$XVFB_PID" 2>/dev/null || true
}
trap cleanup EXIT

exec kodi --standalone
