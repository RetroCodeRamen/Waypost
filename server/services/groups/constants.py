"""Groups protocol constants.

HTTP/portal-only in v1 — no Waylink ops registered, same precedent as
Rollcall (server/api/main.py never calls gateway.register for it either).
Groups is a management concern, not something a Pocket needs mid-hike.
"""

ROLE_MEMBER = "member"
ROLE_ADMIN = "admin"
ALLOWED_ROLES = {ROLE_MEMBER, ROLE_ADMIN}

MAX_NAME = 80
