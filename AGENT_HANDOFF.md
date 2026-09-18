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

**Date:** 2026-09-18  

**Active milestone:** **M2e** Production radio crypto 🟡 (Dispatch-over-RNS TCP lab ✅; RNode LoRa still open)  
**Just finished:** **N2** username/password auth ✅  

**Have today**

- Laptop Station API + SQLite + portal (auth-gated)
- N2: register/login, PBKDF2 hashes, session cookie + Bearer; lab users `aj`/`bob` password `waypost1` (lab only)
- N1 opportunistic Dispatch; Heltec M2c air path (plaintext stand-in)
- M2e: `ReticulumTransport`, `dispatch_rns_airtest` PASS on encrypted TCP lab; bind `transport_dest` for `rns-*` pushes
- Deploy templates under `deploy/raspberry-pi/` — **not validated on hardware**

**Don’t have yet**

- Pi AP product path (M1b): hostapd + dnsmasq + Waygate + Caddy on real Pi
- RNode production LoRa interface (finish M2e)
- Pocket/Outpost firmware; mesh without Station (M3)
- Stalwart/OIDC (M4)

**Freezes:** no new portal apps; no Atlas; no Workshop until network depth advances.

**Human direction (Pi):** Prefer Raspberry Pi OS Lite 64-bit + SSH first (not image-first). Human will provide IP / user / password out of band when ready. Then validate M1b; bake an image later.

---

## Active work / handoff slots

Fill these when you start or finish work so the other agent doesn’t collide.

| Slot | Agent | Status | Branch / notes |
|------|-------|--------|----------------|
| M2e RNode LoRa | — | open | After TCP lab; needs hardware |
| M1b Pi stack | — | waiting on human | SSH install once Pi is online |
| — | — | — | — |

**Cursor last session:** N2 auth hardened (all private APIs); M2e Dispatch-over-RNS; Station may be on `WAYPOST_TRANSPORT=reticulum` locally.  
**Claude last session:** _(none yet — introduce yourself in the message board)_

---

## Environment cheat sheet (lab)

```bash
# Laptop Station (Heltec plaintext lab)
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

Newest first. Format:

```text
### YYYY-MM-DD HH:MM TZ — <Cursor|Claude|Human>
**Re:** …
**Did:** …
**Next for other agent:** …
**Blocked:** …
```

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
