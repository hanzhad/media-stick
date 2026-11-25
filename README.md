# media-stick

A Raspberry Pi 3B+ as a media stick for a plain TV: Kodi full screen, phone as the remote, media sent over the network. Everything installed on the device is described in this repository and applied by `device/bootstrap.sh` and `device/os_apply.py` (see [docs/architecture.md](docs/architecture.md)).

## Media Stick v2 Highlights

- **Native 1080p Skin & Quick Resume**: lightweight `skin.media-stick` plus SQLite WAL snapshots (`mediastick_store.py`) that restore section, filter, navigation stack, and focus when reopening YouTube or SWEET.TV, alongside playback-gated background prefetch.
- **Panel v2 PWA, Finger Trackpad & WebSocket Remote**: installable ES-module PWA served from the device with persistent RFC 6455 `/ws` updates, a relative-motion finger trackpad over HTTP (no motion sensors required), 960x540 JPEG screen preview, and optional 4-digit LAN Pairing PIN.
- **Display Arbitrator & CEC Standby/Wake**: `mediastick-displayd` serializes Kodi, AirPlay, Miracast, Chromium web apps, and `STANDBY` (HDMI-CEC TV standby/wake, KMS DPMS, CPU governor scaling, and Miracast P2P pause during playback/hotspot).
- **Minimal PipeWire & Audio-Only AirPlay**: 48 kHz PipeWire + trimmed WirePlumber (Bluetooth/camera monitors disabled) backing HDMI audio, `wpctl` volume, and screen-mirroring or audio-only AirPlay via UxPlay.
- **Offline Checks & Safe Updates**: run `make check` (`python3 tools/check.py`) for `shellcheck`, `xmllint`, `py_compile`, and all unit suites; on the Pi, `media-stick-update` validates updates with `media-stick-healthcheck` and rolls back on failure, backed by `zram0` swap and tmpfs caches. See [docs/architecture.md](docs/architecture.md) for details and owner runbooks.

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

Kodi opens on the media-stick launcher: full-screen wallpapers that change every 5 min, Bing photos cached daily (a few bundled ones when offline). The boot picture (`special://home/media/splash.png`, the one Plymouth and Kodi's splash show) is the layer under the wallpapers, so from power-on until the first photo fades in the TV shows only it. A row of apps sits along the bottom, most recently used first; any installed video or program add-on shows up there, and Netflix and the other web apps are in it. Left on the first app opens the menu: Search, Accounts, Phone remote & network (with a QR code for the device's page, by IP address: many Android phones cannot resolve `mediastick.local`), Settings, Power. The clock and the remote address are top-right. The skin underneath is the native 1080p `skin.media-stick`; after 30 s without a key the row of apps fades to 30 % and slides down, and the phone-remote QR code shrinks into the bottom-left corner so the phone can always reconnect; the next key brings everything back (and does nothing else). There is no screensaver: the Bing photos rotate behind the home screen. Kodi's own add-on catalogue (Settings, Add-ons) installs more.

SWEET.TV opens its own Netflix-style screen (`sweettv_app.py` + `script-media-stick-sweettv.xml`) instead of the plugin's plain list: a 7-section left rail (Search, Continue, Favourites, Shows, Series, Movies, TV Channels), a hero banner for the focused card, filter chips (`sweettv_shelf.py`), a 4x2 card grid, and modals (`sweettv_guide.py`) for channel guides, show episodes, and VOD series seasons. Live channels come from the plugin's `special://temp/channelList.json` (read once per change; signed out it offers the sign-in; `tools/sweettv-shape.py <file>` prints its key structure without values). Shows (`GetCollections(type=7)` + EPG shows), Series, Movies, VOD details, and Search (`SearchService/Search.json`, `SearchService/GetTop.json`) come from `api.sweet.tv` through `mediastick_sweetapi` and paginated `page_cache` slices (`sweettv_pages.py`, VERSION 4, slices <= 50 items); signing out drops `sweettv:*`. Continue and Favourites read the stick's per-app SWEET.TV local state (`mediastick_resume`: `positions.json` and `sweettv-favourites.json`), and number keys jump to channels.

