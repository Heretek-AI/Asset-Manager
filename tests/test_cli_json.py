"""JSON contract tests: machine output the native binary consumes."""

import json
import os
import subprocess

import pytest

from assetmgr.cli import main

ACTIONS_ROOT = os.path.join(os.path.dirname(__file__), "..", "actions")
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


def _run_json(capsys, *argv):
    code = main([*argv, "--json"])
    out = capsys.readouterr().out
    return code, json.loads(out)


def test_info_json(capsys):
    code, payload = _run_json(capsys, "info")
    assert code == 0
    assert payload["name"] == "asset-manager"
    assert payload["version"]


def test_actions_json(capsys):
    code, payload = _run_json(capsys, "actions", "--root", ACTIONS_ROOT)
    assert code == 0
    ids = [a["id"] for a in payload["actions"]]
    assert "example::hello-world" in ids
    assert payload["errors"] == []


def test_validate_json_ok(capsys):
    code, payload = _run_json(capsys, "validate", "--root", ACTIONS_ROOT)
    assert code == 0
    assert payload == {"valid": True, "errors": []}


def test_validate_json_bad(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text('version: "1.0"\naction:\n  name: No Id\n')
    code, payload = _run_json(capsys, "validate", "--root", str(tmp_path))
    assert code == 1
    assert payload["valid"] is False
    assert len(payload["errors"]) == 1


def test_project_init_json(tmp_path, capsys):
    code, payload = _run_json(
        capsys, "project-init", str(tmp_path / "film"), "--name", "film")
    assert code == 0
    assert payload["marker"].endswith("film.approj")
    assert os.path.exists(payload["marker"])


def test_run_json_unknown(capsys):
    code, payload = _run_json(
        capsys, "run", "no::such-action", "--root", ACTIONS_ROOT)
    assert code == 2
    assert payload["error"] == "unknown action"


def test_run_json_ok(tmp_path, capsys):
    target = tmp_path / "shot.png"
    target.write_text("x")
    code, payload = _run_json(
        capsys, "run", "example::hello-world",
        "--root", ACTIONS_ROOT, "--path", str(target))
    assert code == 0
    assert payload["action_id"] == "example::hello-world"
    assert payload["exit_code"] == 0
    assert "Hello World" in payload["output"]


def test_status_json_repo(capsys):
    if subprocess.run(["git", "--version"],
                       capture_output=True).returncode != 0:
        pytest.skip("git binary absent")
    code, payload = _run_json(capsys, "status", "--path", REPO_ROOT)
    assert code == 0
    assert payload["branch"]
    assert isinstance(payload["entries"], list)


def test_status_json_not_a_checkout(tmp_path, capsys):
    code, payload = _run_json(capsys, "status", "--path", str(tmp_path))
    assert code == 1
    assert payload["error"] == "not a git checkout"


ONE_PIXEL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


def _write_png(path):
    import base64
    with open(path, "wb") as handle:
        handle.write(base64.b64decode(ONE_PIXEL_PNG_B64))
    return str(path)


def _needs_engine():
    import shutil
    if shutil.which("ffmpeg") is None and shutil.which("magick") is None:
        pytest.skip("no thumbnail engine (ffmpeg/magick) on PATH")


def test_thumbnail_json_ok(tmp_path, capsys):
    _needs_engine()
    source = _write_png(tmp_path / "hero.png")
    code, payload = _run_json(capsys, "thumbnail", source)
    assert code == 0
    assert payload["source"] == os.path.abspath(source)
    assert os.path.exists(payload["destination"])
    with open(payload["destination"], "rb") as handle:
        assert handle.read(8) == b"\x89PNG\r\n\x1a\n"


def test_thumbnail_json_missing_file(tmp_path, capsys):
    code, payload = _run_json(
        capsys, "thumbnail", str(tmp_path / "nope.png"))
    assert code == 2
    assert payload["error"] == "no such file"


def test_thumbnail_default_name(tmp_path, capsys):
    _needs_engine()
    source = _write_png(tmp_path / "hero.png")
    assert main(["thumbnail", source]) == 0
    assert os.path.exists(tmp_path / "hero_thumb.png")
    capsys.readouterr()


def test_thumbnail_json_no_engine(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("PATH", str(tmp_path))  # dir with no engines on it
    source = _write_png(tmp_path / "hero.png")
    code, payload = _run_json(capsys, "thumbnail", source)
    assert code == 3
    assert "ffmpeg" in payload["error"]


def test_library_init_json(tmp_path, capsys):
    code, payload = _run_json(capsys, "library-init",
                              str(tmp_path / "lib"))
    assert code == 0
    assert os.path.exists(payload["db"])


def test_library_push_pull_json(tmp_path, capsys):
    from test_library_server import TOKEN, start_server
    _, base = start_server(tmp_path / "srv")
    source = _write_png(tmp_path / "hero.png")
    code, payload = _run_json(
        capsys, "library-push", source, "--server", base,
        "--token", TOKEN, "--kind", "texture", "--tags", "hero,demo")
    assert code == 0
    assert payload["id"] == 1
    dest = str(tmp_path / "fetched.png")
    code, payload = _run_json(
        capsys, "library-pull", "1", "--out", dest,
        "--server", base, "--token", TOKEN)
    assert code == 0
    with open(source, "rb") as a, open(dest, "rb") as b:
        assert a.read() == b.read()


def test_library_push_needs_endpoint(tmp_path, capsys):
    source = _write_png(tmp_path / "hero.png")
    code, payload = _run_json(capsys, "library-push", source)
    assert code == 2
    assert "server" in payload["error"]


def test_library_token_lifecycle_against_server(tmp_path, capsys):
    from test_library_server import start_server
    db = str(tmp_path / "srv" / "lib.db")
    _, base = start_server(tmp_path / "srv")
    code, created = _run_json(capsys, "library-token-create", "carol",
                              "--db", db)
    assert code == 0
    token = created["token"]
    code, listed = _run_json(capsys, "library-token-list", "--db", db)
    assert code == 0
    # "default" comes from the test server's bootstrap token
    assert {t["name"] for t in listed["tokens"]} == {"default", "carol"}
    # carol's token works against the live server sharing the same DB
    assert _run_json(capsys, "library-push", _write_png(tmp_path / "a.png"),
                     "--server", base, "--token", token)[0] == 0
    code, _ = _run_json(capsys, "library-token-revoke", "carol",
                        "--db", db)
    assert code == 0
    code, payload = _run_json(capsys, "library-push",
                              _write_png(tmp_path / "b.png"),
                              "--server", base, "--token", token)
    assert code == 1
    assert "401" in payload["error"]
