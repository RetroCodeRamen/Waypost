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

Station: `WAYPOST_TRANSPORT=reticulum` (config under `data/reticulum/` or `WAYPOST_RNS_CONFIG`; swap AutoInterface/TCP for RNodeInterface for production LoRa).

## Related

- `python -m tools.radio.airtest` — raw framed echo over air  
- `python -m tools.radio.peer_pong` / `ping` — Waylink `PING`/`PONG`  
- [firmware/heltec/README.md](../firmware/heltec/README.md)
- [security.md](security.md) encryption matrix
