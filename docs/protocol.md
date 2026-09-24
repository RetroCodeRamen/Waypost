# Waylink RPC protocol

Versioned compact RPC carried over Waylink. Wi-Fi clients use HTTP/JSON against the same logical operations; this document defines the **radio-facing** envelope and service operations.

**Encoding (initial):** CBOR  
**Do not** micro-optimize byte counts until real airtime is measured.

---

## Envelope (v1)

Conceptual fields:

| Field | Type | Description |
|-------|------|-------------|
| `v` | uint | Protocol version (`1`) |
| `mid` | bytes/str | Globally unique message ID (dedup key) |
| `rid` | bytes/str | Request ID (correlates request/response) |
| `src` | bytes/str | Source identity / destination handle |
| `dst` | bytes/str | Destination identity / handle |
| `svc` | str | Service identifier |
| `op` | str | Operation |
| `flags` | uint | Bit flags (request/response/error/ack/…) |
| `ts` | uint | Unix timestamp (seconds) |
| `ttl` | uint | Time-to-live (hops or seconds — see flags) |
| `payload` | any | Operation-specific CBOR |

Shared schema lives in `shared/protocol/` and is mirrored in Python under `server` for Station use.

### Flags (initial)

| Bit | Name | Meaning |
|-----|------|---------|
| 0 | `REQUEST` | Client → server or peer request |
| 1 | `RESPONSE` | Reply to a request |
| 2 | `ERROR` | Failure payload |
| 3 | `ACK` | Transport/application ack |
| 4 | `QUEUED` | Accepted for later delivery |

---

## Service identifiers

| ID | User-facing |
|----|-------------|
| `CORE` | System / ping |
| `DISPATCH` | Dispatch |
| `MAIL` | Postbox |
| `FIELDBOOK` | Fieldbook |
| `PROFILE` | Profile / Rollcall data |
| `COMMONS` | Commons |
| `NOTICEBOARD` | Noticeboard |
| `BEACON` | Beacon |
| `LOCKER` | Locker |
| `FINDER` | Finder |
| `SYNC` | Cache / sync control |
| `SIGNAL` | Signal diagnostics |
| `ATLAS` | Maps / location (Station origin + Pocket fixes) |

---

## Core operations

| Operation | Direction | Notes |
|-----------|-----------|-------|
| `PING` | any → any | Liveness; reply `PONG` |
| `PONG` | response | Echo / latency |

---

## Postbox (`MAIL`)

LoRa is **not** mailbox sync. Canonical mailbox stays on Station. Pocket requests explicitly.

| Operation | Purpose |
|-----------|---------|
| `MAIL_STATUS` | Unread counts / summary |
| `MAIL_LIST` | Compact headers |
| `MAIL_GET` | Selected body |
| `MAIL_SEND` | Compose/send |
| `MAIL_REPLY` | Reply |
| `MAIL_MARK` | Read/delete flags (later) |
| `MAIL_FLUSH` | Deliver queued OUTBOX messages |

Folders: `INBOX`, `OUTBOX` (queued outbound), `SENT`, `DRAFTS`.

Outbound mail is stored in **OUTBOX** first, then flushed to **SENT** + recipient **INBOX**.  
Waylink `MAIL_NOTIFY` pushes are persisted in SQLite (survive Station restart / offline Pocket).

Attachments: metadata over LoRa; bodies normally Wi-Fi only.

---

## Fieldbook

| Operation | Purpose |
|-----------|---------|
| `WIKI_SEARCH` | Compact results |
| `WIKI_GET` | Structured/plain content |
| `WIKI_UPDATE` | Edit with base `revision` |
| `WIKI_CREATE` | New page (later) |

On revision mismatch: return conflict with current revision — never silent overwrite.

---

## Dispatch

| Operation | Purpose |
|-----------|---------|
| `MSG_SEND` | Send message (to peer Pocket, room, or via Station) |
| `MSG_LIST` | Conversation history window |
| `MSG_ACK` | Delivery/read state |
| `MSG_SYNC` | Catch-up / upload carried copies after reconnect (to Station or peer) |

Delivery states: `QUEUED` → `SENT` → `ROUTED` → `DELIVERED` → `READ` (or `EXPIRED`).

