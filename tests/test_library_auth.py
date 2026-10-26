"""API token tests (multi-user auth for the self-hosted library)."""

from library import db


def test_create_and_check_token(tmp_path):
    conn = db.open_db(tmp_path / "lib.db")
    plaintext = db.create_token(conn, "alice")
    assert plaintext and isinstance(plaintext, str)
    assert db.check_token(conn, plaintext) is True
    assert db.check_token(conn, "wrong") is False
    assert db.check_token(conn, "") is False


def test_tokens_are_stored_hashed(tmp_path):
    conn = db.open_db(tmp_path / "lib.db")
    plaintext = db.create_token(conn, "alice")
    rows = db.list_tokens(conn)
    assert [r["name"] for r in rows] == ["alice"]
    assert all(plaintext not in str(r) for r in rows)
    assert all("sha256" in r or len(r.get("token_sha256", "")) == 64
               for r in rows)


def test_revoke_token(tmp_path):
    conn = db.open_db(tmp_path / "lib.db")
    alice = db.create_token(conn, "alice")
    bob = db.create_token(conn, "bob")
    assert db.revoke_token(conn, "alice") is True
    assert db.check_token(conn, alice) is False
    assert db.check_token(conn, bob) is True
    assert db.revoke_token(conn, "nobody") is False
    assert [r["name"] for r in db.list_tokens(conn, include_revoked=True)] == \
        ["alice", "bob"]
    assert [r["name"] for r in db.list_tokens(conn)] == ["bob"]