YouTube opens its own screen too: sections on the left (Recommendations, Subscriptions, Watch later, History, Playlists, Search), a grid of video cards (thumbnail, title, channel, length) on the right, four to a row. OK plays, a playlist opens in place and Back goes up one level, a long list loads its next page by itself when the cursor comes within two rows of the end (a thin "Loading…" line says so; there is no "More videos" card), Search asks for words on the TV and shows the results on the same screen, Back from the top goes Home. The lists come from the YouTube add-on (JSON-RPC `Files.GetDirectory`), so they need what the add-on needs: a personal Google key and, for the account's own sections, a sign-in. Without the key the screen says so (a card, "On your phone open: Accounts > YouTube > Keys"; the keys are entered on the phone, where a wizard walks through getting them. The card shows the wizard's step: the panel writes it, without any secret, to `/run/media-stick/ytkeys.step.json` as `{"step", "total", "title", "hint", "updated"}` through the `step` action of `POST /api/accounts/ytkeys`; a file older than 30 minutes is ignored), signed out it offers the sign-in, and an empty or failed answer has its own card. A Google account with no YouTube channel has no subscriptions, Watch later or playlists (the add-on answers Channel not found): when mediastick_ytchannel.peek says so, those three sections say it on their card, the Accounts screen adds No YouTube channel on this account under the profile, and the finished YouTube sign-in carries a hint for the phone; recommendations and search are unchanged, and nothing is claimed while the answer is unknown. The section paths and the fields read are assumptions about the add-on (see the header of `youtube_data.py`) until checked on a device with a key.

Netflix, Disney+, Prime Video and HBO Max are their websites in Chromium with Widevine, full screen, with Kodi stopped while they run (`web-app@<name>.service`). The page's remote types into the browser meanwhile; its Home button closes the browser and Kodi comes back. Expect 720p at most and a slower interface than Kodi: this is a Pi 3B+.

## Accounts

Signing in to YouTube or SWEET.TV in Kodi means a code and an address to type; YouTube asks for up to four codes in a row. Here the code comes as a link: the phone page shows it and the TV shows it as a QR, and either opens the provider's page on the phone with the code already typed in, so one tap on Continue replaces the typing. That holds for the pages that take the code in the address (YouTube own activate page, SWEET.TV); the link is otherwise the page or complete link (verification_url_complete) the provider answer gives, with nothing added, so a personal Google client (google.com/device) gets that page in the QR and the screen says to type the code there. The phone page can also cancel a sign-in that is waiting. SWEET.TV has one sign-in button ("Войти"), with the same screens as YouTube, but its code is waited for six hours, not ten minutes: a reseller such as Friendly Share connects the subscription within its working hours (14:00 to 00:00) after the person pastes the code into its page. The add-on checks gently (3 s, then 12 s after ten minutes) and waits out a network that drops; the code is never replaced by itself. If SWEET.TV answers that the code is expired (any `result` with EXPIRED in it), or nothing answers for half an hour, the sign-in ends as failed with `reason` `expired` and the phone says «Код устарел, нажмите «Обновить код»». "Обновить код" (on the sheet while waiting, after a second tap; on the card and the end sheet once it ran out) makes the running add-on ask SWEET.TV for a new code in the same run (`/api/accounts/renew` leaves a `renew` request file next to the state; the TV screen and the sheet just follow the new code), and only with nothing waiting starts a sign-in; a TV screen that still shows the result of the last one is waited for, not turned away. SWEET.TV's check answer `STARTED` means "not yet" and is not logged. The old `partner` mode (no QR, its own TV layout) is still understood by the add-on and the TV but nothing asks for it: the panel refuses it.

The YouTube profile on the TV has one source of truth, the add-on's `current_user`: the phone's list of profiles (its check mark), its messages and the TV's YouTube window all follow it. `/api/accounts/switch` answers only once the add-on shows the target profile as current (`{ok, current}`; after 8 s a 504 «Телевизор не переключил профиль. Посмотрите на ТВ.»); the tapped row says «переключаю…» (the others wait) and «На ТВ: X» is said from that answer or from a later poll, never before. The window (`youtube_app.py`) looks at the current profile id every 2 s and, when it differs from the one it loaded with, clears its cache and circle and loads the section again. Launching YouTube from the launcher opens straight on that profile when it is signed in (no «Who's watching»); when it is not, or none is current, the picker is shown as before. The picker stays reachable on purpose: OK on the account's circle at the top right of the YouTube window (Up from the section rail, the grid or the card's button, Right of the search types) or the Accounts row «Switch profile or add one»; the window then follows the profile picked.

