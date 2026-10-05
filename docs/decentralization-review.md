# Decentralization review — Waypost against the "no device is necessary" rule

**Date:** 2026-10-04. **Scope:** the code and docs as of commit `5c8cd4f`, reviewed against the
network philosophy adopted the same day ([network-model.md](network-model.md)). This is a
correction and refinement, **not a redesign**: services, names, hardware, and working code stay.

Status tags: **✅ implemented** · **🟡 partial** · **📋 planned** · **🔧 architectural change required**.

Naming decisions made for this review (asked 2026-10-04):
- **Beacon stays emergency alerts.** Identity is a network layer with no app name; discovery and
  presence belong to **Rollcall**.
- **Fieldbook = wiki, Commons = social feed.** The brief's "Commons/wiki cache" means Fieldbook (and
  Commons where useful).
- **Courier is a role** any moving device plays, not a separate product.

---

## 1. What already supports the model

| Piece | Status | Where |
|---|---|---|
| Encrypted packet substrate with per-device keypairs, announces, and multi-hop forwarding — Scouts and Outposts already run Reticulum *transport* (they forward packets for others) | ✅ hardware | `firmware/*/src` (`transport_enabled(true)`), `server/transports/reticulum*` |
| Transport-independent apps (Waylink envelope; apps never touch Reticulum) | ✅ | `shared/protocol/envelope.py`, `server/transports/base.py` |
| Globally unique message ids and dedup by id at the gateway, in Dispatch, Beacon, Corkboard | ✅ (64-bit) | `new_id()`, `WaylinkGateway._seen_mids`, `messages.id`, `beacon mid UNIQUE` |
| Carry-forward sync of messages: `MSG_SYNC` ingests carried copies, dedups, piggybacks the peer's pending, paged to one packet | ✅ Station · 🟡 devices | `server/services/dispatch/service.py` |
| Peer-to-peer Dispatch with no Station, courier hand-off, hop caps, TTL, Wi-Fi↔LoRa failover | ✅ **sim only** | `dispatch/peer.py`, `outpost.py`, `waylink_node.py`, `test_mesh_dispatch.py` |
| Outpost-primary data that survives Station absence (Corkboard: Outpost copy is primary, Station is backup, `synced_at` markers) | ✅ (RAM on device — 🔧 needs flash) | `services/corkboard/`, `firmware/outpost` |
| Outpost serves people with no Scout over its own Wi-Fi (Corkboard, walk-up Beacon) | ✅ hardware | `firmware/outpost` `/board`, `/post`, `/beacon` |
| Outpost queues Beacon reports and retries; Station dedups | ✅ | `BEACON_SYNC`, `firmware/outpost` |
| Capability-ish announces: Outpost puts an auto-claim marker in announce `app_data`, Station acts on it | ✅ (one flag) | `ReticulumTransport` announce handler |
| Fieldbook revisions with `base_revision` conflict detection (merge-friendly history) | ✅ | `services/fieldbook/` |
| Device identity separate from account; pairing codes; per-device revocation; passwords never over LoRa | ✅ | `services/auth/pairing.py`, [identity.md](identity.md) |
| Scout caches who it is and its contacts in flash (owner-tagged) and boots usable before the radio is up | ✅ | `firmware/pocket/src/account.*`, `contacts.*`, `station_link` |
| Scout PIN lock that works offline | ✅ (UI lock only) | `app_lock.cpp` |
| Signed messages, deliver-at-first-node, Station as memory | 📋 designed | [mesh-delivery.md](mesh-delivery.md) |
| Shared sync states (`LOCAL/QUEUED/SYNCING/SYNCED/CONFLICT/FAILED`) | 📋 design | [offline-sync.md](offline-sync.md) |

**Takeaway:** the *plumbing* for the model exists (encrypted forwarding, unique ids, dedup,
carry-forward, a proven sim). What's missing is on the **devices**: they hold almost no data of their
own, and every conversation they have is with Station.

## 2. Station-central assumptions (each blocks T1 or T2)

| # | Assumption | Where | Consequence when Station is gone |
|---|---|---|---|
| S1 | Scout talks to exactly one compiled-in destination (`WAYPOST_STATION_DEST_HASH`) | `station_link.cpp`, `platformio.ini` | Scout can't talk to anyone else |
| S2 | Scout apps fetch live; nothing is stored on the Scout (messages, history, Beacon, Fieldbook) | `app_dispatch.cpp`, `app_beacon.cpp`, `app_fieldbook.cpp` | Empty screens; can't read old messages |
| S3 | Compose = immediate `MSG_SEND` to Station; failure = "not sent" | `app_dispatch.cpp` | No offline compose or outbox |
| S4 | Who a device acts for is only known by Station (`device_bindings`), checked on every request | `pairing.py`, `dispatch/service.py` sender rule | Nobody else can tell who sent what |
| S5 | Accounts/passwords exist only on Station; `WHOAMI`/`PAIR_REDEEM` need it | `services/auth` | No new sign-ins anywhere else (acceptable); but also no offline verification (not acceptable) |
| S6 | Pending messages live per user at Station; delivery = Station pushes | `DispatchStore`, `MSG_SYNC` | Messages stop |
| S7 | Contacts/directory only from Station's `ROLL_LIST` | `rollcall.py` | Fine once cached ✅ — but no key material in it for verifying |
| S8 | Outposts only talk to Station (`BOARD_SYNC`, `BEACON_SYNC`, `OUTPOST_CLAIM`); relaying is only raw Reticulum forwarding | `firmware/outpost` | Outpost relays packets nobody can use; no local messaging |
| S9 | Beacon alerts are pushed **only** by Station | `beacon/service.py` | A Beacon raised at an Outpost or Scout reaches nobody |
| S10 | Station "is" the network in docs: system context draws a hub with spokes; "Comms rule" is framed as an exception | `architecture.md`, `roadmap.md` | Design drift toward hub-and-spoke |
| S11 | Message ids are 64-bit and ids for rooms are slugs | `envelope.py`, Dispatch rooms | Collisions become plausible across long-lived islands |
| S12 | Outpost's notes are in RAM; queue not power-safe | `firmware/outpost` | Power cut loses local data |

