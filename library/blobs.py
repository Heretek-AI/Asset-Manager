"""Content-addressed blob store (SHA-256, ``ab/cd/rest`` fan-out)."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import BinaryIO

__all__ = ["put", "put_stream", "get_path"]


def _shard(root: Path, digest: str) -> Path:
    return root / digest[:2] / digest[2:4] / digest[4:]


def _finalize(root: Path, digest: str, source: Path) -> Path:
    target = _shard(root, digest)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
    else:
        source.unlink()
    return target


def put(root: str | Path, data: bytes) -> str:
    """Store *data*; returns its SHA-256 hex digest (idempotent)."""
    digest = hashlib.sha256(data).hexdigest()
    target = _shard(Path(root), digest)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return digest


def put_stream(root: str | Path, stream: BinaryIO) -> str:
    """Store stream contents without holding them in RAM; returns digest.

    Streams through a temp file, then moves it into place atomically.
    """
    root = Path(root)
    digestor = hashlib.sha256()
    with tempfile.NamedTemporaryFile(dir=str(root), delete=False) as tmp:
        tmp_path = Path(tmp.name)
        while True:
            block = stream.read(1 << 20)
            if not block:
                break
            digestor.update(block)
            tmp.write(block)
    _finalize(root, digestor.hexdigest(), tmp_path)
    return digestor.hexdigest()


def get_path(root: str | Path, digest: str) -> Path:
    """Filesystem path of a stored blob; raises FileNotFoundError if absent."""
    target = _shard(Path(root), digest)
    if not target.is_file():
        raise FileNotFoundError(f"blob {digest} not in store")
    return target
