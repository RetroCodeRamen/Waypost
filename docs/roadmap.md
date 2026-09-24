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
| **Corkboard** (per-outpost public noteboard, both sides) | **Proven (M6 ✅)** — sim + browser; real-hardware round trip pending the physical claim test below |
| **Standalone Outpost firmware** (Wi-Fi AP + real on-device Reticulum via microReticulum) | **Proven on real Heltec V3 hardware (M6)** — identity persists across reboots; see `firmware/outpost/README.md` |
| **Device pairing codes + per-device revocation** | **Done (M4 slice 1 ✅)** — also now reused for `OUTPOST_CLAIM` (infrastructure claiming), not just Pocket devices |
| Role-label OLED splash (both board types) | **Done (2026-09-23)** — Outpost hardware-verified; Station's board runs a patched-but-genuine RNode build (`firmware/RNode_Firmware/`), logo shown on a new button gesture |
| `ADMIN_APPROVAL` registration mode + admin-role | **Done (M4 slice 2 ✅)** — first-ever account bootstraps as admin; portal `/control.html` approves pending registrations |

### Explicitly not done

| Area | Gap |
|------|-----|
| Raspberry Pi Station install | Idempotent installer + Caddy HTTPS done and tested in containers ([pi-setup.md](pi-setup.md)) — **not yet run on real Pi hardware** |
| Waygate / hostapd / dnsmasq on real Pi | hostapd/dnsmasq staged behind `--enable-ap`, unrun on hardware; openNDS (Waygate) not started |
| `ReticulumTransport` / production RNode path | **Done (M2e ✅)** — encrypted Dispatch over real LoRa, RNode-flashed Heltec V3 |
| Pocket (T-Deck) firmware / UI | Not started — peer/courier logic proven in sim (`server/services/dispatch/peer.py`, M3); hardware in transit |
| Pocket GPS → Station location reports | Not started (planned under M7/M8) |
| **Atlas** (map, Station origin, range/distance) | Not started |
| Outpost firmware **on MakerHawk specifically** | GPIO still unverified on that board — the Heltec V3 build above is proven, MakerHawk is the separate, not-yet-confirmed-ordered production SKU |
| Physical Outpost claim over real LoRa | Everything upstream is verified (HTTP round trip proven live) — the join-the-AP-and-use-`/claim` step itself hasn't been done yet |
| Stalwart / BookStack / Memos / Kiwix adapters | Placeholders |
| Stalwart-vs-SQLite decision for identity | Undecided — M4's own scope says decide, don't do both halfway (see `priority-review.md` §12) |
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

### Just finished — **M6 standalone Outpost + OUTPOST_CLAIM** ✅ (sim/hardware, software side)

**Goal:** Outposts as real relay infrastructure — public noteboard, real on-device encryption, Station able to actually address one.

Standalone Outpost firmware (Heltec V3, real on-device Reticulum via microReticulum, Wi-Fi AP + Corkboard) is flashed and hardware-verified, identity stable across reboots. `OUTPOST_CLAIM` reuses the M4 pairing-code system so Station can `learn_route()` an Outpost before replying to it — verified over a live HTTP round trip; also fixed a matching latent bug in Pocket's own radio-pairing path (`PAIR_REDEEM` never called `learn_route`). Both boards now carry a role-label OLED splash — Outpost hardware-verified, Station's via a patched-but-genuine RNode firmware build (`firmware/RNode_Firmware/`). Full detail: `docs/architecture.md`, `docs/protocol.md`, `AGENT_HANDOFF.md`'s 2026-09-23 entries.

