"""``assetmgr`` command line: reference-CLI-inspired, local-only."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from assetmgr import __version__
from assetmgr.actions import discover
from assetmgr.host import DispatchError, run_action
from assetmgr.store import find_project_root, init_project


def _cmd_actions(args: argparse.Namespace) -> int:
    found, errors = discover(args.root)
    scope = args.scope
    for manifest in found:
        if scope and not manifest.enabled_for_trigger(scope):
            continue
        flag = manifest.enable
        print(f"{manifest.manifest_id}  [{manifest.action_type}]  "
              f"{manifest.name}  (enable={flag})")
    for problem in errors:
        print(f"warning: {problem}", file=sys.stderr)
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    _found, errors = discover(args.root)
    for problem in errors:
        print(problem, file=sys.stderr)
    if errors:
        print(f"{len(errors)} invalid manifest(s)", file=sys.stderr)
        return 1
    print("all manifests valid")
    return 0


def _cmd_info(_args: argparse.Namespace) -> int:
    print(f"asset-manager {__version__} (headless host, local-only)")
    return 0


def _cmd_project_init(args: argparse.Namespace) -> int:
    marker = init_project(args.directory, args.name, force=args.force)
    print(f"project initialised: {marker}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    found, _errors = discover(args.root)
    wanted = [m for m in found if m.manifest_id == args.action_id]
    if not wanted:
        print(f"unknown action: {args.action_id}", file=sys.stderr)
        return 2
    try:
        return run_action(wanted[0], path=args.path or "")
    except DispatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _cmd_status(args: argparse.Namespace) -> int:
    target = os.path.abspath(args.path or os.getcwd())
    root = find_project_root(target) or target
    completed = subprocess.run(
        ["git", "-C", root, "status", "--porcelain=v1", "--branch"],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        print(f"not a git checkout: {root}", file=sys.stderr)
        return 1
    print(completed.stdout.rstrip() or "(clean)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assetmgr",
                                     description="OSS asset manager (local host)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("actions", help="list discovered actions")
    p.add_argument("--root", default="actions")
    p.add_argument("--scope", default="",
                   help="only actions registered for this trigger")
    p.set_defaults(func=_cmd_actions)

    p = sub.add_parser("validate", help="validate action manifests")
    p.add_argument("--root", default="actions")
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("info", help="host info")
    p.set_defaults(func=_cmd_info)

    p = sub.add_parser("project-init", help="create a local project marker")
    p.add_argument("directory")
    p.add_argument("--name", required=True)
    p.add_argument("--force", action="store_true")
    p.set_defaults(func=_cmd_project_init)

    p = sub.add_parser("run", help="run one action by id")
    p.add_argument("action_id")
    p.add_argument("--root", default="actions")
    p.add_argument("--path", default="")
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("status", help="git status of a project (offline)")
    p.add_argument("--path", default="")
    p.set_defaults(func=_cmd_status)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