A normal sign-in has one sheet on the phone, the onboarding one (`#ob-sheet`), and one counter. YouTube asks Google for a code for each of the add-on's token types (up to four) and Google asks the person to approve each, which looks like the same action repeated: so the kicker says "YouTube · подтверждение 2 из 3" (TV: "Approval 2 of 3"), the phone's hint says once why Google asks again, and the three steps are the recipe of every approval, not a progress bar. `round` of `rounds` come from the YouTube overlay (the token slots that still lack a token, minus the ones Google gave no code for) through `mediastick_signin.publish`, which also says `prefilled` (the link carries the code): a link that does not (google.com/device) tells the person to type the code. The old code sheet (`#acc-sheet`) is only the fallback for a sign-in with no onboarding document (partner mode, no library); a new code replaces the old one in the same sheet, un-minimizes it and buzzes, and the sheet has «Отмена» and, for SWEET.TV, «Обновить код».

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

## SWEET.TV API

What the phone page asks of the stick for SWEET.TV beyond the channel list: `device/files/usr/local/lib/media-stick/panel_sweettv.py` (routes `/api/sweettv/...`, handed over by `panel` in two lines; POSTs carry `X-Panel: 1` like all others) and, for what is playing now and the seek, `panel_watch.py` (`/api/watch/...`). Times are unix seconds, ids are strings of digits, errors are `{"error": "text"}` with 4xx/409/503, every text a person reads comes out of the dictionary (below). Tests: `tools/test-sweetlive.py`.

Going back on a live channel. A live SWEET.TV stream is a window of about a minute in Kodi, so Kodi's own seek back cannot go further. What can: the archive of the programme on now (the add-on's `playvid/<channel>|<programme id>`) started at `now - start - step` seconds, never before the start. One function decides that, `mediastick_sweetlive.plan`, for everybody who asks: the TV remote (the add-on's `service.py` gets Kodi's seek callback `onPlayBackSeek` with a negative offset, and `onPlayBackResumed` after a pause longer than `PAUSE_LIMIT` = 30 s), the phone's -10 and the way back to live. A channel with no archive (`catchup` false, or the programme not `available`) says so ("No archive for this channel": a TV notification, a `note` on the phone) and keeps Kodi's ordinary seek inside the window. The start place rides in the plugin URL (`playvid/5|51?ms_start=3590`); the add-on gives the item the place as its `ResumeTime` property (Kodi ignores `StartOffset` of a plugin-resolved item; a resume point it starts from) and the programme's real length as `TotalTime`. That is not trusted alone: the add-on's service, on Kodi's `onAVStarted`, reads the entry the plugin wrote (below; or, when the player gives the plugin path it was asked to open, the `ms_start` of that path) and, in a thread, until the playback shows its length (at least `MIN_TOTAL` = 30 s), seeks with `Player.seekTime` to the place (not past the length: a programme still on is as long as it has been so far); it looks that the player landed (within `SEEK_TOLERANCE` = 8 s) and tries again, three times at most, `SEEK_RETRY` = 3 s apart, for at most `SEEK_WAIT` = 60 s, and leaves a player that began at the place alone (`mediastick_sweetlive.follow`, `seek_step`; it is the long-lived service that does this, the plugin process ends after `setResolvedUrl`). The red remote key, in full-screen video, runs the add-on's `/golive` route: an archived programme's channel live again (nothing on anything else).

