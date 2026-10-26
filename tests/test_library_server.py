"""Library HTTP API tests (spins a real server on an ephemeral port)."""

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from library.server import LibraryServer

TOKEN = "test-token"


def start_server(tmp_path, token=TOKEN):
    server = LibraryServer(tmp_path / "store", tmp_path / "lib.db",
                            token=token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.ready.wait(timeout=10)
    return server, f"http://127.0.0.1:{server.port}"


def call(base, path, *, token: str | None = TOKEN, data=None, params=None,
         content_type="application/octet-stream"):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method="GET" if data is None else "POST")
    if token is not None:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", content_type)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_health_needs_no_auth(tmp_path):
    _, base = start_server(tmp_path)
    status, body = call(base, "/health", token=None)
    assert status == 200
    assert json.loads(body) == {"ok": True}


def test_auth_required(tmp_path):
    _, base = start_server(tmp_path)
    assert call(base, "/api/v1/assets", token=None)[0] == 401
    assert call(base, "/api/v1/assets", token="wrong")[0] == 401


def test_multiple_tokens_and_revocation(tmp_path):
    from library import db as library_db
    _, base = start_server(tmp_path)
    db_path = tmp_path / "lib.db"
    conn = library_db.open_db(str(db_path))
    try:
        second = library_db.create_token(conn, "second")
    finally:
        conn.close()
    assert call(base, "/api/v1/assets", token=TOKEN)[0] == 200
    assert call(base, "/api/v1/assets", token=second)[0] == 200
    conn = library_db.open_db(str(db_path))
    try:
        assert library_db.revoke_token(conn, "second") is True
    finally:
        conn.close()
    assert call(base, "/api/v1/assets", token=second)[0] == 401
    assert call(base, "/api/v1/assets", token=TOKEN)[0] == 200


def test_upload_list_download_roundtrip(tmp_path):
    _, base = start_server(tmp_path)
    status, body = call(base, "/api/v1/assets", token=TOKEN, data=b"png-bytes",
                        params={"name": "hero.png", "kind": "texture",
                                "importer": "texture", "tags": "hero,player"})
    assert status == 201, body
    asset_id = json.loads(body)["id"]
    status, body = call(base, "/api/v1/assets", token=TOKEN)
    assert status == 200
    assets = json.loads(body)["assets"]
    assert len(assets) == 1 and assets[0]["name"] == "hero.png"
    assert assets[0]["params"] == {}
    status, body = call(base, f"/api/v1/assets/{asset_id}/blob", token=TOKEN)
    assert status == 200 and body == b"png-bytes"


def test_list_filters(tmp_path):
    _, base = start_server(tmp_path)
    call(base, "/api/v1/assets", token=TOKEN, data=b"a",
         params={"name": "hero.png", "kind": "texture", "tags": "game"})
    call(base, "/api/v1/assets", token=TOKEN, data=b"b",
         params={"name": "click.wav", "kind": "audio"})
    _, body = call(base, "/api/v1/assets", token=TOKEN, params={"kind": "audio"})
    assert [a["name"] for a in json.loads(body)["assets"]] == ["click.wav"]
    _, body = call(base, "/api/v1/assets", token=TOKEN, params={"tag": "game"})
    assert [a["name"] for a in json.loads(body)["assets"]] == ["hero.png"]
    _, body = call(base, "/api/v1/assets", token=TOKEN, params={"q": "zzz"})
    assert json.loads(body)["assets"] == []
