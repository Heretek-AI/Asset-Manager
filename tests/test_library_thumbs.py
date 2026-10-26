"""Thumbnail column migration + server thumbnail tests."""

import base64
import json
import sqlite3
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

import library.db as db
from library.server import LibraryServer


def _old_schema(path):
    conn = sqlite3.connect(str(path))
    conn.execute("CREATE TABLE assets("
                 "id INTEGER PRIMARY KEY, name TEXT NOT NULL,"
                 " blob_sha256 TEXT NOT NULL, size_bytes INTEGER NOT NULL,"
                 " kind TEXT NOT NULL DEFAULT 'raw',"
                 " godot_importer TEXT,"
                 " params_json TEXT NOT NULL DEFAULT '{}',"
                 " tags_json TEXT NOT NULL DEFAULT '[]',"
                 " created_at TEXT NOT NULL DEFAULT (datetime('now')))")
    conn.execute("INSERT INTO assets(name, blob_sha256, size_bytes)"
                 " VALUES ('old.png', 'ab', 3)")
    conn.commit()
    conn.close()


def test_old_db_gains_thumbnail_column(tmp_path):
    path = tmp_path / "lib.db"
    _old_schema(path)
    conn = db.open_db(path)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)")]
        assert "thumbnail_sha256" in cols
        row = db.get_asset(conn, 1)
        assert row["thumbnail_sha256"] is None
        assert row["name"] == "old.png"
    finally:
        conn.close()


def test_new_db_has_thumbnail_column(tmp_path):
    conn = db.open_db(tmp_path / "lib.db")
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(assets)")]
        assert "thumbnail_sha256" in cols
    finally:
        conn.close()


def _png_bytes() -> bytes:
    return base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def _start(tmp_path):
    server = LibraryServer(tmp_path / "store", tmp_path / "lib.db",
                           token="secret")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.ready.wait(timeout=10)
    return f"http://127.0.0.1:{server.port}"


def _get(base, path, token="secret"):
    req = urllib.request.Request(base + path)
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers), exc.read()


def _post(base, path, data=b"", params=None, token="secret"):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def test_image_upload_generates_thumbnail(tmp_path):
    import shutil
    if shutil.which("ffmpeg") is None and shutil.which("magick") is None:
        pytest.skip("no thumbnail engine on PATH")
    base = _start(tmp_path)
    status, body = _post(base, "/api/v1/assets", data=_png_bytes(),
                         params={"name": "hero.png", "kind": "texture"})
    assert status == 201, body
    asset_id = json.loads(body)["id"]
    listed = {a["id"]: a for a in json.loads(_list(base))["assets"]}
    assert listed[asset_id]["thumbnail_sha256"] is not None
    status, headers, blob = _get(base, f"/api/v1/assets/{asset_id}/thumbnail")
    assert status == 200, blob[:100]
    assert headers.get("Content-Type") == "image/png"
    assert headers.get("Access-Control-Allow-Origin") == "*"
    assert blob[:8] == b"\x89PNG\r\n\x1a\n"


def _list(base):
    status, _, body = _get(base, "/api/v1/assets")
    assert status == 200
    return body


def test_text_upload_has_no_thumbnail(tmp_path):
    base = _start(tmp_path)
    status, body = _post(base, "/api/v1/assets", data=b"just text",
                         params={"name": "note.txt"})
    assert status == 201, body
    asset_id = json.loads(body)["id"]
    status, _headers, body = _get(base, f"/api/v1/assets/{asset_id}/thumbnail")
    assert status == 404
    assert json.loads(body)["error"] == "no thumbnail"


def test_thumbnail_unknown_asset_404(tmp_path):
    base = _start(tmp_path)
    status, _headers, body = _get(base, "/api/v1/assets/999/thumbnail")
    assert status == 404
