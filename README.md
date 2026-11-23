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
| show a Windows 11 PC screen on the TV | Win+K, "Media Stick" (Miracast over the network, `miracast.service`; sound too); see "Casting from Windows (Win+K)" |
| look at the SWEET.TV screen without an account | on the device `kodi-rpc Addons.ExecuteAddon '{"addonid":"script.media-stick.home","params":["sweettv","demo"]}'`: invented channels, marked DEMO, nothing is played |
| look at the YouTube screen without a key or an account | on the device `kodi-rpc Addons.ExecuteAddon '{"addonid":"script.media-stick.home","params":["youtube","demo"]}'`: invented videos, marked DEMO, nothing is played; a third word (`signin`, `needkey`, `empty`, `error`, `loading`) shows that card instead of the list |
| look at the onboarding screens (the phone does the action, the TV shows the hints) | on the device `kodi-rpc Addons.ExecuteAddon '{"addonid":"script.media-stick.home","params":["onboarding","demo","signin"]}'` (or `keys`): invented documents, nothing is written, Back closes |
| add a Kodi add-on for good | add its id to `device/kodi-addons.want`, run `python3 tools/kodi-addons-lock.py`, commit |
| apps on the home screen | none to set: any installed video or program add-on appears by itself, last used first |
| Kodi phone app (Kore, Official Kodi Remote, Yatse) | finds `mediastick` by itself; user `kodi`, password: `ssh … sudo grep KODI_WEB /etc/media-stick/secrets.env` |

## Casting from Windows (Win+K)

The stick is a Miracast receiver: on a Windows 11 PC press Win+K, pick "Media Stick", and the PC's screen and sound appear on the TV; Kodi comes back when the PC stops casting (Disconnect in the same panel). It is Miracast over infrastructure (Microsoft's MS-MICE): the PC finds the stick by Wi-Fi Direct discovery or mDNS and then talks to it over the home network, so **the PC and the stick must be on the same network** (the stick's Wi-Fi or its Ethernet, no guest network with client isolation). The stick never opens a Wi-Fi Direct group. The PC needs a Wi-Fi adapter whose driver supports Wireless Display: `netsh wlan show drivers` must say `Wireless Display Supported: Yes` (a graphics driver and a Wi-Fi driver line; "Yes" for both is best). One PC at a time, and not while an iPhone or Mac is mirroring. The program is `device/files/usr/local/bin/miracast`, its offline test `tools/test-miracast.py`; logs: `journalctl -u miracast`, `/run/media-stick/miracast.log` and `/run/media-stick/miracast-draw.log`.

## The page

http://mediastick.local is the one place to use the device from:

- hotspot up (no network) → Wi-Fi setup
- phone → remote (d-pad, playback, volume, text into Kodi search); screen, info and settings behind tabs
- wide screen → screen, remote, device info and settings side by side; the keyboard works as a remote

Anyone on the home network can open it, like a Chromecast. A browser on another site cannot press its buttons (every change needs a custom header that cross-site requests cannot carry).

## On the TV

Kodi opens on the media-stick launcher: full-screen wallpapers that change every 45 s, Bing photos cached daily (a few bundled ones when offline). The boot picture (`special://home/media/splash.png`, the one Plymouth and Kodi's splash show) is the layer under the wallpapers, so from power-on until the first photo fades in the TV shows only it. A row of apps sits along the bottom, most recently used first; any installed video or program add-on shows up there, and Netflix and the other web apps are in it. Left on the first app opens the menu: Search, Accounts, Phone remote & network (with a QR code for the device's page, by IP address: many Android phones cannot resolve `mediastick.local`), Settings, Power. The clock and the remote address are top-right. The skin underneath is the Fire TV–style `skin.ftv`; after 30 s without a key the row of apps fades to 30 % and slides down, and the phone-remote QR code shrinks into the bottom-left corner so the phone can always reconnect; the next key brings everything back (and does nothing else). There is no screensaver: the Bing photos rotate behind the home screen. Kodi's own add-on catalogue (Settings, Add-ons) installs more.

SWEET.TV opens its own screen in the launcher's style instead of the plugin's plain list: a full-screen backdrop in the colour of the focused channel, a row of channel cards along the bottom, a narrow category menu on the left, and over the row what the focused channel shows now (title, times, progress, description, what is next) with buttons for the programme guide and for continuing an archived programme. It opens on the channels watched last. OK plays live, the menu key stars a channel, number keys jump to a channel number, Back goes Home. It reads the channel list the plugin keeps in `special://temp/channelList.json` while signed in; signed out it offers the sign-in. `tools/sweettv-shape.py <file>` prints that file's key structure (no values) to check the assumptions in `sweettv_data.py`.

YouTube opens its own screen too: sections on the left (Recommendations, Subscriptions, Watch later, History, Playlists, Search), a grid of video cards (thumbnail, title, channel, length) on the right, four to a row. OK plays, a playlist opens in place and Back goes up one level, a long list loads its next page by itself when the cursor comes within two rows of the end (a thin "Loading…" line says so; there is no "More videos" card), Search asks for words on the TV and shows the results on the same screen, Back from the top goes Home. The lists come from the YouTube add-on (JSON-RPC `Files.GetDirectory`), so they need what the add-on needs: a personal Google key and, for the account's own sections, a sign-in. Without the key the screen says so (a card, "On your phone open: Accounts > YouTube > Keys"; the keys are entered on the phone, where a wizard walks through getting them. The card shows the wizard's step: the panel writes it, without any secret, to `/run/media-stick/ytkeys.step.json` as `{"step", "total", "title", "hint", "updated"}` through the `step` action of `POST /api/accounts/ytkeys`; a file older than 30 minutes is ignored), signed out it offers the sign-in, and an empty or failed answer has its own card. A Google account with no YouTube channel has no subscriptions, Watch later or playlists (the add-on answers Channel not found): when mediastick_ytchannel.peek says so, those three sections say it on their card, the Accounts screen adds No YouTube channel on this account under the profile, and the finished YouTube sign-in carries a hint for the phone; recommendations and search are unchanged, and nothing is claimed while the answer is unknown. The section paths and the fields read are assumptions about the add-on (see the header of `youtube_data.py`) until checked on a device with a key.

