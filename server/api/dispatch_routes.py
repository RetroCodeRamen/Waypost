"""HTTP routes for Dispatch and mock Waylink bridge."""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from server.api.deps import actor_username, auth_enforced, get_current_user
from server.services.dispatch.constants import TRANSPORT_WIFI
from shared.protocol.envelope import (
    SVC_DISPATCH,
    SVC_MAIL,
    Envelope,
    Flags,
    decode_cbor,
    encode_cbor,
)


class DirectSend(BaseModel):
    sender: str = Field(min_length=1, max_length=32)
    body: str = Field(min_length=1, max_length=4000)
    peer: Optional[str] = Field(default=None, min_length=1, max_length=32)
    conversation_id: Optional[str] = Field(default=None, min_length=1, max_length=80)
    message_id: Optional[str] = None
    transport: str = TRANSPORT_WIFI


class DeviceBind(BaseModel):
    node_id: str = Field(min_length=1, max_length=64)
    username: str = Field(min_length=1, max_length=32)
    transport_dest: Optional[str] = Field(
        default=None,
        max_length=128,
        description="Reticulum destination hash (32 hex) for encrypted pushes",
    )


class DeviceUnbind(BaseModel):
    username: str = Field(min_length=1, max_length=32)


class DirectOpen(BaseModel):
    user_a: str = Field(min_length=1, max_length=32)
    user_b: str = Field(min_length=1, max_length=32)


class RoomCreate(BaseModel):
    title: str = Field(min_length=1, max_length=80)
    members: list[str] = Field(min_length=1)
    slug: Optional[str] = Field(default=None, max_length=64)


class RoomJoin(BaseModel):
    username: str = Field(min_length=1, max_length=32)


class WaylinkRpcBody(BaseModel):
    """JSON envelope for mock Pocket ↔ Station without radios."""

    v: int = 1
    mid: str
    rid: str
    src: str
    dst: str = "station"
    svc: str
    op: str
    flags: int = int(Flags.REQUEST)
    ts: int = 0
    ttl: int = 8
    payload: Any = None


