"""``assetmgr`` command line: reference-CLI-inspired, local-only.

Human-readable text is the default; every command also accepts ``--json``
for machine consumers (the native ``assetmgrd`` binary drives this).
"""

from __future__ import annotations

import argparse
import io
import json
import os
import subprocess
import sys
from contextlib import redirect_stdout

from assetmgr import __version__
from assetmgr.actions import discover
from assetmgr.errors import DependencyMissingError
from assetmgr.godot import find_godot_project_root, get_project_name
from assetmgr.host import DispatchError, run_action
from assetmgr.scan import scan_project
from assetmgr.store import find_project_root, init_project


def _emit(args: argparse.Namespace, text: str, payload: dict) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload))
    else:
        print(text)


def _cmd_actions(args: argparse.Namespace) -> int:
    found, errors = discover(args.root)
    scope = args.scope
    rows = []
    for manifest in found:
        if scope and not manifest.enabled_for_trigger(scope):
            continue
        rows.append(manifest)
        if not args.json:
            print(f"{manifest.manifest_id}  [{manifest.action_type}]  "
                  f"{manifest.name}  (enable={manifest.enable})")
    for problem in errors:
        print(f"warning: {problem}", file=sys.stderr)
    if args.json:
        print(json.dumps({"actions": [
            {"id": m.manifest_id, "name": m.name, "type": m.action_type,
             "category": m.category, "description": m.description,
             "enable": m.enable, "icon": m.icon_path,
             "triggers": sorted(m.register.keys())} for m in rows],
            "errors": errors}))
    return 0


def _cmd_validate(args: argparse.Namespace) -> int:
    _found, errors = discover(args.root)
    if args.json:
        print(json.dumps({"valid": not errors, "errors": errors}))
        return 1 if errors else 0
    for problem in errors:
        print(problem, file=sys.stderr)
    if errors:
        print(f"{len(errors)} invalid manifest(s)", file=sys.stderr)
        return 1
    print("all manifests valid")
    return 0


def _cmd_info(args: argparse.Namespace) -> int:
    _emit(args, f"asset-manager {__version__} (headless host, local-only)",
          {"name": "asset-manager", "version": __version__,
           "mode": "headless host, local-only"})
    return 0


def _cmd_project_init(args: argparse.Namespace) -> int:
    marker = init_project(args.directory, args.name, force=args.force)
    _emit(args, f"project initialised: {marker}", {"marker": marker})
    return 0


def _cmd_project_scan(args: argparse.Namespace) -> int:
    start = os.path.abspath(args.root)
    project_root = find_godot_project_root(start)
    if project_root is None:
        if args.json:
            print(json.dumps({"root": start, "error": "not a godot project"}))
        else:
            print(f"not a godot project: {start}", file=sys.stderr)
        return 1
    assets = scan_project(project_root)
    if args.json:
        print(json.dumps({"root": project_root,
                          "project_name": get_project_name(project_root),
                          "assets": assets}))
    else:
        for asset in assets:
            print(f"{asset['path']}  {asset['size_bytes']} bytes")
        print(f"{len(assets)} asset(s) in {project_root}")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    found, _errors = discover(args.root)
    wanted = [m for m in found if m.manifest_id == args.action_id]
    if not wanted:
        if args.json:
            print(json.dumps({"action_id": args.action_id,
                              "error": "unknown action"}))
        else:
            print(f"unknown action: {args.action_id}", file=sys.stderr)
        return 2
    buf = io.StringIO()
    try:
        if args.json:
            with redirect_stdout(buf):
                code = run_action(wanted[0], path=args.path or "")
        else:
            code = run_action(wanted[0], path=args.path or "")
    except DispatchError as exc:
        if args.json:
            print(json.dumps({"action_id": args.action_id, "error": str(exc)}))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"action_id": args.action_id, "exit_code": code,
                          "output": buf.getvalue()}))
    return code


def _parse_porcelain(output: str) -> tuple[str, list[str]]:
    branch, entries = "", []
    for line in output.splitlines():
        if line.startswith("## "):
            branch = line[3:]
        elif line.strip():
            entries.append(line)
    return branch, entries


