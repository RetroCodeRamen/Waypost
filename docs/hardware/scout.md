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
| Display | 320×240 ST7789, **BGR** colour order (with RGB, blue-greens show as olive) — design UI for this density |
| LoRa (SX1262) | Waylink / Reticulum |
| Wi‑Fi | Station API when in range |
| GPS | Atlas / `LOC_REPORT` — **T-Deck Plus** (or GPS module). Base T-Deck may lack GNSS |
| microSD | Target for local-first caches (`/waypost/...`). Not used yet: firmware state (identity, Reticulum stores) lives in internal flash (LittleFS); the SD chip-select is held high at boot so the card stays off the shared SPI bus |
| USB | `/dev/ttyACM0` — ESP32-S3 native CDC |

## Software (current state, 2026-10-03)

- Runtime: [ADR 0001](../adr/0001-pocket-runtime.md) — Arduino + TFT_eSPI UI of our own over the same vendored **microReticulum** stack as `firmware/outpost/`.
- Firmware tree: [`firmware/pocket/`](../../firmware/pocket/) (directory name = internal **Pocket** class). Build, flash, configuration, controls, and the USB-serial remote control are in its [README](../../firmware/pocket/README.md).
- **Working over real LoRa:** Waypost Scout logo boot screen → home tile launcher → **Dispatch** (chat with one default peer, Station-relayed, live `MSG_PUSH` + ack, unread badge), **Fieldbook** (search → outline → section, read in ~160-byte chunks), **Trailhead** (Station's linked text pages), **Signal** (identity, Station path, PING ~1.8 s round trip).
- Every reply a Scout asks for fits one encrypted Reticulum packet (383 bytes) — see `docs/protocol.md` (Trailhead; radio-sized Fieldbook forms).
- **Not yet:** Scout↔Scout without Station, contact list / multiple conversations, Fieldbook editing, `PAIR_REDEEM` on-device (bind via portal/API for now), GPS `LOC_REPORT`, courier queue, microSD caches.

## Location (product intent)

Same as the prior T-Deck doc: Pocket-class devices report GPS to Station (`LOC_REPORT`); camp origin is a deliberate operator snapshot (`ORIGIN_SET`), not continuous tracking. See roadmap **M7** / **M9** (Atlas).

## Launcher apps (user-facing names)

Built: Dispatch, Fieldbook, Trailhead, Signal. Planned: Rollcall, Postbox, Commons, Noticeboard, Locker, Archive, Atlas, Finder, Workshop, Arcade, Logbook — plus Control/Profile via system UI. Branding: [naming.md](../naming.md).
