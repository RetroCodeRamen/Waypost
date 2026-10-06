# Camp demo — acceptance test T1 / T2

Scripted demo for **“no device is strictly necessary”** ([network-model.md](network-model.md)). Run when hardware is on the Pi Station ([pi-ops.md](pi-ops.md)).

**Hardware:** Pi Station + RNode, one Heltec Outpost, one T-Deck Scout (`firmware/scout`).

---

## Prep (once)

1. Pi Station up — `./tools/pi/health-check.sh` green.
2. Scout flashed: `cd firmware/scout && pio run -e tdeck -t upload --upload-port /dev/ttyACM0`
3. Outpost on `/dev/ttyUSB1` (or lab port).
4. Scout signed in (username + password on device); portal accounts exist for test users.
5. `./tools/pi/pull-backup.sh` — snapshot before demo.

---

## T1 — Station unplugged, network still works

Goal: Scouts + Outpost form a useful network without the Pi.

1. **Power off the Pi** (or unplug Ethernet and stop `waypost-api` — Outpost may still route if it cached paths; full test uses Pi off).
2. On **Scout A**, compose a Dispatch message to a contact (or use a stand-in peer at the Outpost per lab notes in `AGENT_HANDOFF.md`).
3. **Expected:** message shows locally (`(waiting)` or delivered via Outpost push); Outpost `/msg` Wi‑Fi page can receive/send for signed-in browsers if in range.
4. Optional: raise a **Beacon** on Scout A — Scout B or Outpost should show it when in sync range.

**Pass:** at least one message moves Scout ↔ Outpost or Scout ↔ Scout with no Station API.

---

## T2 — Station returns, network reconciles

1. **Power Pi back on**; wait for `waypost-api` + RNode (`./tools/pi/health-check.sh`).
2. Scout on Wi‑Fi or LoRa path to Station — catch-up runs automatically (every ~3 min + on path found).
3. **Portal:** sign in at `https://way.post`, open Dispatch — messages from the outage appear, signed where applicable.
4. **Expected:** no manual re-pairing; `DELIVERED` / delivery receipts where built.

**Pass:** offline traffic visible on Station without reconfiguration.

---

## T3 — add a device, nothing breaks

1. Note Scout destination hash (Signal app or serial).
2. Register/bind a **new** device in portal **Devices** (or let Outpost auto-claim).
3. **Expected:** existing Scouts/Outposts unchanged; new device adds capability only.

---

## Quick smoke (5 min)

If you only have time for one path:

1. Send Dispatch message Scout → portal user over LoRa (Station up).
2. Unplug Pi 30 s, send another message (queues locally).
3. Plug Pi back, confirm both messages in portal within ~5 min.

---

## Troubleshooting

| Symptom | Check |
|---------|--------|
| Scout “no path” | RNode on Pi: `ls -l /dev/waypost-lora`; Outpost powered; same LoRa params |
| Portal empty after outage | Scout signed in? catch-up in serial; Station logs `SYNC` / `MSG_SYNC` |
| Outpost not pushing | Claimed in DB? Scout announced recently? |

See [radio-dev.md](radio-dev.md) and [pi-ops.md](pi-ops.md).
