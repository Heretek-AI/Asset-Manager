"""Library metadata DB tests."""

from library.db import add_asset, get_asset, open_db


def test_add_get_roundtrip(tmp_path):
    db = open_db(tmp_path / "library.db")
    asset_id = add_asset(db, name="hero.png", blob_sha256="ab" * 32,
                         size_bytes=70, kind="texture",
                         godot_importer="texture",
                         params={"compress/mode": 0}, tags=["hero"])
    row = get_asset(db, asset_id)
    assert row["name"] == "hero.png"
    assert row["blob_sha256"] == "ab" * 32
    assert row["godot_importer"] == "texture"
    assert row["params"] == {"compress/mode": 0}
    assert row["tags"] == ["hero"]


def test_list_filter(tmp_path):
    from library.db import list_assets
    db = open_db(tmp_path / "library.db")
    add_asset(db, name="hero.png", blob_sha256="aa" * 32, size_bytes=1,
              tags=["game"])
    add_asset(db, name="click.wav", blob_sha256="bb" * 32, size_bytes=2,
              kind="audio", tags=["ui"])
    assert len(list_assets(db)) == 2
    assert [a["name"] for a in list_assets(db, tag="game")] == ["hero.png"]
    assert [a["name"] for a in list_assets(db, kind="audio")] == ["click.wav"]
    assert list_assets(db, q="her") and not list_assets(db, q="zzz")
