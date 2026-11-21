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
| device health | `tools/doctor.sh` |
| what the TV shows, as a PNG | `tools/screenshot.sh out.png` |
| remote, live screen, device info, Wi-Fi | http://mediastick.local |
| cast a video from a phone or PC | "Cast to device" / any UPnP-DLNA app; AirPlay (audio) from iOS |
| Kodi phone app (Kore, Official Kodi Remote, Yatse) | finds `mediastick` by itself; user `kodi`, password: `ssh … sudo grep KODI_WEB /etc/media-stick/secrets.env` |

## The page

http://mediastick.local is the one place to use the device from:

- hotspot up (no network) → Wi-Fi setup
- phone → remote (d-pad, playback, volume, text into Kodi search); screen, info and settings behind tabs
- wide screen → screen, remote, device info and settings side by side; the keyboard works as a remote

Anyone on the home network can open it, like a Chromecast. A browser on another site cannot press its buttons (every change needs a custom header that cross-site requests cannot carry).

## Self-update

The device pulls `main` on the schedule in `device/config.env` (`UPDATE_SCHEDULE`, every 5 minutes while developing) and applies it; a failed update rolls back. Nothing is updated while Kodi is playing.

## Layout

| | |
|---|---|
| `provisioning/` | writing the card and the first-boot files; `cloud-init/user-data` never changes |
| `provisioning/firstboot/` | first boot: get online (cable, Wi-Fi, or setup hotspot), clone, hand over to bootstrap |
| `device/bootstrap.sh` | brings the Pi to the described state; safe to run again |
| `device/files/` | copied to the same paths on the device |
| `tools/` | run from a computer |

## Secrets

The repository holds names only (`secrets.example.env`). Values live on the device in `/etc/media-stick/secrets.env` (root:media, 0640). Wi-Fi passwords are typed by a person into the setup page and go straight into a root-only NetworkManager file. Access is by SSH key; password login is off.

Lost the key: put a new public key in a file named `authorized_keys` on the card's boot partition (FAT, readable on any computer); the Pi adds it at boot.
