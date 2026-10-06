"""Set a Station account's password from the command line (the operator's
way back in when nobody can sign in).

    sudo waypost-set-password aj          (on the Pi; installed by install.sh)
    python -m server.admin.set_password aj   (with WAYPOST_* settings in the environment)

The
password is asked for twice, never on the command line. It does what a
sign-in with the new password does: the password hash, and the identity key
derived from it (the old key is revoked, so messages signed with it stop
being accepted — the same as a person changing their password).
"""

from __future__ import annotations

import getpass
import sys

from server.api.config import get_settings
from server.api.db import Database
from server.services.auth.passwords import hash_password
from server.services.auth.service import MIN_PASSWORD
from server.services.identity.certs import CommunityKey
from server.services.identity.service import IdentityService


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print("usage: python -m server.admin.set_password USERNAME", file=sys.stderr)
        return 2
    settings = get_settings()
    db = Database(settings.waypost_sqlite_path)
    user = db.get_user_by_username(argv[0].strip())
    if not user:
        print(f"no account named {argv[0]!r}", file=sys.stderr)
        return 1
    while True:
        a = getpass.getpass(f"New password for {user['username']} ({MIN_PASSWORD}+ characters): ")
        b = getpass.getpass("Again: ")
        if a != b:
            print("Those didn't match - try again.")
        elif len(a) < MIN_PASSWORD:
            print(f"At least {MIN_PASSWORD} characters (it's also what your identity key comes from).")
        else:
            break
    db.set_password_hash(user["username"], hash_password(a))
    identity = IdentityService(db.identity,
                               CommunityKey.load_or_create(settings.waypost_data_dir / "community.key"),
                               get_binding=db.dispatch.get_binding, get_user=db.get_user_by_username)
    identity.record_password(user["username"], a)
    print(f"Password set for {user['username']}. Sign in with it; Scouts signed in as "
          f"{user['username']} need to sign in again with the new one.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
