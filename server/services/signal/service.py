"""Signal — radio / network diagnostics."""

from __future__ import annotations

import time
from typing import Any, Optional

from shared.protocol.envelope import Envelope, Flags

OP_SIGNAL_STATUS = "SIGNAL_STATUS"
OP_SIGNAL_ROUTE = "SIGNAL_ROUTE"


class SignalService:
    def __init__(self, app_state_getter) -> None:
        """app_state_getter: callable returning the FastAPI app.state-like object."""
        self._get_state = app_state_getter

    def status(self) -> dict[str, Any]:
        state = self._get_state()
        settings = state.settings
        transport = getattr(state, "transport", None)
        gateway = getattr(state, "gateway", None)
        db = state.db
        rollcall = state.rollcall
        beacon = state.beacon

        people = rollcall.list_people()
        online = [
            p
            for p in people
            if p
            and (
                "wifi" in (p.get("reachability") or "")
                or "lora" in (p.get("reachability") or "")
            )
        ]
        nodes = []
        try:
            rows = db._conn.execute(
                "SELECT node_id, username FROM device_bindings ORDER BY node_id"
            ).fetchall()
            nodes = [{"node_id": r["node_id"], "username": r["username"]} for r in rows]
        except Exception:
            nodes = []

        transport_name = getattr(transport, "name", None) or settings.waypost_transport
        gateway_handlers = 0
        if gateway is not None:
            gateway_handlers = len(getattr(gateway, "_handlers", {}) or {})

        active_beacon = beacon.get_active()

        radios: list[dict[str, Any]] = []
        try:
            from tools.radio.list_devices import list_radio_devices

            radios = list_radio_devices()
        except Exception:
            radios = []

        note = "Mock transport — no radio hardware."
        if transport_name == "mock" and radios:
            note = (
                f"Mock transport active, but {len(radios)} USB serial radio(s) detected. "
                "Set WAYPOST_TRANSPORT=serial and WAYPOST_LORA_DEVICE=/dev/waypost-lora "
                "after flashing Heltec bridge firmware."
            )
        elif transport_name in ("serial", "serial_bridge", "heltec"):
            note = f"USB serial bridge on {getattr(settings, 'waypost_lora_device', None)}"
        elif transport_name in ("reticulum", "rns", "lora"):
            note = "Reticulum encrypted Waylink (M2e)"
        elif transport_name != "mock":
            note = "Radio path configured."

        rns_hash = None
        if transport is not None and hasattr(transport, "destination_hash_hex"):
            rns_hash = getattr(transport, "destination_hash_hex", None)

        encrypted = transport_name in ("reticulum", "rns", "lora")
        rns_interface = getattr(transport, "interface", None) if encrypted else None
        if encrypted:
            security = "encrypted (Reticulum)"
        elif transport_name == "mock":
            security = "none (mock, no radio)"
        else:
            security = "PLAINTEXT — lab only, not private"
        rnode = getattr(transport, "rnode", None) if rns_interface == "rnode" else None
        rnode_info = (
            {
                "port": rnode.port,
                "frequency_mhz": rnode.frequency / 1_000_000,
                "bandwidth_khz": rnode.bandwidth / 1000,
                "txpower_dbm": rnode.txpower,
                "spreadingfactor": rnode.spreadingfactor,
                "codingrate": rnode.codingrate,
            }
            if rnode is not None
            else None
        )

        sync: dict[str, Any] = {
            "pending_dispatch": 0,
            "pending_by_user": {},
            "outbox_depth": 0,
            "waiting_nodes": [],
        }
        dispatch = getattr(state, "dispatch", None)
        if dispatch is not None and hasattr(dispatch, "sync_status"):
            sync = dispatch.sync_status()

        return {
            "status": "ok",
            "checked_at": time.time(),
            "station": {
                "name": "Waypost Station",
                "env": settings.waypost_env,
                "ssid": settings.waypost_ssid,
                "domain": settings.waypost_domain,
                "registration_mode": settings.waypost_registration_mode,
            },
            "waylink": {
                "transport": transport_name,
                "device": getattr(settings, "waypost_lora_device", None),
                "gateway_running": bool(
                    gateway and getattr(gateway, "_task", None) is not None
                ),
                "handlers": gateway_handlers,
                "encrypted": encrypted,
                "security": security,
                "rns_interface": rns_interface,
                "rns_hash": rns_hash,
                "rnode": rnode_info,
                "note": note,
                "radios": radios,
                "radios_detected": len(radios),
            },
            "network": {
                "users_total": len(people),
                "users_online": len(online),
                "bound_nodes": nodes,
                "outposts_online": 0,
                "outposts_total": 0,
            },
            "sync": sync,
            "services": {
                "dispatch": True,
                "postbox": True,
                "commons": True,
                "noticeboard": True,
                "beacon": True,
                "locker": True,
                "rollcall": True,
            },
            "database": db.health(),
            "beacon_active": active_beacon is not None,
            "active_beacon": active_beacon,
        }

    async def route(self, destination: str) -> dict[str, Any]:
        state = self._get_state()
        transport = state.transport
        reachable = await transport.reachable(destination)
        info = await transport.get_route(destination)
        quality = await transport.get_link_quality(destination)
        return {
            "destination": destination,
            "reachable": reachable,
            "quality": quality.value if hasattr(quality, "value") else str(quality),
            "route": (
                {
                    "hops": info.hops,
                    "next_hop": info.next_hop,
                    "path": list(info.path),
                }
                if info
                else None
            ),
        }

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        if op == OP_SIGNAL_STATUS:
            return envelope.make_response(op=op, payload=self.status())
        if op == OP_SIGNAL_ROUTE:
            dest = str(payload.get("destination") or "")
            if not dest:
                return envelope.make_response(
                    op=op, payload={"error": "destination required"}, error=True
                )
            # Sync wrapper: schedule is awkward; use known mock sync helpers when available
            transport = self._get_state().transport
            mesh = getattr(transport, "_mesh", None)
            if mesh is not None:
                info = mesh.get_route(transport.node_id, dest)
                reachable = mesh.is_reachable(transport.node_id, dest)
                return envelope.make_response(
                    op=op,
                    payload={
                        "destination": dest,
                        "reachable": reachable,
                        "route": (
                            {
                                "hops": info.hops,
                                "next_hop": info.next_hop,
                                "path": list(info.path),
                            }
                            if info
                            else None
                        ),
                    },
                )
            return envelope.make_response(
                op=op,
                payload={
                    "destination": dest,
                    "reachable": False,
                    "route": None,
                    "note": "async route lookup unavailable over sync RPC in this transport",
                },
            )
        return envelope.make_response(
            op=op,
            payload={"error": f"unknown_op:{op}"},
            flags=Flags.RESPONSE,
            error=True,
        )
