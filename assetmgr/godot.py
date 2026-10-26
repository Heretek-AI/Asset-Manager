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
from typing import Any

PROJECT_FILE = "project.godot"
GODOT_DIR = ".godot"

_SECTION_RE = re.compile(r"^\[(.+)\]\s*$")
_KEY_RE = re.compile(r"^[A-Za-z0-9_/@.\-]+\s*=")
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


def _split_top_level(text: str) -> list[str]:
    """Split on commas that are not inside double quotes."""
    parts, current, in_quotes, escape = [], "", False, False
    for char in text:
        if escape:
            current += char
            escape = False
        elif char == "\\" and in_quotes:
            current += char
            escape = True
        elif char == '"':
            current += char
            in_quotes = not in_quotes
        elif char == "," and not in_quotes:
            parts.append(current)
            current = ""
        else:
            current += char
    parts.append(current)
    return parts


def parse_godot_value(raw: str) -> object:
    """Parse one ConfigFile value (strings, bools, numbers, arrays).

    Dictionaries stay raw text: Godot's ``{...}`` blocks have no stable
    one-line form worth re-parsing here.
    """
    text = raw.strip()
    if len(text) >= 2 and text.startswith('"') and text.endswith('"'):
        return _unescape(text[1:-1])
    if text.startswith("[") and text.endswith("]"):
        return [parse_godot_value(item) for item in _split_top_level(text[1:-1])
                if item.strip()]
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


def parse_godot_config(text: str) -> dict[str, dict[str, Any]]:
    """Parse Godot ConfigFile text into ``{section: {key: value}}``.

    Handles multi-line values (Godot writes dict/array values across
    lines in ``*.import`` files): a line without ``=`` continues the
    previous key's value.
    """
    raw: dict[str, dict[str, str]] = {}
    section = ""
    pending_key: str | None = None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith(";"):
            continue
        match = _SECTION_RE.match(stripped)
        if match:
            section = match.group(1)
            raw.setdefault(section, {})
            pending_key = None
            continue
        if section and _KEY_RE.match(stripped):
            key, _, value = stripped.partition("=")
            key = key.strip()
            raw[section][key] = value.strip()
            pending_key = key
            continue
        if pending_key is not None and section:
            raw[section][pending_key] += "\n" + stripped
    resolved: dict[str, dict[str, Any]] = {}
    for section_name, keys in raw.items():
        resolved[section_name] = {k: parse_godot_value(v)
                                  for k, v in keys.items()}
    return resolved


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


def read_project_config(root: str) -> dict[str, dict[str, Any]]:
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


def list_import_files(root: str) -> list[str]:
    """All ``*.import`` files in the project, sorted (.godot/ excluded)."""
    found: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        if GODOT_DIR in os.path.relpath(dirpath, root).split(os.sep):
            continue
        for filename in filenames:
            if filename.endswith(".import"):
                found.append(os.path.join(dirpath, filename))
    return sorted(found)


def read_import(import_path: str) -> dict[str, dict[str, Any]]:
    """Parse a ``*.import`` sidecar into ``{section: {key: value}}``."""
    with open(import_path, encoding="utf-8") as handle:
        return parse_godot_config(handle.read())


def _escape_godot_string(text: str) -> str:
    """Escape a string for Godot ConfigFile one-line form."""
    out: list[str] = []
    for char in text:
        if char == "\\":
            out.append("\\\\")
        elif char == '"':
            out.append('\\"')
        elif char == "\n":
            out.append("\\n")
        elif char == "\t":
            out.append("\\t")
        elif char == "\r":
            out.append("\\r")
        elif ord(char) < 0x20:
            out.append(f"\\u{ord(char):04x}")
        else:
            out.append(char)
    return "".join(out)


