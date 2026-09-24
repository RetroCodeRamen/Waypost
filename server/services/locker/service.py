"""Locker service — shared and personal file storage on the Station."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional

from server.services.locker.constants import (
    ALLOWED_SCOPES,
    MAX_NAME_LEN,
    MAX_NOTE_LEN,
    MAX_UPLOAD_BYTES,
    OP_FILE_DELETE,
    OP_FILE_INFO,
    OP_FILE_LIST,
    SCOPE_GROUP,
    SCOPE_PERSONAL,
    SCOPE_SHARED,
)
from server.services.locker.store import LockerStore
from shared.protocol.envelope import Envelope, Flags, new_id

_SAFE_NAME = re.compile(r"[^\w.\- ()\[\]]+", re.UNICODE)


def sanitize_filename(name: str) -> str:
    base = Path(name or "file").name.strip() or "file"
    cleaned = _SAFE_NAME.sub("_", base).strip("._") or "file"
    if len(cleaned) > MAX_NAME_LEN:
        stem = Path(cleaned).stem[: MAX_NAME_LEN - 20]
        suffix = Path(cleaned).suffix[:20]
        cleaned = stem + suffix
    return cleaned


def format_size(n: int) -> str:
    n = int(n)
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


class LockerService:
    def __init__(
        self,
        store: LockerStore,
        *,
        is_group_member: Optional[Callable[[str, str], bool]] = None,
    ) -> None:
        self.store = store
        # Injected rather than importing GroupsStore directly — same
        # cross-service lookup pattern as NoticeboardService's get_binding.
        self._is_group_member = is_group_member or (lambda _gid, _username: False)

    def list_files(
        self,
        *,
        scope: Optional[str] = None,
        owner: Optional[str] = None,
        viewer: Optional[str] = None,
        limit: int = 100,
        group_id: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        items = self.store.list_files(
            scope=scope,
            owner=owner,
            viewer=viewer,
            limit=limit,
            is_group_member=self._is_group_member,
            group_id=group_id,
        )
        return [self._public(i) for i in items]

    def info(self, file_id: str, *, viewer: Optional[str] = None) -> Optional[dict[str, Any]]:
        item = self.store.get(file_id)
        if not item or item.get("deleted"):
            return None
        if not self._can_access(item, viewer):
            return None
        return self._public(item)

    def disk_path(self, file_id: str, *, viewer: Optional[str] = None) -> Optional[Path]:
        item = self.store.get(file_id)
        if not item or item.get("deleted"):
            return None
        if not self._can_access(item, viewer):
            return None
        path = self.store.path_for(item["stored_name"])
        if not path.is_file():
            return None
        return path

    def upload(
        self,
        *,
        owner: str,
        filename: str,
        content_type: str,
        data: bytes | BinaryIO,
        scope: str = SCOPE_SHARED,
        note: str = "",
        file_id: Optional[str] = None,
        group_id: Optional[str] = None,
    ) -> dict[str, Any]:
        owner = owner.strip()
        scope = (scope or SCOPE_SHARED).strip().lower()
        note = (note or "").strip()
        if not owner:
            raise ValueError("owner required")
        if scope not in ALLOWED_SCOPES:
            raise ValueError("scope must be shared, personal, or group")
        if len(note) > MAX_NOTE_LEN:
            raise ValueError(f"note too long (max {MAX_NOTE_LEN})")
        if scope == SCOPE_GROUP:
            group_id = (group_id or "").strip()
            if not group_id:
                raise ValueError("group_id required for group scope")
            if not self._is_group_member(group_id, owner):
                raise ValueError("owner must be a member of the group")
        else:
            group_id = None

        safe_name = sanitize_filename(filename)
        if isinstance(data, (bytes, bytearray)):
            blob = bytes(data)
        else:
            blob = data.read()
        size = len(blob)
        if size <= 0:
            raise ValueError("empty file")
        if size > MAX_UPLOAD_BYTES:
            raise ValueError(f"file too large (max {format_size(MAX_UPLOAD_BYTES)})")

        fid = file_id or new_id()
        stored = f"{fid}_{safe_name}"
        dest = self.store.path_for(stored)
        dest.write_bytes(blob)

        item = self.store.create(
            owner=owner,
            scope=scope,
            filename=safe_name,
            content_type=content_type or "application/octet-stream",
            size=size,
            stored_name=stored,
            note=note,
            file_id=fid,
            group_id=group_id,
        )
        return self._public(item)

    def delete(self, file_id: str, *, actor: str) -> Optional[dict[str, Any]]:
        item = self.store.get(file_id)
        if not item:
            return None
        if item["owner"].lower() != actor.strip().lower():
            raise PermissionError("only the uploader can delete this file")
        deleted = self.store.soft_delete(file_id)
        # Best-effort remove blob
        if deleted:
            path = self.store.path_for(deleted["stored_name"])
            try:
                if path.is_file():
                    path.unlink()
            except OSError:
                pass
        return self._public(deleted) if deleted else None

    def count_shared(self) -> int:
        return self.store.count_shared()

    def handle_rpc(self, envelope: Envelope) -> Envelope:
        """Metadata only over Waylink — never send file bodies."""
        op = envelope.op
        payload = envelope.payload if isinstance(envelope.payload, dict) else {}
        viewer = str(payload.get("viewer") or envelope.src or "")
        try:
            if op == OP_FILE_LIST:
                files = self.list_files(
                    scope=payload.get("scope"),
                    owner=payload.get("owner"),
                    viewer=viewer or None,
                    limit=int(payload.get("limit") or 50),
                )
                return envelope.make_response(op=op, payload={"files": files})
            if op == OP_FILE_INFO:
                info = self.info(str(payload.get("id") or ""), viewer=viewer or None)
                if not info:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"file": info})
            if op == OP_FILE_DELETE:
                deleted = self.delete(str(payload.get("id") or ""), actor=viewer)
                if not deleted:
                    return envelope.make_response(
                        op=op, payload={"error": "not_found"}, error=True
                    )
                return envelope.make_response(op=op, payload={"file": deleted})
            return envelope.make_response(
                op=op,
                payload={"error": f"unknown_op:{op}"},
                flags=Flags.RESPONSE,
                error=True,
            )
        except PermissionError as exc:
            return envelope.make_response(op=op, payload={"error": str(exc)}, error=True)
        except ValueError as exc:
            return envelope.make_response(op=op, payload={"error": str(exc)}, error=True)

    def _can_access(self, item: dict[str, Any], viewer: Optional[str]) -> bool:
        if item["scope"] == SCOPE_SHARED:
            return True
        if item["scope"] == SCOPE_PERSONAL:
            return bool(viewer) and viewer.lower() == item["owner"].lower()
        if item["scope"] == SCOPE_GROUP:
            gid = item.get("group_id")
            return bool(viewer) and bool(gid) and self._is_group_member(gid, viewer)
        return False

    @staticmethod
    def _public(item: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        if not item:
            return None
        return {
            "id": item["id"],
            "owner": item["owner"],
            "scope": item["scope"],
            "group_id": item.get("group_id"),
            "filename": item["filename"],
            "content_type": item["content_type"],
            "size": item["size"],
            "size_label": format_size(item["size"]),
            "note": item.get("note") or "",
            "created_at": item["created_at"],
            "deleted": bool(item.get("deleted")),
            "download_path": f"/api/locker/files/{item['id']}/download",
        }
