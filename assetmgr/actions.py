"""Action manifest discovery, validation and trigger matching.

Implements the ``*.yaml`` action manifest format as observed in shipped
action packs (see docs/ACTION_YAML.md):

.. code-block:: yaml

    version: "1.0"
    action:
      name: Batch Rename
      id: ap::rename
      version: 1
      author: Example Author
      category: user
      type: python
      description: Renames a set of selected files
      icon:
        path: icons/rename.svg
      script: batch_rename.py
      register:
        file:
          enable: true
          filter: "*.png;*.jpg"
"""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, field
from typing import Any

import yaml

SCHEMA_VERSIONS = {"1.0", "1"}
ACTION_TYPES = {"python", "command", "package"}

# Registration points observed in shipped manifests.
REGISTER_TRIGGERS = {
    "file",
    "folder",
    "new_file",
    "new_folder",
    "new_task",
    "task",
    "sidebar",
    "workspace_overview",
    "join_project_files",
    "drive",
}

_VARIABLE_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class ManifestError(ValueError):
    """An action manifest is missing, malformed or invalid."""


def substitute_variables(text: str, variables: dict[str, str]) -> str:
    """Expand ``${name}`` placeholders; unknown names are left intact."""

    def _replace(match: re.Match[str]) -> str:
        key = match.group(1)
        return str(variables.get(key, match.group(0)))

    return _VARIABLE_RE.sub(_replace, text)


@dataclass
class ActionManifest:
    """One validated action manifest."""

    source_path: str
    manifest_id: str
    name: str
    action_type: str
    version: int = 1
    author: str = ""
    category: str = ""
    description: str = ""
    enable: Any = None
    icon_path: str = ""
    icon_color: str = ""
    script: str = ""
    command: str = ""
    arguments: str = ""
    working_directory: str = ""
    detach: bool = False
    environment: dict[str, str] = field(default_factory=dict)
    inputs: dict[str, Any] = field(default_factory=dict)
    settings: str = ""
    dependencies: list[str] = field(default_factory=list)
    platforms: list[str] = field(default_factory=list)
    members: list[str] = field(default_factory=list)
    register: dict[str, Any] = field(default_factory=dict)
    toast_error: str = ""

    @property
    def yaml_dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.source_path))

    @property
    def is_placeholder(self) -> bool:
        """Manifests with ``script: none`` reserve an id for host wiring."""
        return self.action_type == "python" and self.script.strip().lower() == "none"

    @classmethod
    def from_file(cls, path: str) -> "ActionManifest":
        with open(path, encoding="utf-8-sig") as handle:
            data = yaml.safe_load(handle)
        return cls.from_dict(path, data or {})

    @classmethod
    def from_dict(cls, path: str, data: dict[str, Any]) -> "ActionManifest":
        if not isinstance(data, dict):
            raise ManifestError(f"{path}: top level must be a mapping")
        schema = str(data.get("version", "1.0"))
        if schema not in SCHEMA_VERSIONS:
            raise ManifestError(f"{path}: unsupported manifest version {schema!r}")
        node = data.get("action")
        if not isinstance(node, dict):
            raise ManifestError(f"{path}: missing 'action' mapping")
        for key in ("name", "id", "type"):
            if not node.get(key):
                raise ManifestError(f"{path}: action.{key} is required")
        action_type = node["type"]
        if action_type not in ACTION_TYPES:
            raise ManifestError(f"{path}: unknown type {action_type!r}")
        if action_type == "package" and not node.get("actions"):
            raise ManifestError(f"{path}: package actions need an 'actions' member list")
        if action_type == "command" and not node.get("command"):
            raise ManifestError(f"{path}: command actions need a 'command'")
        if action_type == "python" and not node.get("script"):
            raise ManifestError(f"{path}: python actions need a 'script'")

        register = node.get("register", {}) or {}
        if not isinstance(register, dict):
            raise ManifestError(f"{path}: 'register' must be a mapping")
        for trigger in register:
            if trigger not in REGISTER_TRIGGERS:
                raise ManifestError(f"{path}: unknown register trigger {trigger!r}")

        icon = node.get("icon", {}) or {}
        toast = node.get("toast", {}) or {}
        return cls(
            source_path=os.path.abspath(path),
            manifest_id=str(node["id"]),
            name=str(node["name"]),
            action_type=action_type,
            version=int(node.get("version", 1)),
            author=str(node.get("author", "")),
            category=str(node.get("category", "")),
            description=str(node.get("description", "")),
            enable=node.get("enable"),
            icon_path=str(icon.get("path", "")),
            icon_color=str(icon.get("color", "")),
            script=str(node.get("script", "")),
            command=str(node.get("command", "")),
            arguments=str(node.get("arguments", "")),
            working_directory=str(node.get("workingDirectory", "")),
            detach=bool(node.get("detach", False)),
            environment=dict(node.get("environment", {}) or {}),
            inputs=dict(node.get("inputs", {}) or {}),
            settings=str(node.get("settings", "")),
            dependencies=list(node.get("dependencies", []) or []),
            platforms=list(node.get("platforms", []) or []),
            members=list(node.get("actions", []) or []),
            register=register,
            toast_error=str((toast.get("error", {}) or {}).get("message", "")),
        )

    def enabled_for_trigger(self, trigger: str) -> bool:
        """Whether this action shows up for a registration point.

        ``enable`` accepts a bool or a hook-module name. A hook name means
        dynamic visibility evaluated by the host; without hook support it
        counts as visible so hosts fail open instead of hiding actions.
        """
        node = self.register.get(trigger)
        if node is None:
            return False
        if isinstance(node, bool):
            return node
        if isinstance(node, dict):
            flag = node.get("enable", False)
            return True if isinstance(flag, str) else bool(flag)
        return False

    def matches_file(self, trigger: str, filename: str) -> bool:
        """Trigger gate plus ``;``-separated wildcard ``filter`` matching."""
        if not self.enabled_for_trigger(trigger):
            return False
        node = self.register.get(trigger)
        filt = ""
        if isinstance(node, dict):
            filt = str(node.get("filter", "") or "")
        if not filt:
            return True
        base = os.path.basename(filename).lower()
        patterns = [p.strip().lower() for p in filt.split(";") if p.strip()]
        return any(fnmatch.fnmatchcase(base, pattern) for pattern in patterns)


def discover(root: str) -> tuple[list[ActionManifest], list[str]]:
    """Walk *root* for action manifests.

    Returns ``(found, errors)``; found is sorted by manifest id so hosts get
    deterministic menus. Invalid files are reported, never fatal.
    """
    found: list[ActionManifest] = []
    errors: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            if not filename.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(dirpath, filename)
            try:
                found.append(ActionManifest.from_file(path))
            except Exception as exc:  # invalid manifests are skipped with a note
                errors.append(f"{path}: {exc}")
    found.sort(key=lambda manifest: manifest.manifest_id)
    return found, errors
