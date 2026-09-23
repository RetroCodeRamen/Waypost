# Waypost Priority Review

**Date:** 2026-09-23 (refresh of the 2026-09-18 review)
**Method:** Full repo inspection + architecture/roadmap/protocol/ADR review, reconciled against `AGENT_HANDOFF.md`'s message board.
**Intent:** Build order by dependency and network truth — not by app catalog completeness.

Related: [roadmap.md](roadmap.md) · [architecture.md](architecture.md) · [offline-sync.md](offline-sync.md) · [identity.md](identity.md) · [groups-and-permissions.md](groups-and-permissions.md) · [provisioning.md](provisioning.md) · [network-time.md](network-time.md) · [federation-future.md](federation-future.md)

**What changed since the 2026-09-18 review:** M2e went from "TCP lab only" to **done, over real LoRa** (two Heltec V3 boards reflashed as RNodes, encrypted Dispatch airtest PASS). M3's sim work went from "not started" to **exit criteria met**: peer↔peer Dispatch with no Station, multi-hop courier (`handoff_to`), `MSG_SYNC` carry-forward with authz (bound device must match username), and Wi‑Fi↔LoRa failover with durable per-device pending. M1b (Pi) went from "templates only" to **fully prepped and tested in containers, uncommitted, waiting on hardware**. The Pi SD card and T-Deck are now "in the mail" — this is a genuine hardware wait, not a deprioritization.

---

## 1. Current state

### Working today (end-to-end)

| Capability | Kind |
|------------|------|
| Laptop Station API + SQLite + portal shell | Backend + frontend prototype |
| Dispatch DMs/rooms over **HTTP** (portal) | Backend + frontend prototype |
| Dispatch over **Heltec LoRa** (peer → Station → portal → peer `MSG_PUSH`) | Real hardware (M2c) — **retired**: those boards are now flashed as RNodes; Heltec plaintext firmware needs a PlatformIO reflash to come back |
| Dispatch over **encrypted Reticulum/RNode LoRa** | **Real hardware (M2e ✅, over-air PASS 2026-09-22)** |
| Waylink `PING`/`PONG`, framed USB↔LoRa bridge | Real hardware (M2b) |
| Peer↔peer Dispatch with **no Station**, multi-hop courier, `MSG_SYNC` carry-forward + authz, Wi‑Fi↔LoRa failover | **Sim** (`server/services/dispatch/peer.py`, `server/tests/test_mesh_dispatch.py`) — M3 sim exit criteria met |
| Account auth: register/login, password hashed at rest, session cookie + Bearer | Real (N2 ✅) |
| Pi installer (idempotent), Caddy offline-CA HTTPS, sandboxed systemd service, staged AP | **Software done, tested in Debian containers — uncommitted, not yet run on a Pi** |
| Mock Pocket / MockTransport | Simulated (CI) |
| Postbox, Commons, Noticeboard, Beacon, Locker, Rollcall, Signal | HTTP prototypes (+ partial Waylink RPC) |
| pytest + Playwright screenshots | Automation — 86 passed, 1 skip as of this review |

### Partially working

| Area | Gap |
|------|-----|
| Dispatch | Sim proves Pocket↔Pocket, courier, and `MSG_SYNC`; **none of it runs on real Pocket hardware yet** (no T-Deck firmware) |
| Delivery / offline | Durable per-device pending now (Wi‑Fi↔LoRa failover slice); still Dispatch-only — other apps (Postbox, Fieldbook) haven't adopted the shared queue states from `offline-sync.md` |
| Signal | Lists radios / airtest / RNode security state; still no unified "Today" sync surface across apps |
| Identity | Real username/password accounts (N2); still no crypto device identity, pairing UX, or revocation product — `MSG_SYNC` authz checks a bound `device_bindings` row, which is the first sliver of this |
| Pi / Waygate | Installer + HTTPS proven in containers; AP + openNDS (Waygate) staged but unrun on real hardware |
| Home dashboard | Aggregates some counts; not a real "Today / sync" surface |

### Not started (architectural / planned)

