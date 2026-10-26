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


# End-to-end: live library server -> Godot-side HTTP download into res://
# (same HTTPClient + FileAccess stack the dock uses) -> headless --import
# produces the editor cache. This is the project's core promise.
E2E_DOWNLOAD_GD = """\
extends SceneTree

func _fail(message: String) -> void:
\tprint("E2E_FAIL:" + message)
\tquit(1)

func _fetch(client: HTTPClient, host: String, port: int, path: String,
\t\ttoken: String) -> PackedByteArray:
\tvar err := client.connect_to_host(host, port)
\tif err != OK:
\t\t_fail("connect")
\t\treturn PackedByteArray()
\tvar deadline := Time.get_ticks_msec() + 15000
\twhile client.get_status() == HTTPClient.STATUS_CONNECTING \\
\t\t\tor client.get_status() == HTTPClient.STATUS_RESOLVING:
\t\tclient.poll()
\t\tOS.delay_msec(10)
\t\tif Time.get_ticks_msec() > deadline:
\t\t\t_fail("connect-timeout")
\t\t\treturn PackedByteArray()
\tif client.get_status() != HTTPClient.STATUS_CONNECTED:
\t\t_fail("not-connected")
\t\treturn PackedByteArray()
\terr = client.request(HTTPClient.METHOD_GET, path,
\t\tPackedStringArray(["Authorization: Bearer " + token]))
\tif err != OK:
\t\t_fail("request")
\t\treturn PackedByteArray()
\tdeadline = Time.get_ticks_msec() + 15000
\twhile client.get_status() == HTTPClient.STATUS_REQUESTING:
\t\tclient.poll()
\t\tOS.delay_msec(10)
\t\tif Time.get_ticks_msec() > deadline:
\t\t\t_fail("request-timeout")
\t\t\treturn PackedByteArray()
\tif client.get_response_code() != 200:
\t\t_fail("http-" + str(client.get_response_code()))
\t\treturn PackedByteArray()
\tvar body := PackedByteArray()
\twhile client.get_status() == HTTPClient.STATUS_BODY:
\t\tclient.poll()
\t\tvar chunk := client.read_response_body_chunk()
\t\tif chunk.size() > 0:
\t\t\tbody.append_array(chunk)
\t\tOS.delay_msec(10)
\treturn body

func _init() -> void:
\tvar args := OS.get_cmdline_user_args()
\tif args.size() < 4:
\t\t_fail("usage: host port token asset-id")
\t\treturn
\tvar host: String = args[0]
\tvar port: int = int(args[1])
\tvar token: String = args[2]
\tvar wanted_id := int(args[3])
\tvar client := HTTPClient.new()
\tvar listing := _fetch(client, host, port, "/api/v1/assets", token)
\tif listing.is_empty():
\t\treturn  # _fail already printed
\tvar ClientScript = load("res://addons/asset_library/asset_client.gd")
\tvar items: Array = ClientScript.parse_assets(listing.get_string_from_utf8())
\tprint("E2E_FOUND:" + str(items.size()))
\tvar target := {}
\tfor item: Variant in items:
\t\tif int((item as Dictionary).get("id", -1)) == wanted_id:
\t\t\ttarget = item
\tif target.is_empty():
\t\t_fail("asset-missing")
\t\treturn
\tvar name: String = str(target.get("name", "download.bin"))
\tvar blob := _fetch(client, host, port,
\t\t"/api/v1/assets/%d/blob" % wanted_id, token)
\tif blob.is_empty():
\t\t_fail("empty-blob")
\t\treturn
\tvar dest := "res://" + name
\tvar file := FileAccess.open(dest, FileAccess.WRITE)
\tif file == null:
\t\t_fail("write")
\t\treturn
\tfile.store_buffer(blob)
\tfile.close()
\tprint("E2E_SAVED:" + dest + ":" + str(blob.size()))
\tquit()
"""


def test_full_loop_server_to_imported(tmp_path, godot_bin):
    import base64
    import sys
    from urllib.parse import urlparse

    from test_library_server import TOKEN, start_server

    _, base = start_server(tmp_path / "srv")
    parts = urlparse(base)
    png = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    source = tmp_path / "hero.png"
    source.write_bytes(png)

    root = make_plugin_project(tmp_path)
    probe = os.path.join(root, "e2e_download.gd")
    with open(probe, "w", encoding="utf-8") as handle:
        handle.write(E2E_DOWNLOAD_GD)

    # Publish through the real CLI (same path the action uses).
    pushed = subprocess.run(
        [sys.executable, "-m", "assetmgr.cli",
         "library-push", str(source), "--server", base, "--token", TOKEN,
         "--kind", "texture", "--importer", "texture", "--json"],
        capture_output=True, text=True, timeout=120)
    assert pushed.returncode == 0, pushed.stderr[-1000:]
    import json as _json
    asset_id = _json.loads(pushed.stdout)["id"]

    # Godot side: search + download into res:// via Godot's own HTTP stack.
    dl = subprocess.run(
        [godot_bin, "--headless", "--path", root, "--script", probe, "--",
         parts.hostname, str(parts.port), TOKEN, str(asset_id)],
        capture_output=True, text=True, timeout=120)
    assert dl.returncode == 0, dl.stderr[-2000:] + dl.stdout[-1000:]
    assert "E2E_FOUND:1" in dl.stdout, dl.stdout
    assert "E2E_SAVED:res://hero.png" in dl.stdout, dl.stdout
    assert "E2E_FAIL" not in dl.stdout

    # Headless import must now produce the editor cache for the file.
    imported = subprocess.run(
        [godot_bin, "--headless", "--path", root, "--import"],
        capture_output=True, text=True, timeout=300)
    assert imported.returncode == 0, imported.stderr[-2000:]
    got = list((tmp_path / "plugproj").rglob("*.ctex"))
    assert got, "no imported output produced"
    assert os.path.isfile(os.path.join(root, "hero.png.import"))
