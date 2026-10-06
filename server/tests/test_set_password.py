"""The operator's password reset (server/admin/set_password.py)."""

from __future__ import annotations

from server.admin import set_password as S
from server.api.db import Database
from server.services.auth.service import AuthService


def test_reset_lets_the_person_sign_in_and_records_their_key(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYPOST_SQLITE_PATH", str(tmp_path / "w.db"))
    monkeypatch.setenv("WAYPOST_DATA_DIR", str(tmp_path))
    db = Database(tmp_path / "w.db")
    db.ensure_user("aj", "AJ")
    answers = iter(["short", "short", "a long enough one", "a long enough one"])
    monkeypatch.setattr(S.getpass, "getpass", lambda prompt="": next(answers))
    assert S.main(["aj"]) == 0
    db = Database(tmp_path / "w.db")
    assert AuthService(db).login(username="aj", password="a long enough one")["token"]
    from server.services.identity import keys as K

    public, ident = db.identity.key_for("aj")  # the key derived from the new password
    assert public == K.public_key("aj", "a long enough one") and ident == K.identity_id(public)


def test_unknown_account(tmp_path, monkeypatch):
    monkeypatch.setenv("WAYPOST_SQLITE_PATH", str(tmp_path / "w.db"))
    monkeypatch.setenv("WAYPOST_DATA_DIR", str(tmp_path))
    assert S.main(["nobody"]) == 1
