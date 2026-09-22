# Waypost project plan

Single source of truth for **what we’re building**, **what’s done**, and **what’s next**.  
Prefer small, testable vertical slices. Do not expand scope mid-slice without updating this doc.

Related: [architecture.md](architecture.md) · [protocol.md](protocol.md) · [naming.md](naming.md) · [security.md](security.md) · [priority-review.md](priority-review.md)

---

## North star

An off-grid community network you can run without the Internet:

| Piece | Intent |
|-------|--------|
| **Waypost Station** | Raspberry Pi hub — Wi‑Fi apps + Waylink gateway |
| **Waygate** | Captive portal when joining community Wi‑Fi |
| **Waylink** | Compact RPC over LoRa (not HTML-over-radio) |
| **Waypost Pocket** | Handheld (T-Deck class) — Cybiko-like personal device |
| **Waypost Outpost** | Cheap ESP32 LoRa hop nodes |

**Design rule:** full-bandwidth community computing on local Wi‑Fi; the *important* stuff still works slowly over LoRa.

**Comms rule (non‑negotiable):** Station is the best sync hub and portal, but **Pockets must keep working when there is no path to Station.** Pocket↔Pocket (and Pocket↔Outpost↔Pocket) delivery is first-class. Devices **store-and-forward** for each other; a recipient **reads a message meant for them immediately**, and still **carries a copy toward Station** (or the next hop that can reach it) so the network converges when someone gets in range.

**First architecture proof (E2E):**

```text
Peer device ──LoRa──► Station radio ──► Station API ──► Web portal
                 ◄──────────────────────────────────────┘
```

Bidirectional **Dispatch** over that path proves the stack. Everything else builds on that spine.

---

## Working principles

1. **Laptop-first vertical slices** — ship testable API + portal (+ hardware when available) before Pi install polish.  
2. **One transport interface** — apps never talk Reticulum/Heltec/Meshtastic directly (`MockTransport` → `SerialBridgeTransport` → `ReticulumTransport`).  
3. **Progressive retrieval** — summaries before bodies; never push large files over LoRa.  
4. **Honest status** — prototypes are prototypes; update this plan when reality changes.  
5. **Hardware claims need measurement** — GPIO, antennas, duty cycle: verify, don’t assume.

---

## Where we are (honest snapshot)

**Date context:** early alpha · development on Linux laptop · two Heltec WiFi LoRa 32 **V3** boards in use.

### Done — useful on a laptop today

| Area | Status |
|------|--------|
| Repo, ADRs, naming, protocol, security, deploy templates | Done |
| Station API (FastAPI + SQLite) + health/meta | Done |
| Portal shell + home dashboard | Done |
| **Dispatch** (HTTP DMs/rooms, mock Pocket, queue) | Prototype |
| **Postbox** (local mailbox, OUTBOX flush) | Prototype |
| **Rollcall** | Prototype |
| **Commons** | Prototype |
| **Noticeboard** | Prototype |
| **Beacon** | Prototype |
| **Locker** (upload/download shared + personal) | Prototype |
| **Signal** (diagnostics, USB radio list, air test) | Prototype |
| Screenshot + pytest automation | Done |
| Waylink `MockTransport` + gateway | Done |
| Heltec USB↔LoRa bridge firmware | Done |
| Heltec **air path** + Waylink `PING`/`PONG` | **Proven on hardware** |
| Dispatch **over LoRa** into portal (Heltec) | **Proven (M2c)** — see [radio-dev.md](radio-dev.md) |

### Explicitly not done

| Area | Gap |
|------|-----|
| Raspberry Pi Station install | Templates only — no “plug in and join WAYPOST Wi‑Fi” product |
| Waygate / hostapd / dnsmasq on real Pi | Not validated on hardware |
| `ReticulumTransport` / production RNode path | Stub |
| Pocket (T-Deck) firmware / UI | Not started |
| Pocket GPS → Station location reports | Not started (planned under M7/M8) |
| **Atlas** (map, Station origin, range/distance) | Not started |
| Outpost (MakerHawk) firmware | Not started — GPIO unverified |
| Stalwart / BookStack / Memos / Kiwix adapters | Placeholders |
| Real identity (OIDC, passwords, invite flows) | Dev users only |
| Fieldbook, Archive, Finder, Control | Not built (or nav “soon” only) |

