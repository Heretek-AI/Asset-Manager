"""Godot project adapter: detect, read and safely extend Godot projects.

Covers the load-bearing project-model facts an asset manager needs:

- project discovery (walk up to ``project.godot``),
- reading ``project.godot`` / ``*.import`` files (Godot ConfigFile format),
- ``*.uid`` sidecar handling,
- copying external files into ``res://`` without touching editor state
  (reimport itself is left to headless Godot, see ``actions/godot/``).

Only observed on-disk formats are used; nothing here requires the editor.
"""

from __future__ import annotations

import os
import re
import shutil

PROJECT_FILE = "project.godot"
GODOT_DIR = ".godot"

_SECTION_RE = re.compile(r"^\[(.+)\]\s*$")
_ESCAPE_RE = re.compile(r"\\(\\|\"|n|t|r|u[0-9a-fA-F]{4})")


def _unescape(text: str) -> str:
    def _replace(match: re.Match[str]) -> str:
        seq = match.group(1)
        if seq == "n":
            return "\n"
        if seq == "t":
            return "\t"
        if seq == "r":
            return "\r"
        if seq.startswith("u"):
            return chr(int(seq[1:], 16))
        return seq  # \\ and \"

    return _ESCAPE_RE.sub(_replace, text)


def parse_godot_value(raw: str) -> object:
    """Parse one ConfigFile value (strings, bools, numbers, else raw text)."""
    text = raw.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return _unescape(text[1:-1])
    lowered = text.lower()
    if lowered in ("true", "false"):
        return lowered == "true"
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text


def parse_godot_config(text: str) -> dict[str, dict[str, object]]:
    """Parse Godot ConfigFile text into ``{section: {key: value}}``."""
    config: dict[str, dict[str, object]] = {}
    section = ""
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        match = _SECTION_RE.match(stripped)
        if match:
            section = match.group(1)
            config.setdefault(section, {})
            continue
        if "=" not in stripped or not section:
            continue
        key, _, value = stripped.partition("=")
        config[section][key.strip()] = parse_godot_value(value)
    return config


def find_godot_project_root(start: str) -> str | None:
    """Walk up from *start* to the folder holding ``project.godot``."""
    current = os.path.abspath(start)
    if os.path.isfile(current):
        current = os.path.dirname(current)
    while True:
        if os.path.isfile(os.path.join(current, PROJECT_FILE)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def is_godot_project(path: str) -> bool:
    """Whether *path* is (or is inside) a Godot project."""
    return find_godot_project_root(path) is not None


def read_project_config(root: str) -> dict[str, dict[str, object]]:
    """Parse the project's ``project.godot``."""
    marker = os.path.join(root, PROJECT_FILE)
    with open(marker, encoding="utf-8") as handle:
        return parse_godot_config(handle.read())


def get_project_name(root: str) -> str:
    """The configured project name, falling back to the folder name."""
    try:
        name = read_project_config(root).get("application", {}).get("config/name")
    except OSError:
        name = ""
    if isinstance(name, str) and name:
        return name
    return os.path.basename(os.path.abspath(root))


def read_uid(uid_path: str) -> str:
    """Read a ``*.uid`` sidecar, returning the bare uid string."""
    with open(uid_path, encoding="utf-8") as handle:
        return handle.read().strip()


def list_uid_files(root: str) -> list[str]:
    """All ``*.uid`` files under the project, sorted."""
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if GODOT_DIR in os.path.relpath(dirpath, root).split(os.sep):
            continue  # editor cache, not source state
        for filename in filenames:
            if filename.endswith(".uid"):
                found.append(os.path.join(dirpath, filename))
    return sorted(found)


def import_files_into_project(paths: list[str], root: str,
                               target_folder: str = "assets") -> list[str]:
    """Copy external files into the project; returns the destinations.

    Files already inside the project are returned unchanged (idempotent).
    Editor reimport is deliberately out of scope — run headless Godot
    (``actions/godot/reimport``) afterwards.
    """
    root = os.path.abspath(root)
    dest_dir = os.path.join(root, target_folder)
    os.makedirs(dest_dir, exist_ok=True)
    destinations: list[str] = []
    for source in paths:
        absolute = os.path.abspath(source)
        if os.path.commonpath([absolute, root]) == root:
            destinations.append(absolute)  # already in res://
            continue
        if not os.path.isfile(absolute):
            raise FileNotFoundError(absolute)
        destination = os.path.join(dest_dir, os.path.basename(absolute))
        if os.path.exists(destination) and os.path.samefile(absolute, destination):
            destinations.append(destination)
            continue
        destinations.append(str(shutil.copy2(absolute, destination)))
    return destinations
