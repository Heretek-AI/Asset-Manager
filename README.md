# Asset-Manager

An independent, open-source asset manager for creative teams: a local-first
project hub with an **action plug-in host**, **git-first version control**
and a **Python automation API**.

> **Clean-room notice.** Asset-Manager is an original implementation written
> from observed interface facts (file formats, CLI shapes, public API
> signatures). It contains no vendor code, binaries, artwork or text, is not
> affiliated with Anchorpoint Software GmbH, and "Anchorpoint" remains their
> trademark. The `anchorpoint` Python module name is kept only so community
> plug-ins written against the documented automation API keep importing.

## What works in v0.1 (all verified by tests)

- **Action host** — `*.yaml` manifest discovery/validation, 10 registration
  triggers, `;`-separated file filters, `${var}` substitution, `python` and
  `command` dispatch with per-action `Context` injection.
- **Python API** — `import anchorpoint` (`Context`, `UI`, `Dialog`,
  `Progress`, VC enums, local helpers) and `import apsync` (project markers,
  file ops, versioning, sidecar attributes, thumbnail via ffmpeg/ImageMagick).
- **CLI** — `assetmgr actions|validate|info|project-init|run|status`.
- **Local projects** — `*.approj` JSON markers, `.meta.json` sidecars, offline
  `git status`.
- Server-backed collaboration (locks, channel notifications, membership) is
  an explicit boundary: those calls raise `ServerRequiredError`.

## Quick start (Python host)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[test]"
pytest
assetmgr validate --root actions
assetmgr actions --root actions
assetmgr project-init ./demo-film --name demo-film
assetmgr run example::hello-world --path ./demo-film
```

## Web UI (native binary + Docker)

The native `assetmgrd` binary serves the browser UI and a JSON API, driving
the same Python host — no behaviour is reimplemented:

```bash
cd native && go test ./... && go build -o assetmgrd .
./assetmgrd -home ..            # http://127.0.0.1:8080
docker compose up --build       # same, in a container (verified 2026-10-25:
                                # image builds; /api/* and the UI respond)
```

API: `GET /api/info|/api/actions|/api/validate|/api/status`,
`POST /api/project-init|/api/run`. Every command also has a `--json` CLI
form the binary consumes; see `docs/API.md`.

## Layout

| Path | Contents |
|---|---|
| `assetmgr/` | host: manifests, dispatch, project store, CLI (`--json` for machines) |
| `native/` | `assetmgrd` Go binary: web UI + JSON API over the Python host |
| `native/web/` | browser UI (no dependencies, `fetch` against `/api/*`) |
| `Dockerfile` / `docker-compose.yml` | Go build stage + `trixie-slim` runtime (python3, git) |
| `anchorpoint/` | automation API bridge (UI/context side) |
| `apsync/` | local project/file engine (store side) |
| `actions/` | bundled example actions (`<name>/<name>.yaml` + `.py`) |
| `tests/` | pytest suite (run: `pytest`) |
| `docs/` | reverse-engineering ledger, schemas, roadmap |

## Docs

- `docs/REVERSE_ENGINEERING.md` — evidence ledger: what was observed, how,
  and what stays unknown.
- `docs/ARCHITECTURE.md` — system map and module responsibilities.
- `docs/ACTION_YAML.md` — manifest schema reference.
- `docs/API.md` — Python API reference and server boundary.
- `docs/GAPS.md` — open questions and how to close them.
