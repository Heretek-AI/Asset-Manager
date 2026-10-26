"""Run the self-hosted asset library server.

First run: create a token, then start (or pass --token once to bootstrap
the ``default`` token)::

    python -m assetmgr.cli library-token-create alice --db library-data/library.db
    python -m library --store library-data/store --db library-data/library.db
"""

from __future__ import annotations

import argparse
import os
import sys

from library.server import DEFAULT_MAX_UPLOAD_BYTES, LibraryServer


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="assetmgr-library",
                                     description="Self-hosted asset library")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8081)
    parser.add_argument("--store", default="library-data/store",
                        help="blob store directory")
    parser.add_argument("--db", default="library-data/library.db",
                        help="metadata database file")
    parser.add_argument("--token", default="",
                        help="bootstrap the 'default' token on first run "
                        "(or ASSETMGR_LIBRARY_TOKEN)")
    parser.add_argument("--max-upload-bytes", type=int,
                        default=DEFAULT_MAX_UPLOAD_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = args.token or os.environ.get("ASSETMGR_LIBRARY_TOKEN", "")
    server = LibraryServer(args.store, args.db, token or None,
                           max_upload_bytes=args.max_upload_bytes)
    from library import db as library_db
    names = [t["name"] for t in library_db.list_tokens(server.conn)]
    if not names:
        print("warning: no API tokens exist; create one with "
              "assetmgr library-token-create <name> --db "
              + args.db, file=sys.stderr)
    print(f"asset-library on http://{args.host}:{args.port}"
          f" (store {args.store})", flush=True)
    server.serve_forever(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
