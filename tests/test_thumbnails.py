"""Thumbnail tests: apsync.generate_thumbnail via ffmpeg / ImageMagick."""

import os
import shutil
import struct
import zlib

import pytest

import apsync
from assetmgr.errors import DependencyMissingError

PNG_MAGIC = bytes.fromhex("89504e470d0a1a0a")


def _write_png(path, width=64, height=64, rgb=(255, 0, 0)):
    """Write a minimal valid PNG with stdlib only (no Pillow dependency)."""

    def chunk(tag, data):
        blob = tag + data
        return struct.pack(">I", len(data)) + blob + struct.pack(">I", zlib.crc32(blob) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    png = (
        PNG_MAGIC
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )
    with open(path, "wb") as handle:
        handle.write(png)
    return path


def _engine_available():
    return shutil.which("ffmpeg") is not None or shutil.which("magick") is not None


def test_generate_thumbnail_success(tmp_path):
    if not _engine_available():
        pytest.skip("neither ffmpeg nor magick on PATH")
    source = _write_png(str(tmp_path / "in.png"))
    destination = str(tmp_path / "out.png")
    assert apsync.generate_thumbnail(source, destination) == destination
    assert os.path.isfile(destination)
    assert os.path.getsize(destination) > 0
    with open(destination, "rb") as handle:
        assert handle.read(8) == PNG_MAGIC


def test_generate_thumbnail_missing_dependency(tmp_path, monkeypatch):
    source = _write_png(str(tmp_path / "in.png"))
    monkeypatch.setenv("PATH", str(tmp_path))  # dir with no engines on it
    with pytest.raises(DependencyMissingError):
        apsync.generate_thumbnail(source, str(tmp_path / "out.png"))
