# Waypost Priority Review

**Date:** 2026-09-18  
**Method:** Full repo inspection + architecture/roadmap/protocol/ADR review.  
**Intent:** Build order by dependency and network truth — not by app catalog completeness.

Related: [roadmap.md](roadmap.md) · [architecture.md](architecture.md) · [offline-sync.md](offline-sync.md) · [identity.md](identity.md) · [groups-and-permissions.md](groups-and-permissions.md) · [provisioning.md](provisioning.md) · [network-time.md](network-time.md) · [federation-future.md](federation-future.md)

---

## 1. Current state

### Working today (end-to-end)

| Capability | Kind |
|------------|------|
| Laptop Station API + SQLite + portal shell | Backend + frontend prototype |
| Dispatch DMs/rooms over **HTTP** (portal) | Backend + frontend prototype |
| Dispatch over **Heltec LoRa** (peer → Station → portal → peer `MSG_PUSH`) | **Real hardware** (M2c) |
| Waylink `PING`/`PONG`, framed USB↔LoRa bridge | **Real hardware** (M2b) |
| Mock Pocket / MockTransport | Simulated (CI) |
| Postbox, Commons, Noticeboard, Beacon, Locker, Rollcall, Signal | HTTP prototypes (+ partial Waylink RPC) |
| Heltec bridge firmware (`MAX_FRAME` 250) | Flashed / proven |
| pytest + Playwright screenshots | Automation |

### Partially working

| Area | Gap |
|------|-----|
| Dispatch | Station-centric only; no Pocket↔Pocket, no courier carry-forward, no `MSG_SYNC` handler |
| Delivery / offline | Pending queue when user has no bound node; not full opportunistic mesh delivery |
| Signal | Lists radios / airtest; no sync-queue visibility |
| Identity | Dev users; bind exists; no crypto device identity, pairing UX, revocation product |
| Pi / Waygate | Deploy templates only |
| ReticulumTransport | Stub (`NotImplementedError`) |
| Home dashboard | Aggregates some counts; not a real “Today / sync” surface |

### Not started (architectural / planned)

Pocket (T-Deck) firmware · Outpost (MakerHawk) firmware · Groups/permissions subsystem · Shared offline-sync subsystem · Network time · Provisioning product · Station↔Station federation · Fieldbook · Atlas · Finder · Archive · Workshop/Arcade · Stalwart/BookStack/Memos adapters

---

## 2. Strong parts of the architecture

- **Services ≠ transports** — `Transport` interface + Waylink gateway; apps speak `MSG_*` / `MAIL_*`.
- **Heltec stand-in proved the spine** without waiting for RNode — correct sequencing.
- **Durable `mid` + CBOR envelope** already in shared protocol.
- **Honest roadmap** and radio-dev runbook after M2c.
- **Comms rule documented:** Pocket↔Pocket + carry-to-Station is non-negotiable for later work.

---

## 3. Weak parts

- **App surface ahead of network depth** — eight portal prototypes vs one Station-mediated LoRa chat path.
- **Production Waylink missing** — Reticulum stub; Heltec is a bridge, not the end mesh stack.
- **No Pocket / Outpost code** — Priority-1 multi-hop tests are blocked on hardware + firmware.
- **250-byte LoRa frames** force compacted Dispatch payloads; easy to regress.
- **`MSG_SYNC` / courier / shared queue** — named in docs, not implemented.
- **Identity** still `aj`/`bob` with no device crypto story in code.

---

## 4. Missing foundational features

1. Opportunistic Dispatch (queue → auto-deliver when route/device appears)  
2. Shared offline / sync subsystem (states visible in Signal/Today)  
3. Account ≠ radio identity (pairing, revocation) — beyond ADR prose  
4. Network time without public NTP  
5. Provisioning (Pocket join + Outpost enroll)  
6. Groups as shared authz (rooms today ≠ Groups)  
7. Multi-hop Outpost path + Pocket-as-courier  
8. Federation / home-Station assumptions (document only for now)

---

## 5. Technical debt / risks

| Risk | Why it matters |
|------|----------------|
| Treating Heltec as production mesh | Will fight Reticulum/RNode if apps grow Heltec-specific assumptions |
| Per-app offline queues | Dispatch/mail already diverge; Fieldbook will fork again |
| Rooms ≠ Groups | Permission sprawl if each app invents ACL |
| Portal feature momentum | Tempting to polish Commons/Locker instead of transport |
| Clock skew | Notice/Beacon expiry and certs fail off-grid without Station time |
| Payload size | LoRa MAX_FRAME 250 — fragmentation or progressive ops needed before rich messages |

---

## 6. Build-order problems (corrected)

**Was:** alternate M1b Pi AP vs M2e Reticulum, then maybe M3.  
**Problem:** neither finishes *reliable messaging*; Pi AP doesn’t prove LoRa; jumping to Reticulum without hardening Dispatch semantics wastes the Heltec path we already have.

**Correct dependency spine:**

```text
proven air path (done)
  → resilient Station-mediated Dispatch + visible queues
    → production transport (Reticulum/RNode) and/or Outpost GPIO truth
      → Pocket comms foundation (T-Deck)
        → multi-hop + courier (Outpost + Pocket)
          → identity/presence depth
            → Postbox / Fieldbook / Notice+Beacon polish
              → Groups → Commons/Locker → Atlas/Archive → Pocket PDA apps
```

**Freeze:** new portal apps and deep Commons/Locker UX until Tier 1 exits.

---

## 7. Priority tiers (adjusted for repo reality)

### TIER 1 — Build now

