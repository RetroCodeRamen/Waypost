# USB RNode (Station LoRa)

## Role

Dedicated LoRa mesh radio attached to the Waypost Station via USB. Preferred first implementation: **Reticulum + RNode-compatible** radio.

**In hand:** the project's two Heltec WiFi LoRa 32 V3 boards ([heltec-wifi-lora-32.md](heltec-wifi-lora-32.md)) are on the official RNode firmware list and are already flashed as RNodes (firmware 1.86, 915 MHz) — encrypted Dispatch over real LoRa passed 2026-09-22 ([radio-dev.md](../radio-dev.md#encrypted-over-real-lora-rnode)). No separate RNode purchase was needed to reach M2e; a dedicated RNode remains the target for the Pi Station once it's deployed.

## Persistent device alias

Do not depend on `/dev/ttyACM0` remaining stable.

Use a udev rule so Linux creates:

```text
/dev/waypost-lora
```

Example rule template: `deploy/raspberry-pi/udev/99-waypost-lora.rules`

Match on vendor/product/serial attributes for the specific RNode hardware in use (**verify VID/PID** for your device; placeholders in the repo rule must be updated).

## Software path

```text
Raspberry Pi → USB → RNode → Reticulum (RNodeInterface) → Waylink gateway → Waypost API
```

Reticulum configuration should reference `/dev/waypost-lora`, not a raw ACM index.

## Verification checklist

- [ ] Confirm VID/PID/serial for installed RNode  
- [ ] Confirm udev symlink after replug  
- [ ] Confirm Reticulum interface comes up after reboot  
- [ ] Confirm `PING`/`PONG` over air (Phase 2)
