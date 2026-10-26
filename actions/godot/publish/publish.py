"""Publish the selection to the self-hosted asset library."""

import json
import os
import subprocess
import sys

import anchorpoint
from assetmgr.godot import describe_for_library, find_godot_project_root

ctx = anchorpoint.get_context()
selection = [*(ctx.selected_files or []), *(ctx.selected_folders or [])]
if ctx.path and ctx.path not in selection:
    selection.append(ctx.path)
files = [p for p in selection if p and os.path.isfile(p)]

root = None
if ctx.project_path:
    root = find_godot_project_root(ctx.project_path)
if root is None and ctx.path:
    root = find_godot_project_root(ctx.path)
if root is None:
    anchorpoint.UI().show_error("Not a Godot project",
                                "No project.godot found above the selection.")
    raise SystemExit(1)
if not files:
    anchorpoint.UI().show_error("Publish failed", "No files selected.")
    raise SystemExit(1)

server = str(ctx.inputs.get("server", "") or "")
token = str(ctx.inputs.get("token", "") or "")
cli = [sys.executable, "-m", "assetmgr.cli"]
published: list[int] = []
for path in files:
    described = describe_for_library(path)
    argv = cli + ["library-push", path, "--json"]
    if server:
        argv += ["--server", server]
    if token:
        argv += ["--token", token]
    argv += ["--kind", described["kind"]]
    if described["importer"]:
        argv += ["--importer", str(described["importer"]),
                 "--params", json.dumps(described["params"])]
    completed = subprocess.run(argv, capture_output=True, text=True)
    if completed.returncode != 0:
        anchorpoint.UI().show_error(
            "Publish failed",
            (completed.stderr or completed.stdout).strip()[-300:])
        raise SystemExit(1)
    try:
        published.append(int(json.loads(completed.stdout)["id"]))
    except (ValueError, KeyError):
        anchorpoint.UI().show_error("Publish failed",
                                    "library returned an unreadable reply")
        raise SystemExit(1)
anchorpoint.UI().show_success(
    "Published to library",
    f"{len(published)} file(s), asset {published[0]}"
    + (f" (+{len(published) - 1} more)" if len(published) > 1 else ""))
