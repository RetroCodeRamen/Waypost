# Waypost Priority Review

**Date:** 2026-09-24 (refresh of the 2026-09-23 review, after the M6 session)
**Method:** Full repo inspection + architecture/roadmap/protocol/ADR review, reconciled against `AGENT_HANDOFF.md`'s message board.
**Intent:** Build order by dependency and network truth — not by app catalog completeness.

Related: [roadmap.md](roadmap.md) · [architecture.md](architecture.md) · [offline-sync.md](offline-sync.md) · [identity.md](identity.md) · [groups-and-permissions.md](groups-and-permissions.md) · [provisioning.md](provisioning.md) · [network-time.md](network-time.md) · [federation-future.md](federation-future.md)

**What changed since the earlier 2026-09-23 review:** M6 went from "sim only, first hardware attempt flaky" to **real standalone Outpost firmware, flashed and verified on hardware** — Heltec V3, Wi-Fi AP + Corkboard + genuine on-device Reticulum (microReticulum, not plaintext, not host-dependent). `OUTPOST_CLAIM` closed the loop that made this only partially useful before: Station can now actually `learn_route()` and reply to a claimed Outpost, reusing the M4 pairing-code system rather than inventing a new one — verified over a live HTTP round trip. That same pass also fixed a real latent bug in Pocket's own radio-pairing path (`PAIR_REDEEM` accepted a `transport_dest` but never called `learn_route`, so a first-time radio pairing couldn't have gotten its own reply). Both physical boards now carry a role-label OLED splash. **Net effect: "No Pocket/Outpost code" is no longer true** — Outpost code is real and hardware-proven; only Pocket (T-Deck) and MakerHawk-specific firmware remain genuinely not started.

**Later the same day:** `ADMIN_APPROVAL` + admin-role — the recommendation from §8 below — got built. `users` gained `is_admin`/`approved_at`; the first account ever registered on a Station bootstraps as admin and auto-approves, so the mode can never deadlock a Station with nobody able to approve anyone; portal `/control.html` (formerly a nav placeholder) lists pending registrations with one-click approve; verified live in a browser end-to-end (register → pending → admin approves → login succeeds), plus 9 new tests. **M4 is now fully built; only the Stalwart-vs-SQLite decision remains, and it's a human call, not a build task** — the rest of this document's references to `ADMIN_APPROVAL` as unbuilt are now historical (kept for the build-order narrative in §6, §8) rather than current status; treat §1's tables as the live source of truth.

**Then, same day again:** picked Noticeboard ack + Beacon auth from §8's Tier 2 list and built it — `NOTICE_ACK`, and a real fix for a genuine spoofing gap (`NOTICE_CREATE`/`EXPIRE` and `BEACON_PUSH`/`CLEAR` over Waylink trusted a self-reported author; now resolved from the device's actual binding, same mechanism Dispatch's `MSG_SYNC` already used). While scoping it, found this document's "Postbox progressive LoRa path — not started" claim was simply wrong — that's already fully built. Corrected throughout; see §7, §8.

**Next day (2026-09-24):** picked the Today/sync dashboard next. Same pattern a third time: checked the code before building, found `/api/dashboard` was already substantially built (5-service activity feed, Beacon banner, network status) — this document's "not started" label undersold it. Two real gaps fixed instead of a rebuild: the Noticeboard card showed the global active-notice count, not the caller's own unread count; the home page's "Sync" line only ever reflected Dispatch, not Postbox's outbox too. 4 new tests, full suite 133 passed. **Three stale "not started" claims caught in two days (Postbox, `ADMIN_APPROVAL`'s actual scope, now this) — treat every status label in this document as a hypothesis, not a fact, per §8's note.**

**Same day, later still:** built Groups/permissions core — this one genuinely *was* "not started" (no file existed, unlike the last three false alarms). `server/services/groups/` (`GroupsStore`/`GroupsService`), HTTP-only routes at `/api/groups*` (no Waylink — same precedent as Rollcall), v1's two enforced roles (member/admin, not the doc's original five), and portal `groups.html`. Integrated with 2 services per M8's exit criterion: Locker (`scope='group'` + `group_id`, membership-gated) and Dispatch (rooms can seed membership from a group at creation, one-time copy not a live link). 12 new tests, full suite 145 passed, 1 skipped. Verified live against the running Station with real per-user sessions (not just the aj-cookie-with-claimed-viewer trick, which — worth noting for future verification — silently no-ops when auth is enforced, since `actor_username()` ignores the claimed name and uses the session's own identity). **This closes M8 entirely** — all four exit criteria met, see `roadmap.md`.

