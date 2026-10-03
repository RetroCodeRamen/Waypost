# Waypost Scout firmware (`firmware/pocket`)

**Waypost Scout** is the handheld product built on the LilyGO T-Deck. People call it a **Scout** in conversation. In protocol and server code the device class stays **`Pocket`** (`pocket-*` node IDs, `PeerDispatchNode`, pairing flows) — see [docs/naming.md](../../docs/naming.md).

Target: **LilyGO T-Deck** (ESP32-S3, ST7789 320×240, SX1262 LoRa, keyboard + trackball). USB serial is usually **`/dev/ttyACM0`** (native CDC/JTAG).

## Status (M7 slice 0)

| Done | Next |
|------|------|
| Boot splash + serial banner | Reticulum + Waylink (microReticulum, same path as Outpost) |
| T-Deck power/backlight/display | Dispatch `MSG_SEND` / `MSG_PUSH` round trip |
| | Pairing (`PAIR_REDEEM`), keyboard input, status UI |

See [docs/hardware/scout.md](../../docs/hardware/scout.md) and [docs/adr/0001-pocket-runtime.md](../../docs/adr/0001-pocket-runtime.md).

## Build & flash

```bash
cd firmware/pocket
pio run -e tdeck                              # build
pio run -e tdeck -t upload --upload-port /dev/ttyACM0
pio device monitor -p /dev/ttyACM0 -b 115200
```

**Do not** use `/dev/ttyUSB0` or `/dev/ttyUSB1` here — those are the Station RNode and Outpost Heltec boards.

## Configuration

| Build flag | Purpose |
|------------|---------|
| `WAYPOST_POCKET_ID` | Logical Pocket node id (default `pocket-1`) — matches Waylink `env.src` |
| `WAYPOST_STATION_DEST_HASH` | *(next slice)* Station Reticulum hash for outbound Waylink |

Station hash: log in to the dev Station and read `GET /api/signal` → `waylink.rns_hash`, or use the hash printed at Station startup.