- Harden **Dispatch** on existing Heltec Station↔peer path (retry, opportunistic deliver-on-bind/appear, reboot-safe queues where practical)  
- Shared **sync/queue** model (even if first consumer is Dispatch only) + Signal/Today visibility  
- Keep **radio regression** (`dispatch_airtest`, ping/pong) green  
- **Rollcall/identity groundwork:** device bind, last-seen, Wi‑Fi vs LoRa reachability labels (no full OIDC yet)  
- **MakerHawk GPIO verification** as a spike when hardware is in hand (unblock M6)  
- Document + keep Heltec as **dev transport**; do not expand Heltec-only features

**Adjustment vs review prompt:** Full `Pocket↔Outpost↔Station` multi-hop is Tier 1 *goal* but **blocked** without T-Deck + verified Outpost. Do not pretend otherwise — use Heltec + sim courier as interim.

### TIER 2 — Build next

- `ReticulumTransport` / RNode (or confirmed production radio)  
- T-Deck Pocket communications foundation (Dispatch + queue + sync-to-Station)  
- Outpost store-and-forward firmware  
- Pocket↔Outpost↔Pocket / courier smoke  
- Postbox progressive LoRa path  
- Fieldbook progressive path  
- Noticeboard ack + Beacon auth/propagation  
- Groups/permissions core  
- Unified Today / sync dashboard

### TIER 3 — After network is useful

- Commons depth · Locker group folders · Finder · Archive · **Atlas** (GPS/origin already designed — implement after Pocket reports exist)

### TIER 4 — Pocket platform expansion

- Logbook · Planner · Workshop/Lua · Arcade

---

## 8. Recommended next milestone (ONE)

### **N1 — Opportunistic Dispatch (Station + Heltec)**

**Goal:** A Dispatch message queued while the peer is unreachable is delivered automatically when that peer (or its radio binding) reappears — same conversation on portal and over LoRa.

**User story:** AJ sends Bob a message from the portal while Bob’s Heltec peer is offline. Bob’s radio comes back on `/dev/ttyUSB1` and re-binds. Bob’s radio Pocket receives the pending traffic without AJ resending. Bob replies over LoRa; AJ sees it in the portal.

**Required components:** Dispatch store/service, Waylink gateway, SerialBridgeTransport, Heltec bridges, `radio_pocket` / `dispatch_airtest`, Signal (queue counts), thin Rollcall last-seen touch.

**Hardware:** Two Heltec V3 USB bridges (already in use). No T-Deck/Outpost required for N1.

**Software:** Existing Station + radio tools; new work = opportunistic flush, retry/backoff, reboot-safe pending where practical, sync status API, airtest coverage for “appear later.”

**Acceptance tests:**
1. Portal send to unbound/offline peer → message `QUEUED` (or equivalent).  
2. Peer bind / radio appear → peer receives `MSG_PUSH` over LoRa without resend.  
3. Peer LoRa reply → visible in portal conversation (existing M2c path still passes).  
4. Duplicate `mid` suppressed.  
5. Signal or Today shows ≥1 pending sync/outbox item while waiting.  
6. `pytest` Dispatch tests green; `dispatch_airtest` still PASS.

**Out of scope for N1:** Reticulum, Pi AP, T-Deck UI, Outpost firmware, Postbox/Fieldbook features, Atlas, Groups, Commons polish, Stalwart.

---

## 9. Roadmap moves — earlier

| Item | Why earlier |
|------|-------------|
| Opportunistic Dispatch / queues | Core off-grid behavior; Heltec path ready to harden |
| Sync visibility (Signal/Today) | Prevents invisible failure |
| MakerHawk GPIO verify (spike) | Unblocks real multi-hop |
| Device bind / reachability in Rollcall | Needed before “who can I reach?” |

## 10. Roadmap moves — later

| Item | Why later |
|------|-----------|
| Atlas | Needs Pocket GPS reports (M7); design kept |
| Pi AP (M1b) | Valuable product path; does not deepen LoRa reliability — parallel *after* N1 or when camp Wi‑Fi is the blocker |
| Commons / Locker depth | Already prototyped; networking > polish |
| Fieldbook / rich Postbox | After sync subsystem + identity groundwork |
| Workshop / Arcade / Planner | Pocket platform Tier 4 |
| Federation | Document only |

## 11. Drop or simplify

- Stop adding portal apps until Tier 1 exits.  
- Do not build Heltec-specific “product” features (keep bridge minimal).  
- Do not invent per-app ACL — wait for Groups doc + one authz model.  
- Cardputer as Pocket reference — **rejected**; T-Deck Plus remains Pocket goal.  
- Live tracking / sub-minute GPS — out; 10–15 min reports only.

## 12. Decisions before more implementation

1. **N1 is next** (opportunistic Dispatch on Heltec) — accepted in this review.  
2. **Heltec = dev transport**; Reticulum/RNode remains production target (ADR 0002).  
3. **Freeze app catalog expansion** until N1 acceptance tests pass.  
4. **T-Deck Plus** is the Pocket SKU (GPS for Atlas later).  
5. When hardware arrives: MakerHawk GPIO verify *before* writing Outpost product firmware.  
6. Open: buy timeline for T-Deck / MakerHawk / RNode — does not change N1.

---

## ChatGPT / external review alignment

The external priority prompt is **accepted** with one critical adjustment: multi-hop Pocket↔Outpost tests are **Tier 1 intent** but **not the immediate build** until Pocket + Outpost hardware/firmware exist. Immediate build = harden the **proven** Station↔Heltec Dispatch path into opportunistic, queue-visible, reboot-tolerant messaging — then production transport + Pocket + Outpost.
