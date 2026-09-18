# Federation / multi-Station (future)

**Status:** Document assumptions · **do not implement** unless it falls out of transport naturally.

---

## Future topology

```text
Station A ── Outpost(s) ── Station B
```

Users may have a **home Station** (identity, Postbox, profile anchor) while visiting another camp’s Station.

## Design constraints (do now)

- Logical IDs for users, messages, groups, conversations — **not** “local DB row only.”
- Account ≠ device; home Station can be a field on the account later without renaming `mid`s.
- Transports must not assume a single global Station instance in app code.

## Do not

- Build federation protocol yet.
- Hard-code “there is only one Waypost in the universe” into APIs.

## Open questions

- Trust model between Stations?
- Mail custody when home Station unreachable?
- Which Station is canonical for a conversation?

## Deferred decisions

- Full federation protocol, DNS-less discovery, conflict of two home Stations.