## 3. Components that remain unchanged

- **Service names and their HTTP/portal/Waylink APIs** — Dispatch, Postbox, Noticeboard, Beacon,
  Fieldbook, Commons, Locker, Rollcall, Corkboard, Trailhead, Signal, Finder, Groups, Control.
  Station keeps serving them exactly as today.
- **Waylink envelope** (`v, mid, rid, src, dst, svc, op, flags, ts, ttl, payload`) and CBOR.
  New ops are added, none removed.
- **Reticulum** as the encrypted packet layer, on all three device types.
- **Radio-sized replies** (383-byte rule, `shared/protocol/radio.py`) and progressive retrieval.
- **Station storage, portal, auth (N2), pairing codes (M4), admin approval, groups.**
- **Scout firmware architecture:** background radio task, canvas UI, apps, USB remote, boot flow.
- **Outpost firmware:** Wi-Fi AP, captive portal, Corkboard, walk-up Beacon, auto-claim, OLED.
- **Hardware:** T-Deck Scout, Heltec V3 Outpost, RNode Station radio. No new hardware needed for
  T1–T3 (a second T-Deck is needed to *test* Scout-to-Scout for real).
- **The sim** (`peer.py`, `outpost.py`, `MockMesh`) — becomes the test bed for the sync protocol.

## 4. Components that need refactoring

| Component | Change | Kind |
|---|---|---|
| Scout `station_link` | Becomes `link`: talks to *any* peer by destination hash; Station is one peer among several, chosen by capability | 🔧 |
| Scout storage | Local object store on flash/SD: own messages, receipts, outbox, carried objects, Beacon, contacts with keys, identity certs | 🔧 (new module, apps read from it) |
| Scout apps | Read from the local store; network fills the store in the background. UI status line from capabilities | 🔧 (incremental per app) |
| Dispatch messages | Become signed `dispatch.msg` objects with 128-bit ids; receipts become objects | 🔧 (wire-compatible: `MSG_SEND` keeps working) |
| `MSG_SYNC` | Generalized into `SYNC_HELLO/DIFF/WANT/PUT` for every object kind; `MSG_SYNC` kept as a shim | 🔧 |
| Station sender rule (S4) | Accept a message whose signature verifies against the author's identity key, regardless of which node delivered it (replaces `is_trusted_courier`) — ✅ for signed messages 2026-10-04/05 | 🔧 |
| Pairing (`PAIR_REDEEM`) | Scouts now sign in with username + password (identity key) instead — ✅ 2026-10-05 | 🔧 done |
| Rollcall `ROLL_LIST` | Contacts' identity certificates fetched separately (`CERT_GET`) and cached — ✅ 2026-10-05 | 🔧 done |
| Beacon | `beacon.event` objects spread by sync from any node; Station's push becomes one source among many | 🔧 |
| Outpost firmware | Object store in flash; runs the sync protocol with Scouts, Outposts, and Station; delivers locally; capability announce; Wi-Fi Dispatch/Noticeboard pages | 🔧 (largest piece) |
| Announces | Capability record in `app_data` (generalizes the auto-claim marker) | 🔧 additive |
| `new_id()` | 128-bit for objects; Waylink `mid` may stay short | 🔧 small |
| Docs | architecture/roadmap reframed as peer network with Station as the best peer | 🔧 (this commit) |

## 5. Will the revised plan pass the tests?

| Test | Blocked today by | Unblocked by (roadmap step in [roadmap.md](roadmap.md#decentralization-track-dependency-order)) |
|---|---|---|
| **T1** Station unplugged, 2 Scouts + Outpost useful | S1, S2, S3, S4, S6, S8, S9 | D1 local store → D2 identity certs → D3 objects + signing → D4 peer link + sync → D5 Outpost sync |
| **T2** Station returns, reconciles | S6 (Station only accepts its own pending), S4 | D4/D5: same sync with Station as just another peer; Station verifies signatures, dedups by oid |
| **T3** New device adds capability only | S1 (compiled-in hash), S10 | D6 capability announce; peers chosen by capability |
