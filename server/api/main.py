"""Waypost Station HTTP API."""

from __future__ import annotations

import asyncio
import html
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from server.api.auth_routes import build_auth_router
from server.api.beacon_routes import build_beacon_router
from server.api.commons_routes import build_commons_router
from server.api.config import Settings, get_settings
from server.api.corkboard_routes import build_corkboard_router
from server.api.dashboard_routes import build_dashboard_router
from server.api.db import Database
from server.api.deps import get_current_user
from server.api.dispatch_routes import build_dispatch_router
from server.api.groups_routes import build_groups_router
from server.api.locker_routes import build_locker_router
from server.api.noticeboard_routes import build_noticeboard_router
from server.api.postbox_routes import build_postbox_router
from server.api.rollcall_routes import build_rollcall_router
from server.api.signal_routes import build_signal_router
from server.gateway.waylink import WaylinkGateway
from server.services.auth.pairing import PairingService
from server.services.auth.passwords import hash_password
from server.services.auth.service import AuthService
from server.services.beacon.constants import (
    OP_BEACON_CLEAR,
    OP_BEACON_GET,
    OP_BEACON_LIST,
    OP_BEACON_PUSH,
)
from server.services.beacon.service import BeaconService
from server.services.commons.constants import OP_POST_CREATE, OP_POST_GET, OP_POST_LIST
from server.services.commons.service import CommonsService
from server.services.corkboard.constants import OP_BOARD_SYNC, OP_OUTPOST_CLAIM
from server.services.corkboard.service import CorkboardService
from server.services.dispatch.constants import (
    OP_MSG_ACK,
    OP_MSG_LIST,
    OP_MSG_PUSH,
    OP_MSG_SEND,
    OP_MSG_SYNC,
)
from server.services.dispatch.service import DispatchService
from server.services.groups.service import GroupsService
from server.services.locker.constants import OP_FILE_DELETE, OP_FILE_INFO, OP_FILE_LIST
from server.services.locker.service import LockerService
from server.services.mail.constants import (
    OP_MAIL_FLUSH,
    OP_MAIL_GET,
    OP_MAIL_LIST,
    OP_MAIL_MARK,
    OP_MAIL_REPLY,
    OP_MAIL_SEND,
    OP_MAIL_STATUS,
)
from server.services.mail.service import PostboxService
from server.services.noticeboard.constants import (
    OP_NOTICE_ACK,
    OP_NOTICE_CREATE,
    OP_NOTICE_EXPIRE,
    OP_NOTICE_GET,
    OP_NOTICE_LIST,
)
from server.services.noticeboard.service import NoticeboardService
from server.services.profiles.constants import OP_PAIR_REDEEM
from server.services.profiles.rollcall import RollcallService
from server.services.signal.service import (
    OP_SIGNAL_ROUTE,
    OP_SIGNAL_STATUS,
    SignalService,
)
from server.transports import create_transport
from shared.protocol.envelope import (
    SVC_BEACON,
    SVC_COMMONS,
    SVC_CORKBOARD,
    SVC_DISPATCH,
    SVC_LOCKER,
    SVC_MAIL,
    SVC_NOTICEBOARD,
    SVC_PROFILE,
    SVC_SIGNAL,
    Envelope,
)

logger = logging.getLogger("waypost.api")

PORTAL_DIR = Path(__file__).resolve().parents[2] / "web" / "portal"


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=32, pattern=r"^[a-zA-Z0-9_\-]+$")
    display_name: str = Field(min_length=1, max_length=80)


