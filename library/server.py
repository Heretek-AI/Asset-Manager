"""Self-hosted asset library HTTP API (stdlib only).

Content blobs live in :mod:`library.blobs`, metadata in :mod:`library.db`.
Every route except ``GET /health`` requires
``Authorization: Bearer <token>`` (compared with :func:`hmac.compare_digest`).
"""

from __future__ import annotations

import hmac
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from library import blobs, db

__all__ = ["LibraryServer", "DEFAULT_MAX_UPLOAD_BYTES"]

#: Refuse single uploads above this (documented cap, not chunked upload).
DEFAULT_MAX_UPLOAD_BYTES = 2 ** 31


def _make_handler(lib: "LibraryServer") -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "AssetLibrary/0.3"

        def log_message(self, format: str, *args: object) -> None:
            pass  # keep test output clean; front with a real server for logs

        # -- helpers ----------------------------------------------------
        def _json(self, code: int, payload: object) -> None:
            body = json.dumps(payload).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            if self.path == "/health" or self.command == "OPTIONS":
                return True
            presented = self.headers.get("Authorization", "")
            expected = f"Bearer {lib.token}"
            if hmac.compare_digest(presented, expected):
                return True
            self._json(401, {"error": "unauthorized"})
            return False

        def _query(self) -> dict[str, str]:
            return {k: v[0] for k, v in
                    parse_qs(urlparse(self.path).query).items()}

        # -- routes ------------------------------------------------------
        def do_GET(self) -> None:
            if not self._authorized():
                return
            path = urlparse(self.path).path
            if path == "/health":
                self._json(200, {"ok": True})
                return
            if path == "/api/v1/assets":
                query = self._query()
                assets = lib.list_assets(
                    q=query.get("q", ""), tag=query.get("tag", ""),
                    kind=query.get("kind", ""))
                self._json(200, {"assets": assets})
                return
            if path.startswith("/api/v1/assets/") and path.endswith("/blob"):
                try:
                    asset_id = int(path.rsplit("/", 2)[-2])
                    row = lib.get_asset(asset_id)
                except (ValueError, KeyError):
                    self._json(404, {"error": "no such asset"})
                    return
                try:
                    blob = blobs.get_path(lib.store_root,
                                           row["blob_sha256"]).read_bytes()
                except FileNotFoundError:
                    self._json(404, {"error": "blob missing"})
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Length", str(len(blob)))
                self.end_headers()
                self.wfile.write(blob)
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            if urlparse(self.path).path != "/api/v1/assets":
                self._json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length <= 0:
                self._json(400, {"error": "empty body"})
                return
            if length > lib.max_upload_bytes:
                self._json(413, {"error": "upload too large"})
                return
            data = self.rfile.read(length)
            query = self._query()
            name = query.get("name") or "upload.bin"
            try:
                params = json.loads(query.get("params", "{}"))
                if not isinstance(params, dict):
                    raise ValueError
            except ValueError:
                self._json(400, {"error": "params must be a JSON object"})
                return
            tags = [t for t in query.get("tags", "").split(",") if t]
            digest = blobs.put(lib.store_root, data)
            asset_id = lib.add_asset(
                name=name, blob_sha256=digest,
                size_bytes=len(data), kind=query.get("kind", "raw"),
                godot_importer=query.get("importer") or None,
                params=params, tags=tags)
            self._json(201, {"id": asset_id, "blob_sha256": digest})

    return Handler


class LibraryServer:
    """A self-hosted asset library: blob store + metadata + HTTP API."""

    def __init__(self, store_root, db_path, token: str,
                 max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES) -> None:
        os.makedirs(store_root, exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.store_root = store_root
        # One shared connection: handler threads are serialized by this lock.
        self.conn = db.open_db(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        self.token = token
        self.max_upload_bytes = max_upload_bytes
        self.ready = threading.Event()
        self.port = 0
        self._httpd: ThreadingHTTPServer | None = None

    def list_assets(self, **filters) -> list:
        """Thread-safe :func:`library.db.list_assets`."""
        with self._lock:
            return db.list_assets(self.conn, **filters)

    def get_asset(self, asset_id: int) -> dict:
        """Thread-safe :func:`library.db.get_asset`."""
        with self._lock:
            return db.get_asset(self.conn, asset_id)

    def add_asset(self, **fields) -> int:
        """Thread-safe :func:`library.db.add_asset`."""
        with self._lock:
            return db.add_asset(self.conn, **fields)

    def serve_forever(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """Block serving; ``port=0`` picks an ephemeral port (see .port)."""
        self._httpd = ThreadingHTTPServer((host, port),
                                          _make_handler(self))
        self.port = self._httpd.server_address[1]
        self.ready.set()
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """Stop a running server (tests / embedding)."""
        if self._httpd is not None:
            self._httpd.shutdown()