```
GET  /api/watch/now          {playing, title, channel, live, cid, epg, programme, can_rewind, go_live, time, total, speed, ...}
     title      the channel's name (a programme's text is `programme`), never the bare channel number
     live       true for a live channel only: the page shows "Live", no length, no bar
     cid, epg   the SWEET.TV channel and programme ids ("" when it is something else; epg "" is live)
     programme  the programme on now (live) or the one playing (archive), "" when the list does not know it
     can_rewind live and the channel has an archive: -10 does something
     go_live    an archived programme is playing: show "Back to live"
     total      an archive: the programme's real length (live: Kodi's window, to be ignored)
POST /api/watch/ctl {"op": "seek", "by": -10}
     live with an archive   {"ok": true, "switched": "archive", "epg", "offset"}   the archive plays, no seek was made
     live without one       {"ok": true, "switched": "", "note": "<text>"}          a seek inside the window was made; show the note
     anything else          {"ok": true}                                             as before
GET  /api/sweettv/home
     {"ok": true, "continue": [...], "favourites": [...], "counts": {"continue", "favourites", "channels"},
      "labels": {...}, "quality": "720p"|"1080p"|"unlimited"}
GET  /api/sweettv/channels
     {"ok": true, "channels": [{"id", "name", "icon", "cats", "is_fast_channel", "archive", "favourite", "now", "next"}],
      "categories": [{"id", "name"}]}
GET  /api/sweettv/guide?cid=<id>
     {"ok": true, "cid", "name", "archive", "archive_days", "now",
      "past":    [{"id", "title", "start", "stop", "archive", "resume", "watched"}],   over, newest first; archive: can be played from the archive
      "current": {"id", "title", "start", "stop", "archive", "resume", "watched"} | null,   on now; archive: can be played from its start
      "next":    [{"id", "title", "start", "stop"}],              to come, soonest first; information only, not playable
      "counts": {"past", "next"}}
     400 wrong id, 404 the channel is not in the list. Play an entry with POST play below.
     The list holds what the add-on asked SWEET.TV for (epg_limit_prev 10, epg_limit_next 100): about ten past programmes,
     the one on now and up to a hundred to come (a channel with no guide at all has none); more past needs /api/sweettv/day.
POST /api/sweettv/play {"cid", "epg"?, "at"?, "from_start"?}  or  {"movie_id", "episode_id"?, "owner_id"?, "start"?}
     no epg                 the live channel
     epg + at "start"       the archive from the beginning (default; also when from_start is true)
     epg + at "now"         from the place the live stream is at (only for the programme on now)
     epg + at <seconds>     from that second, clamped into the programme
     epg + at "resume"      from the place the stick saved (0 when there is none)
     movie_id               VOD movie or episode (`playvod/<movie_id>|<episode_id or null>|<owner_id>`); `start` or `at` "resume" reads local position
     {"ok": true, "epg", "offset"} (and "movie_id" for VOD); 404 no such programme, 409 not in archive
POST /api/sweettv/ctl {"op": "from_start"|"seek_by"|"live", "seconds"?}   unified Live/DVR/VOD controls
POST /api/sweettv/golive {}   {"ok": true}; 409 when an archived programme is not what is playing
     (what is playing is known by its plugin path or, for an archive, by the stream address, see "What the address of a stream is")
GET  /api/sweettv/settings    {"ok": true, "quality": "720p"|"1080p"|"unlimited", "options": [{"id", "label"}, ...]}
POST /api/sweettv/settings {"quality": "720p"|"1080p"|"unlimited"}   the same answer; 400 for an invalid value, 503 without the library
POST /api/sweettv/favourite {"key", "title"?, "thumb"?, "meta"?}   {"ok": true, "key", "favourite"}   toggle local SWEET.TV favourite (`ch:<id>`, `vod:<id>`, `show:vod:<id>`, `show:epg:<id>`, `show:tv:<id>`)
GET  /api/sweettv/shows       {"ok": true, "items": [...]}   unified GetCollections(type=7) Movie/Epg shows and playable channel EPG shows
GET  /api/sweettv/show?id=<id> {"ok": true, "id", "title", ...}   detail for `vod:<id>`, `epg:<col_id>`, or `tv:<show_id>`
GET  /api/sweettv/movies?genre=&sort=&offset=&limit=   paginated VOD movies catalog (4K UHD filtered unless quality is `unlimited`)
GET  /api/sweettv/series?genre=&sort=&offset=&limit=   paginated VOD series catalog
GET  /api/sweettv/vod?id=<movie_id>   {"ok": true, "id": "vod:<id>", "movie_id", "title", ..., "favourite", "resume", "watched", "vod_url", "seasons": [...]}
GET  /api/sweettv/top         {"ok": true, "items": [...], "count"}   trending search items (SearchService/GetTop.json)
GET  /api/sweettv/search?q=<text>
     {"ok": true, "query", "count", "items": [row, ...]}   a needle under 2 characters asks nothing: {"ok": true, "items": [], "count": 0, "short": true}
     programme row: {"kind": "programme", "title", "cid", "epg", "start", "stop", "channel_name", "when": "Пт 20 ноя 17:00", "live",
                     "playable_in_archive", "playable", "repeats", "more": "ещё 2 показа" | ""}   newest first, one row per title
     channel row:   {"kind": "channel", "cid", "title", "playable"}; also "movie" (playable VOD when available) and "person" rows
     409 SWEET.TV refuses the sign-in or there is none, 502 no answer / a reply of the wrong shape, 503 without the library
GET  /api/sweettv/day?cid=<id>&date=YYYY-MM-DD
     {"ok": true, "cid", "name", "date", "now", "archive_days", "future_days",
      "items": [{"epg", "title", "start", "stop", "when", "live", "playable_in_archive", "preview" (https or ""), "season", "episode", "show_id", "resume", "watched"}]}
     400 wrong channel or date, 404 the channel is not in the list, 409 the date is older than the channel's catchup_duration days or
     further ahead than its epg_days_future, 502 / 503 as above
```

