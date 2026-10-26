"""Self-hosted asset library HTTP API (stdlib only).

Content blobs live in :mod:`library.blobs`, metadata in :mod:`library.db`.
Every route except ``GET /health`` requires
``Authorization: Bearer <token>`` (compared with :func:`hmac.compare_digest`).
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import ssl
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from library import blobs, db

__all__ = ["LibraryServer", "DEFAULT_MAX_UPLOAD_BYTES", "UploadTooLargeError"]

#: Refuse single uploads above this (documented cap, not chunked upload).
DEFAULT_MAX_UPLOAD_BYTES = 2 ** 31

#: Sessions untouched this long are deleted on server start.
STALE_UPLOAD_SECONDS = 24 * 3600

#: Upload ids are URL-safe tokens minted by the server.
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class UploadTooLargeError(Exception):
    """A chunk would push the upload over the server cap."""


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
            if presented.startswith("Bearer "):
                presented = presented[len("Bearer "):]
            if lib.check_token(presented):
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
            parts = path.strip("/").split("/")
            if (len(parts) == 4 and parts[:3] == ["api", "v1", "uploads"]
                    and _ID_RE.fullmatch(parts[3] or "")):
                try:
                    self._json(200, lib.upload_status(parts[3]))
                except KeyError:
                    self._json(404, {"error": "no such upload"})
                return
            self._json(404, {"error": "not found"})

        def do_POST(self) -> None:
            if not self._authorized():
                return
            path = urlparse(self.path).path
            if path == "/api/v1/assets":
                self._handle_single_upload()
                return
            if path == "/api/v1/uploads":
                self._handle_upload_init()
                return
            parts = path.strip("/").split("/")
            if (len(parts) == 5 and parts[:3] == ["api", "v1", "uploads"]
                    and _ID_RE.fullmatch(parts[3])):
                if parts[4] == "chunks":
                    self._handle_chunk(parts[3])
                elif parts[4] == "complete":
                    self._handle_complete(parts[3])
                else:
                    self._json(404, {"error": "not found"})
                return
            self._json(404, {"error": "not found"})

        def _body(self, cap: int | None = None) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0:
                length = 0
            if cap is not None and length > cap:
                self._json(413, {"error": "upload too large"})
                raise _BodyTooLarge
            return self.rfile.read(length)

        def _handle_single_upload(self) -> None:
            try:
                data = self._body(cap=lib.max_upload_bytes)
            except _BodyTooLarge:
                return
            if not data:
                self._json(400, {"error": "empty body"})
                return
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

        def _upload_meta(self) -> tuple[dict, dict | None]:
            query = self._query()
            try:
                params = json.loads(query.get("params", "{}"))
                if not isinstance(params, dict):
                    raise ValueError
            except ValueError:
                params = None
            return query, params

        def _handle_upload_init(self) -> None:
            query, params = self._upload_meta()
            if params is None:
                self._json(400, {"error": "params must be a JSON object"})
                return
            try:
                upload_id = lib.create_upload(
                    name=query.get("name") or "upload.bin",
                    kind=query.get("kind", "raw"),
                    importer=query.get("importer") or None,
                    params=params,
                    tags=[t for t in query.get("tags", "").split(",") if t])
            except OSError as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(201, {"upload_id": upload_id})

        def _handle_chunk(self, upload_id: str) -> None:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = 0
            if length < 0:
                length = 0
            try:
                if lib.upload_would_exceed(upload_id, length):
                    lib.abort_upload(upload_id)
                    self._json(413, {"error": "upload too large"})
                    return
                data = self.rfile.read(length) if length else b""
                try:
                    offset = lib.append_chunk(upload_id, data)
                except UploadTooLargeError:
                    self._json(413, {"error": "upload too large"})
                    return
            except KeyError:
                self._json(404, {"error": "no such upload"})
                return
            self._json(200, {"upload_id": upload_id, "offset": offset})

        def _handle_complete(self, upload_id: str) -> None:
            try:
                result = lib.complete_upload(upload_id)
            except KeyError:
                self._json(404, {"error": "no such upload"})
                return
            self._json(201, result)

    return Handler


class _BodyTooLarge(Exception):
    """Internal control flow: body already rejected with 413."""


class LibraryServer:
    """A self-hosted asset library: blob store + metadata + HTTP API."""

    def __init__(self, store_root, db_path, token: str | None = None,
                 max_upload_bytes: int = DEFAULT_MAX_UPLOAD_BYTES,
                 tls_cert: str | None = None,
                 tls_key: str | None = None) -> None:
        if bool(tls_cert) != bool(tls_key):
            raise ValueError("tls_cert and tls_key must be given together")
        for path in (tls_cert, tls_key):
            if path and not os.path.isfile(path):
                raise FileNotFoundError(f"TLS file not found: {path}")
        self.tls_cert = tls_cert
        self.tls_key = tls_key
        os.makedirs(store_root, exist_ok=True)
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.store_root = str(store_root)
        self.uploads_dir = os.path.join(
            os.path.dirname(os.path.abspath(store_root)), "uploads")
        os.makedirs(self.uploads_dir, exist_ok=True)
        self._sweep_stale_uploads()
        # One shared connection: handler threads are serialized by this lock.
        self.conn = db.open_db(db_path, check_same_thread=False)
        self._lock = threading.Lock()
        if token:
            self._ensure_bootstrap_token(token)
        self.max_upload_bytes = max_upload_bytes
        self.ready = threading.Event()
        self.port = 0
        self._httpd: ThreadingHTTPServer | None = None

    def _ensure_bootstrap_token(self, token: str) -> None:
        """Seed the ``default`` token on first run (back-compat single secret)."""
        import hashlib as _hashlib

        with self._lock:
            exists = self.conn.execute(
                "SELECT 1 FROM api_tokens WHERE name='default'").fetchone()
            if exists is None:
                self.conn.execute(
                    "INSERT INTO api_tokens(token_sha256, name)"
                    " VALUES (?, 'default')",
                    (_hashlib.sha256(token.encode()).hexdigest(),))
                self.conn.commit()

    def check_token(self, presented: str) -> bool:
        """Thread-safe :func:`library.db.check_token`."""
        with self._lock:
            return db.check_token(self.conn, presented)

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

    # -- chunked upload sessions --------------------------------------
    def _session_paths(self, upload_id: str) -> tuple[str, str]:
        if not _ID_RE.fullmatch(upload_id or ""):
            raise KeyError(upload_id)
        session = os.path.join(self.uploads_dir, upload_id)
        if not os.path.isdir(session):
            raise KeyError(upload_id)
        return session, os.path.join(session, "data.bin")

    @staticmethod
    def _read_meta(session: str) -> dict:
        with open(os.path.join(session, "meta.json"),
                  encoding="utf-8") as handle:
            meta = json.load(handle)
        return meta if isinstance(meta, dict) else {}

    def _sweep_stale_uploads(self) -> None:
        """Delete abandoned session dirs older than a day (startup only)."""
        now = time.time()
        try:
            entries = os.listdir(self.uploads_dir)
        except OSError:
            return
        for entry in entries:
            path = os.path.join(self.uploads_dir, entry)
            try:
                if (os.path.isdir(path) and not os.path.islink(path)
                        and now - os.path.getmtime(path) > STALE_UPLOAD_SECONDS):
                    shutil.rmtree(path, ignore_errors=True)
            except OSError:
                continue

    def create_upload(self, *, name: str, kind: str = "raw",
                      importer: str | None = None,
                      params: dict | None = None,
                      tags: list | None = None) -> str:
        """Begin a session; returns its id. Raises OSError on FS trouble."""
        upload_id = secrets.token_urlsafe(12)
        session = os.path.join(self.uploads_dir, upload_id)
        os.makedirs(session)
        with open(os.path.join(session, "meta.json"), "w",
                  encoding="utf-8") as handle:
            json.dump({"name": name, "kind": kind, "importer": importer,
                       "params": params or {}, "tags": tags or []}, handle)
        open(os.path.join(session, "data.bin"), "wb").close()
        return upload_id

    def _session_size(self, upload_id: str) -> int:
        _session, data = self._session_paths(upload_id)
        return os.path.getsize(data)

    def upload_would_exceed(self, upload_id: str, incoming: int) -> bool:
        """Whether appending *incoming* bytes would breach the cap."""
        return self._session_size(upload_id) + incoming > self.max_upload_bytes

    def append_chunk(self, upload_id: str, data: bytes) -> int:
        """Append *data*; returns the new offset. KeyError if unknown."""
        with self._lock:
            _session, path = self._session_paths(upload_id)
            if os.path.getsize(path) + len(data) > self.max_upload_bytes:
                raise UploadTooLargeError(upload_id)
            with open(path, "ab") as handle:
                handle.write(data)
            os.utime(self._session_paths(upload_id)[0], None)
            return os.path.getsize(path)

    def upload_status(self, upload_id: str) -> dict:
        """Current ``{"upload_id", "offset", "size"}``; KeyError if unknown."""
        with self._lock:
            session, path = self._session_paths(upload_id)
            size = os.path.getsize(path)
            os.utime(session, None)
            return {"upload_id": upload_id, "offset": size, "size": size}

    def abort_upload(self, upload_id: str) -> None:
        """Drop a session and its bytes; unknown ids are ignored."""
        with self._lock:
            try:
                session, _data = self._session_paths(upload_id)
            except KeyError:
                return
            shutil.rmtree(session, ignore_errors=True)

    def complete_upload(self, upload_id: str) -> dict:
        """Assemble, store and index; returns the asset record."""
        with self._lock:
            session, path = self._session_paths(upload_id)
            meta = self._read_meta(session)
            size = os.path.getsize(path)
            with open(path, "rb") as stream:
                digest = blobs.put_stream(self.store_root, stream)
            asset_id = db.add_asset(
                self.conn, name=meta.get("name", "upload.bin"),
                blob_sha256=digest, size_bytes=size,
                kind=meta.get("kind", "raw"),
                godot_importer=meta.get("importer"),
                params=meta.get("params") or {},
                tags=meta.get("tags") or [])
            shutil.rmtree(session, ignore_errors=True)
            return {"id": asset_id, "blob_sha256": digest, "size": size}

    def serve_forever(self, host: str = "127.0.0.1", port: int = 0) -> None:
        """Block serving; ``port=0`` picks an ephemeral port (see .port)."""
        self._httpd = ThreadingHTTPServer((host, port),
                                          _make_handler(self))
        if self.tls_cert and self.tls_key:
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(self.tls_cert, self.tls_key)
            self._httpd.socket = context.wrap_socket(self._httpd.socket,
                                                     server_side=True)
        self.port = self._httpd.server_address[1]
        self.ready.set()
        self._httpd.serve_forever()

    def shutdown(self) -> None:
        """Stop a running server (tests / embedding)."""
        if self._httpd is not None:
            self._httpd.shutdown()
