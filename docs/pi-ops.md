# Pi Station — operations runbook

For first-time install see [pi-setup.md](pi-setup.md). This doc is for **day‑to‑day ops** once the Pi is the production Station.

**Current lab:** Pi 3 at `waypost.local` (`10.0.0.193`), portal `https://way.post`, RNode on `/dev/waypost-lora`. **Do not** run the laptop Station with the radio attached — the Pi owns it.

---

## Health check (from laptop)

```bash
./tools/pi/health-check.sh
./tools/pi/health-check.sh aj@10.0.0.193
```

Expect `waypost-api`, `caddy`, and (when AP is on) `hostapd` / `dnsmasq` **active**, and `/api/health` → `"status":"ok"`.

---

## Backup

### On the Pi (needs sudo once per run, or daily timer after reinstall)

```bash
sudo /usr/local/sbin/waypost-backup
ls -lt /var/lib/waypost/backups/
```

Creates `waypost-YYYYMMDD-HHMMSS.tar.gz` with:

- `waypost.db`
- `community.key` (identity signing authority — **critical**)
- `rns-identity` (Reticulum Station address)

Keeps the 14 newest archives.

After updating the repo on the Pi, re-run `sudo ./deploy/raspberry-pi/install.sh` (no flags) to install the backup script and enable the daily timer.

### Pull to laptop (no sudo on Pi)

```bash
./tools/pi/pull-backup.sh
```

Writes to `~/Waypost-backups/` (gitignored). Never commit backups or keys.

If `/var/lib/waypost/backups` is not readable over SSH, the script falls back to `~/waypost-import` on the Pi (migration snapshot).

---

## Restore (disaster recovery)

1. Flash a fresh Pi OS Lite image and run [pi-setup.md](pi-setup.md) steps 1–2 **without** `--enable-ap` first.
2. Copy a backup tarball to the Pi, e.g. `~/restore/waypost-*.tar.gz`.
3. Extract into a directory and import:

```bash
mkdir -p ~/restore/extract
tar -xzf ~/restore/waypost-*.tar.gz -C ~/restore/extract
sudo ./deploy/raspberry-pi/install.sh --import ~/restore/extract
sudo ./deploy/raspberry-pi/install.sh --enable-ap   # from Ethernet
```

Scouts and Outposts keep working if **database + community key + rns-identity** match the old Station.

---

## Common tasks

| Task | Command |
|------|---------|
| Wi‑Fi password | `sudo cat /etc/waypost/wifi-psk` |
| Reset user password | `sudo waypost-set-password USERNAME` |
| API logs | `journalctl -u waypost-api -f` |
| Caddy logs | `journalctl -u caddy -f` |
| Restart API | `sudo systemctl restart waypost-api` |
| CA fingerprint | `cat /srv/waypost/public/waypost-ca.sha256` |
| Fix clock (no RTC) | `sudo date -s "YYYY-MM-DD HH:MM"` then `sudo systemctl restart caddy` |

---

## Update Station code

```bash
cd ~/Waypost   # or /opt/waypost source checkout
git pull
sudo ./deploy/raspberry-pi/install.sh --skip-apt
sudo systemctl restart waypost-api
```

---

## What is not automated yet

- **Waygate / openNDS** — HTTP splash works; network-level session gating is future work ([openNDS README](../deploy/raspberry-pi/opennds/README.md)).
- **`WAYPOST_RNS_UPSTREAM`** — Reticulum federation link; unset on lab Pi.
- **Off-Pi backup without sudo** — add a sudoers drop-in for `waypost-backup` if you want passwordless pull of fresh tarballs.
