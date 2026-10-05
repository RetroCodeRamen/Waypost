# Waypost Scout firmware (`firmware/scout`)

**Waypost Scout** is the handheld product built on the LilyGO T-Deck. People call it a **Scout** in conversation. In protocol and server code the device class stays **`Pocket`** (`pocket-*` node IDs, `PeerDispatchNode`, pairing flows) — see [docs/naming.md](../../docs/naming.md).

Rebuilt 2026-10-05 to replace the first firmware (`firmware/pocket`, legacy; no longer used by this build): the screen and keys never wait on the radio. Design and the reasons: [docs/scout-firmware-architecture.md](../../docs/scout-firmware-architecture.md).

Target: **LilyGO T-Deck** (ESP32-S3, ST7789 320×240, SX1262 LoRa, keyboard + trackball). USB serial is usually **`/dev/ttyACM0`** (native CDC/JTAG).

## What it does

A Cybiko-style handheld that talks to Station over microReticulum on LoRa (Waylink RPC):

| App | What it does | Waylink ops |
|-----|--------------|-------------|
| **Sign in** | Username + password (the same as the portal). The Scout works out the identity key (~4–5 s) and proves it to Station with a signed challenge — the password never goes over the radio. With Station out of reach it signs in anyway and finishes when Station is back | `LOGIN_NONCE`, `LOGIN`, `WHOAMI` |
| **Lock** | PIN entry at boot and after 5 min idle, when a PIN is set | — |
| **Home** | 3×3 tile launcher; first letter of an app name opens it | — |
| **Dispatch** | Conversations list (unread dots) → conversation (history, older pages as you scroll up, live messages) → reply, 140 bytes max. "+ New message" picks from contacts (cached in flash). **Messages are kept on the Scout** (`store.*`): history reads and compose work with Station out of reach; a message written offline shows "(waiting)" and goes out by itself when Station is back (outbox, retried every 30 s, one copy on Station however often it's retried); one Station refuses shows "(not sent: reason)". Unread counts survive reboots. Signed messages also move by **peer sync** — from Station, or straight from another Scout in range with no Station at all — and the Scout passes on what it holds. Once the Scout has its device certificate, every message is **signed** on the Scout when written (D3) — the compose counter then shows the room left after the signature. Missed messages (or ones whose delivery ack was lost) arrive by catch-up when Station comes into reach and every 3 minutes while it is | `MSG_CONVS`, `MSG_LIST`, `MSG_SEND`, `MSG_PUSH` + ack, `MSG_SYNC`, `ROLL_LIST` |
| **Beacon** | Emergency alerts: full-screen alarm in the severity's colour over any app (lock screen too) until acknowledged; shows "CLEARED" if cancelled. The app lists the current and recent Beacons and can raise one (severity → headline → details → type SEND). Alerts are saved on the Scout: shown with Station out of reach, and one you've acknowledged isn't raised again after a reboot | `BEACON_ALERT` (pushed), `BEACON_GET`, `BEACON_LIST`, `BEACON_PUSH` |
| **Fieldbook** | Search the camp wiki → page outline → read a section | `WIKI_SEARCH` (compact), `WIKI_GET` (outline / section chunks) |
| **Trailhead** | Browse the Station's linked text pages; follow links, roll left to go back | `TRAIL_GET` |
| **Signal** | This Scout's node id and hash, Station path, PING round trip | `CORE/PING` |
| **Settings** | Who the Scout belongs to; whether Station vouches for this key and how many contacts can be checked offline; set / change / remove the PIN (it seals the identity key); sign out | `UNPAIR`, `CERT_*` (background) |

Long text arrives in ~160-byte chunks (one encrypted Reticulum packet per reply) as you scroll — see `docs/protocol.md` "Trailhead" and the radio-sized Fieldbook forms.

**Screen:** dims after 1 minute without a key and switches off after 3; any key or the trackball wakes it (that first key only wakes it). A new message or a Beacon lights it. The PIN lock still follows the 5-minute no-key timer.

**Controls:** roll the trackball to move, press it to open/select, roll left to go back. Keyboard types; Enter sends/searches; Backspace on an empty line goes back.

## Code layout (`src/`)

Four tasks: **net** (core 0) owns Reticulum and the radio; **ui** (core 1, 30 frames a second) owns
keys, apps, all app state and the screen; two workers, **crypto** and **sync**, take slow work off
the UI. The UI task never waits on the network: requests take a callback.

| File | Role |
|------|------|
| `main.cpp` | Bring-up, the UI task's frame loop, background jobs (catch-up, outbox, identity check) |
| `board.*` | Pins, and LilyGO's bring-up order (power, every chip-select high, MISO pulled up, SPI, keyboard delay) |
| `bus.*` | The one lock on the SPI bus that the display and radio share (RadioLib `LockingHal` + display flushes) |
| `display.*` | LovyanGFX on the ST7789: a PSRAM canvas, and a dirty-rectangle flush in short pieces from internal RAM |
| `radio.*` | Non-blocking SX1262 interface for microReticulum: DIO1 interrupt, queued sends, listen-before-talk, RNode split framing |
| `net.*` | The net task: any Waylink request (`request`/`result`), pushes (`incoming`), cached paths, Station reach and clock |
| `tasks.*` | `rpc::ask` (callback on the UI task), `rpc::call` (workers only), the workers, posting results to the UI task |
| `certs.*` | Offline identity: pinned community key, certificates for itself and contacts, the PIN-sealed identity key (roadmap D2) |
| `kdf.*` | scrypt: the identity key from username + password (4 MiB from PSRAM; on the crypto worker) |
| `sync.*` | Peer sync (D4) on the sync worker: Station every 3 min, Outposts heard and contacts' Scouts in range every minute (at once after writing); answers other devices' `SYNC` requests. Engine shared with the Outpost: `firmware/common/waypost_core` |
| `store.*` | The Scout's own messages: conversations index, one file per conversation, outbox (roadmap D1) |
| `input.*` | Keyboard + trackball (+ USB remote) → one event queue, read every frame |
| `ui.*` | Title bar, lists, word wrap, screen text mirror; unchanged rows aren't redrawn |
| `reader.*` | Chunked text reader (headings, links) shared by Fieldbook and Trailhead |
| `app*.cpp` | The apps |

`lib/microReticulum` is vendored with one local fix (no `Serial.flush()` in its logger).

## Build & flash

```bash
cd firmware/scout
pio run -e tdeck                              # build
pio run -e tdeck -t upload --upload-port /dev/ttyACM0
pio device monitor -p /dev/ttyACM0 -b 115200
```

**Do not** use `/dev/ttyUSB0` or `/dev/ttyUSB1` here — those are the Station RNode and Outpost Heltec boards.

**A flash fails or is interrupted:** the Scout can't be bricked (the bootloader is in ROM). Put it in
download mode: switch off, hold the trackball pressed, switch on, release after 2 s (screen stays
dark). Then flash with esptool directly, and switch off and on afterwards:

```bash
~/.platformio/penv/bin/python ~/.platformio/packages/tool-esptoolpy/esptool.py --chip esp32s3 \
  --port /dev/ttyACM0 --baud 921600 --before no_reset --after no_reset write_flash -z \
  0x0 .pio/build/tdeck/bootloader.bin 0x8000 .pio/build/tdeck/partitions.bin \
  0xe000 ~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin \
  0x10000 .pio/build/tdeck/firmware.bin
```

## Configuration

| Build flag | Purpose |
|------------|---------|
| `WAYPOST_POCKET_ID` | Node id prefix (default `pocket-1`); the full id adds the first 4 hex of the destination hash, e.g. `pocket-1-e75a` |
| `WAYPOST_STATION_DEST_HASH` | Station's Reticulum destination hash (32 hex) |
| `WAYPOST_USB_REMOTE` | `1` (default) keeps the USB-serial remote control; `0` for field builds |

Station hash: log in to the dev Station and read `GET /api/signal` → `waylink.rns_hash`, or use the hash printed at Station startup.

**Signing in:** a new Scout opens on the Sign in screen: username, then password. An account made before 2026-10-05 needs one sign-in on the Station portal first (that's when Station learns its identity key). The Scout is then bound to the account and Station can push to it. A Scout bound via the API is still recognized (`WHOAMI`), but can't sign messages until someone signs in on it. Lab shortcut for binding without signing in:

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

- Boot shows the Waypost Scout logo (`src/scout_logo.h`, from `image/waypost-scout-logo.png` via `tools/make_scout_logo.py`) for 2.5 s while the radio starts on the net task. The home footer says "radio starting…" until it's up; Signal shows the boot's step timings.
- One Waylink request is on the air at a time (LoRa is half duplex; a second one lost replies), so background work (certificates, peer sync) can delay an app's request by a few seconds.
- Colors are the night-sky blue-greens of the README header art, defined once in `src/ui.h`. The panel takes LovyanGFX's default colour order with inversion on (as Meshtastic's T-Deck setup). Image data must be passed as `lgfx::rgb565_t*`: a bare `uint16_t*` is read byte-swapped.
- microReticulum's packet-hash store logs `esp_littlefs: Failed to unlink /hashlist_store/seg1.dat. Has open FD` at times. This is in the library (the first firmware logged it too), and it's harmless so far.

See [docs/hardware/scout.md](../../docs/hardware/scout.md) and [docs/adr/0001-pocket-runtime.md](../../docs/adr/0001-pocket-runtime.md).
