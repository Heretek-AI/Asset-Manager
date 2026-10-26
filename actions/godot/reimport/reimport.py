"""Refresh the editor import cache via headless Godot."""

import shutil
import subprocess

import anchorpoint
from assetmgr.godot import find_godot_project_root

ctx = anchorpoint.get_context()
root = None
if ctx.project_path:
    root = find_godot_project_root(ctx.project_path)
if root is None and ctx.path:
    root = find_godot_project_root(ctx.path)
if root is None:
    anchorpoint.UI().show_error("Not a Godot project",
                                "No project.godot found above the selection.")
    raise SystemExit(1)

exe = str(ctx.inputs.get("godot", "godot") or "godot")
resolved = shutil.which(exe) or (exe if anchorpoint.check_application(exe) else "")
if not resolved:
    anchorpoint.UI().show_error(
        "Godot not found",
        f"Executable {exe!r} is not on PATH. Set the 'godot' action input.")
    raise SystemExit(1)

with anchorpoint.Progress("Reimporting Godot project") as job:
    job.set_text("godot --headless --import ...")
    completed = subprocess.run(
        [resolved, "--headless", "--path", root, "--import"],
        capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        anchorpoint.UI().show_error(
            "Reimport failed", completed.stderr.strip()[-500:])
        raise SystemExit(1)
anchorpoint.UI().show_success("Reimport finished",
                              "Editor cache (.godot/) is up to date.")
