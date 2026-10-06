"""3D generators with a synthetic 12-triangle cube. No GPU."""
from __future__ import annotations

import json
import struct
from pathlib import Path

from services.game_generators.base import GenContext
from services.game_generators.three_d import (
    Character3dGenerator,
    Model3dGenerator,
    budget_warning,
    clips_for,
)

GLB_MAGIC = 0x46546C67
JSON_CHUNK = 0x4E4F534A
BIN_CHUNK = 0x004E4942


def _f32(*values: float) -> bytes:
    return b"".join(struct.pack("<f", value) for value in values)


def _u16(*values: int) -> bytes:
    return b"".join(struct.pack("<H", value) for value in values)


def _pack(document: dict, blob: bytes) -> bytes:
    raw = json.dumps(document, separators=(",", ":")).encode("utf-8")
    raw += b" " * ((4 - (len(raw) % 4)) % 4)
    chunks = struct.pack("<II", len(raw), JSON_CHUNK) + raw
    padded = blob + (b"\x00" * ((4 - (len(blob) % 4)) % 4))
    chunks += struct.pack("<II", len(padded), BIN_CHUNK) + padded
    return struct.pack("<III", GLB_MAGIC, 2, 12 + len(chunks)) + chunks


def _cube(path: Path, *, clip: str | None = None) -> None:
    positions = _f32(
        -1, -1, -1, 1, -1, -1, 1, 1, -1, -1, 1, -1,
        -1, -1, 1, 1, -1, 1, 1, 1, 1, -1, 1, 1,
    )
    indices = _u16(
        0, 1, 2, 0, 2, 3, 4, 6, 5, 4, 7, 6,
        0, 4, 5, 0, 5, 1, 2, 6, 7, 2, 7, 3,
        0, 3, 7, 0, 7, 4, 1, 5, 6, 1, 6, 2,
    )
    blob = positions + indices
    document = {
        "asset": {"version": "2.0"},
        "meshes": [{"name": "Cube", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": 4}]}],
        "buffers": [{"byteLength": len(blob)}],
        "bufferViews": [
            {"buffer": 0, "byteOffset": 0, "byteLength": len(positions)},
            {"buffer": 0, "byteOffset": len(positions), "byteLength": len(indices)},
        ],
        "accessors": [
            {"bufferView": 0, "componentType": 5126, "count": 8, "type": "VEC3"},
            {"bufferView": 1, "componentType": 5123, "count": 36, "type": "SCALAR"},
        ],
    }
    if clip:
        document["animations"] = [{"name": clip, "channels": [], "samplers": []}]
    path.write_bytes(_pack(document, blob))


class _Tools:
    def __init__(self, image: Path, glb: Path, rigged: Path | None = None):
        self.image = image
        self.glb = glb
        self.rigged = rigged or glb
        self.calls = []
        self.loopbacks = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool == "generation.image":
            return {"receipt": {"result": {"job_id": "job-image"}}}
        if tool == "jobs.wait":
            job = args["input"]["job_id"]
            path = self.image if job == "orbit-job" else self.image
            if job == "orbit-job":
                path = self.image
            return {"status": "completed", "output_files": [str(path)]}
        if tool == "model3d.generate":
            return {"result": {"job_id": "job-mesh"}}
        if tool == "model3d.status":
            return {"status": "completed", "filename": str(self.glb)}
        if tool == "model3d.rig":
            return {"result": {"job_id": "job-rig"}}
        if tool == "model3d.rig.status":
            return {"status": "completed", "filename": str(self.rigged)}
        raise AssertionError(tool)

    def loopback(self, tool, args):
        self.loopbacks.append((tool, args))
        return {"receipt": {"result": {"job_id": "orbit-job"}}}


def _ctx(tmp_path: Path, game: dict, asset: dict, fake: _Tools) -> GenContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=fake.loopback, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )


def _style(limit: int = 3000) -> dict:
    return {"preset": "pixel-16", "traits": "flat toon", "model3d": {"maxTriangles": limit, "look": "toon"}}


def test_clip_map_and_budget_thresholds():
    assert clips_for("player") == ("idle", "walk", "run", "jump", "punch", "victory")
    assert clips_for("enemy") == ("idle", "walk", "attack", "hit")
    assert clips_for("boss") == clips_for("enemy")
    assert clips_for("npc") == ("idle", "talk", "wave")
    assert budget_warning(11, 10) == []
    assert budget_warning(12, 10) == ["over_budget"]
    assert budget_warning(None, 10) == []


def test_model_calls_image_then_mesh_and_warns_over_budget(tmp_path):
    picture = tmp_path / "concept-src.png"
    picture.write_bytes(b"png")
    glb = tmp_path / "cube.glb"
    _cube(glb)
    game = {"id": "bosque", "style": _style(10), "assets": []}
    asset = {"id": "cofre", "kind": "model3d", "description": "a chest", "spec": {"maxTriangles": 10, "multiview": False}}
    fake = _Tools(picture, glb)
    result = Model3dGenerator().run(_ctx(tmp_path, game, asset, fake))
    tools = [name for name, _args in fake.calls]
    assert tools == ["generation.image", "jobs.wait", "model3d.generate", "model3d.status"]
    params = fake.calls[0][1]["input"]["params"]
    assert params["resolution"] == "1024x1024"
    assert "plain light grey background" in params["prompt"]
    assert "no shadow" in params["prompt"]
    assert "flat solid" not in params["prompt"]
    mesh = next(args["input"] for name, args in fake.calls if name == "model3d.generate")
    assert mesh["preset"] == "balanced"
    assert mesh["reduce_face"] is True
    assert mesh["target_face_num"] == 10
    assert "images" not in mesh
    assert result.metrics["triangles"] == 12
    assert "over_budget" in result.warnings
    assert (tmp_path / "ws" / result.files["model"]).is_file()


def test_multiview_sends_four_views_in_order(tmp_path, monkeypatch):
    picture = tmp_path / "concept-src.png"
    picture.write_bytes(b"png")
    glb = tmp_path / "cube.glb"
    _cube(glb)

    def grab(_video, _start, _end, folder):
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        frame = path / "0001.png"
        frame.write_bytes(b"png")
        return [frame]

    monkeypatch.setattr("services.game_frames.extract_frames", grab)
    game = {"id": "bosque", "style": _style(), "assets": []}
    asset = {"id": "cofre", "kind": "model3d", "description": "a chest", "spec": {"maxTriangles": 3000, "multiview": True}}
    fake = _Tools(picture, glb)
    Model3dGenerator().run(_ctx(tmp_path, game, asset, fake))
    tools = [name for name, _args in fake.calls]
    assert tools[:4] == ["generation.image", "jobs.wait", "jobs.wait", "model3d.generate"]
    assert fake.loopbacks[0][0] == "generate"
    mesh = next(args["input"] for name, args in fake.calls if name == "model3d.generate")
    assert mesh["preset"] == "multiview"
    assert list(mesh["images"]) == ["front", "left", "back", "right"]


def test_character_uses_approved_art_and_reports_missing_clips(tmp_path):
    picture = tmp_path / "ws" / "hero.png"
    picture.parent.mkdir()
    picture.write_bytes(b"png")
    mesh = tmp_path / "cube.glb"
    rigged = tmp_path / "rig.glb"
    _cube(mesh)
    _cube(rigged, clip="idle")
    game = {
        "id": "bosque",
        "style": _style(),
        "assets": [{
            "id": "heroe", "kind": "character", "status": "approved", "approvedAttemptId": "ok1",
            "spec": {"role": "enemy"},
            "attempts": [{"id": "ok1", "status": "ok", "files": {"rawKey": "hero.png"}}],
        }],
    }
    asset = {
        "id": "heroe3d", "kind": "character3d", "description": "the knight",
        "spec": {"character": "heroe", "profile": "humanoid", "maxTriangles": 3000},
    }
    fake = _Tools(picture, mesh, rigged)
    result = Character3dGenerator().run(_ctx(tmp_path, game, asset, fake))
    tools = [name for name, _args in fake.calls]
    assert "generation.image" not in tools
    assert tools == ["model3d.generate", "model3d.status", "model3d.rig", "model3d.rig.status"]
    rig_call = next(args["input"] for name, args in fake.calls if name == "model3d.rig")
    assert rig_call["engine"] == "humanoid"
    assert rig_call["animations"] == ["idle", "walk", "attack", "hit"]
    assert "rig_profile" not in rig_call
    assert "hero.png" in rig_call["source"] or "hero.png" in next(
        args["input"]["image_path"] for name, args in fake.calls if name == "model3d.generate"
    )
    assert result.metrics["missingClips"] == ["walk", "attack", "hit"]
    assert "clip_missing" in result.warnings
    assert "over_budget" not in result.warnings
    assert (tmp_path / "ws" / result.files["rig"]).is_file()


def test_non_humanoid_profile_asks_for_a_procedural_rig(tmp_path):
    picture = tmp_path / "bird.png"
    picture.write_bytes(b"png")
    glb = tmp_path / "cube.glb"
    _cube(glb, clip="idle")
    game = {"id": "bosque", "style": _style(), "assets": []}
    asset = {
        "id": "ave", "kind": "character3d", "description": "a bird",
        "spec": {"profile": "flying", "maxTriangles": 3000},
    }
    fake = _Tools(picture, glb, glb)
    Character3dGenerator().run(_ctx(tmp_path, game, asset, fake))
    rig_call = next(args["input"] for name, args in fake.calls if name == "model3d.rig")
    assert rig_call["engine"] == "procedural"
    assert rig_call["rig_profile"] == "flying"
    assert rig_call["animations"] == list(clips_for("player"))
