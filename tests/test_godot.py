"""Godot adapter tests: config parsing, discovery, import, actions."""

import os
import shutil
import subprocess

import pytest

import anchorpoint
from assetmgr.actions import discover
from assetmgr.godot import (
    find_godot_project_root,
    get_project_name,
    import_files_into_project,
    import_summary,
    is_godot_project,
    known_importer_params,
    list_import_files,
    list_uid_files,
    parse_godot_config,
    read_import,
    read_uid,
    set_import_params,
    validate_import_params,
)
from assetmgr.host import run_action

GODOT_ACTIONS = os.path.join(os.path.dirname(__file__), "..", "actions", "godot")

SAMPLE_PROJECT_GODOT = """\
; Engine configuration file.
; It's best edited using the editor UI and not directly.

config_version=5

[application]

config/name="Probe Game"
config/description="A probe."
run/main_scene="res://main.tscn"

[rendering]

renderer/rendering_method="gl_compatibility"
textures/vram_compression/import_etc2_astc=true
anti_aliasing/quality/msaa_3d=2
scale=1.5
"""


def make_project(tmp_path, name="probe"):
    root = tmp_path / name
    root.mkdir()
    (root / "project.godot").write_text(SAMPLE_PROJECT_GODOT)
    return str(root)


def test_parse_project_config():
    config = parse_godot_config(SAMPLE_PROJECT_GODOT)
    assert config["application"]["config/name"] == "Probe Game"
    assert config["application"]["run/main_scene"] == "res://main.tscn"
    assert config["rendering"]["textures/vram_compression/import_etc2_astc"] is True
    assert config["rendering"]["anti_aliasing/quality/msaa_3d"] == 2
    assert config["rendering"]["scale"] == 1.5
    assert "config_version" not in config  # section-less keys are ignored


def test_parse_escapes_and_comments():
    config = parse_godot_config('[s]\na="x\\"y\\nq"\n; comment\nb=7\n')
    assert config["s"]["a"] == 'x"y\nq'
    assert config["s"]["b"] == 7


def test_discovery_walk_up(tmp_path):
    root = make_project(tmp_path)
    nested = os.path.join(root, "art", "tiles")
    os.makedirs(nested)
    assert find_godot_project_root(nested) == root
    assert is_godot_project(nested) is True
    assert is_godot_project(str(tmp_path)) is False
    assert get_project_name(root) == "Probe Game"


def test_uid_roundtrip(tmp_path):
    root = make_project(tmp_path)
    uid_path = os.path.join(root, "icon.svg.uid")
    with open(uid_path, "w", encoding="utf-8") as handle:
        handle.write("uid://abc123\n")
    assert read_uid(uid_path) == "uid://abc123"
    assert list_uid_files(root) == [uid_path]


def test_import_copies_external_file(tmp_path):
    root = make_project(tmp_path)
    incoming = tmp_path / "incoming"
    incoming.mkdir()
    source = incoming / "hero.png"
    source.write_text("png-bytes")
    (dest,) = import_files_into_project([str(source)], root)
    assert dest == os.path.join(root, "assets", "hero.png")
    assert os.path.exists(dest)


def test_import_is_idempotent_for_project_files(tmp_path):
    root = make_project(tmp_path)
    inside = os.path.join(root, "assets", "hero.png")
    os.makedirs(os.path.dirname(inside), exist_ok=True)
    with open(inside, "w") as handle:
        handle.write("x")
    assert import_files_into_project([inside], root) == [inside]


def test_import_missing_file_raises(tmp_path):
    root = make_project(tmp_path)
    with pytest.raises(FileNotFoundError):
        import_files_into_project([os.path.join(str(tmp_path), "nope.png")], root)


def test_godot_action_manifests_discovered():
    found, errors = discover(GODOT_ACTIONS)
    assert not errors
    ids = {m.manifest_id for m in found}
    assert {"godot::import-asset", "godot::reimport",
            "godot::open-project", "godot::set-preset",
            "godot::publish-to-library"} <= ids


def test_import_action_dispatch(tmp_path, capsys):
    root = make_project(tmp_path)
    source = tmp_path / "hero.png"
    source.write_text("png-bytes")
    found, _ = discover(GODOT_ACTIONS)
    action = next(m for m in found if m.manifest_id == "godot::import-asset")
    assert run_action(action, path=str(source),
                      extra_inputs={"target_folder": "assets"},
                      context_overrides={"project_path": root}) == 0
    assert os.path.exists(os.path.join(root, "assets", "hero.png"))