Netflix, Disney+, Prime Video and HBO Max are their websites in Chromium with Widevine, full screen, with Kodi stopped while they run (`web-app@<name>.service`). The page's remote types into the browser meanwhile; its Home button closes the browser and Kodi comes back. Expect 720p at most and a slower interface than Kodi: this is a Pi 3B+.

## Accounts

Signing in to YouTube or SWEET.TV in Kodi means a code and an address to type; YouTube asks for up to four codes in a row. Here the code comes as a link: the phone page shows it and the TV shows it as a QR, and either opens the provider's page on the phone with the code already typed in, so one tap on Continue replaces the typing. That holds for the pages that take the code in the address (YouTube own activate page, SWEET.TV); the link is otherwise the page or complete link (verification_url_complete) the provider answer gives, with nothing added, so a personal Google client (google.com/device) gets that page in the QR and the screen says to type the code there. The phone page can also cancel a sign-in that is waiting. SWEET.TV has one sign-in button ("Войти"), with the same screens as YouTube, but its code is waited for six hours, not ten minutes: a reseller such as Friendly Share connects the subscription within its working hours (14:00 to 00:00) after the person pastes the code into its page. The add-on checks gently (3 s, then 12 s after ten minutes) and waits out a network that drops; the code is never replaced by itself. If SWEET.TV answers that the code is expired (any `result` with EXPIRED in it), or nothing answers for half an hour, the sign-in ends as failed with `reason` `expired` and the phone says «Код устарел, нажмите «Обновить код»». "Обновить код" (on the sheet while waiting, after a second tap; on the card and the end sheet once it ran out) stops the sign-in and starts one with a new code (`/api/accounts/renew`). The old `partner` mode (no QR, its own TV layout) is still understood by the add-on and the TV but nothing asks for it: the panel refuses it.

The add-ons publish what they wait for into `/run/media-stick/signin` (RAM, one small JSON file per service; library `device/files/usr/local/lib/media-stick/mediastick_signin.py`), which the TV screen and the page read. The add-ons are the pinned third-party ones, so the few lines they need are not forked: `device/skin-overlay/<add-on>/` holds a changed copy of each file, every change fenced by `media-stick begin` / `end`, copied over the installed add-on by bootstrap after every (re)install. `tools/make-skin-overlays.py` rebuilds them from the pinned zips.

