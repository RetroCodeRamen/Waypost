"""Transport factory."""

from __future__ import annotations

import os
from typing import Optional

from server.transports.base import Transport
from server.transports.mock import MockMesh, MockTransport, MockTransportConfig
from server.transports.reticulum import ReticulumTransport, RNodeRadio
from server.transports.serial_bridge import SerialBridgeTransport

# Process-wide mock mesh for single-process Station + tests
_default_mesh: Optional[MockMesh] = None


def get_default_mesh() -> MockMesh:
    global _default_mesh
    if _default_mesh is None:
        _default_mesh = MockMesh()
    return _default_mesh


def create_transport(
    kind: Optional[str] = None,
    *,
    node_id: str = "station",
    device_path: Optional[str] = None,
) -> Transport:
    kind = (kind or os.getenv("WAYPOST_TRANSPORT", "mock")).lower()
    if kind == "mock":
        mesh = get_default_mesh()
        return mesh.attach(node_id, MockTransportConfig())
    if kind in ("serial", "serial_bridge", "heltec"):
        path = device_path or os.getenv("WAYPOST_LORA_DEVICE", "/dev/waypost-lora")
        return SerialBridgeTransport(device_path=path, node_id=node_id)
    if kind in ("reticulum", "rns", "lora"):
        path = device_path or os.getenv("WAYPOST_LORA_DEVICE", "/dev/waypost-lora")
        config = os.getenv("WAYPOST_RNS_CONFIG", "data/reticulum")
        port = int(os.getenv("WAYPOST_RNS_PORT", "37429"))
        iface = os.getenv("WAYPOST_RNS_INTERFACE", "auto")
        tcp_host = os.getenv("WAYPOST_RNS_TCP_HOST", "127.0.0.1")
        tcp_port = int(os.getenv("WAYPOST_RNS_TCP_PORT", "4242"))
        return ReticulumTransport(
            device_path=path,
            config_dir=config,
            control_port=port,
            node_id=node_id,
            interface=iface,
            tcp_host=tcp_host,
            tcp_port=tcp_port,
            rnode=RNodeRadio.from_env(path) if iface == "rnode" else None,
        )
    raise ValueError(f"Unknown WAYPOST_TRANSPORT: {kind}")
