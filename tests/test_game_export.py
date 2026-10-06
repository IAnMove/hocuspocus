"""Synthetic pack: approved files in, unapproved assets listed as missing."""
import json
import shutil
import threading
import tracemalloc
import zipfile
from pathlib import PurePosixPath

import numpy as np
import pytest
import soundfile as sf
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.game_library import create_game_library_router
from services.game_audio import write_wav_loop
from services.game_export import export_game
from services.game_sheet import pack_rows

MANIFEST_SCHEMA = {
    "required": ["schema", "version", "game", "assets", "generatedAt"],
    "schema": "hocuspocus.game-pack",
    "version": 1,
    "game_required": ["id", "title", "revision", "style"],
}


def _png(path, color):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (4, 4), color).save(path)


def _attempt(files, metrics=None, provenance=None):
    return {
        "id": "a1",
        "status": "ok",
        "files": files,
        "metrics": metrics or {},
        "provenance": provenance or {"steps": []},
    }


def _asset(asset_id, kind, files, **extra):
    return {
        "id": asset_id,
        "kind": kind,
        "name": extra.get("name", asset_id),
        "status": extra.get("status", "approved"),
        "tags": extra.get("tags", []),
        "spec": extra.get("spec", {}),
        "approvedAttemptId": "a1" if extra.get("status", "approved") == "approved" else None,
        "attempts": [_attempt(files, extra.get("metrics"), extra.get("provenance"))] if files is not None else [],
    }


def _game(tmp_path):
    _png(tmp_path / "heroe.png", (180, 40, 40, 255))
    _png(tmp_path / "idle.png", (20, 180, 40, 255))
    _png(tmp_path / "walk-0.png", (20, 40, 180, 255))
    _png(tmp_path / "walk-1.png", (20, 80, 180, 255))
    _png(tmp_path / "gema.png", (40, 200, 80, 255))
    _png(tmp_path / "moneda.png", (220, 180, 20, 255))
    _png(tmp_path / "icon-a.png", (200, 200, 200, 255))
    _png(tmp_path / "icon-b.png", (80, 80, 80, 255))
    _png(tmp_path / "boton.png", (20, 20, 20, 255))
    _png(tmp_path / "hierba.png", (20, 120, 20, 255))
    _png(tmp_path / "suelo.png", (120, 80, 40, 255))
    _png(tmp_path / "bg" / "layer-0.png", (80, 140, 200, 255))
    _png(tmp_path / "explosion.png", (255, 80, 0, 255))
    (tmp_path / "boton-nine.json").write_text(json.dumps({"left": 2, "right": 2, "top": 2, "bottom": 2}), encoding="utf-8")
    (tmp_path / "suelo.json").write_text(json.dumps({"names": ["tl", "t", "tr", "l", "c", "r", "bl", "b", "br"]}), encoding="utf-8")
    (tmp_path / "bg" / "parallax.json").write_text(json.dumps({"layers": [{"file": "layer-0.png", "factor": 0.3}]}), encoding="utf-8")
    (tmp_path / "explosion.json").write_text(json.dumps({"meta": {"blend": "add"}}), encoding="utf-8")
    write_wav_loop(tmp_path / "nivel1.wav", np.zeros(100, dtype=np.float32), 8000, 0, 99)
    (tmp_path / "nivel1.ogg").write_bytes(b"OggS-nivel1")
    (tmp_path / "salto-1.wav").write_bytes(b"RIFF-salto")
    (tmp_path / "cofre.glb").write_bytes(b"glTF-cofre")
    (tmp_path / "heroe3d.glb").write_bytes(b"glTF-heroe")
    (tmp_path / "rig.glb").write_bytes(b"glTF-rig")
    return {
        "id": "bosque",
        "title": "Bosque encantado",
        "revision": 7,
        "view": "side",
        "style": {"preset": "pixel-16", "pixel": {"enabled": True, "tile": 1}},
        "assets": [
            _asset("heroe", "character", {"main": "heroe.png", "rawKey": "heroe.png"}, provenance={"steps": [{"tool": "generation.image", "model": "qwen_image_21"}]}),
            _asset("heroe-walk", "animation", {"frames": ["walk-0.png", "walk-1.png"]}, spec={"character": "heroe", "action": "walk", "fps": 12, "loop": True}),
            _asset("heroe-idle", "animation", {"frames": ["idle.png"]}, spec={"character": "heroe", "action": "idle", "fps": 8, "loop": True}),
            _asset("gema", "sprite", {"main": "gema.png"}),
            _asset("moneda", "item", {"main": "moneda.png"}),
            _asset("corazon", "icon", {"main": "icon-a.png"}, tags=["hud"]),
            _asset("estrella", "icon", {"main": "icon-b.png"}, tags=["hud"]),
            _asset("boton", "ui", {"main": "boton.png", "nine": "boton-nine.json"}),
            _asset("hierba", "tile", {"main": "hierba.png"}),
            _asset("tierra-tileset", "tileset", {"main": "suelo.png", "tiles": "suelo.json"}),
            _asset("bosque", "background", {"parallax": "bg/parallax.json"}),
            _asset("explosion", "vfx", {"main": "explosion.png", "atlas": "explosion.json"}),
            _asset("salto", "sfx", {"1": "salto-1.wav"}),
            _asset("nivel1", "music", {"wav": "nivel1.wav", "ogg": "nivel1.ogg"}, metrics={"loopStart": 0, "loopEnd": 99, "bpm": 120, "lufs": -16}),
            _asset("cofre", "model3d", {"model": "cofre.glb"}),
            _asset("heroe3d", "character3d", {"model": "heroe3d.glb", "rig": "rig.glb"}),
            _asset("llave", "item", None, status="pending"),
        ],
        "exports": [],
    }


