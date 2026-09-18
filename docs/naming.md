# Waypost naming and terminology

Official user-facing names. Use these consistently in UIs, docs, and marketing. Internal code modules may use descriptive names (`mail`, `wiki`, `messaging`, `transport`) when that improves clarity.

Do **not** rename third-party software internally merely for branding (Stalwart remains Stalwart; BookStack remains BookStack). Adapters wrap them behind Waypost service names.

---

## Platform and infrastructure

| Name | Meaning |
|------|---------|
| **Waypost** | The complete ecosystem and network. Example: “Connect to the Waypost network.” |
| **Waypost Station** | The Raspberry Pi server that hosts community services. Central but not required for every peer-to-peer function. |
| **Waypost Pocket** | The LilyGO T-Deck handheld computer — a Cybiko-like personal device, not a LoRa terminal. Also a **mobile courier**: can carry/forward messages for peers when Station is unreachable. |
| **Waypost Outpost** | Autonomous ESP32 LoRa hop / coverage node (e.g. MakerHawk ESP32 LoRa V3). Always-on courier; not a Station and not a Pocket. |
| **Waylink** | The logical communications / transport layer. First implementation: Reticulum/LXMF. Transport-agnostic. |
| **Waygate** | Captive portal and browser entry point when joining Waypost Wi-Fi. |

---

## First-party applications

| Name | Purpose |
|------|---------|
| **Dispatch** | Instant messaging / group chat |
| **Postbox** | Email |
| **Rollcall** | People / profiles / contacts / presence |
| **Commons** | Community / social feed |
| **Fieldbook** | Editable community wiki |
| **Noticeboard** | Structured bulletins and announcements |
| **Beacon** | Emergency / high-priority alerts |
| **Locker** | Shared and personal files |
| **Archive** | Offline reference library / Kiwix content |
| **Atlas** | Maps: Station camp origin, Pocket positions, range/distance |
| **Finder** | Global / federated search |
| **Logbook** | Notes / journal |
| **Planner** | Calendar / tasks / organizer |
| **Workshop** | Installed applications and tools |
| **Arcade** | Games |
| **Signal** | Radio / network diagnostics |
| **Control** | Settings |

---

## Related concepts

| Term | Notes |
|------|-------|
| **Profile** | User’s personal profile; may live under Rollcall or status UI. Preferred web path: `/~username` |
| **Station** | Short form for Waypost Station when unambiguous |
| **Pocket** | Short form for Waypost Pocket when unambiguous |
| **Outpost** | Short form for Waypost Outpost when unambiguous |

Former name **Relay** is retired — use **Outpost** in all user-facing and plan docs. Internal verbs (“relays a packet”) are fine; the product/node type is Outpost.

---

## Distinctions to preserve

- **Commons** ≠ **Noticeboard** — social posts vs structured bulletins.
- **Noticeboard** ≠ **Beacon** — normal announcements vs emergency broadcasts.
- **Fieldbook** ≠ **Archive** — editable community knowledge vs imported reference content.
- **Waylink** ≠ IP networking — compact RPC over radio, not HTML over LoRa.
- Device radio identity ≠ Waypost account username — link via pairing.

---

## Internal identifiers (protocol / code)

Protocol service IDs may be concise (`MAIL`, `FIELDBOOK`, `DISPATCH`). User-facing labels stay branded (`Postbox`, `Fieldbook`, `Dispatch`).
