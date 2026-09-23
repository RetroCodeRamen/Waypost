# Pi Station setup — SD card to working Station

Target: Raspberry Pi 5 (or 4), **Raspberry Pi OS Lite 64-bit**, one RNode radio on USB.
Installer: [`deploy/raspberry-pi/install.sh`](../deploy/raspberry-pi/install.sh) (tested on Debian Bookworm and Trixie containers; the access-point step needs real hardware).

## 1. Flash the SD card (on the laptop)

1. Install Raspberry Pi Imager (`sudo apt install rpi-imager`, or from raspberrypi.com).
2. **Device:** your Pi model. **OS:** Raspberry Pi OS (other) → **Raspberry Pi OS Lite (64-bit)**. **Storage:** the SD card.
3. When asked to apply OS customisation, choose **Edit settings**:
   - **Hostname:** `waypost`
   - **Username / password:** your admin account (not `waypost` — that name is reserved for the service user)
   - **Wireless LAN:** your *home* Wi‑Fi, so you can reach it for the install. Set **Wireless LAN country** (e.g. `US`).
   - **Locale:** your time zone.
   - **Services tab:** enable **SSH** (password auth is fine; a public key is better).
4. Write, eject, insert in the Pi, plug in Ethernet if you have it, power on. First boot takes 1–2 minutes.

## 2. Copy the repo and install (Station + HTTPS)

The repo is private, so copy it from the laptop rather than giving the Pi GitHub credentials:

```bash
# on the laptop, from the repo root
rsync -a --exclude .venv --exclude data --exclude .git --exclude '.pio' ./ <you>@waypost.local:~/Waypost/
ssh <you>@waypost.local
```

```bash
# on the Pi
cd ~/Waypost
sudo ./deploy/raspberry-pi/install.sh
```

Outside the US/CA/MX/AU/NZ/BR pass the LoRa frequency and Wi‑Fi country, e.g. `--country GB --frequency 868100000`. No radio yet? Add `--transport mock`.

What it does (safe to re-run; secrets, database and CA are created once and kept):

| Piece | Where |
|-------|-------|
| Code + Python venv | `/opt/waypost` (root-owned, read-only to the service) |
| Data (SQLite, Reticulum identity) | `/var/lib/waypost` |
| Settings + generated secret | `/etc/waypost/waypost.env` |
| Station API | `waypost-api.service` on 127.0.0.1:8000, sandboxed |
| HTTPS | Caddy (official repo, 2.8+) with an offline local CA |
| Radio | udev → `/dev/waypost-lora`, Reticulum `RNodeInterface` |
| Access point | **staged only** — hostapd config + Wi‑Fi password in `/etc/waypost/wifi-psk` |

Check it:

```bash
systemctl status waypost-api caddy --no-pager
curl -s http://127.0.0.1:8000/api/health
cat /etc/waypost/public/waypost-ca.sha256     # CA fingerprint people will compare
```

## 3. Switch on the WAYPOST access point

This turns `wlan0` from "client of your home Wi‑Fi" into the `WAYPOST` hotspot, so **any SSH session over Wi‑Fi drops**. The script refuses to do it from a `wlan0` SSH session.

- **With Ethernet:** `ssh <you>@waypost.local` over the cable, then `sudo ./deploy/raspberry-pi/install.sh --enable-ap`.
- **Without Ethernet:** plug in a keyboard + screen and run it on the console, or pass `--force-ap` and reconnect by joining `WAYPOST` (then `ssh <you>@10.42.0.1`).

Wi‑Fi password: `sudo cat /etc/waypost/wifi-psk`.

## 4. First visit from a phone or laptop

1. Join `WAYPOST`.
2. Open `http://waypost.home.arpa/` → you land on **Trust this Station**.
3. Download and install the certificate (per-device steps are on the page); compare the fingerprint with `cat /etc/waypost/public/waypost-ca.sha256` on the Pi.
4. The page detects the trust and moves you to `https://waypost.home.arpa/`. Register an account there — the same username/password signs in on Waypost Pocket.

## Notes and limits

- **Clock:** the Pi has no battery clock by default and boots with the time it last shut down. Certificates last 30 days so a lagging clock still works, but a Pi that was off for more than ~3 weeks can serve certs phones reject. Until [network-time](network-time.md) lands, set the time on boot if needed: `sudo date -s "2026-09-22 17:00"`, then `sudo systemctl restart caddy`. A Pi 5 RTC battery avoids this.
- **Production mode:** `WAYPOST_ENV=production` means no demo users (`aj`/`bob`/`waypost1` are lab-only), and session cookies are HTTPS-only.
- **One radio:** the udev rule maps the first supported USB radio to `/dev/waypost-lora`. For several radios, pin by `ID_PATH` (see `deploy/raspberry-pi/udev/99-waypost-lora.rules`).
- **Not yet:** Waygate captive portal (openNDS), backups, firewall rules.

## Troubleshooting

| Symptom | Check |
|---------|-------|
| API not healthy | `journalctl -u waypost-api -e` |
| Browser warns about the certificate | CA not installed on that device, or Pi clock far off (`date`) |
| No `WAYPOST` network | `journalctl -u hostapd -e`; `rfkill list`; Wi‑Fi country set? |
| Joined `WAYPOST` but no address | `journalctl -u dnsmasq -e`; `ip addr show wlan0` should list 10.42.0.1 |
| Signal shows no radio | `ls -l /dev/waypost-lora`; `rnodeconf /dev/waypost-lora --info` |