def _matches_manifest(payload: dict) -> None:
    for key in MANIFEST_SCHEMA["required"]:
        assert key in payload
    assert payload["schema"] == MANIFEST_SCHEMA["schema"]
    assert payload["version"] == MANIFEST_SCHEMA["version"]
    for key in MANIFEST_SCHEMA["game_required"]:
        assert key in payload["game"]
    assert isinstance(payload["assets"], list) and payload["assets"]
    assert isinstance(payload["generatedAt"], str) and payload["generatedAt"]


def test_zip_matches_the_pack_layout_and_keeps_smpl(tmp_path):
    game = _game(tmp_path)
    result = export_game(tmp_path, game, workspace="lab", now="2026-10-07T00:00:00Z")
    assert result["file"] == "game-exports/bosque-r7.zip"
    assert result["url"] == "/api/v1/file/game-exports/bosque-r7.zip?workspace=lab"
    assert result["missing"] == [{"id": "llave", "kind": "item", "status": "pending"}]
    assert result["counts"]["animation"] == 2
    assert result["counts"]["total"] == 16
    assert game["exports"][0]["file"] == result["file"]
    assert game["exports"][0]["revision"] == 7

    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        names = set(archive.namelist())
        required = {
            "bosque-r7/manifest.json",
            "bosque-r7/README.txt",
            "bosque-r7/provenance.json",
            "bosque-r7/characters/heroe/heroe.png",
            "bosque-r7/characters/heroe/heroe.json",
            "bosque-r7/characters/heroe/heroe-base.png",
            "bosque-r7/sprites/gema.png",
            "bosque-r7/items/moneda.png",
            "bosque-r7/icons/hud.png",
            "bosque-r7/icons/hud.json",
            "bosque-r7/ui/boton.png",
            "bosque-r7/ui/boton.json",
            "bosque-r7/tiles/hierba.png",
            "bosque-r7/tiles/tierra-tileset.png",
            "bosque-r7/tiles/tierra-tileset.json",
            "bosque-r7/backgrounds/bosque/layer-0.png",
            "bosque-r7/backgrounds/bosque/parallax.json",
            "bosque-r7/vfx/explosion.png",
            "bosque-r7/vfx/explosion.json",
            "bosque-r7/audio/sfx/salto-1.wav",
            "bosque-r7/audio/music/nivel1.wav",
            "bosque-r7/audio/music/nivel1.ogg",
            "bosque-r7/audio/loops.json",
            "bosque-r7/models/cofre.glb",
            "bosque-r7/models/heroe3d.glb",
        }
        assert required <= names
        assert not any("llave" in name for name in names)
        wav = archive.read("bosque-r7/audio/music/nivel1.wav")
        assert wav == (tmp_path / "nivel1.wav").read_bytes()
        assert b"smpl" in wav
        assert archive.read("bosque-r7/audio/music/nivel1.ogg") == b"OggS-nivel1"
        assert archive.read("bosque-r7/models/heroe3d.glb") == b"glTF-rig"
        readme = archive.read("bosque-r7/README.txt").decode("utf-8")
        assert "Declaración de uso de IA" in readme
        assert "AI use statement" in readme
        assert "qwen_image_21" in readme
        manifest = json.loads(archive.read("bosque-r7/manifest.json"))
        _matches_manifest(manifest)
        assert manifest["game"]["id"] == "bosque"
        assert manifest["game"]["revision"] == 7
        atlas = json.loads(archive.read("bosque-r7/characters/heroe/heroe.json"))
        tags = atlas["meta"]["frameTags"]
        assert [tag["name"] for tag in tags] == ["idle", "walk"]
        assert tags[0] == {"name": "idle", "from": 0, "to": 0, "direction": "forward"}
        assert tags[1] == {"name": "walk", "from": 1, "to": 2, "direction": "forward"}
        assert atlas["meta"]["scale"] == "1"
        assert atlas["meta"]["image"] == "heroe.png"
        with Image.open(archive.open("bosque-r7/characters/heroe/heroe.png")) as sheet:
            cell_h = atlas["frames"]["idle_0"]["frame"]["h"]
            assert sheet.height == cell_h * 2
        loops = json.loads(archive.read("bosque-r7/audio/loops.json"))
        assert loops == [{
            "file": "audio/music/nivel1.wav",
            "loopStart": 0,
            "loopEnd": 99,
            "bpm": 120,
            "lufs": -16,
        }]
        icons = json.loads(archive.read("bosque-r7/icons/hud.json"))
        assert [tag["name"] for tag in icons["meta"]["frameTags"]] == ["corazon", "estrella"]
        tiles = json.loads(archive.read("bosque-r7/tiles/tierra-tileset.json"))
        assert tiles["names"] == ["tl", "t", "tr", "l", "c", "r", "bl", "b", "br"]
        vfx = json.loads(archive.read("bosque-r7/vfx/explosion.json"))
        assert vfx["meta"]["blend"] == "add"

    again = export_game(tmp_path, game, workspace="lab", now="2026-10-07T00:01:00Z")
    assert again["file"] == "game-exports/bosque-r7-2.zip"
    assert len(game["exports"]) == 2


