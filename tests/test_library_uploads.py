"""Chunked (session) upload tests: init -> chunks -> complete."""

import json
import urllib.error
import urllib.parse
import urllib.request

import pytest

from library.client import LibraryError, pull, push, upload_status
from library.server import LibraryServer
from test_library_server import TOKEN

CHUNK = b"01234567"  # 8 bytes; tests force tiny chunks via chunk_size


def start_server(tmp_path, **kwargs):
    import threading
    server = LibraryServer(tmp_path / "store", tmp_path / "lib.db",
                           token=TOKEN, **kwargs)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    server.ready.wait(timeout=10)
    return server, f"http://127.0.0.1:{server.port}"


def post(base, path, token=TOKEN, data=b"", params=None):
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


def test_session_roundtrip_many_chunks(tmp_path):
    _, base = start_server(tmp_path)
    status, body = post(base, "/api/v1/uploads",
                        params={"name": "big.bin", "kind": "raw"})
    assert status == 201, body
    upload_id = json.loads(body)["upload_id"]

    payload = CHUNK * 100  # 800 bytes over 8-byte chunks
    for i in range(0, len(payload), 8):
        status, body = post(base, f"/api/v1/uploads/{upload_id}/chunks",
                            data=payload[i:i + 8])
        assert status == 200, body
    assert json.loads(body)["offset"] == len(payload)

    status, body = post(base, f"/api/v1/uploads/{upload_id}/complete")
    assert status == 201, body
    asset_id = json.loads(body)["id"]
    assert json.loads(body)["size"] == len(payload)

    dest = tmp_path / "back.bin"
    assert pull(base, TOKEN, asset_id, str(dest))["size"] == len(payload)
    assert dest.read_bytes() == payload


def test_status_reports_offset(tmp_path):
    _, base = start_server(tmp_path)
    _, body = post(base, "/api/v1/uploads", params={"name": "a.bin"})
    upload_id = json.loads(body)["upload_id"]
    post(base, f"/api/v1/uploads/{upload_id}/chunks", data=b"12345")
    status, body = post(base, f"/api/v1/uploads/{upload_id}/chunks",
                        data=b"67890")
    assert json.loads(body)["offset"] == 10
    assert upload_status(base, TOKEN, upload_id)["offset"] == 10
    with pytest.raises(LibraryError):
        upload_status(base, TOKEN, "no-such-id")


def test_unknown_upload_id_404s(tmp_path):
    _, base = start_server(tmp_path)
    assert post(base, "/api/v1/uploads/nope/chunks", data=b"x")[0] == 404
    assert post(base, "/api/v1/uploads/nope/complete")[0] == 404


def test_cap_enforced_across_chunks(tmp_path):
    _, base = start_server(tmp_path, max_upload_bytes=16)
    _, body = post(base, "/api/v1/uploads", params={"name": "a.bin"})
    upload_id = json.loads(body)["upload_id"]
    assert post(base, f"/api/v1/uploads/{upload_id}/chunks",
                data=b"0" * 16)[0] == 200
    status, body = post(base, f"/api/v1/uploads/{upload_id}/chunks",
                        data=b"overflow")
    assert status == 413
    # session is dead after exceeding the cap
    assert post(base, f"/api/v1/uploads/{upload_id}/complete")[0] == 404


def test_push_auto_chunks_large_files(tmp_path):
    _, base = start_server(tmp_path)
    big = tmp_path / "big.bin"
    big.write_bytes(b"y" * 100)
    result = push(base, TOKEN, str(big), chunk_size=7, chunk_above=10)
    assert result["id"] == 1
    dest = tmp_path / "back.bin"
    assert pull(base, TOKEN, 1, str(dest))["size"] == 100
    assert dest.read_bytes() == b"y" * 100


def test_push_small_file_stays_single_shot(tmp_path, monkeypatch):
    from test_library_server import start_server as _start
    import library.client as client_mod
    _, base = _start(tmp_path)
    small = tmp_path / "small.bin"
    small.write_bytes(b"z" * 10)
    calls = []
    real = client_mod._push_session
    monkeypatch.setattr(client_mod, "_push_session",
                        lambda *a, **k: calls.append(1) or real(*a, **k))
    push(base, TOKEN, str(small), chunk_above=1024)
    assert calls == []


def test_push_missing_file_still_raises(tmp_path):
    with pytest.raises(LibraryError):
        push("http://127.0.0.1:1", TOKEN, str(tmp_path / "nope.bin"))
