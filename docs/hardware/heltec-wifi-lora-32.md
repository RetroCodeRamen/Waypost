# Heltec WiFi LoRa 32 — USB-connected development radios

## Observed on this project

Two Heltec boards with **Silicon Labs CP2102** USB-UART bridges appear as:

| Kernel device | Stable by-path symlink |
|---------------|------------------------|
| `/dev/ttyUSB0` | `/dev/serial/by-path/pci-…-usb-0:2.3:1.0-port0` |
| `/dev/ttyUSB1` | `/dev/serial/by-path/pci-…-usb-0:3:1.0-port0` |

USB IDs: `10c4:ea60` (CP210x). Both boards often report serial `0001`, so **do not** rely on `by-id` alone — use **by-path** or numbered Waypost aliases.

## Proven on this project

Two Heltec WiFi LoRa 32 **V3** (ESP32-S3 + SX1262) boards:

| Port | Role |
|------|------|
| `/dev/ttyUSB0` | Station-side radio |
| `/dev/ttyUSB1` | Peer / Pocket stand-in |

Flashed with `firmware/heltec`. Verified: USB `ECHO`/`STAT`, bidirectional LoRa payload relay, Waylink `PING`→`PONG`.

## Role in Waypost

| Board | Suggested role |
|-------|----------------|
| Heltec A (USB → Station host) | Station-side LoRa radio stand-in until a dedicated RNode is attached |
| Heltec B (USB or battery) | Pocket / Outpost stand-in for air tests |

Production Station path remains **RNode + Reticulum** (`/dev/waypost-lora`). Heltec USB boards are the **laptop vertical slice** for Phase 2.

**Update (2026-09-22):** these same two boards *are* the RNode hardware now — Heltec WiFi LoRa 32 V3 is on the official RNode firmware list, so no separate radio purchase was needed for M2e. Both were reflashed with `rnodeconf --autoinstall` (firmware 1.86, 915 MHz) — see [radio-dev.md](../radio-dev.md#encrypted-over-real-lora-rnode) and [usb-rnode.md](usb-rnode.md). This **replaces** the Waypost Heltec bridge firmware below; getting the plaintext lab bridge back requires a PlatformIO reflash of `firmware/heltec`.

## udev aliases

See `deploy/raspberry-pi/udev/99-waypost-lora.rules`.

After install + replug:

```text
/dev/waypost-lora      → first Heltec (Station radio)
/dev/waypost-lora-b    → second Heltec (peer / Pocket stand-in)
```

```bash
sudo cp deploy/raspberry-pi/udev/99-waypost-lora.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/waypost-lora*
```

## Host probe

```bash
uv pip install pyserial
python -m tools.radio.list_devices
```

## Firmware

Scaffold: `firmware/heltec/` (PlatformIO). Flashes a USB↔LoRa bridge that speaks length-prefixed CBOR Waylink envelopes over serial at **115200**.

Until firmware is flashed, serial ports open but stay silent — that is expected.

## Pin notes (Heltec WiFi LoRa 32 **V3** — verify silk on your board)

Common V3 (ESP32-S3 + SX1262) mapping used by many sketches — **confirm on your revision**:

| Function | GPIO (typical V3) |
|----------|-------------------|
| LoRa NSS | 8 |
| LoRa SCK | 9 |
| LoRa MOSI | 10 |
| LoRa MISO | 11 |
| LoRa RST | 12 |
| LoRa BUSY | 13 |
| LoRa DIO1 | 14 |
| OLED SDA / SCL | 17 / 18 |

V2 boards use SX127x and different pins — select `heltec_wifi_lora_32_V2` in PlatformIO if that is what you have.

## Regulatory

US 915 MHz ISM for initial tests. Configure region in firmware / Reticulum; no continuous-transmit loops.