def test_export_route_records_the_zip(tmp_path):
    _png(tmp_path / "hero.png", (1, 2, 3, 255))
    app = FastAPI()
    app.include_router(create_game_library_router(workspace_dir=lambda _name: str(tmp_path), lock=threading.RLock()))
    client = TestClient(app)
    created = client.post("/api/v1/games", json={"workspace": "lab", "game": {
        "id": "bosque",
        "title": "Bosque",
        "assets": [{
            "id": "heroe",
            "kind": "character",
            "status": "approved",
            "approvedAttemptId": "a1",
            "attempts": [{"id": "a1", "status": "ok", "files": {"main": "hero.png"}}],
        }],
    }})
    assert created.status_code == 201
    exported = client.post("/api/v1/games/bosque/export", json={"workspace": "lab"})
    assert exported.status_code == 200
    body = exported.json()
    assert body["file"] == "game-exports/bosque-r1.zip"
    assert body["missing"] == []
    assert (tmp_path / body["file"]).is_file()
    stored = client.get("/api/v1/games/bosque", params={"workspace": "lab"})
    assert stored.status_code == 200
    assert stored.json()["exports"][0]["file"] == body["file"]
    missing = client.post("/api/v1/games/nope/export", json={"workspace": "lab"})
    assert missing.status_code == 404


NOW = "2026-10-07T00:00:00Z"


def _export(root, assets, **kwargs):
    game = {"id": "g", "title": "G", "revision": 1, "view": "side", "assets": assets, "exports": []}
    return game, export_game(root, game, now=NOW, **kwargs)


def _router_client(tmp_path):
    app = FastAPI()
    app.include_router(create_game_library_router(workspace_dir=lambda _name: str(tmp_path), lock=threading.RLock()))
    return TestClient(app)


