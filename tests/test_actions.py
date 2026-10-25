"""Host behaviour tests: manifests, dispatch, store, local git status."""

import os
import subprocess

import pytest

import anchorpoint
import apsync
from assetmgr.actions import ActionManifest, ManifestError, discover, substitute_variables
from assetmgr.host import DispatchError, run_action
from assetmgr.store import find_project_root, init_project, is_project

ACTIONS_ROOT = os.path.join(os.path.dirname(__file__), "..", "actions")


def test_discover_finds_example_action():
    found, errors = discover(ACTIONS_ROOT)
    assert not errors
    ids = [m.manifest_id for m in found]
    assert "example::hello-world" in ids


def test_manifest_fields():
    found, _ = discover(ACTIONS_ROOT)
    action = next(m for m in found if m.manifest_id == "example::hello-world")
    assert action.name == "Hello World"
    assert action.action_type == "python"
    assert action.enabled_for_trigger("file") is True
    assert action.enabled_for_trigger("sidebar") is False
    assert action.matches_file("file", "shot.png") is True


def test_manifest_rejects_missing_id(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text('version: "1.0"\naction:\n  name: No Id\n  type: python\n')
    with pytest.raises(ManifestError):
        ActionManifest.from_file(str(bad))


def test_manifest_rejects_unknown_trigger(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text(
        'version: "1.0"\naction:\n  name: X\n  id: x::y\n  type: python\n'
        '  script: x.py\n  register:\n    everywhere:\n      enable: true\n'
    )
    with pytest.raises(ManifestError):
        ActionManifest.from_file(str(bad))


def test_filter_matching(tmp_path):
    manifest = ActionManifest.from_dict(
        "t.yaml",
        {"version": "1.0", "action": {
            "name": "T", "id": "t::t", "type": "python", "script": "t.py",
            "register": {"file": {"enable": True,
                                  "filter": "*.blend;*.png"}}}},
    )
    assert manifest.matches_file("file", "scene.BLEND") is True
    assert manifest.matches_file("file", "notes.txt") is False
    assert manifest.matches_file("folder", "anything") is False


def test_substitute_variables():
    out = substitute_variables("${yaml_dir}/ffmpeg.exe", {"yaml_dir": "/a"})
    assert out == "/a/ffmpeg.exe"
    assert substitute_variables("${missing}", {}) == "${missing}"


def test_run_python_action(tmp_path, capsys):
    found, _ = discover(ACTIONS_ROOT)
    action = next(m for m in found if m.manifest_id == "example::hello-world")
    target = tmp_path / "shot.png"
    target.write_text("x")
    assert run_action(action, path=str(target)) == 0
    assert "Hello World" in capsys.readouterr().out


def test_run_missing_script_raises(tmp_path):
    manifest = ActionManifest.from_dict(
        "t.yaml",
        {"version": "1.0", "action": {
            "name": "T", "id": "t::t", "type": "python", "script": "nope.py",
            "register": {"file": {"enable": True}}}},
    )
    with pytest.raises(DispatchError):
        run_action(manifest, path=str(tmp_path))


def test_context_only_inside_dispatch():
    with pytest.raises(RuntimeError):
        anchorpoint.get_context()


def test_project_roundtrip(tmp_path):
    marker = init_project(str(tmp_path / "film"), "film")
    assert marker.endswith(".approj")
    assert is_project(str(tmp_path / "film")) is True
    assert is_project(str(tmp_path / "film"), recursive=True) is True
    nested = tmp_path / "film" / "shots" / "s01"
    nested.mkdir(parents=True)
    assert find_project_root(str(nested)) == str(tmp_path / "film")
    assert is_project(str(tmp_path), recursive=True) is False


def test_next_version_naming(tmp_path):
    first = tmp_path / "plate_v001.exr"
    first.write_text("x")
    nxt = apsync.create_next_version(str(first))
    assert nxt.endswith("plate_v002.exr")
    assert os.path.exists(nxt)
    assert apsync.get_next_version_path("a/b/c.mov").endswith("c_v001.mov")


def test_sidecar_attributes(tmp_path):
    target = tmp_path / "asset.png"
    target.write_text("x")
    apsync.set_attribute(str(target), "rating", 4)
    assert apsync.get_attribute(str(target), "rating") == 4
    assert apsync.get_attribute(str(target), "missing", "dflt") == "dflt"


def test_server_boundary_raises():
    with pytest.raises(anchorpoint.ServerRequiredError):
        anchorpoint.lock("ws", "proj", ["a.png"])


def test_git_status_clean(tmp_path):
    if subprocess.run(["git", "--version"], capture_output=True).returncode != 0:
        pytest.skip("git binary absent")
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(repo), "config", "user.name", "t"], check=True)
    (repo / "f.txt").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    out = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v1", "--branch"],
        capture_output=True, text=True, check=True,
    )
    assert "##" in out.stdout  # branch header present, worktree clean
