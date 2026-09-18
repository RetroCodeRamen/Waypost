# Waypost Station — Raspberry Pi

## Target

| Item | Preference |
|------|------------|
| Board | Raspberry Pi 5 (8 GB); Pi 4 where practical |
| OS | Raspberry Pi OS Lite 64-bit / Debian ARM64 |
| Storage | SSD for `/var/lib/waypost` preferred; microSD boot OK |
| Network | Wi-Fi AP (hostapd); Ethernet optional |
| Radio | USB RNode → `/dev/waypost-lora` |

## Roles

Hosts hotspot, DHCP, DNS, Waygate, Waypost API, portal, identity, application backends (Compose), Waylink gateway, admin, backups.

Must operate with **no Internet**.

## Notes

- Keep ARM64 compatibility in dependencies and container images.  
- Design for sudden power loss: systemd restart, durable SQLite, documented volume mounts.  
- Do not put hostapd/dnsmasq/openNDS in Docker solely for consistency.