def test_approved_files_that_cannot_be_read_are_reported(tmp_path):
    _png(tmp_path / "ok.png", (1, 2, 3, 255))
    _png(tmp_path / "f0.png", (1, 2, 3, 255))
    (tmp_path / "broken.png").write_bytes(b"not a png")
    rejected = _asset("tachado", "sprite", {"main": "ok.png"})
    rejected["attempts"][0]["decision"] = "rejected"
    orphan = _asset("huerfano", "sprite", {"main": "ok.png"})
    orphan["approvedAttemptId"] = None
    stale = _asset("viejo", "sprite", {"main": "ok.png"})
    stale["status"] = "stale"
    _game, result = _export(tmp_path, [
        _asset("ok", "sprite", {"main": "ok.png"}),
        _asset("gone", "sprite", {"main": "nope.png"}),
        _asset("walk", "animation", {"frames": ["f0.png", "broken.png", "f9.png"]}, spec={"character": "heroe", "action": "walk"}),
        rejected,
        orphan,
        stale,
    ])
    assert result["counts"] == {"sprite": 1, "animation": 1, "total": 2}
    rows = {row["id"]: row for row in result["missing"]}
    assert rows["gone"] == {"id": "gone", "kind": "sprite", "status": "approved", "problem": "not_packed", "files": ["nope.png"]}
    assert rows["walk"]["problem"] == "files_missing"
    assert rows["walk"]["files"] == ["broken.png", "f9.png"]
    assert rows["tachado"]["problem"] == "no_approved_attempt"
    assert rows["huerfano"]["problem"] == "no_approved_attempt"
    assert rows["viejo"] == {"id": "viejo", "kind": "sprite", "status": "stale"}
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        sprites = [name for name in archive.namelist() if name.startswith("g-r1/sprites/")]
        manifest = json.loads(archive.read("g-r1/manifest.json"))
    assert sprites == ["g-r1/sprites/ok.png"]
    assert [row["id"] for row in manifest["assets"]] == ["ok", "walk"]


def test_library_file_names_cannot_escape_the_pack(tmp_path):
    (tmp_path / "x.wav").write_bytes(b"RIFF-x")
    _png(tmp_path / "art" / "gema.png", (1, 2, 3, 255))
    outside = tmp_path.parent / f"{tmp_path.name}-outside.png"
    _png(outside, (1, 2, 3, 255))
    _game, result = _export(tmp_path, [
        _asset("salto", "sfx", {"../../../../../../escaped": "x.wav"}),
        _asset("gema", "sprite", {"main": "art\\gema.png"}),
        _asset("fuera", "sprite", {"main": f"../{outside.name}"}),
        _asset("absoluto", "sprite", {"main": str(outside)}),
    ])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        names = archive.namelist()
    assert all(name.startswith("g-r1/") and ".." not in name.split("/") and "\\" not in name for name in names)
    assert "g-r1/audio/sfx/salto-escaped.wav" in names
    assert "g-r1/sprites/gema.png" in names
    assert {row["id"] for row in result["missing"]} == {"fuera", "absoluto"}


def test_assets_never_overwrite_each_other_in_the_zip(tmp_path):
    _png(tmp_path / "a.png", (255, 0, 0, 255))
    _png(tmp_path / "b.png", (0, 255, 0, 255))
    _png(tmp_path / "h.png", (0, 0, 255, 255))
    (tmp_path / "v1.wav").write_bytes(b"RIFF-golpe-variant-1")
    (tmp_path / "g1.wav").write_bytes(b"RIFF-golpe-1")
    _game, result = _export(tmp_path, [
        _asset("hud", "icon", {"main": "h.png"}),
        _asset("corazon", "icon", {"main": "a.png"}, tags=["hud"]),
        _asset("estrella", "icon", {"main": "b.png"}, tags=["hud"]),
        _asset("golpe", "sfx", {"1": "v1.wav"}),
        _asset("golpe-1", "sfx", {"wav": "g1.wav"}),
    ])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        names = archive.namelist()
        files = {row["id"]: row["files"] for row in json.loads(archive.read("g-r1/manifest.json"))["assets"]}
        assert archive.read(f"g-r1/{files['golpe'][0]}") == b"RIFF-golpe-variant-1"
        assert archive.read(f"g-r1/{files['golpe-1'][0]}") == b"RIFF-golpe-1"
        with Image.open(archive.open(f"g-r1/{files['hud'][0]}")) as icon:
            assert icon.size == (4, 4) and icon.getpixel((0, 0)) == (0, 0, 255, 255)
        sheet = json.loads(archive.read(f"g-r1/{files['corazon'][1]}"))
    assert len(names) == len(set(names))
    assert files["golpe"] != files["golpe-1"]
    assert files["hud"][0] not in files["corazon"]
    assert sheet["meta"]["image"] == PurePosixPath(files["corazon"][0]).name


