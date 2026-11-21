# media-stick — notes for an agent

Read README.md first. This file is what it does not say.

## Reaching the device
- `ssh -i ~/.ssh/mediastick media@mediastick.local` (user `media`, passwordless sudo). Over the Mac's Internet Sharing it is usually 192.168.2.2; set `MEDIASTICK_HOST` if `.local` does not resolve.
- Every tool in `tools/` reads `MEDIASTICK_HOST` / `MEDIASTICK_KEY`.

## Changing things
- The device state is `device/bootstrap.sh` + `device/files/`. Change those, never hand-edit the Pi and leave it: a hand edit is lost on the next deploy.
- `bootstrap.sh` must stay idempotent: check before change, restart a service only when its file changed.
- `provisioning/cloud-init/user-data` only clones the repo and runs bootstrap. Do not add logic there; it reaches the device only when a card is rewritten.
- Quick fix loop: edit → `tools/deploy.sh --local` → `tools/doctor.sh` → `tools/screenshot.sh` → commit → `tools/deploy.sh`.

## Verifying
- `tools/doctor.sh` must show no FAIL lines.
- `tools/screenshot.sh` and look at the image: the UI should be on screen, not a console. Video on a hardware overlay plane can come out black in a screenshot — that is the capture, not playback.
- Kodi log: `~media/.kodi/temp/kodi.log`; service: `journalctl -u kodi -n 100`.

## Hardware limits (Pi 3B+, 1 GB)
- Hardware decode is H.264 only, up to 1080p. HEVC/H.265 and 4K are not targets.
- Do not add a desktop or a browser-based UI on the TV; memory is the bottleneck.

## Secrets
- Never commit a value. Names go in `secrets.example.env`; values in `/etc/media-stick/secrets.env` on the device.
- The repository is public.

## Commits
- `area: what changed` in lower case, imperative (areas: provisioning, device, kodi, tools, addons, docs).
