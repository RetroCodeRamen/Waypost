# Waypost network model

**Status:** architectural direction, adopted 2026-10-04. Refines (does not replace) the existing
architecture — see [decentralization-review.md](decentralization-review.md) for what already fits,
what changes, and why. Every section is tagged:

- **✅ implemented** — works today (on hardware unless noted "sim").
- **🟡 partial** — some of it exists; the gap is named.
- **📋 planned** — designed here, not built.
- **🔧 change** — architectural change to something that exists.

Related: [architecture.md](architecture.md) · [identity.md](identity.md) · [protocol.md](protocol.md) ·
[outpost.md](outpost.md) · [hardware/scout.md](hardware/scout.md) · [roadmap.md](roadmap.md)

---

## 1. The rule

> **No individual Waypost device is strictly necessary for the network to function.** Every device
> adds capability, range, storage, convenience, or persistence; local communication continues when
> other infrastructure disappears.

Waypost is **local-first, offline-first, store-and-forward, opportunistically connected, and
eventually synchronized.** The Station enhances the network; it does not create it.

Acceptance tests (every milestone is judged against these):

| | Test |
|---|---|
| **T1** | If Station is unplugged, two Scouts and an Outpost still form a useful Waypost network. |
| **T2** | When Station comes back, the network reconciles what happened while it was gone, with no manual rebuilding. |
| **T3** | Adding another Waypost device adds capability, never a new mandatory dependency. |

Non-goal: reproducing Internet-style routed mesh or TCP/IP over LoRa. Prefer opportunistic delivery,
store-and-forward, object sync, caching, local discovery, and simple forwarding rules. Reticulum is
kept as the encrypted packet substrate (it already gives identities, encryption, announces, and
simple forwarding); Waypost's own logic lives in objects and sync, not in routing.

---

## 2. Roles

Roles describe what a node *offers*, not a hierarchy. Any node can be absent.

### Station — headquarters, archive, sync hub, recovery point
Most capable and most persistent. Normally holds the most complete copy of everything:
canonical history, Fieldbook/Commons/Locker/Noticeboard archives, account recovery, the
**community key** that signs identities (§7), revocations, administration, the web portal,
optional Internet, backups, and a dependable rendezvous for messages to people who are away.
**Not** required for any single interaction. 🔧 *Today it is required for most* — see the review.

### Outpost — fixed local infrastructure
Extends Waypost into an area and runs on its own for long periods: relays and stores messages,
caches identity certificates and authenticates offline, caches popular Fieldbook pages and local
Noticeboard, syncs with Scouts, other Outposts, and Station whenever it can, and offers a Wi-Fi
page so people without a Scout can take part. Uplink may be LoRa only, Wi-Fi, Ethernet, Internet,
or intermittent. Design: [outpost.md](outpost.md).

### Scout — the personal device (T-Deck)
The complete personal Waypost: identity/login, direct Scout-to-Scout, Scout-to-Outpost, local
storage of messages, offline composition, delayed delivery, opportunistic sync, cached pages,
Noticeboard, local discovery. Must stay useful if Station disappears entirely; two Scouts in range
must be able to talk with nothing else. Plan: [hardware/scout.md](hardware/scout.md).

### Courier — physical store-and-forward (a role, not a device)
Any node that physically moves (a Scout in a pocket, a laptop, an Outpost being relocated) can carry
objects between isolated islands: Scout → Courier → Outpost, Outpost → Courier → Outpost, Scout →
Courier → Scout, and eventually anything → Station. A first-class transport: the sync protocol
assumes **no** realtime end-to-end path, ever. 🟡 *Sim only* (`PeerDispatchNode.handoff_to`,
`OutpostNode`, hop caps, TTL — `server/services/dispatch/`).

---

## 3. Objects — one data model for every service  📋 (🟡 Dispatch has a precursor)

Everything that moves between nodes is an **object**. Services (Dispatch, Postbox, Noticeboard,
Beacon, Fieldbook, Commons, Corkboard, Rollcall, Locker metadata, identity) define object *kinds*;
the network only moves objects.

