"""Content-addressed blob store (SHA-256, `ab/cd/rest` fan-out)."""

from __future__ import annotations

import hashlib
from pathlib import Path

__all__ = ["put", "get_path"]


def _shard(root: Path, digest: str) -> Path:
    return root / digest[:2] / digest[2:4] / digest[4:]


def put(root: str | Path, data: bytes) -> str:
    """Store *data*, returning its SHA-256 hex digest (idempotent)."""
    digest = hashlib.sha256(data).hexdigest()
    target = _shard(Path(root), digest)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return digest


def get_path(root: str | Path, digest: str) -> Path:
    """Filesystem path of a stored blob; raises FileNotFoundError if absent."""
    target = _shard(Path(root), digest)
    if not target.is_file():
        raise FileNotFoundError(f"blob {digest} not in store")
    return target
