"""Content-addressed blob store tests."""

from library.blobs import get_path, put

SHA_ABCD = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"


def test_roundtrip(tmp_path):
    digest = put(tmp_path / "store", b"abc")
    assert digest == SHA_ABCD
    assert get_path(tmp_path / "store", digest).read_bytes() == b"abc"


def test_missing_blob_raises(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        get_path(tmp_path / "store", "0" * 64)


def test_dedupe_same_digest(tmp_path):
    root = tmp_path / "store"
    assert put(root, b"abc") == put(root, b"abc")
    assert len(list((root).rglob("*"))) == 3  # ab/cd/rest chain minus dirs