```text
Object
  oid      128-bit random id, created once by the author's device, never reused
  kind     "dispatch.msg" | "dispatch.receipt" | "postbox.mail" | "noticeboard.notice" |
           "beacon.event" | "fieldbook.rev" | "commons.post" | "corkboard.note" |
           "rollcall.presence" | "identity.cert" | "identity.revoke" | ...
  author   identity id of the person (§7), plus the signing device id
  created  author's clock (ms) — informative only; nothing depends on clocks agreeing
  scope    who it is for: public | area:<id> | user:<identity> | conv:<id> | group:<id>
  refs     oids it builds on (revision parent, reply-to, the message a receipt confirms)
  expires  optional (Beacon, presence, notices)
  body     kind-specific, small
  sig      author device's signature over the canonical bytes of everything above
```

Rules:
- **Immutable.** An object never changes. Edits, deletions, state changes are *new* objects that
  reference older ones (a Fieldbook revision references its parent; a receipt references a
  message; a Beacon clear references the push). State is *derived*: "delivered" = a receipt exists;
  "Beacon active" = a push with no clear after it. This is what makes merging trivial.
- **Signed by the author's device**, verifiable offline (§7). Relays may read objects they carry
  (decided 2026-10-04) but cannot forge or alter them.
- **Size classes** decide which transports may carry them (§9): *small* (≤ one LoRa packet:
  messages ≤140 bytes, receipts, presence, revocations, Beacon, manifests) vs *large* (Fieldbook
  pages, Commons posts with media, files, batches).
- Conversation ids stay **deterministic** where they already are (`dm:<a>:<b>`), so copies of the
  same conversation created on different islands merge. ✅ Rooms get an oid-based id (today a slug
  — two islands could pick the same slug 🔧).

Existing precursors: Waylink `Envelope.mid` ✅; Dispatch messages keyed by id with `MSG_SYNC`
carry-forward ✅ (sim + Station); Fieldbook revisions with `base_revision` conflict detection ✅;
Corkboard notes with `synced_at` and Outpost-primary copies ✅; Beacon events deduped by `mid` ✅.

---

## 4. Deduplication — foundational  🟡

The same object legitimately arrives by several routes. Duplicates must collapse at every node.

- **One id, forever:** `oid` is generated once, by the author's device, 128 bits of randomness.
  🔧 Today `new_id()` is 64 bits (`uuid4().hex[:16]`, `shared/protocol/envelope.py`) — fine for one
  Station, too small for a long-lived multi-island network. Widen to 128 bits for objects; keep the
  short form for transient Waylink `mid`/`rid` (request/reply correlation only).
- **Store keyed by oid**, insert-if-absent. ✅ Dispatch (`messages.id` primary key), Beacon
  (`mid UNIQUE`), Corkboard (`id`), gateway `_seen_mids` (in memory). 🔧 Becomes one object store per
  node instead of per-service tables plus per-transport caches.
