# Identity and presence

**Status:** ADR [0003](adr/0003-identity.md) · **N2 ✅** username/password on Station (local stand-in before Stalwart) · **M4 ✅** pairing codes + per-device revocation + `ADMIN_APPROVAL`/admin-role.

**M4 scope note:** the one remaining open item is the Stalwart integration-vs-cutover
decision — a human call, not a build task (see `priority-review.md` §12). Everything
else in M4's original acceptance shape (pairing, revocation, registration-mode UI,
`ADMIN_APPROVAL`) is done.

---

## Account model (required)

Every person who uses Waypost has **one account**: a **username + password**. Since 2026-10-05 the
pair is also their **identity**: a key derived from username + password, the same on every device.

1. **Register / sign in on the Station** portal with username + password (**10+ characters**).
   Station records the person's identity key whenever it sees the password (registration,
   portal sign-in) and vouches for it.
2. **Scout:** sign in on the device with the same username + password. The Scout works out the key
   (~4–5 s), proves it to Station by signing a one-time challenge (`PROFILE/LOGIN_NONCE`, `LOGIN`),
   and is bound to the account. No pairing code; the password never crosses the radio. With
   Station out of reach the person can still sign in — the key needs only the password — and the
   Scout finishes with Station later. The PIN keeps the derived key sealed between sessions.
3. **Outpost Wi-Fi page** (`http://out.post/msg`): sign in with the same username + password; the
   browser works out the key, so the password never reaches the Outpost. One session per browser —
   several people can be signed in on one Outpost.

Pairing codes (`PAIR_REDEEM`) still work and still claim Outposts; Scouts no longer use them.

Registration modes (Station setting): `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`.

---

## Offline identity (target)

**Status:** ✅ **built 2026-10-05**, on Station, Scout and Outpost (roadmap D2, reworked the same
day to the human's design: identity = username + password). Verified on hardware: Scout and
Outpost self-tests match Python byte for byte; a phone page's crypto (run under Node) matches
Python's pinned vectors; signed messages moved Outpost → Scout and Scout → Station over LoRa.
Code: `server/services/identity/{keys,certs,objects,service}.py`, `firmware/common/waypost_core`,
`firmware/pocket/src/{kdf,certs}.*`, `firmware/outpost/web/wpcrypto.js`. Ops in
[protocol.md](protocol.md#offline-identity-profile-cert-ops-2026-10-04).

### The key

```text
seed = scrypt(password, salt = "waypost-identity-v1\n" + lower(username), N=4096, r=8, p=4, 32 bytes)
key  = Ed25519 key from that seed
id   = SHA-256(public key)[:16]
```

The same username + password give the same key on any device. **A different password is a
different identity**, so reusing someone's username can't intercept their friends' messages:
Station vouches for one key per username, and devices check messages against it. Measured cost:
~4.4 s on a Scout (4 MiB of PSRAM), ~150 ms in Node, 25 ms in Python.

**Honest costs** (told to the human when they chose this):
- Anyone holding one of a person's signed messages can try password guesses offline against their
  public key. That's why scrypt (slow, memory-hard) and a 10-character minimum for new accounts.
  Accounts older than the rule keep their passwords until changed — they're weaker.
- **A new password is a new identity.** Station records the new key and revokes the old one;
  messages signed with the old key are refused once a device has the revocation.
- Station only learns a person's key when it sees their password. Accounts from before 2026-10-05
  need **one portal sign-in** before a Scout login works (`no_identity_yet`).

### Separate things

| | What |
|---|---|
| **Username** | human-readable, on Station |
| **Identity key / id** | derived from username + password; signs the person's messages |
| **Password** | Station keeps a PBKDF2 hash for portal sign-in; never sent over the radio, never to an Outpost |
| **Scout PIN** | local only: seals the derived key on the Scout between unlocks |
| **Network identity** | each device's Reticulum keypair: addressing, encryption, forwarding. Never sealed, so a locked Scout still receives |

### Certificates

Signed by Station's **community key** (Ed25519, `community.key` in Station's data directory, created
on first start, mode 0600 — back it up with the data):

```text
id    { n serial, i identity id, u username, dn display name (≤40 bytes), p identity public key, t, x }
rev   { n, r serial revoked, t }
```

Canonical signed bytes (`WAYPOST-CERT-1\n` + `name:len:value`), pinned vectors checked by pytest, the
Scout and the Outpost at boot. 30-day lifetime, renewed in the last 7. Devices pin the community key
the first time they hear it and never replace it silently.

**Who caches what:** a Scout keeps its own person's certificate, its contacts', and anyone whose
message arrives (looked up by identity id, `CERT_GET {i}`). An Outpost caches everyone's
(`CERT_LIST`, claimed Outposts only), since it checks everyone's messages.

**Verifying offline (any node):** message signature valid for the key in the author's `id`
certificate, signed by the community key, unexpired, not revoked. No round trip.

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
- Certificate lifetime (30 days) and how loudly a Scout warns as expiry nears without a Station sync.
- Password change: there is no portal "change password" yet; when there is, it must record the new key (new identity) and revoke the old.
- Linking an old identity to the new one after a password change, so friends' devices follow along without Station.
- Whether a person may hold several identities (e.g. a shared camp role account) — v1: no.
- Pairing-code rate limiting — short TTL + single-use bounds guessing today, but no explicit rate limit on `/api/auth/pairing/redeem` yet ([security.md](security.md) still lists this as a general gap, not M4-specific)

## Deferred

- Full OIDC / Stalwart cutover — the one remaining M4 item, a human decision (`priority-review.md` §12)
- Cross-Station identity ([federation-future.md](federation-future.md))  
- Password over LoRa (forbidden by design)
- `ensure_user`-created accounts (device binds, lab seeding) are auto-approved and never gated by `ADMIN_APPROVAL` — they get no password hash either way, so there's nothing for that mode to actually protect there; see `Database.ensure_user`'s docstring-equivalent comment for why this is safe, not a loophole
