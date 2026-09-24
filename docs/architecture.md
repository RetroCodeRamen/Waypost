# Waypost architecture

## Design goal

Full-bandwidth community computing over local Wi-Fi, with the most important communication and information services still accessible over low-bandwidth LoRa via **Waylink**.

LoRa is **not** conventional IP. Do not transmit complete HTML sites across LoRa. Services expose one logical API:

| Client path | Encoding |
|-------------|----------|
| Wi-Fi / Ethernet | HTTP + JSON |
| LoRa / mesh | Compact CBOR RPC over Waylink |

Both paths hit the same Station service layer (or peer services when Station is unavailable for Dispatch).

---

## System context

```text
┌─────────────────────────────────────────────────────────────┐
│                        WAYPOST                              │
│                                                             │
│  Phones / laptops ──Wi-Fi──► Waygate ──► Portal + API       │
│                                      │                      │
│                              Waypost Station (Pi)           │
│                                      │                      │
│                         ┌────────────┼────────────┐         │
│                         │  Adapters  │  Services  │         │
│                         │ Stalwart   │ Dispatch   │         │
│                         │ BookStack  │ Noticeboard│         │
│                         │ Memos …    │ Beacon …   │         │
│                         └────────────┼────────────┘         │
│                                      │                      │
│                              Waylink gateway                │
│                                      │                      │
│                              USB RNode (/dev/waypost-lora)  │
└──────────────────────────────────────┼──────────────────────┘
                                       │ LoRa
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
              Waypost Outpost      Waypost Outpost     Waypost Pocket
```

Graceful degradation (core requirement):

```text
Pocket ──► Outpost ──► Outpost ──► Pocket
```

without Station, for peer-to-peer Dispatch (and eventually other P2P-capable ops).

---

## Station software layers

```text
┌──────────────────────────────────────┐
│  Waygate (openNDS) / Caddy / Portal  │
├──────────────────────────────────────┤
│  Waypost API (FastAPI)               │
│    identity · dispatch · mail · …    │
├──────────────────────────────────────┤
│  Adapters (Stalwart, BookStack, …)   │
├──────────────────────────────────────┤
│  Waylink gateway                     │
│    Transport interface               │
│      MockTransport (dev / CI)        │
│      SerialBridgeTransport (Heltec)  │
│      ReticulumTransport (target)     │
├──────────────────────────────────────┤
│  Host: hostapd · dnsmasq · systemd   │
└──────────────────────────────────────┘
```

**Dev note:** `SerialBridgeTransport` (Heltec plaintext bridge) was the original radio stand-in; production Station radio is USB RNode + `ReticulumTransport`, proven over real LoRa as of M2e (2026-09-22) — the project's two Heltec V3 boards now serve as that RNode hardware directly (see [hardware/usb-rnode.md](hardware/usb-rnode.md)). Host networking (AP, DHCP, DNS, captive portal) runs on the Pi via **systemd**, not Docker, for reliability. Application services that fit containers may use Docker Compose.

---

## Transport abstraction (Waylink)

User-facing name: **Waylink**. Implementation must stay transport-agnostic.

Conceptual interface (Python: `server/transports/base.py`):

```text
Transport
    send()
    receive()
    reachable()
    get_route()
    get_link_quality()
```

Initial implementations:

| Class | Role |
|-------|------|
| `MockTransport` | Dev/sim: latency, loss, duplicates, queueing |
| `ReticulumTransport` | Production LoRa via Reticulum/LXMF |

Future candidates: Meshtastic, MeshCore, packet radio, TCP, Internet gateway.

Application code must not import Reticulum directly outside the transport adapter.

---

## Automatic transport selection (Pocket)

1. Waypost Wi-Fi if available → HTTP API (prefer Station for sync)  
2. Else Waylink route if destination reachable → compact RPC (may be peer Pocket or Outpost, **not** only Station)  
3. Else queue locally and **carry** until a peer/Outpost/Station appears  

Conversations and mailboxes are identified by logical IDs, **not** by transport. Global unique IDs (`mid`) enable deduplication when a device switches Wi-Fi ↔ LoRa or when a carried copy finally reaches Station.

### Pocket↔Pocket and store-and-forward

Station is the community hub (portal, canonical history) but **must not be a single point of failure for chat**.

```text
Pocket A ──LoRa──► Pocket B          (B reads immediately if recipient)
    │                 │
    │                 └── still carries / offers copy toward Station
    └── via Outpost or another Pocket (courier) when direct path missing
```

Rules:
- **Recipient:** if `dst` is this Pocket’s identity → show in Dispatch now.  
- **Courier:** if not the recipient (or even if it is) → retain envelope for forwarding/sync until ACK’d toward Station or TTL/expiry.  
- **Station:** when any path appears, merge by `mid`; portal catches up without re-asking the humans.  
- Outposts are always-on couriers; **Pockets are mobile couriers** (people walking between camp and trail).

Reticulum/LXMF (or successor transport) should provide the hop/carry primitives; Waypost apps speak logical `MSG_*` only.

**Implemented in sim (M3):** `server/services/dispatch/peer.py` (`PeerDispatchNode`) proves this exact flow — direct delivery, courier carry, `MSG_SYNC` merge by `mid` — in the mock mesh. Real Pocket firmware (M7) is what's still missing to run it on hardware.