`api.sweet.tv` catalog, search, day, and VOD (`mediastick_sweetapi`). Because the channel list's guide is a window of ten past programmes and has no VOD catalog, `mediastick_sweetapi` (standard library, `device/files/usr/local/lib/media-stick/`) calls `api.sweet.tv` directly: `SearchService/Search.json` and `SearchService/GetTop.json` for search and trending, `TvService/GetChannels.json` for a channel's full day (30 programmes each way, extended up to twice each way until the day is covered), `TvService/GetEpgRecords.json`, `MovieService/GetConfiguration.json`, `GetCollections.json`, `GetCollectionInfo.json`, `GetGenreMovies.json`, `GetMovieInfo.json`, and `GetLink.json` for shows, series, movies, and VOD playback (`playvod/<movie_id>|<episode_id or null>|<owner_id>`, resolved with HLS/Widevine MPD support in `device/skin-overlay/plugin.video.sweettv/`). Headers match the add-on's helper (`user-agent`, `x-device` `1;22;0;2;<version>`, `origin: https://sweet.tv`, `authorization` the bearer of the add-on's `settings.xml`, never logged); 8 s timeouts, answers kept 60 s (configuration 600 s), a 401 reads the token again once and retries, a needle under 2 characters never calls the API, every failure comes back as `{"ok": false, "error", "message"}` and never raises. Search/day programmes outside the channel list's window play through `POST /api/sweettv/play {"cid", "epg"}` via `mediastick_sweetapi.recall` and the same archive rules apply; 4K UHD titles and channels are hidden unless `prefs/max-quality` is `unlimited` (default `1080p` for Pi 3B+ H.264 limits). Tests: `tools/test-sweetapi.py` (uses `tools/fixtures/sweettv-*.json`) and `tools/test-sweettv-play.py`.

Per-app local resume, favourites, and quality cap (`mediastick_resume`, standard library only). SWEET.TV on both the TV app and the phone page always reads the stick's local positions in `/var/lib/media-stick/resume/positions.json` (`MEDIASTICK_RESUME_DIR` moves it): `{"v": 1, "items": {"yt:<video id>": {"pos", "total", "done", "at"}, "sw:<channel>|<programme>": {"cid", "epg", "pos", "total", "done", "at", "title", "start", "stop"}, "sw:vod:<movie_id>[|<episode_id>]": {"movie_id", "episode_id", "pos", "total", "done", "at", "title"}}, "live": {"cid", "at"}}`, and local SWEET.TV favourites in `/var/lib/media-stick/resume/sweettv-favourites.json`. Device video quality cap lives in `/var/lib/media-stick/prefs/max-quality` (`MEDIASTICK_PREFS_DIR` moves it; `720p`, `1080p` default, or `unlimited`). YouTube remains independent and uses its own profile/account history (`store.local_resume()`, `panel_watch._local_resume()`, and `youtube_files._local()` return `None`). The home add-on's service (`resume_recorder`) looks at what plays every 5 seconds, whoever started it, and writes a place at most every 30 seconds (at once when a video changes, stops or ends), the whole file renamed into place; at most 300 items are kept, the newest. A SWEET.TV live stream has no place, only the channel; a video within 30 s of its end, or past 97 %, is `done` (a full bar, no place); a place in the first 5 s is not kept. Tests: `tools/test-resume.py`, `tools/test-panel-watch.py`, `tools/test-sweettv-app.py`.

