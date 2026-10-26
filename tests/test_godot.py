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
    is_godot_project,
    list_uid_files,
    parse_godot_config,
    read_uid,
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
            "godot::open-project"} <= ids


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
