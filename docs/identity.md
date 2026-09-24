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
| Registration under `ADMIN_APPROVAL` | Account is created but issued no session; `POST /api/auth/login` rejects until an admin approves (`users.approved_at`) |
| Admin approves a pending user | `POST /api/auth/approve` (admin-only; portal: `/control.html`); the first account ever registered on a Station bootstraps as admin and is auto-approved, so `ADMIN_APPROVAL` can never deadlock a fresh Station with no one able to approve anyone |

## Open questions

- Guest browse on Waygate before login? (likely: Waygate splash → register/login only)  
- Password reset without Internet (admin unlock)?  
- Cryptographic device identity format before Reticulum destinations exist?
- Pairing-code rate limiting — short TTL + single-use bounds guessing today, but no explicit rate limit on `/api/auth/pairing/redeem` yet ([security.md](security.md) still lists this as a general gap, not M4-specific)

## Deferred

- Full OIDC / Stalwart cutover — the one remaining M4 item, a human decision (`priority-review.md` §12)
- Cross-Station identity ([federation-future.md](federation-future.md))  
- Password over LoRa (forbidden by design)
- `ensure_user`-created accounts (device binds, lab seeding) are auto-approved and never gated by `ADMIN_APPROVAL` — they get no password hash either way, so there's nothing for that mode to actually protect there; see `Database.ensure_user`'s docstring-equivalent comment for why this is safe, not a loophole
