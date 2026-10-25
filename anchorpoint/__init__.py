"""Headless UI/context bridge for action scripts (``import anchorpoint``).

The desktop shell injects one :class:`Context` per action run; scripts use
``anchorpoint.get_context()`` to reach it. Outside a run (plain ``python``),
:func:`get_context` raises — exactly like the reference host, where the
bridge only exists inside the application process.
"""

from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass, field
from enum import IntEnum

_local = threading.local()


class ServerRequiredError(RuntimeError):
    """Operation needs the vendor sync server (locks, notifications, ...)."""


class ActionButtonType(IntEnum):
    Primary = 0
    Secondary = 1
    SecondaryText = 2
    Danger = 3


class BrowseType(IntEnum):
    File = 1
    Folder = 2


class ChangeSource(IntEnum):
    You = 0
    Other = 1
    Action = 2


class TimelineChannelModuleState(IntEnum):
    NONE = 0
    UNLOADED = 1
    UNSYNCED = 2
    CONFLICTED = 3


class VCConflictHandling(IntEnum):
    TakeOurs = 0
    TakeTheirs = 1
    External = 2
    Cancel = 3


class VCFileStatus(IntEnum):
    Unknown = 0
    New = 1
    Deleted = 2
    Modified = 3
    Renamed = 4
    Conflicted = 5


@dataclass
class VCChange:
    path: str
    status: VCFileStatus = VCFileStatus.Unknown


@dataclass
class Context:
    """Values the host populates for one action invocation."""

    type: str = ""
    path: str = ""
    folder: str = ""
    filename: str = ""
    suffix: str = ""
    selected_files: list[str] = field(default_factory=list)
    selected_folders: list[str] = field(default_factory=list)
    selected_tasks: list[str] = field(default_factory=list)
    project_id: str = ""
    project_path: str = ""
    workspace_id: str = ""
    yaml_dir: str = ""
    module_path: str = ""
    app_dir: str = ""
    username: str = ""
    email: str = ""
    user_id: str = ""
    inputs: dict = field(default_factory=dict)
    icon: str = ""
    icon_color: str = ""


def get_context() -> Context:
    ctx = getattr(_local, "context", None)
    if ctx is None:
        raise RuntimeError("no action context: code runs outside an action dispatch")
    return ctx


def _push_context(ctx: Context) -> None:
    _local.context = ctx


def _pop_context() -> None:
    _local.context = None


class UI:
    """Headless stand-in: records toasts, prints to stdout."""

    def __init__(self) -> None:
        self.toasts: list[tuple[str, str, str]] = []

    def _toast(self, kind: str, title: str, description: str = "") -> None:
        self.toasts.append((kind, title, description))
        print(f"[assetmgr:{kind}] {title} {description}".rstrip())

    def show_success(self, title: str, description: str = "") -> None:
        self._toast("success", title, description)

    def show_info(self, title: str, description: str = "") -> None:
        self._toast("info", title, description)

    def show_error(self, title: str, description: str = "") -> None:
        self._toast("error", title, description)


class Progress:
    """Console progress job usable as a context manager."""

    def __init__(self, title: str, text: str = "", infinite: bool = True,
                 cancelable: bool = False) -> None:
        self.title = title
        self.text = text
        self.canceled = False
        self._value = 0.0

    def __enter__(self) -> "Progress":
        print(f"[assetmgr:progress:start] {self.title}")
        return self

    def __exit__(self, *exc: object) -> None:
        self.finish()

    def report_progress(self, value: float) -> None:
        self._value = max(0.0, min(1.0, float(value)))

    def set_text(self, text: str) -> None:
        self.text = text

    def finish(self) -> None:
        print(f"[assetmgr:progress:done] {self.title}")

    def stop_progress(self) -> None:
        self.finish()


