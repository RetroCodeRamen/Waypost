"""SQLite persistence for Station core, Dispatch, and Postbox."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Optional

from server.services.beacon.store import BeaconStore
from server.services.commons.store import CommonsStore
from server.services.dispatch.store import DispatchStore
from server.services.locker.store import LockerStore
from server.services.mail.store import MailStore
from server.services.noticeboard.store import NoticeStore


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
    display_name TEXT NOT NULL,
    status TEXT DEFAULT '',
    bio TEXT DEFAULT '',
    password_hash TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(username);

CREATE TABLE IF NOT EXISTS pairing_codes (
    code TEXT PRIMARY KEY,
    username TEXT NOT NULL COLLATE NOCASE,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used_at REAL
);

CREATE INDEX IF NOT EXISTS idx_pairing_username ON pairing_codes(username);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Database:
    def __init__(self, path: Path, *, locker_root: Optional[Path] = None) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._migrate()
        self._conn.commit()
        self.dispatch = DispatchStore(self._conn)
        self.mail = MailStore(self._conn)
        self.commons = CommonsStore(self._conn)
        self.noticeboard = NoticeStore(self._conn)
        self.beacon = BeaconStore(self._conn)
        root = locker_root or (path.parent / "locker")
        self.locker = LockerStore(self._conn, root)

    def _migrate(self) -> None:
        cols = {
            r["name"]
            for r in self._conn.execute("PRAGMA table_info(users)").fetchall()
        }
        if "password_hash" not in cols:
            self._conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")

    def close(self) -> None:
        self._conn.close()

    def health(self) -> dict[str, Any]:
        row = self._conn.execute("SELECT 1 AS ok").fetchone()
        return {"sqlite": bool(row), "path": str(self.path)}

    def create_user(
        self,
        username: str,
        display_name: str,
        *,
        password_hash: Optional[str] = None,
    ) -> dict[str, Any]:
        cur = self._conn.execute(
            "INSERT INTO users (username, display_name, password_hash) VALUES (?, ?, ?)",
            (username, display_name, password_hash),
        )
        self._conn.commit()
        return self.get_user_by_id(cur.lastrowid)  # type: ignore[arg-type]

    def set_password_hash(self, username: str, password_hash: str) -> None:
        self._conn.execute(
            "UPDATE users SET password_hash = ? WHERE username = ? COLLATE NOCASE",
            (password_hash, username),
        )
        self._conn.commit()

    def get_user_by_id(self, user_id: int) -> Optional[dict[str, Any]]:
        row = self._conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def get_user_by_username(self, username: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM users WHERE username = ? COLLATE NOCASE",
            (username,),
        ).fetchone()
        return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT id, username, display_name, status, bio, created_at FROM users ORDER BY username"
        ).fetchall()
        return [dict(r) for r in rows]

    def ensure_user(self, username: str, display_name: Optional[str] = None) -> dict[str, Any]:
        existing = self.get_user_by_username(username)
        if existing:
            return existing
        return self.create_user(username, display_name or username)

    def create_session(
        self, *, token: str, username: str, created_at: float, expires_at: float
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sessions (token, username, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (token, username, created_at, expires_at),
        )
        self._conn.commit()

    def get_session(self, token: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        self._conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        self._conn.commit()

    def create_pairing_code(
        self, *, code: str, username: str, created_at: float, expires_at: float
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO pairing_codes (code, username, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (code, username, created_at, expires_at),
        )
        self._conn.commit()

    def get_pairing_code(self, code: str) -> Optional[dict[str, Any]]:
        row = self._conn.execute(
            "SELECT * FROM pairing_codes WHERE code = ?", (code,)
        ).fetchone()
        return dict(row) if row else None

    def mark_pairing_code_used(self, code: str, *, used_at: float) -> None:
        self._conn.execute(
            "UPDATE pairing_codes SET used_at = ? WHERE code = ?", (used_at, code)
        )
        self._conn.commit()
