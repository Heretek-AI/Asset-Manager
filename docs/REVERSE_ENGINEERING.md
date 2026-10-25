# Reverse-engineering ledger — observed facts only

Target: `AnchorpointSetup.exe` v1.38.0, Squirrel installer, downloaded
2026-10-25 from `https://s3.eu-central-1.amazonaws.com/releases.anchorpoint.app/RELEASE/AnchorpointSetup.exe`.

Every conclusion below separates **observation** (tool output), **inference**
(reasoned from observations) and **unknown** (not established). Nothing here
claims runtime behaviour beyond what static evidence plus file layout show.

## Artifact identity

| Item | Value |
|---|---|
| `AnchorpointSetup.exe` SHA-256 | `bdcc3a0f…a2d193758f370b3` (381 MB, PE32 i386 GUI, Squirrel self-extractor) |
| `Anchorpoint-1.38.0-full.nupkg` | ZIP, 7,749 members, nuspec id `Anchorpoint`, version `1.38.0`, author `Anchorpoint Software GmbH` |
| `Anchorpoint.exe` SHA-256 | `c60ba7a3…a9e2e2b0aca1950402f973b7b` (33.8 MB, PE32+ x86-64 GUI) |
| Signer | `Anchorpoint Software GmbH`, Certum Code Signing 2021 CA (REA `inspect-pe-certificates` Evidence) |
| Internal codename | `twain` (`ap-desktop` repo path baked into `ap.exe` PDB string) |

## REA Evidence (offline, no engine required)

| Evidence file | Method | Finding |
|---|---|---|
| `evidence/anchorpoint-exe-inspect-pe-imports.json` | `rea inspect-pe-imports` | Qt6 stack: Core(734) Gui Qml Quick Widgets Network Sql OpenGL WebEngineQuick; plus `Core.dll`(266) `sync.dll` `Plugin.dll` sentry `libmpv-2`; Log4Qt |
| `evidence/anchorpoint-exe-inspect-pe-certificates.json` | `rea inspect-pe-certificates` | Certum chain, signer as above; no signature verification performed |
| `evidence/anchorpoint-exe-inspect-pe-resources.json` | `rea inspect-pe-resources` | Icon/version resource tree |
| `evidence/anchorpoint-exe-inspect-native-exports.json` | `rea inspect-native-exports` | 1,320 exports incl. `apsync::BaseObject`, Log4Qt appenders, `qml_register_types_UI_*` (16 QML modules) |
| `evidence/ap-exe-inspect-*.json` | same on `ap.exe` | CLI11 + `twain::CommandLineIPC` (`connectIPC`, `connectPlugin`, `commit/pull/push/revert/sync`, `responseCommand`) |
| `evidence/setup-certs.json` | `rea inspect-pe-certificates` on Setup.exe | **failed, recorded**: 381 MB exceeds 64 MiB REA input budget (`max_file_bytes`); carved + nupkg used instead |
| `evidence/anchorpoint-strings.txt` | `strings -a` (5.3 MB) | 477 compiled-in QML module names, `qsTr` UI text, endpoint hosts, CLI topics |

Supporting files: `carved/` (Squirrel payload: `Anchorpoint.exe`, `Update.exe`,
`ap.exe`, `ThumbnailGen.exe`, `SubstanceRender.exe`, …), `full/lib_extract/`
(full nupkg tree).

## Key observations (→ design decisions in this repo)

1. **Qt6/QML app, Python-embedded.** `plugins/python/` ships CPython 3.13 +
   `anchorpoint/__init__.pyi` (3,990 lines: the entire public automation
   surface) + native `apsync…pyd`. → `anchorpoint/` + `apsync/` packages here.
2. **Action packs.** `scripts/ap-actions/*/` = `<id>.yaml` + `.py` + `.svg`;
   101 manifests use `version/action{name,id,version,author,category,type,
   description,icon,script|command,inputs,settings,dependencies,platforms,
   actions,register,environment,toast}` with 10 register triggers and
   `;`-separated filters. → `assetmgr/actions.py` enforces exactly this.
3. **Project markers.** DCC-side plug-in walks up to `*.approj`.
   → `assetmgr/store.py` uses `<name>.approj` JSON markers.
4. **Thumbnail pipeline.** `ThumbnailGen.exe` (stdin-JSON jobs, 21 format
   plug-ins) + `scripts/thumbnail.py` (OLE) + `scripts/schdoc.py` (Altium).
   → `apsync.generate_thumbnail` shells out to ffmpeg/ImageMagick.
5. **Git engine.** Bundled Git-for-Windows + scalar; ~26 `git::*` actions;
   free-tier gate on non-GitHub remotes; file locks independent of LFS.
   → offline `git status` in CLI; locks are an explicit server boundary.
6. **Server split.** Hosts seen: `track.` (telemetry), `cloud.` + `grpc--cloud.`
   (sync API), S3 (updates). Status/commit/branch/stash/revert/merge UI work
   offline; locks, notifications, membership, trailers need the server.

## Explicit limitations / unknowns

- No Ghidra/Hopper decompilation was needed for v0.1 and none is claimed;
  Ghidra 12.2 is installed for future targeted work.
- `apsync.*` native method bodies: class names only (pybind11), signatures
  unrecovered — reimplemented from stub + samples, marked where guessed.
- Wire schemas (`connect-req`, `action-dispatch` JSON) need daemon traffic
  capture — see `docs/GAPS.md`.
- QML/UI text in the binary is copyrighted expression: described, never copied.