def test_repeated_animation_names_do_not_crash_the_sheet(tmp_path):
    _png(tmp_path / "f.png", (1, 2, 3, 255))
    _game, result = _export(tmp_path, [
        _asset("a", "animation", {"frames": ["f.png"]}, spec={"character": "h", "action": "q"}),
        _asset("b", "animation", {"frames": ["f.png"]}, spec={"character": "h", "action": "q-c"}),
        _asset("c", "animation", {"frames": ["f.png"]}, spec={"character": "h", "action": "q"}),
    ])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        tags = [tag["name"] for tag in json.loads(archive.read("g-r1/characters/h/h.json"))["meta"]["frameTags"]]
    assert len(tags) == len(set(tags)) == 3


def test_vfx_atlas_names_its_sheet_and_the_readme_explains_both_pivots(tmp_path):
    """Candidates live in their own folders; the approved one is packed, with its centre pivot."""
    for index, value in ((1, 40), (2, 200)):
        sheet, atlas = pack_rows([{"name": "boom", "frames": [np.full((6, 6, 4), value, np.uint8)], "fps": 12, "loop": True}], (8, 8), anchor="center")
        folder = tmp_path / "game" / "g" / "boom" / "r1" / f"a{index}"
        folder.mkdir(parents=True)
        sheet.save(folder / "sheet.png")
        atlas["meta"].update(image="sheet.png", blend="add")
        (folder / "sheet.json").write_text(json.dumps(atlas), encoding="utf-8")
    boom = _asset("boom", "vfx", None)
    boom["attempts"] = [
        {"id": f"r1-a{index}", "status": "ok", "files": {"main": f"game/g/boom/r1/a{index}/sheet.png", "atlas": f"game/g/boom/r1/a{index}/sheet.json"}}
        for index in (1, 2)
    ]
    boom["approvedAttemptId"] = "r1-a2"
    _game, result = _export(tmp_path, [boom])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        exported = json.loads(archive.read("g-r1/vfx/boom.json"))
        readme = archive.read("g-r1/README.txt").decode("utf-8")
        with Image.open(archive.open("g-r1/vfx/boom.png")) as packed:
            assert packed.getpixel((4, 4)) == (200, 200, 200, 200)
    assert exported["meta"]["image"] == "boom.png"
    assert exported["meta"]["pivot"] == {"x": 4, "y": 4}
    assert exported["meta"]["blend"] == "add"
    assert "center of the cell for the effects in vfx/" in readme
    assert "The pivot is the bottom center of the cell (meta.pivot)" not in readme


def test_symlinked_workspace_keeps_parallax_layers(tmp_path):
    real = tmp_path / "real"
    link = tmp_path / "link"
    real.mkdir()
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are not available")
    _png(real / "bg" / "Layer 0.png", (80, 140, 200, 255))
    layers = [{"file": "Layer 0.png", "factor": 0.3}, {"file": "gone.png", "factor": 0.6}]
    (real / "bg" / "parallax.json").write_text(json.dumps({"layers": layers, "loopX": True}), encoding="utf-8")
    game = {"id": "g", "revision": 1, "assets": [_asset("bosque", "background", {"parallax": "bg/parallax.json"})]}
    result = export_game(link, game, now=NOW)
    with zipfile.ZipFile(real / result["file"]) as archive:
        names = archive.namelist()
        parallax = json.loads(archive.read("g-r1/backgrounds/bosque/parallax.json"))
    assert "g-r1/backgrounds/bosque/layer-0.png" in names
    assert parallax == {"layers": [{"file": "layer-0.png", "factor": 0.3}], "loopX": True}
    assert result["missing"] == [{"id": "bosque", "kind": "background", "status": "approved", "problem": "files_missing", "files": ["gone.png"]}]


def test_character_base_is_the_approved_sprite_and_tile_variants_ship(tmp_path):
    Image.new("RGBA", (16, 16), (1, 2, 3, 255)).save(tmp_path / "main.png")
    Image.new("RGBA", (300, 500), (1, 2, 3, 255)).save(tmp_path / "raw-key.png")
    _png(tmp_path / "hierba.png", (20, 120, 20, 255))
    _png(tmp_path / "hierba-2.png", (20, 140, 20, 255))
    _game, result = _export(tmp_path, [
        _asset("heroe", "character", {"main": "main.png", "rawKey": "raw-key.png"}),
        _asset("hierba", "tile", {"main": "hierba.png", "variant-2": "hierba-2.png"}),
    ])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        names = archive.namelist()
        with Image.open(archive.open("g-r1/characters/heroe/heroe-base.png")) as base:
            assert base.size == (16, 16)
    assert {"g-r1/tiles/hierba.png", "g-r1/tiles/hierba-variant-2.png"} <= set(names)