def format_godot_value(value: object) -> str:
    """Serialize a Python value to Godot ConfigFile one-line form."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(format_godot_value(item) for item in value) + "]"
    return f'"{_escape_godot_string(str(value))}"'


def _split_line_ending(line: str) -> tuple[str, str]:
    """Split a kept-ends line into ``(content, ending)``."""
    if line.endswith("\r\n"):
        return line[:-2], "\r\n"
    if line.endswith("\n") or line.endswith("\r"):
        return line[:-1], line[-1:]
    return line, ""


def set_import_params(import_path: str, params: dict[str, object]) -> list[str]:
    """Update keys in the ``[params]`` section of a ``*.import`` file.

    Every other byte is preserved: comments, blank lines, section order,
    key order and unrelated values are untouched; only targeted key lines
    change, and keys missing from ``[params]`` are appended at its end
    (a missing ``[params]`` section is appended at end of file).

    Returns the keys that were written.
    """
    with open(import_path, encoding="utf-8", newline="") as handle:
        text = handle.read()
    parts = [_split_line_ending(line)
             for line in text.splitlines(keepends=True)]

    section = ""
    pending: list | None = None  # [key, start line, end line (excl.)]
    spans: dict[str, list[tuple[int, int]]] = {}
    header_idx: int | None = None
    end_idx: int | None = None

    def _flush() -> None:
        nonlocal pending
        if pending is not None:
            spans.setdefault(pending[0], []).append((pending[1], pending[2]))
            pending = None

    for index, (content, _ending) in enumerate(parts):
        stripped = content.strip()
        section_match = _SECTION_RE.match(stripped) if stripped else None
        if section_match:
            _flush()
            section = section_match.group(1)
            if section == "params":
                if header_idx is None:
                    header_idx = index
            elif header_idx is not None and end_idx is None:
                end_idx = index
            continue
        if not stripped or stripped.startswith(";"):
            continue
        if section and _KEY_RE.match(stripped):
            _flush()
            if section == "params":
                pending = [stripped.partition("=")[0].strip(),
                           index, index + 1]
            continue
        if pending is not None:
            pending[2] = index + 1
    _flush()
    if end_idx is None:
        end_idx = len(parts)

    if not params:
        return []

    rows = [list(part) for part in parts]
    removals: set[int] = set()
    if header_idx is None:
        if rows == [["", ""]]:
            rows = []
        elif rows and rows[-1][1] == "":
            rows[-1][1] = "\n"
        header_idx = len(rows)
        rows.append(["[params]", "\n"])
        end_idx = len(rows)
    ending = "\r\n" if any(line_ending == "\r\n"
                            for _, line_ending in rows) else "\n"
    if rows and rows[-1][1] == "":
        rows[-1][1] = ending
    insert_at = end_idx
    while insert_at > header_idx + 1 and rows[insert_at - 1][0] == "":
        insert_at -= 1  # keep the block's trailing blank line last
    for key, value in params.items():
        updated = f"{key}={format_godot_value(value)}"
        if key in spans:
            for start, end in spans[key]:
                rows[start] = [updated, rows[start][1] or "\n"]
                removals.update(range(start + 1, end))
        else:
            rows.insert(insert_at, [updated, ending])
            for other_spans in spans.values():
                for pos, (start, end) in enumerate(other_spans):
                    if start >= insert_at:
                        other_spans[pos] = (start + 1, end + 1)
            removals = {i + 1 if i >= insert_at else i for i in removals}
            insert_at += 1

    kept = [content + line_ending
            for i, (content, line_ending) in enumerate(rows)
            if i not in removals]
    with open(import_path, "w", encoding="utf-8", newline="") as handle:
        handle.write("".join(kept))
    return list(params)


def import_summary(parsed: dict[str, dict[str, Any]]) -> dict[str, object]:
    """Condense a parsed ``*.import`` to importer/type/uid/files/params."""
    remap = parsed.get("remap", {})
    deps = parsed.get("deps", {})
    dest = deps.get("dest_files", [])
    return {
        "importer": remap.get("importer"),
        "type": remap.get("type"),
        "uid": remap.get("uid"),
        "path": remap.get("path"),
        "source_file": deps.get("source_file"),
        "dest_files": dest if isinstance(dest, list) else [dest],
        "params": parsed.get("params", {}),
    }
