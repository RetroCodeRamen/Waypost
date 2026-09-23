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
| Outpost nodes | Forwarding infrastructure; must not hold user passwords or private mail |

Receiving a valid radio packet does **not** authorize:

- reading another user’s Postbox  
- private Dispatch threads  
- Fieldbook edits without permission  
- Station admin  
- editing another profile  
- private Locker files  

---

## Identity and devices

- One Waypost account: **username + password** (OIDC later via Stalwart).  
- Same credentials for **Station portal** and **Pocket** (Pocket authenticates over Wi‑Fi/HTTPS to Station — never send passwords over LoRa).  
- Pocket radio identity is separate; linked via bind / pairing codes with revocation. **M4 ✅:** a signed-in user generates a 6-digit, 10-minute, single-use pairing code (`POST /api/auth/pairing/create`); a device redeems it (`POST /api/auth/pairing/redeem` or Waylink `PAIR_REDEEM`) with **no session and no password** — the code itself is the bounded-lifetime credential that's safe to send over an untrusted or radio-only path.  
- Lost Pocket: `POST /api/dispatch/devices/unbind-one` revokes exactly that device (sibling devices keep working) — see [identity.md](identity.md).  
- Disabled users: reject API and radio-authenticated app ops — **not implemented yet**; needs the `ADMIN_APPROVAL`/admin-role work noted in `identity.md`'s Deferred section.

---

## Encryption requirements

| Path | Requirement | Status |
|------|-------------|--------|
| Browser / Pocket ↔ Station (Wi‑Fi) | **TLS** (Waypost local CA or equivalent) | Caddy offline local CA + trust page, proven on laptop and in Debian containers; plain HTTP only serves the CA/trust page. Session cookie `Secure` over HTTPS. Awaiting Pi (M1b). Laptop HTTP OK for lab only |
| Station Wi‑Fi air | **WPA2/WPA3** | hostapd WPA2-PSK/CCMP with a generated per-Station password (Pi onboard Wi‑Fi lacks reliable SAE in AP mode); awaiting Pi (M1b) |
| LoRa via Heltec USB bridge | **Not encrypted** — development stand-in only | Must not be treated as production privacy |
| LoRa production Waylink | **Transport crypto** (Reticulum/LXMF per ADR 0002) | M2e — encrypted Dispatch over LoRa **passed** on RNode-flashed Heltec V3 (2026-09-22). Signal labels plaintext Heltec links as "lab only" |
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
