# Media Stick v2 Architecture

Media Stick turns a Raspberry Pi 3B+ (1 GB RAM, Raspberry Pi OS Lite 64-bit / Debian 13 trixie) into a headless TV appliance controlled from a phone. Everything on the device is declared in this repository and applied idempotently by `device/bootstrap.sh` and `device/os_apply.py`.

## Hardware & Memory Budget (Pi 3B+, 1 GB RAM)

- **CMA & Video Decode**: `/boot/firmware/config.txt` sets `dtoverlay=vc4-kms-v3d,cma-256` (256 MB contiguous memory for 1080p H.264 hardware decode; HEVC/H.265 and 4K are not targets).
- **zram & VM Tuning**: `systemd-zram-generator` configures a 384 MB `zstd` `/dev/zram0` swap device (`priority=100`, `vm.swappiness=100`, `vm.page-cluster=0` in `device/files/etc/sysctl.d/90-media-stick-vm.conf`), replacing disk swap (`dphys-swapfile.service` is disabled).
- **tmpfs & Volatile Logs**: `/run/media-stick` holds transient shots, display sockets, sign-in/onboarding state, and active stream metadata; `/etc/fstab` adds `noatime,commit=60` on `/` and a 16 MB `tmpfs` at `/home/media/.kodi/temp`; Chromium web-app cache lives in `/tmp/chromium-cache` (32 MB cap); `journald` is volatile (`RuntimeMaxUse=16M`).
- **Cgroup Guardrails**: `kodi.service` (`MemoryHigh=380M`, `MemoryMax=480M`, `OOMScoreAdjust=200`) and `web-app@.service` (`MemoryHigh=450M`, `MemoryMax=580M`, `OOMScoreAdjust=500`) bound foreground processes while `mediastick-displayd.service`, `panel.service`, and `airplay.service` carry `OOMScoreAdjust=-200`.

## Display & Power Arbitrator (`mediastick-displayd`)

- **Centralized State Machine**: `device/files/usr/local/bin/mediastick-displayd` and `mediastick_display.py` (`DisplayStateMachine`) serialize all screen ownership transitions over `/run/media-stick/display.sock` (`KODI`, `CAST_AIRPLAY`, `CAST_MIRACAST`, `WEB_APP`, `STANDBY`).
- **Standby & HDMI-CEC**: Entering `STANDBY` flushes state, stops the active display unit, sends HDMI-CEC standby (`cec-ctl -d /dev/cec0 --to 0 --standby`), turns KMS DPMS off, drops CPU governors to `powersave`, and pauses Miracast P2P. `wake` reverses this (`ondemand` governor, KMS DPMS on, CEC `image-view-on`, restarts Kodi).
- **Miracast P2P Pause**: `is_p2p_allowed(state, kodi_playing, hotspot_active)` only allows Wi-Fi P2P discovery (`wpa_cli ... p2p_stop_find`) when `KODI` owns the screen, Kodi is idle (reported by `PlaybackNotifier` in `script.media-stick.home/service.py`), and no setup hotspot is active.
- **Single DRM Splash**: `mediastick_drm.py` and `console-splash` own the framebuffer splash shown between transitions (`draw_splash`) and at boot alongside Plymouth (`mediastick` theme).

## Minimal PipeWire Audio & AirPlay

- **PipeWire + WirePlumber**: `device/files/etc/pipewire/pipewire.conf.d/10-media-stick.conf` locks a 48 kHz clock (`quantum = 1024`) for `vc4hdmi`, while `device/files/etc/wireplumber/wireplumber.conf.d/50-media-stick-no-bt.conf` disables Bluetooth, V4L2, and libcamera monitors to keep audio daemon RSS minimal.
- **AirPlay (`airplay.service`)**: `device/files/usr/local/bin/airplay` wraps `uxplay`, acquires `CAST_AIRPLAY` from `mediastick-displayd`, and supports both screen mirroring and audio-only AirPlay streaming without touching Kodi until release.

## Shared Store, Quick Resume & Prefetch (`mediastick_store.py`)

- **SQLite WAL Store**: `device/files/usr/local/lib/media-stick/mediastick_store.py` provides two WAL-mode SQLite databases (stdlib-only, zero `xbmc` imports) with `SecretRefused` guards:
  - `StateStore` (`/var/lib/media-stick/state.db`): durable `resume`, `favourites`, `app_recent`, and `prefs` tables with idempotent migration from legacy JSON files.
  - `CacheStore` (`/var/cache/media-stick/cache.db`): `pages` and `api_cache` SWR caches bounded by a combined 8 MB LRU eviction budget, plus `ui_snapshots` (`MAX_SNAPSHOT_BYTES = 65536`) for Quick Resume.
- **Quick Resume & Playback-Gated Prefetch**: `quick_resume.py` saves debounced UI snapshots (`nav_stack`, section, filter, focused index/key, cards, `media_ref`) per app/profile so reopening YouTube or SWEET.TV restores state immediately. `prefetch.py` warms initial pages serially in one low-priority thread and pauses whenever Kodi is playing or `airplay`/`miracast`/`webapp` flags exist; `service.py` uses adaptive polling (`IDLE_POLL = 1.0s`, `PLAYING_POLL = 5.0s`).

## Native 1080p Skin (`skin.media-stick`)

