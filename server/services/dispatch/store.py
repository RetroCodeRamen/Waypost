"""Dispatch persistence — conversations, messages, offline push queue."""

from __future__ import annotations

import re
import sqlite3
import time
from typing import Any, Optional

from server.services.dispatch.constants import DELIVERY_QUEUED
from shared.protocol.envelope import new_id


DISPATCH_SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL DEFAULT 'direct',
    title TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_members (
    conversation_id TEXT NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    PRIMARY KEY (conversation_id, username),
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT NOT NULL,
    sender TEXT NOT NULL COLLATE NOCASE,
    body TEXT NOT NULL,
    created_at REAL NOT NULL,
    transport TEXT,
    delivery_state TEXT NOT NULL DEFAULT 'QUEUED',
    FOREIGN KEY (conversation_id) REFERENCES conversations(id)
);

CREATE INDEX IF NOT EXISTS idx_messages_conv_time
    ON messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS device_bindings (
    node_id TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE,
    created_at REAL NOT NULL,
    transport_dest TEXT
);

CREATE TABLE IF NOT EXISTS pending_pushes (
    message_id TEXT NOT NULL,
    username TEXT NOT NULL COLLATE NOCASE,
    created_at REAL NOT NULL,
    PRIMARY KEY (message_id, username),
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_pending_user ON pending_pushes(username);

CREATE TABLE IF NOT EXISTS courier_queue (
    message_id TEXT NOT NULL,
    dest TEXT NOT NULL,
    created_at REAL NOT NULL,
    PRIMARY KEY (message_id, dest),
    FOREIGN KEY (message_id) REFERENCES messages(id)
);

CREATE INDEX IF NOT EXISTS idx_courier_dest ON courier_queue(dest);
"""

_SLUG_RE = re.compile(r"[^a-z0-9\-]+")


def direct_conversation_id(user_a: str, user_b: str) -> str:
    a, b = sorted([user_a.lower(), user_b.lower()])
    return f"dm:{a}:{b}"


def room_conversation_id(slug: str) -> str:
    clean = _SLUG_RE.sub("-", slug.strip().lower()).strip("-")
    if not clean:
        clean = new_id()[:8]
    return f"room:{clean}"


class DispatchStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(DISPATCH_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cols = {
            r[1]
            for r in self._conn.execute("PRAGMA table_info(device_bindings)").fetchall()
        }
        if "transport_dest" not in cols:
            self._conn.execute(
                "ALTER TABLE device_bindings ADD COLUMN transport_dest TEXT"
            )

    def bind_device(
        self,
        node_id: str,
        username: str,
        *,
        transport_dest: Optional[str] = None,
    ) -> dict[str, Any]:
        now = time.time()
        self._conn.execute(
            """
            INSERT INTO device_bindings (node_id, username, created_at, transport_dest)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(node_id) DO UPDATE SET
                username = excluded.username,
                transport_dest = COALESCE(excluded.transport_dest, device_bindings.transport_dest)
            """,
            (node_id, username, now, transport_dest),
        )
        self._conn.commit()
        out = {"node_id": node_id, "username": username}
        if transport_dest:
            out["transport_dest"] = transport_dest
        else:
            row = self.get_binding(node_id)
            if row and row.get("transport_dest"):
                out["transport_dest"] = row["transport_dest"]
        return out

    def get_binding(self, node_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT node_id, username, created_at, transport_dest FROM device_bindings WHERE node_id = ?",
            (node_id,),
        ).fetchone()
        return dict(row) if row else None

    def transport_dest_for(self, node_id: str) -> Optional[str]:
        row = self.get_binding(node_id)
        if not row:
            return None
        dest = row.get("transport_dest")
        return str(dest) if dest else None

    def nodes_for_user(self, username: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT node_id FROM device_bindings WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchall()
        return [r["node_id"] for r in rows]

    def unbind_user(self, username: str) -> int:
        cur = self._conn.execute(
            "DELETE FROM device_bindings WHERE username = ? COLLATE NOCASE",
            (username,),
        )
        self._conn.commit()
        return int(cur.rowcount or 0)

    def unbind_device(self, node_id: str) -> bool:
        cur = self._conn.execute(
            "DELETE FROM device_bindings WHERE node_id = ?",
            (node_id,),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def ensure_direct(self, user_a: str, user_b: str) -> dict[str, Any]:
        cid = direct_conversation_id(user_a, user_b)
        existing = self.get_conversation(cid)
        if existing:
            return existing
        now = time.time()
        title = f"{user_a} ↔ {user_b}"
        self._conn.execute(
            "INSERT INTO conversations (id, kind, title, created_at, updated_at) VALUES (?, 'direct', ?, ?, ?)",
            (cid, title, now, now),
        )
        for u in (user_a, user_b):
            self._conn.execute(
                "INSERT INTO conversation_members (conversation_id, username) VALUES (?, ?)",
                (cid, u),
            )
        self._conn.commit()
        return self.get_conversation(cid)  # type: ignore[return-value]

    def create_room(
        self,
        *,
        title: str,
        members: list[str],
        slug: Optional[str] = None,
    ) -> dict[str, Any]:
        cid = room_conversation_id(slug or title)
        existing = self.get_conversation(cid)
        if existing:
            # Ensure membership for all requested members
            for u in members:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO conversation_members (conversation_id, username)
                    VALUES (?, ?)
                    """,
                    (cid, u),
                )
            self._conn.commit()
            return self.get_conversation(cid)  # type: ignore[return-value]

        now = time.time()
        self._conn.execute(
            "INSERT INTO conversations (id, kind, title, created_at, updated_at) VALUES (?, 'room', ?, ?, ?)",
            (cid, title, now, now),
        )
        for u in members:
            self._conn.execute(
                "INSERT INTO conversation_members (conversation_id, username) VALUES (?, ?)",
                (cid, u),
            )
        self._conn.commit()
        return self.get_conversation(cid)  # type: ignore[return-value]

    def add_room_member(self, conversation_id: str, username: str) -> Optional[dict[str, Any]]:
        conv = self.get_conversation(conversation_id)
        if not conv or conv["kind"] != "room":
            return None
        self._conn.execute(
            """
            INSERT OR IGNORE INTO conversation_members (conversation_id, username)
            VALUES (?, ?)
            """,
            (conversation_id, username),
        )
        self._conn.commit()
        return self.get_conversation(conversation_id)

    def get_conversation(self, conversation_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
        ).fetchone()
        if not row:
            return None
        members = self._conn.execute(
            "SELECT username FROM conversation_members WHERE conversation_id = ? ORDER BY username",
            (conversation_id,),
        ).fetchall()
        data = dict(row)
        data["members"] = [m["username"] for m in members]
        return data

    def list_conversations(self, username: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT c.* FROM conversations c
            JOIN conversation_members m ON m.conversation_id = c.id
            WHERE m.username = ? COLLATE NOCASE
            ORDER BY c.updated_at DESC
            """,
            (username,),
        ).fetchall()
        result = []
        for row in rows:
            conv = dict(row)
            members = self._conn.execute(
                "SELECT username FROM conversation_members WHERE conversation_id = ?",
                (conv["id"],),
            ).fetchall()
            conv["members"] = [m["username"] for m in members]
            last = self._conn.execute(
                """
                SELECT id, sender, body, created_at, transport, delivery_state
                FROM messages WHERE conversation_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (conv["id"],),
            ).fetchone()
            conv["last_message"] = dict(last) if last else None
            result.append(conv)
        return result

    def add_message(
        self,
        *,
        conversation_id: str,
        sender: str,
        body: str,
        message_id: Optional[str] = None,
        transport: Optional[str] = None,
        delivery_state: str = DELIVERY_QUEUED,
        created_at: Optional[float] = None,
    ) -> tuple[dict[str, Any], bool]:
        mid = message_id or new_id()
        existing = self._conn.execute(
            "SELECT * FROM messages WHERE id = ?", (mid,)
        ).fetchone()
        if existing:
            return dict(existing), False

        ts = created_at if created_at is not None else time.time()
        self._conn.execute(
            """
            INSERT INTO messages
                (id, conversation_id, sender, body, created_at, transport, delivery_state)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (mid, conversation_id, sender, body, ts, transport, delivery_state),
        )
        self._conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (ts, conversation_id),
        )
        self._conn.commit()
        row = self._conn.execute("SELECT * FROM messages WHERE id = ?", (mid,)).fetchone()
        return dict(row), True

    def list_messages(
        self,
        conversation_id: str,
        *,
        limit: int = 50,
        after_ts: Optional[float] = None,
    ) -> list[dict[str, Any]]:
        if after_ts is not None:
            rows = self._conn.execute(
                """
                SELECT * FROM messages
                WHERE conversation_id = ? AND created_at > ?
                ORDER BY created_at ASC LIMIT ?
                """,
                (conversation_id, after_ts, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT * FROM messages WHERE conversation_id = ?
                ORDER BY created_at DESC LIMIT ?
                """,
                (conversation_id, limit),
            ).fetchall()
            rows = list(reversed(rows))
        return [dict(r) for r in rows]

    def get_message(self, message_id: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM messages WHERE id = ?", (message_id,)
        ).fetchone()
        return dict(row) if row else None

    def set_delivery_state(self, message_id: str, state: str) -> Optional[dict[str, Any]]:
        self._conn.execute(
            "UPDATE messages SET delivery_state = ? WHERE id = ?",
            (state, message_id),
        )
        self._conn.commit()
        return self.get_message(message_id)

    def member_usernames(self, conversation_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT username FROM conversation_members WHERE conversation_id = ?",
            (conversation_id,),
        ).fetchall()
        return [r["username"] for r in rows]

    def is_member(self, conversation_id: str, username: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1 FROM conversation_members
            WHERE conversation_id = ? AND username = ? COLLATE NOCASE
            """,
            (conversation_id, username),
        ).fetchone()
        return row is not None

    def queue_pending_push(self, message_id: str, username: str) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO pending_pushes (message_id, username, created_at)
            VALUES (?, ?, ?)
            """,
            (message_id, username, time.time()),
        )
        self._conn.commit()

    def list_pending_for_user(self, username: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT p.message_id, p.username, p.created_at, m.*
            FROM pending_pushes p
            JOIN messages m ON m.id = p.message_id
            WHERE p.username = ? COLLATE NOCASE
            ORDER BY m.created_at ASC
            """,
            (username,),
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_pending(self, message_id: str, username: str) -> None:
        self._conn.execute(
            "DELETE FROM pending_pushes WHERE message_id = ? AND username = ? COLLATE NOCASE",
            (message_id, username),
        )
        self._conn.commit()

    def pending_usernames_for_message(self, message_id: str) -> list[str]:
        rows = self._conn.execute(
            "SELECT username FROM pending_pushes WHERE message_id = ?",
            (message_id,),
        ).fetchall()
        return [r["username"] for r in rows]

    def count_pending(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) AS n FROM pending_pushes").fetchone()
        return int(row["n"] if row else 0)

    def count_pending_by_user(self) -> dict[str, int]:
        rows = self._conn.execute(
            """
            SELECT username, COUNT(*) AS n FROM pending_pushes
            GROUP BY username COLLATE NOCASE
            """
        ).fetchall()
        return {str(r["username"]): int(r["n"]) for r in rows}

    # -- Courier queue (outbound carry: this node -> dest, e.g. peer or "station") --

    def queue_courier(self, message_id: str, dest: str) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO courier_queue (message_id, dest, created_at)
            VALUES (?, ?, ?)
            """,
            (message_id, dest, time.time()),
        )
        self._conn.commit()

    def list_courier_pending(self, dest: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT c.message_id, c.dest, c.created_at AS courier_created_at, m.*
            FROM courier_queue c
            JOIN messages m ON m.id = c.message_id
            WHERE c.dest = ?
            ORDER BY m.created_at ASC
            """,
            (dest,),
        ).fetchall()
        return [dict(r) for r in rows]

    def list_courier_all(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT c.message_id, c.dest, c.created_at AS courier_created_at, m.*
            FROM courier_queue c
            JOIN messages m ON m.id = c.message_id
            ORDER BY m.created_at ASC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_courier(self, message_id: str, dest: str) -> None:
        self._conn.execute(
            "DELETE FROM courier_queue WHERE message_id = ? AND dest = ?",
            (message_id, dest),
        )
        self._conn.commit()
