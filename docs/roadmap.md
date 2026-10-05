# Waypost project plan

Single source of truth for **what we’re building**, **what’s done**, and **what’s next**.  
Prefer small, testable vertical slices. Do not expand scope mid-slice without updating this doc.

Related: [architecture.md](architecture.md) · [protocol.md](protocol.md) · [naming.md](naming.md) · [security.md](security.md) · [priority-review.md](priority-review.md)

---

## North star

An off-grid community network you can run without the Internet:

| Piece | Intent |
|-------|--------|
| **Waypost Station** | Raspberry Pi — headquarters, archive, sync hub, recovery point, portal. Enhances the network; doesn't create it |
| **Waygate** | Captive portal when joining community Wi‑Fi |
| **Waylink** | Compact RPC over LoRa (not HTML-over-radio) |
| **Waypost Scout** | Handheld (T-Deck) — complete personal Waypost, works with only another Scout; internal class **Pocket** |
| **Waypost Outpost** | Fixed ESP32 LoRa infrastructure that runs on its own: relay, store, local services, Wi-Fi page |
| **Courier** | A role: any moving device carrying objects between islands |

**Network rule (2026-10-04, non‑negotiable):** **no individual device is strictly necessary.** Waypost is local-first, offline-first, store-and-forward, opportunistically connected and eventually synchronized. Every device adds capability, never a mandatory dependency. Model: [network-model.md](network-model.md). Gap analysis: [decentralization-review.md](decentralization-review.md).

**Acceptance tests for the whole plan:** **T1** Station unplugged → two Scouts and an Outpost still form a useful network. **T2** Station returns → the network reconciles with no manual rebuild. **T3** adding a device adds capability, not a dependency.

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

