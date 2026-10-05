# Waypost Scout firmware (`firmware/pocket`)

**Waypost Scout** is the handheld product built on the LilyGO T-Deck. People call it a **Scout** in conversation. In protocol and server code the device class stays **`Pocket`** (`pocket-*` node IDs, `PeerDispatchNode`, pairing flows) — see [docs/naming.md](../../docs/naming.md).

Target: **LilyGO T-Deck** (ESP32-S3, ST7789 320×240, SX1262 LoRa, keyboard + trackball). USB serial is usually **`/dev/ttyACM0`** (native CDC/JTAG).

## What it does

A Cybiko-style handheld that talks to Station over microReticulum on LoRa (Waylink RPC):

| App | What it does | Waylink ops |
|-----|--------------|-------------|
| **Pairing** | First boot: type the 6-digit code from the portal's Devices page (or the Scout adopts its account automatically if Station already has it bound) | `PAIR_REDEEM`, `WHOAMI` |
| **Lock** | PIN entry at boot and after 5 min idle, when a PIN is set | — |
| **Home** | 3×3 tile launcher; first letter of an app name opens it | — |
| **Dispatch** | Conversations list (unread dots) → conversation (history, older pages as you scroll up, live messages) → reply, 140 bytes max. "+ New message" picks from contacts (cached in flash). **Messages are kept on the Scout** (`store.*`): history reads and compose work with Station out of reach; a message written offline shows "(waiting)" and goes out by itself when Station is back (outbox, retried every 30 s, one copy on Station however often it's retried); one Station refuses shows "(not sent: reason)". Unread counts survive reboots. Signed messages also move by **peer sync** — from Station, or straight from another Scout in range with no Station at all — and the Scout passes on what it holds. Once the Scout has its device certificate, every message is **signed** on the Scout when written (D3) — the compose counter then shows the room left after the signature. Missed messages (or ones whose delivery ack was lost) arrive by catch-up when Station comes into reach and every 3 minutes while it is | `MSG_CONVS`, `MSG_LIST`, `MSG_SEND`, `MSG_PUSH` + ack, `MSG_SYNC`, `ROLL_LIST` |
| **Beacon** | Emergency alerts: full-screen alarm in the severity's colour over any app (lock screen too) until acknowledged; shows "CLEARED" if cancelled. The app lists the current and recent Beacons and can raise one (severity → headline → details → type SEND). Alerts are saved on the Scout: shown with Station out of reach, and one you've acknowledged isn't raised again after a reboot | `BEACON_ALERT` (pushed), `BEACON_GET`, `BEACON_LIST`, `BEACON_PUSH` |
| **Fieldbook** | Search the camp wiki → page outline → read a section | `WIKI_SEARCH` (compact), `WIKI_GET` (outline / section chunks) |
| **Trailhead** | Browse the Station's linked text pages; follow links, roll left to go back | `TRAIL_GET` |
| **Signal** | This Scout's node id and hash, Station path, PING round trip | `CORE/PING` |
| **Settings** | Who the Scout belongs to; whether people can be verified offline ("ID: verified offline, 3/3 contacts"); set / change / remove the PIN; unpair | `UNPAIR`, `CERT_*` (background) |

Long text arrives in ~160-byte chunks (one encrypted Reticulum packet per reply) as you scroll — see `docs/protocol.md` "Trailhead" and the radio-sized Fieldbook forms.

**Screen:** dims after 1 minute without a key and switches off after 3; any key or the trackball wakes it (that first key only wakes it). A new message or a Beacon lights it. The PIN lock still follows the 5-minute no-key timer.

**Controls:** roll the trackball to move, press it to open/select, roll left to go back. Keyboard types; Enter sends/searches; Backspace on an empty line goes back.

## Code layout (`src/`)

| File | Role |
|------|------|
| `main.cpp` | Bring-up and the event loop |
| `station_link.*` | Reticulum, identity, request/reply (rid-matched, retries for reads); wall clock learned from Station's replies |
| `certs.*` | Offline identity: pinned community key, certificates for itself and contacts, the PIN-sealed signing key (roadmap D2) |
| `sync.*` | Peer sync (D4): reconciles signed messages with Station every 3 min and with contacts' Scouts in range; answers other devices' `SYNC` requests |
| `store.*` | The Scout's own messages: conversations index, one file per conversation, outbox (roadmap D1) |
| `waylink_cbor.*` | CBOR envelopes: generic `encode_request` / `parse_reply`, plus older hand-written codecs |
| `input.*`, `keyboard.*` | Keyboard + trackball → one event stream; USB-serial remote control |
| `ui.*` | Title bar, lists, word wrap, screen text mirror |
| `reader.*` | Chunked text reader (headings, links) shared by Fieldbook and Trailhead |
| `app*.cpp` | The apps |

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
| `WAYPOST_POCKET_ID` | Node id prefix (default `pocket-1`); the full id adds the first 4 hex of the destination hash, e.g. `pocket-1-e75a` |
| `WAYPOST_STATION_DEST_HASH` | Station's Reticulum destination hash (32 hex) |
| `WAYPOST_USB_REMOTE` | `1` (default) keeps the USB-serial remote control; `0` for field builds |

Station hash: log in to the dev Station and read `GET /api/signal` → `waylink.rns_hash`, or use the hash printed at Station startup.

**Pairing:** a new Scout opens on the Pairing screen. On the portal, open Devices → Pair a device and type the 6-digit code on the Scout; it sends its own destination hash, so Station can push to it. A Scout already bound via the API is recognized automatically (`WHOAMI`) once Station is in reach. Lab shortcut, equivalent to pairing:

```bash
curl -X POST http://localhost:8000/api/dispatch/devices/bind -H 'Content-Type: application/json' \
  -d '{"username":"aj","node_id":"pocket-1-e75a","transport_dest":"<scout dest hash>"}'
```

## USB-serial remote control

For development and field debugging, the Scout accepts input over USB serial.
Every remote keystroke is **two bytes: `Ctrl-]` (0x1D), then the key**. Bytes without the
prefix are ignored: when a host opens the port, Linux briefly echoes the Scout's own log
output back to it, and bare bytes turned that echo into keypresses. After the prefix,
printable characters, Enter (`\r`) and Backspace (`0x08`) act like the keyboard;
**Ctrl-P / Ctrl-N / Ctrl-B / Ctrl-F** are trackball up / down / left / right, **Ctrl-G**
is a trackball press, **Ctrl-X** dumps a full-resolution screenshot (raw RGB565 read back from
the off-screen canvas; framing in `src/ui.cpp`), and **Ctrl-D** prints the current screen as text:

```
=== screen ===
[Waypost Scout] (station ok) msg 1
> Dispatch - Messages
  Fieldbook - Camp wiki
...
-- pocket-1-e75a   Station reachable
=== end ===
```

## Known limitations

- The radio starts on a background task (`station_link::start_radio`, after the account and contacts files are loaded — storage isn't safe for two tasks at once), so the apps open after the logo even if the radio is slow; the title-bar dot and home footer say "radio starting…" until it's up, and radio-dependent screens say so instead of hanging. Signal shows the last boot's total and slowest step (`/waypost_lastboot`). Test a slow radio with `PLATFORMIO_BUILD_FLAGS=-DWAYPOST_TEST_SLOW_RADIO_MS=30000`.
- Boot shows the Waypost Scout logo (`src/scout_logo.h`, from `image/waypost-scout-logo.png` via `tools/make_scout_logo.py`) with a progress bar, for at least 5 s. Requests show a spinner in the title bar while waiting.
- Colors are the night-sky blue-greens of the README header art (`image/logo2.png`) and the logo, defined once as named roles in `src/ui.h`. The panel is **BGR** (`include/tdeck_tft_setup.h`); with RGB, blue-greens show as olive.
- Changing `include/tdeck_tft_setup.h` needs `pio run -t clean`: it's force-included into TFT_eSPI, and PlatformIO doesn't rebuild the library when it changes.
- Requests block the UI while waiting (≤ 8 s per attempt; reads retry up to 3 times).
- Chat is Station-relayed with one peer; no contact list, no offline catch-up (`MSG_SYNC`) yet.

See [docs/hardware/scout.md](../../docs/hardware/scout.md) and [docs/adr/0001-pocket-runtime.md](../../docs/adr/0001-pocket-runtime.md).
