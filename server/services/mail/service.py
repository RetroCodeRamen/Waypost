"""Postbox service — progressive mail over HTTP and Waylink."""

from __future__ import annotations

import logging
from typing import Any, Optional

from server.services.mail.constants import (
    FOLDER_INBOX,
    FOLDER_OUTBOX,
    OP_MAIL_FLUSH,
    OP_MAIL_GET,
    OP_MAIL_LIST,
    OP_MAIL_MARK,
    OP_MAIL_NOTIFY,
    OP_MAIL_REPLY,
    OP_MAIL_SEND,
    OP_MAIL_STATUS,
)
from server.services.mail.store import MailStore, user_from_addr
from shared.protocol.envelope import SVC_MAIL, Envelope, Flags, new_id

logger = logging.getLogger("waypost.postbox")


class PostboxService:
    """Canonical mailbox on Station. LoRa uses progressive MAIL_* ops, not sync.

    Outbound mail always lands in OUTBOX storage first, then flushes to SENT +
    recipient INBOX. Waylink MAIL_NOTIFY pushes are persisted in SQLite.
    """

    def __init__(
        self,
        store: MailStore,
        *,
        nodes_for_user=None,
    ) -> None:
        self.store = store
        self._nodes_for_user = nodes_for_user or (lambda _u: [])

    def set_nodes_lookup(self, fn) -> None:
        self._nodes_for_user = fn

    def status(self, mailbox: str, folder: str = FOLDER_INBOX) -> dict[str, Any]:
        return self.store.status(mailbox, folder)

    def list_headers(self, mailbox: str, **kwargs) -> list[dict[str, Any]]:
        return self.store.list_headers(mailbox, **kwargs)

    def get(self, mailbox: str, **kwargs) -> Optional[dict[str, Any]]:
        return self.store.get(mailbox, **kwargs)

    def mark(self, mailbox: str, **kwargs) -> Optional[dict[str, Any]]:
        return self.store.mark(mailbox, **kwargs)

    def send(
        self,
        *,
        from_user: str,
        to_addr: str,
        subject: str,
        body: str,
        message_id: Optional[str] = None,
        in_reply_to: Optional[str] = None,
        attachment_name: Optional[str] = None,
        attachment_size: Optional[int] = None,
        queue_only: bool = False,
    ) -> dict[str, Any]:
        if not subject.strip() and not body.strip():
            raise ValueError("subject or body required")
        result = self.store.send(
            from_user=from_user,
            to_addr=to_addr,
            subject=subject.strip() or "(no subject)",
            body=body,
            message_id=message_id,
            in_reply_to=in_reply_to,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
            queue_only=queue_only,
        )
        if not result.get("queued"):
            self._notify_new_mail(result["delivered_to"])
        return result

    def flush_outbox(
        self,
        mailbox: str,
        *,
        local_id: Optional[int] = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        if local_id is not None:
            result = self.store.flush_outbox_item(mailbox, local_id=local_id)
            self._notify_new_mail(result["delivered_to"])
            return {"flushed": [result], "count": 1}
        results = self.store.flush_outbox(mailbox, limit=limit)
        notified: set[str] = set()
        for r in results:
            dest = r["delivered_to"]
            if dest not in notified:
                self._notify_new_mail(dest)
                notified.add(dest)
        return {"flushed": results, "count": len(results)}

    def reply(
        self,
        *,
        from_user: str,
        local_id: int,
        body: str,
        folder: str = FOLDER_INBOX,
        queue_only: bool = False,
    ) -> dict[str, Any]:
        original = self.store.get(from_user, local_id=local_id, folder=folder)
        if not original:
            raise ValueError("original message not found")
        subject = original["subject"]
        if not subject.lower().startswith("re:"):
            subject = f"Re: {subject}"
        return self.send(
            from_user=from_user,
            to_addr=original["from"],
            subject=subject,
            body=body,
            in_reply_to=original["id"],
            queue_only=queue_only,
        )

    def _notify_new_mail(self, username: str) -> None:
        st = self.store.status(username)
        nodes = list(self._nodes_for_user(username))
        if not nodes:
            # Persist a pending notify keyed by username for later bind flush
            env = Envelope(
                src="station",
                dst=f"user:{username}",
                svc=SVC_MAIL,
                op=OP_MAIL_NOTIFY,
                flags=int(Flags.REQUEST),
                mid=new_id(),
                payload={
                    "unread": st["unread"],
                    "total": st["total"],
                    "mailbox": username,
                    "outbox": st["outbox"],
                },
            )
            self.store.enqueue_push(f"user:{username}", env.to_dict())
            logger.info("mail_notify_queued_offline user=%s unread=%s", username, st["unread"])
            return
        for node_id in nodes:
            env = Envelope(
                src="station",
                dst=node_id,
                svc=SVC_MAIL,
                op=OP_MAIL_NOTIFY,
                flags=int(Flags.REQUEST),
                mid=new_id(),
                payload={
                    "unread": st["unread"],
                    "total": st["total"],
                    "mailbox": username,
                    "outbox": st["outbox"],
                },
            )
            self.store.enqueue_push(node_id, env.to_dict())
            logger.info("mail_notify node=%s unread=%s", node_id, st["unread"])

    def flush_pending_notifies_for_user(self, username: str, node_id: str) -> int:
        """When a Pocket binds, move user-keyed notifies onto the device outbox."""
        pending = self.store.poll_pushes(f"user:{username}", max_items=50)
        for env in pending:
            env = dict(env)
            env["dst"] = node_id
            self.store.enqueue_push(node_id, env)
        return len(pending)

    def poll_outbox(self, node_id: str, *, max_items: int = 20) -> list[dict[str, Any]]:
        return self.store.poll_pushes(node_id, max_items=max_items)

    async def handle_rpc(self, env: Envelope) -> Optional[Envelope]:
        op = env.op
        if op == OP_MAIL_STATUS:
            return self._rpc_status(env)
        if op == OP_MAIL_LIST:
            return self._rpc_list(env)
        if op == OP_MAIL_GET:
            return self._rpc_get(env)
        if op == OP_MAIL_SEND:
            return self._rpc_send(env)
        if op == OP_MAIL_REPLY:
            return self._rpc_reply(env)
        if op == OP_MAIL_MARK:
            return self._rpc_mark(env)
        if op == OP_MAIL_FLUSH:
            return self._rpc_flush(env)
        return env.make_response(
            op=op, payload={"error": "unknown_operation", "op": op}, error=True
        )

    def _mailbox_from_env(self, env: Envelope, payload: dict) -> Optional[str]:
        if payload.get("mailbox"):
            return str(payload["mailbox"])
        if payload.get("username"):
            return str(payload["username"])
        return None

    def _rpc_status(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload)
        if not mailbox:
            return env.make_response(
                op=OP_MAIL_STATUS, payload={"error": "mailbox_required"}, error=True
            )
        st = self.status(mailbox, str(payload.get("folder") or FOLDER_INBOX))
        return env.make_response(
            op=OP_MAIL_STATUS,
            payload={
                "unread": st["unread"],
                "total": st["total"],
                "outbox": st["outbox"],
                "sent": st["sent"],
                "addr": st["address"],
            },
        )

    def _rpc_list(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload)
        if not mailbox:
            return env.make_response(
                op=OP_MAIL_LIST, payload={"error": "mailbox_required"}, error=True
            )
        folder = str(payload.get("folder") or FOLDER_INBOX)
        limit = int(payload.get("limit") or 10)
        headers = self.list_headers(
            mailbox,
            folder=folder,
            limit=limit,
            unread_only=bool(payload.get("unread_only")),
        )
        compact = [
            {
                "n": h["local_id"],
                "from": user_from_addr(h["from"]) or h["from"],
                "to": user_from_addr(h["to"]) or h["to"],
                "subj": h["subject"][:60],
                "ts": int(h["created_at"]),
                "u": 0 if h["read"] else 1,
                "att": 1 if h["has_attachment"] else 0,
                "folder": h.get("folder") or folder,
            }
            for h in headers
        ]
        return env.make_response(
            op=OP_MAIL_LIST, payload={"folder": folder, "messages": compact}
        )

    def _rpc_get(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload)
        if not mailbox:
            return env.make_response(
                op=OP_MAIL_GET, payload={"error": "mailbox_required"}, error=True
            )
        local_id = payload.get("n") or payload.get("local_id")
        message_id = payload.get("id") or payload.get("message_id")
        folder = str(payload.get("folder") or FOLDER_INBOX)
        msg = self.get(
            mailbox,
            local_id=int(local_id) if local_id is not None else None,
            message_id=str(message_id) if message_id else None,
            folder=folder,
            include_body=True,
        )
        if not msg:
            return env.make_response(
                op=OP_MAIL_GET, payload={"error": "not_found"}, error=True
            )
        if folder == FOLDER_INBOX:
            self.mark(mailbox, message_id=msg["id"], read=True)
        out: dict[str, Any] = {
            "n": msg["local_id"],
            "from": msg["from"],
            "to": msg["to"],
            "subj": msg["subject"],
            "body": msg["body"],
            "ts": int(msg["created_at"]),
            "folder": msg.get("folder") or folder,
        }
        if msg.get("has_attachment"):
            out["att"] = {
                "name": msg.get("attachment_name"),
                "size": msg.get("attachment_size"),
                "wifi": True,
            }
        return env.make_response(op=OP_MAIL_GET, payload=out)

    def _rpc_send(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload) or payload.get("from_user")
        to_addr = payload.get("to") or payload.get("to_addr")
        if not mailbox or not to_addr:
            return env.make_response(
                op=OP_MAIL_SEND,
                payload={"error": "mailbox_and_to_required"},
                error=True,
            )
        queue_only = bool(payload.get("queue_only"))
        try:
            result = self.send(
                from_user=str(mailbox),
                to_addr=str(to_addr),
                subject=str(payload.get("subject") or payload.get("subj") or ""),
                body=str(payload.get("body") or ""),
                message_id=str(payload["message_id"]) if payload.get("message_id") else None,
                queue_only=queue_only,
            )
        except ValueError as exc:
            return env.make_response(
                op=OP_MAIL_SEND, payload={"error": str(exc)}, error=True
            )
        if result.get("queued"):
            return env.make_response(
                op=OP_MAIL_SEND,
                payload={
                    "ok": True,
                    "queued": True,
                    "n": result["outbox"]["local_id"],
                    "folder": FOLDER_OUTBOX,
                    "to": result["delivered_to"],
                },
                flags=Flags.RESPONSE | Flags.QUEUED,
            )
        return env.make_response(
            op=OP_MAIL_SEND,
            payload={
                "ok": True,
                "queued": False,
                "n": result["sent"]["local_id"],
                "folder": "SENT",
                "to": result["delivered_to"],
            },
            flags=Flags.RESPONSE | Flags.ACK,
        )

    def _rpc_reply(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload)
        local_id = payload.get("n") or payload.get("local_id")
        body = payload.get("body")
        if not mailbox or local_id is None or body is None:
            return env.make_response(
                op=OP_MAIL_REPLY,
                payload={"error": "mailbox_n_body_required"},
                error=True,
            )
        try:
            result = self.reply(
                from_user=str(mailbox),
                local_id=int(local_id),
                body=str(body),
                folder=str(payload.get("folder") or FOLDER_INBOX),
                queue_only=bool(payload.get("queue_only")),
            )
        except ValueError as exc:
            return env.make_response(
                op=OP_MAIL_REPLY, payload={"error": str(exc)}, error=True
            )
        if result.get("queued"):
            return env.make_response(
                op=OP_MAIL_REPLY,
                payload={"ok": True, "queued": True, "n": result["outbox"]["local_id"]},
                flags=Flags.RESPONSE | Flags.QUEUED,
            )
        return env.make_response(
            op=OP_MAIL_REPLY,
            payload={"ok": True, "queued": False, "n": result["sent"]["local_id"]},
            flags=Flags.RESPONSE | Flags.ACK,
        )

    def _rpc_mark(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload)
        if not mailbox:
            return env.make_response(
                op=OP_MAIL_MARK, payload={"error": "mailbox_required"}, error=True
            )
        result = self.mark(
            mailbox,
            local_id=int(payload["n"]) if payload.get("n") is not None else None,
            message_id=str(payload["id"]) if payload.get("id") else None,
            folder=str(payload.get("folder") or FOLDER_INBOX),
            read=payload.get("read"),
            delete=bool(payload.get("delete")),
        )
        if not result:
            return env.make_response(
                op=OP_MAIL_MARK, payload={"error": "not_found"}, error=True
            )
        return env.make_response(op=OP_MAIL_MARK, payload={"ok": True, **result})

    def _rpc_flush(self, env: Envelope) -> Envelope:
        payload = env.payload if isinstance(env.payload, dict) else {}
        mailbox = self._mailbox_from_env(env, payload)
        if not mailbox:
            return env.make_response(
                op=OP_MAIL_FLUSH, payload={"error": "mailbox_required"}, error=True
            )
        try:
            result = self.flush_outbox(
                mailbox,
                local_id=int(payload["n"]) if payload.get("n") is not None else None,
                limit=int(payload.get("limit") or 50),
            )
        except ValueError as exc:
            return env.make_response(
                op=OP_MAIL_FLUSH, payload={"error": str(exc)}, error=True
            )
        return env.make_response(
            op=OP_MAIL_FLUSH,
            payload={"ok": True, "count": result["count"]},
            flags=Flags.RESPONSE | Flags.ACK,
        )
