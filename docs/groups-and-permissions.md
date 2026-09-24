# Groups and permissions

**Status:** v1 shipped (2026-09-24) · `server/services/groups/` is the one authorization
model — **do not** implement a second ACL per app.
**Today:** Groups scope Locker files (`scope='group'`) and can seed a Dispatch room's
initial membership. Dispatch "rooms" remain their own conversation-membership concept,
separate from Groups, used directly or seeded from a Group at creation time.

---

## What v1 built

- `GroupsStore`/`GroupsService` (`server/services/groups/`) — `groups` +
  `group_members(role)` tables. Other services consult it through an injected lookup
  (`is_member`/`get_role`), the same cross-service pattern as
  `NoticeboardService.get_binding` — never a second copy of membership data.
- HTTP routes only, `/api/groups*` — no Waylink ops. Same precedent as Rollcall (also
  portal/HTTP-only). Groups is a management concern, not something needed mid-hike from a
  Pocket; radio access can be a later slice if a real need shows up.
- **Roles:** exactly two enforced ranks, `member` and `admin` — not the five-role list
  below. See "Deferred" for why.
- **Locker integration:** `locker_files.group_id` (nullable) + a third `scope` value,
  `'group'`. Viewing/downloading a group-scoped file requires membership, checked via the
  same injected-lookup pattern.
- **Dispatch integration:** `POST /api/dispatch/conversations/rooms` takes an optional
  `group_id` that seeds the new room's membership from the group's *current* members — a
  one-time copy at creation, not a live link. Adding someone to the group afterward does
  not retroactively add them to rooms created from it.
- Portal: `groups.html` — create a group, list mine, view/add/remove members (add/remove
  is admin-only, enforced server-side).

## Requirements (original design)

First-class **Groups** (Family, Trail Crew, Maintenance, …) that can eventually scope:

- Dispatch room(s) — done (seed-on-create)
- Noticeboard — not yet (same pattern as Locker, straightforward when needed)
- Fieldbook area — not yet (Fieldbook itself doesn't exist yet)
- Locker folder — done
- Commons feed — not yet

Shared roles (original starting set):

```text
Member · Moderator · Editor · Operator · Administrator
```

v1 ships `Member` and `Administrator` only (stored as `member`/`admin`). Beacon create
restriction and private-transport guarantees for Dispatch/Postbox are unrelated to Groups
and were already true beforehand.

## Assumptions

- One authorization model consulted by services; no copy-paste permission tables. ✅ held.
- Group IDs are stable logical IDs (federation-friendly later). ✅ — `new_id()`, no
  Station-specific encoding.

## Open questions (still open)

- Group-specific custom roles — v2. `role` is stored as a free string so this doesn't need
  a schema change later, but only `member`/`admin` are enforced today.
- How do Outposts learn group encryption keys (if any) without holding passwords? — moot
  for now: nothing in v1 encrypts group-scoped content differently from shared content.
- Default group for "everyone on this Station"? — still undecided, staying open.

## Deferred

- Noticeboard/Commons/Fieldbook group-scoping — same pattern as Locker
  (`is_group_member` injection), not built because nothing in M8's exit criteria required
  more than 2 services and Fieldbook doesn't exist yet.
- Full 5-role permission semantics — v1 needed "who can manage membership" (admin) vs.
  "who's just in the group" (member); richer roles (Moderator/Editor/Operator) wait for a
  concrete feature that needs the distinction.
- Waylink/radio access to Groups — HTTP/portal-only for now.
- Live-syncing a Dispatch room's membership to its backing group after creation — the
  seed-on-create copy was enough for the exit criteria; a live link is more machinery than
  anything currently needs.
