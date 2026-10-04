# Identity and presence

**Status:** ADR [0003](adr/0003-identity.md) · **N2 ✅** username/password on Station (local stand-in before Stalwart) · **M4 ✅** pairing codes + per-device revocation + `ADMIN_APPROVAL`/admin-role.

**M4 scope note:** the one remaining open item is the Stalwart integration-vs-cutover
decision — a human call, not a build task (see `priority-review.md` §12). Everything
else in M4's original acceptance shape (pairing, revocation, registration-mode UI,
`ADMIN_APPROVAL`) is done.

---

## Account model (required)

Every person who uses Waypost has **one account**:

1. **Register / sign in on the Station** (portal or Waygate) with **username + password**.  
2. **Same username + password** signs into **Waypost Pocket** (over Station Wi‑Fi HTTP/HTTPS).  
3. Pocket **radio identity** stays separate; after account login, the Pocket **pairs/binds** its radio node to that account via a short-lived, single-use **pairing code** (`POST /api/auth/pairing/create` while signed in on the portal; `POST /api/auth/pairing/redeem` or the Waylink `PAIR_REDEEM` op — no session needed to redeem, since a radio-only device has none). Passwords are **never** sent over LoRa; the pairing code is deliberately the thing that can cross an unencrypted or radio-only path instead.

Registration modes (Station setting): `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`.

---

## Offline identity (target)

**Status:** 📋 design, adopted 2026-10-04 ([network-model.md](network-model.md) §7). Extends the
account model above. Nothing here replaces passwords on Station or pairing codes. It adds a way for
**any** node to check who sent something **without asking Station**.

### Four separate things

| | Today | Target |
|---|---|---|
| **Username** (`aj`) | ✅ Station `users` | unchanged; may change without breaking anything |
| **Identity id** | — (username is the key everywhere) | 📋 stable id = hash of the person's identity record, issued once; usernames map to it |
| **Credentials** | ✅ password (Station only), ✅ Scout PIN (UI lock) | password stays on Station; PIN unlocks the device key locally; never sent anywhere |
| **Device identity** | ✅ each Scout/Outpost's Reticulum keypair (Ed25519 + X25519) | unchanged; becomes the *signing* key for that device |

### Certificates (small signed objects, cached everywhere)

```text
community key     Ed25519 keypair created at Station setup; private half stays on Station
                  (+ offline backup); public half handed to every device at pairing/claim.

identity.cert     { identity_id, username, display_name, serial, issued, expires }
                  signed by the community key

device.cert       { device_hash (Reticulum identity hash), identity_id, role: scout|outpost,
                    issued, expires }   signed by the community key

identity.revoke   { serial or device_hash, reason, issued }   signed by the community key
```

Each fits one LoRa packet. Ed25519 signatures are 64 bytes.

**Issuing:** `PAIR_REDEEM` (✅ binds a device today) also returns the identity and device certificates
plus the community public key (🔧 additive). `OUTPOST_CLAIM` and auto-claim (✅) do the same for
Outposts. Station republishes certificates when they near expiry, whenever it syncs with a device.

**Verifying offline (any node):** object signature valid for its device key → device cert signed by
community key, not expired → identity cert likewise → neither revoked (cached list). No round trip.

**Logging in on a Scout:** the device private key is stored encrypted with a key derived from the
PIN (slow KDF, salted). PIN entry decrypts it into RAM; locking wipes it. A Scout with no PIN set keeps
today's behaviour (key unencrypted), clearly labelled. 🔧 today the PIN only guards the UI.

**Station's role:** issues certificates, revokes, recovers (lost Scout → revoke its device cert, pair a
new one; forgotten PIN → re-pair), rotates keys, and keeps the canonical directory. **None of these
are needed for an ordinary login or message.**

**Revocation latency:** a revoked device can still be believed by nodes that haven't synced the
revocation. Bounded by certificate expiry (default 30 days, reissued silently while the device keeps
syncing). Revocations sync at high priority.

