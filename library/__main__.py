"""Run the self-hosted asset library server.

Token via ``--token`` or ``ASSETMGR_LIBRARY_TOKEN`` (required).
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
                        help="bearer token (or ASSETMGR_LIBRARY_TOKEN)")
    parser.add_argument("--max-upload-bytes", type=int,
                        default=DEFAULT_MAX_UPLOAD_BYTES)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    token = args.token or os.environ.get("ASSETMGR_LIBRARY_TOKEN", "")
    if not token:
        print("error: library token required (--token or ASSETMGR_LIBRARY_TOKEN)",
              file=sys.stderr)
        return 2
    server = LibraryServer(args.store, args.db, token,
                           max_upload_bytes=args.max_upload_bytes)
    print(f"asset-library on http://{args.host}:{args.port}"
          f" (store {args.store})", flush=True)
    server.serve_forever(args.host, args.port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