Apps marked *prototype* mean: local store + HTTP UI + some Waylink RPC ops — **not** production auth, sync, or multi-Station federation.

---

## Priority spine (dependency order)

Do **not** optimize for app count. Prefer:

```text
transport proof → resilient messaging → identity/presence → shared sync
  → mail/wiki → notices/beacon → groups → community apps
  → Pocket platform (Logbook/Workshop/…)
```

Full analysis: **[priority-review.md](priority-review.md)**.  
Foundational designs (implement later): [offline-sync.md](offline-sync.md) · [identity.md](identity.md) · [groups-and-permissions.md](groups-and-permissions.md) · [provisioning.md](provisioning.md) · [network-time.md](network-time.md) · [federation-future.md](federation-future.md).

### Just finished — **M2e Production radio crypto** ✅

**Goal:** Encrypt LoRa Waylink (Reticulum/RNode). N2 username/password auth is ✅.

**M2e:** `ReticulumTransport` + Dispatch-over-RNS (`dispatch_rns_airtest` PASS on TCP lab). `RNodeInterface` config (`WAYPOST_RNS_INTERFACE=rnode` + validated radio params), `dispatch_rns_airtest --rnode`, and Signal shows link security. **Over-air PASS 2026-09-22:** encrypted Dispatch (send, portal history, `MSG_PUSH` reply) between two Heltec V3 boards flashed as RNodes ([radio-dev](radio-dev.md#encrypted-over-real-lora-rnode)). Remaining: run as the default on the Pi Station (M1b) and retire plaintext Heltec from anything user-facing.

**Next:** M1b Pi AP + TLS (waits on Pi SSH); Wi‑Fi TLS is the remaining "all communications encrypted" gap. Heltec bridge firmware stays **lab plaintext** only.

**Still freeze:** new portal apps; Atlas; Workshop.

---

## Milestone plan (history + future)

Each milestone has a **goal**, **exit criteria**, and **out of scope**. Completed milestones stay for history.

### M0 — Foundation ✅

**Goal:** Repo and design can be reasoned about without hardware.

**Exit criteria:** Architecture, naming, protocol, security, ADRs, MockTransport, monorepo layout.

---

### M1 — Laptop Station slice ✅ (apps) / 🟡 (Pi networking)

**Goal:** Developers can run a Station API + portal on any Linux laptop and exercise core community apps without radios.

| Track | Status | Exit criteria |
|-------|--------|----------------|
| **M1a API + portal apps** | ✅ | Dispatch, Postbox, Rollcall, Commons, Noticeboard, Beacon, Locker, Signal prototypes; tests green |
| **M1b Pi network stack** | 🟡 | Templates exist; **not** validated: hostapd + dnsmasq + Waygate + Caddy on a real Pi |

**Success for “real Station” still pending:** Pi boots → SSID `WAYPOST` → DHCP/DNS → Waygate → homepage.

**Do not** treat M1b as blocking radio work — N1 and Heltec proof proceed on laptop.

---

### M2 — Waylink radio vertical slice ✅ (Heltec stand-in)

**Goal:** Prove Station ↔ peer messaging over LoRa using the same envelope/gateway path apps will use.

| Step | Status | Exit criteria |
|------|--------|----------------|
| **M2a** Heltec USB bridge + host framing | ✅ | Firmware flashed; `ECHO`/`STAT`; device detection in Signal |
| **M2b** Bidirectional air + `PING`/`PONG` | ✅ | `tools.radio.airtest` + `peer_pong`/`ping` succeed on two V3 boards |
| **M2c** Dispatch over Heltec link | ✅ | Peer Heltec → portal Dispatch; portal reply → peer `MSG_PUSH` |
| **M2d** Radio-dev runbook | ✅ | [radio-dev.md](radio-dev.md); Signal shows live radio state |
| **M2e** RNode + Reticulum path | ✅ | `ReticulumTransport` replaces Heltec without app changes; over-air PASS on RNode-flashed V3 |

**Stand-in exit:** Bidirectional Dispatch over Heltec — **met**. Production mesh = M2e / Tier 2.

---

### N1 — Opportunistic Dispatch ✅

**Goal:** Queued Dispatch delivers when the peer reappears — portal + Heltec LoRa; pending sync visible.

**Exit criteria:** [priority-review.md](priority-review.md) §8 — **met** (`dispatch_airtest --appear-later`, Signal sync, pytest).

---

### N2 — Account auth (username / password) ✅

**Goal:** Register and login on Station; same credentials for Pocket over Wi‑Fi; session-protected APIs.

**Exit criteria:**
- Register + login endpoints; password hashed at rest  
- Portal login/register UI; unauthenticated users redirected  
- Mutating / private APIs require session (except health/meta and auth routes)  
- Pocket can `POST /api/auth/login` with same username/password and receive a Bearer token  
- pytest covers register/login/reject-bad-password; existing tests use test-env auth bypass or login helper  
- Docs: passwords never over LoRa; encryption matrix in security.md  

**Out of scope:** Stalwart, OIDC, TLS termination on laptop, LoRa encryption (M2e).

---

### M2e — Production radio crypto (elevated) ✅

**Goal:** Replace Heltec plaintext stand-in with **encrypted** Waylink (Reticulum/RNode or accepted equivalent).

**Exit criteria:** App-level Dispatch unchanged; air traffic not readable as clear CBOR; documented in security.md.

**Progress:** Exit criteria met 2026-09-22 — encrypted Dispatch E2E over TCP lab and over LoRa (`dispatch_rns_airtest --rnode` PASS, Heltec V3 as RNode, RNode firmware 1.86).

**Why elevated:** “All communications encrypted” cannot be claimed on Heltec bridge alone.

**Depends on:** N2 ✅.

---

### M3 — Dispatch hardening (mesh semantics) 🟡

**Goal:** Same conversation on Wi‑Fi and LoRa — including **no Station** (sim first, then hardware).

**Exit criteria:** Shared queue states ([offline-sync.md](offline-sync.md)); peer A→B without Station; carry-forward exercised; Wi‑Fi↔LoRa failover.

**Progress:** `PeerDispatchNode` proves peer→peer Dispatch with **no Station**, `MSG_SYNC` carry-forward (dedup by `mid`, pending piggyback), **multi-hop courier** (`handoff_to` one-hop carry; peers only push at 1 hop), **MSG_SYNC authz** (bound device must match username), and **Wi‑Fi↔LoRa failover** (retry across paths dedups by `mid`; pending is durable until any device confirms, survives Station restart, and a confirm on one path drops the other path's copy). Tests in `server/tests/test_mesh_dispatch.py`. Sim exit criteria met. **Still open:** hardware / Outpost multi-hop (M6); Pocket firmware (M7).

**Depends on:** N1 ✅. Prefer N2 auth before multi-user mesh demos.

---

### M4 — Identity depth (Stalwart / OIDC / pairing UX)

**Goal:** Production identity authority; polished Pocket pairing; revocation UX.

**Exit criteria:** Stalwart path or scheduled cutover; pairing codes; registration modes enforced in UI.
---

### M5 — Postbox + Fieldbook (progressive)

**Goal:** Mail and wiki usable off-grid without giant sync.

**Exit criteria:** Postbox LoRa `STATUS→LIST→GET→SEND`; Fieldbook search→page→section; offline edits via shared sync; Pocket favorites cache design.

---

### M6 — Outpost + Pocket courier network

**Goal:** Multi-hop and delay-tolerant coverage; Outposts **and** Pockets forward.

**Exit criteria:** MakerHawk pinout verified; transport-node firmware; Pocket↔Outpost↔Pocket + courier-to-Station smoke; queues survive power cycle. Recipient reads now; copy still syncs to Station (`mid` dedup).

---

### M7 — Pocket environment (T-Deck Plus)

**Goal:** Handheld computer + GPS reports + on-device courier queue.

**Exit criteria:** Shell; Dispatch over Waylink; `/waypost/courier/`; `LOC_REPORT` every 10–15 min; Station pairing.

---

### M8 — Groups, Today view, Notice/Beacon polish

**Goal:** Shared authz + homepage that answers what happened / what’s waiting; trustworthy notices and Beacon.

**Exit criteria:** Groups used by ≥2 services ([groups-and-permissions.md](groups-and-permissions.md)); Today aggregates unread + sync; Notice ack; Beacon auth + replay protection.

---

### M9 — Atlas

**Goal:** Camp map — static Station origin (snapshot from a Pocket GPS) + Pocket positions + range/distance.

**Exit criteria:** Origin snapshot ≠ tracking; stale markers; `LOC_*` / `ORIGIN_*`; offline tiles spike.

---

### M10 — Archive, Commons/Locker depth, resilience

**Goal:** Wi‑Fi-first community depth + survive power loss.

**Exit criteria:** Kiwix/Archive; Commons/Locker beyond prototype; backups; network-time hardening ([network-time.md](network-time.md)).

---

### M11 — Pocket platform expansion

**Goal:** Logbook, Planner, Workshop/Lua, Arcade — after networking is trustworthy.

---

### M1b — Pi network stack (parallel track)

**Goal:** Real Station Wi‑Fi product path.

**Exit criteria:** Pi boots → SSID `WAYPOST` → Waygate → homepage. **Does not block N1.** Schedule when camp Wi‑Fi is the blocker.

---

## Near-term queue (do in order)

1. ~~**M2e** radio transport crypto~~ ✅ (over-air PASS 2026-09-22)  
2. **M3** mesh/sim peer + shared sync adoption — sim ✅; hardware with Pocket firmware  
3. **Hardware spikes (parallel):** MakerHawk GPIO; T-Deck Plus  
4. **M1b Pi AP + TLS** when camp Wi‑Fi is the blocker  
5. Then M4 Stalwart → M5 → M6/M7  

**Do not:** Atlas, Workshop, or new portal apps before M2e/M3 network depth.

---

## App maturity matrix

| App | HTTP prototype | Waylink RPC | Over LoRa (air) | Production backend |
|-----|----------------|-------------|-----------------|--------------------|
| Dispatch | ✅ | Partial | ✅ M2c | — |
| Postbox | ✅ | Partial | ⬜ | Stalwart later |
| Rollcall | ✅ | — | ⬜ | — |
| Commons | ✅ | Partial | ⬜ | Memos later |
| Noticeboard | ✅ | Partial | ⬜ | — |
| Beacon | ✅ | Partial | ⬜ | — |
| Locker | ✅ | Metadata only | N/A (Wi‑Fi bodies) | — |
| Signal | ✅ | Partial | ✅ airtest/ping | — |
| Fieldbook | ⬜ | Spec only | ⬜ | BookStack later |
| **Atlas** | ⬜ | Spec (M9) | ⬜ `LOC_*` | Offline tiles on Station |
| Finder / Archive / Control | ⬜ | Spec / stub | ⬜ | — |

---

## Decision log (plan hygiene)

| Decision | Choice | Why |
|----------|--------|-----|
| Dev radios before RNode | Heltec V3 USB bridge | Hardware on hand; proves framing + air before Reticulum |
| Community apps before Pi AP | M1a before M1b | Unblocks UX/protocol learning on laptop |
| Apps before full identity | Dev users `aj`/`bob` | Faster slices; M4 replaces this deliberately |
| Reticulum still the production Waylink target | ADR 0002 | Heltec bridge is a stand-in transport, not the end state |
| Station camp position = snapshot from a Pocket GPS | Operator picks a Pocket fix → Station stores static origin | Station / Heltec / Outposts have no GPS; Station must not “follow” a device |
| Product hop nodes named **Outpost** | Not “Relay” | Clearer camp metaphor; “relay” remains an OK verb for forwarding |
| Pocket location cadence ~10–15 min | Default report interval | LoRa duty cycle + battery; not live tracking |
| Pocket↔Pocket works without Station | Direct + Outpost + Pocket-as-courier | Camp life must not depend on the Pi being reachable |
| Recipient reads now, still syncs to Station | Local delivery + durable `mid` sync later | Portal/history converge without blocking the human conversation |
| **Next build = N2 username/password auth** | One account for portal + Pocket | Overdue; passwordless Station is not community-safe |
| Production LoRa must be encrypted | M2e Reticulum (Heltec = lab only) | Cleartext CBOR on air is unacceptable for real camps |

When we change direction, add a row here and adjust milestones above.

---

## How to use this doc

- Before a coding session: read **Active milestone (N1)** and [priority-review.md](priority-review.md).  
- After a slice ships: mark the step ✅, update the **honest snapshot**, fix README status if user-facing claims changed.  
- Resist “while we’re here” features that aren’t on the near-term queue — park them under a later milestone instead.
