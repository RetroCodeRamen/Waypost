"""SQLite Postbox store — local mailbox until Stalwart adapter lands."""

from __future__ import annotations

import json
import sqlite3
import time
from typing import Any, Optional

from server.services.mail.constants import (
    DEFAULT_MAIL_DOMAIN,
    FOLDER_INBOX,
    FOLDER_OUTBOX,
    FOLDER_SENT,
)
from shared.protocol.envelope import new_id


MAIL_SCHEMA = """
CREATE TABLE IF NOT EXISTS mail_messages (
    id TEXT PRIMARY KEY,
    mailbox TEXT NOT NULL COLLATE NOCASE,
    folder TEXT NOT NULL,
    local_id INTEGER NOT NULL,
    from_addr TEXT NOT NULL,
    to_addr TEXT NOT NULL,
    subject TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    created_at REAL NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    in_reply_to TEXT,
    has_attachment INTEGER NOT NULL DEFAULT 0,
    attachment_name TEXT,
    attachment_size INTEGER,
    attachment_wifi_only INTEGER NOT NULL DEFAULT 1,
    UNIQUE (mailbox, folder, local_id)
);

CREATE INDEX IF NOT EXISTS idx_mail_mailbox_folder
    ON mail_messages(mailbox, folder, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_mail_mailbox_unread
    ON mail_messages(mailbox, folder, is_read);

CREATE TABLE IF NOT EXISTS mail_push_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    envelope_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mail_push_node
    ON mail_push_outbox(node_id, id);
"""


def addr_for_user(username: str, domain: str = DEFAULT_MAIL_DOMAIN) -> str:
    return f"{username.lower()}@{domain}"


def user_from_addr(addr: str, domain: str = DEFAULT_MAIL_DOMAIN) -> Optional[str]:
    addr = addr.strip().lower()
    if "@" not in addr:
        return addr
    local, _, host = addr.partition("@")
    if host and host not in (domain, "waypost.home.arpa", "localhost"):
        pass
    return local or None


