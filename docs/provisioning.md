# Provisioning

**Status:** Required product feature · UX not built · avoid architectures that make enroll painful.

---

## Requirements

### Pocket (future)

```text
Welcome to Waypost
Found: WAYPOST
[Join]
Pairing code: 482193
```

- Discover Station Wi‑Fi / Waygate
- Pair radio identity to account
- Region / radio settings without editing firmware source per unit
- Show firmware version; support revocation

### Outpost (future)

- Unique identity + config at enroll time
- Station association
- No per-device source edits for channel/keys

### Dev today

`tools/provisioning/bootstrap-dev.sh` only creates local data dirs — **not** product provisioning.

## Assumptions

- First camps: single Station SSID `WAYPOST`.
- Pairing codes are short-lived and rate-limited ([security.md](security.md)).

## Open questions

- QR vs numeric code vs NFC?
- Factory vs field flash for Outposts?
- Offline Outpost enroll when Station is down?

## Deferred

- Polished join UX until Pocket shell exists.
- Multi-Station picker ([federation-future.md](federation-future.md)).
