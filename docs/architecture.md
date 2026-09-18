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

**Dev note:** Two Heltec V3 boards + `SerialBridgeTransport` are the current radio stand-in. Production Station radio remains USB RNode + Reticulum (see roadmap M2e). Host networking (AP, DHCP, DNS, captive portal) runs on the Pi via **systemd**, not Docker, for reliability. Application services that fit containers may use Docker Compose.

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