**Same day (Cursor):** review of that Groups commit found three authz holes (any user could read any group's roster; any user could seed a Dispatch room from any group's members; `add_member` could demote the last admin to zero admins) — all closed with tests, 148 passed. Then built the **Fieldbook progressive path** (the last software-only Tier 2 item that was genuinely empty — checked: `server/services/fieldbook/__init__.py` was the only file). `FieldbookStore`/`FieldbookService`, `WIKI_SEARCH/GET/UPDATE/CREATE` over Waylink with outline / section / `since`-diff so a Pocket never pulls a whole page to read or catch up on one part, base-revision conflict detection (409 over HTTP, compact `revision_conflict` + outline over radio, never a silent overwrite), section-level edits, full revision history, portal `fieldbook.html` with an in-editor conflict rebase flow. 17 new tests, **full suite 165 passed, 1 skipped**. Design: `docs/fieldbook.md`. M5's software half is done; what's left of M5 (Pocket offline edit queueing, favorites cache) waits on the shared sync subsystem and T-Deck firmware.

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
| **Corkboard** (per-outpost public noteboard, both sides) | **Real (M6)** — sim + browser proven; Outpost-side firmware flashed and hardware-verified |
| **Standalone Outpost firmware** (Wi-Fi AP + on-device Reticulum) | **Real hardware (M6)** — Heltec V3, identity stable across reboots, `firmware/outpost/` |
| **`OUTPOST_CLAIM`** (Station learns to address a claimed Outpost) | **Real (M6)** — verified over a live HTTP round trip against the running Station |
| **Device pairing codes + per-device revocation** | **Real (M4 slice 1)** — same codes now also drive `OUTPOST_CLAIM` |
| Role-label OLED splash (Outpost + Station boards) | **Real (2026-09-23)** — Outpost hardware-verified; Station via a patched-but-genuine RNode build |
| pytest + Playwright screenshots | Automation — 165 passed, 1 skip as of this review |

### Partially working

