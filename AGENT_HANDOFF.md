# Agent handoff — Waypost

**Two-way working document for Cursor and Claude.**  
Whenever the human gives a new direction, **both agents must read this file first**, then update it before handing off or ending a session.

Related truth sources (do not duplicate long plans here):

| Doc | Role |
|-----|------|
| [docs/roadmap.md](docs/roadmap.md) | What’s done / next milestones |
| [docs/priority-review.md](docs/priority-review.md) | Build order and freezes |
| [docs/security.md](docs/security.md) | Trust + encryption matrix |
| [docs/radio-dev.md](docs/radio-dev.md) | Heltec + Reticulum lab runbooks |
| [docs/architecture.md](docs/architecture.md) | System shape |

---

## Protocol (both agents)

1. **Read this file** at the start of any session or after a new user direction.  
2. **Do not** contradict roadmap freezes (no Atlas / Workshop / new portal apps before network depth).  
3. **Update this file** before you stop: current focus, what you changed, what’s blocked, what the other agent should do next.  
4. **Append** to [Message board](#message-board) (newest at top) — short, dated notes. Do not rewrite history; correct with a new note.  
5. **Secrets stay out of git** — never put Pi passwords, Wi‑Fi PSK, tokens, or `.env` contents here. Put placeholders and say “ask human.”  
6. Prefer small vertical slices; update [docs/roadmap.md](docs/roadmap.md) when a milestone status changes.

### Ownership hints

| Area | Default owner | Notes |
|------|---------------|--------|
| Station API, Dispatch, auth, tests | Either | Keep pytest green |
| Portal UI / design | Prefer Cursor when visual | Follow user frontend rules |
| Claude Code / remote machine work | Claude | When human routes work to Claude |
| Pi install over SSH (M1b) | Claude or Cursor | Human provides IP/user/pass out of band |
| Radio / Heltec / RNS lab | Either | Heltec = plaintext lab; RNS = encrypted path |

---

## Current snapshot (update when wrong)

**Date:** 2026-09-23  

**Active milestone:** **M6** Outpost 🟡 — standalone Outpost firmware (`firmware/outpost`) exists, flashed to real hardware (`/dev/ttyUSB1`); identity persistence bugs found+fixed; Station can now reply to a claimed Outpost (`OUTPOST_CLAIM`, verified over live HTTP). Only remaining gap: the physical Outpost-Wi-Fi→`/claim`→real-LoRa leg needs a human to join the AP by hand — everything upstream is proven. **M4** Identity depth **✅ build-complete** — pairing codes, revocation, `ADMIN_APPROVAL`/admin-role all done; only the Stalwart-vs-SQLite decision remains, a human call not a build task. **M1b** Pi — software prep done, waiting on SD card (human has it in the mail) — **Station is this dev machine, not a Pi, until then**; **M7** T-Deck also in the mail. **No single obvious next milestone right now** — M4's completion means the next step is a genuine choice among independent Tier 2 software items (Postbox progressive sync, Noticeboard/Beacon depth, Groups, Today dashboard) — see `docs/priority-review.md` §8.  
**Just finished:** M4 slice 2 — `ADMIN_APPROVAL` + admin-role, portal `/control.html` ([docs/identity.md](docs/identity.md)); before that a full docs refresh (`roadmap.md`, `priority-review.md`, `security.md`) plus committing all of M6 in one commit (`c4f0cc4`); before that M6 `OUTPOST_CLAIM` — Station can reply to a claimed Outpost, reusing the M4 pairing-code system exactly; fixed a matching latent bug in Pocket radio-pairing along the way ([docs/protocol.md](docs/protocol.md), [docs/architecture.md](docs/architecture.md)); before that M6 standalone Outpost firmware — real Reticulum via microReticulum (not plaintext), Wi-Fi AP + Corkboard web UI, hardware-verified identity persistence across reboots ([firmware/outpost/README.md](firmware/outpost/README.md)); before that M6 Corkboard — both sides in sim; before that M6 slice 1 — `OutpostNode` LoRa relay (sim) + courier hop-cap/TTL; before that M4 slice 1 — pairing codes + per-device revocation; before that **M2e ✅** over real LoRa

**Have today**

- Laptop Station API + SQLite + portal (auth-gated)
- N2: register/login, PBKDF2 hashes, session cookie + Bearer; lab users `aj`/`bob` password `waypost1` (lab only)
- N1 opportunistic Dispatch; Heltec M2c air path (plaintext stand-in — **boards no longer carry that firmware**, see below)
- M2e ✅: `ReticulumTransport`; `dispatch_rns_airtest` PASS on TCP lab **and over LoRa** (`--rnode`, 915 MHz, SF8/125 kHz); bind `transport_dest` for `rns-*` pushes; Signal shows security + RNode settings
- **Hardware state:** `/dev/ttyUSB0` (Station's radio) runs **Waypost's own patched build** of RNode firmware 1.86 (`firmware/RNode_Firmware/` — adds the button-triggered logo splash, otherwise unmodified; still genuine RNode, not a firmware swap). `/dev/ttyUSB1` was reflashed 2026-09-23 with the standalone Outpost firmware (`firmware/outpost`) — **no longer RNode**; `WAYPOST_TRANSPORT=serial` (Heltec plaintext) will not work on either board until `firmware/heltec` is reflashed onto it
- M3 (sim): `PeerDispatchNode` — peer↔peer, `MSG_SYNC` (+ authz), **multi-hop** `handoff_to` (aj→bob→carol), **Wi‑Fi↔LoRa failover**; `test_mesh_dispatch.py`
- Dispatch pending is durable for every recipient until a device confirms (outbox poll, `MSG_ACK`, `MSG_PUSH` reply, or `MSG_SYNC`); state is `SENT` until then, not `DELIVERED`
- `deploy/raspberry-pi/install.sh` — idempotent Pi installer, tested twice in Debian Bookworm + Trixie containers (not yet on a Pi). Caddy (official repo, ≥2.8) offline local CA, 30-day leaves; `/trust.html` over HTTP; `Secure` session cookie over HTTPS; production env has no demo users and hides the lab hint
- AP (hostapd/dnsmasq) staged; only `--enable-ap` switches wlan0, and it refuses if SSH arrives over wlan0
- M4: pairing codes (`POST /api/auth/pairing/create` + `/redeem`, no session needed to redeem; also Waylink `PAIR_REDEEM`) and per-device revocation (`GET /api/dispatch/devices`, `POST /api/dispatch/devices/unbind-one`); portal `devices.html`; `login.html` now hides/explains "Create account" per registration mode. `server/tests/test_pairing.py`, 96 passed
- M3: courier `hops`/`for_user` columns on `courier_queue`; `MAX_COURIER_HOPS=3` caps Pocket-to-Pocket relay (Station-bound and Outpost relay are exempt); `COURIER_TTL_SECONDS` (24h) + `DispatchStore.purge_expired_courier`, swept opportunistically. Fixed a real bug this surfaced: `handoff_to`'s `for_user` was re-derived from the DM conversation id using `self.username` as pivot — broke for any pure courier (not a party to either side) past hop 2; now stored on the row and threaded through unchanged
- M6 (sim): `OutpostNode` (`server/services/dispatch/outpost.py`) — uncapped relay, preferred-route caching to Station (find shortest, prefer it, rediscover on failure), direct hand-off between co-located Pockets. Shares plumbing with `PeerDispatchNode` via new `WaylinkPeerNode` base (`waylink_node.py`) — extracted after confirming a zero-diff run of all 11 prior M3 tests. Fixed a real deadlock this surfaced: a handler that itself issues a nested outbound request (Outpost's direct hand-off) blocked the single receive-loop task forever waiting on its own reply — `WaylinkPeerNode` now runs each handler as its own task (dedup still happens synchronously first). `server/tests/test_mesh_dispatch.py` +3 tests, 102 passed, 1 skip
- M6 (hardware, in progress): `tools/radio/outpost_airtest.py` — both Heltec boards as Station + one Outpost. Fixed two real `ReticulumTransport` bugs found via this: `get_route`/`reachable` never resolved logical node_ids to RNS hashes (only `send` did — `get_route` also returned `hops=None`/no `next_hop`, which `OutpostNode`'s routing logic depends on; now returns `hops=1, next_hop=destination` when reachable, since Reticulum's own mesh routing is opaque below this abstraction anyway). One run completed a full send→process round trip over real LoRa; hasn't reproduced reliably since — looks like RF/timing, not app logic (sim passes consistently). **Not resolved** — needs more patient hardware debugging next session
- M6 Corkboard (sim, both sides): new `server/services/corkboard/` (`{constants,store,service}.py`) — per-outpost public note board, `body` + free-text `signature` (no account needed to author, matching walk-up-at-Outpost's-Wi-Fi). `BOARD_SYNC` Waylink op ingests notes keyed by `env.src` (dedup by `mid`, auto-registers the outpost), piggybacks that outpost's Station-composed outbox back in the same response (mirrors `MSG_SYNC`). Reads/posts always scoped to one outpost — no merged cross-outpost view, by design. HTTP: `GET /api/corkboard/outposts`, `GET/POST .../outposts/{id}/notes`. Portal `corkboard.html`. `OutpostNode.add_local_note`/`sync_corkboard` complete the loop — a `synced_at` marker (not deletion) tracks what's reached Station, since the Outpost's copy is the durable primary and never clears. Verified end-to-end in the browser (portal → outbox → simulated resync) and in sim (`OutpostNode` ↔ `CorkboardService` full round trip, including idempotent resync and receiving a piggybacked Station note). `server/tests/test_corkboard.py` + `test_mesh_dispatch.py`, 110 passed. **Still open:** everything Wi-Fi/firmware-side (needs real hardware or firmware work), Beacon origin-outpost extension

**Don’t have yet**

- M1b on real Pi: run installer, `--enable-ap`, phone joins `WAYPOST` → trust → HTTPS; openNDS (Waygate)
- Station clock bootstrap (no RTC) — TLS certs are only 30 days tolerant ([network-time.md](docs/network-time.md))
- The physical claim test over real LoRa (join `WAYPOST-OUTPOST`, use its `/claim` page — needs a human, see 2026-09-23 message board entry); Station's board still shows RNode's own diagnostics, not a Waypost-branded splash (code's ready in `firmware/heltec`, human chose to hold off — see message board); Beacon origin-outpost extension; session-isolated Wi‑Fi terminal; Pocket firmware (M7)
- Stalwart integration-vs-cutover decision (M4) — the only thing left in that milestone

**Freezes:** no new portal apps; no Atlas; no Workshop until network depth advances.

**Human direction (Pi):** Prefer Raspberry Pi OS Lite 64-bit + SSH first (not image-first). Human will provide IP / user / password out of band when ready. Then validate M1b; bake an image later.

---

## Active work / handoff slots

Fill these when you start or finish work so the other agent doesn’t collide.

| Slot | Agent | Status | Branch / notes |
|------|-------|--------|----------------|
| M2e RNode LoRa | Cursor | **done** | Over-air PASS 2026-09-22 |
| M1b Pi stack | Cursor | prep done, **committed** | Installer + HTTPS ready; run on Pi when SD card arrives ([pi-setup.md](docs/pi-setup.md)) |
| M3 peer + multi-hop + failover sim | Cursor | done | Sim exit criteria met; hardware waits on M6/M7 |
| Docs refresh | Claude | done | `priority-review.md` rewrite + smaller fixes across roadmap/architecture/hardware docs — see message board |
| M4 pairing codes + device revocation | Claude | **done (slice 1)** | Pairing codes + per-device revoke + honest registration-mode UI shipped |
| M4 ADMIN_APPROVAL + admin-role | Claude | **done (slice 2)** | `/control.html`, first-user-bootstraps-admin, login gated on approval. Stalwart cutover still open — see message board |
| M6 OutpostNode (sim) | Claude | **done** | Uncapped relay + preferred-route caching, sim-tested. Corkboard/Beacon-extension/Wi‑Fi terminal are follow-up slices, not started |
| M6 OutpostNode (hardware, `outpost_airtest.py`) | Claude | **superseded** | Both-Heltecs-as-RNode stand-in; superseded by real Outpost firmware existing now, not pursued further |
| M6 Corkboard | Claude | **done, both sides (sim)** | `OutpostNode.sync_corkboard` + `CorkboardService` full round trip verified in sim and browser |
| M6 standalone Outpost firmware | Claude | **hardware bring-up done** | `firmware/outpost` flashed to `/dev/ttyUSB1`, identity persistence verified across reboots |
| M6 OUTPOST_CLAIM | Claude | **done, verified over live HTTP** | Station can reply to a claimed Outpost; physical Wi-Fi→radio leg still needs a human — see message board |

**Cursor last session:** M1b prep (Pi installer, offline HTTPS, SD guide); prior: RNode flash + M2e over-air PASS.  
**Claude last session:** M4 finished — ADMIN_APPROVAL + admin-role, docs refresh, M6 committed (see message board).

---

## Environment cheat sheet (lab)

```bash
# Laptop Station (encrypted LoRa — current board state)
WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=rnode \
  WAYPOST_LORA_DEVICE=/dev/ttyUSB0 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station-rnode \
  uvicorn server.api.main:app --host 127.0.0.1 --port 8000
# Peer over LoRa on board 2
python -m tools.radio.dispatch_rns_airtest --rnode /dev/ttyUSB1

# Laptop Station (Heltec plaintext lab — needs firmware/heltec reflashed first)
WAYPOST_TRANSPORT=serial WAYPOST_LORA_DEVICE=/dev/ttyUSB0 \
  uvicorn server.api.main:app --host 127.0.0.1 --port 8000

# Laptop Station (encrypted RNS TCP lab)
WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=tcp_server \
  WAYPOST_RNS_TCP_PORT=4242 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station \
  WAYPOST_RNS_PORT=37429 \
  uvicorn server.api.main:app --host 127.0.0.1 --port 8000

# Tests
source .venv/bin/activate && python -m pytest server/tests/ -q

# RNS Dispatch airtest (Station must be reticulum TCP server)
python -m tools.radio.dispatch_rns_airtest
```

Portal login: http://127.0.0.1:8000/login.html  

**Never** send passwords over LoRa. Heltec CBOR is not privacy.

---

## Message board

### 2026-09-23 — Claude (M4 finished: ADMIN_APPROVAL + admin-role; docs refreshed; M6 committed)

**Re:** "Fix stale docs, commit M6, then start the next set of things we can get to without the T-Deck or Pi up and running" — following a full project review (done/in-progress/needs-planning/doc-health) requested earlier the same turn.
**Did, in order:** (1) Refreshed `docs/roadmap.md`'s top-level snapshot table and `docs/priority-review.md` (which predated this entire session's M6 work) to match reality, plus `docs/security.md`'s encryption table. (2) Committed all of M6 — standalone Outpost firmware, Corkboard, `OUTPOST_CLAIM`, role-label displays, the vendored/patched RNode firmware, 80 files, one commit (`c4f0cc4`). (3) Picked the priority review's own recommendation — the one remaining hardware-free piece of M4 — and built it: `ADMIN_APPROVAL` registration mode + admin-role.
**M4 slice 2 — `ADMIN_APPROVAL` + admin-role:** `users` gained `is_admin`/`approved_at` (migration grandfathers every pre-existing account — nobody gets retroactively locked out). Registering under `ADMIN_APPROVAL` creates the account but issues no session; `POST /api/auth/login` rejects until `POST /api/auth/approve` (new `get_current_admin` dependency) sets `approved_at`. **The first account ever registered on a Station bootstraps as admin, auto-approved** — otherwise an `ADMIN_APPROVAL` Station could never have anyone able to approve anyone. Found and fixed a real regression risk before it shipped: `ensure_user` (used by device-bind flows and lab-user seeding, not the public register path) would have locked out the lab demo users (`aj`/`bob`) under my first draft of the unconditional login approval-check — fixed by auto-approving `ensure_user`-created accounts (safe: they get no password hash either way, so `ADMIN_APPROVAL`'s actual purpose — gating who can log in with a password — is untouched). Also made lab-seeded `aj` an admin so the new Control page is testable in dev without a separate bootstrap flow.
**Portal:** `/control.html` — the "Control" nav item was a `soon: true` placeholder since the beginning of this project; now real. Lists pending registrations, one-click approve. `login.html`'s `ADMIN_APPROVAL` handling changed from "disable the button, say not available" (M4 slice 1's honest-but-incomplete stance) to actually working — button re-enabled, and a successful pending registration now shows "waiting on admin approval" instead of silently doing nothing.
**Verified:** 9 new tests (`server/tests/test_auth.py`) — bootstrap-admin, pending-blocks-login, approval-unblocks-login, double-approve rejected, OPEN/INVITE_ONLY unaffected, full HTTP round trip, non-admin 403 on admin routes. Full suite 122 passed (up from 115), 1 skipped. Verified live in a browser against a throwaway `ADMIN_APPROVAL`-mode instance: registered "carol" → confirmed pending server-side → logged in as admin "aj" → Control page showed carol pending → clicked Approve in the real UI → confirmed carol could then log in. Browser login had the same intermittent first-attempt flakiness noted in earlier entries (unrelated to this feature — works on retry with explicit ref-based clicks).
**Docs:** `identity.md`, `security.md`, `roadmap.md` (M4 marked ✅ build / 🟡 Stalwart decision), `priority-review.md` (marked done everywhere it was flagged unbuilt, replaced the stale "M4 next" recommendation with an honest "pick one, they're independent" list of what's left in Tier 2).
**Next for other agent:** No single obvious next step — genuinely independent choice among Postbox progressive LoRa path, Noticeboard ack + Beacon auth, Groups/permissions core, or the Today/sync dashboard (`priority-review.md` §8). Separately, the app-catalog freeze has now been flagged as stale-adjacent three times across two reviews without a decision — worth raising directly with the human rather than a fourth silent flag.
**Blocked:** Nothing.

### 2026-09-23 — Claude (OLED role labels — prioritized mid-session)

**Re:** "Can you also make putting the labels and graphics on the screens of the LoRa devices kind of a priority — I would like to know which device is which when I look at them easily." Pulled forward from the M2 backlog note (spec captured there earlier this session).
**Did:** Generated a monochrome 40x40 XBM icon from the real brand asset (`web/portal/static/brand/waypost-mark-256.png`, threshold-composited and resized — `firmware/*/src/waypost_mark.h`, ~200 bytes, not hand-drawn). Added U8g2 (`olikraus/U8g2`) to both firmware projects; found the real `SDA_OLED`/`SCL_OLED`/`RST_OLED` pins (17/18/21) from the board's own `pins_arduino.h` in the installed PlatformIO framework rather than guessing — V2 has different pins (4/15/16), scoped this to V3 only since that's the hardware actually on hand and testable. Text is runtime-centered via `getStrWidth()` rather than hand-placed, since I can't see the physical screen to verify pixel-exact layout.
**`firmware/outpost` — done and verified on hardware:** flashed to `/dev/ttyUSB1`, clean boot (no I2C errors, identity still stable at the same hash as before). Shows the mark + "OUTPOST".
**`firmware/heltec` (Station's board) — written, compiles clean, deliberately not flashed.** `/dev/ttyUSB0` runs vendor RNode firmware for Station's actual production radio; `firmware/heltec` is the old plaintext lab bridge, and flashing it replaces RNode until reflashed back via `rnodeconf`. Asked the human before touching a live, working radio link rather than assuming — first checked whether it was even necessary: RNode firmware's own source (`markqvist/RNode_Firmware`'s `Boards.h`) shows `HAS_DISPLAY true` for `BOARD_HELTEC32_V3`, meaning RNode already drives that OLED with its own diagnostics (checked via `gh api`/`curl` against the RNode repo, not by opening the live serial port — Station's Python process has `/dev/ttyUSB0` open right now, and a second connection could have interfered with it). Human's call: hold off — the two boards likely already look distinct enough from different firmware alone; revisit later on request.
**Next for other agent:** Nothing blocking. If the human later wants Station's board actually branded, the code's ready in `firmware/heltec` — just needs the flash + `rnodeconf` round-trip, or MakerHawk hardware once it exists (same approach applies, GPIO still needs verifying — `docs/hardware/makerhawk-v3.md`).
**Blocked:** Nothing.

**Update, same session:** human asked directly — "update the rnode screen to just show the waypost logo when the action button is pushed." Different approach than the above: rather than swap Station's board to `firmware/heltec` (replaces RNode), **patched RNode firmware itself**. New `firmware/RNode_Firmware/` — vendored, trimmed copy of upstream `master` (confirmed same version already flashed: 1.86, `Config.h` MAJ_VERS/MIN_VERS), patched additively (new ~0.7-1.3s button-hold gesture → 3s Waypost logo; the button's four existing duration behaviors — quick-tap BT toggle, sleep, BT pairing, console — are otherwise untouched, sleep's threshold just moved ~0.6s later to make room). Built via upstream's own `arduino-cli` toolchain (not PlatformIO — had to install arduino-cli + pin ESP32 core 2.0.17 to match what upstream release-tests against, plus their 6 required Arduino libraries). Confirmed *before* touching the live device that Reticulum's Python `RNodeInterface.validate_firmware()` only checks the self-reported version number over serial, not a firmware hash — so a patched-but-same-version build would be accepted exactly like the stock binary. User confirmed the gesture design (new short hold, quick-tap untouched) and region (US 915MHz — turned out not to matter, `BOARD_MODEL=0x3A` is frequency-agnostic; Station's own serial config sets the actual frequency at runtime like today) via AskUserQuestion before building. User then explicitly approved the flash itself (the sandbox's auto-mode classifier blocked the first attempt, correctly, as a physical-hardware-write action — asked, got "Please run it," then proceeded). **Flashed to `/dev/ttyUSB0`. Station restarted and reconnected cleanly** — same destination hash (`70a798ca48cfc9e8993fd3442c0ec50c`), `/api/health` 200, no errors. **Still unverified: whether the logo actually renders right on the physical screen** — no camera/visual access from here; needs the human to hold the action button ~1s and look. `firmware/RNode_Firmware/README.md` has full rebuild/reflash instructions and the exact diff explanation.
**Next for other agent:** If the human reports the logo looks wrong (position, size, garbled bits — MSB vs LSB bit-order mistakes are the likely failure mode, see the README's warning about not mixing `WaypostLogo.h`'s bit order with `waypost_mark.h`'s), the fix is in `firmware/RNode_Firmware/Display.h`'s `draw_waypost_logo()`. Otherwise this thread is closed.
**Blocked:** Nothing — done, pending only the human's visual confirmation.

### 2026-09-23 — Claude (M6: OUTPOST_CLAIM — Station can now reply to an Outpost)

**Re:** "Let's keep going with the next pass" — picked up the real gap from the previous entry: Station couldn't reply to an Outpost it hadn't been manually told about.
**Did:** `OUTPOST_CLAIM` (`SVC_CORKBOARD`), reusing the M4 pairing-code system exactly rather than inventing anything new — a Station user generates a code on Corkboard's new "Claim an outpost" portal section (same `POST /api/auth/pairing/create` endpoint Pocket pairing already uses), a human enters it on the Outpost's own new `/claim` Wi-Fi page, and the Outpost's claim request carries its own destination hash directly in the payload. `PairingService.redeem_outpost_code`/`handle_outpost_claim` call `transport.learn_route(node_id, transport_dest)` **synchronously before returning** — `WaylinkGateway._handle_packet` resolves and sends the reply only after the handler returns (`server/gateway/waylink.py`), so this is what makes even a never-before-seen Outpost's very first request routable at all. `outposts` table gained a `transport_dest` column (migration-guarded); Station rehydrates claimed routes at startup, same pattern as `device_bindings`.
**Found and fixed a matching latent bug along the way** (not scope creep — identical bug class, same file, needed the same capability): the existing Pocket radio-pairing path (`PAIR_REDEEM`) accepted `transport_dest` in its payload but never called `learn_route` — so a radio-only device pairing for the first time couldn't actually receive its own success reply either. Two-line fix in `handle_rpc`/`redeem_code`.
**Verified:** `server/tests/test_pairing.py` +5 tests (service-level redemption, bad-hash rejection, reused-code rejection, full RPC round trip, the PAIR_REDEEM regression) — 115 passed, 1 skipped, full suite. Portal UI verified in a real browser (login flaked on the first attempt again — same `next=` redirect issue noted in the M4 entry below, worked on retry with explicit ref-based clicks): code generated, live countdown, real `POST /api/auth/pairing/create` 200. Full gateway path verified live over HTTP against the running Station (`curl`: login → create code → `OUTPOST_CLAIM` via `/api/waylink/rpc` → `ok:true` → `GET /api/corkboard/outposts` shows the claimed outpost with the right hash). Firmware (`/claim` GET+POST, `waylink::encode_outpost_claim_request`, refactored `connect_to_station`/`send_and_await_reply` helpers shared with `refresh_board`) compiles clean and is flashed to `/dev/ttyUSB1`.
**Not yet verified:** the physical leg — someone joining the Outpost's own `WAYPOST-OUTPOST` Wi-Fi and using its `/claim` page for real, over real LoRa. This sandbox can't join that AP (would mean switching the dev machine's network away from its normal LAN/internet — didn't do this without asking). Everything upstream of that physical step is proven; this is the one remaining unknown.
**Next for other agent:** Hand the physical claim test to the human (join `WAYPOST-OUTPOST`, generate a code on `/corkboard.html`, enter it at `http://192.168.4.1/claim`), or move to OLED role labels (independent, spec already captured in roadmap M2 backlog) while that happens.
**Blocked:** The physical radio leg needs a human with a phone, not more agent work.

### 2026-09-23 — Claude (M6: standalone Outpost firmware — first hardware bring-up)

**Re:** "The outpost should exist completely in the Heltec device" (rejected an earlier Wi-Fi-only-first scoping) → "Why can't we use reticulum from the go?" (rejected plaintext LoRa; correctly pushed back on an unverified assumption) → plan revised and approved around **microReticulum** (`attermann/microReticulum`, Apache-2.0 — a real, maintained C++ port of the actual Reticulum protocol, not a host-only library as I'd wrongly assumed).
**Did:** New `firmware/outpost/` PlatformIO project, Heltec V3 target, flashed to real hardware on `/dev/ttyUSB1` (Station's `/dev/ttyUSB0` untouched). Wi-Fi AP (`WAYPOST-OUTPOST`) + a small web UI ("The Outpost" — post a note + optional signature, list notes, Refresh-to-sync), real on-device Reticulum identity/destination, `BOARD_SYNC` speaks the exact same wire shape `OutpostNode.sync_corkboard`/`CorkboardService` already use — hand-written compact CBOR codec (`src/waylink_cbor.{h,cpp}`, not a general library, see its header comment for why). `lib/lora_interface/` vendored unmodified from microReticulum's own examples (already has a `BOARD_HELTEC_V3` pin mapping matching `firmware/heltec`'s independently-verified pins exactly — lucky, not planned).
**Two real bugs found and fixed on real hardware, not sim** — the destination hash was changing on every reboot, which would have made "claiming" an Outpost impossible: (1) `LittleFSFileSystem::init(true)` runs a self-test against a relative path that ESP32's VFS always rejects, so the "self-test failed" branch reformatted the filesystem **on every single boot** — fixed by calling `init(false)` (LittleFS's own `begin(true, ...)` still auto-formats a genuinely fresh/corrupt filesystem regardless). (2) `Reticulum::storagepath()` defaults to `"."` and gets reset by `Reticulum()`'s own constructor — fixed by setting it *after* construction, *before* `.start()`. That second fix only partially worked: `time_offset`/`transport_identity` pick it up, confirmed via boot log, but Transport's path/known/hashlist stores are static objects built before `setup()` runs at all, so they're stuck with `"."` regardless — documented as a known limitation in `firmware/outpost/README.md` rather than chased further (would mean patching the vendored library). Net result: **this Outpost's own identity is confirmed stable across four consecutive real reboots** (same destination hash every time); Reticulum's own path/announce cache just starts cold each boot instead of warm — a performance cost, not a correctness one.
**Verified on real hardware:** clean `pio run` build (15.5% RAM, 68.3% flash), flash succeeds, boots, Wi-Fi AP comes up, LoRa radio receives real packets (RSSI/SNR logged), identity persists across reboots. **Not yet verified:** the actual `BOARD_SYNC` round trip over air, the web UI itself (this sandbox can't join the Outpost's own Wi-Fi AP to browser-test it — different network namespace, same limitation as always with this environment).
**Real gap surfaced, not yet built:** the user asked directly — "this needs a way for a station to claim an outpost." Checked, and it's real: `ReticulumTransport` can only reply to a peer whose destination hash it already knows via `learn_route()`, and nothing populates that for Outposts automatically today (only a manual call, same as `tools/radio/outpost_airtest.py` uses). The existing M4 pairing-code system (`server/services/auth/pairing.py` + `dispatch_routes.py`'s `learn_route` call) is the right pattern to extend, not reinvent — likely: Station listens for Reticulum announces, portal surfaces "unclaimed outposts heard," a logged-in user claims one. **Scoped in conversation, not designed or built yet** — needs its own plan pass before touching Station-side Python.
**Other request captured, not built:** role labels (Station: "waypost" + logo; Outpost: "outpost" + icon only) on the boards' onboard SSD1306 OLED, so the two physical boards are visually distinguishable. Captured with full spec in `docs/roadmap.md`'s M2 backlog note (2026-09-23) rather than implemented now — didn't want to interrupt firmware bring-up mid-debug; both `firmware/heltec` and `firmware/outpost` would need a small display splash, same driver either way.
**Next for other agent:** Two independent next slices, pick either: (1) the Station-side "claim an outpost" flow (Python — announce listening, portal UI, `learn_route` wiring) — needed before a real `BOARD_SYNC` can complete over air; (2) OLED role-label splash on both boards (firmware, cosmetic, no dependencies on anything else). Neither blocks the other.
**Blocked:** Nothing — real hardware in hand, no external dependency.

### 2026-09-23 — Claude (M6: Corkboard, Outpost-side — closes the loop)

**Re:** "Let's finish outpost before syncing."  
**Did:** `OutpostNode` now owns a `CorkboardStore` (own local board, durable primary — never cleared) with `add_local_note(body, signature)` and `sync_corkboard(station_node_id=None)`. Added a `synced_at` column to `corkboard_notes` (marks a locally-authored note as confirmed-at-Station without deleting it — the durability model is inverted from Dispatch's courier queue on purpose). `sync_corkboard` uploads not-yet-synced local notes, ingests whatever Station piggybacks back in the same response, marks piggybacked notes synced immediately (they arrived from Station, so they're already there by definition). Updated the `_outpost`/`_station` test helpers in `test_mesh_dispatch.py` (constructor now requires `corkboard_store`; `_station` returns a 3-tuple with the `CorkboardService`) — 5 call sites, mechanical, all still passing. 2 new tests: full round trip + idempotent resync, and receiving a piggybacked Station note. Full suite 110 passed, 1 skip.  
**Corkboard is now complete in sim, both directions** — Station and Outpost each independently proven, and now proven talking to each other via a real `BOARD_SYNC` round trip in the mesh sim (not just the browser demo from the previous entry). What's left is explicitly hardware/firmware territory (Wi‑Fi AP + local web server + session isolation) or a separate agreed piece (Beacon origin-outpost extension) — not more Station/Outpost application logic.  
**Next for other agent:** Your call — Beacon origin-outpost extension (independent, sim-only, no hardware needed) or return to the unresolved `outpost_airtest.py` hardware flakiness. Both are legitimate next steps; neither blocks the other.  
**Blocked:** Nothing — sim-only, no hardware needed for this piece.

### 2026-09-23 — Claude (M6: Corkboard, Station-side, sim-only)

**Re:** "Build Corkboard's Station-side logic first, sim-only" — after confirming there's currently no way to actually log into an Outpost over Wi‑Fi (that needs real ESP32 firmware, a different stack from this repo's Python, not started).  
**Did:** New `server/services/corkboard/` module (`constants.py`, `store.py`, `service.py`) mirroring Noticeboard's shape, not Dispatch's — Corkboard's trust model is genuinely different (free-text signature, not an account) and its durability model is inverted (Outpost's copy is primary and never clears; Station's is backup). Three tables: `outposts` (auto-populated registry, keyed by `env.src` so an Outpost can't claim another's identity), `corkboard_notes` (per-outpost, dedup by `mid`, no cross-outpost query exists — enforced by only ever querying with an explicit `outpost_id`), `corkboard_outbox` (Station-composed notes queued per outpost). New `SVC_CORKBOARD`/`OP_BOARD_SYNC` in `shared/protocol/envelope.py`. `CorkboardService.sync` ingests a batch and piggybacks that outpost's outbox back inline — same "the response is the delivery confirmation" shape as `DispatchService._rpc_sync`. HTTP: `GET /api/corkboard/outposts`, `GET/POST .../outposts/{id}/notes`. Portal `corkboard.html` + `corkboard.js/css`, nav entry in `shell.js`.  
**Verified end-to-end in the browser** (not just pytest): started a dev server, simulated a `BOARD_SYNC` from a fake `outpost-ridge` via a raw envelope + curl (since `OutpostNode` has no sync method yet — out of scope this slice, see below), logged into the portal, saw the outpost and its two seeded notes render correctly, posted a new note from the UI, then simulated a second sync and confirmed the posted note came back in the piggyback. `server/tests/test_corkboard.py` (6 tests) + full suite: 108 passed, 1 skip.  
**Deliberately out of scope, not silently dropped:** `OutpostNode`'s own local Corkboard store + a `sync_corkboard()` method (the wire contract is ready for it — Station needs zero further changes when that lands), the Beacon origin-outpost extension, and anything Wi‑Fi/firmware.  
**Next for other agent:** `OutpostNode`-side Corkboard sync is the natural next slice (mirrors `PeerDispatchNode.sync_with_station`'s shape closely). Beacon origin-outpost extension is independent and could go either before or after it.  
**Blocked:** Nothing — sim-only, no hardware needed.

### 2026-09-23 — Claude (M6: OutpostNode sim + first hardware attempt)

**Re:** Continuation of the architecture conversation — pairing codes/revocation, hop-cap+TTL, and Outpost architecture (routing/Corkboard/Beacon-extension/session-isolated terminal) all got discussed and largely agreed on; this session built the first concrete piece: Outpost routing/relay.  
**Did:** `server/services/dispatch/outpost.py` (`OutpostNode`) — infrastructure relay node, no username, never a message's final recipient. Uncapped hops (exempt from `MAX_COURIER_HOPS`), preferred-route caching to Station (`_route_to_station`: cache the discovered next hop via `Transport.get_route`, keep using it while it still works even if a shorter route appears, rediscover on failure), direct hand-off when two Pockets are co-located at the same Outpost. Extracted shared transport/request-response plumbing into `server/services/dispatch/waylink_node.py` (`WaylinkPeerNode`) so `PeerDispatchNode` and `OutpostNode` don't duplicate it — verified zero-diff on all 11 prior M3 tests before adding anything new.

**Two real bugs found and fixed along the way** (not scope creep — both blocked the feature from working at all):
1. **Deadlock**: a handler that itself issues a nested outbound request and awaits the reply (Outpost's direct hand-off) blocked the node's single receive-loop task forever, since nothing was left running to receive that reply. `PeerDispatchNode` never hit this because its handlers only ever store-and-ACK, never call out mid-handler. Fixed by having `WaylinkPeerNode` run each handler as its own task (mid-dedup still happens synchronously first, before any handler `await`).
2. **Station-dialect mismatch**: `OutpostNode`'s Station-bound relay was about to send the peer-relay envelope shape (`{message, final_dest, for_user, hops}`) straight to Station, which only understands the flat `{sender, body, peer}` shape `_rpc_send`/`sync_with_station` already use. Fixed with a dedicated `_deliver_to_station` that speaks Station's existing dialect unmodified on the final hop only — everywhere else (Outpost-to-Outpost, Outpost-to-Pocket) still uses the peer-relay envelope.

`server/tests/test_mesh_dispatch.py` +3 (route caching/stickiness, uncapped 5-outpost relay reaching Station end-to-end, direct match between co-located Pockets). Full suite 102 passed, 1 skip.

**Then tried real hardware** — both Heltec V3 boards (Station's own + a temporary Outpost stand-in, same precedent as Heltec-before-RNode). New `tools/radio/outpost_airtest.py`. This found **two more real bugs in `ReticulumTransport`** (pre-existing, not introduced this session, just never exercised until OutpostNode's routing logic leaned on them): `get_route`/`reachable` never resolved logical node_ids to RNS hashes the way `send` already did (so `reachable("station")` always failed), and `get_route` returned `hops=None`/no `next_hop` — a stub that MockTransport's real BFS never surfaced as broken. Fixed both (`get_route` now returns `hops=1, next_hop=destination` when reachable — Reticulum's own routing is opaque below this abstraction, so that's the honest single-conceptual-hop answer). One run then completed a full send→process round trip over real encrypted LoRa (Station genuinely received, decrypted, and processed the relayed message). **Later runs haven't reproduced it reliably** — the failure signature shifted between attempts in a way that doesn't point at a code bug I could keep chasing from logs alone; smells like RF/timing between back-to-back runs. Stopped after 5 real hardware attempts rather than keep grinding blind. Docs updated: `docs/offline-sync.md`, `docs/architecture.md`, `docs/roadmap.md` (M6), `docs/security.md` (courier plaintext-hold is bounded-by-TTL, not absolute — applies to `OutpostNode` too now), `docs/hardware/makerhawk-v3.md`, `docs/radio-dev.md` (new M6 section with repro steps + honest status).

**Next for other agent:** Corkboard and the Beacon origin-outpost extension (both agreed-on, not started) build on `OutpostNode` existing, which it now does. The hardware flakiness is the open thread — try `outpost_airtest.py` again with more time between runs / different board positioning before assuming it's a code issue; if it keeps failing the same way, worth adding more diagnostic logging around the RNS path-discovery timing specifically.  
**Blocked:** Nothing on the sim work. Hardware round-trip reliability is unresolved, not blocked — just needs patience this session didn't have left to spend.

### 2026-09-23 — Claude (M3 courier hop cap + TTL)

**Re:** Follow-up from an architecture discussion — courier items had no expiry (a courier holds plaintext of messages it isn't a party to, indefinitely) and `handoff_to` had no hop limit.  
**Did:** `courier_queue` gets `hops` and `for_user` columns. `MAX_COURIER_HOPS = 3` caps device-to-device relay in `handoff_to` (a message can still be delivered directly or synced to Station past the cap, it just can't go to a 4th travel device) — Station/Outpost hops are meant to be exempt once Outposts exist (M6), moot for now since only Pocket-to-Pocket exists. `COURIER_TTL_SECONDS` (24h default) + `DispatchStore.purge_expired_courier`, swept opportunistically in `flush_pending`/`handoff_to`/`sync_with_station`. **Also fixed a real bug this surfaced**: `handoff_to`'s `for_user` was re-derived from the DM conversation id using `self.username` as the pivot ("am I party a or b") — works for the originating sender but breaks for any pure courier (not a party to either side), corrupting the conversation on hop 3+ (`ensure_direct("aj","aj")` crash). Now `for_user` is stored on the courier row when first queued/accepted and threaded through unchanged on every further hop. `server/tests/test_mesh_dispatch.py`: 3 new tests (hop cap, TTL expiry via direct store manipulation, opportunistic purge). Full suite 99 passed, 1 skip.  
**Next for other agent:** Nothing blocking. Outpost architecture (routing, scratchpad board, Station-side Outpost board view, per-outpost notice, Outpost↔Station encryption) is now a live discussion in conversation — no code yet, no plan written.  
**Blocked:** Nothing.

### 2026-09-23 — Claude (M4 browser verification, correcting prior note)

**Re:** Human gave this machine's LAN IP (`10.0.0.17`) so the browser tool could reach a dev server started in this sandbox — resolves the "couldn't verify in browser" limitation noted in the M4 slice-1 entry below.  
**Did:** Ran the dev server on `0.0.0.0:8123`, opened it via `10.0.0.17:8123` in the actual browser (not `127.0.0.1`, which the browser tool can't reach — different network namespace from this sandbox). Verified in-browser: `login.html` in `OPEN` mode, register → dashboard, `devices.html` renders in the shell, "Generate pairing code" shows a live countdown, a code redeemed via an unauthenticated request (simulating a Pocket) appears in "My devices", Revoke removes it, and switching the Station to `WAYPOST_REGISTRATION_MODE=INVITE_ONLY` correctly hides "Create account" and shows the invite-only hint. All matches the curl-level verification from the slice-1 commit.  
**Found (pre-existing, not introduced by M4):** `login.html`'s "Display name" `<label>` is visible even in sign-in mode — its `hidden` attribute is overridden by the `.auth-wrap label { display: block; }` rule in the page's inline `<style>` block, which beats the `[hidden]` UA rule. The input itself stays correctly hidden (no such override on `input`), so it's cosmetic only. Confirmed via `git show 7c4992e:web/portal/login.html` that this predates M4 — not fixed here to keep this note purely about verification, but worth a one-line fix (`display: none` guard, or move the rule to a `:not([hidden])` selector) next time someone's in that file.  
**Next for other agent:** Nothing blocking — M4 slice 1 is now fully verified end-to-end, not just at the API level.  
**Blocked:** Nothing.

### 2026-09-23 — Claude (M4 slice 1: pairing codes + device revocation)

**Re:** "Start on M4" — the identity-depth milestone the refreshed priority review flagged as the only hardware-free item left in the priority spine.  
**Did:** Scoped M4 down to a small vertical slice rather than half-building everything: **pairing codes** (`server/services/auth/pairing.py` — `POST /api/auth/pairing/create` authenticated, `POST /api/auth/pairing/redeem` deliberately unauthenticated since a radio-only device has no session; also Waylink `PAIR_REDEEM` under `SVC_PROFILE`, which was reserved in protocol.md but had zero handlers until now) — both reuse the existing `DispatchService.bind_device`, no new bind logic. **Per-device revocation**: `DispatchStore.unbind_device` already existed but nothing called it — added `DispatchService.unbind_device` (ownership-checked) + `GET /api/dispatch/devices` + `POST /api/dispatch/devices/unbind-one`, sibling of the existing wipe-everything `unbind_user`/`/unbind`. **Registration modes honest in the UI**: `GET /api/auth/registration_mode` + `login.html` now hides "Create account" for `INVITE_ONLY` and disables it with an explanation for `ADMIN_APPROVAL`, instead of always showing it regardless of mode. New portal page `devices.html` (pairing-code generator + device list/revoke), added to `shell.js`'s nav. 9 new tests (`test_pairing.py`); full suite 96 passed, 1 skip. Verified the whole flow end-to-end via curl against a live dev server (register → create code → redeem with no cookies → appears in device list → revoke → gone) — **could not get browser-based visual verification working**: the claude-in-chrome extension's browser can't reach the sandbox's `127.0.0.1` (different network namespace from the Bash tool), so screenshots aren't possible for this kind of change in this environment. Worth a human eyeballing `devices.html` once it's convenient.  
**Deliberately deferred, not silently dropped:** `ADMIN_APPROVAL` registration mode and any admin-role concept — the `users` table has no `approved_at`/`is_admin` column, there's no admin-only route anywhere, and there's no first-admin bootstrap decision made. This is real scope (pending-user state, who becomes admin, an approval UI), not a quick add-on to this slice. Also deferred: the Stalwart integration-vs-explicit-cutover decision from ADR 0003 — nothing here depends on it.  
**Next for other agent:** M4 slice 2 (`ADMIN_APPROVAL` + admin role) if that's next, or M1b/M2e-on-Pi/M3-on-hardware once the SD card/T-Deck arrive.  
**Blocked:** Nothing on this slice — pure software, no hardware needed.

### 2026-09-23 — Claude (docs refresh)

**Re:** "Update all docs now, strong documentation is super important."  
**Did:** Full doc sweep against current reality (M2e ✅ over real LoRa, M3 sim exit criteria met with multi-hop/authz/failover, M1b prepped-but-uncommitted). Rewrote `docs/priority-review.md` (was dated 2026-09-18, said `ReticulumTransport` was a stub and `MSG_SYNC`/courier were unimplemented — both now done in sim/hardware; added a fresh Tier list and a new recommended-next-milestone section pointing at **M4** as the only hardware-free item left in the priority spine). Fixed a stale "Stub" line and "dev users only" identity line in `docs/roadmap.md`'s gap table. Cross-linked `docs/hardware/heltec-wifi-lora-32.md` ↔ `docs/hardware/usb-rnode.md` (these boards now double as the RNode hardware — wasn't documented on either page). Small accuracy fix in `docs/architecture.md`'s transport dev-note + a pointer to `PeerDispatchNode` from the Pocket↔Pocket design section. Added `pi-setup.md` to README's doc list. Everything else (`protocol.md`, `security.md`, `offline-sync.md`, `deployment.md`, `network-time.md`, `radio-dev.md`, `pi-setup.md`, identity/groups/provisioning/federation design docs, ADRs, naming/brand) checked and already current — left alone. 86 passed, 1 skip, unchanged (docs-only).  
**Flagged, not decided:** `priority-review.md` §3/§12 now explicitly calls out that the roadmap's app-catalog freeze ("no Atlas/Workshop/new portal apps until network depth advances") was written pre-M2e/M3 and Tier 1 has since exited — worth a human call on whether to revisit it.  
**Next for other agent:** Commit the pending M1b work (still uncommitted — installer, Caddy config, trust page, systemd units, `pi-setup.md`) plus these doc changes. Otherwise M4 (identity depth) is the next hardware-free milestone per the refreshed priority review, or M1b/M2e-on-Pi/M3-on-hardware once the SD card/T-Deck arrive.  
**Blocked:** Nothing on this pass — docs only.

### 2026-09-22 — Cursor (M1b prep, no Pi yet)

**Re:** Human: SD card + T-Deck in the mail — do what's possible now; chose the Pi slice.  
**Did:** `deploy/raspberry-pi/install.sh` (idempotent; shellcheck clean; two-pass tested in `debian:bookworm` + `debian:trixie` — secrets stable, perms 0640/0600, prod env rejects lab login, HTTPS 200 with CA, HTTP → trust page). Caddyfile: offline local CA, 365d intermediate + 30d leaves (Pi has no RTC), HTTP serves only CA/trust/static. Found Debian's Caddy 2.6 can't set `intermediate_lifetime` → installer uses Caddy's official apt repo and enforces ≥2.8. New `web/portal/trust.html` (per-OS CA install, fingerprint, auto-forward to HTTPS). Session cookie `Secure` behind HTTPS; login page hides lab creds unless development. Sandboxed `waypost-api.service`, `waypost-wlan0.service`, Pi udev rule, hostapd template with generated PSK. Guide: `docs/pi-setup.md`. **86 passed**.  
**Heads-up:** RNode Station on the laptop was restarted (same RNode config, now with `--proxy-headers`).  
**Next:** When the SD card arrives: follow `docs/pi-setup.md` (human flashes SD with Imager; agent can run the rest over SSH). Then T-Deck firmware-base decision (ADR 0001).  
**Blocked:** Pi SD card; T-Deck.

### 2026-09-22 — Cursor (M2e over-air ✅)

**Re:** Human plugged in both boards and asked the agent to flash them.  
**Did:** `rnodeconf /dev/ttyUSBx --autoinstall` on both Heltec V3 boards (answers `8`, Enter, `3` = 915 MHz, `y`; no button presses needed). RNode firmware 1.86, signatures validated. Stopped a 4-day-old TCP-lab Station on :8000 and started Station with `WAYPOST_RNS_INTERFACE=rnode` on ttyUSB0. `dispatch_rns_airtest --rnode /dev/ttyUSB1` → **PASS** (send, portal history, `MSG_PUSH` reply) in ~13 s. Signal reports `encrypted (Reticulum)` + RNode settings. Roadmap: M2e ✅.  
**Heads-up:** Station is left running on the RNode config (background uvicorn on :8000). Plaintext Heltec `serial` lab needs a PlatformIO reflash to come back.  
**Next:** M1b Pi (Wi‑Fi TLS) when the human shares SSH; T-Deck Pocket firmware (M7) so M3 can run on hardware.  
**Blocked:** Pi SSH; T-Deck.

### 2026-09-22 — Cursor (M2e RNode software)

**Re:** "Yes" — M2e software polish.  
**Did:** `RNodeRadio` (validated freq/bw/txpower/SF/CR, env `WAYPOST_RNS_*`) + `WAYPOST_RNS_INTERFACE=rnode` writes an `RNodeInterface` config. `dispatch_rns_airtest --rnode /dev/ttyUSBx` for over-air runs. Signal reports `security` / `rns_interface` / `rnode` and the portal colours plaintext Heltec as a warning. Runbook in `docs/radio-dev.md`. **84 passed**.  
**Key finding:** Heltec LoRa32 V3 (our lab boards) is on the official RNode firmware list — M2e over-air may **not** need new hardware. Flashing replaces the Waypost Heltec bridge firmware (reversible with PlatformIO), so it waits on the human.  
**Next:** Human flashes boards (or OKs an agent to) → run the airtest over LoRa. Otherwise M1b when Pi is online.  
**Blocked:** Physical access to boards / Pi.

### 2026-09-22 — Cursor (failover)

**Re:** "Keep going" — last open M3 sim item.  
**Did:** Fixed two Dispatch gaps found while writing the Wi‑Fi↔LoRa failover test: (1) pushes to *bound* devices were memory-only and marked `DELIVERED` on enqueue — now every recipient gets a SQLite pending row until a device confirms, and state is `SENT` meanwhile; (2) confirming on one path (e.g. LoRa) now prunes the stale copy queued for the user's other devices (e.g. Wi‑Fi outbox). A Pocket's `MSG_PUSH` reply now counts as its delivery ACK (registered on gateway); gateway no longer answers unhandled *responses* (avoids error ping-pong). New tests: `test_wifi_to_lora_failover_same_conversation`, `test_pending_survives_restart_and_fails_over_to_lora`. **75 passed**.  
**Next for other agent:** M2e software polish (RNodeInterface config stub + docs, Signal UI shows encrypted/RNS hash), or M1b/M2e once Pi/RNode arrive.  
**Blocked:** Pi / T-Deck / RNode still out of band.

Newest first. Format:

```text
### YYYY-MM-DD HH:MM TZ — <Cursor|Claude|Human>
**Re:** …
**Did:** …
**Next for other agent:** …
**Blocked:** …
```

### 2026-09-22 — Cursor

**Re:** Next unblocked slice without Pi/T-Deck — M3 multi-hop + MSG_SYNC authz.  
**Did:** Pushed Claude’s peer/`MSG_SYNC` commit. Added 1-hop-only peer push, `handoff_to` multi-hop courier (aj→bob→carol), MSG_SYNC requires bound device matching username. **73 passed**.  
**Next for other agent:** Wi‑Fi↔LoRa failover test (sim), or M2e software polish / RNode when hardware arrives.  
**Blocked:** Pi / T-Deck / RNode still out of band.

### 2026-09-20 — Cursor

**Re:** Review Claude's uncommitted M3 sim work since private-repo handoff.  
**Did:** Read handoff + diff; ran full pytest (**71 passed**, 1 skip). Verdict: solid M3 sim slice — keep. Notes for next: MSG_SYNC is still unauthenticated (any radio peer can claim a username and drain pending — acceptable for sim, needs bind/authz before hardware); work is **local only** (not committed/pushed to origin).  
**Next for other agent / human:** Commit + push Claude's M3 changes when ready. Then either multi-hop M3 continuation, or M1b/M2e when Pi/RNode arrive.  
**Blocked:** Nothing on the review itself.

### 2026-09-18 — Claude

**Re:** M2e/M1b both blocked (RNode hardware; Pi SSH access) — human asked to work on something unblocked.  
**Did:** M3 sim slice per `docs/roadmap.md` near-term queue / `docs/priority-review.md` Tier 1: `server/services/dispatch/peer.py` (`PeerDispatchNode`) proves Pocket↔Pocket Dispatch delivery with **no Station in the mesh**, plus `MSG_SYNC` carry-forward to Station (dedup by `mid`, Station's own pending queue for that user piggybacks back inline in the same round trip — see `_rpc_sync` in `server/services/dispatch/service.py`). New `courier_queue` table on `DispatchStore`. 4 new tests in `server/tests/test_mesh_dispatch.py`; full suite green (71 passed, 1 pre-existing skip). Updated `docs/roadmap.md` (M3 🟡), `docs/offline-sync.md`, `README.md` to match. Plan file: `~/.claude/plans/wobbly-stargazing-adleman.md`.  
**Next for other agent:** M3 continuation — multi-hop courier (beyond one hop), a dedicated Wi‑Fi↔LoRa failover test, and eventually wiring a real Pocket to `PeerDispatchNode` once T-Deck firmware exists (M7). Not urgent: M2e RNode and M1b Pi still top of queue once hardware/human input arrives.  
**Blocked:** Nothing on this slice — it's sim-only by design (see roadmap M3 scoping).

---

### 2026-09-18 — Cursor

**Re:** Create shared handoff + private GitHub  
**Did:** Added this file; private GitHub repo setup for Waypost.  
**Next for Claude:** Read this file + `docs/roadmap.md` before any task. Introduce yourself here when you start. Pi work waits until human shares SSH details out of band.  
**Blocked:** Pi IP/user/pass not in repo (by design). RNode hardware for finishing M2e.

---

## Checklist when user gives a new direction

- [ ] Read this handoff + relevant roadmap section  
- [ ] Note the new direction in the message board  
- [ ] Update Active work slots (claim a slot)  
- [ ] Do the work  
- [ ] Update snapshot / roadmap status if milestone moved  
- [ ] Leave a clear “Next for other agent” note  
