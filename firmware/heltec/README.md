# Heltec USB↔LoRa bridge firmware

Minimal firmware so a Heltec WiFi LoRa 32 **V3** on USB can ferry Waylink payloads between the Station host and the air.

## Proven on this project

Two Heltec WiFi LoRa 32 V3 (ESP32-S3) boards were flashed and verified:

```text
USB0 ──WP frame──► Heltec A ──LoRa 915──► Heltec B ──WP frame──► USB1
```

Bidirectional air test and Waylink `PING`/`PONG` succeeded.

Payload limit: **250 bytes** per LoRa frame (`MAX_FRAME` in firmware). Dispatch `MSG_*` CBOR fits; keep bodies short on-air.

## Frame format

```text
W P | uint32 big-endian length | payload
```

Special ASCII payloads: `ECHO` (USB loopback), `STAT` (status).

## Flash

```bash
cd firmware/heltec
pio run -e heltec_wifi_lora_32_V3 -t upload --upload-port /dev/ttyUSB0
pio run -e heltec_wifi_lora_32_V3 -t upload --upload-port /dev/ttyUSB1
```

Expect `WAYPOST_BRIDGE_READY` on serial after boot.

## Host tools

```bash
python -m tools.radio.ping --port /dev/ttyUSB0 echo
python -m tools.radio.ping --port /dev/ttyUSB0 stat
python -m tools.radio.airtest --tx /dev/ttyUSB0 --rx /dev/ttyUSB1

# Terminal A
python -m tools.radio.peer_pong --port /dev/ttyUSB1 --seconds 60
# Terminal B
python -m tools.radio.ping --port /dev/ttyUSB0 ping --dst peer
```

Signal portal: **Air test** button calls `POST /api/signal/airtest`.