class DialogEntry:
    """Fluent dialog builder (headless: records rows, returns defaults)."""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def _add(self, kind: str, **kwargs: object) -> "DialogEntry":
        self.rows.append({"kind": kind, **kwargs})
        return self

    def add_text(self, text: str, **kwargs: object) -> "DialogEntry":
        return self._add("text", text=text, **kwargs)

    def add_input(self, default: str = "", placeholder: str = "",
                  var: str = "", **kwargs: object) -> "DialogEntry":
        return self._add("input", default=default, placeholder=placeholder,
                         var=var, **kwargs)

    def add_checkbox(self, default: bool = False, text: str = "",
                     var: str = "", **kwargs: object) -> "DialogEntry":
        return self._add("checkbox", default=default, text=text, var=var, **kwargs)

    def add_button(self, text: str, var: str = "",
                   **kwargs: object) -> "DialogEntry":
        return self._add("button", text=text, var=var, **kwargs)

    def add_dropdown(self, default: str = "", values: list | None = None,
                     var: str = "", **kwargs: object) -> "DialogEntry":
        return self._add("dropdown", default=default,
                         values=values or [], var=var, **kwargs)

    def get_value(self, var: str) -> object:
        for row in self.rows:
            if row.get("var") == var:
                return row.get("default")
        return None


class Dialog(DialogEntry):
    def __init__(self, title: str = "") -> None:
        super().__init__()
        self.title = title

    def show(self) -> dict:
        """Headless show: returns {var: default} without blocking."""
        return {r["var"]: r.get("default") for r in self.rows if r.get("var")}

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

_cache: dict[str, object] = {}


def get_api():  # lazy import breaks no cycles
    import apsync
    return apsync


def temp_dir() -> str:
    return tempfile.mkdtemp(prefix="assetmgr-")


def get_application_dir() -> str:
    return os.path.dirname(os.path.abspath(__file__))


def get_config() -> dict:
    return {}


def check_application(path: str, info: str = "", name: str | None = None) -> bool:
    return os.path.exists(path)


def get_alternative_name(path: str) -> str:
    """Return a free sibling path by appending `` (n)`` before the suffix."""
    base, ext = os.path.splitext(path)
    candidate, n = path, 1
    while os.path.exists(candidate):
        n += 1
        candidate = f"{base} ({n}){ext}"
    return candidate


def is_network_drive(path: str) -> bool:  # network-share detection is OS-specific
    return False


def log_error(message: str) -> None:
    print(f"[assetmgr:error] {message}")


def log_success(message: str) -> None:
    print(f"[assetmgr:ok] {message}")


def get_cache(key: str) -> object:
    return _cache.get(key)


def set_cache(key: str, value: object) -> None:
    _cache[key] = value


def has_cache(key: str) -> bool:
    return key in _cache


def reset_cache() -> None:
    _cache.clear()


def join_project_path(*parts: str) -> str:
    return os.path.join(*parts)


def show_in_explorer(path: str) -> None:
    print(f"[assetmgr:reveal] {path}")


def copy_files_to_clipboard(file_paths: list[str]) -> None:
    print(f"[assetmgr:clipboard] {len(file_paths)} path(s)")


def create_commit_deeplink(channel_entry_id: str, channel_id: str,
                           branch: str | None = None,
                           module: str | None = None) -> str:
    target = f"{channel_id}/{channel_entry_id}"
    if branch:
        target += f"?branch={branch}"
    return f"ap://hook/{target}"


def _server_only(*args: object, **kwargs: object):
    raise ServerRequiredError("this operation requires the sync server")


# Collaboration / server-backed surface: same names, explicit boundary.
lock = _server_only
unlock = _server_only
get_locks = _server_only
update_locks = _server_only
evaluate_locks = _server_only
locks_disabled = _server_only
locks_readonly_enabled = _server_only
schedule_channel_notification = _server_only
schedule_custom_notification = _server_only
get_channel_info = _server_only
update_channel_info = _server_only
get_unsynced_files = _server_only
update_unsynced_files = _server_only
remove_unsynced_files = _server_only
