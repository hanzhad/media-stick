# media-stick — notes for an agent

Read README.md first. This file is what it does not say.

## Reaching the device
- `ssh -i ~/.ssh/mediastick media@mediastick.local` (user `media`, passwordless sudo). Over the Mac's Internet Sharing it is usually 192.168.2.2; set `MEDIASTICK_HOST` if `.local` does not resolve.
- Every tool in `tools/` reads `MEDIASTICK_HOST` / `MEDIASTICK_KEY`.

## Changing things
- The device state is `device/bootstrap.sh` + `device/files/`. Change those, never hand-edit the Pi and leave it: a hand edit is lost on the next deploy.
- `bootstrap.sh` must stay idempotent: check before change, restart a service only when its file changed.
- Add-ons with an overlay (`device/skin-overlay/`: YouTube, SWEET.TV) are whole upstream files with fenced edits; never edit them by hand, edit the edit list in `tools/make-skin-overlays.py`. To bump one: change its line in `device/kodi-addons.want`, run `python3 tools/kodi-addons-lock.py`, then `python3 tools/make-skin-overlays.py` (it stops if upstream changed the file or an edit no longer applies; read the change, then `--accept-new-upstream`). Until the overlay is redone `tools/test-signin.py` fails: its header names the version it was made for. `make-skin-overlays.py --check` (needs the network) says whether the committed overlays equal a rebuild.
- `provisioning/cloud-init/user-data` only clones the repo and runs bootstrap. Do not add logic there; it reaches the device only when a card is rewritten.
- Quick fix loop: edit → `tools/deploy.sh --local` → `tools/doctor.sh` → `tools/screenshot.sh` → commit → `tools/deploy.sh`.
- The SWEET.TV screen (`sweettv_app.py` + `script-media-stick-sweettv.xml`) reads `special://temp/channelList.json`, whose shape is inferred from the plugin's source, not yet seen on a device: once a signed-in device has it, run `python3 tools/sweettv-shape.py <that file>` and compare with the header of `sweettv_data.py`. `tools/make-sweettv-art.py` draws its pictures (star, progress bars, demo logos); tests: `tools/test-sweettv-app.py`. The screen is laid out like the launcher (backdrop in the focused channel's colour, a row of cards along the bottom, a narrow category menu); what is said about a channel is in `sweettv_view.py`.

