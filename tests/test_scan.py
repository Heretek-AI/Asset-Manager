"""Project scanner tests: asset discovery, sidecars, exclusions, CLI JSON."""

import json
import os

import pytest

from assetmgr.cli import main
from assetmgr.scan import scan_project

SAMPLE_PROJECT_GODOT = """\
config_version=5

[application]

config/name="Scan Game"
"""

TEXTURE_IMPORT = """\
[remap]

importer="texture"
type="CompressedTexture2D"
uid="uid://b1scanuid"
path="res://.godot/imported/hero.png-abc123.ctex"

[deps]

source_file="res://art/hero.png"
dest_files=["res://.godot/imported/hero.png-abc123.ctex"]

[params]

compress/mode=0
process/fix_alpha_border=true
"""


def make_project(tmp_path, name="game"):
    root = tmp_path / name
    (root / "art").mkdir(parents=True)
    (root / "project.godot").write_text(SAMPLE_PROJECT_GODOT)
    (root / "art" / "hero.png").write_bytes(b"png-bytes")
    (root / "main.tscn").write_text("[gd_scene]\n")
    return str(root)


def by_path(assets):
    return {a["path"]: a for a in assets}


def test_scan_finds_assets(tmp_path):
    root = make_project(tmp_path)
    assets = scan_project(root)
    assert json.dumps(assets)  # JSON-serializable
    found = by_path(assets)
    assert "res://art/hero.png" in found
    assert "res://main.tscn" in found
    hero = found["res://art/hero.png"]
    assert hero["name"] == "hero.png"
    assert hero["suffix"] == ".png"
    assert hero["size_bytes"] == len(b"png-bytes")
    assert isinstance(hero["mtime"], float)
    assert hero["has_import"] is False
    assert hero["import"] is None
    assert hero["uid"] is None
    assert hero["attributes"] == {}


def test_scan_detects_import_uid_meta(tmp_path):
    root = make_project(tmp_path)
    hero = os.path.join(root, "art", "hero.png")
    with open(f"{hero}.import", "w", encoding="utf-8") as handle:
        handle.write(TEXTURE_IMPORT)
    with open(f"{hero}.uid", "w", encoding="utf-8") as handle:
        handle.write("uid://b1scanuid\n")
    notes = os.path.join(root, "notes.txt")
    with open(notes, "w", encoding="utf-8") as handle:
        handle.write("hello")
    with open(f"{notes}.meta.json", "w", encoding="utf-8") as handle:
        json.dump({"tags": ["draft"]}, handle)

    found = by_path(scan_project(root))
    hero_entry = found["res://art/hero.png"]
    assert hero_entry["has_import"] is True
    assert hero_entry["import"]["importer"] == "texture"
    assert hero_entry["import"]["type"] == "CompressedTexture2D"
    assert hero_entry["import"]["uid"] == "uid://b1scanuid"
    assert hero_entry["import"]["params"]["compress/mode"] == 0
    assert hero_entry["uid"] == "uid://b1scanuid"
    assert found["res://notes.txt"]["attributes"] == {"tags": ["draft"]}


def test_scan_excludes_godot_cache_and_sidecars(tmp_path):
    root = make_project(tmp_path)
    cache = os.path.join(root, ".godot", "imported")
    os.makedirs(cache)
    with open(os.path.join(cache, "hero.png-abc123.ctex"), "w") as handle:
        handle.write("compiled")
    hero = os.path.join(root, "art", "hero.png")
    with open(f"{hero}.import", "w", encoding="utf-8") as handle:
        handle.write(TEXTURE_IMPORT)
    with open(f"{hero}.uid", "w", encoding="utf-8") as handle:
        handle.write("uid://b1scanuid\n")

    paths = [a["path"] for a in scan_project(root)]
    assert paths, "expected assets"
    assert not any(".godot" in p.removeprefix("res://").split("/") for p in paths)
    assert not any(p.endswith((".import", ".uid", ".meta.json")) for p in paths)
    assert "res://art/hero.png" in paths


def test_scan_requires_godot_project(tmp_path):
    with pytest.raises(FileNotFoundError):
        scan_project(str(tmp_path))
    with pytest.raises(FileNotFoundError):
        scan_project(os.path.join(str(tmp_path), "missing"))


def test_project_scan_cli_json(tmp_path, capsys):
    root = make_project(tmp_path)
    assert main(["project-scan", root, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["project_name"] == "Scan Game"
    assert {a["path"] for a in payload["assets"]} >= {
        "res://art/hero.png", "res://main.tscn"}


def test_project_scan_cli_json_not_a_project(tmp_path, capsys):
    assert main(["project-scan", str(tmp_path), "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["error"] == "not a godot project"
