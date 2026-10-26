"""Library client tests (push/pull against a live test server)."""

import json

import pytest

from library.client import LibraryError, pull, push
from test_library_server import TOKEN, call, start_server


def test_push_pull_roundtrip(tmp_path):
    _, base = start_server(tmp_path)
    source = tmp_path / "hero.png"
    source.write_bytes(b"png-bytes")
    result = push(base, TOKEN, str(source), kind="texture",
                  importer="texture", tags=["hero"])
    assert result["id"] == 1
    dest = tmp_path / "fetched.png"
    pulled = pull(base, TOKEN, result["id"], str(dest))
    assert dest.read_bytes() == b"png-bytes"
    assert pulled["size"] == len(b"png-bytes")


def test_push_params_json(tmp_path):
    _, base = start_server(tmp_path)
    source = tmp_path / "a.bin"
    source.write_bytes(b"x")
    result = push(base, TOKEN, str(source),
                  params={"compress/mode": 1})
    _, body = call(base, "/api/v1/assets", token=TOKEN)
    assert json.loads(body)["assets"][0]["params"] == {"compress/mode": 1}


def test_bad_token_raises(tmp_path):
    _, base = start_server(tmp_path)
    source = tmp_path / "a.bin"
    source.write_bytes(b"x")
    with pytest.raises(LibraryError):
        push(base, "wrong", str(source))
    with pytest.raises(LibraryError):
        pull(base, "wrong", 1, str(tmp_path / "o.bin"))


def test_missing_file_raises(tmp_path):
    _, base = start_server(tmp_path)
    with pytest.raises(LibraryError):
        push(base, TOKEN, str(tmp_path / "nope.bin"))
