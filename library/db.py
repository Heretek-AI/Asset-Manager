"""SQLite metadata for library assets and API tokens (stdlib only)."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any

__all__ = ["open_db", "add_asset", "get_asset", "list_assets",
           "create_token", "revoke_token", "list_tokens", "check_token"]

SCHEMA = """\
CREATE TABLE IF NOT EXISTS assets(
 id INTEGER PRIMARY KEY,
 name TEXT NOT NULL,
 blob_sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL,
 kind TEXT NOT NULL DEFAULT 'raw',
 godot_importer TEXT,
 params_json TEXT NOT NULL DEFAULT '{}',
 tags_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 thumbnail_sha256 TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
CREATE TABLE IF NOT EXISTS api_tokens(
 token_sha256 TEXT PRIMARY KEY,
 name TEXT NOT NULL UNIQUE,
 created_at TEXT NOT NULL DEFAULT (datetime('now')),
 revoked INTEGER NOT NULL DEFAULT 0);
"""


def open_db(path: str | Path, *,
            check_same_thread: bool = True) -> sqlite3.Connection:
    """Open (creating) the library database at *path*."""
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Bring older databases up to the current schema (additive only)."""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(assets)")]
    if "thumbnail_sha256" not in cols:
        conn.execute("ALTER TABLE assets ADD COLUMN"
                     " thumbnail_sha256 TEXT NOT NULL DEFAULT ''")
        conn.commit()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "blob_sha256": row["blob_sha256"],
        "size_bytes": row["size_bytes"],
        "kind": row["kind"],
        "godot_importer": row["godot_importer"],
        "params": json.loads(row["params_json"]),
        "tags": json.loads(row["tags_json"]),
        "created_at": row["created_at"],
        "thumbnail_sha256": row["thumbnail_sha256"] or None,
    }


def add_asset(conn: sqlite3.Connection, *, name: str, blob_sha256: str,
              size_bytes: int, kind: str = "raw",
              godot_importer: str | None = None,
              params: dict | None = None,
              tags: list | None = None,
              thumbnail_sha256: str = "") -> int:
    """Insert one asset row; returns its id."""
    placeholders = ",".join(["?"] * 8)
    cur = conn.execute(
        "INSERT INTO assets(name, blob_sha256, size_bytes, kind,"
        " godot_importer, params_json, tags_json, thumbnail_sha256)"
        f" VALUES ({placeholders})",
        (name, blob_sha256, size_bytes, kind, godot_importer,
         json.dumps(params or {}), json.dumps(tags or []),
         thumbnail_sha256))
    conn.commit()
    return int(cur.lastrowid)


def get_asset(conn: sqlite3.Connection, asset_id: int) -> dict[str, Any]:
    """Fetch one asset by id; raises KeyError when absent."""
    row = conn.execute("SELECT * FROM assets WHERE id=?",
                       (asset_id,)).fetchone()
    if row is None:
        raise KeyError(f"asset {asset_id} not found")
    return _row_to_dict(row)


def list_assets(conn: sqlite3.Connection, *, q: str = "",
                tag: str = "", kind: str = "") -> list[dict[str, Any]]:
    """List assets, newest first, with optional filters."""
    where: list[str] = []
    args: list = []
    if q:
        where.append("name LIKE ?")
        args.append(f"%{q}%")
    if kind:
        where.append("kind = ?")
        args.append(kind)
    sql = "SELECT * FROM assets"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id DESC"
    rows = [_row_to_dict(r) for r in conn.execute(sql, args)]
    if tag:
        rows = [r for r in rows if tag in r["tags"]]
    return rows


def _token_digest(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode()).hexdigest()


def create_token(conn: sqlite3.Connection, name: str) -> str:
    """Create an API token for *name*; returns the plaintext (shown once).

    Only the SHA-256 digest is stored. Raises ValueError on duplicate name.
    """
    plaintext = secrets.token_urlsafe(32)
    try:
        conn.execute(
            "INSERT INTO api_tokens(token_sha256, name) VALUES (?, ?)",
            (_token_digest(plaintext), name))
    except sqlite3.IntegrityError:
        raise ValueError(f"token {name!r} already exists") from None
    conn.commit()
    return plaintext


def revoke_token(conn: sqlite3.Connection, name: str) -> bool:
    """Revoke *name*'s token; True when something was revoked."""
    cur = conn.execute("UPDATE api_tokens SET revoked=1 WHERE name=?",
                       (name,))
    conn.commit()
    return cur.rowcount > 0


def check_token(conn: sqlite3.Connection, presented: str) -> bool:
    """Whether *presented* matches a live (non-revoked) token."""
    if not presented:
        return False
    digest = _token_digest(presented)
    stored = [r[0] for r in
              conn.execute("SELECT token_sha256 FROM api_tokens"
                           " WHERE revoked=0")]
    return any(hmac.compare_digest(digest, candidate) for candidate in stored)


def list_tokens(conn: sqlite3.Connection,
                include_revoked: bool = False) -> list[dict[str, Any]]:
    """Token metadata (digests, never plaintext), oldest first."""
    sql = "SELECT name, token_sha256, created_at, revoked FROM api_tokens"
    if not include_revoked:
        sql += " WHERE revoked=0"
    return [{"name": r[0], "token_sha256": r[1], "created_at": r[2],
             "revoked": bool(r[3])}
            for r in conn.execute(sql + " ORDER BY rowid")]