**Outposts** cache certificates for everyone (a few hundred bytes per person), so they can deliver to
and accept from people offline. People without a Scout at an Outpost: see
[outpost.md](outpost.md#signing-in-without-a-scout).

**Community key loss/compromise:** Station backup includes the key. Compromise needs a new key and
re-pairing every device. Acceptable for v1, and stated plainly in [security.md](security.md).

### Migration from today

1. Station creates the community key (one-time, on upgrade) and issues certificates for existing
   bindings. Devices pick them up at their next sync.
2. Station accepts **both** signed objects and today's unsigned binding-checked requests for a while.
   Unsigned is refused once every bound device has a certificate.
3. The `is_trusted_courier` exception (claimed Outposts may relay as anyone) goes away: the signature
   proves the sender, so it doesn't matter who carried the object.

---

## Rollcall / presence

Rollcall answers: **who exists, and who can I reach?**

- Username + display name + profile  
- **Account ≠ radio/device identity**  
- Linked Pockets with **revocation** — `GET /api/dispatch/devices` lists your own bindings, `POST /api/dispatch/devices/unbind-one` revokes exactly one (portal: [devices.html](../web/portal/devices.html))  
- Last seen; reachability: Wi‑Fi / LoRa / both / unknown  
- **Nearby** (📋, Scout): built locally from capability announces — Scouts, Outposts, whether
  Station is reachable and through what. Presence is a short-lived `rollcall.presence` object, not
  a Station lookup ([network-model.md](network-model.md) §6).  

---

## Assumptions

- Local SQLite password hashes are the **alpha stand-in**; Stalwart (+ OIDC) remains the production authority (ADR 0003).  
- Migration: export local users into Stalwart without renaming usernames.  
- Sessions: HTTP cookie and/or Bearer token; Pocket stores token in secure local storage.

## Expected behavior

| Action | Result |
|--------|--------|
| Portal register | Creates account (password hashed); starts session |
| Portal login | Session; APIs require auth |
| Pocket login (Wi‑Fi) | Same credentials → token; then device bind |
| Portal pairing-code create | Authenticated only; 6 digits, 10-minute TTL, single use |
| Device pairing-code redeem | **No session required**; binds `node_id` to the code's owner, same flush-on-bind as direct bind |
| Lost Pocket | `POST /api/dispatch/devices/unbind-one` revokes that device only; password change invalidates sessions (when implemented) |
| Registration under `ADMIN_APPROVAL` | Account is created but issued no session; `POST /api/auth/login` rejects until an admin approves (`users.approved_at`) |
| Admin approves a pending user | `POST /api/auth/approve` (admin-only; portal: `/control.html`); the first account ever registered on a Station bootstraps as admin and is auto-approved, so `ADMIN_APPROVAL` can never deadlock a fresh Station with no one able to approve anyone |

## Open questions

- Guest browse on Waygate before login? (likely: Waygate splash → register/login only)  
- Password reset without Internet (admin unlock)?  
- ~~Cryptographic device identity format before Reticulum destinations exist?~~ Answered 2026-10-04: device identity = Reticulum identity; certificates above.
- Certificate lifetime (30 days proposed) and how loudly a Scout warns as expiry nears without a Station sync.
- Whether a person may hold several identities (e.g. a shared camp role account) — v1: no.
- Pairing-code rate limiting — short TTL + single-use bounds guessing today, but no explicit rate limit on `/api/auth/pairing/redeem` yet ([security.md](security.md) still lists this as a general gap, not M4-specific)

## Deferred

- Full OIDC / Stalwart cutover — the one remaining M4 item, a human decision (`priority-review.md` §12)
- Cross-Station identity ([federation-future.md](federation-future.md))  
- Password over LoRa (forbidden by design)
- `ensure_user`-created accounts (device binds, lab seeding) are auto-approved and never gated by `ADMIN_APPROVAL` — they get no password hash either way, so there's nothing for that mode to actually protect there; see `Database.ensure_user`'s docstring-equivalent comment for why this is safe, not a loophole
