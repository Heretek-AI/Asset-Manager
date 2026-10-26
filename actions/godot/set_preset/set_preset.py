"""Apply an import preset: update [params] in the asset's *.import file."""

import json
import os

import anchorpoint
from assetmgr.godot import (
    find_godot_project_root,
    parse_godot_value,
    read_import,
    set_import_params,
    validate_import_params,
)


def _parse_params(raw: object) -> dict:
    """Accept a dict, a JSON object, or ``key=value`` lines."""
    if isinstance(raw, dict):
        return dict(raw)
    text = str(raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError("params JSON must be an object")
        return dict(data)
    params: dict = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(";") or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"bad params line (want key=value): {line!r}")
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            raise ValueError(f"bad params line (want key=value): {line!r}")
        params[key] = parse_godot_value(value.strip())
    return params


ctx = anchorpoint.get_context()
selection = [*(ctx.selected_files or []), *(ctx.selected_folders or [])]
if ctx.path and ctx.path not in selection:
    selection.append(ctx.path)

target = str(ctx.inputs.get("target", "") or "").strip()
asset = target or (selection[0] if selection else "")

if asset.startswith("res://"):
    asset = asset[len("res://"):]

root = None
if ctx.project_path:
    root = find_godot_project_root(ctx.project_path)
if root is None and asset:
    root = find_godot_project_root(asset)
if root is None:
    anchorpoint.UI().show_error("Not a Godot project",
                                "No project.godot found above the selection.")
    raise SystemExit(1)

if asset and not os.path.isabs(asset):
    asset = os.path.join(root, asset)
if asset.endswith(".import"):
    import_path = asset
elif asset and os.path.isdir(asset):
    anchorpoint.UI().show_error("Set import preset failed",
                                f"{asset!r} is a folder; select an asset file.")
    raise SystemExit(1)
else:
    import_path = (asset + ".import") if asset else ""
if not import_path or not os.path.isfile(import_path):
    anchorpoint.UI().show_error(
        "Set import preset failed",
        f"No *.import sidecar for {asset or 'empty selection'!r} "
        "(reimport the project first).")
    raise SystemExit(1)

try:
    params = _parse_params(ctx.inputs.get("params", ""))
except ValueError as exc:
    anchorpoint.UI().show_error("Set import preset failed", str(exc))
    raise SystemExit(1)
if not params:
    anchorpoint.UI().show_error("Set import preset failed",
                                "No import params given in the 'params' input.")
    raise SystemExit(1)

written = set_import_params(import_path, params)
importer = str(read_import(import_path).get("remap", {}).get("importer") or "")
unknown = validate_import_params(importer, params) if importer else []
note = (f" WARNING: {importer or 'unknown importer'} does not declare "
        f"{', '.join(unknown)} (Godot will ignore them)."
        if unknown else "")
anchorpoint.UI().show_success(
    "Import preset updated",
    f"{len(written)} param(s) in {os.path.basename(import_path)} "
    f"(run godot::reimport to refresh the editor cache).{note}")
