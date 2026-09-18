# Groups and permissions

**Status:** Design now · **do not** implement a second ACL per app.  
**Today:** Dispatch “rooms” are conversation membership only — **not** Groups.

---

## Requirements

First-class **Groups** (Family, Trail Crew, Maintenance, …) that can eventually scope:

- Dispatch room(s)
- Noticeboard
- Fieldbook area
- Locker folder
- Commons feed

Shared roles (starting set):

```text
Member · Moderator · Editor · Operator · Administrator
```

Beacon create must be restricted. Private Dispatch/Postbox remain private on every transport.

## Assumptions

- One authorization model consulted by services; no copy-paste permission tables.
- Group IDs are stable logical IDs (federation-friendly later).

## Open questions

- Group-specific custom roles — v2?
- How do Outposts learn group encryption keys (if any) without holding passwords?
- Default group for “everyone on this Station”?

## Deferred

- Full Groups UI and migrations until Dispatch + identity groundwork are trustworthy.
- Do not retrofit Commons/Locker with ad-hoc ACLs before this model lands.
