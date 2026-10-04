# Waypost naming and terminology

Official user-facing names. Use these consistently in UIs, docs, and marketing. Internal code modules may use descriptive names (`mail`, `wiki`, `messaging`, `transport`) when that improves clarity.

Do **not** rename third-party software internally merely for branding (Stalwart remains Stalwart; BookStack remains BookStack). Adapters wrap them behind Waypost service names.

---

## Platform and infrastructure

| Name | Meaning |
|------|---------|
| **Waypost** | The complete ecosystem and network. Example: “Connect to the Waypost network.” |
| **Waypost Station** | The Raspberry Pi server: headquarters, archive, sync hub, recovery point, portal. The best-equipped peer — it enhances the network but does not create it; nothing else requires it to be up ([network-model.md](network-model.md)). |
| **Waypost Scout** | The LilyGO T-Deck handheld computer — a Cybiko-like personal device, not a LoRa terminal. Also a **mobile courier**: can carry/forward messages for peers when Station is unreachable. |
| **Waypost Outpost** | Autonomous ESP32 LoRa hop / coverage node (e.g. MakerHawk ESP32 LoRa V3). Always-on courier; not a Station and not a Pocket. |
| **Waylink** | The logical communications / transport layer. First implementation: Reticulum/LXMF. Transport-agnostic. |
| **Waygate** | Captive portal splash when joining Waypost Wi‑Fi — explains off‑grid / local-only access, then Continue to trust + sign-in (Station) or the Corkboard (Outpost). |
| **way.post** | Local DNS name for the Station portal when connected to `WAYPOST` Wi‑Fi (Pi dnsmasq → `10.42.0.1`). Not a public website — only resolves on-network. |
| **out.post** | Local DNS name for an Outpost Corkboard when connected to `WAYPOST-OUTPOST` Wi‑Fi (Outpost AP → `192.168.4.1`). Same local-only rules as `way.post`. |

---

## First-party applications

| Name | Purpose |
|------|---------|
| **Dispatch** | Instant messaging / group chat |
| **Postbox** | Email |
| **Rollcall** | People / profiles / contacts / presence — and on a Scout, **Nearby** (who and what is in range) |
| **Commons** | Community / social feed |
| **Fieldbook** | Editable community wiki |
| **Trailhead** | The Station's small web: short linked text pages, readable on a Scout over the radio |
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
| **Scout** | Short form for Waypost Scout when unambiguous |
| **Outpost** | Short form for Waypost Outpost when unambiguous |
| **Courier** | A **role**, not a product: any device that physically carries objects between places that can't otherwise reach each other (a Scout in a pocket, a laptop, a moved Outpost). "The Scout acted as courier." |
| **Object** | Anything the network syncs — a message, receipt, notice, Beacon event, wiki revision, identity certificate. Internal/design term ([network-model.md](network-model.md)). |
| **Community key** | The Station-held key that signs identity and device certificates and revocations. Design term; not an app. Identity has no app name — people see it through Rollcall and Settings. |
| **Pocket** | **Internal only** — device class in protocol, code, and DB (`pocket-*` node IDs, `PeerDispatchNode`, courier). Not the user-facing product name; the T-Deck product is **Waypost Scout**. |

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

**Pocket vs Scout:** firmware lives under `firmware/pocket/`, node IDs use the `pocket-` prefix, and server sims use `PeerDispatchNode` / “Pocket” in comments — that is intentional. UI, docs, and packaging say **Scout** / **Waypost Scout**.
