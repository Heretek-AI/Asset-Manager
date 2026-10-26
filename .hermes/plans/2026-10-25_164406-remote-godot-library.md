# PLAN: Self-hosted remote game-asset library with Godot on-demand import (v0.3.0)

## Goal

Turn Asset-Manager into a self-hosted central asset library that a Godot editor
client browses remotely, downloading only chosen assets into the local project —
so devs import what they need without storing the whole library on device.

## Current context / assumptions

- Repo: `Heretek-AI/Asset-Manager`, branch `main`, tag `v0.2.0`, tree clean.
- Layout (all paths relative to repo root):
  - `assetmgr/` — Python host: `actions.py` (manifest discovery), `host.py`
    (dispatch), `store.py` (`*.approj` markers, `.meta.json` sidecars),
    `scan.py` (project scan), `godot.py` (ConfigFile parser, `.import`
    read/`set_import_params`, `IMPORTER_PARAMS`, `validate_import_params`),
    `cli.py` (every command has `--json`, single-document stdout).
  - `anchorpoint/` + `apsync/` — automation API + local engine
    (`generate_thumbnail` shells to ffmpeg/ImageMagick).
  - `native/` — Go binary `assetmgrd` (stdlib only): shells out to
    `python3 -m assetmgr.cli … --json`, serves embedded `native/web/`, JSON API
    (`GET /api/info|actions|validate|status|scan`, `POST /api/project-init|run|thumbnail`).
  - `Dockerfile` (Go build → `trixie-slim` + python3 + git + headless Godot 4.3
    + ffmpeg), `docker-compose.yml`, `actions/godot/*`, `tests/`.
- Runtimes available in this dev container: system `python3` (project venv at
  `/home/hermes/.hermes/cache/scratch/assetmgr-test-venv`), `go 1.24.4`,
  `godot` 4.3 at `/tmp/godot-bin/godot` (host) and `/usr/local/bin/godot`
  (image), `ffmpeg` 7.1.5, Docker engine 26.1.5.
- Anchorpoint (reference, anchorpoint.app): Git-based VC for game teams,
  **selective checkout** ("download only what you need"), asset pipeline
  *before* the engine, per-DCC integrations. We copy the *selective* idea,
  not the vendor: our library is a dumb content store + metadata, NOT git.
- Out of scope: vendor cloud, OAuth secrets, PySide6 shell, multiplayer
  locking (existing `ServerRequiredError` boundary stays).

## Architecture / proposed approach

Add a **library server** (new `library/` Python package: content-addressed
blob store + SQLite metadata + token auth) next to the existing local host;
the Go binary gains a reverse-proxy route plus a **Godot editor plugin**
(new `godot-plugin/addons/asset_library/`) that browses the remote catalog
from inside the editor and downloads chosen assets into `res://`, then
triggers a reimport. Artists keep terabytes server-side; devs pull kilobytes.

## Step-by-step tasks

Conventions for every task: test venv python is
`/home/hermes/.hermes/cache/scratch/assetmgr-test-venv/bin/python`.
TDD each task: write failing test → run → implement → run → `git commit`.
Never commit red. Paths are repo-relative.

### Phase A — library server core

**A1. Blob store module (`library/blobs.py`).**
Write `tests/test_blobs.py` first:
```python
from library.blobs import put, get_path
def test_roundtrip(tmp_path):
    digest = put(tmp_path / "store", b"abc")
    assert digest == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert get_path(tmp_path / "store", digest).read_bytes() == b"abc"
```
Run (expect FAIL, module missing):
`assetmgr-test-venv/bin/python -m pytest tests/test_blobs.py -q`
Implement `library/blobs.py`: `put(root, data)->sha256 hex` writing to
`root/ab/cd/rest`, `get_path(root, digest)->Path` (raise
`FileNotFoundError` if absent). Re-run: expect `1 passed`.
Commit: `git commit -qm "library: content-addressed blob store"`.

**A2. Metadata DB (`library/db.py`).**
Test first (`tests/test_library_db.py`): open sqlite in tmp, `add_asset()`
returns id, `get_asset()` round-trips
`{name, blob_sha256, size_bytes, kind, godot_importer, params_json, tags}`.
Run: expect FAIL. Implement with `sqlite3` stdlib, schema:
```sql
CREATE TABLE IF NOT EXISTS assets(
 id INTEGER PRIMARY KEY, name TEXT NOT NULL, blob_sha256 TEXT NOT NULL,
 size_bytes INTEGER NOT NULL, kind TEXT NOT NULL DEFAULT 'raw',
 godot_importer TEXT, params_json TEXT NOT NULL DEFAULT '{}',
 tags_json TEXT NOT NULL DEFAULT '[]',
 created_at TEXT NOT NULL DEFAULT (datetime('now')));
```
Re-run: expect pass. Commit.

