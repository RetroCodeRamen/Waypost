# ADR 0001 — Waypost Scout (Pocket) runtime

## Status

Accepted, decided (2026-10-02, updated 2026-10-03): **option B in practice** — the same vendored **microReticulum + lora_interface** stack as `firmware/outpost/` underneath, with our own Arduino + TFT_eSPI UI on top, not a third-party T-Deck mesh firmware base. The reply round trip that looked blocked was two bugs, both fixed: the embedded radio driver's split-frame format didn't match real RNode (`3586bfb`), and Scout rejected PONG for lacking `ok` (`192a32a`). Dispatch, Fieldbook, Trailhead, and Signal now run over real LoRa (`ce23568`) — see [scout.md](../hardware/scout.md).

## Context

**Waypost Scout** is the T-Deck product; **Pocket** is the internal device class (protocol node IDs, server sims). The Scout needs keyboard, display, Wi-Fi, LoRa, Reticulum/LXMF, and eventually a Cybiko-like application shell. Two broad approaches exist:

**A.** Build upon an existing T-Deck Reticulum / mesh UI firmware  
**B.** Native ESP-IDF + LVGL (or similar) with Reticulum integrated underneath  

## Decision

Originally: for the first working prototype, prefer adapting a proven Reticulum-capable T-Deck base **if** it could support our Dispatch slice without fighting the architecture.

**Chosen:** no third-party base. microReticulum was already proven on the Outpost, so the Scout reuses it and draws its own UI with TFT_eSPI (an off-screen canvas in PSRAM, pushed row by row). LVGL was not needed for the current launcher-and-lists UI.

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