**Offline / no-Station path:**
- `MSG_SEND` may target another Pocket directly over Waylink; destination **delivers locally** when it is the recipient.  
- Couriers (other Pockets, Outposts) may store and forward the same `mid` toward Station or the recipient.  
- When Station (or Wi‑Fi) appears, `MSG_SYNC` (or equivalent push) merges by `mid` so portal history matches what people already read in the field.  
- Reading on-device does **not** cancel the duty to sync a copy to Station when possible.

---

## Other services (initial ops)

| Service | Operations |
|---------|------------|
| `PROFILE` | `PROFILE_GET`, `PROFILE_UPDATE` (not yet implemented); `PAIR_REDEEM` (M4 ✅ — redeem a pairing code created via `POST /api/auth/pairing/create`, binding `node_id` to that code's account without a password ever crossing the radio link) |
| `COMMONS` | `POST_LIST`, `POST_CREATE`, `POST_GET` |
| `NOTICEBOARD` | `NOTICE_LIST`, `NOTICE_GET`, `NOTICE_CREATE`, `NOTICE_EXPIRE` |
| `BEACON` | `BEACON_GET`, `BEACON_PUSH`, `BEACON_CLEAR`, `BEACON_LIST` |
| `LOCKER` | `FILE_LIST`, `FILE_INFO`, `FILE_DELETE` |
| `FINDER` | `SEARCH` |
| `SIGNAL` | `SIGNAL_STATUS`, `SIGNAL_ROUTE` |
| `ATLAS` | `LOC_REPORT`, `LOC_GET`, `LOC_LIST`, `ORIGIN_GET`, `ORIGIN_SET` |
| `CORKBOARD` | `BOARD_SYNC` (M6 ✅ — an Outpost uploads its public note board, dedup by `mid`, keyed by `env.src` so an Outpost can't claim to be a different one; Station piggybacks that Outpost's outbox back in the same response, mirroring `MSG_SYNC`); `OUTPOST_CLAIM` (M6 ✅ — redeem a Station-generated pairing code to register and teach Station this Outpost's Reticulum destination hash, required once before `BOARD_SYNC` can route a reply at all — see below) |

### Commons (`COMMONS`)

Local Station feed (Memos adapter later). Wi‑Fi clients use HTTP; Pocket uses compact RPC:

| Operation | Purpose |
|-----------|---------|
| `POST_LIST` | Recent posts (newest first) |
| `POST_CREATE` | Create a post (`author`, `body`, optional `title`) |
| `POST_GET` | Fetch one post by `id` |

### Noticeboard (`NOTICEBOARD`)

Structured bulletins (distinct from Commons posts). Priorities: `high`, `normal`, `low`. Optional `expires_at` auto-clears active list.

| Operation | Purpose |
|-----------|---------|
| `NOTICE_LIST` | Active (or all) notices |
| `NOTICE_GET` | Fetch one notice by `id` |
| `NOTICE_CREATE` | Post a bulletin |
| `NOTICE_EXPIRE` | Mark a notice inactive |

### Beacon (`BEACON`)

Emergency / high-priority alerts (distinct from Noticeboard). One active Beacon at a time; new push clears the previous. Anti-replay via `mid`. Author push cooldown (default 30s) for flood control.

| Operation | Purpose |
|-----------|---------|
| `BEACON_GET` | Current active Beacon (or null) |
| `BEACON_PUSH` | Activate a Beacon (`title`, `body`, `severity`) |
| `BEACON_CLEAR` | Clear active Beacon |
| `BEACON_LIST` | Recent history |

Severities: `emergency`, `urgent`, `advisory`.

### Signal (`SIGNAL`)

| Operation | Purpose |
|-----------|---------|
| `SIGNAL_STATUS` | Station / Waylink / service diagnostics snapshot |
| `SIGNAL_ROUTE` | Probe reachability / route to a node |

### Corkboard (`CORKBOARD`)

Per-outpost public note board — a `body` plus a free-text `signature`, no
account required to author one (matches the walk-up-at-the-Outpost's-Wi-Fi
use case). The Outpost's own copy is durable and primary; Station's is
backup, never merged across outposts — a Station user always reads/posts
to exactly one known outpost.

| Operation | Purpose |
|-----------|---------|
| `BOARD_SYNC` | Outpost → Station: upload notes (dedup by `mid`); Station registers/touches the outpost (keyed by `env.src`) and piggybacks that outpost's Station-composed outbox back in the same response |
| `OUTPOST_CLAIM` | Outpost → Station: `{code, transport_dest, display_name}` — redeems a pairing code (same codes/UI as Pocket pairing, `server/services/auth/pairing.py`), registers the outpost, and calls `learn_route(node_id, transport_dest)` **before** the reply is sent, which is what makes the reply routable at all |

**Why claiming exists:** Station's transport only knows how to reach a
peer whose Reticulum destination hash it's been told — an Outpost's own
hash isn't discoverable automatically. `OUTPOST_CLAIM` carries that hash
directly in its own payload, and `learn_route` runs synchronously inside
the handler, before `WaylinkGateway` resolves and sends the reply — so
even a never-before-seen Outpost's very first request gets a routable
response. Until an Outpost is claimed, `BOARD_SYNC` requests still
*arrive* at Station, but Station has no way to send anything back.

HTTP (Station portal, any signed-in user): `GET /api/corkboard/outposts`,
`GET /api/corkboard/outposts/{id}/notes`, `POST
/api/corkboard/outposts/{id}/notes` (queues into the outbox — delivered on
that outpost's next `BOARD_SYNC`); `POST /api/auth/pairing/create` (shared
with Pocket pairing) generates the claim code shown in the portal.

### Locker (`LOCKER`)

Shared and personal files stored on the Station. **Wi‑Fi only for bodies** — Waylink exposes metadata (`FILE_LIST` / `FILE_INFO`), not file bytes.

| Operation | Purpose |
|-----------|---------|
| `FILE_LIST` | List visible files (`shared` for everyone; `personal` for owner) |
| `FILE_INFO` | Metadata for one file |
| `FILE_DELETE` | Soft-delete (uploader only) |

HTTP: `POST /api/locker/files` (multipart upload), `GET .../download`. Default max upload 25 MiB.

### Atlas (`ATLAS`)

Location for camp maps. **Station and bare LoRa bridges have no GPS.** GPS-equipped Pockets (e.g. LilyGO T-Deck Plus) are the source of truth for fixes.

**Station origin:** set once by copying a Pocket’s *current* fix into a static `station_origin`. The origin does **not** track that Pocket afterward.

**Pocket reports:** periodic `LOC_REPORT` (default every **10–15 minutes**). Keep payloads tiny (lat/lon + accuracy + optional battery); progressive rules apply.

| Operation | Purpose |
|-----------|---------|
| `LOC_REPORT` | Pocket → Station: last fix (`lat`, `lon`, `acc_m?`, `alt_m?`, `fix_ts`) |
| `LOC_GET` | Request last-known position for a `node_id` / username |
| `LOC_LIST` | Compact list of known positions (Station origin + Pockets) |
| `ORIGIN_GET` | Read Station camp origin |
| `ORIGIN_SET` | Set Station origin from a chosen Pocket’s current (or last-known) fix — **snapshot only** |

Portal Atlas (Wi‑Fi) uses HTTP against the same logical model; distance / range rings are computed server-side from `station_origin`.

---

## Deduplication and TTL

- Every operation/message has a globally unique `mid`.  
- Outposts, Pockets (as couriers), and Station drop duplicates.  
- Expired TTL → do not forward; may surface as `EXPIRED` to originator when known.  
- Carry-forward queues are bounded (disk/RAM); oldest or lowest-priority drop first under pressure.

---

## Progressive retrieval

Always prefer summary → detail → body. Never push large content unsolicited.

---

## Versioning

- Increment `v` for incompatible envelope changes.  
- Additive operations may stay on the same major version if unknown ops return a clear error.  
- Document breaking changes in ADRs / changelog.

---

## Security note

Envelope authenticity relies on Waylink/Reticulum crypto where available. Application authorization is separate: a valid packet does not grant Postbox access to another user’s mail. See [security.md](security.md).
