# Open gaps and how to close them

1. **`apsync.*` native signatures** — 40+ classes live only in the compiled
   binding; reimplemented here from the stub + samples. Close with
   `pybind11` introspection (`dir()/help()`) on a Windows install.
2. **Daemon wire schemas** (`connect-req`, `action-dispatch` JSON) — needs a
   traffic capture of the local IPC loop; no network claims made.
3. **Vendor REST/gRPC paths** — only hosts observed (`cloud.`, `grpc--cloud.`);
   server features are out of scope by design (see server boundary).
4. **`enable:` hook contract** — hook-script arg/return convention for dynamic
   visibility; host currently fails open (hook name ⇒ visible).
5. **`store:` scopes** (`user|action|project`) — persistence backend for
   prompted inputs; defaults to in-run values in v0.1.
6. **Thumbnail job schema** — preview/detail pixel policy beyond the
   documented 2048 cap; external tools used as black boxes.
7. **Graphical shell** — PySide6/QML browser per `docs/ARCHITECTURE.md`;
   headless `UI`/`Dialog` define the seam.
8. **OAuth client ids** seen in config constants are upstream secrets and are
   deliberately NOT shipped; the OSS build uses user-supplied credentials.