| Area | Gap |
|------|-----|
| Dispatch | Sim proves Pocket↔Pocket, courier, and `MSG_SYNC`; **none of it runs on real Pocket hardware yet** (no T-Deck firmware) |
| Outpost | Real firmware + real encryption + claiming all proven on Heltec V3; multi-hop relay *logic* is deliberately not hand-built (Reticulum's own Transport mode handles it) and the physical claim-over-real-LoRa step hasn't been run by a human yet; MakerHawk (the intended production SKU) has unverified GPIO and isn't confirmed ordered |
| Delivery / offline | Durable per-device pending now (Wi‑Fi↔LoRa failover slice); still Dispatch-only — other apps (Postbox, Fieldbook) haven't adopted the shared queue states from `offline-sync.md` |
| Signal | Lists radios / airtest / RNode security state; still no unified "Today" sync surface across apps (though `/api/dashboard`'s `sync` field, extended 2026-09-24, now covers cross-app pending — see Home dashboard row) |
| Identity | Real username/password accounts (N2); pairing UX + revocation + `ADMIN_APPROVAL`/admin-role all real now (M4 fully built); still no crypto device identity beyond that, and the Stalwart-vs-SQLite decision is still open |
| Pi / Waygate | Installer + HTTPS proven in containers; AP + openNDS (Waygate) staged but unrun on real hardware |
| Home dashboard | **More built than this table said (corrected 2026-09-24):** already aggregated 5 services' activity, an active-Beacon banner, and network/user status before today — this row previously undersold it. Two real gaps fixed: Noticeboard card now shows *this user's* unread count (was global active count); "Sync" status now a genuine cross-app total (Dispatch + Postbox), not Dispatch-only. Still open: no explicit date-scoped "Today" framing, and this isn't the shared offline-sync subsystem (item #2 below) — it surfaces what each app already tracks, doesn't unify the tracking itself |

### Not started (architectural / planned)

Pocket (T-Deck) firmware · Outpost firmware **specifically on MakerHawk** (Heltec V3 version is done — see above) · Shared offline-sync subsystem beyond Dispatch · Network time bootstrap (no RTC) · Provisioning product · Station↔Station federation · Fieldbook · Atlas · Finder · Archive · Workshop/Arcade · Stalwart/BookStack/Memos adapters · openNDS (Waygate)

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

- **Hardware is now the pacing item for Pocket and Pi specifically, not Outpost anymore.** M1b and T-Deck-based M3 are still blocked purely on physical arrival. Outpost moved out of this category this session — real firmware exists and runs on Heltec V3; only the MakerHawk-specific build and the physical claim-over-air test remain hardware/human-gated.
- **250-byte LoRa frames** still force compacted Dispatch payloads; easy to regress as more ops move to RNode.
- **Identity** has real pairing/revocation/`ADMIN_APPROVAL` now (M4 fully built, reused for Outposts too), but still no crypto device identity beyond that, and the Stalwart decision is still open.
- **This document's own freeze condition is now stale-adjacent — more so than when this line was first written.** The roadmap's "no Atlas / Workshop / new portal apps until network depth advances" freeze predates M2e, M3-sim, *and* M6. All three have since landed. Whether "network depth" has now advanced enough to revisit the freeze is a call for the human, not this review — flagged here again so it isn't silently forgotten a second time.

---

## 4. Missing foundational features

1. ~~Opportunistic Dispatch (queue → auto-deliver when route/device appears)~~ — **done (N1 ✅)**
2. Shared offline / sync subsystem beyond Dispatch (states visible in Signal/Today; Postbox/Fieldbook haven't adopted it)
3. ~~Account ≠ radio identity depth — pairing UX, revocation~~ — **done (M4 slice 1 ✅, extended to Outposts in M6)**; cryptographic device identity beyond that is still open
4. Network time without public NTP — no RTC on the Pi means 30-day certs are already the practical ceiling (`network-time.md`)
5. Provisioning: Outpost enroll is **done** (`OUTPOST_CLAIM`, M6); Pocket join still needs T-Deck firmware first
6. ~~Groups as shared authz (rooms today ≠ Groups)~~ — **done (v1, 2026-09-24)**: `server/services/groups/`, 2 services integrated (Locker, Dispatch); rooms remain their own concept, seedable from a Group
7. Multi-hop Outpost path + Pocket-as-courier **on real hardware** — **partially done**: Outpost firmware is real and hardware-proven (M6), and Reticulum's own Transport mode handles multi-hop path discovery without app code; Pocket-as-courier still has no real hardware since T-Deck firmware doesn't exist
8. Federation / home-Station assumptions (document only for now)
9. ~~`ADMIN_APPROVAL` registration mode + admin-role~~ — **done, same day** (see header)

---

## 5. Technical debt / risks

| Risk | Why it matters | Status |
|------|-----------------|--------|
| Treating Heltec as production mesh | Would fight Reticulum/RNode if apps grew Heltec-specific assumptions | **Retired** — M2e is done; Heltec plaintext is explicitly lab-only now, and the same boards double as RNode hardware |
| Per-app offline queues | Dispatch/mail already diverge; Fieldbook will fork again | Still open — only Dispatch has adopted `offline-sync.md`'s states |
| Rooms ≠ Groups | Permission sprawl if each app invents ACL | **Resolved (2026-09-24)** — Groups v1 is the one model; Locker/Dispatch consult it via injected lookups, no per-app ACL |
| Portal feature momentum | Tempting to polish Commons/Locker instead of transport | Still open — freeze still in effect |
| Clock skew | Notice/Beacon expiry and certs fail off-grid without Station time | **Sharper now**: Caddy issues real 30-day certs on the Pi, so a Pi that boots weeks behind serves certs phones reject — see `network-time.md` and `pi-setup.md#notes-and-limits` |
| Payload size | LoRa MAX_FRAME 250 — fragmentation or progressive ops needed before rich messages | Still open |
| Uncommitted work | M1b prep + all of M6 (Outpost firmware, Corkboard, `OUTPOST_CLAIM`, RNode display patch) | **Committed as of this refresh** |

---

## 6. Build-order (current position)

```text
proven air path (done)
  → resilient Station-mediated Dispatch + visible queues (done — N1)
    → production transport (done — M2e ✅, over real LoRa)
      → mesh semantics without Station (done in sim — M3 ✅; hardware pending)
        → Outpost as real relay infrastructure (done on Heltec V3 — M6 ✅; MakerHawk pending)
          → Pocket comms foundation (T-Deck) ← hardware-blocked
            → multi-hop courier with a real Pocket ← hardware-blocked
              → identity/presence depth (M4) ← ALMOST DONE, one software-only piece left
                → Postbox / Fieldbook / Notice+Beacon polish
                  → Groups (done ✅) → Commons/Locker → Atlas/Archive → Pocket PDA apps
```

M6 moved Outpost from "sim + flaky hardware attempt" to "real firmware, hardware-verified, Station can address it" — genuinely done, not just de-risked. That leaves exactly two things still hardware-blocked (T-Deck-dependent Pocket work, and M1b's Pi), and one thing nearly done in software (M4 — see §8).

**Freeze:** new portal apps and deep Commons/Locker UX until Tier 1 exits — see the note in §3 about revisiting this now that M2e, M3-sim, *and* M6 are all done.

---

## 7. Priority tiers (adjusted for repo reality)

### TIER 1 — Done (or done-enough for sim)

- ~~Harden **Dispatch** on existing Heltec Station↔peer path~~ — done; extended further (multi-device failover, durable pending)
- ~~Shared **sync/queue** model~~ — done for Dispatch; not yet adopted by other apps
- ~~Keep **radio regression** green~~ — 165 passed, 1 skipped as of this review
- ~~**Rollcall/identity groundwork:** device bind, last-seen, Wi‑Fi vs LoRa reachability labels~~ — done (`RollcallService.get` already computes `wifi`/`lora`/`recent`/`unavailable`)
- ~~**Standalone Outpost firmware**~~ — done on Heltec V3 (M6 ✅); MakerHawk GPIO verification still open, hardware not confirmed ordered
- ~~Document + keep Heltec as **dev transport**~~ — done; Heltec V3 boards now also serve as RNode hardware

### TIER 2 — Build next (mixed: some done, most hardware-blocked)

- ~~`ReticulumTransport` / RNode~~ — **done (M2e ✅)**
- T-Deck Pocket communications foundation (Dispatch + queue + sync-to-Station) — **hardware in transit; sim (`PeerDispatchNode`) is ready to port once firmware exists**
- ~~Outpost store-and-forward firmware~~ — **done on Heltec V3 (M6 ✅)**; MakerHawk-specific build still pending that hardware
- Pocket↔Outpost↔Pocket / courier smoke — Outpost's half is ready; still blocked on real Pocket hardware
- ~~`ADMIN_APPROVAL` + admin-role~~ — **done** (M4 fully built now — see header)
- ~~Postbox progressive LoRa path~~ — **turned out to already be built**, this line was stale (see header)
- ~~Fieldbook progressive path~~ — **done (2026-09-24)**: search → outline → section → `since`-diff over Waylink, section-level edits with base-revision conflict, portal page; see `docs/fieldbook.md`
- ~~Noticeboard ack + Beacon auth~~ — **done (2026-09-23)**; Beacon *propagation* through Outposts explicitly still not started (real scope of its own, not part of the auth fix)
- ~~Groups/permissions core~~ — **done (2026-09-24)**, see header — core + Locker/Dispatch integration
- ~~Unified Today / sync dashboard~~ — **turned out to already be substantially built**; two real gaps fixed 2026-09-24 (see header) — this line was stale, third instance this session
- **M1b Pi AP + TLS** — software done and tested in containers; blocked purely on physical Pi

### TIER 3 — After network is useful

- Commons depth · Locker group folders · Finder · Archive · **Atlas** (GPS/origin already designed — implement after Pocket reports exist)

### TIER 4 — Pocket platform expansion

- Logbook · Planner · Workshop/Lua · Arcade

---

## 8. Recommended next milestone (ONE)

**M4 is done, same day as this line was written** — see the header. Its acceptance shape:
1. ~~Pairing code flow~~ — **done**, proven reusable (Pocket devices + Outpost claiming both use it).
2. ~~Revocation~~ — **done**.
3. ~~Registration modes enforced in the portal UI~~ — **done**.
4. ~~`ADMIN_APPROVAL` gating registrations + admin-role~~ — **done**: first-ever account bootstraps as admin; `/control.html` approves the rest.
5. Stalwart decision — **the only thing left, and it's a human call, not a build task.**

### **Next up: Tier 2 software-only work (pick one)**

With M4 build-complete, nothing left in the priority spine's hardware-free lane is a single obvious next step the way M4 was. **Noticeboard ack + Beacon auth got picked and built the same day** (see header) — while implementing it, checked Postbox against this same list and found its "progressive LoRa path" line was simply wrong: `MAIL_STATUS`/`MAIL_LIST`/`MAIL_GET` already implement exactly that pattern (compact headers, full body on demand, attachments kept Wi-Fi-only) — nothing to build there. What's left, still independent, none blocking each other:

- ~~**Fieldbook progressive path**~~ — **done 2026-09-24**. Was genuinely empty (package marker only — verified before building, per the note below). Now `server/services/fieldbook/`, HTTP + four Waylink ops, portal `fieldbook.html`, 17 tests.
- ~~**Groups/permissions core**~~ — **done 2026-09-24**, see header. Was genuinely unstarted (unlike the three false alarms above) — now the one authz model, integrated with Locker + Dispatch.
- ~~**Unified Today/sync dashboard**~~ — **done 2026-09-24**, see header. Was already ~80% there; the "not started" label was wrong.
- **Beacon propagation through Outposts** — deliberately cut from the auth-fix slice; store-and-forward relay for Beacon the way Dispatch's courier queue already works, real scope of its own.
- **Extend Groups scoping to Noticeboard/Commons** — same injected-lookup pattern as Locker, not built because M8's exit criteria only asked for ≥2 services.

**Before picking the next one, verify the item against the actual code first** — this same review nearly recommended re-building already-finished Postbox work. Two stale-claim near-misses in one project (this one, and the `ADMIN_APPROVAL` staleness the previous refresh caught) is enough to treat every "not started" line in this document as a hypothesis to check, not a fact.

This review doesn't pick one — they're independent enough that the choice is preference/priority, not dependency order. Also worth revisiting now, separately: **the app-catalog freeze** (§3, §11, §12.3) — it's been flagged as stale-adjacent twice now without a decision.

**Out of scope:** anything that needs the Pi or T-Deck; full OIDC for third-party apps; the Stalwart cutover itself.

---

## 9. Roadmap moves — earlier

| Item | Why earlier |
|------|-------------|
| ~~Opportunistic Dispatch / queues~~ | **Done** |
| ~~Sync visibility (Signal/Today)~~ | **Done (2026-09-24)** — dashboard `sync` is now a real cross-app aggregate, not Dispatch-only |
| ~~Device bind / reachability in Rollcall~~ | **Done** |
| ~~Standalone Outpost firmware~~ | **Done on Heltec V3 (M6)** — real encryption, real hardware, not sim |
| ~~`ADMIN_APPROVAL` + admin-role~~ | **Done** — M4 is now fully built except the Stalwart decision |
| ~~Groups/permissions core~~ | **Done (2026-09-24)** — M8 now fully closed; see header |

## 10. Roadmap moves — later

| Item | Why later |
|------|-----------|
| Atlas | Needs Pocket GPS reports (M7); design kept |
| MakerHawk GPIO verify (spike) | Still blocked — hardware not confirmed ordered, unlike Pi/T-Deck |
| Pi AP (M1b) | Software done; genuinely just waiting on the physical Pi now |
| Commons / Locker depth | Already prototyped; networking > polish |
| Fieldbook / rich Postbox | Both built (Fieldbook 2026-09-24); what's left is Pocket-side offline edit queueing, which waits on the shared sync subsystem (#2) |
| Workshop / Arcade / Planner | Pocket platform Tier 4 |
| Federation | Document only |

## 11. Drop or simplify

- Stop adding portal apps until Tier 1 exits — **Tier 1 has now exited, more thoroughly than at the last review** (M6 landed on real hardware since); this is the trigger to revisit the freeze (see §3, §6).
- Do not build Heltec-specific "product" features (keep bridge minimal) — moot now that Heltec's production role is RNode firmware, not the CBOR bridge.
- ~~Do not invent per-app ACL — wait for Groups doc + one authz model.~~ — **the model now exists** (`server/services/groups/`); this is a live constraint, not a future one — any new group-scoped feature integrates with it, never a bespoke table.
- Cardputer as Pocket reference — **rejected**; T-Deck Plus remains Pocket goal (now in transit).
- Live tracking / sub-minute GPS — out; 10–15 min reports only.

## 12. Decisions before more implementation

1. ~~N1 is next~~ — done; ~~M4 is next~~ — **done** (build-complete same day). **Next is a choice among independent Tier 2 software items** — see §8.
2. **Heltec = dev transport; Reticulum/RNode is production** (ADR 0002) — no longer just a target, **proven over real LoRa, and now on Outpost's own standalone firmware too (M6)**.
3. **Revisit the app-catalog freeze.** It was set when Tier 1 was open; Tier 1 has exited (sim-complete through M3, *and now real hardware through M6*). Options: lift it now that transport + mesh semantics + real Outpost hardware are all proven, keep it until M1b/T-Deck land, or redefine "network depth" explicitly. This review still doesn't decide it — flagging it a second time as the most consequential open call.
4. **T-Deck Plus** remains the Pocket SKU; it's now physically in transit, not just a decision.
5. When hardware arrives: MakerHawk GPIO verify *before* writing Outpost product firmware (unchanged) — note the Heltec V3 firmware is already a proven reference to adapt from, not a from-scratch job.
6. ~~Commit the uncommitted M1b work~~ — **done, along with all of M6, as of this refresh.**
7. Open: MakerHawk order/arrival timeline — unlike Pi and T-Deck, not yet confirmed in the handoff.
8. **Stalwart vs. SQLite** — still open, still a human call, unchanged from the prior review. The only thing left in M4; didn't block `ADMIN_APPROVAL`/admin-role, which is now done.

---

## History: original review alignment (2026-09-18)

The original external priority prompt was accepted with one adjustment: multi-hop Pocket↔Outpost tests were Tier-1 *intent* but not the immediate build until hardware/firmware existed. That adjustment held — the immediate build (harden Station↔Heltec Dispatch into opportunistic, queue-visible, reboot-tolerant messaging, then production transport) is exactly what happened, on schedule, through M2e. This section is kept for history; §1–§8 above are the current read.
