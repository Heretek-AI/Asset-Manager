"""Godot editor plugin tests (driven headless against real Godot 4.3)."""

import os
import shutil
import subprocess

import pytest

GODOT = shutil.which("godot")
PLUGIN_SRC = os.path.join(os.path.dirname(__file__), "..",
                          "godot-plugin", "addons", "asset_library")

PROBE_GD = """\
extends SceneTree

func _init() -> void:
\tvar ClientScript = load("res://addons/asset_library/asset_client.gd")
\tvar url: String = ClientScript.search_url(
\t\t"http://x/api/v1/assets", {"q": "hero", "kind": ""})
\tprint("URL:" + url)
\tvar items: Array = ClientScript.parse_assets(
\t\t'{"assets": [{"id": 1, "name": "hero.png"}]}')
\tprint("COUNT:" + str(items.size()))
\tprint("NAME:" + str((items[0] as Dictionary).get("name")))
\tprint("EMPTY:" + str(ClientScript.parse_assets("nope").size()))
\tquit()
"""


def make_plugin_project(tmp_path):
    root = tmp_path / "plugproj"
    (root / "addons" / "asset_library").mkdir(parents=True)
    (root / "project.godot").write_text(
        'config_version=5\n\n[application]\n\nconfig/name="PlugProbe"\n')
    for name in ("plugin.cfg", "plugin.gd", "asset_dock.tscn",
                 "asset_client.gd", "asset_dock.gd"):
        shutil.copy(os.path.join(PLUGIN_SRC, name),
                    root / "addons" / "asset_library" / name)
    return str(root)


@pytest.fixture
def godot_bin():
    if GODOT is None:
        pytest.skip("no godot binary on PATH")
    return GODOT


def test_plugin_loads_in_editor_headless(tmp_path, godot_bin):
    root = make_plugin_project(tmp_path)
    completed = subprocess.run(
        [godot_bin, "--headless", "--editor", "--quit-after", "10",
         "--path", root],
        capture_output=True, text=True, timeout=300)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "SCRIPT ERROR" not in completed.stderr
    assert "Parse Error" not in completed.stderr


def test_client_pure_functions_headless(tmp_path, godot_bin):
    root = make_plugin_project(tmp_path)
    probe = os.path.join(root, "probe_check.gd")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write(PROBE_GD)
    completed = subprocess.run(
        [godot_bin, "--headless", "--path", root, "--script", probe],
        capture_output=True, text=True, timeout=120)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert "URL:http://x/api/v1/assets?q=hero" in completed.stdout
    assert "COUNT:1" in completed.stdout
    assert "NAME:hero.png" in completed.stdout
    assert "EMPTY:0" in completed.stdout
