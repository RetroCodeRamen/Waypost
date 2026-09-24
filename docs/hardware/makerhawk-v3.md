# MakerHawk ESP32 LoRa V3 — Waypost Outpost

## Product role

Autonomous **Waypost Outpost**: routing, store-and-forward, deduplication, queue management, battery/diagnostics, safe OTA. Not a Raspberry Pi peripheral.

Sold as: **MakerHawk ESP32 LoRa V3 Development Board**.

**Status:** this board isn't in hand yet (not confirmed ordered). The relay/routing *logic* Outpost firmware will eventually run is already built and sim-tested (`server/services/dispatch/outpost.py`, `OutpostNode`) — and got a first real-radio exercise using the project's two RNode-flashed Heltec V3 boards as a temporary Station+Outpost stand-in, same precedent as Heltec standing in before RNode existed (`tools/radio/outpost_airtest.py`, `docs/roadmap.md` M6). One run completed a full send→process round trip over real encrypted LoRa between the two boards; it hasn't reproduced reliably since, likely RF/timing rather than the app logic (which is also sim-tested independently). None of this exercises MakerHawk-specific concerns (GPIO, Wi‑Fi AP mode, embedded web server, power) — those still need the real board.

## Known general characteristics

These are commonly advertised features and should be treated as **unverified until measured on the board in hand**:

| Feature | Reported |
|---------|----------|
| MCU | ESP32-S3 (~240 MHz) |
| Radio | SX1262-class LoRa |
| Wireless | Wi-Fi, Bluetooth |
| UI | OLED display |
| Power | USB; battery connector; kits with case/battery available |

## GPIO mapping — REQUIRES VERIFICATION

**Do not assume Heltec WiFi LoRa 32 V3 (or other) pinouts match MakerHawk.**

Document verified pins here after probing schematics/silkscreen/multimeter and a blink/radio smoke test:

| Function | GPIO | Verified? | Notes |
|----------|------|-----------|-------|
| SX1262 NSS | _TBD_ | ❌ | |
| SX1262 SCK | _TBD_ | ❌ | |
| SX1262 MOSI | _TBD_ | ❌ | |
| SX1262 MISO | _TBD_ | ❌ | |
| SX1262 BUSY | _TBD_ | ❌ | |
| SX1262 DIO1 | _TBD_ | ❌ | |
| SX1262 RST | _TBD_ | ❌ | |
| SX1262 TXEN / RXEN | _TBD_ | ❌ | if present |
| OLED SDA / SCL | _TBD_ | ❌ | |
| Battery ADC | _TBD_ | ❌ | |
| User button(s) | _TBD_ | ❌ | |

Board abstraction in firmware should load a `makerhawk_v3` pin config, not hardcode Heltec pins.

## Firmware approach

Prefer adapting an existing open-source **Reticulum transport-node** implementation to this board over inventing a routing stack.

## OLED diagnostics (target UX)

```text
WAYPOST R07

Peers: 4
Queue: 2
Battery: 76%

Station: 3 hops
RSSI: -91
```

No unnecessary UI.

## Regulatory

Frequency, BW, SF, CR, TX power are **configuration** (US 915 MHz ISM expected for initial project use). No continuous-transmit loops.
