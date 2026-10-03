# Waypost Scout — LilyGO T-Deck

## Naming

| Layer | Name | Example |
|-------|------|---------|
| Product | **Waypost Scout** | “Flash the Scout firmware.” |
| Casual | **Scout** | “Hand me your Scout.” |
| Internal / protocol | **Pocket** | `node_id`: `pocket-aj`, `PeerDispatchNode`, courier queue |

Do not rename protocol identifiers or SQLite bindings from `pocket` to `scout` — Scout is the product skin on the Pocket device class.

## Product role

**Waypost Scout** is the handheld community computer (modern Cybiko successor): keyboard, trackball, display, Wi‑Fi, LoRa, and eventually the full Pocket app shell. It is also a **mobile courier** — it can carry and forward messages for peers when Station is out of range.

## Hardware (vendor-documented; confirm on unit)

| Feature | Use |
|---------|-----|
| Keyboard | Primary text input |
| Trackball | Pointer / navigation |
| Display | 320×240 ST7789 — design UI for this density |
| LoRa (SX1262) | Waylink / Reticulum |
| Wi‑Fi | Station API when in range |
| GPS | Atlas / `LOC_REPORT` — **T-Deck Plus** (or GPS module). Base T-Deck may lack GNSS |
| microSD | Local-first caches (`/waypost/...` on SD, target layout in ADR) |
| USB | `/dev/ttyACM0` — ESP32-S3 native CDC |

## Software direction

- Runtime choice: [ADR 0001](../adr/0001-pocket-runtime.md) — first prototype favors a proven Reticulum-capable base if it unblocks Dispatch; long-term UI may move to native LVGL.
- Firmware tree: [`firmware/pocket/`](../../firmware/pocket/) (directory name = internal **Pocket** class).
- First milestone: **Dispatch over Waylink** on real LoRa, not a finished launcher (M7).
- **Slice 1 (2026-10-02):** `firmware/pocket/` — microReticulum + LoRa (T-Deck SX1262 pins), auto `CORE/PING` ~45s after boot; TFT shows path/PING status. Flash: `pio run -e tdeck -t upload --upload-port /dev/ttyACM0`. Set `WAYPOST_STATION_DEST_HASH` in `platformio.ini` (same as Outpost). Optional `WAYPOST_DISPATCH_PEER` for `MSG_SEND` after binding `pocket-*` + `transport_dest` in portal.

## Location (product intent)

Same as the prior T-Deck doc: Pocket-class devices report GPS to Station (`LOC_REPORT`); camp origin is a deliberate operator snapshot (`ORIGIN_SET`), not continuous tracking. See roadmap **M7** / **M9** (Atlas).

## Launcher apps (user-facing names)

Rollcall, Dispatch, Postbox, Commons, Fieldbook, Noticeboard, Locker, Archive, Atlas, Finder, Workshop, Arcade, Logbook, Signal — plus Control/Profile via system UI. Branding: [naming.md](../naming.md).
