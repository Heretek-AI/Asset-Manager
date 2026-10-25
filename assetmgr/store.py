"""Local project store: ``*.approj`` markers, metadata and sidecars.

A project is any folder containing (or nested under a folder containing)
a ``<name>.approj`` JSON marker, e.g. ``my-film/my-film.approj``::

    {"project_id": "...", "workspace_id": "...", "name": "..."}

Per-file metadata (attributes, tags) lives in ``<file>.meta.json`` sidecars
next to the file, so projects stay plain folders fully usable with git.
"""

from __future__ import annotations

import json
import os

MARKER_SUFFIX = ".approj"


def find_project_root(start: str) -> str | None:
    """Walk up from *start* to the nearest folder holding a marker."""
    current = os.path.abspath(start)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    while True:
        try:
            entries = os.listdir(current)
        except OSError:
            return None
        if any(e.endswith(MARKER_SUFFIX) for e in entries):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def is_project(path: str, recursive: bool = False) -> bool:
    """Whether *path* is (or is inside) a project folder."""
    if recursive:
        return find_project_root(path) is not None
    candidate = os.path.abspath(path)
    if not os.path.isdir(candidate):
        return False
    try:
        entries = os.listdir(candidate)
    except OSError:
        return False
    return any(e.endswith(MARKER_SUFFIX) for e in entries)


def read_marker(project_root: str) -> dict:
    for entry in sorted(os.listdir(project_root)):
        if entry.endswith(MARKER_SUFFIX):
            with open(os.path.join(project_root, entry), encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("project marker must hold a JSON object")
            return data
    raise FileNotFoundError(f"no *{MARKER_SUFFIX} marker in {project_root}")


def init_project(directory: str, name: str, project_id: str = "",
                 workspace_id: str = "", force: bool = False) -> str:
    """Create a project marker; returns the marker path."""
    os.makedirs(directory, exist_ok=True)
    marker = os.path.join(os.path.abspath(directory), f"{name}{MARKER_SUFFIX}")
    if os.path.exists(marker) and not force:
        raise FileExistsError(marker)
    payload = {"name": name, "project_id": project_id, "workspace_id": workspace_id}
    with open(marker, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    return marker


def sidecar_path(target: str) -> str:
    return f"{os.path.abspath(target)}.meta.json"


def read_sidecar(target: str) -> dict:
    path = sidecar_path(target)
    if not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def write_sidecar(target: str, data: dict) -> str:
    path = sidecar_path(target)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
    return path