The phone and the TV share one more picture, the onboarding channel: while a flow needs the phone (the sign-in above, the Google key wizard), whoever runs it writes `/run/media-stick/onboarding/<service>.json` (RAM; library `device/files/usr/local/lib/media-stick/mediastick_onboarding.py`, tests `tools/test-onboarding.py`). The TV draws it big (a dim backdrop and one card: the steps with done, now and to-come marks, the QR and code of a sign-in, or the rows of Google-page chips, a warning and status badges of a key wizard), the phone page draws it as its sheet; neither asks the other anything. The sign-in writes it from `mediastick_signin.publish` (`mediastick_signin_guide.py` has the words; the old `signin/<service>.json` is unchanged); the key card reads `youtube.json` with `flow` `keys` and falls back to `ytkeys.step.json`. Schema v1, all texts one line, longer ones are cut and longer lists lose their tail:

```
{"v": 1, "service": "youtube", "flow": "signin" | "keys" | <other>,
 "state": "active" | "done" | "failed" | "cancelled",
 "kicker": {"tv", "phone"},                       optional, <= 60
 "title": {"tv", "phone"},                        <= 80
 "step": 2, "steps": [{"id", "tv", "phone"}],      1-based; <= 8 steps, text <= 120
 "code": "KQX-7MD-P4W", "link": "https://...",    sign-in only
 "action": {"kind": "link"|"paste"|"wait", "label", "url"},
 "hint": {"tv", "phone"},                         <= 160
 "chips": [[{"t", "s": "done"|"now"|"todo"}]],     TV only: <= 4 rows, <= 12 chips, text <= 48
 "items": [{"id", "label", "s": "ok"|"wait"}],   TV only: <= 6 badges, never a value
 "warn": {"tv", "phone"},                         <= 160
 "updated": <unix>, "expires": <unix>}             expires is mandatory; after it the file is nothing
```

`service` is `[a-z0-9_-]{1,32}`; the file is written whole and renamed into place (mode 0644). The library refuses a document that holds a Google API key (`AIza...`), a client secret (`GOCSPX-...`), a client id (`...apps.googleusercontent.com`), an OAuth token or a long token-like word, and reads a file with any of them as nothing; unknown fields are kept on read, a missing, corrupt, expired or other-version file reads as nothing. `MEDIASTICK_ONBOARDING_DIR` moves the directory (tests).

## Self-update

The device pulls `main` on the schedule in `device/config.env` (`UPDATE_SCHEDULE`, every 5 minutes while developing) and applies it; a failed update rolls back. Nothing is updated while Kodi is playing.

## Layout

| | |
|---|---|
| `provisioning/` | writing the card and the first-boot files; `cloud-init/user-data` never changes |
| `provisioning/firstboot/` | first boot: get online (cable, Wi-Fi, or setup hotspot), clone, hand over to bootstrap |
| `device/bootstrap.sh` | brings the Pi to the described state; safe to run again |
| `device/files/` | copied to the same paths on the device |
| `device/kodi-addons/script.media-stick.home/` | the launcher add-on: `resources/lib/` (`launcher.py` home, `apps.py`, `accounts*.py` and `signin.py` sign-in, `sweettv_app.py` the SWEET.TV window, `sweettv_data.py` its Kodi-free logic, `sweettv_state.py` favourites, `sweettv_files.py` the files it reads, `sweettv_demo.py` the demo channels, `onboarding_app.py` the onboarding window and `onboarding_view.py` its Kodi-free logic, `onboarding_files.py` the files it reads, `onboarding_demo.py` the demo documents), `resources/skins/default/1080i/` the windows |
| `device/kodi-addons/script.media-stick.home/` (YouTube) | `resources/lib/youtube_app.py` the window, `youtube_data.py` its Kodi-free logic, `youtube_state.py` last section and search, `youtube_cards.py` what a card says (lines cut to fit with `textfit.py`), `youtube_files.py` the add-on calls and files it reads (and the wizard's step file), `youtube_demo.py` the demo videos, `ytkeys.py` writes the Google keys into the add-on; the phone side of the key wizard is `device/files/usr/local/lib/media-stick/panel_ytkeys.py`, `panel_ytkeys_ui.py` and `mediastick_ytkeys.py`; `resources/skins/default/1080i/script-media-stick-youtube.xml` |
| `device/skin-overlay/` | files copied over installed add-ons: the sign-in changes to YouTube and SWEET.TV, the skin's pointer |
| `tools/` | run from a computer |

## Secrets

The repository holds names only (`secrets.example.env`). Values live on the device in `/etc/media-stick/secrets.env` (root:media, 0640). Wi-Fi passwords are typed by a person into the setup page and go straight into a root-only NetworkManager file. Access is by SSH key; password login is off.

Lost the key: put a new public key in a file named `authorized_keys` on the card's boot partition (FAT, readable on any computer); the Pi adds it at boot.