Pocket (T-Deck) firmware · Outpost (MakerHawk) firmware · Groups/permissions subsystem · Shared offline-sync subsystem beyond Dispatch · Network time bootstrap (no RTC) · Provisioning product · Station↔Station federation · Fieldbook · Atlas · Finder · Archive · Workshop/Arcade · Stalwart/BookStack/Memos adapters · openNDS (Waygate)

---

## 2. Strong parts of the architecture

- **Services ≠ transports** — `Transport` interface + Waylink gateway; apps speak `MSG_*` / `MAIL_*`. This paid off directly: `ReticulumTransport` replaced the Heltec stand-in with **zero app-level changes**, exactly as ADR 0002 intended.
- **Heltec stand-in proved the spine**, then **the same boards became the production RNode hardware** — no separate radio purchase needed to reach M2e.
- **`PeerDispatchNode` reused `DispatchStore` and the courier/`MSG_SYNC` design directly from `offline-sync.md`/`protocol.md`** rather than inventing new plumbing — the documented "Offline / no-Station path" and the shipped code now match.
- **Durable `mid` + CBOR envelope** already in shared protocol; the Wi‑Fi↔LoRa failover slice extended dedup to cover multi-device delivery races, not just message content.
- **Honest roadmap** and radio-dev runbook stayed current through the M2e hardware milestone.
- **Comms rule documented and now partially proven in sim:** Pocket↔Pocket + carry-to-Station works end-to-end without Station in the mesh at all (sim); only real firmware is missing.

---

## 3. Weak parts

- **Hardware is now the pacing item, not software.** M1b and M3-on-hardware are both fully speced/prepped and blocked purely on physical Pi + T-Deck arrival — a different kind of blocker than the software gaps this review used to track.
- **No Pocket / Outpost code** — Priority-1 multi-hop tests are still blocked on hardware + firmware; MakerHawk isn't even confirmed ordered yet (only Pi SD card + T-Deck are "in the mail" per the handoff).
- **250-byte LoRa frames** still force compacted Dispatch payloads; easy to regress as more ops move to RNode.
- **Identity** still has no device crypto story beyond password auth + `device_bindings`; pairing codes and revocation UX (M4) haven't started.
- **Uncommitted work risk:** the M1b prep (installer, Caddy config, trust page, systemd units, docs/pi-setup.md) is sitting in the working tree, not committed. Low but real risk of accidental loss until it's committed.
- **This document's own freeze condition is now stale-adjacent:** the roadmap's "no Atlas / Workshop / new portal apps until network depth advances" freeze was written when M2e was unstarted and M3 was a design doc. Both have since landed (in sim, for M3). Whether "network depth" has now advanced enough to revisit the freeze is a call for the human, not this review — flagged here so it isn't silently forgotten.

---

## 4. Missing foundational features

