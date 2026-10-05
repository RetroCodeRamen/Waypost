"""SQLite store for people's identity keys and the certificates Station has
issued for them.

``identities`` holds each person's current key (derived from username +
password, keys.py). Certificates share one serial space (``certs.serial``).
Only fields are stored: signatures are recomputed when served (Ed25519 is
deterministic, so a certificate is always served with the same bytes).
"""

from __future__ import annotations

import sqlite3
import time
from typing import Any, Optional

IDENTITY_SCHEMA = """
CREATE TABLE IF NOT EXISTS identities (
    username TEXT PRIMARY KEY COLLATE NOCASE,
    identity_id BLOB NOT NULL UNIQUE,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS certs (
    serial INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,                 -- id | rev
    username TEXT COLLATE NOCASE,
    identity_id BLOB,
    display_name TEXT,                  -- id
    node_id TEXT,                       -- (unused since 2026-10-05: device certificates)
    signing_key BLOB,                   -- (unused since 2026-10-05)
    device_hash BLOB,                   -- (unused since 2026-10-05)
    revokes INTEGER,                    -- rev: the serial it revokes
    issued INTEGER NOT NULL,
    expires INTEGER,                    -- id
    revoked_at INTEGER                  -- id: set when revoked
);
CREATE INDEX IF NOT EXISTS certs_user ON certs (kind, username);
"""


class IdentityStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.executescript(IDENTITY_SCHEMA)
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(identities)").fetchall()}
        if "public_key" not in cols:
            # Before 2026-10-05 identity ids were random; rows without a key
            # are ignored until the person signs in and gets a real one.
            self._conn.execute("ALTER TABLE identities ADD COLUMN public_key BLOB")
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(certs)").fetchall()}
        if "public_key" not in cols:
            self._conn.execute("ALTER TABLE certs ADD COLUMN public_key BLOB")
        self._conn.execute("CREATE INDEX IF NOT EXISTS certs_ident ON certs (kind, identity_id)")

    # -- identity keys --------------------------------------------------------

    def key_for(self, username: str) -> Optional[tuple[bytes, bytes]]:
        """(public key, identity id) of the person's current key, if known."""
        row = self._conn.execute(
            "SELECT public_key, identity_id FROM identities WHERE username = ? AND public_key IS NOT NULL",
            (username,),
        ).fetchone()
        return (bytes(row[0]), bytes(row[1])) if row else None

    def set_key(self, username: str, public_key: bytes, identity_id: bytes) -> Optional[bytes]:
        """Records the person's key. Returns the previous identity id when it
        changed (a new password = a new identity), else None."""
        old = self.key_for(username)
        if old and old[0] == bytes(public_key):
            return None
        self._conn.execute(
            """INSERT INTO identities (username, identity_id, public_key, created_at) VALUES (?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET identity_id = excluded.identity_id,
                   public_key = excluded.public_key, created_at = excluded.created_at""",
            (username, bytes(identity_id), bytes(public_key), time.time()),
        )
        self._conn.commit()
        return old[1] if old else None

    # -- certificates -------------------------------------------------------

    def _insert(self, **fields: Any) -> dict[str, Any]:
        cols = ", ".join(fields)
        marks = ", ".join("?" for _ in fields)
        cur = self._conn.execute(f"INSERT INTO certs ({cols}) VALUES ({marks})", tuple(fields.values()))
        self._conn.commit()
        return self.get(int(cur.lastrowid))

    def get(self, serial: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM certs WHERE serial = ?", (serial,)).fetchone()
        return dict(row) if row else None

    def add_identity(self, *, username: str, identity_id: bytes, display_name: str, public_key: bytes,
                     issued: int, expires: int) -> dict[str, Any]:
        return self._insert(kind="id", username=username, identity_id=bytes(identity_id),
                            display_name=display_name, public_key=bytes(public_key),
                            issued=issued, expires=expires)

    def latest_identity(self, username: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            """SELECT * FROM certs WHERE kind = 'id' AND username = ? AND revoked_at IS NULL
               AND public_key IS NOT NULL ORDER BY serial DESC LIMIT 1""",
            (username,),
        ).fetchone()
        return dict(row) if row else None

    def by_identity_id(self, identity_id: bytes) -> Optional[dict[str, Any]]:
        """The newest certificate ever issued for this identity id —
        revoked ones included, so callers can tell 'revoked' from 'unknown'."""
        row = self._conn.execute(
            "SELECT * FROM certs WHERE kind = 'id' AND identity_id = ? ORDER BY serial DESC LIMIT 1",
            (bytes(identity_id),),
        ).fetchone()
        return dict(row) if row else None

    def revoke_identity(self, identity_id: bytes, now: int) -> int:
        """Revokes every live certificate for this identity id."""
        rows = self._conn.execute(
            "SELECT serial FROM certs WHERE kind = 'id' AND identity_id = ? AND revoked_at IS NULL",
            (bytes(identity_id),),
        ).fetchall()
        return sum(1 for r in rows if self.revoke(int(r[0]), now))

    def revoke(self, serial: int, now: int) -> Optional[dict[str, Any]]:
        """Marks `serial` revoked and records a revocation certificate."""
        cur = self._conn.execute(
            "UPDATE certs SET revoked_at = ? WHERE serial = ? AND revoked_at IS NULL", (now, serial)
        )
        if cur.rowcount == 0:
            self._conn.commit()
            return None
        return self._insert(kind="rev", revokes=serial, issued=now)

    def revocations(self, now: int) -> list[dict[str, Any]]:
        """Revocations still worth spreading: the revoked certificate hasn't
        expired yet (after that nobody accepts it anyway)."""
        rows = self._conn.execute(
            """SELECT r.* FROM certs r JOIN certs c ON c.serial = r.revokes
               WHERE r.kind = 'rev' AND c.expires > ? ORDER BY r.serial""",
            (now,),
        ).fetchall()
        return [dict(r) for r in rows]

    def usernames_with_keys(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT username FROM identities WHERE public_key IS NOT NULL ORDER BY username"
        ).fetchall()
        return [str(r[0]) for r in rows]

    def owner_of(self, identity_id: bytes) -> Optional[str]:
        row = self.by_identity_id(identity_id)
        return str(row["username"]) if row else None
