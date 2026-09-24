# Outpost firmware — standalone Wi-Fi AP + real Reticulum + Corkboard

Product name: **The Outpost** (not Relay). No host computer — this board runs
the actual Reticulum protocol itself, over its own LoRa radio, while also
serving a local Wi-Fi AP with a public Corkboard messageboard for visitors.

Target hardware verified so far: **Heltec WiFi LoRa 32 V3** (ESP32-S3 +
SX1262), currently flashed to `/dev/ttyUSB1` for bring-up. MakerHawk ESP32
LoRa V3 is the intended production board — same SoC/radio class, GPIO
mapping still needs verifying against [docs/hardware/makerhawk-v3.md](../../docs/hardware/makerhawk-v3.md)
before flashing one.

## Why real Reticulum, not plaintext LoRa

An earlier draft of this firmware planned plaintext CBOR over LoRa,
reasoning that real Reticulum needed a host-side Python stack. That was
wrong: [microReticulum](https://github.com/attermann/microReticulum)
(Apache-2.0) is a mature, maintained C++ port of the actual Reticulum
protocol — full crypto (Ed25519/X25519/AES/Fernet), identities,
destinations, announces, path discovery — that runs standalone on ESP32.
This firmware uses it directly, satisfying the "all transport communication
encrypted between outposts and station" requirement with a reviewed
library instead of hand-rolled crypto. See `docs/architecture.md` and the
plan history for the full story.

`lib/lora_interface/` is vendored unmodified from microReticulum's own
`examples/common/lora_interface` (Apache-2.0) — it already has a
`BOARD_HELTEC_V3` pin mapping that matches `firmware/heltec/src/main.cpp`'s
independently-verified pins exactly.

## Protocol

Same wire protocol Station's `ReticulumTransport` already speaks
(`server/transports/reticulum.py`): a single `RNS.Destination(IN, SINGLE,
"waypost", "waylink")` per node, plain `RNS.Packet` send/receive — **not**
a Link session. `src`/`dst` in the Waylink `Envelope` (CBOR, hand-encoded
in `src/waylink_cbor.cpp` — see its header comment for why a full CBOR
library wasn't used) carry logical node-id strings ("outpost-1",
"station"); the Reticulum destination hash is a separate, transport-level
address. `BOARD_SYNC` (`SVC_CORKBOARD`) is the only op this firmware speaks.

## Flashing

```bash
cd firmware/outpost
pio run -e heltec_wifi_lora_32_V3                              # build
pio run -e heltec_wifi_lora_32_V3 -t upload --upload-port /dev/ttyUSB1
pio device monitor -p /dev/ttyUSB1 -b 115200                   # (interactive terminal only —
                                                                 #  see "Serial monitoring" below)
```

**`/dev/ttyUSB0` is Station's own live radio — never flash that port with
this firmware.** Only `/dev/ttyUSB1` is safe to use for Outpost bring-up.

### First test: pointing this Outpost at Station

Station's destination hash isn't auto-discovered yet — set it explicitly:

1. Get Station's hash: it's printed at Station startup
   (`ReticulumTransport.destination_hash_hex`), or via
   `curl localhost:8000/api/health` if that's exposed there.
2. Edit `WAYPOST_STATION_DEST_HASH` in `platformio.ini`'s
   `[env:heltec_wifi_lora_32_V3]` build_flags (32 hex chars), rebuild, reflash.

**Station can't reply until it's been told this Outpost's destination
hash** — `ReticulumTransport` only routes to peers it knows via
`learn_route(node_id, transport_dest)` (same mechanism the M4 pairing-code
system uses for Pocket devices). Two ways that happens now:

1. **Walk up and claim it** — a Station user generates a code on the
   Corkboard portal page, enters it on this Outpost's own `/claim` Wi-Fi
   page. See `docs/protocol.md`'s `OUTPOST_CLAIM`.
2. **Auto-claim (on by default)** — this firmware periodically announces
   itself over Reticulum, and while unclaimed *and* auto-claim is enabled
   (see below), that announce carries a small marker Station's
   `ReticulumTransport` recognizes and claims from automatically, no code
   needed. See `docs/security.md`'s "Auto-claim" entry for the trust model.

### The PRG/BOOT button — toggles auto-claim discoverability

GPIO0 (every Heltec V3's PRG/BOOT button), otherwise unused by this
firmware. A short press toggles whether this Outpost advertises itself as
auto-claimable — on by default, persisted in flash, shown briefly on the
OLED ("AUTO-CLAIM ON"/"OFF"). Turning it off doesn't affect an
already-claimed Outpost (claimed-ness never gets undone by this
firmware); it only controls whether a *not-yet-claimed* board can be
picked up automatically versus requiring the walk-up `/claim` flow.

### Serial monitoring from a non-interactive shell

`pio device monitor` needs a real TTY. From a script or non-interactive
shell, read the port directly and pulse RTS low then high to force a
reset (these boards use native USB-CDC, not a UART bridge, so output
during the *original* boot — right after flashing — is gone by the time
you attach; pulsing RTS gets you a fresh boot to watch):

```python
import serial, time
ser = serial.Serial('/dev/ttyUSB1', 115200, timeout=1)
ser.setDTR(False); ser.setRTS(True); time.sleep(0.3); ser.setRTS(False)
# then read ser for a few seconds
```

## Scope (this slice)

**In:** Wi-Fi AP (open network, SSID `WAYPOST-OUTPOST`) + Corkboard web UI
(post a note with an optional signature, list notes, Refresh-to-sync);
real Reticulum identity + destination, persisted in flash; `BOARD_SYNC`
round trip to Station.

**In (2026-09-24):** local DNS (`out.post` → `192.168.4.1`) via ESP32
`DNSServer` + DHCP DNS offer; **Waygate** splash at `/` with Continue →
`/board` (Corkboard). Captive-portal probe URLs redirect to the splash.

**In (2026-09-24, later):** auto-claim — periodic re-announce (every 10
min while unclaimed) carrying a marker in `app_data`, gated by a
persisted, button-toggled `auto_claim_enabled` flag (default on); learns
it's been claimed (walk-up or auto) via a `claimed` field on its own
periodic `BOARD_SYNC` reply (also new: this now runs automatically every
5 min, not just when a human visits `/refresh`).

**Out, deliberately:** multi-hop relay logic (microReticulum's own
Transport mode handles Reticulum-level path discovery for free —
`transport_enabled(true)` is set, so this board already relays
announces/paths for others even though this firmware writes none of that
logic itself); private Dispatch relay; the emergency Beacon button; flash
persistence of the note board itself (in-RAM ring buffer, capped at 40
notes, oldest evicted first — the Reticulum *identity* does persist, see
below); un-claiming or transferring an already-claimed Outpost to a
different Station.

## Known limitations (hardware-verified 2026-09-23)

- **Reticulum's own internal path/announce cache does not survive a
  reboot.** `Reticulum::storagepath()` defaults to `"."` and gets reset by
  `Reticulum()`'s own constructor; setting it (done in `main.cpp`, right
  after construction and before `.start()`) fixes it for
  `time_offset`/`transport_identity`, confirmed via the boot log, but
  Transport's path/known/hashlist stores are static objects constructed
  before `setup()` ever runs — they capture `"."` regardless, and ESP32's
  VFS rejects any path that doesn't start with `/`. Fixing that fully
  means patching the vendored library, not something done here. **This
  Outpost's own identity is unaffected** — it's read/written directly via
  an absolute path (`/waypost_identity`) in `main.cpp`, not through those
  stores, and was confirmed stable across four consecutive reboots during
  bring-up (same destination hash every time). Net effect: this Outpost's
  address stays constant, but it re-learns LoRa paths/neighbors from
  scratch each boot instead of resuming a warm cache — a performance
  cost, not a correctness one.
- `filesystem.init(false)` (not `true`) is required — `true` runs
  `LittleFSFileSystem`'s own self-test against the relative path
  `./__init_test__`, which always "fails" for the same VFS reason above
  and would silently reformat the filesystem (wiping the identity) on
  every single boot. Confirmed empirically before this was found: the
  destination hash changed on every reset until fixed.
- **Auto-claim (2026-09-24) compiles clean (`pio run`) and is verified
  live against a real Reticulum stack — TCP lab, not real LoRa, and not
  yet flashed to the physical Outpost** (`tools/radio/auto_claim_airtest.py`
  proves the Station-side announce handler end-to-end: a fake outpost
  peer announces with the marker, Station claims it with the correct
  hash, all through the real `rns` package, no mocks). The button/OLED
  and periodic-announce/auto-sync pieces are new code on real hardware
  that hasn't been power-cycled yet — reflash and a physical check (does
  the button actually toggle, does the OLED status show correctly, does
  a real over-LoRa announce reach a real Station) are the next steps
  before calling this hardware-verified the way the rest of this
  document's claims are.
