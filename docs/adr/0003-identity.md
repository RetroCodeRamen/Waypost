# ADR 0003 — Identity and SSO

## Status

Accepted (local username/password **N2** now; Stalwart/OIDC remains production target)

## Context

Users need one account across Postbox, Fieldbook, Commons, portal, and Pocket. Multiple unrelated passwords would fail the product goal. Alpha Station currently had **no passwords** — that is unacceptable for anything beyond a single-operator laptop demo.

## Decision

### Now (N2)

- Station stores **username + password hash** (PBKDF2-HMAC-SHA256 or better) in SQLite.  
- Portal: register + login → HTTP session / Bearer token.  
- Pocket: **same username + password** against Station over Wi‑Fi (`/api/auth/login`); then bind radio identity.  
- **Never** transmit passwords over LoRa.

### Later (production)

- Prefer **Stalwart** as account / identity authority, including OIDC.  
- Use **OIDC** for apps that support it (BookStack required; Memos if suitable).  
- Pocket **radio identity ≠ username**; bind via pairing codes with revocation.  
- Registration modes: `OPEN` | `INVITE_ONLY` | `ADMIN_APPROVAL`.

## Alternatives

| Option | Why not default |
|--------|-----------------|
| Keycloak / full IdP | Heavier on Pi; defer unless Stalwart OIDC proves insufficient |
| Per-app local users | Breaks single-account UX |
| Equate LXMF address with username | Loses multi-device and revocation story |
| Stay passwordless in alpha | Unsafe; rejected as of N2 |

## Consequences

- N2 local auth is a **stand-in**; migrate usernames into Stalwart without renames.  
- Document trust boundaries and encryption in `docs/security.md`.  
- Unauthenticated API access allowed only when `waypost_env=test` (automated tests).
