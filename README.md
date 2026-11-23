# media-stick

A Raspberry Pi 3B+ as a media stick for a plain TV: Kodi full screen, phone as the remote, media sent over the network. Everything installed on the device is described in this repository and applied by one script.

## From scratch

1. SD card in the Mac → `provisioning/make-card.sh disk8` (find the disk with `diskutil list external physical`).
2. Card in the Pi, HDMI to the TV, power on.
3. No network configured → the Pi raises its own Wi-Fi `mediastick-setup`; the TV shows its password and address. Join it from a phone, pick the home network, type its password. The same happens later whenever the device boots and cannot reach any network.
4. The Pi clones this repository and runs `device/bootstrap.sh`. Kodi is on screen in 10–15 minutes.

A network cable (or the Mac's Internet Sharing) also works and skips step 3.

## Day to day

| what | command |
|---|---|
| ship `main` to the device | `tools/deploy.sh` |
| ship an uncommitted edit | `tools/deploy.sh --local` |
| share the device with another session (take it before changing it) | `tools/device-lease.sh acquire`, `renew`, `release`, `status` (see AGENTS.md) |
| device health | `tools/doctor.sh` |
| what the TV shows, as a PNG | `tools/screenshot.sh out.png` |
| smoke test of sign-in and accounts on the device (needs the lease; `--live` starts and cancels a SWEET.TV sign-in on the TV) | `tools/smoke-accounts.sh [--live]` |
| remote, live screen, device info, Wi-Fi | http://mediastick.local |
| cast a video from a phone or PC | "Cast to device" / any UPnP-DLNA app |
| show an iPhone, iPad or Mac screen on the TV | Screen Mirroring → Media Stick (AirPlay by UxPlay, `airplay.service`; sound too); Kodi comes back when the phone stops |
| look at the SWEET.TV screen without an account | on the device `kodi-rpc Addons.ExecuteAddon '{"addonid":"script.media-stick.home","params":["sweettv","demo"]}'`: invented channels, marked DEMO, nothing is played |
| look at the YouTube screen without a key or an account | on the device `kodi-rpc Addons.ExecuteAddon '{"addonid":"script.media-stick.home","params":["youtube","demo"]}'`: invented videos, marked DEMO, nothing is played; a third word (`signin`, `needkey`, `empty`, `error`, `loading`) shows that card instead of the list |
| add a Kodi add-on for good | add its id to `device/kodi-addons.want`, run `python3 tools/kodi-addons-lock.py`, commit |
| apps on the home screen | none to set: any installed video or program add-on appears by itself, last used first |
| Kodi phone app (Kore, Official Kodi Remote, Yatse) | finds `mediastick` by itself; user `kodi`, password: `ssh … sudo grep KODI_WEB /etc/media-stick/secrets.env` |

## The page

http://mediastick.local is the one place to use the device from:

- hotspot up (no network) → Wi-Fi setup
- phone → remote (d-pad, playback, volume, text into Kodi search); screen, info and settings behind tabs
- wide screen → screen, remote, device info and settings side by side; the keyboard works as a remote

Anyone on the home network can open it, like a Chromecast. A browser on another site cannot press its buttons (every change needs a custom header that cross-site requests cannot carry).

## On the TV

Kodi opens on the media-stick launcher: full-screen wallpapers that change every 45 s, Bing photos cached daily (a few bundled ones when offline). A row of apps sits along the bottom, most recently used first; any installed video or program add-on shows up there, and Netflix and the other web apps are in it. Left on the first app opens the menu: Search, Accounts, Phone remote & network (with a QR code for the device's page, by IP address: many Android phones cannot resolve `mediastick.local`), Settings, Power. The clock and the remote address are top-right. The skin underneath is the Fire TV–style `skin.ftv`; after 30 s without a key the row of apps fades to 30 % and slides down, and the phone-remote QR code shrinks into the bottom-left corner so the phone can always reconnect; the next key brings everything back (and does nothing else). There is no screensaver: the Bing photos rotate behind the home screen. Kodi's own add-on catalogue (Settings, Add-ons) installs more.

SWEET.TV opens its own screen in the launcher's style instead of the plugin's plain list: a full-screen backdrop in the colour of the focused channel, a row of channel cards along the bottom, a narrow category menu on the left, and over the row what the focused channel shows now (title, times, progress, description, what is next) with buttons for the programme guide and for continuing an archived programme. It opens on the channels watched last. OK plays live, the menu key stars a channel, number keys jump to a channel number, Back goes Home. It reads the channel list the plugin keeps in `special://temp/channelList.json` while signed in; signed out it offers the sign-in. `tools/sweettv-shape.py <file>` prints that file's key structure (no values) to check the assumptions in `sweettv_data.py`.

YouTube opens its own screen too: sections on the left (Recommendations, Subscriptions, Watch later, History, Playlists, Search), a grid of video cards (thumbnail, title, channel, length) on the right, four to a row. OK plays, a playlist opens in place and Back goes up one level, a long list loads its next page by itself when the cursor comes within two rows of the end (a thin "Loading…" line says so; there is no "More videos" card), Search asks for words on the TV and shows the results on the same screen, Back from the top goes Home. The lists come from the YouTube add-on (JSON-RPC `Files.GetDirectory`), so they need what the add-on needs: a personal Google key and, for the account's own sections, a sign-in. Without the key the screen says so (a card, "On your phone open: Accounts > YouTube > Keys"; the keys are entered on the phone, where a wizard walks through getting them. The card shows the wizard's step: the panel writes it, without any secret, to `/run/media-stick/ytkeys.step.json` as `{"step", "total", "title", "hint", "updated"}` through the `step` action of `POST /api/accounts/ytkeys`; a file older than 30 minutes is ignored), signed out it offers the sign-in, and an empty or failed answer has its own card. The section paths and the fields read are assumptions about the add-on (see the header of `youtube_data.py`) until checked on a device with a key.

Netflix, Disney+, Prime Video and HBO Max are their websites in Chromium with Widevine, full screen, with Kodi stopped while they run (`web-app@<name>.service`). The page's remote types into the browser meanwhile; its Home button closes the browser and Kodi comes back. Expect 720p at most and a slower interface than Kodi: this is a Pi 3B+.

## Accounts

Signing in to YouTube or SWEET.TV in Kodi means a code and an address to type; YouTube asks for up to four codes in a row. Here the code comes as a link: the phone page shows it and the TV shows it as a QR, and either opens the provider's page on the phone with the code already typed in, so one tap on Continue replaces the typing. The phone page can also cancel a sign-in that is waiting.

The add-ons publish what they wait for into `/run/media-stick/signin` (RAM, one small JSON file per service; library `device/files/usr/local/lib/media-stick/mediastick_signin.py`), which the TV screen and the page read. The add-ons are the pinned third-party ones, so the few lines they need are not forked: `device/skin-overlay/<add-on>/` holds a changed copy of each file, every change fenced by `media-stick begin` / `end`, copied over the installed add-on by bootstrap after every (re)install. `tools/make-skin-overlays.py` rebuilds them from the pinned zips.

## Self-update

The device pulls `main` on the schedule in `device/config.env` (`UPDATE_SCHEDULE`, every 5 minutes while developing) and applies it; a failed update rolls back. Nothing is updated while Kodi is playing.

## Layout

| | |
|---|---|
| `provisioning/` | writing the card and the first-boot files; `cloud-init/user-data` never changes |
| `provisioning/firstboot/` | first boot: get online (cable, Wi-Fi, or setup hotspot), clone, hand over to bootstrap |
| `device/bootstrap.sh` | brings the Pi to the described state; safe to run again |
| `device/files/` | copied to the same paths on the device |
| `device/kodi-addons/script.media-stick.home/` | the launcher add-on: `resources/lib/` (`launcher.py` home, `apps.py`, `accounts*.py` and `signin.py` sign-in, `sweettv_app.py` the SWEET.TV window, `sweettv_data.py` its Kodi-free logic, `sweettv_state.py` favourites, `sweettv_files.py` the files it reads, `sweettv_demo.py` the demo channels), `resources/skins/default/1080i/` the windows |
| `device/kodi-addons/script.media-stick.home/` (YouTube) | `resources/lib/youtube_app.py` the window, `youtube_data.py` its Kodi-free logic, `youtube_state.py` last section and search, `youtube_cards.py` what a card says (lines cut to fit with `textfit.py`), `youtube_files.py` the add-on calls and files it reads (and the wizard's step file), `youtube_demo.py` the demo videos, `ytkeys.py` writes the Google keys into the add-on; the phone side of the key wizard is `device/files/usr/local/lib/media-stick/panel_ytkeys.py`, `panel_ytkeys_ui.py` and `mediastick_ytkeys.py`; `resources/skins/default/1080i/script-media-stick-youtube.xml` |
| `device/skin-overlay/` | files copied over installed add-ons: the sign-in changes to YouTube and SWEET.TV, the skin's pointer |
| `tools/` | run from a computer |

## Secrets

The repository holds names only (`secrets.example.env`). Values live on the device in `/etc/media-stick/secrets.env` (root:media, 0640). Wi-Fi passwords are typed by a person into the setup page and go straight into a root-only NetworkManager file. Access is by SSH key; password login is off.

Lost the key: put a new public key in a file named `authorized_keys` on the card's boot partition (FAT, readable on any computer); the Pi adds it at boot.
