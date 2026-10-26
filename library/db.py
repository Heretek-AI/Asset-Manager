"""SQLite metadata for library assets (stdlib only)."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

__all__ = ["open_db", "add_asset", "get_asset", "list_assets"]

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
 created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_assets_kind ON assets(kind);
"""


def open_db(path: str | Path, *,
            check_same_thread: bool = True) -> sqlite3.Connection:
    """Open (creating) the library database at *path*."""
    conn = sqlite3.connect(str(path), check_same_thread=check_same_thread)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


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
    }


def add_asset(conn: sqlite3.Connection, *, name: str, blob_sha256: str,
              size_bytes: int, kind: str = "raw",
              godot_importer: str | None = None,
              params: dict | None = None,
              tags: list | None = None) -> int:
    """Insert one asset row; returns its id."""
    placeholders = ",".join(["?"] * 7)
    cur = conn.execute(
        "INSERT INTO assets(name, blob_sha256, size_bytes, kind,"
        " godot_importer, params_json, tags_json)"
        f" VALUES ({placeholders})",
        (name, blob_sha256, size_bytes, kind, godot_importer,
         json.dumps(params or {}), json.dumps(tags or [])))
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
