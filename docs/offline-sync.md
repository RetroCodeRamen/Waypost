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
- Pocket courier queues are bounded; TTL/expiry applies (`DispatchStore.purge_expired_courier`, swept opportunistically on `flush_pending`/`handoff_to`/`sync_with_station` — default `COURIER_TTL_SECONDS` in `server/services/dispatch/peer.py`, 24h). A courier holds plaintext of messages it isn't a party to, so this bounds exposure as well as storage growth.
- Device-to-device relay hops (travel device → travel device, i.e. `PeerDispatchNode.handoff_to`) are capped at `MAX_COURIER_HOPS` (3) — a message can still be delivered directly or synced to Station regardless of hop count, it just can't be handed to a 4th travel device. **`OutpostNode` (`server/services/dispatch/outpost.py`) is exempt from this cap** — fixed, always-on infrastructure, not a battery-constrained Pocket — and relays uncapped both toward Station (with preferred-route caching — find the shortest known path, keep using it while it works, rediscover if it stops) and between Outposts. Sim-tested (`server/tests/test_mesh_dispatch.py`); a first real-hardware attempt (two RNode-flashed Heltec V3 boards standing in for Station + one Outpost — `tools/radio/outpost_airtest.py`) got one full round trip through and surfaced two real transport-layer bugs (now fixed: `ReticulumTransport.get_route`/`reachable` never resolved logical node_ids to RNS hashes, and Station never learned an Outpost's hash without an explicit bind), but hasn't reproduced reliably since — likely RF/timing, not application logic; see `AGENT_HANDOFF.md` for the open thread.
- Heltec 250B limit means progressive ops, not giant sync blobs.

## Open questions

- Single SQLite `sync_jobs` table vs per-service tables with a common view API?
- How aggressive is retry backoff on LoRa duty cycle?
- Who is allowed to see another user’s pending counts? (privacy)

## Deferred

- Cross-Station federation of queues ([federation-future.md](federation-future.md)).
- Full Fieldbook/Postbox adoption until Dispatch queue path is proven.