def test_reimport_requires_godot_binary(tmp_path):
    if shutil.which("godot"):
        pytest.skip("godot binary present; covered by live reimport test")
    found, _ = discover(GODOT_ACTIONS)
    action = next(m for m in found if m.manifest_id == "godot::reimport")
    root = make_project(tmp_path)
    code = run_action(action, path=root, extra_inputs={"godot": "godot-missing-xyz"})
    assert code == 1  # action reports failure instead of raising


def test_live_headless_reimport(tmp_path):
    godot = shutil.which("godot")
    if not godot:
        pytest.skip("no godot binary on PATH")
    root = make_project(tmp_path)
    asset = os.path.join(root, "assets", "hero.png")
    os.makedirs(os.path.dirname(asset), exist_ok=True)
    # minimal valid 1x1 PNG
    import base64
    with open(asset, "wb") as handle:
        handle.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    completed = subprocess.run(
        [godot, "--headless", "--path", root, "--import"],
        capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert os.path.isdir(os.path.join(root, ".godot"))
    assert os.path.isdir(os.path.join(root, ".godot", "imported"))
    assert anchorpoint  # bridge importable alongside adapter use


REAL_TEXTURE_IMPORT = """\
[remap]

importer="texture"
type="CompressedTexture2D"
uid="uid://xsp571jaov0p"
path="res://.godot/imported/hero.png-87aa9197b739ca3ad1031ac3d1b82853.ctex"
metadata={
"vram_texture": false
}

[deps]

source_file="res://hero.png"
dest_files=["res://.godot/imported/hero.png-87aa9197b739ca3ad1031ac3d1b82853.ctex"]

[params]

compress/mode=0
compress/lossy_quality=0.7
process/fix_alpha_border=true
roughness/src_normal=""
"""


def test_parse_real_import_file():
    parsed = parse_godot_config(REAL_TEXTURE_IMPORT)
    assert parsed["remap"]["importer"] == "texture"
    assert parsed["remap"]["uid"] == "uid://xsp571jaov0p"
    assert parsed["deps"]["source_file"] == "res://hero.png"
    assert parsed["deps"]["dest_files"] == [
        "res://.godot/imported/hero.png-87aa9197b739ca3ad1031ac3d1b82853.ctex"]
    assert parsed["params"]["compress/mode"] == 0
    assert parsed["params"]["compress/lossy_quality"] == 0.7
    assert parsed["params"]["process/fix_alpha_border"] is True
    assert parsed["params"]["roughness/src_normal"] == ""
    # multiline dict stays raw text, keyed under its owner
    assert "vram_texture" in str(parsed["remap"]["metadata"])
    summary = import_summary(parsed)
    assert summary["importer"] == "texture"
    assert summary["type"] == "CompressedTexture2D"
    assert summary["uid"] == "uid://xsp571jaov0p"
    assert summary["params"]["compress/mode"] == 0


def test_array_with_quoted_commas():
    parsed = parse_godot_config('[s]\nfiles=["a,b", "c"]\nn=2\n')
    assert parsed["s"]["files"] == ["a,b", "c"]
    assert parsed["s"]["n"] == 2


def test_font_import_value_shapes():
    parsed = parse_godot_config(
        "[params]\nRendering=null\nantialiasing=1\noversampling=0.0\n"
        "fallbacks=[]\npreload=[]\nlanguage_support={}\n"
        'scale_mesh=Vector3(1, 1, 1)\n')
    params = parsed["params"]
    assert params["Rendering"] == "null"  # Godot null kept verbatim
    assert params["antialiasing"] == 1
    assert params["oversampling"] == 0.0
    assert params["fallbacks"] == []
    assert params["language_support"] == "{}"
    assert params["scale_mesh"] == "Vector3(1, 1, 1)"


def test_quoted_key_lines_are_continuations():
    parsed = parse_godot_config('[s]\nmetadata={\n"a=b": true\n}\nnext=1\n')
    assert "a=b" in str(parsed["s"]["metadata"])
    assert parsed["s"]["next"] == 1


def test_list_and_read_import_files(tmp_path):
    root = make_project(tmp_path)
    imp = os.path.join(root, "hero.png.import")
    with open(imp, "w", encoding="utf-8") as handle:
        handle.write(REAL_TEXTURE_IMPORT)
    assert list_import_files(root) == [imp]
    assert read_import(imp)["remap"]["importer"] == "texture"


def test_known_importer_params_are_harvested_not_guessed():
    texture = known_importer_params("texture")
    assert texture is not None
    assert len(texture) == 17  # real 4.3 output
    wav = known_importer_params("wav")
    assert wav is not None
    assert len(wav) == 10  # real 4.3 output
    for importer, count in (("mp3", 5), ("oggvorbisstr", 5),
                            ("font_data_dynamic", 20),
                            ("wavefront_obj", 5), ("scene", 21)):
        params = known_importer_params(importer)
        assert params is not None
        assert len(params) == count, (importer, params)
    assert known_importer_params("not_a_real_importer") is None


def test_validate_import_params():
    assert validate_import_params(
        "texture", {"compress/mode": 0, "mipmaps/generate": True}) == []
    assert validate_import_params(
        "texture", {"compress/mode": 0, "loop_mode": 1}) == ["loop_mode"]
    assert validate_import_params("wav", {"edit/loop_mode": 1}) == []
    assert validate_import_params("mp3", {"loop": True}) == []
    assert validate_import_params("mp3", {"compress/mode": 0}) == ["compress/mode"]
    assert validate_import_params("font_data_dynamic", {"hinting": 2}) == []
    assert validate_import_params(
        "wavefront_obj", {"scale_mesh": "Vector3(1, 1, 1)"}) == []
    assert validate_import_params("scene", {"animation/fps": 30}) == []
    assert validate_import_params("scene", {"loop": True}) == ["loop"]
    # unknown importer: absence of data is not evidence of a bad key
    assert validate_import_params(
        "not_a_real_importer", {"anything/at_all": 1}) == []


def test_set_preset_warns_but_applies_unknown_keys(tmp_path, capsys):
    root = make_project(tmp_path)
    imp = os.path.join(root, "hero.png.import")
    with open(imp, "w", encoding="utf-8") as handle:
        handle.write(REAL_TEXTURE_IMPORT)
    found, _ = discover(GODOT_ACTIONS)
    action = next(m for m in found if m.manifest_id == "godot::set-preset")
    params = "compress/lossy_quality=0.5\nloop_mode=1"
    assert run_action(action, path=os.path.join(root, "hero.png"),
                      extra_inputs={"params": params},
                      context_overrides={"project_path": root}) == 0
    out = capsys.readouterr().out
    assert "WARNING" in out and "loop_mode" in out
    # applied anyway: known key updated, unknown key appended
    reread = read_import(imp)
    assert reread["params"]["compress/lossy_quality"] == 0.5
    assert reread["params"]["loop_mode"] == 1


PRESET_IMPORT = """\
; texture preset, keep me
[remap]

importer="texture"
type="CompressedTexture2D"
metadata={
"vram_texture": false
}

[deps]

source_file="res://hero.png"

[params]

compress/mode=0
compress/lossy_quality=0.7
process/fix_alpha_border=true
roughness/src_normal=""
"""


def test_set_import_params_roundtrip_fidelity(tmp_path):
    imp = tmp_path / "hero.png.import"
    imp.write_text(PRESET_IMPORT, encoding="utf-8")
    written = set_import_params(str(imp), {"compress/lossy_quality": 0.25})
    assert written == ["compress/lossy_quality"]
    before, after = PRESET_IMPORT.splitlines(), imp.read_text().splitlines()
    assert len(before) == len(after)
    diffs = [(i, old, new) for i, (old, new)
             in enumerate(zip(before, after)) if old != new]
    assert diffs == [(16, "compress/lossy_quality=0.7",
                      "compress/lossy_quality=0.25")]
    params = read_import(str(imp))["params"]
    assert params["compress/lossy_quality"] == 0.25
    # value formatting matches Godot one-line form
    set_import_params(str(imp), {"compress/mode": 2,
                                 "process/fix_alpha_border": False,
                                 "roughness/src_normal": "a,b"})
    params = read_import(str(imp))["params"]
    assert params["compress/mode"] == 2
    assert params["process/fix_alpha_border"] is False
    assert params["roughness/src_normal"] == "a,b"
    text = imp.read_text()
    assert "roughness/src_normal=\"a,b\"" in text
    assert "; texture preset, keep me" in text
    assert '"vram_texture": false' in text  # multiline remap dict untouched


def test_set_import_params_appends_missing_key(tmp_path):
    imp = tmp_path / "hero.png.import"
    imp.write_text(PRESET_IMPORT + "\n[other]\n\nx=1\n", encoding="utf-8")
    set_import_params(str(imp), {"process/hdr_as_srgb": True})
    # the key lands at the end of [params], ahead of its trailing blank line
    assert imp.read_text() == (
        PRESET_IMPORT.rstrip("\n") + "\nprocess/hdr_as_srgb=true\n"
        + "\n[other]\n\nx=1\n")
    assert read_import(str(imp))["params"]["process/hdr_as_srgb"] is True


def test_live_set_preset_survives_reimport(tmp_path):
    godot = shutil.which("godot")
    if not godot:
        pytest.skip("no godot binary on PATH")
    assert godot is not None
    root = make_project(tmp_path)
    asset = os.path.join(root, "hero.png")
    with open(asset, "wb") as handle:
        import base64
        handle.write(base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="))
    first = subprocess.run(
        [godot, "--headless", "--path", root, "--import"],
        capture_output=True, text=True, timeout=300)
    assert first.returncode == 0, first.stderr[-2000:]
    import_path = asset + ".import"
    assert os.path.isfile(import_path)
    assert "params" in read_import(import_path)
    set_import_params(import_path, {"compress/lossy_quality": 0.25})
    assert read_import(import_path)["params"]["compress/lossy_quality"] == 0.25
    second = subprocess.run(
        [godot, "--headless", "--path", root, "--import"],
        capture_output=True, text=True, timeout=300)
    assert second.returncode == 0, second.stderr[-2000:]
    assert read_import(import_path)["params"]["compress/lossy_quality"] == 0.25


def test_describe_for_library_with_import_sidecar(tmp_path):
    from assetmgr.godot import describe_for_library
    root = make_project(tmp_path)
    asset = os.path.join(root, "hero.png")
    with open(asset, "w") as handle:
        handle.write("x")
    with open(asset + ".import", "w", encoding="utf-8") as handle:
        handle.write(REAL_TEXTURE_IMPORT)
    described = describe_for_library(asset)
    assert described["importer"] == "texture"
    assert described["kind"] == "texture"
    assert described["params"]["compress/mode"] == 0


def test_describe_for_library_suffix_fallback(tmp_path):
    from assetmgr.godot import describe_for_library
    root = make_project(tmp_path)
    asset = os.path.join(root, "click.wav")
    with open(asset, "w") as handle:
        handle.write("x")
    described = describe_for_library(asset)
    assert described["kind"] == "audio"
    assert described["importer"] is None
    assert described["params"] == {}


def test_publish_action_dispatch(tmp_path, capsys, monkeypatch):
    from test_library_server import TOKEN, start_server
    _, base = start_server(tmp_path / "srv")
    root = make_project(tmp_path)
    asset = os.path.join(root, "hero.png")
    with open(asset, "w") as handle:
        handle.write("png-bytes")
    with open(asset + ".import", "w", encoding="utf-8") as handle:
        handle.write(REAL_TEXTURE_IMPORT)
    found, _ = discover(GODOT_ACTIONS)
    action = next(m for m in found
                  if m.manifest_id == "godot::publish-to-library")
    monkeypatch.delenv("ASSETMGR_LIBRARY_URL", raising=False)
    monkeypatch.delenv("ASSETMGR_LIBRARY_TOKEN", raising=False)
    assert run_action(action, path=asset,
                      extra_inputs={"server": base, "token": TOKEN},
                      context_overrides={"project_path": root}) == 0
    out = capsys.readouterr().out
    assert "Published" in out and "asset 1" in out
    from library.client import pull
    dest = os.path.join(str(tmp_path), "fetched.png")
    pull(base, TOKEN, 1, dest)
    with open(dest, "rb") as handle:
        assert handle.read() == b"png-bytes"
