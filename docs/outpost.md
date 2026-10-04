# Waypost Outpost — design

**Status:** design (2026-10-04), building on the working firmware in `firmware/outpost` (Heltec V3).
Model: [network-model.md](network-model.md). Hardware: [hardware/heltec-wifi-lora-32.md](hardware/heltec-wifi-lora-32.md),
[hardware/makerhawk-v3.md](hardware/makerhawk-v3.md).

An Outpost is **fixed local infrastructure that keeps working on its own**. It doesn't depend on
Station: it adds range, storage, and a place to take part for people with no Scout.

## What it does — and where each part stands

| Capability | Status |
|---|---|
| Reticulum transport node: forwards encrypted packets for others | ✅ hardware |
| Persistent device identity, OLED role label, button-toggled auto-claim | ✅ hardware |
| Wi-Fi AP `WAYPOST-OUTPOST` with captive portal; Corkboard read/post; walk-up Beacon report | ✅ hardware |
| Corkboard sync to Station (`BOARD_SYNC`), Beacon reports to Station (`BEACON_SYNC`), claim | ✅ hardware |
| Notes and queues survive power loss | 🔧 notes are RAM-only today → flash object store |
| **Object store** (flash, bounded): messages, receipts, notices, Beacon events, identity certs, revocations, cached Fieldbook pages | 📋 |
| **Peer sync** (`SYNC_*`) with Scouts, other Outposts, Station — same protocol for all | 📋 (sim precursor: `OutpostNode`) |
| **Local delivery:** a message for someone whose Scout is in range or who is signed in on Wi-Fi is delivered at once, and still synced onward | 📋 ([mesh-delivery.md](mesh-delivery.md)) |
| **Capability announce** (services, Station reachability, "has objects for") | 📋 (precedent: auto-claim marker ✅) |
| **Offline identity checks** with cached certificates and revocations | 📋 |
| Local **Noticeboard** for its area, cached **Fieldbook** pages (read on Wi-Fi) | 📋 |
| Wi-Fi **Dispatch page** for signed-in people (inbox, reply) | 📋 |
| **Beacon spread:** raises a walk-up Beacon *locally* (alerts Scouts in range) as well as toward Station | 📋 (🔧 today only sends to Station) |

## Store and retention

Heltec V3: ~1.5 MB LittleFS free after firmware (measure). Budget, in priority order:
identity certs + revocations (small, always kept) → Beacon events (until expiry) → messages and
receipts for users seen here recently → objects being carried toward Station → Noticeboard for the
area → Fieldbook cache (evicted first). A carried object is dropped once Station's archive receipt is
seen, or at expiry; the Outpost's own Corkboard notes stay (Outpost-primary, as today).

## Uplinks

LoRa only (normal), Wi-Fi client / Ethernet to Station (Tier 2, later), Internet (never required),
or **none for weeks** — a Courier walking by is the uplink. The Outpost never assumes the uplink is up.

## Signing in without a Scout

Someone on the Outpost's Wi-Fi with a phone wants to read and send Dispatch messages as themselves.
The Outpost holds no passwords and Station may be unreachable. Options:

1. **Sign-in code from Station, cached session** (from [mesh-delivery.md](mesh-delivery.md)):
   the person gets a one-time code on the portal or their Scout, the Outpost checks it with Station
   once, and Station returns a signed session good for some hours. Needs Station *at sign-in*.
2. **Scout vouches:** the person's own Scout, in range, signs "let this browser act for me at
   Outpost X for N hours". Works with no Station. Needs the Scout present.
3. **Outpost-local passcode, offline-verifiable:** at pairing time the person can set an *Outpost
   passcode*; Station puts a slow salted hash of it (or a passcode-wrapped key) in the identity
   certificate, which every Outpost caches. The Outpost verifies locally. Works with no Station and
   no Scout. Risk: a stolen Outpost allows offline guessing against cached hashes — mitigated by a
   strong KDF, a separate passcode (never the account password), and certificate expiry.

**Recommendation:** ship (2) and (1) first; offer (3) as an opt-in per person. The browser session
the Outpost issues is local to that Outpost and expires. Messages sent from it are signed by the
**Outpost's** key on the person's behalf, with a "via Outpost X" marker. That's weaker than a Scout's
own signature and is shown as such.

## Firmware structure (incremental)

`firmware/outpost/src/main.cpp` is a single file today. Split as features land:
`store.*` (flash object store), `sync.*` (`SYNC_*` engine; the same C++ shared with the Scout via a
common lib), `caps.*` (announce record), `web_*.cpp` (Wi-Fi pages), keeping the current handlers.
The sync engine and the object codec go into a library shared by Outpost and Scout
(`firmware/common/` 📋) so the two devices can't drift.
