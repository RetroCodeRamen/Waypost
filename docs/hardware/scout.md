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

## Software (current state, 2026-10-04)

- Runtime: [ADR 0001](../adr/0001-pocket-runtime.md) — Arduino + TFT_eSPI UI of our own over the same vendored **microReticulum** stack as `firmware/outpost/`.
- Firmware tree: [`firmware/scout/`](../../firmware/scout/) (canonical; internal **Pocket** class in protocol). Legacy: [`firmware/pocket/`](../../firmware/pocket/). Build, flash, and controls: [scout README](../../firmware/scout/README.md).
- **Working over real LoRa:** logo boot screen; the radio starts in the background (Station reachable in ~10–20 s) → **sign in** with username + password (identity key derived on the device; `LOGIN_NONCE`/`LOGIN`, 2026-10-05), **PIN lock** (seals the key), **Settings** → 3×3 launcher → **Dispatch** (conversations, contact picker from cached `ROLL_LIST`, chat, live push + ack, catch-up every 3 min), **Beacon** (full-screen alerts over any screen including the lock screen, list, raise), **Fieldbook**, **Trailhead**, **Signal**.
- Every reply a Scout asks for fits one encrypted Reticulum packet (383 bytes) — see `docs/protocol.md`.
- **Not yet:** anything without Station — see the plan below.

## Firmware plan — a Scout that works on its own

Direction adopted 2026-10-04 ([network-model.md](../network-model.md)): a Scout is a complete
personal Waypost, not a Station terminal. Two Scouts in range must work with nothing else. In
dependency order (roadmap track **D**, [roadmap.md](../roadmap.md#decentralization-track-dependency-order)):

| Step | What | Status |
|---|---|---|
| Account + contacts cached in flash, owner-tagged | | ✅ |
| PIN lock | locks the UI and seals the signing key (D2) | ✅ |
| **Local object store** | messages (own conversations), outbox, Beacon alerts in LittleFS (`store.*`); receipts and certificates come with D2/D3; microSD later | 🟡 D1 built 2026-10-04 |
| **Apps read from the store** | Dispatch history/compose work offline; outbox sends when Station is in reach (any peer after D4); shows "(waiting)" / "(not sent: …)"; screen dims and sleeps | 🟡 D1 built, hand test pending |
| **Identity certificates** | pins the community key, keeps certificates for itself and contacts, verifies offline (`certs.*`) | 🟡 D2 built 2026-10-04 |
| **Signed objects** | every message/receipt/Beacon it creates is signed with its device key | 📋 D3 |
| **`station_link` → `link`** | talks to any peer by destination; Station is one peer, picked by capability | 🔧 D4 |
| **Peer sync** | `SYNC_*` with whoever is near: other Scouts, Outposts, Station | 📋 D4 |
| **Nearby + status** | from announces: "Nearby: 2 Scouts, 1 Outpost · Station: via Outpost" | 📋 D6 |
| **Courier role** | carries others' objects within a budget; drops them on archive receipt | 📋 D7 |
| **Beacon spread** | relays Beacon events to peers; raise works without Station | 🔧 D5 |
| **Tier 2** | ESP-NOW to other Scouts, Wi-Fi to Outpost/Station APs, for big syncs | 📋 D8 |
| Fieldbook / Trailhead / Noticeboard pinned pages cached | | 📋 D9 |

Storage note: internal flash has ~ a few MB of LittleFS free; the microSD slot shares the SPI bus
with the radio and display, so it needs its own bring-up (bus locking) before use.

## Location (product intent)

Same as the prior T-Deck doc: Pocket-class devices report GPS to Station (`LOC_REPORT`); camp origin is a deliberate operator snapshot (`ORIGIN_SET`), not continuous tracking. See roadmap **M7** / **M9** (Atlas).

## Launcher apps (user-facing names)

Built: Dispatch, Fieldbook, Trailhead, Signal. Planned: Rollcall, Postbox, Commons, Noticeboard, Locker, Archive, Atlas, Finder, Workshop, Arcade, Logbook — plus Control/Profile via system UI. Branding: [naming.md](../naming.md).
