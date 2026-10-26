"""Local project/file engine (``import apsync``).

Implements the offline-capable subset against plain folders: project
markers, file operations, ``${var}`` templates, next-version paths and
JSON sidecar attributes. Everything server-backed raises
:exc:`ServerRequiredError` instead of failing silently.
"""

from __future__ import annotations

import os
import re
import shutil

from assetmgr import store
from assetmgr.errors import DependencyMissingError, ServerRequiredError

__all__ = [
    "ServerRequiredError",
    "is_project",
    "create_project_file",
    "find_project_root",
    "copy_file",
    "move_file",
    "copy_folder",
    "move_folder",
    "resolve_variables",
    "create_next_version",
    "get_next_version_path",
    "get_attribute",
    "set_attribute",
    "generate_thumbnail",
]

_VARIABLE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _server_only(*args: object, **kwargs: object):
    raise ServerRequiredError("this operation requires the sync server")


def is_project(path: str, recursive: bool = True) -> bool:
    return store.is_project(path, recursive=recursive)


def find_project_root(path: str) -> str | None:
    return store.find_project_root(path)


def create_project_file(path: str, project_id: str, workspace_id: str = "",
                        force: bool = False) -> str:
    name = os.path.basename(os.path.abspath(path)) or "project"
    return store.init_project(path, name, project_id, workspace_id, force=force)


def copy_file(source: str, destination: str) -> str:
    return str(shutil.copy2(source, destination))


def move_file(source: str, destination: str) -> str:
    return str(shutil.move(source, destination))


def copy_folder(source: str, destination: str) -> str:
    return str(shutil.copytree(source, destination))


def move_folder(source: str, destination: str) -> str:
    return str(shutil.move(source, destination))


def resolve_variables(text: str, variables: dict[str, str]) -> str:
    def _replace(match: re.Match[str]) -> str:
        return str(variables.get(match.group(1), match.group(0)))

    return _VARIABLE_RE.sub(_replace, text)


_VERSION_RE = re.compile(r"^(?P<stem>.*?)(?:_v(?P<num>\d+))?$")


def get_next_version_path(path: str) -> str:
    """Insert or bump a ``_vNNN`` suffix before the extension."""
    directory, filename = os.path.split(path)
    stem, ext = os.path.splitext(filename)
    match = _VERSION_RE.match(stem)
    assert match is not None
    number = int(match.group("num") or 0) + 1
    return os.path.join(directory, f"{match.group('stem')}_v{number:03d}{ext}")


def create_next_version(path: str) -> str:
    """Copy *path* to its next version; returns the new path."""
    target = get_next_version_path(path)
    if os.path.isdir(path):
        copy_folder(path, target)
    else:
        copy_file(path, target)
    return target


def get_attribute(target: str, name: str, default: object = None) -> object:
    return store.read_sidecar(target).get(name, default)


def set_attribute(target: str, name: str, value: object) -> str:
    data = store.read_sidecar(target)
    data[name] = value
    return store.write_sidecar(target, data)


def generate_thumbnail(source: str, destination: str) -> str:
    """Render a preview image; needs ffmpeg or ImageMagick on PATH."""
    for tool, args in (
        ("ffmpeg", ["-y", "-i", source, "-vframes", "1", destination]),
        ("magick", [source + "[0]", "-thumbnail", "512x512>", destination]),
    ):
        if shutil.which(tool) is None:
            continue
        import subprocess

        result = subprocess.run([tool, *args], capture_output=True, text=True)
        if result.returncode == 0 and os.path.exists(destination):
            return destination
        raise RuntimeError(f"{tool} failed: {result.stderr.strip()[:300]}")
    raise DependencyMissingError("generate_thumbnail needs ffmpeg or ImageMagick")


# Server-backed surface (membership, locks, timeline channels, trailers).
get_projects = _server_only
get_users = _server_only
add_timeline_entry = _server_only
get_timeline_channel = _server_only
create_commit_trailer = _server_only
