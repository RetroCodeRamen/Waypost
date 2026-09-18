# Network time

**Status:** Design now · no public NTP assumed off-grid.

---

## Requirements

Station provides **network time** to Pockets and Outposts.

Affects: Dispatch timestamps, Postbox, Notice/Beacon expiry, logs, Fieldbook revisions, certificates, scheduling, Atlas fix timestamps.

## Assumptions

- Station clock is the camp authority (RTC and/or operator set; GPS time later if Station gains a receiver or trusts a Pocket fix’s time carefully).
- Devices may be wrong after long power-off; skew must be detectable.

## Expected behavior

- Pocket/Outpost fetch time from Station when any path exists (Wi‑Fi preferred; compact Waylink time op later).
- If clocks disagree beyond threshold: trust Station for server-side expiry; show warning on device; do not silently accept ancient Beacon as fresh.

## Open questions

- Dedicated `TIME_GET` / `TIME_SET` Waylink ops vs piggyback on `SIGNAL_STATUS`?
- How to bootstrap Station clock with no GPS and no Internet (operator UI)?
- Signed time responses?

## Deferred

- Full PKI dependency on perfect time
- GPS-disciplined Station clock productization