What the address of a stream is. For an archived programme Kodi's `Player.GetItem` (and the player's `getPlayingFile()`) gives the address of the stream the add-on resolved (`https://hls-dvr2.sweet.tv/dvr/...`), not the plugin path that was asked for (a live channel keeps its plugin path), so nothing downstream could tell which channel and programme was playing: `/api/watch/now` said `live` false, empty `epg`, `go_live` false, and `golive` answered 409. So `playvid` (every SWEET.TV item goes through it, whoever asked: the phone, the TV's own screens, the remote) writes `/run/media-stick/sweettv-now.json` (RAM; `MEDIASTICK_SWEETNOW_DIR` moves it) when it resolves: `{"v": 1, "items": [{"cid", "epg" ("" for live), "offset" (seconds it was asked to start at), "at", "sha", "where"}]}`, the last four items, newest first. `sha` is a SHA-256 of the stream address without its `|options`, `where` is `host/first-folder` of it; the address itself and its token are not kept. Whoever sees an address looks it up (`mediastick_sweetlive.recall` / `identify`; `panel_watch.sweet_ref` is the phone side, so `now_view`, `decorate`, `golive` and the -10 all use it; the add-on's service, `/golive` route and `resume_recorder` use it too, the recorder turning the address into the plugin path `playvid/<cid>|<epg>` so its positions are keyed as before): the same address is the same item; an address that is in no entry but is in the same `where` as an entry written less than `WEAK_AGE` = 300 s ago is taken for that entry (the identity only; the service seeks only for an address that is exactly the entry's); any other address is not a SWEET.TV item of ours. Nothing has to be cleared: a stream that no longer plays is simply not looked up, and the item that is going away is still told apart from the one being opened. `/api/watch/now` also has `app` "sweettv" and `channel` (the channel's name from the list when Kodi gives no show title) for such an item. Tests: `tools/test-sweetlive.py`, `tools/test-panel-watch.py`, `tools/test-resume.py`.

Where the place comes from (the ask). On the device the plugin path was opened with `?ms_start=8814` and the add-on still saw 0 (`sweettv-now.json` had `"offset": 0`, the player began at 0:14 of a 2 h 27 min programme): where Kodi leaves the query of a path whose id holds a `|` is not known, so nothing depends on it. Whoever opens an archive from a place already knows channel, programme and place, and writes them down just before opening (`mediastick_sweetlive.ask` / `ask_url`: `/run/media-stick/sweettv-ask.json`, `{"v": 1, "ask": {"cid", "epg", "offset", "at"}}`, one ask, written atomically; the phone's `POST /api/sweettv/play`, the -10 of `POST /api/watch/ctl` through `panel_sweettv.open_url`, and the TV remote's seek back or long pause in the add-on's `service.py`). The add-on's `playvid` takes the place, in this order, from `sys.argv[2]` (the query), `sys.argv[0]`, the id string itself (and the id is cut at the first `?`, `&` or `|` after the programme id, so a query that leaked into it is not the programme: `mediastick_sweetlive.split_id`), any other argument, and then the ask, if it is for exactly this channel and programme and no older than `ASK_FRESH` = 30 s (`mediastick_sweetlive.start_of`). An ask for this item is consumed whichever source won, so a play of the same programme started later from the TV is not put at a stale place; an ask for another item is left alone. The first place above 0 wins; none is the beginning (live and a play from the start ask for nothing). One line in `xbmc.log` (LOGINFO, `media-stick: SWEET.TV archive <cid>|<epg> asked to start at <n>s (<source>)`, source `query`, `path`, `videoid`, `argv`, `ask` or `none, ask <none|other|stale>`) says which was used; no address or token is in it. The service's verify-then-seek reads the offset the plugin wrote in `sweettv-now.json` as before.

Texts. A string a person sees is looked up as `tr(msgid)` from `sweettv_text.py` (`TEXT = {msgid: {"ru", "uk"}}`, the msgid is the English text; `tr` answers in `LANG`, the device's language: the TV window calls `set_language(sweettv_files.language())` when it is made, which reads the launcher's Home property `media-stick.lang`, else the file of `mediastick_lang`, as SWEET.TV's own code (`ru`, `uk`, `en`, `pl`, `hu`; `be` reads as `ru`, the rest as `en`); a language without a translation reads the English msgid; the plural «N channels» has the three Slavic forms in one entry, joined with `|`, and `tr_n` picks one; the skin has no text of its own, the fixed labels are the window's properties `l_*` from `sweettv_text.labels()`). The panel and the SWEET.TV add-on's service reach the dictionary through `mediastick_sweetlive.text(msgid)` (it loads the launcher add-on's file on its own, and falls back to the msgid). `tools/test-sweetlive.py` checks that every msgid has `ru` and `uk` and that every `_t("...")` in the panel is in the dictionary.