**Date context (updated 2026-10-03):** early alpha · development on Linux laptop · two Heltec WiFi LoRa 32 **V3** boards (one RNode = Station's radio on `/dev/ttyUSB0`, one running Outpost firmware on `/dev/ttyUSB1`) + a LilyGO **T-Deck** Scout (`/dev/ttyACM0`).

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
| **Scout (T-Deck) firmware** — launcher, Dispatch, Fieldbook, Trailhead, Signal | **Proven over real LoRa (M7, 2026-10-03)** — see `firmware/pocket/README.md` |
| **Trailhead** (Station's small web: linked text pages, portal editor, `TRAIL_GET`) | **Done (2026-10-03)** — read on a Scout over real LoRa |
| Outpost auto-claim + `BOARD_SYNC` over real LoRa | **Proven (2026-10-03)** — after the embedded radio driver's wire-format fix (`3586bfb`) |

### Explicitly not done

| Area | Gap |
|------|-----|
| Raspberry Pi Station install | Idempotent installer + Caddy HTTPS done and tested in containers ([pi-setup.md](pi-setup.md)) — **not yet run on real Pi hardware** |
| Waygate / hostapd / dnsmasq on real Pi | hostapd/dnsmasq staged behind `--enable-ap`, unrun on hardware; openNDS (Waygate) not started |
| `ReticulumTransport` / production RNode path | **Done (M2e ✅)** — encrypted Dispatch over real LoRa, RNode-flashed Heltec V3 |
| Scout (T-Deck) firmware / UI | 🟡 launcher + Dispatch, Fieldbook, Trailhead, Signal apps live over LoRa (M7) |
| Pocket GPS → Station location reports | Not started (planned under M7/M8) |
| **Atlas** (map, Station origin, range/distance) | Not started |
| Outpost firmware **on MakerHawk specifically** | GPIO still unverified on that board — the Heltec V3 build above is proven, MakerHawk is the separate, not-yet-confirmed-ordered production SKU |
| Physical Outpost claim over real LoRa | Everything upstream is verified (HTTP round trip proven live) — the join-the-AP-and-use-`/claim` step itself hasn't been done yet |
| Stalwart / BookStack / Memos / Kiwix adapters | Placeholders |
| Stalwart-vs-SQLite decision for identity | Undecided — M4's own scope says decide, don't do both halfway (see `priority-review.md` §12) |
| Fieldbook | **Built 2026-09-24** (SQLite pages + revisions, `WIKI_SEARCH/GET/UPDATE/CREATE` with outline/section/diff, portal `fieldbook.html`) — offline edit *queueing* on Pocket still waits on the shared sync subsystem |
| Finder | **Built 2026-09-24** — cross-app search (`SEARCH` over Waylink + `GET /api/finder/search`), portal `finder.html`. Deliberately scoped to Commons/Noticeboard/Fieldbook/Locker, all through each service's own existing visibility rules; Dispatch/Postbox (private) and Corkboard (no merged cross-outpost view by design) stay out — see `docs/protocol.md`'s Finder section |
| Archive | Not built (nav “soon” only) — Kiwix integration, a meaningfully bigger undertaking than Finder was (external ZIM-format content server), see M10 |

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

## Decentralization track (dependency order)

**Adopted 2026-10-04.** This is now the main line of work. It continues M3 (mesh semantics), M6
(Outpost courier network) and M7 (Scout) rather than replacing them. Nothing is rewritten: each step
adds to working code and keeps today's Station paths working alongside.

Status key: ✅ implemented · 🟡 partial · 📋 planned · 🔧 architectural change required.

| Step | What | Builds on | Status | Proves |
|---|---|---|---|---|
| **D0** | Model + review docs: [network-model.md](network-model.md), [decentralization-review.md](decentralization-review.md), [outpost.md](outpost.md), offline identity in [identity.md](identity.md#offline-identity-target) | — | ✅ 2026-10-04 | — |
| **D1** | **Scout keeps its own data:** local store (own messages, receipts, outbox, Beacon events, contacts); apps read from it; outbox sends when a path appears; states queued / sent / delivered / archived | account + contacts cache ✅ | 🟡 **built 2026-10-04** — saved conversations + unread verified across reboots on hardware; outbox (Station-idempotent `message_id`), offline compose, saved Beacon alerts, screen dim/off built, **hand test pending** (Scout is PIN-locked) | Scout useful with Station off (read history, compose) |
| **D2** | **Offline identity:** community key on Station; identity + device certificates issued at `PAIR_REDEEM` / claim; cached on every device; revocation objects; PIN seals the Scout's signing key | pairing ✅, device keys ✅ | 🟡 **built 2026-10-04** — Station complete (+11 tests); Scout pins the key, fetches + verifies certificates for itself and contacts, persists them, self-test matches Python (hardware). Signing key is separate from the network identity so a locked Scout still receives. **Hand test pending:** own device certificate (needs one unlock) | any node can verify a person offline |
| **D3** | **Objects + signing:** 128-bit `oid`, Ed25519 signature by the device signing key over canonical bytes (Python + C++, pinned vector); Station verifies and accepts signed `dispatch.msg` alongside today's unsigned path; `firmware/common/` shared lib still to do (with D5) | D2; `mid` dedup ✅ | 🟡 **built 2026-10-04** — Station verifies signed `MSG_SEND` from any carrier (+7 tests); Scout signs at compose, outbox keeps the signature, compose limit sized to the packet; self-test vector matches on hardware; portal marks "signed". **Hand test pending:** a live signed send (needs one unlock for the signing key) | messages can't be forged by whoever carries them |
| **D4** | **Peer sync:** `SYNC_HELLO/DIFF/WANT/PUT` in the Python sim first (port `PeerDispatchNode`/`OutpostNode` onto it), then on Station, then Scout. `station_link` → `link` (any peer). Scout↔Scout direct | D1, D3; `MSG_SYNC` ✅ | 🟡 **built 2026-10-05** — sim (7 tests: no-Station, outage + reconcile, courier, tampering, revoked, efficiency, packet sizes), Station `SYNC` responder, Scout initiator + responder. **On hardware over LoRa:** Scout pulled 2 signed messages from Station (verified offline); with Station off, a stand-in second Scout and the T-Deck exchanged 3 messages directly; Station back → the T-Deck carried the direct message to Station (signed, author basecamp). Open: delivery receipts as objects; a real second T-Deck | **two Scouts, no Station** (T1 part) ✅ hardware; **Station rejoins and catches up** (T2) ✅ hardware |
| **D5** | **Outpost as a node:** flash object store (Corkboard notes too), `SYNC_*` with Scouts/Outposts/Station, local delivery to Scouts in range, cached certificates, Beacon events spread from any node | D3, D4 | 🔧 | **T1 complete** (2 Scouts + Outpost, Station unplugged) |
| **D6** | **Capability discovery + status:** announce capability record, `CAPS_GET`, Scout "Nearby" and the home status block (Dispatch available / Station via Outpost); peers chosen by capability, not compiled-in hash | D4 (announce parsing can start earlier) | 📋 (auto-claim marker ✅) | **T3** |
| **D7** | **Courier role:** carry budget, priority, retention (drop on archive receipt or expiry), Outpost→Courier→Outpost | D4, D5 | 📋 (sim ✅) | islands with no radio path converge |
| **D8** | **Tier 2 transport:** Scout joins Outpost/Station Wi-Fi (Reticulum over UDP) and ESP-NOW Scout↔Scout for large objects; same `SYNC_*`. In parallel any time: **LoRa profile field test** (range vs airtime, SF8–SF11) | D4 | 📋 | full sync in seconds when close |
| **D9** | **Services onto objects:** Noticeboard (area-local at Outposts), Fieldbook page cache, Postbox, Commons, Rollcall presence, Trailhead cache; Outpost Wi-Fi Dispatch page + sign-in without a Scout ([outpost.md](outpost.md#signing-in-without-a-scout)) | D5, D8 for large items | 📋 | Outpost serves people with no Scout and no Station |
| **D10** | **Retire Station-only paths:** refuse unsigned device messages once every device has certificates; drop `is_trusted_courier`; portal shows how/when each item arrived | D2–D5 everywhere | 🔧 | — |

**Test hardware:** D4's Scout↔Scout needs a **second T-Deck** (until then a Python stand-in Scout on
the RNode with Station stopped). D5 uses the Heltec Outpost on hand. D7 needs no new hardware.

**Acceptance demo (after D5/D6):** unplug Station → Scout A messages Scout B directly and via the
Outpost; a Beacon raised on A shows on B; Outpost Wi-Fi shows the board → plug Station back in → the
portal shows every message and the Beacon with no manual step → add a second Outpost → range grows,
nothing is reconfigured.

### Just finished — **M7 Scout over real LoRa** (2026-10-03)

The T-Deck runs a home launcher with Dispatch (chat with live push + ack), Fieldbook (search → outline → chunked sections), Trailhead (new: the Station's small web of linked text pages), and Signal, all over encrypted LoRa to Station. Details: M7 below, `firmware/pocket/README.md`, `AGENT_HANDOFF.md` 2026-10-03.

### Before that — **M6 standalone Outpost + OUTPOST_CLAIM** ✅ (sim/hardware, software side)

**Goal:** Outposts as real relay infrastructure — public noteboard, real on-device encryption, Station able to actually address one.

Standalone Outpost firmware (Heltec V3, real on-device Reticulum via microReticulum, Wi-Fi AP + Corkboard) is flashed and hardware-verified, identity stable across reboots. `OUTPOST_CLAIM` reuses the M4 pairing-code system so Station can `learn_route()` an Outpost before replying to it — verified over a live HTTP round trip; also fixed a matching latent bug in Pocket's own radio-pairing path (`PAIR_REDEEM` never called `learn_route`). Both boards now carry a role-label OLED splash — Outpost hardware-verified, Station's via a patched-but-genuine RNode firmware build (`firmware/RNode_Firmware/`). Full detail: `docs/architecture.md`, `docs/protocol.md`, `AGENT_HANDOFF.md`'s 2026-09-23 entries.

**Remaining on this thread:** the physical claim test over real LoRa (join the Outpost's Wi-Fi, use `/claim`) — needs a human, not more code; MakerHawk GPIO verification whenever that board exists.

**Next in the priority spine (no hardware needed):** M4 is build-complete except the Stalwart-vs-SQLite decision (a call for the human, not something to build around). M8 is now fully done (2026-09-24) — Noticeboard ack, Beacon auth, Today/sync dashboard, and Groups (core + Locker/Dispatch integration) all shipped. Postbox's progressive LoRa path turned out to already be built (`MAIL_STATUS`/`LIST`/`GET`, compact headers, Wi-Fi-only attachments — this was a stale claim in `priority-review.md`, corrected there). Fieldbook progressive path shipped 2026-09-24 (`docs/fieldbook.md`) — M5's software half is now done on both apps. Remaining Tier 2 software-only items: Beacon propagation through Outposts, extending Groups scoping to Noticeboard/Commons/Fieldbook (not required for M8's exit criteria, same pattern as Locker once needed). See `priority-review.md` §7, §8, §12.

**Still freeze:** new portal apps; Atlas; Workshop — **worth revisiting now that M2e, M3-sim, and M6 have all landed; see priority-review.md §3, §6, §12.2.** (Exception, 2026-10-03: Trailhead was added at the human's direction as part of a complete Scout — see the decision log.)

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

### M5 — Postbox + Fieldbook (progressive) 🟡 software done

**Goal:** Mail and wiki usable off-grid without giant sync.

**Exit criteria:** ~~Postbox LoRa `STATUS→LIST→GET→SEND`~~ ✅ (already built, see priority-review §8); ~~Fieldbook search→page→section~~ ✅ 2026-09-24 (plus `since`-diff and section-level edits with base-revision conflict detection — [fieldbook.md](fieldbook.md)); offline edits via shared sync — **open**, waits on the shared offline-sync subsystem (Dispatch is still the only adopter); Pocket favorites cache design — **open**, design only once T-Deck firmware exists.

---

### M6 — Outpost + Pocket courier network 🟡

**Goal:** Multi-hop and delay-tolerant coverage; Outposts **and** Pockets forward.

**Exit criteria:** MakerHawk pinout verified; transport-node firmware; Pocket↔Outpost↔Pocket + courier-to-Station smoke; queues survive power cycle. Recipient reads now; copy still syncs to Station (`mid` dedup).

**Progress (sim + first hardware attempt):** `OutpostNode` (`server/services/dispatch/outpost.py`) — uncapped relay hops (unlike Pockets' 3-hop cap), preferred-route caching to Station, direct hand-off between two Pockets co-located at the same Outpost. Sim-tested via `MockMesh` (`server/tests/test_mesh_dispatch.py`) — not yet against real MakerHawk hardware, which still doesn't exist (GPIO unverified, not confirmed ordered). A first real-radio attempt used the two RNode-flashed Heltec V3 boards as a Station+Outpost stand-in (same precedent as Heltec-before-RNode) — `tools/radio/outpost_airtest.py`. One run completed a full send→process round trip over real encrypted LoRa; later runs haven't reproduced it reliably. Two real bugs surfaced and got fixed along the way: `ReticulumTransport.get_route`/`reachable` never resolved logical node_ids to RNS hashes (only `send` did), and nothing taught Station how to resolve a reply back to an Outpost without an explicit bind. **Update 2026-10-03:** the "works once, then never again" pattern had two real causes, both fixed: Station's `WaylinkGateway` receive loop silently died on its first unhandled exception (`e88bec5`), and the embedded radio driver used by Outpost and Scout split large packets in a format real RNode firmware couldn't reassemble (`3586bfb`). The standalone Outpost's `BOARD_SYNC` + auto-claim now complete over real LoRa. `tools/radio/outpost_airtest.py` (Python on both boards) hasn't been re-run since — `/dev/ttyUSB1` now runs Outpost firmware, not RNode. **Still open:** the Beacon origin-outpost extension, and the session-isolated Wi-Fi terminal (needs real MakerHawk-class hardware or firmware work either way).

**Progress — Corkboard (sim, both sides) + standalone Outpost firmware (hardware bring-up started 2026-09-23):** per-outpost public note board — `server/services/corkboard/` (`{constants,store,service}.py`), `BOARD_SYNC` op, portal page `corkboard.html`. Outpost's copy is the durable primary, Station's is backup; a Station user reads/posts exactly one known outpost at a time, never a merged view (deliberate UX + security choice). Registration is automatic — the first `BOARD_SYNC` from any `env.src` creates the outpost entry. `OutpostNode.add_local_note`/`sync_corkboard` complete the loop: upload not-yet-synced notes (tracked via a `synced_at` marker, never deleted locally), ingest whatever Station piggybacks back. Posting from the portal queues into a per-outpost outbox and gets piggybacked into that outpost's next sync — proven end-to-end both in the browser (portal → outbox → simulated resync) and in sim (`OutpostNode` ↔ `CorkboardService` full round trip, `server/tests/test_mesh_dispatch.py`). `server/tests/test_corkboard.py` + mesh tests, 110 passed.

A first standalone Outpost firmware now exists and is flashed to real hardware — `firmware/outpost` (Heltec V3 on `/dev/ttyUSB1`): Wi-Fi AP + Corkboard web UI + real on-device Reticulum via microReticulum (not plaintext — an earlier draft assumed real Reticulum needed a host computer; that was checked and found wrong, see `firmware/outpost/README.md`). Its identity/destination hash is confirmed stable across reboots (a real bug — the filesystem was silently reformatting every boot — found and fixed during bring-up).

Claiming is also done: `OUTPOST_CLAIM` (`docs/protocol.md`) reuses the M4 pairing-code system exactly — a code generated on Corkboard's portal page, entered on the Outpost's own `/claim` Wi-Fi page, `learn_route` called before the reply so even the claim's own response is routable. Fixed a matching latent bug found along the way: the Pocket radio-pairing path (`PAIR_REDEEM`) accepted a `transport_dest` but never called `learn_route` either. Verified end-to-end over HTTP against a live Station (`server/tests/test_pairing.py` +5, 115 passed; a live curl round trip: code → claim → registered with the right hash). **Still open:** the physical leg — someone joining the Outpost's own Wi-Fi and using its `/claim` page over real LoRa, not yet done (this sandbox can't join that AP); role labels on the boards' onboard OLED so Station vs. Outpost hardware is visually distinguishable (requested 2026-09-23, spec captured above under M2's backlog note); the emergency-alert button; session isolation; the Beacon origin-outpost extension (separate agreed piece, not started).

**Progress (2026-09-24) — auto-claim, no code needed:** Station now claims nearby unclaimed Outposts automatically, on by default, per direct user request. `ReticulumTransport` registers a real `RNS.Transport` announce handler; an unclaimed Outpost includes a marker in its own periodic Reticulum announce (gated by a new physical-button-toggled `auto_claim_enabled` flag, default on) — Station resolves the destination hash from the announce itself (Reticulum-signed, not a self-reported payload field) and claims it the same way `OUTPOST_CLAIM` does, minus the code. `PairingService.auto_claim_outpost` is idempotent and never overrides an existing claim. `WAYPOST_AUTO_CLAIM_OUTPOSTS` (default on) is the kill switch. `firmware/outpost` gained the button (GPIO0/PRG), an OLED status splash, persisted flags, periodic re-announce (10 min) and periodic auto-sync (5 min, not just on `/refresh` anymore). 9 new/updated tests (`test_pairing.py`, `test_corkboard.py`), full suite 179 passed. **Verified live against a real Reticulum stack** (TCP lab, `tools/radio/auto_claim_airtest.py` — a fake outpost peer announces with the marker, Station claims it with the correct hash, full `rns` package round trip, no mocks). **Flashed to the physical Outpost (`/dev/ttyUSB1`)** — boots clean, identity persisted, no new errors.

**Progress (2026-09-24, same day) — the emergency Beacon button:** the last piece flagged as "not in slice" from yesterday's Beacon-Outpost sync work. `firmware/outpost` gained `/beacon` — a walk-up web form (no login, same posture as `/post`) to report a real emergency, deliberately **push-only** (no walk-up "clear" — silencing someone else's real active alert anonymously is a materially different risk than reporting one, so clearing stays a Station-side action). New `encode_beacon_sync_request` in `waylink_cbor.{h,cpp}`; queues locally, sends immediately on submit, retries on the same periodic timer `BOARD_SYNC` uses; `BeaconStore`'s existing dedup-by-`mid` makes a retry-after-unconfirmed-send safe (verified this is genuinely how the store behaves, not assumed). Compiles clean, flashed to `/dev/ttyUSB1` alongside auto-claim, boots clean, identity hash unchanged across both reflashes. **Still open:** the actual over-LoRa walk-up→Station round trip — Station's own RNode board wasn't connected to this machine while this was built, so only the parts provable without the physical Outpost (the Station-side security model, already tested) are verified; the rest needs a human with both boards.

---

### M7 — Scout environment (T-Deck; internal: Pocket)

**Goal:** Handheld computer + GPS reports + on-device courier queue.

**Exit criteria:** Shell; Dispatch over Waylink; `/waypost/courier/`; `LOC_REPORT` every 10–15 min; Station pairing.

**Progress (2026-10-02):** Scout naming locked (product = Waypost Scout / Scout; protocol class = Pocket). `firmware/pocket/` PlatformIO project for LilyGO T-Deck — slice 0 boot splash; **slice 1** microReticulum over SX1262 + Waylink `CORE/PING` (optional `MSG_SEND` when `WAYPOST_DISPATCH_PEER` set). Builds clean, flashed to `/dev/ttyACM0`; serial confirms path + `Identity::recall` for Station — reply leg still times out (same Station RNode TX gap as Outpost). Next: live PING verify when Station radio path fixed, then `MSG_SEND` bind + keyboard UI.

**Progress (2026-10-03):** The "reply leg" was two bugs, both fixed: the embedded radio driver's split-frame format didn't match real RNode (`3586bfb`), and Scout rejected PONG for lacking `ok` (`192a32a`). Scout is now a Cybiko-style shell (`ce23568`): home tile launcher; **Dispatch** chat with unread badge (send + live `MSG_PUSH` receive + ack); **Fieldbook** search → outline → section, read in ~160-byte chunks; **Trailhead** (new: the Station's small web of linked text pages, `TRAIL_GET`, portal editor — `6991c5c`); **Signal** (identity, Station path, PING). All verified live over LoRa (PING 20/20, ~1.8 s round trip). Every reply a Scout requests is sized to one encrypted Reticulum packet (383 B), guarded by tests. **Still open:** trackball pins not yet confirmed by hand; a few clustered packet losses not yet explained (steady state clean); Fieldbook editing from Scout, contact list / multiple conversations, `PAIR_REDEEM` on-device, GPS `LOC_REPORT`, courier queue.

---

### M8 — Groups, Today view, Notice/Beacon polish ✅

**Goal:** Shared authz + homepage that answers what happened / what’s waiting; trustworthy notices and Beacon.

**Exit criteria:** Groups used by ≥2 services ([groups-and-permissions.md](groups-and-permissions.md)); Today aggregates unread + sync; Notice ack; Beacon auth + replay protection.

**Progress (2026-09-23):** Notice ack ✅ — `NOTICE_ACK` (Waylink) + `POST /api/noticeboard/notices/{id}/ack`, idempotent, per-user, portal shows an unread count and a "Mark as read" action. Beacon auth ✅ — `BEACON_PUSH`/`CLEAR` (and Noticeboard's `NOTICE_CREATE`/`EXPIRE`) now resolve the acting username from the radio device's binding rather than trusting the payload's own `author` field, closing a real spoofing gap (see `docs/security.md`, `docs/protocol.md`). Replay protection for Beacon was already covered generically — `WaylinkGateway` dedups every op by `mid`, and `PUSH_COOLDOWN_SEC` rate-limits repeat pushes from one author — so nothing new was needed there specifically.

**Progress (2026-09-24):** Today view's "aggregates unread + sync" exit criterion — turned out to be much further along than "not started": `/api/dashboard` already aggregated 5 services' activity, an active-Beacon banner, and network/online-user status. Two real gaps, both fixed: (1) the Noticeboard card showed the *global* active-notice count, not *this user's* unread count — now uses yesterday's `count_unacked(username)`, label changed "Active Notices" → "Unread Notices". (2) The home page's "Sync" status line only ever reflected Dispatch's pending queue — extended to a genuine cross-app aggregate (`pending_total` = Dispatch pending + Postbox outbox), without building the full shared offline-sync subsystem that's still separately tracked as open debt (`priority-review.md` #2). 4 new tests, full suite 133 passed. **Still open:** Groups (not started — no file exists yet, biggest remaining piece of this milestone), Beacon propagation through Outposts (explicitly out of scope for the auth fix — see `docs/protocol.md`'s Beacon section).

**Progress (2026-09-24, later):** Groups core shipped — `server/services/groups/` (`GroupsStore`/`GroupsService`), HTTP routes at `/api/groups*` (portal/HTTP-only in v1, same precedent as Rollcall — no Waylink ops), and a `groups.html` portal page. v1 enforces exactly two ranks (member/admin), not the doc's full 5-role sketch — an explicit, doc-acknowledged v2 deferral. Used by 2 services, meeting the exit criterion: **Locker** (`locker_files.group_id` + `scope='group'`, gated by an injected `is_group_member` lookup — same cross-service pattern as `NoticeboardService.get_binding`) and **Dispatch** (`POST /api/dispatch/conversations/rooms` takes an optional `group_id` that seeds room membership from the group's *current* members — a one-time copy, not live-linked). 12 new tests, full suite 145 passed, 1 skipped. Verified live against the running Station (curl with real per-user sessions for aj/bob/carol — confirmed a non-member genuinely can't see or download a group-scoped file — and a browser pass through the portal UI). M8 is now fully done; all four exit criteria met. See `docs/groups-and-permissions.md` for what's deferred to v2.

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

**From 2026-10-04: follow the [Decentralization track](#decentralization-track-dependency-order), D1 next.** Parallel, no dependencies: the physical Outpost claim test, the Pi install, the LoRa profile field test, hand-checking the Scout's Beacon screens. The list below is the earlier queue, kept for history.

1. ~~**M2e** radio transport crypto~~ ✅ (over-air PASS 2026-09-22)  
2. **M3** mesh/sim peer + shared sync adoption — sim ✅; hardware with Pocket firmware  
3. **M4** identity depth — pairing codes + per-device revocation + `ADMIN_APPROVAL`/admin-role all ✅; Stalwart decision still open  
4. **Hardware spikes (parallel):** MakerHawk GPIO; T-Deck Plus  
5. **M1b Pi AP + TLS** when camp Wi‑Fi is the blocker  
6. Then M5 → M6/M7 — M7 underway on real hardware (Scout apps over LoRa, 2026-10-03)  

**Do not:** Atlas, Workshop, or new portal apps before M2e/M3 network depth.

---

## App maturity matrix

| App | HTTP prototype | Waylink RPC | Over LoRa (air) | Production backend |
|-----|----------------|-------------|-----------------|--------------------|
| Dispatch | ✅ | Partial | ✅ M2c; ✅ Scout (send, live push + ack) | — |
| Postbox | ✅ | Partial | ⬜ | Stalwart later |
| Rollcall | ✅ | — | ⬜ | — |
| Groups | ✅ | — (HTTP-only, same precedent as Rollcall) | N/A | — |
| Commons | ✅ | Partial | ⬜ | Memos later |
| Noticeboard | ✅ | Partial | ⬜ | — |
| Beacon | ✅ | Partial | ⬜ | — |
| Locker | ✅ | Metadata only | N/A (Wi‑Fi bodies) | — |
| Signal | ✅ | Partial | ✅ airtest/ping; ✅ Scout PING | — |
| Fieldbook | ✅ | `WIKI_SEARCH/GET/UPDATE/CREATE` (outline/section/diff; radio-sized compact/chunked forms) | ✅ reads on Scout; edits ⬜ | BookStack later |
| Trailhead | ✅ | `TRAIL_GET` (chunked) | ✅ Scout | — |
| Corkboard | ✅ | `BOARD_SYNC` | ✅ Outpost ↔ Station | — |
| **Atlas** | ⬜ | Spec (M9) | ⬜ `LOC_*` | Offline tiles on Station |
| Finder | ✅ | `SEARCH` | ⬜ | — |
| Control | ✅ (M4) | — | N/A | — |
| Archive | ⬜ | Spec (M10) | ⬜ | Kiwix |

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
| Mesh delivery on hardware (2026-10-04) | Hop-by-hop courier; relays (Outposts, Scouts) may read what they carry; messages signed; Outposts serve nearby Scouts **and** people signed in on their Wi-Fi | Human's direction; design in [mesh-delivery.md](mesh-delivery.md). End-to-end encryption offered, not chosen for now |
| **No device is strictly necessary (2026-10-04)** | Peer object sync for every node; Station = archive/hub/recovery, not a dependency; roadmap track D | Human's direction: a Cybiko-like, local-first network. Refinement, not a rewrite — services, names, hardware and working code kept ([decentralization-review.md](decentralization-review.md)) |
| Offline identity (2026-10-04) | Station community key signs identity + device certificates; PIN unlocks the device key; any node verifies offline | Login and message checks must not need Station; passwords still never cross LoRa |
| Naming (2026-10-04) | Beacon stays alerts; identity has no app name, discovery/presence = Rollcall "Nearby"; Fieldbook = wiki, Commons = social; Courier = a role | Human's choices; keeps every existing service name |
| Tier 2 first choices (2026-10-04) | Wi-Fi to Outpost/Station APs + ESP-NOW Scout↔Scout; fast LoRa profile later | Separate radio from LoRa, so Tier 1 keeps listening; hardware already present |
| **Next build = N2 username/password auth** | One account for portal + Pocket | Overdue; passwordless Station is not community-safe |
| Production LoRa must be encrypted | M2e Reticulum (Heltec = lab only) | Cleartext CBOR on air is unacceptable for real camps |
| Scout replies fit one packet | Radio-sized ops (`compact`/`limit`/`offset`), chunked text, a test guard at 383 bytes | microReticulum on the device can't receive anything larger; Resource transfer is a later speed-up |
| Trailhead built despite the app freeze (2026-10-03) | Human direction: a complete Scout needs "a small web hosted on Station" | Text pages + links over LoRa, not HTML (Waylink ≠ IP networking) |

When we change direction, add a row here and adjust milestones above.

---

## How to use this doc

- Before a coding session: read **Active milestone (N1)** and [priority-review.md](priority-review.md).  
- After a slice ships: mark the step ✅, update the **honest snapshot**, fix README status if user-facing claims changed.  
- Resist “while we’re here” features that aren’t on the near-term queue — park them under a later milestone instead.