**Implemented in sim, first hardware attempt (M6):** `server/services/dispatch/outpost.py` (`OutpostNode`) is the always-on-courier half — uncapped relay hops (Pockets cap at 3 device-to-device hops; Outposts don't), preferred-route caching toward Station, direct hand-off when two Pockets are both in range of the same Outpost. Both node types share transport/request-response plumbing via `server/services/dispatch/waylink_node.py` (`WaylinkPeerNode`) rather than duplicating it.

That shared base exists because of a real bug worth remembering: a node's inbound-packet loop is a single task, so a handler that itself issues an outbound request and awaits the reply (as `OutpostNode`'s direct-hand-off does) will deadlock if the loop can't return to receiving while that handler waits — nothing would be left running to receive the reply. `WaylinkPeerNode` runs each handler as its own task (after synchronously deduping by `mid`, before any handler-level `await`) specifically so nested requests are safe. `PeerDispatchNode`'s handlers never happened to need this (they only ever store-and-ACK, never call out mid-handler), which is why the bug stayed latent through all of M3.

**Corkboard — Outpost-primary, Station-backup (M6, sim):** a genuinely different trust/durability model from Dispatch, which is why it's its own service (`server/services/corkboard/`) rather than reusing Noticeboard or Dispatch. Authorship is a free-text signature, not an account — matching a walk-up user at an Outpost's own Wi-Fi with no Waypost login. The Outpost's own copy is the durable primary; Station's is backup and never clears the Outpost's copy on sync (the opposite of Dispatch's courier queue, where the local copy is just a delivery vehicle) — tracked with a `synced_at` marker on the Outpost's own notes rather than deletion, so "already sent to Station" and "still here" aren't mutually exclusive. A Station user's read/write is always scoped to one known outpost — never a merged cross-outpost view — both for UX (a bear warning at one outpost is noise mixed into another's flood warning) and to bound the blast radius of any single post or read.

Both halves now exist: `OutpostNode.add_local_note`/`sync_corkboard` (Outpost-side — upload not-yet-synced notes, ingest whatever Station piggybacks back) and `CorkboardService.sync` (Station-side — ingest, auto-register, piggyback the outbox). Proven end-to-end in sim over a real `BOARD_SYNC` round trip (`server/tests/test_mesh_dispatch.py`).

**Standalone Outpost firmware (`firmware/outpost`, hardware bring-up started 2026-09-23):** a real device now exists — Heltec V3, Wi-Fi AP + Corkboard web UI + real on-device Reticulum via [microReticulum](https://github.com/attermann/microReticulum) (a mature C++ port of the actual protocol, not a host-side-only library as earlier assumed — see `firmware/outpost/README.md`). Its own identity/destination persists across reboots (verified over four consecutive resets on real hardware).

**Claiming an Outpost:** Station can only reply to a peer whose Reticulum destination hash it already knows via `learn_route()` — nothing discovers that automatically, so a never-claimed Outpost's `BOARD_SYNC` would arrive but Station couldn't route a response back. `OUTPOST_CLAIM` (`docs/protocol.md`) fixes this by reusing the M4 pairing-code system as-is: a Station user generates a code on the Corkboard portal page (same `POST /api/auth/pairing/create` Pocket pairing uses), a human enters it on the Outpost's own `/claim` Wi-Fi page, and the Outpost's claim request carries its own destination hash directly in its payload — `learn_route` runs synchronously inside the handler, before the reply is sent, so even that very first request gets a routable response. Building this surfaced (and fixed) a matching latent bug in the older Pocket radio-pairing path (`PAIR_REDEEM`): it accepted a `transport_dest` in its payload but never called `learn_route`, so a radio-only device's own first pairing reply could never have reached it either. Verified end-to-end over HTTP against a live Station (code → claim → registered with the right hash); the physical Outpost-Wi-Fi→`/claim`→real-LoRa leg still needs someone to join the Outpost's AP by hand.

---

## Bandwidth philosophy

Progressive retrieval only:

- Postbox: count → headers → selected body → attachment metadata  
- Fieldbook: search → page → section/diff  
- Locker: listing → metadata (not large files over LoRa)  
- Finder: titles → selected result  

Never auto-send large payloads because they exist.

---

## Identity

One Waypost account → username, `user@waypost` (or configured domain), profile `/~username`, Dispatch/Commons/Fieldbook identity.

Preferred: Stalwart as account authority + OIDC for apps that support it. Pocket radio identity is separate and **linked** via pairing codes.

Registration modes: `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`.

---

## Data and offline-first

- Station: SQLite for core Waypost app state initially; FOSS apps keep their own stores.  
- Pocket: microSD caches (`/waypost/...`), drafts, queues, local Logbook/Planner/Arcade.  
- Sync states: `LOCAL` | `QUEUED` | `SYNCING` | `SYNCED` | `CONFLICT` | `FAILED`.

---

## FOSS integration map

| User-facing | Backend (preferred) |
|-------------|---------------------|
| Postbox | Stalwart (SMTP/IMAP/JMAP/OIDC) |
| Fieldbook | BookStack |
| Commons | Memos |
| Archive | Kiwix |
| Waygate | openNDS |
| Wi-Fi AP / DHCP/DNS | hostapd / dnsmasq |
| Reverse proxy | Caddy |
| Waylink | Reticulum + LXMF |

Custom code is primarily integration, portal UX, protocol gateway, and Pocket/Outpost firmware.

---

## Phase focus

See [roadmap.md](roadmap.md). First end-to-end proof (done on Heltec stand-in as M2c):

```text
Pocket ──LoRa──► USB radio ──► Station API ──► Web Portal
```

Dispatch message both directions. Everything else builds on that pattern.

**Location / Atlas (planned M7–M8):** GPS-equipped Pockets report fixes on a long interval; Station camp position is a **one-shot snapshot** from a chosen Pocket (Station itself has no GPS). Portal Atlas shows nodes and distance from that origin.