def test_every_sfx_take_gets_an_ogg(tmp_path):
    for index in (1, 2):
        sf.write(tmp_path / f"salto-{index}.wav", np.zeros(800, dtype=np.float32), 8000, subtype="PCM_16")
    _game, result = _export(tmp_path, [_asset("salto", "sfx", {"1": "salto-1.wav", "2": "salto-2.wav"})])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        names = set(archive.namelist())
    assert {"g-r1/audio/sfx/salto-1.ogg", "g-r1/audio/sfx/salto-2.ogg"} <= names


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")
def test_music_ogg_made_at_export_keeps_the_loop(tmp_path):
    tone = (np.sin(np.arange(8000) / 10) * 0.3).astype(np.float32)
    write_wav_loop(tmp_path / "nivel.wav", tone, 8000, 0, 7999)
    _game, result = _export(tmp_path, [_asset("nivel", "music", {"wav": "nivel.wav"}, metrics={"loopStart": 0, "loopEnd": 7999, "bpm": 120})])
    with zipfile.ZipFile(tmp_path / result["file"]) as archive:
        ogg = archive.read("g-r1/audio/music/nivel.ogg")
        loops = json.loads(archive.read("g-r1/audio/loops.json"))
    assert b"LOOPSTART=0" in ogg and b"LOOPLENGTH=8000" in ogg
    assert loops == [{"file": "audio/music/nivel.wav", "loopStart": 0, "loopEnd": 7999, "bpm": 120, "lufs": None}]


def test_failed_export_leaves_no_partial_zip(tmp_path, monkeypatch):
    _png(tmp_path / "a.png", (1, 2, 3, 255))
    _png(tmp_path / "b.png", (1, 2, 3, 255))
    assets = [_asset("a", "sprite", {"main": "a.png"}), _asset("b", "sprite", {"main": "b.png"})]
    original = zipfile.ZipFile._writecheck
    calls = []

    def disk_full(self, zinfo):
        calls.append(zinfo.filename)
        if len(calls) == 2:
            raise OSError(28, "No space left on device")
        return original(self, zinfo)

    monkeypatch.setattr(zipfile.ZipFile, "_writecheck", disk_full)
    game = {"id": "g", "revision": 1, "assets": assets, "exports": []}
    with pytest.raises(OSError):
        export_game(tmp_path, game, now=NOW)
    monkeypatch.undo()
    assert list((tmp_path / "game-exports").iterdir()) == []
    assert game["exports"] == []
    assert export_game(tmp_path, game, now=NOW)["file"] == "game-exports/g-r1.zip"


def test_large_files_stream_into_the_zip(tmp_path):
    (tmp_path / "big.glb").write_bytes(bytes(16 * 1024 * 1024))
    tracemalloc.start()
    try:
        _game, result = _export(tmp_path, [_asset("cofre", "model3d", {"model": "big.glb"})])
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert result["counts"] == {"model3d": 1, "total": 1}
    assert peak < 6 * 1024 * 1024


def test_the_same_input_gives_the_same_zip(tmp_path):
    _png(tmp_path / "a.png", (1, 2, 3, 255))
    assets = [_asset("a", "sprite", {"main": "a.png"}), _asset("b", "icon", {"main": "a.png"})]
    game, first = _export(tmp_path, assets)
    second = export_game(tmp_path, game, now=NOW)
    assert second["file"] == "game-exports/g-r1-2.zip"
    assert (tmp_path / first["file"]).read_bytes() == (tmp_path / second["file"]).read_bytes()


def test_export_route_refuses_an_empty_pack(tmp_path):
    client = _router_client(tmp_path)
    created = client.post("/api/v1/games", json={"workspace": "lab", "game": {
        "id": "vacio",
        "title": "Vacio",
        "assets": [
            {"id": "llave", "kind": "item", "status": "pending"},
            {"id": "gema", "kind": "sprite", "status": "approved", "approvedAttemptId": "a1",
             "attempts": [{"id": "a1", "status": "ok", "files": {"main": "nope.png"}}]},
        ],
    }})
    assert created.status_code == 201
    exported = client.post("/api/v1/games/vacio/export", json={"workspace": "lab"})
    assert exported.status_code == 409
    assert exported.json()["detail"]["code"] == "nothing_to_export"
    assert not (tmp_path / "game-exports").exists() or list((tmp_path / "game-exports").iterdir()) == []
    stored = client.get("/api/v1/games/vacio", params={"workspace": "lab"})
    assert stored.json()["exports"] == []