**Remaining on this thread:** the physical claim test over real LoRa (join the Outpost's Wi-Fi, use `/claim`) — needs a human, not more code; MakerHawk GPIO verification whenever that board exists.

**Next in the priority spine (no hardware needed):** M4 is build-complete except the Stalwart-vs-SQLite decision (a call for the human, not something to build around). Noticeboard ack + Beacon auth (M8 slice) are also now done (2026-09-23) — see below. Postbox's progressive LoRa path turned out to already be built (`MAIL_STATUS`/`LIST`/`GET`, compact headers, Wi-Fi-only attachments — this was a stale claim in `priority-review.md`, corrected there). Remaining Tier 2 software-only items: Fieldbook progressive path, Groups (biggest, nothing else depends on it yet), Today dashboard. See `priority-review.md` §7, §8, §12.

**Still freeze:** new portal apps; Atlas; Workshop — **worth revisiting now that M2e, M3-sim, and M6 have all landed; see priority-review.md §3, §6, §12.2.**

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

**Role-label OLED splash — prioritized 2026-09-23** ("I would like to know which device is which when I look at them easily"): both Heltec V3 boards' onboard SSD1306 (128x64, real pins verified against the board's own `pins_arduino.h`, not guessed: `SDA_OLED`/`SCL_OLED`/`RST_OLED` = 17/18/21) now draw the Waypost mark icon (40x40, generated from `web/portal/static/brand/waypost-mark-256.png` — see each firmware's `waypost_mark.h`) plus a role label via U8g2, runtime-centered so it doesn't depend on exact font-metric guesses.

- **`firmware/outpost`** — done, flashed, boot-verified clean (no I2C errors, identity still stable). Shows the mark + "OUTPOST".
- **Station's board** — done a different way than `firmware/outpost`: rather than swap to `firmware/heltec` (which would replace RNode entirely), patched **RNode firmware itself** — `firmware/RNode_Firmware/` is a vendored, trimmed copy of upstream `master` (same version already flashed, 1.86) with one additive change: a new ~0.7–1.3s button-hold gesture shows the Waypost logo for 3s, inserted into the existing button's four duration-based behaviors without touching any of them (quick-tap BT toggle unchanged; sleep's threshold just moved ~0.6s later to make room). Built via upstream's own `arduino-cli` toolchain (pinned to ESP32 core 2.0.17, matching what they release-test against — not the 3.x core the rest of this project's firmware uses via PlatformIO). Confirmed before touching the live device that Reticulum's Python side (`RNodeInterface.validate_firmware()`) only checks the firmware's self-reported version number, not a hash, so a patched-but-same-version build is accepted exactly like the stock binary — verified true: flashed to `/dev/ttyUSB0`, Station reconnected cleanly, same destination hash, `/api/health` 200. **Not yet verified: whether the logo actually renders correctly** — no way to see the physical screen remotely; needs a human to hold the action button for ~1 second and look.

MakerHawk's own OLED still has only a planned diagnostic layout ([hardware/makerhawk-v3.md](hardware/makerhawk-v3.md)) — the same icon+label approach applies once that hardware exists.

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

### M4 — Identity depth (Stalwart / OIDC / pairing UX) ✅ (build) / 🟡 (Stalwart decision)

**Goal:** Production identity authority; polished Pocket pairing; revocation UX.

**Exit criteria:** Stalwart path or scheduled cutover; pairing codes; registration modes enforced in UI.

**Progress (slice 1):** Pairing codes — `POST /api/auth/pairing/create` (authenticated) / `POST /api/auth/pairing/redeem` (no session; also `PAIR_REDEEM` over Waylink) — bind a device without a password ever crossing LoRa. Per-device revocation — `GET /api/dispatch/devices`, `POST /api/dispatch/devices/unbind-one` — revokes one device, siblings survive (unlike the older `unbind` which wipes all of a user's devices). Portal: new `devices.html`. `OPEN`/`INVITE_ONLY` are now honest in `login.html` (the button hides/explains instead of letting a blocked registration submit). See `docs/identity.md`, `docs/security.md`. Same pairing codes reused as-is for `OUTPOST_CLAIM` in M6 — proof the design generalizes past just Pocket devices.

**Progress (slice 2 — `ADMIN_APPROVAL` + admin-role):** `users` gained `is_admin`/`approved_at` (migration grandfathers every pre-existing account so nobody gets retroactively locked out). Registering under `ADMIN_APPROVAL` creates the account but issues no session; `POST /api/auth/login` rejects until `POST /api/auth/approve` (admin-only, new `get_current_admin` dependency) sets `approved_at`. The **first account ever registered on a Station bootstraps as admin, auto-approved** — otherwise an `ADMIN_APPROVAL` Station could never have anyone able to approve anyone. `ensure_user`-created accounts (device binds, lab seeding) are auto-approved too — they're not the public self-registration path `ADMIN_APPROVAL` is actually gating, and they get no password hash either way. Portal: `/control.html` (the former "Control" nav placeholder, now real) lists pending registrations with one-click approve. `login.html` re-enabled "Create account" under `ADMIN_APPROVAL` (was previously disabled with an honest "not available" note) and now shows the account's pending status after registering instead of silently doing nothing. 9 new tests, verified live in a browser (register → pending → admin approves via the real UI → login succeeds).

**Still open:** Stalwart integration-vs-cutover — a human decision, not something to build around. See `priority-review.md` §12.3.

---

### M5 — Postbox + Fieldbook (progressive)

**Goal:** Mail and wiki usable off-grid without giant sync.

**Exit criteria:** Postbox LoRa `STATUS→LIST→GET→SEND`; Fieldbook search→page→section; offline edits via shared sync; Pocket favorites cache design.

---

### M6 — Outpost + Pocket courier network 🟡

**Goal:** Multi-hop and delay-tolerant coverage; Outposts **and** Pockets forward.

**Exit criteria:** MakerHawk pinout verified; transport-node firmware; Pocket↔Outpost↔Pocket + courier-to-Station smoke; queues survive power cycle. Recipient reads now; copy still syncs to Station (`mid` dedup).

**Progress (sim + first hardware attempt):** `OutpostNode` (`server/services/dispatch/outpost.py`) — uncapped relay hops (unlike Pockets' 3-hop cap), preferred-route caching to Station, direct hand-off between two Pockets co-located at the same Outpost. Sim-tested via `MockMesh` (`server/tests/test_mesh_dispatch.py`) — not yet against real MakerHawk hardware, which still doesn't exist (GPIO unverified, not confirmed ordered). A first real-radio attempt used the two RNode-flashed Heltec V3 boards as a Station+Outpost stand-in (same precedent as Heltec-before-RNode) — `tools/radio/outpost_airtest.py`. One run completed a full send→process round trip over real encrypted LoRa; later runs haven't reproduced it reliably. Two real bugs surfaced and got fixed along the way: `ReticulumTransport.get_route`/`reachable` never resolved logical node_ids to RNS hashes (only `send` did), and nothing taught Station how to resolve a reply back to an Outpost without an explicit bind. **Still open:** reliable hardware round-trip (RF/timing, not app logic, is the suspect), the Beacon origin-outpost extension, and the session-isolated Wi-Fi terminal (needs real MakerHawk-class hardware or firmware work either way).

**Progress — Corkboard (sim, both sides) + standalone Outpost firmware (hardware bring-up started 2026-09-23):** per-outpost public note board — `server/services/corkboard/` (`{constants,store,service}.py`), `BOARD_SYNC` op, portal page `corkboard.html`. Outpost's copy is the durable primary, Station's is backup; a Station user reads/posts exactly one known outpost at a time, never a merged view (deliberate UX + security choice). Registration is automatic — the first `BOARD_SYNC` from any `env.src` creates the outpost entry. `OutpostNode.add_local_note`/`sync_corkboard` complete the loop: upload not-yet-synced notes (tracked via a `synced_at` marker, never deleted locally), ingest whatever Station piggybacks back. Posting from the portal queues into a per-outpost outbox and gets piggybacked into that outpost's next sync — proven end-to-end both in the browser (portal → outbox → simulated resync) and in sim (`OutpostNode` ↔ `CorkboardService` full round trip, `server/tests/test_mesh_dispatch.py`). `server/tests/test_corkboard.py` + mesh tests, 110 passed.

A first standalone Outpost firmware now exists and is flashed to real hardware — `firmware/outpost` (Heltec V3 on `/dev/ttyUSB1`): Wi-Fi AP + Corkboard web UI + real on-device Reticulum via microReticulum (not plaintext — an earlier draft assumed real Reticulum needed a host computer; that was checked and found wrong, see `firmware/outpost/README.md`). Its identity/destination hash is confirmed stable across reboots (a real bug — the filesystem was silently reformatting every boot — found and fixed during bring-up).

Claiming is also done: `OUTPOST_CLAIM` (`docs/protocol.md`) reuses the M4 pairing-code system exactly — a code generated on Corkboard's portal page, entered on the Outpost's own `/claim` Wi-Fi page, `learn_route` called before the reply so even the claim's own response is routable. Fixed a matching latent bug found along the way: the Pocket radio-pairing path (`PAIR_REDEEM`) accepted a `transport_dest` but never called `learn_route` either. Verified end-to-end over HTTP against a live Station (`server/tests/test_pairing.py` +5, 115 passed; a live curl round trip: code → claim → registered with the right hash). **Still open:** the physical leg — someone joining the Outpost's own Wi-Fi and using its `/claim` page over real LoRa, not yet done (this sandbox can't join that AP); role labels on the boards' onboard OLED so Station vs. Outpost hardware is visually distinguishable (requested 2026-09-23, spec captured above under M2's backlog note); the emergency-alert button; session isolation; the Beacon origin-outpost extension (separate agreed piece, not started).

---

### M7 — Pocket environment (T-Deck Plus)

**Goal:** Handheld computer + GPS reports + on-device courier queue.

**Exit criteria:** Shell; Dispatch over Waylink; `/waypost/courier/`; `LOC_REPORT` every 10–15 min; Station pairing.

---

### M8 — Groups, Today view, Notice/Beacon polish 🟡

**Goal:** Shared authz + homepage that answers what happened / what’s waiting; trustworthy notices and Beacon.

**Exit criteria:** Groups used by ≥2 services ([groups-and-permissions.md](groups-and-permissions.md)); Today aggregates unread + sync; Notice ack; Beacon auth + replay protection.

**Progress (2026-09-23):** Notice ack ✅ — `NOTICE_ACK` (Waylink) + `POST /api/noticeboard/notices/{id}/ack`, idempotent, per-user, portal shows an unread count and a "Mark as read" action. Beacon auth ✅ — `BEACON_PUSH`/`CLEAR` (and Noticeboard's `NOTICE_CREATE`/`EXPIRE`) now resolve the acting username from the radio device's binding rather than trusting the payload's own `author` field, closing a real spoofing gap (see `docs/security.md`, `docs/protocol.md`). Replay protection for Beacon was already covered generically — `WaylinkGateway` dedups every op by `mid`, and `PUSH_COOLDOWN_SEC` rate-limits repeat pushes from one author — so nothing new was needed there specifically. **Still open:** Groups (not started — no file exists yet, biggest remaining piece of this milestone), Today view, Beacon propagation through Outposts (explicitly out of scope for the auth fix — see `docs/protocol.md`'s Beacon section).

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

**Prep done (no Pi yet):** idempotent `deploy/raspberry-pi/install.sh` (tested twice in Debian Bookworm + Trixie containers), Caddy HTTPS with offline local CA + trust page (proven on laptop), sandboxed `waypost-api.service`, generated secrets/PSK, AP staged behind `--enable-ap` with a guard against cutting off wlan0 SSH. Guide: [pi-setup.md](pi-setup.md). **Remaining on hardware:** run it, `--enable-ap`, phone joins `WAYPOST` → trust → HTTPS; then openNDS (Waygate).

---

## Near-term queue (do in order)

1. ~~**M2e** radio transport crypto~~ ✅ (over-air PASS 2026-09-22)  
2. **M3** mesh/sim peer + shared sync adoption — sim ✅; hardware with Pocket firmware  
3. **M4** identity depth — pairing codes + per-device revocation + `ADMIN_APPROVAL`/admin-role all ✅; Stalwart decision still open  
4. **Hardware spikes (parallel):** MakerHawk GPIO; T-Deck Plus  
5. **M1b Pi AP + TLS** when camp Wi‑Fi is the blocker  
6. Then M5 → M6/M7  

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
