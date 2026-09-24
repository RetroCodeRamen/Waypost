# Waypost security model

## Threat assumptions

- LoRa traffic can be overheard by strangers.  
- Wi-Fi may be joined by untrusted devices until Waygate/auth policies apply.  
- The Station may be physically accessible.  
- Power loss and abrupt reboot are normal.  
- Internet may be absent; ACME public certs are not assumed.

Never rely on obscurity. Do not invent cryptographic primitives — use Reticulum (and standard TLS/OIDC) where applicable.

---

## Trust boundaries

| Boundary | Trust |
|----------|--------|
| Pocket ↔ Waylink peers | Authenticated by transport crypto when Reticulum is used; app auth still required |
| Pocket ↔ Station Wi-Fi API | HTTPS (local CA) + session/OIDC |
| Browser ↔ Station | Same; Waygate bootstrap may start on HTTP then steer to trusted HTTPS |
| Adapter ↔ FOSS backends | Local network; prefer mTLS or shared secrets on loopback/compose network |
| Outpost nodes | Forwarding infrastructure; must not hold user passwords or private mail — in practice this means **bounded transient hold, not "never touches plaintext"**: `OutpostNode` (like a Pocket-as-courier) necessarily stores a plaintext copy of whatever it's relaying until delivery or `COURIER_TTL_SECONDS` expiry (`DispatchStore.purge_expired_courier`, default 24h), same as any store-and-forward node has to. Never send passwords this way (see below) — only message bodies pass through the courier path, and only for as long as the TTL allows |

Receiving a valid radio packet does **not** authorize:

- reading another user’s Postbox  
- private Dispatch threads  
- Fieldbook edits without permission  
- Station admin  
- editing another profile  
- private Locker files
- **posting, expiring, or acknowledging a Noticeboard notice, or pushing/clearing a Beacon, as anyone other than the packet's own bound device** — `NOTICE_CREATE`/`EXPIRE`/`ACK` and `BEACON_PUSH`/`CLEAR` all resolve the acting username from `device_bindings`, same mechanism `MSG_SYNC` authz already used for Dispatch (found and fixed 2026-09-23 — both previously trusted a self-reported `author` field in the payload, which for Beacon specifically meant anyone with a working radio could push or silence an emergency alert as anyone)

---

## Identity and devices

- One Waypost account: **username + password** (OIDC later via Stalwart).  
- Same credentials for **Station portal** and **Pocket** (Pocket authenticates over Wi‑Fi/HTTPS to Station — never send passwords over LoRa).  
- Pocket radio identity is separate; linked via bind / pairing codes with revocation. **M4 ✅:** a signed-in user generates a 6-digit, 10-minute, single-use pairing code (`POST /api/auth/pairing/create`); a device redeems it (`POST /api/auth/pairing/redeem` or Waylink `PAIR_REDEEM`) with **no session and no password** — the code itself is the bounded-lifetime credential that's safe to send over an untrusted or radio-only path.  
- **M6 ✅:** the same pairing codes now also authorize claiming Outpost infrastructure (`OUTPOST_CLAIM`, `server/services/auth/pairing.py`) — a human generates a code on Station, enters it on the Outpost's own Wi-Fi page, and the code is what proves intent before Station will `learn_route()` and start trusting that node's self-reported destination hash. Same trust model as device pairing (a human-provided code, not raw self-assertion), different redemption target (infrastructure has no username).  
- Lost Pocket: `POST /api/dispatch/devices/unbind-one` revokes exactly that device (sibling devices keep working) — see [identity.md](identity.md).  
- **M4 ✅:** `ADMIN_APPROVAL` registration mode actually gates login now — a pending account (`approved_at IS NULL`) is created but issued no session, and `POST /api/auth/login` rejects it until an admin approves (`POST /api/auth/approve`, portal `/control.html`). The first account ever registered on a Station bootstraps as admin, auto-approved, so the mode can't deadlock a fresh Station.

---

## Encryption requirements

| Path | Requirement | Status |
|------|-------------|--------|
| Browser / Pocket ↔ Station (Wi‑Fi) | **TLS** (Waypost local CA or equivalent) | Caddy offline local CA + trust page, proven on laptop and in Debian containers; plain HTTP only serves the CA/trust page. Session cookie `Secure` over HTTPS. Awaiting Pi (M1b). Laptop HTTP OK for lab only |
| Station Wi‑Fi air | **WPA2/WPA3** | hostapd WPA2-PSK/CCMP with a generated per-Station password (Pi onboard Wi‑Fi lacks reliable SAE in AP mode); awaiting Pi (M1b) |
| LoRa via Heltec USB bridge | **Not encrypted** — development stand-in only | Must not be treated as production privacy |
| LoRa production Waylink | **Transport crypto** (Reticulum/LXMF per ADR 0002) | M2e — encrypted Dispatch over LoRa **passed** on RNode-flashed Heltec V3 (2026-09-22). Signal labels plaintext Heltec links as "lab only" |
| Outpost's own radio (standalone firmware) | **Transport crypto**, on-device — no host computer | M6 — Outposts run real Reticulum themselves via [microReticulum](https://github.com/attermann/microReticulum), a reviewed C++ port of the actual protocol (not hand-rolled crypto, not plaintext). Identity/destination hash persists across reboots, hardware-verified 2026-09-23. See `firmware/outpost/README.md` |
| Outposts | Forward ciphertext; must not hold user passwords or private mail plaintext |
| Dispatch / Postbox bodies at rest | Station disk; protect Station physically; backups warn on keys |

**Rule:** Users interact with services, not transports — but **every production hop must provide confidentiality + integrity**. Heltec plaintext CBOR is a lab tool. Before “real camp” radio use: **M2e Reticulum** (or equivalent) or an explicit interim app-layer crypto ADR.

Never invent primitives — use TLS, Argon2/bcrypt-class password hashes, and Reticulum (or reviewed libs).

---

## Offline TLS

Options:

1. Waypost local CA  
2. Generated Station server certificates  
3. Downloadable CA for clients  
4. Documented trust installation on phones/laptops  

Tradeoff: users must install a CA (or accept warnings). Prefer documented CA install over permanent HTTP for authenticated services.

Implemented (`deploy/raspberry-pi/caddy/Caddyfile`): Caddy's internal CA ("Waypost Station Local CA", 10-year root, 365-day intermediate, 30-day leaves for clock-drift tolerance). `http://…/trust.html` offers the CA and its SHA-256 fingerprint for out-of-band comparison, then forwards to HTTPS once trusted. Setup: [pi-setup.md](pi-setup.md).

Wi-Fi: WPA2/WPA3 where hardware permits.

---

## Radio and airtime

- Region-configurable frequency, bandwidth, SF, CR, TX power.  
- No uncontrolled continuous-transmit loops.  
- Beacon and Noticeboard floods: rate limits + TTL + replay protection.  
- Games must not monopolize airtime.

---

## Logging

Structured logs may include message ID, request ID, transport, source, destination, service, operation.

**Never log:** passwords, private keys, full auth tokens, casual private message bodies (debug modes must be careful).

---

## Backups

`waypost-backup` / `waypost-restore` must warn clearly if private keys are included unencrypted.

---

## Application controls

- Registration: `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`  
- Rate limits on auth, mail send, radio RPC  
- Malformed packet limits at gateway  
- Anti-replay for Beacon and sensitive ops  

Details evolve with phases; this document is the authoritative trust model.
