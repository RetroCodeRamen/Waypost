# USB RNode (Station LoRa)

## Role

Dedicated LoRa mesh radio attached to the Waypost Station via USB. Preferred first implementation: **Reticulum + RNode-compatible** radio.

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
