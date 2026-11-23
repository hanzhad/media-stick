# Handoff — 2026-11-21

Where the work stopped and what is left. Read `README.md` and `AGENTS.md` first; this file is only what they do not say. Delete this file when every part below is done or moved elsewhere.

## State right now

- Raspberry Pi 3B+, Raspberry Pi OS Lite 64-bit (Debian 13 trixie, image 2026-10-06), hostname `mediastick`, user `media`.
- On the home Wi-Fi `TheHole`, `192.168.1.14`, also `mediastick.local`. The Ethernet cable and the Mac's Internet Sharing are no longer needed.
- Kodi 21.3 runs full screen from `kodi.service` (GBM, no desktop). Inputstream adaptive/ffmpegdirect enabled. No content sources yet.
- The page `http://mediastick.local` (`device/files/usr/local/bin/panel`, `panel.service`, port 80): phone remote, live screen, device info, settings, Wi-Fi change. Tested on phone width and on 1400×900.
- Self-update: `media-stick-update.timer` pulls `main` every 5 minutes (`UPDATE_SCHEDULE` in `device/config.env`), runs bootstrap, rolls back on failure. Tested: a pushed commit landed on its own 25 s after the timer fired. **Everything pushed to `main` reaches the TV within 5 minutes.**
- Not on a TV yet: without a display the Pi gives 1024×768 (no EDID); 1080p comes from the real TV.

## Getting access from another machine

- The SSH key is `~/.ssh/mediastick` on the first Mac. A passphrase-protected copy is on the owner's Google Drive (`mediastick-backup`). On the new machine: download it to `~/.ssh/mediastick`, `chmod 600`, then `ssh -i ~/.ssh/mediastick media@mediastick.local`. The passphrase is asked on use.
- Or add a new key without the old one: put its public key into a file named `authorized_keys` on the SD card's boot partition and reboot the Pi (`mediastick-bootkeys.service` adds it).
- Git identity for this repository: `user.name hanzhad`, `user.email 34131296+hanzhad@users.noreply.github.com`, SSH-signed commits. Commit messages: `area: what changed`, **no `Co-Authored-By` trailer**.

## What is left, in parts

Each part stands alone; close or re-scope it separately.

### A. Rewrite the page (`panel`)

The current page works but was a first pass; the owner wants the UI redone.

- No `confirm()` / `alert()` anywhere: the Claude app's built-in browser refuses them silently, so a button that asks first does nothing there. Two-step buttons or inline confirmation instead.
- The screen is captured only while it is actually being looked at, and slower. Today every open wide-screen tab drives Kodi screenshots continuously (Kodi at ~125% CPU, Pi 35 → 41 °C).
- Status must not call `sudo wifi-setup status` every 5 s per tab: that wakes systemd/dbus/polkit (~40% CPU). Read Wi-Fi state without sudo (`nmcli` read access is enough).
- Keep: one page; hotspot → Wi-Fi setup, phone → remote with the rest behind tabs, wide screen → everything at once; `X-Panel: 1` header on every change and the Host check.
- Done when: `grep -nE 'confirm\(|alert\(' device/files/usr/local/bin/panel` is empty; with one wide tab open for a minute, `top` shows Kodi under ~30% CPU while idle; no `sudo` in the status path.

### B. Content sources

- SWEET.TV (channels + archive) under the owner's own subscription, as a Kodi add-on in `addons/`. Credentials only in `/etc/media-stick/secrets.env` on the device, names in `secrets.example.env`.
- HDRezka: not written by us (a piracy site). The owner may install a third-party add-on by hand.
- Done when: a SWEET.TV channel plays at 1080p H.264 and `vcgencmd get_throttled` stays `0x0` during playback.

### C. TV control and standby

- HDMI-CEC through Kodi: TV on and input switch when the Pi wakes, TV to standby when it sleeps; the TV remote drives Kodi. Needs CEC enabled in the TV menu (Anynet+/SimpLink/Bravia Sync…).
- Soft standby (the Pi has no real sleep and no Wake-on-LAN): Kodi idle, HDMI off, CPU governor down, Wi-Fi up; wake from a button on the page.
- Done when: standby and wake from the page switch the real TV off and on.

### D. Clean-card test (last)

- `provisioning/make-card.sh <diskN>` onto a card, boot it with no cable and no saved Wi-Fi.
- Expect: TV shows the hotspot `mediastick-setup`, its password and address immediately (no wait when nothing is configured); a phone joins, the page pops up, the home network is chosen; the Pi clones the repo and runs bootstrap; Kodi on screen in 10–15 min.
- Never run end to end yet. `firstboot.sh` and the `portal` mode of `wifi-setup` are untested on a live device; the captive-portal redirect is untested.

### E. Loose ends

- `UPDATE_SCHEDULE` back to once a day (`*-*-* 04:00`) when development slows.
- Wi-Fi regulatory domain is unset (`00`); `TheHole` also broadcasts on 5 GHz channel 100. Country is probably PL — ask, then set it (the Wi-Fi form already takes a country).
- Fan: two wires on pins 4 (5 V) and 6 (GND), always on, not switchable without a transistor. Measure temperature during a film with no page open; if under ~65 °C the owner may remove the fan, otherwise a MOSFET module on GPIO14 plus `dtoverlay=gpio-fan`.
- Claude Code reads `CLAUDE.md`, not `AGENTS.md`; the owner chose `AGENTS.md`. If agent notes are not being picked up, ask before adding anything.

### F. Idea, not started: the box as an MCP server for chat assistants

The owner's idea (2026-11-24, parked): say to Claude or ChatGPT «включи на ТВ <фильм>» and the assistant finds it and starts it on the TV.
- Tools it would offer: search across SWEET.TV (channels, archive, films, shows; needs the SWEET.TV session's `/api/sweettv/*`) and YouTube; play an item on the TV; what is playing; pause, volume, stop. Built on the panel's existing APIs.
- Reachability decides the shape: `mediastick-ivlsy.duckdns.org` resolves to the LAN address (it exists for the TLS certificate), so nothing outside the home reaches the box.
  - From the computer: a local MCP server (stdio) for Claude Desktop / Claude Code on the home PC, talking to the box over the LAN. Nothing exposed; small.
  - From the phone (Claude or ChatGPT apps call MCP servers from their cloud): needs an outbound tunnel from the box (Cloudflare Tunnel or Tailscale Funnel, no router port forward) exposing only the MCP endpoint, with real authentication (OAuth), since whoever has the URL controls the TV.
- Not HDRezka (see B).

## Things learned the hard way

- A `bytes` literal with Cyrillic in it is a SyntaxError — keep page HTML as `str` and `.encode()`.
- `mediastick.local` resolves to IPv6 first on macOS; servers must listen dual-stack (`::` with `IPV6_V6ONLY=0`).
- Chrome on macOS needs System Settings → Privacy & Security → Local Network enabled, or LAN addresses fail with `ERR_ADDRESS_UNREACHABLE`.
- Kodi screenshots: `ffmpeg -f kmsgrab` gives tiled garbage on vc4; use Kodi's own screenshot via JSON-RPC (`kodi-rpc`), written to `/run` not the SD card. Video on the overlay plane may come out black.
- `wifi-setup connect` once reported success because the cable was online; success is now `wlan0` up on the `home-wifi` profile, keep it that way.
- Bootstrap restarts a service only when its unit or its same-named program changed; a new service needs to be added to the enable/restart lists in `device/bootstrap.sh`.
- `apt-get install --no-install-recommends kodi` leaves out the skin fonts; they are listed explicitly in bootstrap.