def _cmd_thumbnail(args: argparse.Namespace) -> int:
    import apsync

    source = os.path.abspath(args.source)
    if not os.path.isfile(source):
        if args.json:
            print(json.dumps({"source": source, "error": "no such file"}))
        else:
            print(f"no such file: {source}", file=sys.stderr)
        return 2
    if args.out:
        destination = os.path.abspath(args.out)
    else:
        stem, _ext = os.path.splitext(os.path.basename(source))
        destination = os.path.join(os.path.dirname(source), stem + "_thumb.png")
    try:
        made = apsync.generate_thumbnail(source, destination)
    except DependencyMissingError as exc:
        if args.json:
            print(json.dumps({"source": source, "error": str(exc)}))
        else:
            print(f"thumbnail failed: {exc}", file=sys.stderr)
        return 3
    except Exception as exc:  # tool failure
        if args.json:
            print(json.dumps({"source": source, "error": str(exc)}))
        else:
            print(f"thumbnail failed: {exc}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps({"source": source, "destination": made}))
    else:
        print(made)
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    target = os.path.abspath(args.path or os.getcwd())
    root = find_project_root(target) or target
    completed = subprocess.run(
        ["git", "-C", root, "status", "--porcelain=v1", "--branch"],
        capture_output=True, text=True,
    )
    if completed.returncode != 0:
        if args.json:
            print(json.dumps({"root": root, "error": "not a git checkout"}))
        else:
            print(f"not a git checkout: {root}", file=sys.stderr)
        return 1
    branch, entries = _parse_porcelain(completed.stdout)
    if args.json:
        print(json.dumps({"root": root, "branch": branch,
                          "clean": not entries, "entries": entries}))
    else:
        print(completed.stdout.rstrip() or "(clean)")
    return 0


def _library_endpoint(args: argparse.Namespace) -> tuple[str, str]:
    server = args.server or os.environ.get("ASSETMGR_LIBRARY_URL", "")
    token = args.token or os.environ.get("ASSETMGR_LIBRARY_TOKEN", "")
    if not server or not token:
        raise SystemExit("library server/token required "
                         "(--server/--token or ASSETMGR_LIBRARY_URL/TOKEN)")
    return server, token


def _cmd_library_init(args: argparse.Namespace) -> int:
    from library import db as library_db

    root = os.path.abspath(args.directory)
    os.makedirs(root, exist_ok=True)
    db_path = os.path.join(root, "library.db")
    library_db.open_db(db_path).close()
    _emit(args, f"library initialised: {root}",
          {"root": root, "db": db_path})
    return 0


def _cmd_library_push(args: argparse.Namespace) -> int:
    from library.client import LibraryError, push

    try:
        server, token = _library_endpoint(args)
    except SystemExit as exc:
        return _die(args, str(exc), 2)
    if args.params:
        try:
            params = json.loads(args.params)
            if not isinstance(params, dict):
                raise ValueError
        except ValueError:
            return _die(args, "params must be a JSON object", 2)
    else:
        params = {}
    tags = [t for t in (args.tags or "").split(",") if t]
    try:
        result = push(server, token, args.file, name=args.name,
                      kind=args.kind, importer=args.importer,
                      params=params, tags=tags)
    except LibraryError as exc:
        return _die(args, str(exc), 1)
    _emit(args, f"uploaded as asset {result['id']}", result)
    return 0


def _cmd_library_pull(args: argparse.Namespace) -> int:
    from library.client import LibraryError, pull

    try:
        server, token = _library_endpoint(args)
    except SystemExit as exc:
        return _die(args, str(exc), 2)
    try:
        result = pull(server, token, args.asset_id, args.out)
    except LibraryError as exc:
        return _die(args, str(exc), 1)
    _emit(args, f"downloaded to {result['path']}", result)
    return 0


def _die(args: argparse.Namespace, message: str, code: int) -> int:
    if getattr(args, "json", False):
        print(json.dumps({"error": message}))
    else:
        print(f"error: {message}", file=sys.stderr)
    return code


def _add_json(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--json", action="store_true",
                        help="emit machine-readable JSON on stdout")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assetmgr",
                                     description="OSS asset manager (local host)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("actions", help="list discovered actions")
    p.add_argument("--root", default="actions")
    p.add_argument("--scope", default="",
                   help="only actions registered for this trigger")
    _add_json(p)
    p.set_defaults(func=_cmd_actions)

    p = sub.add_parser("validate", help="validate action manifests")
    p.add_argument("--root", default="actions")
    _add_json(p)
    p.set_defaults(func=_cmd_validate)

    p = sub.add_parser("info", help="host info")
    _add_json(p)
    p.set_defaults(func=_cmd_info)

    p = sub.add_parser("project-init", help="create a local project marker")
    p.add_argument("directory")
    p.add_argument("--name", required=True)
    p.add_argument("--force", action="store_true")
    _add_json(p)
    p.set_defaults(func=_cmd_project_init)

    p = sub.add_parser("project-scan", help="scan a Godot project for assets")
    p.add_argument("root", help="project root (or anything inside it)")
    _add_json(p)
    p.set_defaults(func=_cmd_project_scan)

    p = sub.add_parser("run", help="run one action by id")
    p.add_argument("action_id")
    p.add_argument("--root", default="actions")
    p.add_argument("--path", default="")
    _add_json(p)
    p.set_defaults(func=_cmd_run)

    p = sub.add_parser("status", help="git status of a project (offline)")
    p.add_argument("--path", default="")
    _add_json(p)
    p.set_defaults(func=_cmd_status)

    p = sub.add_parser("thumbnail", help="render a preview image (ffmpeg/ImageMagick)")
    p.add_argument("source")
    p.add_argument("--out", default="",
                   help="destination PNG (default: <name>_thumb.png beside source)")
    _add_json(p)
    p.set_defaults(func=_cmd_thumbnail)

    p = sub.add_parser("library-init", help="initialise a library store directory")
    p.add_argument("directory")
    _add_json(p)
    p.set_defaults(func=_cmd_library_init)

    p = sub.add_parser("library-push", help="upload a file to the library server")
    p.add_argument("file")
    p.add_argument("--server", default="")
    p.add_argument("--token", default="")
    p.add_argument("--name", default=None)
    p.add_argument("--kind", default="raw")
    p.add_argument("--importer", default=None)
    p.add_argument("--params", default="",
                   help="import params as a JSON object")
    p.add_argument("--tags", default="",
                   help="comma-separated tags")
    _add_json(p)
    p.set_defaults(func=_cmd_library_push)

    p = sub.add_parser("library-pull", help="download an asset from the library server")
    p.add_argument("asset_id", type=int)
    p.add_argument("--out", required=True)
    p.add_argument("--server", default="")
    p.add_argument("--token", default="")
    _add_json(p)
    p.set_defaults(func=_cmd_library_pull)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
