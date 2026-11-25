#!/usr/bin/env bash
# Launch the media-stick Kodi + Phone Remote desktop emulator via WSLg (or headless Xvfb).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="media-stick-emulator:local"
HOST="${MEDIASTICK_HOST:-192.168.1.14}"
KEY="${MEDIASTICK_KEY:-$HOME/.ssh/mediastick}"

MODE="auto"
HEADLESS=0
BUILD=0

while [ "$#" -gt 0 ]; do
    case "$1" in
        --live) MODE="live" ;;
        --demo) MODE="demo" ;;
        --headless) HEADLESS=1 ;;
        --build) BUILD=1 ;;
        -h|--help)
            echo "Usage: $0 [--live|--demo] [--headless] [--build]"
            echo "  --live      Pull SWEET.TV creds & channels from Pi ($HOST) into ephemeral tmpfs"
            echo "  --demo      Run with built-in demo data (no Pi required)"
            echo "  --headless  Use Xvfb instead of WSLg window"
            echo "  --build     Rebuild $IMAGE before starting"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
    shift
done

if [ "$BUILD" = "1" ] || ! docker image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Building $IMAGE..."
    docker build -t "$IMAGE" "$SCRIPT_DIR"
fi

CRED_DIR=""
cleanup() {
    if [ -n "$CRED_DIR" ] && [ -d "$CRED_DIR" ]; then
        rm -rf "$CRED_DIR"
    fi
}
trap cleanup EXIT

if [ "$MODE" = "auto" ]; then
    if [ -f "$KEY" ] && ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=3 -o StrictHostKeyChecking=accept-new "media@$HOST" true 2>/dev/null; then
        MODE="live"
    else
        MODE="demo"
    fi
fi

DOCKER_ARGS=(
    --rm -it
    -v "$REPO:/workspace:ro"
    -p 18080:18080
    -p 9090:9090
)

if [ "$MODE" = "live" ]; then
    CRED_DIR="$(mktemp -d /dev/shm/ms-emu.XXXXXX)"
    chmod 700 "$CRED_DIR"
    echo "Staging live SWEET.TV state from media@$HOST into ephemeral tmpfs..."
    scp -i "$KEY" -o ConnectTimeout=5 -q "media@$HOST:.kodi/userdata/addon_data/plugin.video.sweettv/settings.xml" "$CRED_DIR/settings.xml"
    scp -i "$KEY" -o ConnectTimeout=5 -q "media@$HOST:.kodi/temp/channelList.json" "$CRED_DIR/channelList.json" || true
    scp -i "$KEY" -o ConnectTimeout=5 -q "media@$HOST:/var/lib/media-stick/resume/resume.json" "$CRED_DIR/resume.json" || true
    scp -i "$KEY" -o ConnectTimeout=5 -q "media@$HOST:/var/lib/media-stick/resume/favourites.json" "$CRED_DIR/favourites.json" || true
    chmod 600 "$CRED_DIR"/*
    DOCKER_ARGS+=(-v "$CRED_DIR:/emu-creds:ro")
    [ -f "$CRED_DIR/settings.xml" ] && DOCKER_ARGS+=(-e SWEETTV_SETTINGS=/emu-creds/settings.xml)
    [ -f "$CRED_DIR/channelList.json" ] && DOCKER_ARGS+=(-e SWEETTV_CHANNELS=/emu-creds/channelList.json)
    [ -f "$CRED_DIR/resume.json" ] && DOCKER_ARGS+=(-e SWEETTV_RESUME=/emu-creds/resume.json)
    [ -f "$CRED_DIR/favourites.json" ] && DOCKER_ARGS+=(-e SWEETTV_FAVS=/emu-creds/favourites.json)
fi

if [ "$HEADLESS" = "1" ] || [ ! -d /tmp/.X11-unix ]; then
    DOCKER_ARGS+=(-e EMU_DISPLAY=xvfb)
    echo "Display: headless Xvfb (:99)"
else
    DOCKER_ARGS+=(
        -e EMU_DISPLAY=wslg
        -e "DISPLAY=${DISPLAY:-:0}"
        -e "WAYLAND_DISPLAY=${WAYLAND_DISPLAY:-}"
        -e XDG_RUNTIME_DIR=/mnt/wslg/runtime-dir
        -v /tmp/.X11-unix:/tmp/.X11-unix
    )
    [ -d /mnt/wslg ] && DOCKER_ARGS+=(-v /mnt/wslg:/mnt/wslg)
    echo "Display: WSLg desktop window ($DISPLAY)"
fi

echo "Phone Remote: http://localhost:18080"
echo "Mode: $MODE"
exec docker run "${DOCKER_ARGS[@]}" "$IMAGE"
