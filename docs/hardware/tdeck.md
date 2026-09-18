# LilyGO T-Deck — Waypost Pocket

## Product role

**Waypost Pocket**: handheld community computer (modern Cybiko successor), not a LoRa radio with menus.

## Hardware (vendor-documented; confirm on unit)

| Feature | Use |
|---------|-----|
| Keyboard | Primary text input |
| Trackball | Pointer / navigation |
| Display | 320×240 — design UI for this density |
| LoRa | Waylink |
| Wi-Fi | Station API when in range |
| **GPS** | Pocket location for **Atlas** — prefer T-Deck **Plus** (or add a GPS module). Base Heltec/Outpost boards have **no** GPS and do not report position |
| Bluetooth | Future accessories / pairing aids |
| microSD | Local-first caches and apps |
| Audio | Notifications / Arcade where useful |

## Location (product intent)

- Pocket reports its GPS fix to Station about every **10–15 minutes** over Waylink (`LOC_REPORT`).  
- When setting up camp, an operator picks **which Pocket’s fix** becomes the Station’s **static origin** (`ORIGIN_SET`). Station does **not** continuously follow that device.  
- Portal **Atlas** shows Station + each reporting Pocket and distance/range from the Station origin.  

See roadmap **M7** (reporting) and **M8** (Atlas UI).

## Software direction

See [ADR 0001](../adr/0001-pocket-runtime.md). First prototype priority: keyboard, display, Wi-Fi, LoRa, Reticulum/LXMF, **Dispatch**. Full shell comes after transport is proven.

## Local storage layout (target)

```text
/waypost/fieldbook/
/waypost/postbox/
/waypost/dispatch/
/waypost/courier/     # carry-forward envelopes for others + pending Station sync
/waypost/locker/
/waypost/workshop/
/waypost/cache/
```

## Launcher apps (user-facing names)

Rollcall, Dispatch, Postbox, Commons, Fieldbook, Noticeboard, Locker, Archive, Atlas, Finder, Workshop, Arcade, Logbook, Signal — plus Control/Profile via system UI.

Keep branding consistent with [naming.md](../naming.md).
