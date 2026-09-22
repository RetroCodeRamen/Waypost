# Offline sync and operation queues

**Status:** Design now · implement starting with milestone **N1** (Dispatch first). M3 added a first `courier_queue` / `MSG_SYNC` implementation for Dispatch (peer↔peer without Station + carry-forward to Station, dedup by `mid`) — see `server/services/dispatch/peer.py` and `server/tests/test_mesh_dispatch.py`. Multi-hop courier and Wi‑Fi↔LoRa failover are covered in the same sim. **Sim-only so far** — no Pocket firmware, no hardware.  
**Not:** A speculative framework — first consumer is Dispatch; other apps adopt the same states.

---

## Requirements

- Disconnected operation is **normal**, not an error.
- One logical conversation/message across Wi‑Fi, LoRa, Outposts, and delayed delivery.
- Queues survive process restart where practical (Station SQLite; Pocket microSD later).
- Users can **see** what is waiting (Signal and/or Today), not only silent background work.
- Dedup by durable `mid` when copies converge at Station or peer.

## Shared states (target)

```text
LOCAL
QUEUED
WAITING_FOR_ROUTE
WAITING_FOR_STATION
WAITING_FOR_WIFI
SYNCING
SYNCED
CONFLICT
FAILED
EXPIRED
```

Apps map domain language onto these (e.g. Dispatch `delivery_state` ↔ queue state).

## Expected behavior

| Situation | Behavior |
|-----------|----------|
| Destination unbound / unreachable | Keep `QUEUED` / `WAITING_*`; do not fail the send UX as hard error |
| Peer appears (bind, LoRa hear, Wi‑Fi) | Opportunistically flush matching outbox |
| Recipient Pocket offline from Station | Peer path or courier may deliver first; Station sync later via `MSG_SYNC` / carry |
| Wi‑Fi-only payload (Locker body) | `WAITING_FOR_WIFI` download/upload job |
| Recipient bound on several paths (Wi‑Fi + LoRa) | Push on every path; Dispatch stays `SENT` with a durable pending row until any device confirms (outbox poll, `MSG_ACK`, `MSG_PUSH` reply, `MSG_SYNC`); first confirm drops the other paths' copies |

## Assumptions

- Station remains the best canonical store when reachable.
- Pocket courier queues are bounded; TTL/expiry applies.
- Heltec 250B limit means progressive ops, not giant sync blobs.

## Open questions

- Single SQLite `sync_jobs` table vs per-service tables with a common view API?
- How aggressive is retry backoff on LoRa duty cycle?
- Who is allowed to see another user’s pending counts? (privacy)

## Deferred

- Cross-Station federation of queues ([federation-future.md](federation-future.md)).
- Full Fieldbook/Postbox adoption until Dispatch queue path is proven.
