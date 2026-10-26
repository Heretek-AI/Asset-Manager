# Python API reference

Two modules, mirroring the observed automation surface. Everything listed
here is implemented; server-backed names exist with identical signatures and
raise `ServerRequiredError`.

## `anchorpoint` — UI/context bridge

```python
import anchorpoint as ap

ctx = ap.get_context()          # Context for this action run (raises outside one)
ap.UI().show_success("Done", "renamed 12 files")
with ap.Progress("Rendering", cancelable=True) as job:
    job.report_progress(0.5)
dlg = ap.Dialog("Rename")
dlg.add_input("shot", var="name").add_checkbox(False, "Keep extension", var="keep")
values = dlg.show()             # headless: {var: default}; GUI shell blocks
```

- **Enums** — `ActionButtonType`, `BrowseType`, `ChangeSource`,
  `TimelineChannelModuleState`, `VCConflictHandling`, `VCFileStatus`.
- **Data** — `Context` (path/folder/filename/suffix, selection lists,
  project/workspace ids, `inputs`, `yaml_dir`, …), `VCChange`.
- **Local helpers** — `temp_dir`, `get_application_dir`, `get_config`,
  `check_application`, `get_alternative_name`, `is_network_drive`,
  `log_error/log_success`, `get/set/has/reset_cache`, `join_project_path`,
  `show_in_explorer`, `copy_files_to_clipboard`, `create_commit_deeplink`.
- **Server boundary (raise)** — `lock/unlock/get_locks/update_locks/`,
  `evaluate_locks`, `locks_disabled/readonly`, `schedule_*_notification`,
  `get/update_channel_info`, `get/update/remove_unsynced_files`.

## `apsync` — local project/file engine

```python
import apsync

apsync.is_project("./demo-film", recursive=True)
apsync.create_project_file("./demo-film", project_id="p1")
apsync.copy_file("a.exr", "b.exr")
apsync.create_next_version("plate_v001.exr")   # -> plate_v002.exr
apsync.set_attribute("asset.png", "rating", 4)
apsync.resolve_variables("${yaml_dir}/tool", {"yaml_dir": "/x"})
apsync.generate_thumbnail("clip.mov", "thumb.png")  # needs ffmpeg/ImageMagick
```

## HTTP API (`assetmgrd`)

Same operations over HTTP; unknown action → 404, dispatch failure → 500,
not-a-checkout → 404, bad body → 400. The browser UI in `native/web/` uses
exactly this surface.

`POST /api/thumbnail` (`{"source", "destination"?}`) renders via the host
`thumbnail` command and returns `image/png` bytes directly (404 unknown
asset, 503 no engine on the server); the browser's Preview column uses it.

```bash
curl localhost:8080/api/info
curl "localhost:8080/api/actions?scope=file"
curl "localhost:8080/api/status?path=/work/demo-film"
curl -X POST localhost:8080/api/project-init \
  -d '{"directory":"/work/demo-film","name":"demo-film"}'
curl -X POST localhost:8080/api/run \
  -d '{"action_id":"example::hello-world","path":"/work/demo-film"}'
curl -X POST localhost:8080/api/thumbnail \
  -d '{"source":"/work/demo-film/hero.png"}' --output thumb.png
```

## CLI

`assetmgr actions [--root] [--scope file]` · `validate` · `info` ·
`project-init DIR --name N [--force]` · `run <action-id> [--path P]` ·
`status [--path P]` (offline `git status`) · `project-scan <root>` (Godot
asset inventory) · `thumbnail SRC [--out PNG]` (exit 3 = no engine) ·
`library-init DIR` · `library-push FILE --server URL --token T [--name N]
[--kind K] [--importer I] [--params JSON] [--tags a,b]` ·
`library-pull ID --out PATH --server URL --token T` ·
`library-token-create NAME [--db DB]` (prints once) ·
`library-token-list` · `library-token-revoke NAME`
(server/token also via `ASSETMGR_LIBRARY_URL` / `ASSETMGR_LIBRARY_TOKEN`).
