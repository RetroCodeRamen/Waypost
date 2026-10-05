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
- **Auto-claim (on by default):** a Station also claims nearby Outposts with no code at all, via `ReticulumTransport`'s registered `RNS.Transport` announce handler (`server/transports/reticulum.py`). This is **not** a weaker version of the code-based trust — it solves a different half of the problem. The code-based flow's real job was never verifying the hash (a self-reported `transport_dest` in a payload can't be trusted on its own either way); it was proving *intent* — that a human actually wanted this claimed. Auto-claim gets the hash a stronger way (Reticulum's own signed announce — the identity that produced it, not a claimed string) and gets intent a different way: the Outpost's own physical PRG/BOOT button toggles whether it advertises itself as claimable at all (default on), and that toggle — not the hash — is what a Station operator should think of as the actual gate. `PairingService.auto_claim_outpost` never overrides an existing claim (walk-up or auto), so it can't be used to steal an already-claimed Outpost. `WAYPOST_AUTO_CLAIM_OUTPOSTS=false` turns this off Station-wide if that trust trade-off isn't wanted. Not designed for: two Stations both in range of the same unclaimed Outpost (first one to hear it wins, no arbitration) — see [federation-future.md](federation-future.md), which already treats multi-Station topology as unbuilt.  
- Lost Pocket: `POST /api/dispatch/devices/unbind-one` revokes exactly that device (sibling devices keep working) — see [identity.md](identity.md).  
- **Scout (T-Deck) physical access:** an optional **PIN lock** (4–8 digits, salted SHA-256 in flash) locks the Scout at boot and after 5 minutes idle; wrong tries back off (30 s after 5, doubling — reset by a reboot). There is no bypass: a forgotten PIN means RESET, which unpairs the Scout (it needs a new pairing code from the account owner). The PIN guards the **UI only** — flash isn't encrypted, so the Reticulum identity and cached account can be read off the chip. The USB serial port accepts remote keystrokes (`Ctrl-]` + key) through the same lock; compile it out of field builds with `-DWAYPOST_USB_REMOTE=0`. A Scout learns its account from Station (`PAIR_REDEEM`/`WHOAMI`), never from what's typed on it; Settings → Unpair also revokes the binding on Station (`PROFILE/UNPAIR`). Revoke a lost Scout from the portal with `unbind-one`.  
- **Who sent a Dispatch message:** Station uses the sending device's binding, not the payload (see protocol.md). Claimed Outposts may relay others' messages with the author in the payload — they're trusted relay infrastructure; end-to-end signatures are planned with Scout-to-Scout messaging.  
- **Offline-verifiable identity (built 2026-10-04, D2; details in identity.md):** a Station-held **community key** signs identity and device certificates; every synced object is signed by its author's device; any node verifies offline and checks a synced revocation list ([identity.md](identity.md#offline-identity-target)). Trade-offs to keep in view: (1) a revoked device is believed by nodes that haven't synced the revocation, bounded by certificate expiry; (2) the community key is the root of trust — it is in Station backups, and losing control of it means re-pairing every device; (3) an Outpost that verifies an *Outpost passcode* offline holds hashes that can be guessed offline if the device is stolen — opt-in, separate from the account password, slow KDF ([outpost.md](outpost.md#signing-in-without-a-scout)); (4) relays can read what they carry (decided 2026-10-04), but signatures stop them altering or forging it. Once signatures are in place, the `is_trusted_courier` exception goes away.  
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

- **Trailhead:** reads are open to anyone on Waylink or the portal (community pages, same posture as Fieldbook reads) — don't put private information there. Writes are portal-only and need a signed-in user.  
- **Lab mode:** `WAYPOST_AUTH_REQUIRED=false` lets the HTTP API act for any claimed username (used for the dev `aj`/`bob` accounts, which have no passwords). Development only; never on a real Station.  

- Registration: `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`  
- Rate limits on auth, mail send, radio RPC  
- Malformed packet limits at gateway  
- Anti-replay for Beacon and sensitive ops  

Details evolve with phases; this document is the authoritative trust model.