- **Seen-set for things not kept** (a Scout that relayed but didn't store): bounded set of recent
  oids so a carried object isn't re-offered in a loop. ✅ precursor: `WaylinkPeerNode._seen_mids`.
- **Derived state never double-counts:** two copies of a receipt are one receipt.

---

## 5. Peer synchronization — one protocol, every node  📋 (🟡 `MSG_SYNC`)

Not "messages waiting to reach Station" but **"objects this node knows that the other may not."**
Same protocol whether the peer is a Scout, Outpost, Courier, or Station; what differs is
**interest** (what each wants), **capacity** (what it can hold), and **link** (what the transport
can carry).

```text
A ⇄ B   SYNC_HELLO   who I am, capabilities (§6), my interests, a summary of what I hold
A ⇄ B   SYNC_DIFF    narrow down which buckets differ (only where summaries disagree)
A → B   SYNC_WANT    the oids I'm missing
B → A   SYNC_PUT     the objects (one per packet on long-range links, batches on fast links)
both    receipts / custody notes as ordinary objects
```

**Summaries:** objects are bucketed by oid prefix within each interest scope. A summary is
per-bucket (count, XOR of oids). Equal buckets are skipped; unequal buckets are split further
(next hex digit) until the differing oids are listed. Two nodes that are mostly in sync exchange a
few hundred bytes. The top-level summary fits one LoRa packet.

**Interests** (what a node asks for):
- Scout: its own user's conversations and mail, public Noticeboard/Beacon for its area, identity
  certificates and revocations, pinned Fieldbook pages.
- Outpost: everything for its area, everything for users it has seen recently, plus whatever it is
  carrying toward Station.
- Courier (any carrying node): anything not expired, up to its capacity, newest and smallest first.
- Station: everything.

**Priority** on scarce links: Beacon > receipts > messages > revocations/identity > presence >
small notices > manifests > everything else.

**Retention / pruning:** a node may drop a carried object once it has seen the *terminal* receipts
(delivered to the recipient **and** archived at Station), or when it expires, or when capacity
forces it (oldest carried-for-others first; never the user's own unsent objects).

**Precursor ✅:** `MSG_SYNC` (Dispatch) — ingest carried copies, dedup by id, piggyback the peer's
pending, paged to one packet for radio devices. It becomes the Dispatch-only special case of
`SYNC_*` and is kept as a compatibility shim.

---

## 6. Capability discovery  📋 (🟡 announce `app_data`)

Devices advertise **what they can do**, not where they sit in a hierarchy:

> "I can relay messages." "I have Fieldbook pages." "I have messages for AJ." "I can reach Station."
> "I have newer Noticeboard entries." "I have 32 objects you may not have."

**Announce (Tier 1, periodic, tiny):** the Reticulum announce's `app_data` carries a compact CBOR
capability record (target ≤ 60 bytes):

| Field | Meaning |
|---|---|
| `r` | role bits: station / outpost / scout / courier-willing |
| `s` | services offered (bitmap: Dispatch, Postbox, Noticeboard, Beacon, Fieldbook, Commons, Locker, Rollcall, Corkboard, Trailhead, Signal) |
| `t` | transports available (long-range LoRa; Wi-Fi AP id; ESP-NOW; …) |
| `st` | Station reachability: direct / via-this-node / none, and how stale |
| `h` | "has objects for": a small Bloom filter of identity ids it holds undelivered objects for |
| `v` | sync summary version (changes whenever its object set changes) |

✅ Precedent: Outposts already put an auto-claim marker in announce `app_data`, and Station reads it.

**On demand:** `CAPS_GET` returns the full record (storage free, object counts per kind, Station
path age, area id). **Nearby view (Scout):** built from announces heard — "3 Scouts, 1 Outpost;
Station via Outpost (2 min ago)".

Not every node implements every service. A small Outpost may offer only Dispatch, Postbox, Beacon,
Noticeboard; Station offers everything. Clients choose peers by capability.

---

## 7. Identity — verifiable offline  📋 (🟡 device keys, pairing)

Four separate things:

| Thing | What | Today |
|---|---|---|
| **Username** | human-readable label (`aj`), can change | ✅ on Station |
| **Identity id** | stable id of the person, derived from a key, never a username/password hash | 📋 |
| **Credentials** | password / PIN — only ever unlock things locally | ✅ password on Station; ✅ Scout PIN (UI lock only) |
| **Device identity** | each device's own Reticulum keypair | ✅ Scout and Outpost, persisted |

**Design (v1, extends today's pairing):** full detail in [identity.md](identity.md#offline-identity-target).
- Station holds a **community key** (created at setup, backed up). Its public half is given to every
  device at pairing/claiming and cached everywhere.
- **Identity certificate** (object `identity.cert`): username, display name, identity id, issued,
  expiry, serial — signed by the community key.
- **Device certificate:** "device D acts for identity I until T" — signed by the community key at
  pairing (today's `PAIR_REDEEM` becomes "issue a device certificate").
- **Verifying offline:** any node with the community public key checks object signature → device
  cert → identity cert → not revoked. No Station contact.
- **Revocation** (object `identity.revoke`, signed by the community key) spreads at high priority.
- **Logging in on a Scout:** the PIN unlocks the device's private key, stored encrypted with a
  PIN-derived key (🔧 today the PIN only locks the UI).
- **People without a Scout at an Outpost:** see [outpost.md](outpost.md#signing-in-without-a-scout).
- **Passwords never travel the Waypost network.** ✅ already a rule.

---

## 8. Messaging over the model

Messaging has the highest priority and the longest practical range. A message is a `dispatch.msg`
object; a receipt is a `dispatch.receipt` object. Paths: Scout→Scout, Scout→Outpost,
Scout→Outpost→Scout, Scout→Courier→Outpost, Outpost→Outpost, Outpost→Station, Scout→Station, or any
mix. Delivery = the object reaching any device the recipient uses; Station *eventually* gets it.

Because Reticulum encrypts each packet for its addressee only, nodes don't "overhear" messages: each
hop *syncs* objects with the next. Hop-by-hop design: [mesh-delivery.md](mesh-delivery.md).

---

## 9. Transport strategy — long range vs local high throughput  📋

Two tiers. The user sees capabilities ("Messaging available", "Full sync available"), never
transports.

**Tier 1 — long range, critical.** LoRa, one network-wide PHY profile (a node only hears others on
the same profile). Carries *small* objects only: messages, receipts, identity/revocations, presence,
Beacon, small notices, sync summaries/manifests. Reach and reliability over speed.
- ✅ Today: SF8 / 125 kHz / CR 4:5 (~3.1 kbps), every reply sized to one encrypted Reticulum packet
  (383 bytes), listen-before-talk on the embedded radios.
- 📋 Choose the long-range profile by **field test** (range vs airtime at SF8–SF11), within the
  region's rules (e.g. US 915 MHz dwell-time limits on narrow channels) — not by guess.

**Tier 2 — local, high throughput.** Used when devices are close. Evaluated options:

| Option | For | Against | Verdict |
|---|---|---|---|
| **Wi-Fi** (Scout joins an Outpost's or Station's AP; Reticulum over UDP) | 100× LoRa; Outposts and Station already run APs; separate radio, so LoRa keeps listening | power; needs an AP | **First choice** for Scout↔Outpost/Station |
| **ESP-NOW** (ESP32 peer-to-peer Wi-Fi frames) | fast, no AP, ~100 m+, both Scout and Outpost chips have it | ESP32-only; small frames | **First choice** for Scout↔Scout |
| Fast LoRa profile (SF7 / 500 kHz) | no new radio | single radio: retuning makes the node deaf on Tier 1; needs rendezvous | later experiment |
| BLE | phones | slower than Wi-Fi, more complex | later (phone companion) |

**Automatic selection:** the sync engine sends small classes over any link and large classes only
over Tier 2 (a user can explicitly request one small page over Tier 1). Tier-2 availability is
advertised in announces (§6); a Scout turns Wi-Fi on only when a Tier-2 peer is near and there is
something large to move (battery). The same `SYNC_*` protocol runs on both tiers.

---

## 10. Graceful degradation

| What disappears | What still works |
|---|---|
| **Station** | Scouts and Outposts message each other and sync locally; Beacon spreads node to node; identities verify offline (cached certificates); Outposts serve their Wi-Fi users. Archive, recovery, new accounts, and anything needing the full history wait. |
| **Internet** | Everything except Internet-facing extras. Waypost never depends on it. |
| **An Outpost** | Scouts in range of each other keep talking directly; Couriers carry the rest. |
| **All infrastructure** | Two Scouts in range: messaging, receipts, Beacon, presence. Out of range: compose offline; delivered when any path appears. |
| **Everything but a Courier** | Objects propagate as the Courier moves between islands. |
| **Station returns** | Every node syncs with it opportunistically; Station receives everything that happened; portal history fills in; receipts flow back. No manual steps (T2). |

User view (Scout home):

```text
WAYPOST                      AJ
Nearby: 3 Scouts · 1 Outpost
Dispatch   available
Postbox    available
Fieldbook  local copies
Station    offline          → later: "reachable via Outpost", syncs quietly
```

---

## 11. How services ride on this

| Service | Object kinds | Notes |
|---|---|---|
| Dispatch | `dispatch.msg`, `dispatch.receipt` | realtime-ish store-and-forward; highest priority |
| Postbox | `postbox.mail` | asynchronous; bodies may be large (Tier 2) |
| Noticeboard | `noticeboard.notice`, `.ack`, `.expire` | area-scoped; small ones Tier 1 |
| Beacon | `beacon.event` (push/clear) | Tier 1 top priority; spreads node to node, not only from Station 🔧 |
| Fieldbook | `fieldbook.rev` | revisions are objects; heads derived; conflicts already handled by `base_revision` |
| Commons | `commons.post` | social feed |
| Corkboard | `corkboard.note` | already Outpost-primary ✅ |
| Rollcall | `rollcall.presence`, `identity.cert` | presence is ephemeral (expires) |
| Locker | metadata objects; file bodies Tier 2 only | |
| Trailhead | `trailhead.page` | Station-authored pages, cached |
| Signal | none — local diagnostics, reads capabilities | |
