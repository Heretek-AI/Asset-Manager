"""HTTP client for a self-hosted asset library (stdlib only)."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

__all__ = ["LibraryError", "push", "pull"]


class LibraryError(RuntimeError):
    """The server refused the request (auth, missing asset, network)."""

    def __init__(self, message: str, status: int = 0) -> None:
        super().__init__(message)
        self.status = status


def _request(server: str, token: str, method: str, path: str, *,
             params: dict | None = None,
             data: bytes | None = None) -> tuple[int, bytes]:
    url = server.rstrip("/") + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/octet-stream")
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        try:
            detail = json.loads(exc.read().decode()).get("error", "")
        except (ValueError, AttributeError):
            detail = ""
        raise LibraryError(f"{method} {path}: HTTP {exc.code}"
                           + (f" ({detail})" if detail else ""),
                           status=exc.code) from None
    except OSError as exc:
        raise LibraryError(f"{method} {path}: {exc}") from None


def push(server: str, token: str, file_path: str, *,
         name: str | None = None, kind: str = "raw",
         importer: str | None = None, params: dict | None = None,
         tags: list[str] | tuple = ()) -> dict:
    """Upload *file_path*; returns the server's ``{"id", "blob_sha256"}``."""
    if not os.path.isfile(file_path):
        raise LibraryError(f"no such file: {file_path}")
    with open(file_path, "rb") as handle:
        data = handle.read()
    query: dict[str, str] = {"name": name or os.path.basename(file_path),
                             "kind": kind}
    if importer:
        query["importer"] = importer
    if params:
        query["params"] = json.dumps(params)
    if tags:
        query["tags"] = ",".join(tags)
    status, body = _request(server, token, "POST", "/api/v1/assets",
                            params=query, data=data)
    if status != 201:
        raise LibraryError(f"upload rejected: HTTP {status}", status=status)
    return json.loads(body.decode())


def pull(server: str, token: str, asset_id: int, out_path: str) -> dict:
    """Download asset *asset_id* to *out_path*; returns ``{"path","size"}``."""
    status, body = _request(server, token, "GET",
                            f"/api/v1/assets/{asset_id}/blob")
    if status != 200:
        raise LibraryError(f"download rejected: HTTP {status}", status=status)
    with open(out_path, "wb") as handle:
        handle.write(body)
    return {"path": os.path.abspath(out_path), "size": len(body)}
