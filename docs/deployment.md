# Waypost Station deployment

## Target hardware

- Raspberry Pi 5 preferred (8 GB); Pi 4 compatible where practical  
- Raspberry Pi OS Lite 64-bit / Debian ARM64  
- SSD preferred for persistent app data; microSD boot OK  
- USB RNode for Waylink (`/dev/waypost-lora` via udev)  
- No Internet required for normal operation  

## Host vs containers

| Component | Deployment |
|-----------|------------|
| hostapd, dnsmasq, openNDS | Host systemd (not Docker) |
| Caddy | Host or container — prefer host for TLS/local CA simplicity initially |
| Waypost API | systemd or container |
| Stalwart, BookStack, Memos, Kiwix | Docker Compose |

Configs live under `deploy/raspberry-pi/`. Compose under `docker-compose.yml` / `deploy/docker/`.

## Local DNS

- **Portal URL (user-facing):** `https://way.post/` — resolved by the Station’s dnsmasq (`10.42.0.1`) for clients on `WAYPOST` Wi‑Fi only. `.post` is a real public TLD; off-network browsers use public DNS and will not reach your Pi. That is intentional: the name is a local alias, like a captive-portal hostname.
- **Technical suffix:** `waypost.home.arpa` (avoid `.local` / mDNS clash) — still wired as aliases in dnsmasq and Caddy.
- **Short name:** `waypost` → same portal.
- **Service hostnames (future):** `postbox.waypost.home.arpa`, `fieldbook.waypost.home.arpa`, …

Do not hardcode service IPs in applications.

## Default Wi-Fi

- SSID: `WAYPOST` (configurable)  
- Captive portal: **Waygate** — HTTP splash at `/waygate.html` plus dnsmasq wildcard DNS and Caddy redirects for OS captive probes. Full **openNDS** session gating is still to add.

After joining Wi‑Fi, phones should land on **Waygate** (off‑grid welcome) → **Trust this Station** (CA download) → sign in at `https://way.post/`. Plain HTTP serves Waygate, trust, static assets, and CA files only.

## Data directories

Suggested on Station:

```text
/var/lib/waypost/
  data/           # SQLite, app state
  mail/           # Stalwart volumes
  fieldbook/
  commons/
  locker/
  archive/
  reticulum/
  backups/
```

## Bootstrap

**Step-by-step: [pi-setup.md](pi-setup.md).** `sudo deploy/raspberry-pi/install.sh` (idempotent) installs packages, the `waypost` service user, code + venv under `/opt/waypost`, data under `/var/lib/waypost`, `/etc/waypost/waypost.env`, the LoRa udev rule, `waypost-api.service`, Caddy HTTPS with an offline local CA, and stages hostapd/dnsmasq. `--enable-ap` switches `wlan0` to the access point.

Still to add: openNDS (Waygate), Compose stack for Stalwart & co, backups.

## Developer machine

No hotspot required. Run API with `WAYPOST_TRANSPORT=mock` and the simulator. See root [README.md](../README.md).
