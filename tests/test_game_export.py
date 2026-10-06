"""Synthetic pack: approved files in, unapproved assets listed as missing."""
import json
import threading
import zipfile

import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.game_library import create_game_library_router
from services.game_audio import write_wav_loop
from services.game_export import export_game

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
