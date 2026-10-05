# Waypost Outpost — design

**Status:** design (2026-10-04), building on the working firmware in `firmware/outpost` (Heltec V3).
Model: [network-model.md](network-model.md). Hardware: [hardware/heltec-wifi-lora-32.md](hardware/heltec-wifi-lora-32.md),
[hardware/makerhawk-v3.md](hardware/makerhawk-v3.md).

An Outpost is **fixed local infrastructure that keeps working on its own**. It doesn't depend on
Station: it adds range, storage, and a place to take part for people with no Scout.

## What it does — and where each part stands

| Capability | Status |
|---|---|
| Reticulum transport node: forwards encrypted packets for others | ✅ hardware |
| Persistent device identity, OLED role label, button-toggled auto-claim | ✅ hardware |
| Wi-Fi AP `WAYPOST-OUTPOST` with captive portal; Corkboard read/post; walk-up Beacon report | ✅ hardware |
| Corkboard sync to Station (`BOARD_SYNC`), Beacon reports to Station (`BEACON_SYNC`), claim | ✅ hardware |
| **Object store** in flash (`/wp_objs`): signed messages, newest 300 kept | ✅ 2026-10-05 |
| **Certificates:** pins the community key, caches everyone's (`CERT_LIST`), revocations, looks up unknown authors | ✅ 2026-10-05 |
| **Peer sync** (`SYNC`, shared engine `firmware/common/waypost_core`) with Scouts, Outposts, Station; takes everything (`*`) | ✅ hardware |
| **Local delivery:** a new message for someone whose Scout synced here in the last 30 min is pushed to it at once | ✅ hardware (Station off) |
| **Announces itself** as an Outpost (`WPOST-OUTPOST:<id>`) so Scouts sync with it | ✅ hardware |
| **Wi-Fi Dispatch page** (`/msg`): sign in with username + password (key worked out in the browser), conversations, compose — one session per browser | ✅ built, page crypto verified against Python under Node; **real-phone test pending** |
| Corkboard notes survive power loss | 🔧 notes are still RAM-only |
| Local Noticeboard, cached Fieldbook pages | 📋 |
| **Beacon spread:** a walk-up Beacon alerts Scouts nearby directly as well as Station | 📋 (today only sends to Station) |

## Store and retention

Heltec V3: ~1.5 MB LittleFS free after firmware (measure). Budget, in priority order:
identity certs + revocations (small, always kept) → Beacon events (until expiry) → messages and
receipts for users seen here recently → objects being carried toward Station → Noticeboard for the
area → Fieldbook cache (evicted first). A carried object is dropped once Station's archive receipt is
seen, or at expiry; the Outpost's own Corkboard notes stay (Outpost-primary, as today).

## Uplinks

LoRa only (normal), Wi-Fi client / Ethernet to Station (Tier 2, later), Internet (never required),
or **none for weeks** — a Courier walking by is the uplink. The Outpost never assumes the uplink is up.

## Signing in without a Scout

**Decided 2026-10-05 (the human):** people sign in on the Outpost's Wi-Fi page with their **username
and password**, per browser session (several people at once). The page works out the identity key
in the browser (`web/wpcrypto.js`: scrypt-js + tweetnacl, vendored in `web/vendor/`), signs the
Outpost's one-time challenge, and keeps the key only in that tab's session — **the password never
reaches the Outpost**. Every message is signed in the browser with the person's own key, so it's
theirs, not "via Outpost". The Outpost refuses a sign-in whose key differs from the one Station
vouches for under that name (`wrong_password`); a name it has no certificate for signs in as "not
vouched for yet" (Station checks when the messages reach it).

Earlier options (sign-in codes, Scout vouching, an Outpost passcode) are superseded.

## Firmware structure (incremental)

`main.cpp` (AP, Corkboard, Beacon, claim, OLED) plus `outpost_net.*` (requests to any peer, queued
incoming SYNC, clock from Station), `outpost_objects.*` (store, certificates, sync scheduling,
pushes), `outpost_web.*` (the `/msg` page and its JSON API; assets gzipped into `src/web_assets.h` by
`tools/make_web_assets.py`). Shared with the Scout: `firmware/common/waypost_core` (Waylink codec,
certificates, signed objects, sync engine) ✅.
