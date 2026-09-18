"""HTTP routes for Signal diagnostics."""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from server.api.deps import get_current_user


class SignalPing(BaseModel):
    destination: str = Field(default="peer", max_length=64)
    port: Optional[str] = Field(default=None, max_length=120)
    wait: float = Field(default=5.0, ge=0.5, le=30.0)


def build_signal_router() -> APIRouter:
    router = APIRouter(tags=["signal"])

    @router.get("/api/signal")
    def signal_status(request: Request, user=Depends(get_current_user)):
        _ = user
        return request.app.state.signal.status()

    @router.get("/api/signal/route")
    async def signal_route(
        destination: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        return await request.app.state.signal.route(destination)

    @router.post("/api/signal/ping")
    async def signal_ping(
        body: SignalPing, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        """Send Waylink PING via Heltec USB serial bridge (blocking thread)."""
        settings = request.app.state.settings
        port = body.port or getattr(settings, "waypost_lora_device", None) or "/dev/ttyUSB0"
        # Prefer first detected radio if configured path missing
        if port.startswith("/dev/waypost"):
            try:
                from tools.radio.list_devices import list_radio_devices

                radios = list_radio_devices()
                if radios:
                    port = radios[0]["path"]
            except Exception:
                port = "/dev/ttyUSB0"

        def _run():
            from tools.radio.ping import cmd_ping

            return cmd_ping(port, body.destination, wait=body.wait)

        code = await asyncio.to_thread(_run)
        if code != 0:
            raise HTTPException(
                status_code=504,
                detail=f"No PONG from {body.destination} via {port}",
            )
        return {"ok": True, "destination": body.destination, "port": port}

    @router.post("/api/signal/airtest")
    async def signal_airtest(
        request: Request,
        user=Depends(get_current_user),
        tx: str = "/dev/ttyUSB0",
        rx: str = "/dev/ttyUSB1",
        payload: str = "WAYPOST_AIR_TEST",
    ):
        _ = user
        def _run():
            import serial
            import threading
            import time

            from tools.radio.ping import read_frame, write_frame

            got: list[bytes] = []
            stop = threading.Event()

            def listener() -> None:
                with serial.Serial(rx, 115200, timeout=0.2) as ser:
                    time.sleep(0.3)
                    ser.reset_input_buffer()
                    deadline = time.time() + 5
                    while time.time() < deadline and not stop.is_set():
                        frame = read_frame(ser, timeout=0.5)
                        if frame is not None:
                            got.append(frame)
                            if frame == payload.encode():
                                stop.set()
                                return

            t = threading.Thread(target=listener, daemon=True)
            t.start()
            time.sleep(0.4)
            with serial.Serial(tx, 115200, timeout=0.2) as ser:
                time.sleep(0.2)
                ser.reset_input_buffer()
                write_frame(ser, payload.encode())
            t.join(timeout=6)
            stop.set()
            return [g.decode("utf-8", errors="replace") for g in got]

        frames = await asyncio.to_thread(_run)
        ok = payload in frames
        return {"ok": ok, "tx": tx, "rx": rx, "payload": payload, "received": frames}

    return router