class MailStore:
    def __init__(self, conn: sqlite3.Connection, domain: str = DEFAULT_MAIL_DOMAIN) -> None:
        self._conn = conn
        self.domain = domain
        self._conn.executescript(MAIL_SCHEMA)
        self._conn.commit()

    def _next_local_id(self, mailbox: str, folder: str) -> int:
        row = self._conn.execute(
            """
            SELECT COALESCE(MAX(local_id), 0) + 1 AS n
            FROM mail_messages WHERE mailbox = ? COLLATE NOCASE AND folder = ?
            """,
            (mailbox, folder),
        ).fetchone()
        return int(row["n"])

    def status(self, mailbox: str, folder: str = FOLDER_INBOX) -> dict[str, Any]:
        unread = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM mail_messages
            WHERE mailbox = ? COLLATE NOCASE AND folder = ? AND is_read = 0
            """,
            (mailbox, folder),
        ).fetchone()["n"]
        total = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM mail_messages
            WHERE mailbox = ? COLLATE NOCASE AND folder = ?
            """,
            (mailbox, folder),
        ).fetchone()["n"]
        outbox = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM mail_messages
            WHERE mailbox = ? COLLATE NOCASE AND folder = ?
            """,
            (mailbox, FOLDER_OUTBOX),
        ).fetchone()["n"]
        sent = self._conn.execute(
            """
            SELECT COUNT(*) AS n FROM mail_messages
            WHERE mailbox = ? COLLATE NOCASE AND folder = ?
            """,
            (mailbox, FOLDER_SENT),
        ).fetchone()["n"]
        return {
            "mailbox": mailbox,
            "folder": folder,
            "unread": int(unread),
            "total": int(total),
            "outbox": int(outbox),
            "sent": int(sent),
            "address": addr_for_user(mailbox, self.domain),
        }

    def list_headers(
        self,
        mailbox: str,
        *,
        folder: str = FOLDER_INBOX,
        limit: int = 20,
        unread_only: bool = False,
    ) -> list[dict[str, Any]]:
        sql = """
            SELECT id, local_id, from_addr, to_addr, subject, created_at, is_read,
                   has_attachment, attachment_name, attachment_size, attachment_wifi_only,
                   folder
            FROM mail_messages
            WHERE mailbox = ? COLLATE NOCASE AND folder = ?
        """
        params: list[Any] = [mailbox, folder]
        if unread_only:
            sql += " AND is_read = 0"
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = self._conn.execute(sql, params).fetchall()
        return [self._header_dict(r) for r in rows]

    def _header_dict(self, row: sqlite3.Row) -> dict[str, Any]:
        data = {
            "id": row["id"],
            "local_id": row["local_id"],
            "from": row["from_addr"],
            "to": row["to_addr"],
            "subject": row["subject"],
            "created_at": row["created_at"],
            "read": bool(row["is_read"]),
            "has_attachment": bool(row["has_attachment"]),
            "attachment_name": row["attachment_name"],
            "attachment_size": row["attachment_size"],
            "attachment_wifi_only": bool(row["attachment_wifi_only"]),
        }
        try:
            data["folder"] = row["folder"]
        except (IndexError, KeyError):
            pass
        return data

    def get(
        self,
        mailbox: str,
        *,
        local_id: Optional[int] = None,
        message_id: Optional[str] = None,
        folder: str = FOLDER_INBOX,
        include_body: bool = True,
    ) -> Optional[dict[str, Any]]:
        if message_id:
            row = self._conn.execute(
                """
                SELECT * FROM mail_messages
                WHERE mailbox = ? COLLATE NOCASE AND id = ?
                """,
                (mailbox, message_id),
            ).fetchone()
        elif local_id is not None:
            row = self._conn.execute(
                """
                SELECT * FROM mail_messages
                WHERE mailbox = ? COLLATE NOCASE AND folder = ? AND local_id = ?
                """,
                (mailbox, folder, local_id),
            ).fetchone()
        else:
            return None
        if not row:
            return None
        data = self._header_dict(row)
        data["folder"] = row["folder"]
        data["in_reply_to"] = row["in_reply_to"]
        if include_body:
            data["body"] = row["body"]
        return data

    def mark(
        self,
        mailbox: str,
        *,
        local_id: Optional[int] = None,
        message_id: Optional[str] = None,
        folder: str = FOLDER_INBOX,
        read: Optional[bool] = None,
        delete: bool = False,
    ) -> Optional[dict[str, Any]]:
        msg = self.get(
            mailbox,
            local_id=local_id,
            message_id=message_id,
            folder=folder,
            include_body=False,
        )
        if not msg:
            return None
        if delete:
            self._conn.execute(
                "DELETE FROM mail_messages WHERE mailbox = ? COLLATE NOCASE AND id = ?",
                (mailbox, msg["id"]),
            )
            self._conn.commit()
            return {"deleted": True, "id": msg["id"], "local_id": msg["local_id"]}
        if read is not None:
            self._conn.execute(
                "UPDATE mail_messages SET is_read = ? WHERE id = ?",
                (1 if read else 0, msg["id"]),
            )
            self._conn.commit()
        return self.get(
            mailbox,
            message_id=msg["id"],
            include_body=False,
        )

    def _row_id_for(self, message_id: str, folder: str, mailbox: str) -> str:
        if folder == FOLDER_INBOX:
            return message_id
        if folder == FOLDER_SENT:
            return f"{message_id}:sent:{mailbox}"
        if folder == FOLDER_OUTBOX:
            return f"{message_id}:outbox:{mailbox}"
        return f"{message_id}:{folder}:{mailbox}"

    def _insert_copy(
        self,
        *,
        message_id: str,
        mailbox: str,
        folder: str,
        from_addr: str,
        to_addr: str,
        subject: str,
        body: str,
        in_reply_to: Optional[str] = None,
        is_read: bool = False,
        has_attachment: bool = False,
        attachment_name: Optional[str] = None,
        attachment_size: Optional[int] = None,
        attachment_wifi_only: bool = True,
        created_at: Optional[float] = None,
    ) -> dict[str, Any]:
        local_id = self._next_local_id(mailbox, folder)
        ts = created_at if created_at is not None else time.time()
        row_id = self._row_id_for(message_id, folder, mailbox)
        self._conn.execute(
            """
            INSERT INTO mail_messages (
                id, mailbox, folder, local_id, from_addr, to_addr, subject, body,
                created_at, is_read, in_reply_to, has_attachment, attachment_name,
                attachment_size, attachment_wifi_only
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row_id,
                mailbox,
                folder,
                local_id,
                from_addr,
                to_addr,
                subject,
                body,
                ts,
                1 if is_read else 0,
                in_reply_to,
                1 if has_attachment else 0,
                attachment_name,
                attachment_size,
                1 if attachment_wifi_only else 0,
            ),
        )
        self._conn.commit()
        return self.get(mailbox, message_id=row_id, include_body=True)  # type: ignore[return-value]

    def enqueue_outbox(
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
    ) -> dict[str, Any]:
        """Store outbound mail in OUTBOX (not yet delivered)."""
        mid = message_id or new_id()
        from_addr = addr_for_user(from_user, self.domain)
        to_user = user_from_addr(to_addr, self.domain)
        if not to_user:
            raise ValueError("invalid recipient")
        to_norm = addr_for_user(to_user, self.domain)
        has_att = bool(attachment_name)
        outbox = self._insert_copy(
            message_id=mid,
            mailbox=from_user,
            folder=FOLDER_OUTBOX,
            from_addr=from_addr,
            to_addr=to_norm,
            subject=subject,
            body=body,
            in_reply_to=in_reply_to,
            is_read=True,
            has_attachment=has_att,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
            attachment_wifi_only=True,
        )
        return {
            "message_id": mid,
            "outbox": outbox,
            "delivered_to": to_user,
            "queued": True,
        }

    def list_outbox(self, mailbox: str, *, limit: int = 50) -> list[dict[str, Any]]:
        return self.list_headers(mailbox, folder=FOLDER_OUTBOX, limit=limit)

    def delete_message_row(self, message_row_id: str) -> None:
        self._conn.execute("DELETE FROM mail_messages WHERE id = ?", (message_row_id,))
        self._conn.commit()

    def flush_outbox_item(
        self,
        mailbox: str,
        *,
        local_id: Optional[int] = None,
        message_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Move one OUTBOX item to SENT and deliver a copy to recipient INBOX."""
        item = self.get(
            mailbox,
            local_id=local_id,
            message_id=message_id,
            folder=FOLDER_OUTBOX,
            include_body=True,
        )
        if not item:
            raise ValueError("outbox message not found")

        # Logical mid is prefix before :outbox:
        logical_id = item["id"].split(":outbox:", 1)[0]
        to_user = user_from_addr(item["to"], self.domain)
        if not to_user:
            raise ValueError("invalid recipient on outbox item")

        sent = self._insert_copy(
            message_id=logical_id,
            mailbox=mailbox,
            folder=FOLDER_SENT,
            from_addr=item["from"],
            to_addr=item["to"],
            subject=item["subject"],
            body=item.get("body") or "",
            in_reply_to=item.get("in_reply_to"),
            is_read=True,
            has_attachment=bool(item.get("has_attachment")),
            attachment_name=item.get("attachment_name"),
            attachment_size=item.get("attachment_size"),
            attachment_wifi_only=bool(item.get("attachment_wifi_only", True)),
            created_at=item.get("created_at"),
        )
        inbox = self._insert_copy(
            message_id=logical_id,
            mailbox=to_user,
            folder=FOLDER_INBOX,
            from_addr=item["from"],
            to_addr=item["to"],
            subject=item["subject"],
            body=item.get("body") or "",
            in_reply_to=item.get("in_reply_to"),
            is_read=False,
            has_attachment=bool(item.get("has_attachment")),
            attachment_name=item.get("attachment_name"),
            attachment_size=item.get("attachment_size"),
            attachment_wifi_only=bool(item.get("attachment_wifi_only", True)),
            created_at=item.get("created_at"),
        )
        self.delete_message_row(item["id"])
        return {
            "message_id": logical_id,
            "sent": sent,
            "delivered_to": to_user,
            "inbox": inbox,
            "queued": False,
        }

    def flush_outbox(self, mailbox: str, *, limit: int = 50) -> list[dict[str, Any]]:
        items = self.list_outbox(mailbox, limit=limit)
        results = []
        # Flush oldest first
        for item in reversed(items):
            results.append(
                self.flush_outbox_item(mailbox, message_id=item["id"])
            )
        return results

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
        """Queue to OUTBOX; unless queue_only, immediately flush to SENT+INBOX."""
        queued = self.enqueue_outbox(
            from_user=from_user,
            to_addr=to_addr,
            subject=subject,
            body=body,
            message_id=message_id,
            in_reply_to=in_reply_to,
            attachment_name=attachment_name,
            attachment_size=attachment_size,
        )
        if queue_only:
            return queued
        return self.flush_outbox_item(
            from_user, message_id=queued["outbox"]["id"]
        )

    # --- Persistent Waylink push outbox ---

    def enqueue_push(self, node_id: str, envelope: dict[str, Any]) -> None:
        self._conn.execute(
            """
            INSERT INTO mail_push_outbox (node_id, envelope_json, created_at)
            VALUES (?, ?, ?)
            """,
            (node_id, json.dumps(envelope), time.time()),
        )
        self._conn.commit()

    def poll_pushes(self, node_id: str, *, max_items: int = 20) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT id, envelope_json FROM mail_push_outbox
            WHERE node_id = ?
            ORDER BY id ASC
            LIMIT ?
            """,
            (node_id, max_items),
        ).fetchall()
        if not rows:
            return []
        ids = [r["id"] for r in rows]
        placeholders = ",".join("?" * len(ids))
        self._conn.execute(
            f"DELETE FROM mail_push_outbox WHERE id IN ({placeholders})",
            ids,
        )
        self._conn.commit()
        return [json.loads(r["envelope_json"]) for r in rows]
