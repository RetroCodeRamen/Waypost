# Waypost Scout firmware (`firmware/pocket`)

**Waypost Scout** is the handheld product built on the LilyGO T-Deck. People call it a **Scout** in conversation. In protocol and server code the device class stays **`Pocket`** (`pocket-*` node IDs, `PeerDispatchNode`, pairing flows) — see [docs/naming.md](../../docs/naming.md).

Target: **LilyGO T-Deck** (ESP32-S3, ST7789 320×240, SX1262 LoRa, keyboard + trackball). USB serial is usually **`/dev/ttyACM0`** (native CDC/JTAG).

## What it does

A Cybiko-style handheld that talks to Station over microReticulum on LoRa (Waylink RPC):

| App | What it does | Waylink ops |
|-----|--------------|-------------|
| **Home** | 2×2 tile launcher; first letter of an app name opens it | — |
| **Dispatch** | Chat with one default peer (`WAYPOST_DISPATCH_PEER`); unread badge in the title bar | `MSG_SEND`, `MSG_PUSH` + ack |
| **Fieldbook** | Search the camp wiki → page outline → read a section | `WIKI_SEARCH` (compact), `WIKI_GET` (outline / section chunks) |
| **Trailhead** | Browse the Station's linked text pages; follow links, roll left to go back | `TRAIL_GET` |
| **Signal** | This Scout's node id and hash, Station path, PING round trip | `CORE/PING` |

Long text arrives in ~160-byte chunks (one encrypted Reticulum packet per reply) as you scroll — see `docs/protocol.md` "Trailhead" and the radio-sized Fieldbook forms.

**Controls:** roll the trackball to move, press it to open/select, roll left to go back. Keyboard types; Enter sends/searches; Backspace on an empty line goes back.

## Code layout (`src/`)

| File | Role |
|------|------|
| `main.cpp` | Bring-up and the event loop |
| `station_link.*` | Reticulum, identity, request/reply (rid-matched, retries for reads) |
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
| `WAYPOST_DISPATCH_USER` / `WAYPOST_DISPATCH_PEER` | Scout's own username and its default chat peer |

Station hash: log in to the dev Station and read `GET /api/signal` → `waylink.rns_hash`, or use the hash printed at Station startup.

Chat needs the Scout bound to its user on Station, **with** its destination hash, or Station can't route pushes back:

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
is a trackball press, and **Ctrl-D** prints the current screen as text:

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

- Requests show a spinner in the title bar while waiting; boot shows a progress bar.
- Requests block the UI while waiting (≤ 8 s per attempt; reads retry up to 3 times).
- Chat is Station-relayed with one peer; no contact list, no offline catch-up (`MSG_SYNC`) yet.

See [docs/hardware/scout.md](../../docs/hardware/scout.md) and [docs/adr/0001-pocket-runtime.md](../../docs/adr/0001-pocket-runtime.md).