def build_dispatch_router() -> APIRouter:
    router = APIRouter(tags=["dispatch"])

    @router.post("/api/dispatch/devices/bind")
    def bind_device(body: DeviceBind, request: Request, user=Depends(get_current_user)):
        username = actor_username(request, user, body.username)
        if auth_enforced(request) and body.username.lower() != username.lower():
            raise HTTPException(status_code=403, detail="cannot bind device for another user")
        db = request.app.state.db
        db.ensure_user(username)
        binding = request.app.state.dispatch.bind_device(
            body.node_id,
            username,
            transport_dest=body.transport_dest,
        )
        # Teach live Reticulum transport how to address this logical node
        transport = getattr(request.app.state, "transport", None)
        if (
            body.transport_dest
            and transport is not None
            and hasattr(transport, "learn_route")
        ):
            transport.learn_route(body.node_id, body.transport_dest)
        if hasattr(request.app.state, "rollcall"):
            request.app.state.rollcall.touch(username, via="lora")
        if hasattr(request.app.state, "postbox"):
            flushed_mail = request.app.state.postbox.flush_pending_notifies_for_user(
                username, body.node_id
            )
            binding["mail_notifies_flushed"] = flushed_mail
        return binding

    @router.post("/api/dispatch/devices/unbind")
    def unbind_devices(body: DeviceUnbind, request: Request, user=Depends(get_current_user)):
        """Detach device bindings (signed-in user only when auth on)."""
        username = actor_username(request, user, body.username)
        if auth_enforced(request) and body.username.lower() != username.lower():
            raise HTTPException(status_code=403, detail="cannot unbind another user")
        return request.app.state.dispatch.unbind_user(username)

    @router.post("/api/dispatch/conversations/direct")
    def open_direct(
        body: DirectOpen, request: Request, user=Depends(get_current_user)
    ):
        db = request.app.state.db
        if auth_enforced(request):
            me = user["username"].lower()
            if me not in (body.user_a.lower(), body.user_b.lower()):
                raise HTTPException(status_code=403, detail="must be a participant")
        db.ensure_user(body.user_a)
        db.ensure_user(body.user_b)
        conv = request.app.state.dispatch.store.ensure_direct(body.user_a, body.user_b)
        messages = request.app.state.dispatch.list_messages(conv["id"])
        return {"conversation": conv, "messages": messages}

    @router.post("/api/dispatch/conversations/rooms")
    def create_room(
        body: RoomCreate, request: Request, user=Depends(get_current_user)
    ):
        db = request.app.state.db
        members = list(dict.fromkeys(body.members))
        if auth_enforced(request) and user["username"] not in members:
            members.insert(0, user["username"])
        for u in members:
            db.ensure_user(u)
        try:
            conv = request.app.state.dispatch.create_room(
                title=body.title, members=members, slug=body.slug
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"conversation": conv, "messages": []}

    @router.post("/api/dispatch/conversations/{conversation_id}/join")
    def join_room(
        conversation_id: str,
        body: RoomJoin,
        request: Request,
        user=Depends(get_current_user),
    ):
        db = request.app.state.db
        username = actor_username(request, user, body.username)
        db.ensure_user(username)
        conv = request.app.state.dispatch.store.add_room_member(
            conversation_id, username
        )
        if not conv:
            raise HTTPException(status_code=404, detail="Room not found")
        return {"conversation": conv}

    @router.get("/api/dispatch/conversations")
    def list_conversations(
        username: str, request: Request, user=Depends(get_current_user)
    ):
        username = actor_username(request, user, username)
        return {"conversations": request.app.state.dispatch.list_conversations(username)}

    @router.get("/api/dispatch/conversations/{conversation_id}")
    def get_conversation(
        conversation_id: str, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        conv = request.app.state.dispatch.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        messages = request.app.state.dispatch.list_messages(conversation_id)
        return {"conversation": conv, "messages": messages}

    @router.get("/api/dispatch/conversations/{conversation_id}/messages")
    def list_messages(
        conversation_id: str,
        request: Request,
        user=Depends(get_current_user),
        after_ts: Optional[float] = None,
        limit: int = 50,
    ):
        _ = user
        conv = request.app.state.dispatch.get_conversation(conversation_id)
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {
            "messages": request.app.state.dispatch.list_messages(
                conversation_id, limit=limit, after_ts=after_ts
            )
        }

    @router.post("/api/dispatch/messages")
    def send_message(
        body: DirectSend, request: Request, user=Depends(get_current_user)
    ):
        db = request.app.state.db
        sender = actor_username(request, user, body.sender)
        db.ensure_user(sender)
        try:
            if body.conversation_id:
                result = request.app.state.dispatch.send_to_conversation(
                    conversation_id=body.conversation_id,
                    sender=sender,
                    body=body.body,
                    message_id=body.message_id,
                    transport=body.transport,
                )
            elif body.peer:
                db.ensure_user(body.peer)
                result = request.app.state.dispatch.send_direct(
                    sender=sender,
                    peer=body.peer,
                    body=body.body,
                    message_id=body.message_id,
                    transport=body.transport,
                )
            else:
                raise HTTPException(
                    status_code=400, detail="peer or conversation_id required"
                )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return result

    @router.post("/api/waylink/rpc")
    async def waylink_rpc_json(
        body: WaylinkRpcBody, request: Request, user=Depends(get_current_user)
    ):
        _ = user
        env = Envelope.from_dict(body.model_dump())
        if env.svc == SVC_DISPATCH:
            reply = await request.app.state.dispatch.handle_rpc(env)
            return reply.to_dict() if reply else {"ok": True}
        if env.svc == SVC_MAIL:
            payload = env.payload if isinstance(env.payload, dict) else {}
            if not payload.get("mailbox") and not payload.get("username"):
                binding = request.app.state.dispatch.store.get_binding(env.src)
                if binding:
                    payload = dict(payload)
                    payload["mailbox"] = binding["username"]
                    env.payload = payload
            reply = await request.app.state.postbox.handle_rpc(env)
            return reply.to_dict() if reply else {"ok": True}
        gateway = getattr(request.app.state, "gateway", None)
        if gateway is not None:
            handler = gateway._handlers.get((env.svc, env.op))
            if handler:
                reply = await handler(env)
                return reply.to_dict() if reply else {"ok": True}
        raise HTTPException(status_code=400, detail=f"unsupported service {env.svc}")

    @router.post("/api/waylink/rpc/cbor")
    async def waylink_rpc_cbor(
        request: Request, user=Depends(get_current_user)
    ):
        _ = user
        raw = await request.body()
        try:
            env = decode_cbor(raw)
        except Exception as exc:
            raise HTTPException(status_code=400, detail="invalid CBOR envelope") from exc
        if env.svc == SVC_DISPATCH:
            reply = await request.app.state.dispatch.handle_rpc(env)
        elif env.svc == SVC_MAIL:
            payload = env.payload if isinstance(env.payload, dict) else {}
            if not payload.get("mailbox") and not payload.get("username"):
                binding = request.app.state.dispatch.store.get_binding(env.src)
                if binding:
                    payload = dict(payload)
                    payload["mailbox"] = binding["username"]
                    env.payload = payload
            reply = await request.app.state.postbox.handle_rpc(env)
        else:
            raise HTTPException(status_code=400, detail=f"unsupported service {env.svc}")
        if reply is None:
            return Response(status_code=204)
        return Response(content=encode_cbor(reply), media_type="application/cbor")

    @router.get("/api/waylink/outbox/{node_id}")
    def waylink_outbox(
        node_id: str,
        request: Request,
        user=Depends(get_current_user),
        max_items: int = 20,
    ):
        _ = user
        items = request.app.state.dispatch.poll_outbox(node_id, max_items=max_items)
        remaining = max(0, max_items - len(items))
        if remaining and hasattr(request.app.state, "postbox"):
            items.extend(request.app.state.postbox.poll_outbox(node_id, max_items=remaining))
        return {"node_id": node_id, "envelopes": items}

    return router
