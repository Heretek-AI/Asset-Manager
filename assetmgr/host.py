"""Action dispatch: run python/command manifests with an injected Context."""

from __future__ import annotations

import os
import runpy
import subprocess

import anchorpoint

from .actions import ActionManifest, substitute_variables


class DispatchError(RuntimeError):
    """The action cannot run in this host."""


def build_context(action: ActionManifest, path: str = "",
                  extra_inputs: dict | None = None) -> anchorpoint.Context:
    path = os.path.abspath(path) if path else ""
    variables = {"path": path, "yaml_dir": action.yaml_dir}
    merged = {k: substitute_variables(str(v), variables)
              for k, v in action.inputs.items()}
    if extra_inputs:
        merged.update(extra_inputs)
    folder, filename = (os.path.split(path) + ("",))[:2] if path else ("", "")
    return anchorpoint.Context(
        type=action.category,
        path=path,
        folder=folder,
        filename=filename,
        suffix=os.path.splitext(filename)[1].lstrip("."),
        project_path="",
        yaml_dir=action.yaml_dir,
        module_path=action.source_path,
        app_dir=anchorpoint.get_application_dir(),
        inputs=merged,
        icon=action.icon_path,
        icon_color=action.icon_color,
    )


def run_action(action: ActionManifest, path: str = "",
               extra_inputs: dict | None = None) -> int:
    """Dispatch one action; returns the process exit code (0 = ok)."""
    if action.action_type == "package":
        raise DispatchError(f"{action.manifest_id}: packages list members, they do not run")
    if action.is_placeholder:
        raise DispatchError(f"{action.manifest_id}: placeholder (script: none)")
    ctx = build_context(action, path, extra_inputs)
    if action.action_type == "command":
        variables = {"path": path, "yaml_dir": action.yaml_dir,
                     "PATH": os.environ.get("PATH", "")}
        cmd = substitute_variables(action.command, variables)
        args = substitute_variables(action.arguments, variables) if action.arguments else ""
        env = dict(os.environ)
        for key, value in action.environment.items():
            env[key] = substitute_variables(value, variables)
        argv = (cmd + " " + args).strip().split()
        cwd = substitute_variables(action.working_directory, variables) or None
        try:
            completed = subprocess.run(argv, cwd=cwd, env=env)
        except FileNotFoundError:
            if action.toast_error:
                print(f"[assetmgr:error] {action.toast_error}")
            raise DispatchError(f"command not found: {cmd}")
        return completed.returncode
    script = os.path.join(action.yaml_dir, action.script)
    if not os.path.isfile(script):
        raise DispatchError(f"script missing: {script}")
    anchorpoint._push_context(ctx)
    try:
        runpy.run_path(script, run_name="__main__")
    finally:
        anchorpoint._pop_context()
    return 0