1. ~~Opportunistic Dispatch (queue → auto-deliver when route/device appears)~~ — **done (N1 ✅)**
2. Shared offline / sync subsystem beyond Dispatch (states visible in Signal/Today; Postbox/Fieldbook haven't adopted it)
3. Account ≠ radio identity depth — pairing UX, revocation, cryptographic device identity (bind + `MSG_SYNC` authz is the current floor, not the ceiling)
4. Network time without public NTP — no RTC on the Pi means 30-day certs are already the practical ceiling (`network-time.md`)
5. Provisioning (Pocket join + Outpost enroll) — needs T-Deck/MakerHawk firmware first
6. Groups as shared authz (rooms today ≠ Groups)
7. Multi-hop Outpost path + Pocket-as-courier **on real hardware** (sim proves the logic; firmware doesn't exist)
8. Federation / home-Station assumptions (document only for now)

---

## 5. Technical debt / risks

| Risk | Why it matters | Status |
|------|-----------------|--------|
| Treating Heltec as production mesh | Would fight Reticulum/RNode if apps grew Heltec-specific assumptions | **Retired** — M2e is done; Heltec plaintext is explicitly lab-only now, and the same boards double as RNode hardware |
| Per-app offline queues | Dispatch/mail already diverge; Fieldbook will fork again | Still open — only Dispatch has adopted `offline-sync.md`'s states |
| Rooms ≠ Groups | Permission sprawl if each app invents ACL | Still open |
| Portal feature momentum | Tempting to polish Commons/Locker instead of transport | Still open — freeze still in effect |
| Clock skew | Notice/Beacon expiry and certs fail off-grid without Station time | **Sharper now**: Caddy issues real 30-day certs on the Pi, so a Pi that boots weeks behind serves certs phones reject — see `network-time.md` and `pi-setup.md#notes-and-limits` |
| Payload size | LoRa MAX_FRAME 250 — fragmentation or progressive ops needed before rich messages | Still open |
| Uncommitted M1b work | Working-tree-only changes can be lost or conflict with parallel work | New — commit soon |

---

## 6. Build-order (current position)

```text
proven air path (done)
  → resilient Station-mediated Dispatch + visible queues (done — N1)
    → production transport (done — M2e ✅, over real LoRa)
      → mesh semantics without Station (done in sim — M3 ✅; hardware pending)
        → Pocket comms foundation (T-Deck) ← hardware-blocked
          → multi-hop + courier (Outpost + Pocket) ← hardware-blocked
            → identity/presence depth (M4) ← UNBLOCKED, software-only
              → Postbox / Fieldbook / Notice+Beacon polish
                → Groups → Commons/Locker → Atlas/Archive → Pocket PDA apps
```

Every step through M3 is now done (sim where hardware doesn't exist yet). The next three steps in the spine (T-Deck comms, multi-hop courier, and — separately — M1b's Pi AP) are all genuinely hardware-blocked at the same time for the first time in this project's history. **M4 (identity depth) is the next step in the spine that needs no hardware at all.**

**Freeze:** new portal apps and deep Commons/Locker UX until Tier 1 exits — see the note in §3 about revisiting this now that M2e/M3-sim are done.

---

## 7. Priority tiers (adjusted for repo reality)

### TIER 1 — Done (or done-enough for sim)

- ~~Harden **Dispatch** on existing Heltec Station↔peer path~~ — done; extended further (multi-device failover, durable pending)
- ~~Shared **sync/queue** model~~ — done for Dispatch; not yet adopted by other apps
- ~~Keep **radio regression** green~~ — 86 passed as of this review
- ~~**Rollcall/identity groundwork:** device bind, last-seen, Wi‑Fi vs LoRa reachability labels~~ — done (`RollcallService.get` already computes `wifi`/`lora`/`recent`/`unavailable`)
- **MakerHawk GPIO verification** — still open; hardware not confirmed ordered
- ~~Document + keep Heltec as **dev transport**~~ — done; Heltec V3 boards now also serve as RNode hardware

### TIER 2 — Build next (mixed: some done, most hardware-blocked)

- ~~`ReticulumTransport` / RNode~~ — **done (M2e ✅)**
- T-Deck Pocket communications foundation (Dispatch + queue + sync-to-Station) — **hardware in transit; sim (`PeerDispatchNode`) is ready to port once firmware exists**
- Outpost store-and-forward firmware — hardware not confirmed ordered
- Pocket↔Outpost↔Pocket / courier smoke — blocked on both above
- Postbox progressive LoRa path — not started, no hardware dependency, software-only
- Fieldbook progressive path — not started, software-only
- Noticeboard ack + Beacon auth/propagation — not started, software-only
- Groups/permissions core — not started, software-only
- Unified Today / sync dashboard — not started, software-only
- **M1b Pi AP + TLS** — software done and tested in containers; blocked purely on physical Pi

### TIER 3 — After network is useful

- Commons depth · Locker group folders · Finder · Archive · **Atlas** (GPS/origin already designed — implement after Pocket reports exist)

### TIER 4 — Pocket platform expansion

- Logbook · Planner · Workshop/Lua · Arcade

---

## 8. Recommended next milestone (ONE)

### **M4 — Identity depth (Stalwart / OIDC / pairing UX)**

**Why this one:** it's the only item left in the priority spine (§6) that needs zero hardware. M1b and M3-on-hardware are both fully speced and will move the instant the Pi/T-Deck arrive — no analysis is blocking them. Everything else in Tier 2 that's software-only (Postbox/Fieldbook progressive sync, Groups, Today dashboard) sits *after* M4 in the roadmap's own ordering.

**Scope, per roadmap.md:** pairing codes, registration-mode enforcement in the UI, and either a Stalwart integration path or a scheduled cutover plan from the current SQLite password store. The `MSG_SYNC` authz check added in the M3 sim slice (bound device must match username) is the first sliver of "account ≠ radio identity" — M4 is where that becomes a real product (pairing UX + revocation), not just an internal guard.

**Acceptance shape (draft, refine before starting):**
1. Pairing code flow: Pocket (or its sim stand-in) presents a code; portal/admin approves; binds a device to an account without re-typing a password over LoRa.
2. Revocation: losing a Pocket removes its binding and rejects further radio-authenticated ops for that node, without touching the account itself.
3. Registration modes (`OPEN` / `INVITE_ONLY` / `ADMIN_APPROVAL`) enforced in the portal UI, not just the API.
4. Stalwart decision: either stand up a Stalwart container as the account authority, or write the ADR-0003 cutover plan explicitly and keep SQLite as the alpha stand-in a while longer. Don't do both halfway.

**Out of scope for M4:** anything that needs the Pi or T-Deck; full OIDC for third-party apps (Stalwart itself may support it, but wiring every Waypost app is later).

---

## 9. Roadmap moves — earlier

| Item | Why earlier |
|------|-------------|
| ~~Opportunistic Dispatch / queues~~ | **Done** |
| ~~Sync visibility (Signal/Today)~~ | Partially done — Signal shows it; a real Today view is still open |
| ~~Device bind / reachability in Rollcall~~ | **Done** |
| M4 identity depth | Now the only hardware-free item left in the priority spine — see §8 |

## 10. Roadmap moves — later

| Item | Why later |
|------|-----------|
| Atlas | Needs Pocket GPS reports (M7); design kept |
| MakerHawk GPIO verify (spike) | Still blocked — hardware not confirmed ordered, unlike Pi/T-Deck |
| Pi AP (M1b) | Software done; genuinely just waiting on the physical Pi now |
| Commons / Locker depth | Already prototyped; networking > polish |
| Fieldbook / rich Postbox | After identity groundwork (M4) — but otherwise software-only, could move earlier if M4 stalls |
| Workshop / Arcade / Planner | Pocket platform Tier 4 |
| Federation | Document only |

## 11. Drop or simplify

- Stop adding portal apps until Tier 1 exits — **Tier 1 has now exited**; this is the trigger to revisit the freeze (see §3, §6).
- Do not build Heltec-specific "product" features (keep bridge minimal) — moot now that Heltec's production role is RNode firmware, not the CBOR bridge.
- Do not invent per-app ACL — wait for Groups doc + one authz model.
- Cardputer as Pocket reference — **rejected**; T-Deck Plus remains Pocket goal (now in transit).
- Live tracking / sub-minute GPS — out; 10–15 min reports only.

## 12. Decisions before more implementation

1. ~~N1 is next~~ — done; **M4 is next** per §8, unless the human wants to spend the hardware-blocked wait on Tier 2 software items (Postbox/Fieldbook/Groups) instead.
2. **Heltec = dev transport; Reticulum/RNode is production** (ADR 0002) — no longer just a target, **proven over real LoRa**.
3. **Revisit the app-catalog freeze.** It was set when Tier 1 was open; Tier 1 has exited (sim-complete through M3). Options: lift it now that transport + mesh semantics are proven, keep it until M1b/M3 land on real hardware, or redefine "network depth" explicitly. This review doesn't decide it — flagging it as the most consequential open call right now.
4. **T-Deck Plus** remains the Pocket SKU; it's now physically in transit, not just a decision.
5. When hardware arrives: MakerHawk GPIO verify *before* writing Outpost product firmware (unchanged).
6. **Commit the uncommitted M1b work** before starting anything else — it's tested and ready, just not in git yet.
7. Open: MakerHawk order/arrival timeline — unlike Pi and T-Deck, not yet confirmed in the handoff.

---

## History: original review alignment (2026-09-18)

The original external priority prompt was accepted with one adjustment: multi-hop Pocket↔Outpost tests were Tier-1 *intent* but not the immediate build until hardware/firmware existed. That adjustment held — the immediate build (harden Station↔Heltec Dispatch into opportunistic, queue-visible, reboot-tolerant messaging, then production transport) is exactly what happened, on schedule, through M2e. This section is kept for history; §1–§8 above are the current read.
