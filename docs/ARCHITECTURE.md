# Architecture

```
actions/<pack>/<action>.yaml + .py     # plug-ins (this repo: examples/)
        │ discover/validate/match
        ▼
assetmgr/actions.py ──► assetmgr/host.py ──► anchorpoint.Context
  manifests, triggers,      dispatch (runpy / subprocess)   injected per run
  ${var} substitution             │
        │                         ├── anchorpoint/  UI/Dialog/Progress,
        │                         │                 enums, local helpers
        │                         └── apsync/  project store, file ops,
        ▼                                          versions, attributes
assetmgr/store.py ── *.approj markers, .meta.json sidecars (plain folders + git)
assetmgr/cli.py   ── actions|validate|info|project-init|run|status
```

## Module responsibilities

- `assetmgr/actions.py` — manifest parsing/validation (`ManifestError` on any
  deviation), `discover()` directory walk, trigger + `;`-filter matching,
  `${var}` substitution. No I/O beyond reading manifests.
- `assetmgr/host.py` — `build_context()` (path → folder/filename/suffix,
  inputs merge) and `run_action()` (python via `runpy` with thread-local
  context; command via `subprocess` with env/cwd templates).
- `assetmgr/store.py` — project markers, `find_project_root` walk-up,
  JSON sidecars. The only on-disk formats v0.1 defines.
- `anchorpoint/` — automation bridge: `get_context()`, `Context`, `UI`,
  `Dialog/DialogEntry`, `Progress`, VC/display enums, local helpers.
  Server-backed names exist and raise `ServerRequiredError`.
- `apsync/` — local engine: markers, `shutil` file ops, `resolve_variables`,
  `_vNNN` versioning, sidecar attributes, external-tool thumbnails.
- `assetmgr/cli.py` — thin argparse over the above; `status` shells to `git`.

## Qt shell (roadmap, not v0.1)

The reference app is Qt6/QML (477 compiled-in modules, 16 `UI_*` libraries:
App/Assets/Attributes/Blocks/Buttons/ContextMenus/Dialogs/ElementViews/
General/Inputs/Popups/Sidebars/Styles/Texts/Utils/Values over Quick,
QmlModels, QuickControls2, Multimedia, Sql, WebEngine). The OSS shell will be
a PySide6/QML browser (`ElementView` grid/list/tree + attribute panels)
driving this same host — the headless `UI`/`Dialog` classes define the exact
seam the graphical front-end must implement.
