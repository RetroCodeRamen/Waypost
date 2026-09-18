"""Locker protocol constants — shared and personal files."""

OP_FILE_LIST = "FILE_LIST"
OP_FILE_INFO = "FILE_INFO"
OP_FILE_DELETE = "FILE_DELETE"

# Early alpha defaults — Station Wi‑Fi, not LoRa bodies
MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MiB
MAX_NAME_LEN = 180
MAX_NOTE_LEN = 240

SCOPE_SHARED = "shared"
SCOPE_PERSONAL = "personal"
ALLOWED_SCOPES = {SCOPE_SHARED, SCOPE_PERSONAL}
