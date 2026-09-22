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

**Date:** 2026-09-22  

**Active milestone:** none unblocked in software — **M1b** Pi waits on SSH; **M3** hardware waits on Pocket firmware  
**Just finished:** **M2e ✅** — encrypted Dispatch over real LoRa (both Heltec V3 boards now run RNode firmware)

**Have today**

- Laptop Station API + SQLite + portal (auth-gated)
- N2: register/login, PBKDF2 hashes, session cookie + Bearer; lab users `aj`/`bob` password `waypost1` (lab only)
- N1 opportunistic Dispatch; Heltec M2c air path (plaintext stand-in — **boards no longer carry that firmware**, see below)
- M2e ✅: `ReticulumTransport`; `dispatch_rns_airtest` PASS on TCP lab **and over LoRa** (`--rnode`, 915 MHz, SF8/125 kHz); bind `transport_dest` for `rns-*` pushes; Signal shows security + RNode settings
- **Hardware state:** `/dev/ttyUSB0` and `/dev/ttyUSB1` (Heltec V3, CP2102) flashed with RNode firmware 1.86 on 2026-09-22. `WAYPOST_TRANSPORT=serial` (Heltec plaintext) will not work until `firmware/heltec` is reflashed
- M3 (sim): `PeerDispatchNode` — peer↔peer, `MSG_SYNC` (+ authz), **multi-hop** `handoff_to` (aj→bob→carol), **Wi‑Fi↔LoRa failover**; `test_mesh_dispatch.py`
- Dispatch pending is durable for every recipient until a device confirms (outbox poll, `MSG_ACK`, `MSG_PUSH` reply, or `MSG_SYNC`); state is `SENT` until then, not `DELIVERED`
- Deploy templates under `deploy/raspberry-pi/` — **not validated on hardware**

**Don’t have yet**

- Pi AP product path (M1b): hostapd + dnsmasq + Waygate + Caddy on real Pi
- Wi‑Fi TLS (M1b) — the remaining gap for "all communications encrypted"
- Pocket/Outpost firmware (M6/M7); M3 on real hardware
- Stalwart/OIDC (M4)

**Freezes:** no new portal apps; no Atlas; no Workshop until network depth advances.

**Human direction (Pi):** Prefer Raspberry Pi OS Lite 64-bit + SSH first (not image-first). Human will provide IP / user / password out of band when ready. Then validate M1b; bake an image later.

---

## Active work / handoff slots

Fill these when you start or finish work so the other agent doesn’t collide.

| Slot | Agent | Status | Branch / notes |
|------|-------|--------|----------------|
| M2e RNode LoRa | Cursor | **done** | Over-air PASS 2026-09-22 |
| M1b Pi stack | — | waiting on human | SSH install once Pi is online |
| M3 peer + multi-hop + failover sim | Cursor | done | Sim exit criteria met; hardware waits on M6/M7 |

**Cursor last session:** Flashed both boards as RNodes, M2e over-air PASS; prior: M3 failover + durable pending.  
**Claude last session:** M3 sim slice — peer-to-peer Dispatch + `MSG_SYNC` carry-forward (see message board).

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
