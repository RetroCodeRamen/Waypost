# Mesh delivery — messages find people without waiting for Station

**Status:** design (2026-10-04). Proven in simulation (`server/services/dispatch/peer.py`,
`server/services/dispatch/outpost.py`, `server/tests/test_mesh_dispatch.py`); **not yet on
hardware**. Builds on the comms rule in [roadmap.md](roadmap.md) and the store-and-forward
rules in [architecture.md](architecture.md#pocketpocket-and-store-and-forward).

**Refined 2026-10-04 by [network-model.md](network-model.md):** this doc's messaging rules stand, but
"Station is the memory" now means Station is the *archive*, not a step that delivery waits on.
Messages are signed objects synced peer to peer by the general `SYNC_*` protocol. The signature
check uses offline certificates ([identity.md](identity.md#offline-identity-target)) instead of
`ROLL_LIST` hashes. The build order below is folded into roadmap track **D**.

## What the human asked for (2026-10-04)

> I want all messages to be stored by the Station as like a memory, a history, all of that. But
> I also want the T-Deck devices to live retrieve their messages and also accept a message
> that's on its way to the Station if it was meant for them, while still making the message go
> back to the Station.
>
> Someone logged into an Outpost can get a message from a device directly and can respond
> directly without having to go all the way back to the Station and then back down the path.
> And devices that are logged in and see a message that was meant for them pick up that message
> and give it to the user logged in.

Decisions (asked 2026-10-04):

- **"Logged into an Outpost" means both** a Scout whose nearest hop is that Outpost, *and* a
  person on the Outpost's Wi-Fi signed in with their Waypost account on its web page.
- **Relays may read what they carry** (Outposts, Scouts acting as couriers). Messages are
  **signed** so the sender can't be faked; Station keeps readable history for the portal. This is
  the existing model in [security.md](security.md) ("bounded transient hold"). End-to-end
  encryption to the recipient was offered and not chosen for now.

## The rules

1. **Station is the memory.** Every message ends up in Station's history, whichever way it
   travelled. Copies converge by message id (`mid`); duplicates are dropped everywhere.
2. **Deliver at the first node that can.** Any node holding a message (Outpost, Scout, Station)
   that has the recipient *local* — their Scout in range, or them signed in on the Outpost's
   Wi-Fi — delivers it right away.
3. **…and still forward it.** Local delivery never ends the message's trip: the node keeps a
   copy and carries it on toward Station until Station (or the next hop toward it) confirms.
4. **Replies take the short way back.** A reply from a local recipient goes straight back
   through the same Outpost/Scout to the sender, and *also* toward Station.
5. **Live where possible, catch-up always.** Devices get messages pushed as they arrive, and
   still sync (`MSG_SYNC`) whenever they reach Station or a courier, so nothing depends on a
   single push arriving.

## The constraint that shapes it

Reticulum encrypts each packet for its destination only. A Scout or Outpost that *hears* a
packet addressed to Station cannot read it — so "picking up a message on its way to Station"
can't mean eavesdropping. Instead messages travel **hop by hop at the Waylink level**: each hop
receives the message addressed to *itself*, decides (deliver locally? forward where?), and sends
it on. This is the courier model the simulators already use.

```text
Scout A ──► Outpost ──► Station          (Station stores; history converges)
              │
              ├──► Scout B in range       (delivered now; B's reply comes straight back)
              └──► phone on Outpost Wi-Fi (signed in; reads and replies on the Outpost page)
```

## What each node needs

**Message envelope (all nodes).** `mid`, sender, recipient(s), conversation id, body, sent time,
and a **signature** by the sender's device identity over those fields. Every hop and Station
verify it against the sender's known Scout identity (from `ROLL_LIST`'s destination hashes /
Reticulum's identity store), so a relay can't forge or alter a message. Bodies stay ≤140 bytes so
one signed message fits one packet.

**Station.** Already the canonical store. Adds: verify signatures on device-originated messages,
accept copies from couriers (`MSG_SYNC` already dedups by `mid`), and tell Outposts which users'
Scouts exist (a directory like `ROLL_LIST`, so an Outpost knows who it can deliver to).

**Outpost (firmware).** A Dispatch courier, not just a Reticulum relay:
- receive messages addressed to it; deliver to a recipient whose Scout is in range (seen via
  announces) or who is signed in on its Wi-Fi; queue the rest; forward everything toward Station;
- keep a bounded, power-safe queue in flash (survives restarts — an M6 exit criterion);
- a Wi-Fi **Dispatch page** for signed-in people (inbox + reply), alongside Corkboard/Beacon.

**Scout (firmware).** Messages stored on the device (history works out of range), an outbox that
sends when any path appears, direct Scout-to-Scout delivery, and a courier queue for messages it
carries for others (capped hops, TTL — see [offline-sync.md](offline-sync.md)).

## Signing in on an Outpost's Wi-Fi (open design)

An Outpost has no account database and may be out of reach of Station, and passwords must never
cross LoRa ([security.md](security.md)). Candidate design, to settle before building:

- **One-time sign-in code:** the person gets a short code from their Scout or the portal (like a
  pairing code), types it on the Outpost page; the Outpost checks it with Station over LoRa once
  and receives a **Station-signed session** for that user, valid for some hours. The session keeps
  working while Station is unreachable.
- The Outpost never sees or stores a password; the session is scoped to that Outpost and expires.

Open questions: session lifetime; what a person sees when the Outpost has never reached Station;
whether a Scout physically present can vouch for its owner's sign-in instead of a code.

## Build order

This expands step 3 of the Scout plan (see `AGENT_HANDOFF.md`, 2026-10-04 review). Step 2 — the
Scout keeping its own message store and an outbox — comes first, because a courier needs somewhere
to keep what it carries.

1. ✅ (2026-10-04, D3) **Signed message envelope** (Station verifies; Scout signs) — shared canonical bytes pinned by
   a test, Python and C++.
2. **Scout-to-Scout direct** when Station is out of reach, with the copy synced to Station later.
3. **Outpost courier on hardware:** deliver to Scouts in range, forward everything, replies take
   the short way back; flash-backed queue.
4. **Outpost Wi-Fi Dispatch page** with the sign-in design above.
5. **Scout as courier** for messages it carries for others.

**Testing:** steps 1 and 3 can be tested with the hardware on hand (Station RNode, Outpost, one
T-Deck). True Scout-to-Scout needs a **second T-Deck**; until then a Python stand-in Scout on the
Station's radio (Station stopped) can play the other side.