def create_app(settings: Optional[Settings] = None) -> FastAPI:
    settings = settings or get_settings()
    settings.ensure_data_dirs()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logging.basicConfig(
            level=getattr(logging, settings.waypost_log_level.upper(), logging.INFO)
        )
        db = Database(
            settings.waypost_sqlite_path,
            locker_root=settings.waypost_locker_dir,
        )
        dispatch = DispatchService(db.dispatch)
        postbox = PostboxService(
            db.mail,
            nodes_for_user=lambda u: db.dispatch.nodes_for_user(u),
        )
        commons = CommonsService(db.commons)
        noticeboard = NoticeboardService(
            db.noticeboard, get_binding=lambda n: db.dispatch.get_binding(n)
        )
        beacon = BeaconService(db.beacon, get_binding=lambda n: db.dispatch.get_binding(n))
        corkboard = CorkboardService(db.corkboard)
        groups = GroupsService(db.groups)
        locker = LockerService(db.locker, is_group_member=db.groups.is_member)
        rollcall = RollcallService(db)
        app.state.db = db
        app.state.settings = settings
        app.state.dispatch = dispatch
        app.state.postbox = postbox
        app.state.commons = commons
        app.state.noticeboard = noticeboard
        app.state.beacon = beacon
        app.state.corkboard = corkboard
        app.state.groups = groups
        app.state.locker = locker
        app.state.rollcall = rollcall
        app.state.signal = SignalService(lambda: app.state)
        app.state.auth = AuthService(db)
        app.state.pairing = PairingService(db, dispatch, corkboard_store=db.corkboard)

        transport = create_transport(
            settings.waypost_transport,
            node_id="station",
            device_path=settings.waypost_lora_device,
        )
        gateway = WaylinkGateway(transport, local_id="station")
        gateway.register(SVC_DISPATCH, OP_MSG_SEND, dispatch.handle_rpc)
        gateway.register(SVC_DISPATCH, OP_MSG_LIST, dispatch.handle_rpc)
        gateway.register(SVC_DISPATCH, OP_MSG_ACK, dispatch.handle_rpc)
        gateway.register(SVC_DISPATCH, OP_MSG_SYNC, dispatch.handle_rpc)
        gateway.register(SVC_DISPATCH, OP_MSG_PUSH, dispatch.handle_rpc)
        for op in (
            OP_MAIL_STATUS,
            OP_MAIL_LIST,
            OP_MAIL_GET,
            OP_MAIL_SEND,
            OP_MAIL_REPLY,
            OP_MAIL_MARK,
            OP_MAIL_FLUSH,
        ):
            gateway.register(SVC_MAIL, op, postbox.handle_rpc)
        for op in (OP_POST_LIST, OP_POST_CREATE, OP_POST_GET):
            gateway.register(SVC_COMMONS, op, commons.handle_rpc)
        for op in (
            OP_NOTICE_LIST,
            OP_NOTICE_GET,
            OP_NOTICE_CREATE,
            OP_NOTICE_EXPIRE,
            OP_NOTICE_ACK,
        ):
            gateway.register(SVC_NOTICEBOARD, op, noticeboard.handle_rpc)
        for op in (OP_BEACON_GET, OP_BEACON_PUSH, OP_BEACON_CLEAR, OP_BEACON_LIST):
            gateway.register(SVC_BEACON, op, beacon.handle_rpc)
        gateway.register(SVC_CORKBOARD, OP_BOARD_SYNC, corkboard.handle_rpc)
        gateway.register(
            SVC_CORKBOARD, OP_OUTPOST_CLAIM, app.state.pairing.handle_outpost_claim
        )
        for op in (OP_FILE_LIST, OP_FILE_INFO, OP_FILE_DELETE):
            gateway.register(SVC_LOCKER, op, locker.handle_rpc)
        for op in (OP_SIGNAL_STATUS, OP_SIGNAL_ROUTE):
            gateway.register(SVC_SIGNAL, op, app.state.signal.handle_rpc)
        gateway.register(SVC_PROFILE, OP_PAIR_REDEEM, app.state.pairing.handle_rpc)
        app.state.transport = transport
        app.state.gateway = gateway
        # PairingService is constructed before Transport exists (it needs
        # to call learn_route() before replying to a redemption — see its
        # module docstring), so it's wired up here instead of at construction.
        app.state.pairing.transport = transport

        def _resolve_dest(dst: str) -> str:
            if hasattr(transport, "resolve_destination"):
                mapped = transport.resolve_destination(dst)
                if mapped and mapped != dst:
                    return mapped
            stored = dispatch.store.transport_dest_for(dst)
            return stored or dst

        gateway._resolve_dest = _resolve_dest  # type: ignore[attr-defined]

        # Reload RNS routes from bindings after restart
        if hasattr(transport, "learn_route"):
            try:
                rows = db._conn.execute(
                    "SELECT node_id, transport_dest FROM device_bindings "
                    "WHERE transport_dest IS NOT NULL AND transport_dest != ''"
                ).fetchall()
                for row in rows:
                    transport.learn_route(row["node_id"], row["transport_dest"])
            except Exception:
                logger.exception("failed to reload transport routes")
            try:
                for row in db.corkboard.list_claimed_outposts():
                    transport.learn_route(row["node_id"], row["transport_dest"])
            except Exception:
                logger.exception("failed to reload outpost transport routes")

        # When using a live radio transport, also TX Dispatch pushes over the air
        if settings.waypost_transport in (
            "serial",
            "serial_bridge",
            "heltec",
            "reticulum",
            "rns",
            "lora",
        ):
            loop = asyncio.get_running_loop()

            def _radio_push(env: Envelope) -> None:
                loop.create_task(gateway.send_envelope(env))

            dispatch.set_radio_push(_radio_push)

        if settings.waypost_transport in (
            "mock",
            "serial",
            "serial_bridge",
            "heltec",
            "reticulum",
            "rns",
            "lora",
        ):
            try:
                await gateway.start()
            except Exception:
                logger.exception(
                    "Failed to start Waylink gateway transport=%s",
                    settings.waypost_transport,
                )
        else:
            logger.info(
                "Skipping gateway start for transport=%s",
                settings.waypost_transport,
            )

        # Dev convenience: demo users with known password (lab only)
        if settings.waypost_env in ("development", "test"):
            for uname, dname in (("aj", "AJ"), ("bob", "Bob")):
                u = db.ensure_user(uname, dname)
                if not u.get("password_hash"):
                    db.set_password_hash(uname, hash_password("waypost1"))
                    logger.info("seeded password for demo user %s (lab: waypost1)", uname)
            # One lab admin so the Control page (ADMIN_APPROVAL) is testable
            # without a separate real bootstrap-first-user flow in dev.
            db.set_admin("aj", is_admin=True)

        logger.info(
            "Waypost API starting env=%s transport=%s auth_required=%s",
            settings.waypost_env,
            settings.waypost_transport,
            settings.waypost_auth_required and settings.waypost_env != "test",
        )
        yield
        if getattr(app.state, "gateway", None) and settings.waypost_transport in (
            "mock",
            "serial",
            "serial_bridge",
            "heltec",
            "reticulum",
            "rns",
            "lora",
        ):
            await app.state.gateway.stop()
        db.close()

    app = FastAPI(
        title="Waypost API",
        description="Off-grid community network Station API",
        version="0.6.0",
        lifespan=lifespan,
    )
    app.include_router(build_auth_router())
    app.include_router(build_dispatch_router())
    app.include_router(build_postbox_router())
    app.include_router(build_commons_router())
    app.include_router(build_noticeboard_router())
    app.include_router(build_beacon_router())
    app.include_router(build_corkboard_router())
    app.include_router(build_groups_router())
    app.include_router(build_locker_router())
    app.include_router(build_signal_router())
    app.include_router(build_rollcall_router())
    app.include_router(build_dashboard_router())

    @app.get("/api/health")
    def health():
        db_health = app.state.db.health()
        return {
            "status": "ok",
            "service": "waypost-station",
            "env": settings.waypost_env,
            "domain": settings.waypost_domain,
            "ssid": settings.waypost_ssid,
            "transport": settings.waypost_transport,
            "registration_mode": settings.waypost_registration_mode,
            "database": db_health,
            "dispatch": True,
            "postbox": True,
            "commons": True,
            "noticeboard": True,
            "beacon": True,
            "groups": True,
            "locker": True,
            "signal": True,
            "rollcall": True,
        }

    @app.get("/api/meta")
    def meta():
        return {
            "name": "Waypost",
            "station": "Waypost Station",
            "apps": [
                "Dispatch",
                "Postbox",
                "Rollcall",
                "Commons",
                "Fieldbook",
                "Noticeboard",
                "Beacon",
                "Groups",
                "Locker",
                "Archive",
                "Atlas",
                "Finder",
                "Signal",
                "Control",
            ],
            "phase": "locker-local",
        }

    @app.get("/api/users")
    def list_users(user=Depends(get_current_user)):
        _ = user
        return {"users": app.state.db.list_users()}

    @app.post("/api/users", status_code=201)
    def create_user(body: UserCreate, user=Depends(get_current_user)):
        _ = user
        # Prefer /api/auth/register (sets password). Kept for Rollcall/profile seeding in lab.
        if settings.waypost_registration_mode == "INVITE_ONLY":
            raise HTTPException(status_code=403, detail="Registration is invite-only")
        existing = app.state.db.get_user_by_username(body.username)
        if existing:
            raise HTTPException(status_code=409, detail="Username already taken")
        created = app.state.db.create_user(body.username, body.display_name)
        return created

    @app.get("/api/users/{username}")
    def get_user(username: str, user=Depends(get_current_user)):
        _ = user
        found = app.state.db.get_user_by_username(username)
        if not found:
            raise HTTPException(status_code=404, detail="User not found")
        # Never expose password_hash over HTTP
        return {
            "id": found["id"],
            "username": found["username"],
            "display_name": found["display_name"],
            "status": found.get("status") or "",
            "bio": found.get("bio") or "",
        }

    @app.get("/~{username}", response_class=HTMLResponse)
    def profile_page(username: str):
        user = app.state.db.get_user_by_username(username)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        status = html.escape(user.get("status") or "No status set")
        bio = html.escape(user.get("bio") or "")
        display = html.escape(user["display_name"])
        uname = html.escape(user["username"])
        mount_user = json.dumps(user["display_name"])
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Waypost /~{uname}</title>
  <link rel="stylesheet" href="/static/tokens.css"/>
  <link rel="stylesheet" href="/static/shell.css"/>
  <link rel="stylesheet" href="/static/style.css"/>