- The YouTube screen (`youtube_app.py` + `script-media-stick-youtube.xml`) asks the YouTube add-on for directories with JSON-RPC `Files.GetDirectory`; nothing in it has been seen on a device yet. To check: on a device with a personal Google key, ask `kodi-rpc Files.GetDirectory '{"directory":"plugin://plugin.video.youtube/","media":"video","properties":["title","thumbnail","art","plot","duration","runtime","file","studio","artist"]}'` and compare with the header of `youtube_data.py` (the section paths: `SECTIONS` there, found on that main page by their path words; the channel name: `studio`/`artist`; the key file: `api_keys.json` in the add-on's userdata, `keys_present`). `tools/make-youtube-art.py` draws its pictures (demo thumbnails, the no-thumbnail plate, the pill-and-bar strips of `youtube_cards.strip_variants()`); tests: `tools/test-youtube-app.py`. The "keys" card follows the phone's key wizard through `/run/media-stick/ytkeys.step.json` (`youtube_files.read_step`, parsed by `youtube_data.parse_step`; written by `mediastick_ytkeys.write_step` when the page posts the `step` action of `/api/accounts/ytkeys`; both sides drop a file older than 30 minutes): change the shape in both or neither, `tools/test-ytkeys.py` and `tools/test-youtube-app.py` each pin one side. A long list loads its next page by itself near the end; there is no "More videos" card. Lists in Kodi take the text colour of a selected item from `<selectedcolor>`, not `<textcolor>`: every label in the screen's list layouts sets both, and a white focus fill gets dark ones.
- The onboarding channel (`/run/media-stick/onboarding/<service>.json`, schema v1 in README, Accounts) has one writer library, `mediastick_onboarding.py`: every writer goes through `build()`, which cuts the texts, drops unknown fields and raises `Refused` for a secret (checked before the cut). Readers (`read()`, the TV's `onboarding_view.parse`) tolerate what they do not know. The sign-in publishes it from `mediastick_signin.publish/touch/begin` with the words of `mediastick_signin_guide.py`; the SWEET.TV steps 2 and 3 there are a guess, not yet seen on a device. The TV side is `onboarding_view.py` (pure: parse, step rows, chip layout), `onboarding_app.py` (the window, worker-thread poll) and the `ob` group of `script-media-stick-signin.xml` (the sign-in code, same document); chips are fixed slots moved from Python (`setPosition`/`setWidth`, top-level controls so the coordinates are absolute); the screens have not been seen on a TV (look with `onboarding,demo,signin|keys`). Pictures: `tools/make-onboarding-art.py`; tests: `tools/test-onboarding.py`, `tools/test-onboarding-tv.py`. The phone page's writer of the key wizard document is the other side: until it exists the key card falls back to `ytkeys.step.json`.

## Self-update
- The device pulls `main` on the schedule in `device/config.env` (`UPDATE_SCHEDULE`) and runs bootstrap; a failed bootstrap rolls back to the previous commit and leaves `/var/lib/media-stick/bad-commit`. It skips while Kodi is playing.
- So a push to `main` reaches the TV by itself. Push only what has passed `deploy.sh --local` + `doctor.sh`.
- Run it now: `ssh ... sudo media-stick-update --force`; log: `journalctl -u media-stick-update`.
- A `deploy.sh --local` edit survives until the next commit lands on `main`, then the update resets it.

## Using the device with another session
The device is one, and two sessions and the owner test on it: a restart, a deploy or the 5-minute self-update under someone's hands breaks what they look at. So the device has a lease: one holder, a stated reason, a time limit (default 30 min, at most 4 h). It is cooperative, kept in RAM (a reboot clears it), and an expired lease is free.
- Before you change anything (deploy, restart Kodi or panel, run bootstrap): `tools/device-lease.sh acquire --for "<name> [<session id>]" --why "<what for>" --ttl 30m` (`--wait 5m` queues behind a holder). Then run the tools with `MEDIASTICK_HOLDER="<name> [<session id>]"`: `deploy.sh` refuses without your live lease and each run extends it by 15 min. `tools/device-lease.sh renew|release|status`.
- Keep it short and release it when done. While it is held `media-stick-update` pauses (it logs "update … postponed"), and `doctor.sh` / `screenshot.sh` still work and print a NOTE line.
- Never steal. "device in use by X" means wait or ask X. `device-lease.sh steal --force` is the owner's; `MEDIASTICK_NO_LEASE=1` and `MEDIASTICK_NO_BASE_CHECK=1` are the owner's way past the checks.
- When another session works on the device, ship only `tools/deploy.sh --only <path>...` (just those files, nothing deleted), never `--local` (it replaces the whole tree and loses the other session's uncommitted edits). Every `deploy.sh` form refuses when your tree lacks commits from `origin/main`: `git pull --rebase` first.
- The first deploy that carries `media-stick-lease` installs it; until then the tools only warn.
- `tools/smoke-accounts.sh` (checks only) and `tools/smoke-accounts.sh --live` (starts a SWEET.TV sign-in on the TV and cancels it, so nobody may be looking at the TV) need the lease and a tree that contains `origin/main`, like `deploy.sh`. `tools/test-smoke-accounts.py` tests it against stub `ssh`/`curl`.

## Verifying
- `tools/doctor.sh` must show no FAIL lines.
- `tools/screenshot.sh` and look at the image: the UI should be on screen, not a console. Video on a hardware overlay plane can come out black in a screenshot — that is the capture, not playback.
- Kodi log: `~media/.kodi/temp/kodi.log`; service: `journalctl -u kodi -n 100`.

## Hardware limits (Pi 3B+, 1 GB)
- Hardware decode is H.264 only, up to 1080p. HEVC/H.265 and 4K are not targets.
- No desktop, and no browser running next to Kodi; memory is the bottleneck. The web services (Netflix and the like) run in Chromium only on demand, with Kodi stopped: `web-app@<name>.service` conflicts with `kodi.service` and starts it again on exit.

## Secrets
- Never commit a value. Names go in `secrets.example.env`; values in `/etc/media-stick/secrets.env` on the device.
- The repository is public.

## Commits
- `area: what changed` in lower case, imperative (areas: provisioning, device, kodi, tools, addons, docs).
