"""Copy the selection into the enclosing Godot project (res://)."""

import anchorpoint
from assetmgr.godot import find_godot_project_root, import_files_into_project

ctx = anchorpoint.get_context()
selection = [*(ctx.selected_files or []), *(ctx.selected_folders or [])]
if ctx.path and ctx.path not in selection:
    selection.append(ctx.path)

root = None
if ctx.project_path:
    root = find_godot_project_root(ctx.project_path)
if root is None and ctx.path:
    root = find_godot_project_root(ctx.path)
if root is None:
    anchorpoint.UI().show_error("Not a Godot project",
                                "No project.godot found above the selection.")
    raise SystemExit(1)

destinations = import_files_into_project(
    selection, root,
    target_folder=str(ctx.inputs.get("target_folder", "assets") or "assets"))
anchorpoint.UI().show_success(
    "Imported into Godot project",
    f"{len(destinations)} file(s) -> res:// "
    "(run godot::reimport to refresh the editor cache)")