**A3. HTTP API (`library/server.py`, stdlib `http.server`, no new deps).**
Endpoints (JSON; `Authorization: Bearer <token>` on all but `/health`):
`GET /health` → `{"ok":true}`; `GET /api/v1/assets?q=&tag=&kind=` →
`{"assets":[...]}`; `POST /api/v1/assets` (multipart: file + fields
name/kind/importer/params/tags) → `{"id":…}`; `GET /api/v1/assets/<id>/blob`
→ bytes. Token from env `ASSETMGR_LIBRARY_TOKEN`, compared with
`hmac.compare_digest`. Test with `urllib` in `tests/test_library_server.py`
spinning the server on port 0 in a thread. Run full suite:
`assetmgr-test-venv/bin/python -m pytest -q` → all pass. Commit.

**A4. CLI thin wrappers (`assetmgr library-*`).**
Add `library-init <dir>`, `library-push <file> --server URL --token T
[--name N --kind K --importer I --params JSON --tags a,b]`,
`library-pull <id> --server URL --token T --out PATH` in `assetmgr/cli.py`
following the existing `_cmd_*` + `--json` pattern. Tests in
`tests/test_cli_json.py` style against a live test server (reuse A3 helper).
Full suite green. Commit.

### Phase B — publish from existing projects

**B1. `godot::publish-to-library` action** (`actions/godot/publish/` +
`publish.py`, mirror `import_asset` structure): resolves project, uploads
selection via `library-push` equivalent (subprocess the CLI), toasts the new
asset id. Test dispatch with a stub server (A3 helper) asserting the blob
arrives byte-identical. Commit.

### Phase C — Godot editor plugin (the remote-import UX)

**C1. Plugin skeleton** (`godot-plugin/addons/asset_library/plugin.cfg`,
`plugin.gd` with `_enter_tree` adding a dock, `_exit_tree` removing it).
Verify headless: `godot --headless --path /tmp/gproj --quit` exits 0 with
the addon present (no script errors in stderr). Commit.

**C2. Dock panel** (`panel.tscn` + `panel.gd`): server URL + token fields
(persisted to `user://asset_library.cfg` via `ConfigFile`), search box,
`ItemList` of results from `GET /api/v1/assets`. Test: GDScript is
headless-testable only by running — assert via `--headless --script` probe
that search URL construction is correct (print + grep). Commit.

**C3. Download + import** (`download.gd`): `HTTPRequest` GET blob →
`FileAccess` write to `res://<name>` → `EditorFileSystem.scan()` (or
`--import` fallback) → toast with importer badge. Live test: real Godot 4.3
opens the demo project, downloads `hero.png` from the test server, asserts
`.godot/imported/hero.png-*.ctex` appears. Commit.

### Phase D — self-hosting

**D1. Compose service**: extend `docker-compose.yml` with `library:` reusing
the `assetmgr` image, `CMD ["assetmgr-library", ...]` (or `python -m
library.server`), named volume `library-data`, token via env file
(`.env.example` with `ASSETMGR_LIBRARY_TOKEN=changeme`). Verify:
`docker compose up -d --build library && curl -s localhost:8081/health`
→ `{"ok":true}`, then `docker compose down`. Commit.

**D2. Docs + README**: `docs/REMOTE_LIBRARY.md` (setup, token, plugin
install, selective-download workflow) + README section with the same two
screenshots pattern as v0.2.0. Commit.

### Phase E — release

**E1.** Bump `pyproject.toml` + `assetmgr/__init__.py` to `0.3.0`, full
suite + `go test ./...` green, commit, push, `gh release create v0.3.0`
with notes + rebuilt `assetmgrd` binary. Verify via
`gh release view v0.3.0 --json tagName,assets`.

## Tests / validation

- Per-task TDD as above; no task is done without its test green.
- Gates before push: `pytest -q` (expect 55+ new-count passing, skips only
  environmental), `gofmt -l .` empty, `go vet ./...` clean,
  `go test -count=1 ./...` ok.
- Live proofs required (not optional): C3 Godot download→import test, D1
  compose health check, E1 release asset presence.

## Risks, tradeoffs, and open questions

- **Godot plugin GDScript has no pytest**: live headless runs are the test
  harness; keep plugin logic thin, push decisions (validation, paths) into
  tested Python.
- **Binary assets in git**: screenshots only; never commit `.godot/`,
  `*.ctex`, or test fixtures >100KB (generate at test time, as today).
- **Auth is bearer-token minimal**: fine for self-hosted single-team use;
  multi-user ACLs are explicitly out of scope.
- **Large uploads**: stdlib server buffers to disk via `tempfile`; set a
  documented 2 GiB cap (`MAX_UPLOAD_BYTES`) rather than building chunked
  upload now (YAGNI).
- **Open question for the user**: one shared library per team, or
  per-project libraries? Plan assumes one server, many projects (token per
  team). If per-project isolation is needed, add a `project` column — ask
  before Phase A if unsure.