- `device/kodi-addons/skin.media-stick/` replaces `skin.ftv` with a minimal native 1080p (`1920x1080`) skin tailored for the launcher, OSD, dialogs, and bundled mouse pointer (`ms-pointer.png`).
- `bootstrap.sh` symlinks Inter `.otf` weights from `fonts-inter` as `.ttf` into `/home/media/.kodi/media/Fonts/` and removes retired `skin.ftv` and unused helper add-ons.

## Panel v2 (`panel_core/` & ES-Module PWA)

- **Backend (`device/files/usr/local/bin/panel` + `panel_core/`)**:
  - `ws_hub.py`: pure-stdlib RFC 6455 WebSocket server at `/ws` pushing state updates and receiving 9-byte `<Bff` binary pointer frames (`move_by`, `click`, `right`, `scroll`).
  - `input_bus.py`: manages dual persistent `/dev/uinput` virtual devices (`media-stick-pointer` and `media-stick-kbd` without external `python3-evdev`), PipeWire `wpctl` volume commands, and minimal `wtype` UTF-8 fallback.
  - `screen_cap.py`: serves `/shot.jpg` as 960x540 JPEG (quality 75) via Kodi JSON-RPC + Pillow or `grim -t jpeg -q 70 -s 0.5 -` during `web-app` sessions (returning HTTP 409 during AirPlay/Miracast).
  - `kodi_bus.py`, `state_hub.py`, `static_files.py`, `tls_reload.py`: persistent JSON-RPC client, cached device/display state collector, ETag/gzip static asset server, and dynamic DuckDNS TLS reload.
  - `auth_pin.py`: optional 4-digit LAN Pairing PIN stored as PBKDF2-HMAC-SHA256 (`100_000` iterations, no plaintext) in `/var/lib/media-stick/pin.json`, issuing `HttpOnly; SameSite=Strict` HMAC-signed `ms_pin` cookies.
- **Frontend (`device/files/usr/local/share/media-stick/web/`)**: installable ES-module PWA (`manifest.webmanifest`, `sw.js`, `static/v2-boot.js`, `ws-client.js`, `trackpad.js`, `screen-v2.js`, `power-banner.js`, `diagnostics.js`) adding a relative-motion finger trackpad (works over HTTP without motion sensors), live screen viewer, standby/wake banner, and unit log diagnostics.

## Declarative OS Apply & Safe Self-Update

- **Reconciler (`device/os_apply.py`)**: syncs `device/files/` atomically, prunes orphaned files recorded in `/var/lib/media-stick/managed-files.json`, validates `/etc/sudoers.d/*` with `visudo -cf` before placement, ensures `/` has `noatime,commit=60` and `/home/media/.kodi/temp` `tmpfs` in `/etc/fstab`, and additively provisions `msadmin` (`sudo,systemd-journal`).
- **Self-Update & Rollback (`media-stick-update` + `media-stick-healthcheck`)**: `media-stick-update.timer` fetches `origin/main` (skipping while Kodi plays, cast/web-app owns the screen, a device lease is held, or a sign-in code is waiting). After running `bootstrap.sh`, it executes `/usr/local/bin/media-stick-healthcheck` (checks managed systemd units, `http://127.0.0.1/api/status` HTTP 200, and Kodi `JSONRPC.Ping` + `script.media-stick.home` enabled when Kodi owns the screen). Any failure resets to the prior commit, re-runs `bootstrap.sh`, and records `/var/lib/media-stick/bad-commit`.

## Owner Runbooks

### Activating GitHub Actions CI (`.github/workflows/ci.yml`)

The offline CI workflow template lives at `docs/ci-workflow.yml` so non-workflow automation never modifies `.github/workflows/`. To enable CI on pull requests and pushes to `main`:

1. From an owner shell with GitHub `workflow` scope:
   ```sh
   mkdir -p .github/workflows
   cp docs/ci-workflow.yml .github/workflows/ci.yml
   git add .github/workflows/ci.yml
   git commit -m "ci: activate offline make check workflow"
   git push origin main
   ```
2. Verify the `CI` workflow runs `make check` (`python3 tools/check.py`) cleanly on `ubuntu-latest`.

### Verifying `msadmin` SSH Before Tightening `media` Sudo

`device/os_apply.py` creates the `msadmin` admin user (`sudo,systemd-journal`), copies `/home/media/.ssh/authorized_keys`, and installs `/etc/sudoers.d/msadmin`. Meanwhile `device/files/etc/sudoers.d/media-stick` grants `media` only the specific `NOPASSWD` commands required by the panel and Kodi (`systemctl restart kodi.service`, `reboot`, `poweroff`, `web-app@*.service`, `media-stick-update.service`, `wifi-setup`, `media-stick-https`).

Before stripping any pre-existing broad `media` sudo drop-in (such as `/etc/sudoers.d/010_pi-nopasswd` on stock images) on a live device:

1. Verify SSH login and passwordless `sudo` as `msadmin`:
   ```sh
   ssh -i ~/.ssh/mediastick msadmin@mediastick.local sudo id
   ```
2. Confirm `/etc/sudoers.d/msadmin` and `/etc/sudoers.d/media-stick` both pass `visudo -c` and that `tools/doctor.sh` reports no failures.
3. Only after confirming `msadmin` access works, remove any legacy broad sudo file for `media` (retaining `/etc/sudoers.d/media-stick` so panel and web-app controls keep working).
