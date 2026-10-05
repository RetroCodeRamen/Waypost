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
| `TRAILHEAD` | Trailhead (Station's small web) |
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

## Profile (`PROFILE`) — device pairing

| Operation | Payload | Reply |
|-----------|---------|-------|
| `PAIR_REDEEM` | `{code, node_id, transport_dest}` | `{ok, username, node_id, transport_dest, ...}` — binds the device to the account that created the 6-digit code |
| `WHOAMI` | `{transport_dest}` | `{username, display_name}` for the sending device's binding, or `not_paired` |
| `UNPAIR` | `{transport_dest}` | `{ok}` — the sending device revokes **its own** binding (never another device's); idempotent |

`transport_dest` (the device's own Reticulum destination hash) lets Station answer a device it has
**no binding** for — a Reticulum packet doesn't carry a return address, so an unpaired Scout would
otherwise never hear `not_paired`. It is ignored for bound devices: their route only ever comes
from the binding, so nobody can redirect another device's replies by claiming its node id.
| `ROLL_LIST` | `{offset?}` | `{people:[{u, n, d}], offset, more}` — the directory minus the caller: username, display name, their Scout's destination hash (`d`, for direct Scout-to-Scout later; `""` if none). **Paired devices only** |

A Scout asks `WHOAMI` once Station is reachable after boot: it adopts the account if it was bound
elsewhere (portal/API) and drops a stale one if it was unpaired. After a local unpair it sends
`UNPAIR` before ever asking `WHOAMI` again, so Station can't hand the old account back.

## Fieldbook (`FIELDBOOK`) — M5 ✅ (2026-09-24, sim)

Progressive: **search → outline → section → diff**. A Pocket never has to pull a whole page to
read one part of it or to catch up on an edit. Full design: [fieldbook.md](fieldbook.md).

| Operation | Payload | Reply |
|-----------|---------|-------|
| `WIKI_SEARCH` | `{q, limit?}` | `{results:[{slug,title,revision,updated_by,updated_at,size,match,snippet}]}` — never bodies |
| `WIKI_GET` | `{slug}` | `{page}` full body (Wi‑Fi-sized; avoid over LoRa) |
| `WIKI_GET` | `{slug, outline:true}` | `{slug,title,revision,size,outline:[{index,heading,level,size}]}` |
| `WIKI_GET` | `{slug, section: idx \| heading}` | `{slug,title,revision,section:{index,heading,level,text,size}}` |
| `WIKI_GET` | `{slug, since: N}` | `{unchanged:true}` if N is current, else `{from_revision,to_revision,diff}` (unified diff) |
| `WIKI_SEARCH` | `{q, compact:true, offset?}` | **Radio-sized:** `{results:[{slug,title}], offset, more}`, as many hits as fit in one packet; titles cut to 40 chars |
| `WIKI_GET` | `{slug, outline:true, offset, limit}` | **Radio-sized:** `{slug, revision, outline:[{index,heading}], offset, more}` |
| `WIKI_GET` | `{slug, section: idx, offset, limit}` | **Radio-sized:** `{slug, revision, index, offset, total, text}`, `text` a byte slice of the section (never splits a UTF-8 character); read on from `offset + len(text)` until `total` |
| `WIKI_UPDATE` | `{slug, base_revision, body}` or `{slug, base_revision, section, section_text}` + optional `title`, `summary` | `{page}` without body (compact ack) |
| `WIKI_CREATE` | `{title, body, slug?, summary?}` | `{page}` without body; `already_exists` error if the slug is taken |

The radio-sized forms are selected by `compact` / `limit` being present, so Wi‑Fi callers keep
the full shapes. They exist because a Pocket over LoRa receives at most one encrypted
Reticulum packet per reply (383 bytes, ~170 of them left for text after the envelope);
replies are sized by encoding and measuring them (`shared/protocol/radio.py`), and
`server/tests/test_trailhead.py` guards that every shape a Scout requests fits.

Sections are ATX headings (`# …`); section 0 is any preamble. Every save appends a
`wiki_revisions` row; nothing is rewritten.

**Revision conflict:** `WIKI_UPDATE` whose `base_revision` isn't current returns an `ERROR`
reply `{error:"revision_conflict", current_revision, updated_by, outline}` — the outline, not
the body, so a Pocket can decide which section to re-fetch. Never a silent overwrite. Over HTTP
the same case is `409` with the full current page.

**Radio authz:** `WIKI_CREATE`/`WIKI_UPDATE` resolve the author from the sending device's
binding (`env.src`), same as Noticeboard/Beacon; unbound devices get `unauthorized_device`.
Reads are open.

---

## Trailhead (`TRAILHEAD`) — 2026-10-03

The Station's small web: short linked text pages, edited in the portal (`/trailhead.html`),
read on the portal or on a Scout over LoRa. Gemini/gopher-style, not HTML (Waylink is
compact RPC over radio). One construct per line:

```
# Heading            (## / ### also)
=> path Link label   (link to another Trailhead page)
anything else        (plain text, wrapped by the reader)
```

| Operation | Payload | Reply |
|-----------|---------|-------|
| `TRAIL_GET` | `{path?, offset, limit}` | `{path, offset, total, text}` plus `title` on the first chunk (`offset` 0); `path` defaults to `home`; `not_found` error if missing |

Same chunking rules as the radio-sized Fieldbook reads. Reads are open; writes are portal
only (`PUT /api/trailhead/pages/{path}`). Paths: `a-z 0-9 - _ /`, max 64; pages max 8 KB
(a Scout reads ~160 bytes per ~1.5 s round trip). A fresh Station seeds `home`,
`getting-started`, and `camp-info`.

---

## Dispatch

| Operation | Purpose |
|-----------|---------|
| `MSG_SEND` | Send message (to peer Pocket, room, or via Station) |
| `MSG_LIST` | Conversation history window |
| `MSG_ACK` | Delivery/read state |
| `MSG_SYNC` | Catch-up / upload carried copies after reconnect (to Station or peer) |

Delivery states: `QUEUED` → `SENT` → `ROUTED` → `DELIVERED` → `READ` (or `EXPIRED`).

**Radio-sized forms for Scouts (2026-10-04)** — every reply fits one encrypted packet:

| Operation | Payload | Reply |
|-----------|---------|-------|
| `MSG_CONVS` | `{offset?}` | `{conversations:[{id, t, ts, from}], offset, more}` — the bound user's conversations, newest activity first; `t` = the other person, or the room title |
| `MSG_LIST` | `{conversation_id \| peer, skip?}` | `{conversation_id, messages:[{id, s, b, ts}], more}` — newest first; `skip` = how many newest the device already holds (count paging; a time cursor would skip messages sharing a timestamp). Bodies over 140 bytes are cut with "…"; `ts` is integer ms. **Members only** (bound device's user must be in the conversation) |
| `MSG_SYNC` | `{username, messages:[]}` | Radio devices (`pocket-`/`radio-`/`rns-`) get as many pending messages as fit, `more: true` until drained; **only messages actually in the reply are marked delivered**. Other callers get the whole queue, full bodies |
| `MSG_PUSH` | — | To radio devices, a body too long for one packet is cut with "…" (the Wi‑Fi outbox and history keep it whole) |

**Who the sender is (2026-10-03):** over Waylink, `MSG_SEND`'s sender is the account the sending
device is bound to (`device_bindings`), never the payload. A bound device may include `sender`
only if it matches (`sender_mismatch` otherwise). A **claimed Outpost** may relay someone else's
message with the author in the payload (trusted relay infrastructure, as for `BEACON_SYNC`).
Anything else gets `unauthorized_device`. From a radio device, a `peer` Station has no account
for gets `unknown_user` (rather than a dead-end conversation; the portal's HTTP path still creates
users on send).

**Signed `MSG_SEND` (2026-10-04, roadmap D3; identity keys 2026-10-05):** a signed-in device signs
each message with the person's identity key and sends
`{p (peer) | v (conversation id), b (body), o (16-byte object id), a (author's identity id),
s (64-byte signature)}`, with the **signed time in the envelope `ts`** (1 = the device didn't know the
time). Signed bytes: `WAYPOST-OBJ-1\n` + `k o u a v b t` as `name:len:value`
(`server/services/identity/objects.py`; for a direct message `v` is `dm:<a>:<b>`). Station takes the
author from the identity id, so **any** node may deliver it (a courier, an Outpost); errors
`bad_signature`, `unknown_identity`, `identity_revoked`, `unknown_user`. The message id is `o` in hex; the body is stored exactly as signed; the reply adds
`signed: true`. A 64-byte signature leaves less room: 127 bytes of body to a short username, 102 to a
32-character one — every compose screen (Scout, Outpost page) limits typing to what fits signed
`MSG_SEND` *and* peer sync (`max_signed_body`).

**Device-chosen message id (2026-10-04):** `MSG_SEND` takes an optional `message_id`. The Scout's
outbox sets its own (32 hex characters, random) so a resend after a lost reply is the **same**
message: Station stores it once, replies `ok` with `created: false`, and pushes nothing again. A
`message_id` that already belongs to a different sender or conversation gets `message_id_conflict`.

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
| `BEACON` | `BEACON_GET`, `BEACON_PUSH`, `BEACON_CLEAR`, `BEACON_LIST`, `BEACON_SYNC` (M6 ✅ — Outpost uploads queued push/clear events; Station returns current active beacon for local cache) |
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
| `NOTICE_LIST` | Active (or all) notices; annotated with `acked` per-notice when the caller resolves to a known user |
| `NOTICE_GET` | Fetch one notice by `id`, same `acked` annotation |
| `NOTICE_CREATE` | Post a bulletin — author is the **radio device's bound account**, not a payload field (see Security note below) |
| `NOTICE_EXPIRE` | Mark a notice inactive — requires a bound device |
| `NOTICE_ACK` | Mark a notice read/acknowledged for the calling (bound) user — idempotent |

**Security (M6-era fix, 2026-09-23):** `NOTICE_CREATE`, `NOTICE_EXPIRE`, and `NOTICE_ACK` over Waylink resolve the acting username from the sender's **bound device** (`device_bindings`, the same mechanism `MSG_SYNC` authz already used — see `docs/protocol.md`'s Dispatch section) rather than trusting a self-reported `author`/`username` field in the payload. An unbound `envelope.src` gets `unauthorized_device`. `NOTICE_LIST`/`NOTICE_GET` stay open to read (matching the HTTP routes' openness) but annotate `acked` using the bound identity when one exists.

### Beacon (`BEACON`)

Emergency / high-priority alerts (distinct from Noticeboard). One active Beacon at a time; new push clears the previous. Anti-replay via `mid`. Author push cooldown (default 30s) for flood control.

| Operation | Purpose |
|-----------|---------|
| `BEACON_GET` | Current active Beacon (or null) |
| `BEACON_PUSH` | Activate a Beacon (`title`, `body`, `severity`) — author is the **radio device's bound account**, not a payload field |
| `BEACON_CLEAR` | Clear active Beacon — requires a bound device |
| `BEACON_LIST` | Recent history |

Severities: `emergency`, `urgent`, `advisory`.

**Security (M6-era fix, 2026-09-23):** before this, `BEACON_PUSH`/`BEACON_CLEAR` over Waylink trusted whatever the packet's own payload claimed (`author`, or just `envelope.src` raw) — for an emergency-alert system, that meant anyone with a working radio could push, or silence, an alert as anyone. Both ops now resolve the acting username from `device_bindings` (same fix, same mechanism, as Noticeboard above) and reject with `unauthorized_device` if the sender isn't a bound device.

**Alerts to Scouts (2026-10-04):** whenever a Beacon is raised or cleared (portal, radio, or Outpost relay — all go through `BeaconService.push/clear`), Station sends `BEACON_ALERT` (a request, unprompted) to every bound radio device: `{id, t, sev, b, a, ts, on}` — title, severity, body cut to fit one packet, author, time, active. Scouts show a full-screen alert over any app (the lock screen too) until acknowledged, and also check `BEACON_GET {compact:true}` on each catch-up so an alert raised while they were off still shows. `BEACON_LIST {compact:true}` → `{beacons:[{id, t, sev, ts, on}], more}`.

**Outpost propagation (2026-09-24):** `BEACON_SYNC` mirrors Corkboard's `BOARD_SYNC` — an Outpost uploads a batch of queued `{op: push, mid, title, body, severity}` events (dedup by `mid`), Station applies them and returns `{ok, ingested, active}`. Unlike `BOARD_SYNC`/Corkboard's free-text-signature model, an Outpost's push carries **no author field at all** — `BeaconService.sync()` requires `envelope.src` to be a *claimed* Outpost (`CorkboardStore.is_claimed`, not just "sent a packet once") and always attributes the push to `outpost:{node_id}`, never anything self-reported in the payload. This is deliberately push-only: `BEACON_CLEAR` (silencing an active alert) stays a Station-side action, on purpose — an anonymous walk-up visitor being able to *report* an emergency and one being able to *silence* someone else's real active alert are very different risk profiles, and only the first is built into the Outpost's own walk-up UI (`/beacon`, no login). Sim-tested via `OutpostNode.sync_beacon()`/`queue_beacon_push()`; the real firmware's own `/beacon` page + `sync_beacon()` (`firmware/outpost/src/main.cpp`) exist now too — compiled and flashed, verified live over a real Reticulum stack for the Station-side auto-claim path it shares plumbing with, but the Outpost-side walk-up→real-LoRa→Station round trip itself still needs a human at the board with a second radio to fully verify. **Still out of scope:** multi-hop beacon courier parallel to Dispatch, Pocket reading the Outpost's cached active beacon over Wi‑Fi (no Pocket firmware exists yet).

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
| `BOARD_SYNC` | Outpost → Station: upload notes (dedup by `mid`); Station registers/touches the outpost (keyed by `env.src`) and piggybacks that outpost's Station-composed outbox **and a `claimed: bool`** back in the same response |
| `OUTPOST_CLAIM` | Outpost → Station: `{code, transport_dest, display_name}` — redeems a pairing code (same codes/UI as Pocket pairing, `server/services/auth/pairing.py`), registers the outpost, and calls `learn_route(node_id, transport_dest)` **before** the reply is sent, which is what makes the reply routable at all |

**Why claiming exists:** Station's transport only knows how to reach a
peer whose Reticulum destination hash it's been told — an Outpost's own
hash isn't discoverable automatically. `OUTPOST_CLAIM` carries that hash
directly in its own payload, and `learn_route` runs synchronously inside
the handler, before `WaylinkGateway` resolves and sends the reply — so
even a never-before-seen Outpost's very first request gets a routable
response. Until an Outpost is claimed, `BOARD_SYNC` requests still
*arrive* at Station, but Station has no way to send anything back.

**Auto-claim (no `OUTPOST_CLAIM` packet at all):** Station can also claim
an Outpost purely from a genuine Reticulum announce — no pairing code,
no `/claim` walk-up. This isn't a new Waylink op; it happens below the
Waylink layer entirely. `ReticulumTransport` registers an
`RNS.Transport` announce handler for the shared `waypost.waylink`
aspect; an unclaimed Outpost whose physical button hasn't disabled it
includes a marker (`AUTO_CLAIM_MARKER = b"WPOST-CLAIM:"` + its
`node_id`) in its own periodic announce's `app_data`. On a match,
Station resolves the destination hash **from the announce itself**
(Reticulum-signed, not a self-reported payload field) and runs the same
`learn_route` + `touch_outpost` `OUTPOST_CLAIM` already does, just
without the code lookup — see `docs/security.md` for why that's a
different, not weaker, proof of legitimacy. On by default
(`WAYPOST_AUTO_CLAIM_OUTPOSTS`); the Outpost learns it worked via the
`claimed` field on its next `BOARD_SYNC` reply, same as a walk-up claim.

HTTP (Station portal, any signed-in user): `GET /api/corkboard/outposts`,
`GET /api/corkboard/outposts/{id}/notes`, `POST
/api/corkboard/outposts/{id}/notes` (queues into the outbox — delivered on
that outpost's next `BOARD_SYNC`); `POST /api/auth/pairing/create` (shared
with Pocket pairing) generates the claim code shown in the portal.

### Finder (`FINDER`)

Cross-app search — "titles → selected result," never a search index of its
own (`server/services/finder/`). A live fan-out query across each
already-existing service's own listing/search method, every time; no
persisted index, no new subsystem. Deliberately scoped to
consciously-public-or-already-scoped content only:

| Included | Excluded, deliberately |
|----------|------------------------|
| Commons, Noticeboard, Fieldbook, Locker | Dispatch, Postbox — private by design, see `docs/security.md`'s "must never authorize... private Dispatch threads / another user's Postbox" |
| | Corkboard — its own design explicitly rules out a merged cross-outpost view |

Every result passes through the *same* visibility check that service's own
native listing already applies — a group-scoped Noticeboard notice never
surfaces to a non-member via Finder, a personal Locker file never surfaces
to anyone but its owner, exactly as if they'd asked that service directly.
Finder is a new way to *find* things, never a new way to *see* them.

| Operation | Purpose |
|-----------|---------|
| `SEARCH` | `{q, limit}` → `[{service, id, title, snippet, updated_at, url}, ...]`, ranked title-hits-first then most-recent. Snippets only, matching the bandwidth philosophy and Locker's own "metadata only over Waylink" precedent — never full bodies or file contents. |

HTTP: `GET /api/finder/search?q=...` (portal, any signed-in user).

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
- 🔧 Planned: `mid` stays the per-request id (64-bit, request/reply correlation). Synced **objects**
  get their own 128-bit `oid`, created once by the author's device. Every store is keyed by `oid`,
  insert-if-absent ([network-model.md](network-model.md) §4).

---

## Offline identity (PROFILE CERT ops, 2026-10-04)

Certificates signed by Station's community key vouch for each person's **identity key** (derived from
username + password, [identity.md](identity.md#offline-identity-target)), so any node can check a
person offline. Keys and signatures travel as CBOR **byte strings**. Every reply fits one packet
(tested). Reworked 2026-10-05: device certificates (`CERT_ISSUE`, `CERT_DEV`) are gone.

| Op | Who may ask | Payload | Reply |
|---|---|---|---|
| `CERT_ROOT` | anyone | `{}` | `{pk}` — community public key (32 bytes) |
| `CERT_GET` | paired device, claimed Outpost | `{u?}` (default: self) or `{i}` (identity id) | `{cert}`; errors `unknown_user`, `no_identity_yet` (Station hasn't seen their password since keys came in), `unknown_identity` |
| `CERT_LIST` | paired device, claimed Outpost | `{offset}` | `{certs, offset, more}` — everyone's, paged (Outposts cache them all) |
| `CERT_REVOKED` | paired device, claimed Outpost | `{offset}` | `{revs, offset, more}` — revocations still worth spreading |
| `LOGIN_NONCE` | anyone | `{transport_dest?}` | `{nonce}` (16 bytes, 2 minutes, one per node) |
| `LOGIN` | anyone | `{u, rd (16-byte destination), sig}` — `sig` by the identity key over `WAYPOST-LOGIN-1\n<node_id>\n<rd>\n<nonce>` | `{ok, username, display_name}` and the node is bound to the account; errors `wrong_password`, `unknown_user`, `no_identity_yet`, `login_expired` |

Certificate map keys: `k` kind (`id`/`rev`), `n` serial, `i` identity id, `u`, `dn`, `p` identity
public key, `t` issued, `x` expires, `r` revoked serial, `s` signature.

---

## Peer sync (`SYNC`) — 2026-10-05 (roadmap D4)

The same four ops between **any** two nodes — Scout, Outpost, Station, a courier — over any transport;
nothing here needs Station. Code: `server/services/sync/engine.py` (Python, also the reference),
`firmware/pocket/src/sync.cpp` (Scout). Design: [network-model.md](network-model.md) §5.

| Op | Payload | Reply |
|---|---|---|
| `HELLO` | `{r role, i [interests], h [held scopes], rd? (16-byte reply destination)}` | `{r, i, h}` |
| `SUM` | `{q scope, p hex prefix}` | `{n, x (8-byte XOR), oids [16-byte ids]}` when ≤10, else `{n, x, sub [[n, x] ×16]}` |
| `WANT` | `{o}` | the object's fields, or `{missing: true}` |
| `PUT` | the object's fields | `{ok, new}` or an error (`bad_signature`, `unknown_certificate`, `certificate_revoked`, …) |

**Interests:** `*` (everything: Station, Outposts), `u:<name>` (a person: author, or party to a
direct conversation), `c:<conversation id>` (a room). `h` lists the scopes of what a node carries
for others, so a take-everything peer can find a courier's cargo. The initiator walks the prefix tree
of each scope either side wants or holds, pulls what it wants and lacks, pushes what the peer wants
and lacks. In sync: **2 requests** (HELLO + one SUM). 300 shared + 2 different each side: 13.

**Object on the wire** (`dispatch.msg`, fields directly in the payload): `o` (16 bytes), `a`
(author's identity id), `b`, `t` (signed time, s), `s` (signature), and `p` (the other person,
direct) or `v` (conversation id). The author comes back from their identity certificate. Every node verifies
on arrival with cached certificates, whoever carried it.

**Replying to a peer:** a Reticulum packet doesn't say who sent it, so `HELLO` carries the
initiator's destination (`rd`); the responder keeps it for that node's following requests. Station
replies to paired devices by their binding as for every other op.

**Size:** compose limits are the body that fits signed `MSG_SEND`, `PUT` *and* a `WANT` reply
between devices with the longest node ids (`max_signed_body`, Python and `firmware/common`: 127 bytes
to a short name).

**Who syncs with whom:** Scouts with Station (3 min), with Outposts they hear announcing
(`WPOST-OUTPOST:<id>` / `WPOST-CLAIM:<id>` in the announce) and contacts' Scouts in range (1 min,
or at once after writing). Outposts take everything (`*`): Station every 2 min (and right after
something new), and **push** a new message straight to the Scout of anyone it concerns who synced
with that Outpost in the last 30 minutes.

**Not yet:** delivery receipts as objects (a message pulled by sync is still `SENT` on Station),
full capability announces (D6), courier policy (D7), Tier 2 (D8), rooms on the Outpost page.

## Outpost Wi-Fi page API (`http://out.post/msg`, 2026-10-05)

JSON over the Outpost's own Wi-Fi (`firmware/outpost/src/outpost_web.cpp`; page in
`firmware/outpost/web/`). Session cookie `wps` per browser.

| Endpoint | Body | Reply |
|---|---|---|
| `GET /api/hello` | — | `{node, nonce}` |
| `POST /api/login` | `{u, p (public key hex), n (nonce), s (signature hex)}` — `s` over `WAYPOST-WEB-LOGIN-1\n<node>\n<nonce bytes>` | `{ok, u, id, vouched}`; `wrong_password` when Station vouches for a different key under that name |
| `GET /api/convs` | — | `{convs: [{id, with, t, n}]}` |
| `GET /api/msgs?c=<conv>` | — | `{msgs: [{o, u, b, t}], max}` |
| `POST /api/send` | `{o, v, b, t, s}` — signed in the browser | `{ok}`; `bad_signature`, `too_long`, `not_a_member` |
| `POST /api/logout`, `GET /api/me` | | |


**Announce `app_data`** (Tier 1): compact capability record (`r` roles, `s` services bitmap,
`t` transports, `st` Station reachability + age, `h` Bloom filter of identity ids it holds objects
for, `v` summary version). Generalizes today's Outpost auto-claim marker ✅.

**Compatibility:** `DISPATCH/MSG_SYNC` ✅ keeps working as the Dispatch-only form; `MSG_SEND` ✅
keeps working and becomes "create a `dispatch.msg` object at the receiving node" when unsigned
(bound device, today's rule) or "ingest the object" when signed.

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
