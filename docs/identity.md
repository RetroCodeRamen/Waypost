# Identity and presence

**Status:** ADR [0003](adr/0003-identity.md) · **N2 ✅** username/password on Station (local stand-in before Stalwart) · **M4 (slice 1) ✅** pairing codes + per-device revocation.

**M4 scope note:** this slice deliberately shipped pairing codes and per-device
revocation only — see `docs/roadmap.md`'s M4 section for what's still open
(`ADMIN_APPROVAL` needs an admin-role concept that doesn't exist anywhere in
the codebase yet; the Stalwart integration-vs-cutover decision is still
undecided). Both are flagged there rather than half-built here.

---

## Account model (required)

Every person who uses Waypost has **one account**:

1. **Register / sign in on the Station** (portal or Waygate) with **username + password**.  
2. **Same username + password** signs into **Waypost Pocket** (over Station Wi‑Fi HTTP/HTTPS).  
3. Pocket **radio identity** stays separate; after account login, the Pocket **pairs/binds** its radio node to that account via a short-lived, single-use **pairing code** (`POST /api/auth/pairing/create` while signed in on the portal; `POST /api/auth/pairing/redeem` or the Waylink `PAIR_REDEEM` op — no session needed to redeem, since a radio-only device has none). Passwords are **never** sent over LoRa; the pairing code is deliberately the thing that can cross an unencrypted or radio-only path instead.

Registration modes (Station setting): `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`.

---

## Rollcall / presence

Rollcall answers: **who exists, and who can I reach?**

- Username + display name + profile  
- **Account ≠ radio/device identity**  
- Linked Pockets with **revocation** — `GET /api/dispatch/devices` lists your own bindings, `POST /api/dispatch/devices/unbind-one` revokes exactly one (portal: [devices.html](../web/portal/devices.html))  
- Last seen; reachability: Wi‑Fi / LoRa / both / unknown  

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
| Disabled user | Reject API and radio-authenticated app ops (needs the `ADMIN_APPROVAL`/admin-role work below — no `disabled` flag exists yet) |

## Open questions

- Guest browse on Waygate before login? (likely: Waygate splash → register/login only)  
- Password reset without Internet (admin unlock)?  
- Cryptographic device identity format before Reticulum destinations exist?
- Pairing-code rate limiting — short TTL + single-use bounds guessing today, but no explicit rate limit on `/api/auth/pairing/redeem` yet ([security.md](security.md) still lists this as a general gap, not M4-specific)

## Deferred

- Full OIDC / Stalwart cutover  
- **`ADMIN_APPROVAL` registration mode** — needs a `users.approved_at` column, a first-admin bootstrap, and an approval UI; none of that exists yet. `OPEN`/`INVITE_ONLY` are honest end-to-end (server + portal UI); `ADMIN_APPROVAL` correctly refuses to pretend it works ([roadmap.md](roadmap.md) M4)  
- Cross-Station identity ([federation-future.md](federation-future.md))  
- Password over LoRa (forbidden by design)
