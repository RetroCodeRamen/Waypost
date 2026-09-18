# ADR 0002 — Waylink transport abstraction

## Status

Accepted

## Context

Initial radio stack is Reticulum/LXMF, but Waypost must not hard-couple application services to Reticulum. Future transports (Meshtastic, MeshCore, packet radio, TCP, Internet gateway) should plug in.

## Decision

Introduce a `Transport` interface in Station (and mirrored concepts on Pocket):

- `send`, `receive` / async iterator  
- `reachable`  
- `get_route`  
- `get_link_quality`  

User-facing name remains **Waylink**.  

First implementations:

1. `MockTransport` — mandatory for development  
2. `ReticulumTransport` — production LoRa path  

Gateway maps compact RPC envelopes to/from transports without leaking transport types into service adapters.

## Alternatives

| Option | Why rejected |
|--------|----------------|
| Call Reticulum/LXMF from every service | Irreversible coupling |
| Treat LoRa as IP/VPN only | Wrong bandwidth model; HTML-over-LoRa temptation |
| Custom routing stack on Outposts | Prefer adapting existing Reticulum transport-node firmware |

## Consequences

- Apps speak logical ops (`MAIL_LIST`, `MSG_SEND`, …), not radio frames.  
- Tests can run without hardware.  
- Adding a transport means a new adapter + config, not rewriting Postbox/Dispatch.
