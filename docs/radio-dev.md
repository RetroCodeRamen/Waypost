# Radio-dev runbook (Heltec)

Laptop Station + two Heltec WiFi LoRa 32 **V3** boards as USB↔LoRa bridges.

## Ports

| Role | Typical device |
|------|----------------|
| Station bridge | `/dev/ttyUSB0` |
| Peer bridge | `/dev/ttyUSB1` |

Optional udev symlink: `/dev/waypost-lora` → Station bridge (see hardware notes).

## One-shot smoke

```bash
# Free ports; flash only if firmware changed
python -m tools.radio.ping --port /dev/ttyUSB0 echo
python -m tools.radio.ping --port /dev/ttyUSB1 echo

# Terminal A — Station
WAYPOST_TRANSPORT=serial WAYPOST_LORA_DEVICE=/dev/ttyUSB0 \
  uvicorn server.api.main:app --host 127.0.0.1 --port 8000

# Terminal B — E2E Dispatch over LoRa
python -m tools.radio.dispatch_airtest --peer-port /dev/ttyUSB1
python -m tools.radio.dispatch_airtest --appear-later --peer-port /dev/ttyUSB1
```

Expect: `PASS: M2c…` and `PASS: N1 opportunistic Dispatch (appear-later)`.

Signal → **Sync** shows Dispatch waiting while a peer is unbound.

## Interactive peer

```bash
python -m tools.radio.radio_pocket --port /dev/ttyUSB1 --user bob --peer aj
```

Bind uses HTTP (`/api/dispatch/devices/bind`); chat frames go over LoRa. Peer `node_id` must start with `radio-` so Station air-pushes replies (HTTP outbox still used for `pocket-*` / portal bindings).

## Limits

- Firmware `MAX_FRAME` = **250** bytes (SX1262). Keep on-air bodies short.
- Envelope IDs are 16 hex chars; `MSG_SEND` ACKs and `MSG_PUSH` are compacted for LoRa.
- `MSG_LIST` over radio returns at most 3 rows.
- **Heltec LoRa is plaintext** — lab stand-in only. Production encryption = **M2e Reticulum**.

## M2e — Encrypted Waylink (Reticulum)

Same-host lab (TCP; AutoInterface is one-per-host):

```bash
# Terminal A — listen
PYTHONUNBUFFERED=1 python -m tools.radio.reticulum_ping --role listen \
  --config /tmp/wp-rns-a --port 37801 --tcp-port 4242

# Terminal B — send (hash from A)
PYTHONUNBUFFERED=1 python -m tools.radio.reticulum_ping --role send \
  --config /tmp/wp-rns-b --port 37811 --tcp-port 4242 --to <hash-from-A>
```

Expect: `RECV encrypted payload: 'WAYPOST_M2E'`.

### Dispatch over Reticulum (encrypted)

```bash
# Terminal A — Station
WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=tcp_server \
  WAYPOST_RNS_TCP_PORT=4242 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station \
  WAYPOST_RNS_PORT=37429 \
  uvicorn server.api.main:app --host 127.0.0.1 --port 8000

# Terminal B — peer Dispatch
python -m tools.radio.dispatch_rns_airtest
# or interactive:
# python -m tools.radio.reticulum_pocket --user bob --peer aj
```

Expect: `PASS: M2e Dispatch over Reticulum (encrypted TCP lab)`.

Bind includes `transport_dest` (peer RNS hash) so Station can push encrypted `MSG_PUSH` replies. Node ids use `rns-*` prefix for air TX (like `radio-*` for Heltec).

Station: `WAYPOST_TRANSPORT=reticulum` (config under `data/reticulum/` or `WAYPOST_RNS_CONFIG`).

### Encrypted over real LoRa (RNode)

**PASS 2026-09-22** on two Heltec WiFi LoRa 32 **V3** boards flashed with RNode firmware 1.86 (US 915 MHz). Flashing **replaces** the Waypost Heltec bridge firmware, so the plaintext `serial` lab above needs `firmware/heltec` reflashed with PlatformIO.

```bash
# Flash each board. Interactive; answers for Heltec V3 on US 915 in rnodeconf 1.5.x:
#   8 (Heltec LoRa32 v3) → Enter (experimental notice) → 3 (915 MHz) → y
rnodeconf /dev/ttyUSB0 --autoinstall
rnodeconf /dev/ttyUSB0 --info   # verify; repeat for /dev/ttyUSB1
```

```bash
# Terminal A — Station on board 1
WAYPOST_TRANSPORT=reticulum WAYPOST_RNS_INTERFACE=rnode \
  WAYPOST_LORA_DEVICE=/dev/ttyUSB0 WAYPOST_RNS_CONFIG=/tmp/wp-rns-station-rnode \
  uvicorn server.api.main:app --host 127.0.0.1 --port 8000

# Terminal B — peer Dispatch on board 2
python -m tools.radio.dispatch_rns_airtest --rnode /dev/ttyUSB1
```

Expect: `PASS: M2e Dispatch over Reticulum (encrypted, RNode LoRa /dev/ttyUSB1)`. Signal shows **Security: encrypted (Reticulum)** and the radio settings.

Radio settings come from env and **must match on every node**:

| Env | Default | Notes |
|-----|---------|-------|
| `WAYPOST_RNS_FREQUENCY` | `915000000` | Hz. US 902–928 MHz ISM; use 868 MHz band in EU — check local rules |
| `WAYPOST_RNS_BANDWIDTH` | `125000` | Hz |
| `WAYPOST_RNS_TXPOWER` | `14` | dBm, 0–22 |
| `WAYPOST_RNS_SF` | `8` | Spreading factor 5–12 (higher = longer range, slower) |
| `WAYPOST_RNS_CR` | `5` | Coding rate 4/5 … 4/8 |

The config file is written once; delete `$WAYPOST_RNS_CONFIG/config` after changing interface or radio settings.

## Related

- `python -m tools.radio.airtest` — raw framed echo over air  
- `python -m tools.radio.peer_pong` / `ping` — Waylink `PING`/`PONG`  
- [firmware/heltec/README.md](../firmware/heltec/README.md)
- [security.md](security.md) encryption matrix