</head>
<body>
  <div id="wp-page">
    <div class="wp-card profile-card">
      <p class="profile-kicker">/~{uname}</p>
      <h1>{display}</h1>
      <p class="status">{status}</p>
      <p class="bio">{bio}</p>
      <p class="actions"><a href="/dispatch.html">Dispatch</a> · <a href="/postbox.html">Postbox</a> · <a href="/rollcall.html">Rollcall</a></p>
    </div>
  </div>
  <script src="/static/shell.js"></script>
  <script>WaypostShell.mount({{ active: "rollcall", user: {mount_user}, subtitle: "Community profile", title: {mount_user} }});</script>
</body>
</html>"""

    if PORTAL_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=PORTAL_DIR / "static"), name="static")

        @app.get("/")
        def portal_index():
            return FileResponse(PORTAL_DIR / "index.html")

        @app.get("/dispatch.html")
        def portal_dispatch():
            return FileResponse(PORTAL_DIR / "dispatch.html")

        @app.get("/postbox.html")
        def portal_postbox():
            return FileResponse(PORTAL_DIR / "postbox.html")

        @app.get("/rollcall.html")
        def portal_rollcall():
            return FileResponse(PORTAL_DIR / "rollcall.html")

        @app.get("/commons.html")
        def portal_commons():
            return FileResponse(PORTAL_DIR / "commons.html")

        @app.get("/noticeboard.html")
        def portal_noticeboard():
            return FileResponse(PORTAL_DIR / "noticeboard.html")

        @app.get("/beacon.html")
        def portal_beacon():
            return FileResponse(PORTAL_DIR / "beacon.html")

        @app.get("/signal.html")
        def portal_signal():
            return FileResponse(PORTAL_DIR / "signal.html")

        @app.get("/locker.html")
        def portal_locker():
            return FileResponse(PORTAL_DIR / "locker.html")

        @app.get("/login.html")
        def portal_login():
            return FileResponse(PORTAL_DIR / "login.html")

        @app.get("/trust.html")
        def portal_trust():
            return FileResponse(PORTAL_DIR / "trust.html")

        @app.get("/devices.html")
        def portal_devices():
            return FileResponse(PORTAL_DIR / "devices.html")

        @app.get("/corkboard.html")
        def portal_corkboard():
            return FileResponse(PORTAL_DIR / "corkboard.html")

        @app.get("/control.html")
        def portal_control():
            return FileResponse(PORTAL_DIR / "control.html")

        @app.get("/groups.html")
        def portal_groups():
            return FileResponse(PORTAL_DIR / "groups.html")

    return app


app = create_app()
