"""Godot project scanner: list every asset under ``res://`` with sidecar state.

For each regular file under the project root (excluding the ``.godot/``
editor cache and ``*.import`` / ``*.uid`` / ``*.meta.json`` sidecars),
:func:`scan_project` reports a JSON-serializable dict::

    {"path": "res://art/hero.png", "name": "hero.png", "suffix": ".png",
     "size_bytes": 1234, "mtime": 1720000000.0,
     "has_import": True, "import": {...} | None,
     "uid": "uid://..." | None, "attributes": {...}}

Import summaries, uid reads and ``.meta.json`` attributes reuse the
:mod:`assetmgr.godot` and :mod:`assetmgr.store` helpers, so the on-disk
formats stay defined in exactly one place each.
"""

from __future__ import annotations

import os
from typing import Any

from assetmgr.godot import (
    GODOT_DIR,
    find_godot_project_root,
    import_summary,
    read_import,
    read_uid,
)
from assetmgr.store import read_sidecar

#: Sidecar suffixes: metadata about an asset, not assets themselves.
SKIP_SUFFIXES = (".import", ".uid", ".meta.json")


def _res_path(project_root: str, absolute: str) -> str:
    relative = os.path.relpath(absolute, project_root).replace(os.sep, "/")
    return f"res://{relative}"


def _is_cache_dir(project_root: str, dirpath: str) -> bool:
    return GODOT_DIR in os.path.relpath(dirpath, project_root).split(os.sep)


def scan_project(root: str) -> list[dict[str, Any]]:
    """List asset files under the Godot project holding *root*.

    *root* may be the project root itself or anything inside it; the
    enclosing project (walked up via ``project.godot``) is scanned.
    Raises :class:`FileNotFoundError` when *root* does not exist or is
    not inside a Godot project.
    """
    start = os.path.abspath(root)
    if not os.path.exists(start):
        raise FileNotFoundError(start)
    project_root = find_godot_project_root(start)
    if project_root is None:
        raise FileNotFoundError(f"not a Godot project: {start}")

    assets: list[dict[str, Any]] = []
    for dirpath, dirnames, filenames in os.walk(project_root):
        dirnames[:] = sorted(d for d in dirnames if d != GODOT_DIR)
        if _is_cache_dir(project_root, dirpath):
            continue
        for filename in sorted(filenames):
            if filename.endswith(SKIP_SUFFIXES):
                continue
            absolute = os.path.join(dirpath, filename)
            try:
                stat = os.stat(absolute)
            except OSError:
                continue  # broken link or vanishing file; not an asset
            if not os.path.isfile(absolute):
                continue
            import_path = f"{absolute}.import"
            has_import = os.path.isfile(import_path)
            parsed_import: dict[str, Any] | None = None
            if has_import:
                try:
                    parsed_import = import_summary(read_import(import_path))  # type: ignore[assignment]
                except OSError:
                    parsed_import = None
            uid_path = f"{absolute}.uid"
            uid: str | None = None
            if os.path.isfile(uid_path):
                try:
                    uid = read_uid(uid_path)
                except OSError:
                    uid = None
            try:
                attributes = read_sidecar(absolute)
            except (OSError, ValueError):
                attributes = {}
            assets.append({
                "path": _res_path(project_root, absolute),
                "name": filename,
                "suffix": os.path.splitext(filename)[1].lower(),
                "size_bytes": stat.st_size,
                "mtime": stat.st_mtime,
                "has_import": has_import,
                "import": parsed_import,
                "uid": uid,
                "attributes": attributes,
            })
    assets.sort(key=lambda item: item["path"])
    return assets
