# Identity and presence

**Status:** ADR [0003](adr/0003-identity.md) · **N2 implementing** username/password on Station (local stand-in before Stalwart).

---

## Account model (required)

Every person who uses Waypost has **one account**:

1. **Register / sign in on the Station** (portal or Waygate) with **username + password**.  
2. **Same username + password** signs into **Waypost Pocket** (over Station Wi‑Fi HTTP/HTTPS).  
3. Pocket **radio identity** stays separate; after account login, the Pocket **pairs/binds** its radio node to that account (pairing code or bind API). Passwords are **never** sent over LoRa.

Registration modes (Station setting): `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`.

---

## Rollcall / presence

Rollcall answers: **who exists, and who can I reach?**

- Username + display name + profile  
- **Account ≠ radio/device identity**  
- Linked Pockets with **revocation**  
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
| Lost Pocket | Revoke device binding; password change invalidates sessions (when implemented) |
| Disabled user | Reject API and radio-authenticated app ops |

## Open questions

- Guest browse on Waygate before login? (likely: Waygate splash → register/login only)  
- Password reset without Internet (admin unlock)?  
- Cryptographic device identity format before Reticulum destinations exist?

## Deferred

- Full OIDC / Stalwart cutover  
- Cross-Station identity ([federation-future.md](federation-future.md))  
- Password over LoRa (forbidden by design)