Assumed, to be checked on a device: the picture of a live stream is the wall clock (`LIVE_LAG` = 0 s behind it); Kodi calls `onPlayBackSeek` with a negative `seekOffset` in milliseconds for a seek back on a live item; the item's `ResumeTime` and `TotalTime` properties make Kodi start a plugin-resolved item at that second (if not, the service's seek does it; `StartOffset` is known not to work); `Player.seekTime` of the add-on's service lands on an archive of a programme that is still running, and the player reports its length (about the time elapsed so far) within a few seconds of `onAVStarted`; the add-on's `playvid` runs as the user that owns `/run/media-stick` (so it can write `sweettv-now.json`), and the player's address equals the `stream_url` the add-on resolved (else only the `where` guess identifies it, and no seek is made); the archive stream of a programme that is still running can be played from its beginning; `Player.getPlayingFile()` (or the `Player.Filenameandpath` label) gives the plugin path of a live plugin-resolved item and the stream address of an archive (the recorder keys on the plugin path and, failing that, on the add-on's entry); `getTime()` of an archive item is the second inside the programme; `Player.Open` accepts `"options": {"resume": false}` for a plugin path.

## Self-update

The device pulls `main` on the schedule in `device/config.env` (`UPDATE_SCHEDULE`, every 5 minutes while developing) and applies it; a failed update rolls back. Nothing is updated while Kodi is playing.

## Layout

| | |
|---|---|
| `provisioning/` | writing the card and the first-boot files; `cloud-init/user-data` never changes |
| `provisioning/firstboot/` | first boot: get online (cable, Wi-Fi, or setup hotspot), clone, hand over to bootstrap |
| `device/bootstrap.sh` | brings the Pi to the described state; safe to run again |
| `device/files/` | copied to the same paths on the device |
| `device/kodi-addons/script.media-stick.home/` | the launcher add-on: `resources/lib/` (`launcher.py` home, `apps.py`, `accounts*.py` and `signin.py` sign-in, `sweettv_app.py` the SWEET.TV window, `sweettv_data.py` its Kodi-free logic, `sweettv_sections.py` 7-section Netflix-style UI builders, `sweettv_shelf.py` filter chips and pagination, `sweettv_guide.py` guide/show/VOD modals, `sweettv_find.py` search, `sweettv_items.py` list items, `sweettv_play.py` playback/resume, `sweettv_jump.py` digit jump, `sweettv_pages.py` paginated `page_cache` helpers, `sweettv_state.py` legacy state, `sweettv_files.py` the files it reads, `sweettv_demo.py` the demo channels/catalog, `onboarding_app.py` the onboarding window and `onboarding_view.py` its Kodi-free logic, `onboarding_files.py` the files it reads, `onboarding_demo.py` the demo documents), `resources/skins/default/1080i/` the windows |
| `device/kodi-addons/script.media-stick.home/` (YouTube) | `resources/lib/youtube_app.py` the window, `youtube_data.py` its Kodi-free logic, `youtube_state.py` last section and search, `youtube_cards.py` what a card says (lines cut to fit with `textfit.py`), `youtube_files.py` the add-on calls and files it reads (and the wizard's step file), `youtube_demo.py` the demo videos, `ytkeys.py` writes the Google keys into the add-on; the phone side of the key wizard is `device/files/usr/local/lib/media-stick/panel_ytkeys.py`, `panel_ytkeys_ui.py` and `mediastick_ytkeys.py`; `resources/skins/default/1080i/script-media-stick-youtube.xml` |
| `device/skin-overlay/` | files copied over installed add-ons: the sign-in changes to YouTube and SWEET.TV, VOD/DVR playback in SWEET.TV, the skin's pointer |
| `tools/` | run from a computer (tests, art generators, `deploy.sh`, `doctor.sh`, `screenshot.sh`, `smoke-accounts.sh`, `device-lease.sh`) |
| `tools/emulator/` | Docker Box Emulator (`Dockerfile`, `run.sh`): Debian trixie-slim + Kodi + Xvfb + phone panel (`:8080`) + JSON-RPC (`:9090`) for local UI and API testing |

## Secrets

The repository holds names only (`secrets.example.env`). Values live on the device in `/etc/media-stick/secrets.env` (root:media, 0640). Wi-Fi passwords are typed by a person into the setup page and go straight into a root-only NetworkManager file. Access is by SSH key; password login is off.

Lost the key: put a new public key in a file named `authorized_keys` on the card's boot partition (FAT, readable on any computer); the Pi adds it at boot.
