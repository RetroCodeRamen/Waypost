# ADR 0001 — Waypost Pocket runtime

## Status

Proposed (research required before Phase 2/8 commitment)

## Context

The Waypost Pocket (LilyGO T-Deck) needs keyboard, display, Wi-Fi, LoRa, Reticulum/LXMF, and eventually a Cybiko-like application shell. Two broad approaches exist:

**A.** Build upon an existing T-Deck Reticulum / mesh UI firmware  
**B.** Native ESP-IDF + LVGL (or similar) with Reticulum integrated underneath  

## Decision

For the **first working prototype**, prefer adapting a proven Reticulum-capable T-Deck base **if** it can support our Dispatch vertical slice without fighting the architecture. Document the chosen base when selected.

Long term, **UI quality and application architecture** (Workshop, launcher, local-first apps) outweigh loyalty to any firmware base. Revisit this ADR before Phase 8.

## Alternatives

| Option | Pros | Cons |
|--------|------|------|
| Existing Reticulum T-Deck firmware | Faster radio/LXMF path | May constrain shell/app model |
| Clean ESP-IDF + LVGL | Full control of Cybiko UX | More work to reintegrate Reticulum |
| Micropython / other | Rapid UI iteration | Risk for radio timing / memory |

## Consequences

- Phase 2 success is Dispatch over LoRa, not a finished shell.  
- Avoid thousands of lines of untested custom UI before transport works.  
- Lua Workshop sandbox is deferred; design manifests/APIs now, implement later.
