# RNode firmware — Waypost fork (Station's board only)

Station's radio (`/dev/ttyUSB0`) runs this, not a Waypost-authored firmware.
[RNode Firmware](https://github.com/markqvist/RNode_Firmware) by Mark Qvist
is the reference LoRa modem firmware Reticulum's own `RNodeInterface`
speaks — Station's `ReticulumTransport` (`server/transports/reticulum.py`)
talks to it over the standard RNode KISS serial protocol exactly like any
other RNode. `UPSTREAM_README.md` is their own README, kept for reference.

**This is a vendored copy of upstream `master` (same version already
flashed — 1.86, `Config.h`'s `MAJ_VERS`/`MIN_VERS`), trimmed to just what's
needed to build the `heltec_wifi_lora_32_V3` target** (no `Documentation/`,
`Console/` web-UI assets, `Builds/` variant files for other boards, or
`Release/` prebuilt binaries — none of those are needed to compile this
target from source). License: GPL-3.0, `LICENSE` unchanged from upstream.

## The one change: a Waypost splash on a new button gesture

Requested 2026-09-23: "update the rnode screen to just show the waypost
logo when the action button is pushed." RNode's action button (GPIO0 on
this board) already has four duration-based behaviors — quick tap toggles
Bluetooth, ~0.7–5s hold sleeps the radio, ~5–10s hold starts BT pairing,
>10s starts the serial console (`button_event()` in `RNode_Firmware.ino`).
Rather than take over an existing gesture, this adds a new one in the gap:

| Hold duration | Action |
|---|---|
| quick tap | Bluetooth toggle (unchanged) |
| **~0.7–1.3s** | **show the Waypost logo for 3s (new)** |
| ~1.3–5s | sleep (was ~0.7–5s — shifted by ~0.6s to make room) |
| ~5–10s | BT pairing (unchanged) |
| >10s | serial console (unchanged) |

Full diff: `RNode_Firmware.ino`'s `button_event()` (new duration bucket
calling `trigger_waypost_logo()`) and `Display.h` (`draw_waypost_logo()`,
`trigger_waypost_logo()`, a `show_waypost_logo`/`show_waypost_logo_until`
timed flag checked in `update_display()` right alongside the existing
`recondition_display` flag it's modeled on). `WaypostLogo.h` is a 40x40
monochrome bitmap generated from `web/portal/static/brand/waypost-mark-256.png`
— **MSB-first bit order** for Adafruit_GFX's `drawBitmap()`, which is the
*opposite* of `firmware/{heltec,outpost}/src/waypost_mark.h`'s LSB-first
format for U8g2. Don't reuse one header's bytes with the other library.

The Heltec V3 panel is portrait after `setRotation` (64×128). The splash
uses `display.width()` / `display.height()`, not the 128×64 `DISP_W` /
`DISP_H` constants, and stacks a 56×56 tree mark over the word WAYPOST.
`WaypostLogo.h` is cropped from the brand mark without the side W.

Nothing else about RNode's radio/KISS-protocol behavior is touched — this
only adds a display gesture.

After flashing a new build, the OLED shows "firmware corrupt" until the
EEPROM hash matches the running image. Read it and write it back:

```bash
rnodeconf /dev/ttyUSB0 --get-firmware-hash
rnodeconf /dev/ttyUSB0 --firmware-hash <that-hash>
```

## Build

Uses `arduino-cli`, not PlatformIO (upstream's own toolchain — this is the
only firmware in this repo that doesn't use PlatformIO, since matching
their exact build process was safer than fighting the framework). Pinned
to Arduino ESP32 core **2.0.17** (`Makefile`'s `ARDUINO_ESP_CORE_VER`) —
this is what upstream release-tests against, not the 3.x core `firmware/
heltec` and `firmware/outpost` use via PlatformIO's espressif32 platform.

```bash
# One-time setup (arduino-cli + ESP32 core 2.0.17 + required libs)
arduino-cli core update-index --config-file arduino-cli.yaml
arduino-cli core install esp32:esp32@2.0.17 --config-file arduino-cli.yaml
arduino-cli lib install "Adafruit SSD1306" "Adafruit SH110X" \
  "Adafruit ST7735 and ST7789 Library" "Adafruit NeoPixel" \
  "XPowersLib" "Crypto" --config-file arduino-cli.yaml

# Build (matches upstream's `make firmware-heltec32_v3` target exactly)
arduino-cli compile --fqbn esp32:esp32:heltec_wifi_lora_32_V3 -e \
  --build-property "build.partitions=no_ota" \
  --build-property "upload.maximum_size=2097152" \
  --build-property 'compiler.cpp.extra_flags="-DBOARD_MODEL=0x3A"' \
  --config-file arduino-cli.yaml --output-dir ./build
```

## Flash

**`/dev/ttyUSB0` only — this is Station's live radio.** Stop Station first
(it holds the serial port open), flash, then restart Station and confirm
`/api/health` / a Signal check before considering it done.

```bash
arduino-cli upload -p /dev/ttyUSB0 --fqbn esp32:esp32:heltec_wifi_lora_32_V3 \
  --input-dir ./build --config-file arduino-cli.yaml
```

No `rnodeconf` round-trip needed afterward — this **is** RNode firmware
(same version, additive patch only), not a swap to different firmware
the way `firmware/heltec`'s plaintext bridge would be. Reticulum's
`RNodeInterface.validate_firmware()` only checks the self-reported
version number over serial (`RNS/Interfaces/RNodeInterface.py`), not a
firmware hash — confirmed before touching the live device — so this
patched-but-same-version build is accepted exactly like the stock binary.

## Regenerating `WaypostLogo.h`

```python
from PIL import Image
src = Image.open("web/portal/static/brand/waypost-mark-256.png").convert("RGBA")
SIZE = 40
bg = Image.new("RGBA", src.size, (255, 255, 255, 255))
comp = Image.alpha_composite(bg, src).convert("L").resize((SIZE, SIZE), Image.LANCZOS)
pixels = comp.load()
# MSB-first row-major bits, threshold ~150, pack 8 pixels/byte per row
```
See git history for the exact script if needed.
