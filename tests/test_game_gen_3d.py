"""3D generators with a synthetic 12-triangle cube. No GPU.

The fake tools answer like the server: outputs are names inside the workspace,
not absolute paths.
"""
from __future__ import annotations

import json
import shutil
import struct
from pathlib import Path

import pytest

from services.game_generators.base import GenContext
from services.game_generators.three_d import (
    Character3dGenerator,
    Model3dGenerator,
    budget_warning,
    clips_for,
)
from services.game_produce import _candidates
from services.game_tools import GameToolError

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


def _cube(path: Path, *, clips: tuple[str, ...] = (), skinned: bool = False, mode: int = 4) -> Path:
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
        "meshes": [{"name": "Cube", "primitives": [{"attributes": {"POSITION": 0}, "indices": 1, "mode": mode}]}],
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
    if skinned:
        document["nodes"] = [{"mesh": 0, "skin": 0}, {"name": "Hips"}]
        document["skins"] = [{"joints": [1]}]
    if clips:
        document["animations"] = [{"name": name, "channels": [], "samplers": []} for name in clips]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_pack(document, blob))
    return path


class _Tools:
    """Server-shaped fake. ``images``, ``meshes`` and ``rigs`` are workspace names."""

    def __init__(self, workspace: Path, *, images=("cofre-concept.png",), meshes=("hy-mesh.glb",),
                 rigs=("hy-rigged.glb",), video="orbit.mp4"):
        self.workspace = workspace
        self.images = list(images)
        self.meshes = list(meshes)
        self.rigs = list(rigs)
        self.video = video
        self.calls = []
        self.loopbacks = []

    def _next(self, names: list[str]) -> str:
        return names.pop(0) if len(names) > 1 else names[0]

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool in {"generation.image", "model3d.generate", "model3d.rig"}:
            return {"receipt": {"result": {"job_id": f"job-{tool}"}}}
        if tool == "jobs.wait":
            job = args["input"]["job_id"]
            files = [self.video] if job == "orbit-job" else list(self.images)
            return {"status": "completed", "output_files": files}
        if tool == "model3d.status":
            return {"status": "completed", "filename": self._next(self.meshes)}
        if tool == "model3d.rig.status":
            return {"status": "completed", "filename": self._next(self.rigs)}
        raise AssertionError(tool)

    def loopback(self, tool, args):
        self.loopbacks.append((tool, args))
        return {"receipt": {"result": {"job_id": "orbit-job"}}}

    def named(self, tool: str) -> list[dict]:
        return [args for name, args in self.calls if name == tool]


def _workspace(tmp_path: Path) -> Path:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    (workspace / "cofre-concept.png").write_bytes(b"png")
    _cube(workspace / "hy-mesh.glb")
    _cube(workspace / "hy-rigged.glb", skinned=True, clips=("Idle",))
    return workspace


def _ctx(workspace: Path, game: dict, asset: dict, fake: _Tools) -> GenContext:
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=fake.loopback, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )


def _style(limit: int = 3000, look: str = "toon") -> dict:
    return {"preset": "pixel-16", "traits": "flat toon", "model3d": {"maxTriangles": limit, "look": look}}


def _chest(**spec) -> dict:
    return {"id": "cofre", "kind": "model3d", "description": "a chest", "candidates": 1,
            "spec": {"maxTriangles": 3000, "multiview": False, **spec}}


def _character(game_assets=(), **spec) -> tuple[dict, dict]:
    game = {"id": "bosque", "style": _style(), "assets": list(game_assets)}
    asset = {"id": "heroe3d", "kind": "character3d", "description": "the knight", "candidates": 1,
             "spec": {"profile": "humanoid", "maxTriangles": 3000, **spec}}
    return game, asset


def _approved_hero(role: str = "enemy") -> dict:
    return {
        "id": "heroe", "kind": "character", "status": "approved", "approvedAttemptId": "ok1",
        "spec": {"role": role},
        "attempts": [{"id": "ok1", "status": "ok", "files": {"rawKey": "hero.png"}}],
    }


def _frames(monkeypatch, seen: list | None = None) -> None:
    def grab(video, _start, _end, folder):
        if not Path(video).is_file():
            raise RuntimeError(f"ffmpeg failed to extract frames: {video} not found")
        if seen is not None:
            seen.append(Path(folder))
        path = Path(folder)
        path.mkdir(parents=True, exist_ok=True)
        frame = path / "0001.png"
        frame.write_bytes(b"png")
        return [frame]

    monkeypatch.setattr("services.game_frames.extract_frames", grab)


def test_clip_map_and_budget_thresholds():
    assert clips_for("player") == ("idle", "walk", "run", "jump", "punch", "victory")
    assert clips_for("enemy") == ("idle", "walk", "attack", "hit")
    assert clips_for("boss") == clips_for("enemy")
    assert clips_for("npc") == ("idle", "talk", "wave")
    assert budget_warning(11, 10) == []
    assert budget_warning(12, 10) == ["over_budget"]
    assert budget_warning(None, 10) == ["triangles_unknown"]
    assert budget_warning(12, None) == []


def test_model_calls_image_then_mesh_and_warns_over_budget(tmp_path):
    workspace = _workspace(tmp_path)
    game = {"id": "bosque", "style": _style(10), "assets": []}
    fake = _Tools(workspace)
    result = Model3dGenerator().run(_ctx(workspace, game, _chest(maxTriangles=10), fake))
    tools = [name for name, _args in fake.calls]
    assert tools == ["generation.image", "jobs.wait", "model3d.generate", "model3d.status"]
    params = fake.calls[0][1]["input"]["params"]
    assert params["resolution"] == "1024x1024"
    assert "plain light grey background" in params["prompt"]
    assert "no shadow" in params["prompt"]
    assert "flat solid" not in params["prompt"]
    mesh = fake.named("model3d.generate")[0]["input"]
    assert mesh["preset"] == "balanced"
    assert mesh["reduce_face"] is True
    assert mesh["target_face_num"] == 10
    assert "images" not in mesh
    assert result.metrics["triangles"] == 12
    assert "over_budget" in result.warnings
    assert result.files["model"] == "game/bosque/cofre/a1/model.glb"
    assert result.files["concept"] == "game/bosque/cofre/a1/concept.png"
    assert (workspace / result.files["model"]).is_file()
    assert (workspace / result.files["concept"]).is_file()


def test_model_candidates_get_their_own_ids_folders_and_jobs(tmp_path):
    workspace = _workspace(tmp_path)
    (workspace / "cofre-concept-2.png").write_bytes(b"png2")
    _cube(workspace / "hy-mesh-2.glb")
    game = {"id": "bosque", "style": _style(), "assets": []}
    asset = {**_chest(), "candidates": 2}
    fake = _Tools(workspace, images=("cofre-concept.png", "cofre-concept-2.png"), meshes=("hy-mesh.glb", "hy-mesh-2.glb"))
    generator = Model3dGenerator()
    result = generator.run(_ctx(workspace, game, asset, fake))
    assert fake.named("generation.image")[0]["input"]["params"]["batch_size"] == 2
    meshes = fake.named("model3d.generate")
    assert [args["input"]["image_path"] for args in meshes] == ["cofre-concept.png", "cofre-concept-2.png"]
    assert len({args["intent_id"] for args in meshes}) == 2
    saved = _candidates(result, "a1")
    assert [attempt_id for attempt_id, _files, _metrics in saved] == ["a1-a1", "a1-a2"]
    assert [files["model"] for _id, files, _metrics in saved] == [
        "game/bosque/cofre/a1/a1/model.glb", "game/bosque/cofre/a1/a2/model.glb",
    ]
    assert all(metrics["triangles"] == 12 for _id, _files, metrics in saved)
    assert (workspace / saved[1][1]["concept"]).read_bytes() == b"png2"
    assert generator.estimate(game, asset) == {"image": 2, "3d": 2}


def test_seed_zero_reaches_the_concept_image(tmp_path):
    workspace = _workspace(tmp_path)
    game = {"id": "bosque", "style": _style(), "assets": []}
    fake = _Tools(workspace)
    Model3dGenerator().run(_ctx(workspace, game, _chest(seed=0), fake))
    assert fake.named("generation.image")[0]["input"]["params"]["seed"] == 0


def test_lowpoly_look_keeps_a_textured_preset(tmp_path):
    from services.model3d_service import PRESETS

    workspace = _workspace(tmp_path)
    game = {"id": "bosque", "style": _style(look="lowpoly"), "assets": []}
    fake = _Tools(workspace)
    Model3dGenerator().run(_ctx(workspace, game, _chest(), fake))
    preset = fake.named("model3d.generate")[0]["input"]["preset"]
    assert PRESETS[preset]["texture_mode"] != "none"


def test_multiview_sends_four_views_from_the_workspace_video(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    (workspace / "orbit.mp4").write_bytes(b"mp4")
    _frames(monkeypatch)
    game = {"id": "bosque", "style": _style(), "assets": []}
    asset = _chest(multiview=True)
    fake = _Tools(workspace)
    generator = Model3dGenerator()
    result = generator.run(_ctx(workspace, game, asset, fake))
    tools = [name for name, _args in fake.calls]
    assert tools[:4] == ["generation.image", "jobs.wait", "jobs.wait", "model3d.generate"]
    assert fake.loopbacks[0][0] == "generate"
    mesh = fake.named("model3d.generate")[0]["input"]
    assert mesh["preset"] == "multiview"
    assert list(mesh["images"]) == ["front", "left", "back", "right"]
    assert "orbit_empty" not in result.warnings
    assert generator.estimate(game, asset) == {"image": 1, "3d": 1, "h3": 1}


def test_multiview_candidates_keep_their_orbit_frames_apart(tmp_path, monkeypatch):
    workspace = _workspace(tmp_path)
    (workspace / "orbit.mp4").write_bytes(b"mp4")
    seen: list[Path] = []
    _frames(monkeypatch, seen)
    game = {"id": "bosque", "style": _style(), "assets": []}
    asset = {**_chest(multiview=True), "candidates": 2}
    fake = _Tools(workspace, images=("cofre-concept.png", "cofre-concept.png"))
    Model3dGenerator().run(_ctx(workspace, game, asset, fake))
    assert len({args["request_id"] for _tool, args in fake.loopbacks}) == 2
    assert {folder.parent.parent.name for folder in seen} == {"a1", "a2"}


def test_corrupt_mesh_fails_the_attempt(tmp_path):
    workspace = _workspace(tmp_path)
    (workspace / "broken.glb").write_bytes(b"not a glb at all")
    game = {"id": "bosque", "style": _style(), "assets": []}
    fake = _Tools(workspace, meshes=("broken.glb",))
    with pytest.raises(GameToolError) as caught:
        Model3dGenerator().run(_ctx(workspace, game, _chest(), fake))
    assert caught.value.code == "invalid_glb"


def test_uncountable_mesh_is_flagged(tmp_path):
    workspace = _workspace(tmp_path)
    _cube(workspace / "odd.glb", mode=9)
    game = {"id": "bosque", "style": _style(), "assets": []}
    fake = _Tools(workspace, meshes=("odd.glb",))
    result = Model3dGenerator().run(_ctx(workspace, game, _chest(), fake))
    assert result.metrics["triangles"] is None
    assert "triangles_unknown" in result.warnings


def test_character_uses_approved_art_and_reports_missing_clips(tmp_path):
    workspace = _workspace(tmp_path)
    (workspace / "hero.png").write_bytes(b"png")
    game, asset = _character([_approved_hero("enemy")], character="heroe")
    fake = _Tools(workspace)
    generator = Character3dGenerator()
    result = generator.run(_ctx(workspace, game, asset, fake))
    tools = [name for name, _args in fake.calls]
    assert tools == ["model3d.generate", "model3d.status", "model3d.rig", "model3d.rig.status"]
    assert fake.named("model3d.generate")[0]["input"]["image_path"].endswith("hero.png")
    rig_call = fake.named("model3d.rig")[0]["input"]
    assert rig_call["engine"] == "humanoid"
    assert rig_call["source"] == "hy-mesh.glb"
    assert "rig_profile" not in rig_call
    assert result.metrics["missingClips"] == ["walk", "punch", "hit"]
    assert "clip_missing" in result.warnings
    assert "over_budget" not in result.warnings
    assert "concept" not in result.files
    assert (workspace / result.files["rig"]).is_file()
    assert generator.estimate(game, asset) == {"3d": 1, "rig": 1}


def test_enemy_humanoid_asks_only_for_clips_the_humanoid_rig_has(tmp_path):
    from services.humanoid_rig.names import CLIP_IDS

    workspace = _workspace(tmp_path)
    (workspace / "hero.png").write_bytes(b"png")
    game, asset = _character([_approved_hero("boss")], character="heroe")
    fake = _Tools(workspace)
    Character3dGenerator().run(_ctx(workspace, game, asset, fake))
    animations = fake.named("model3d.rig")[0]["input"]["animations"]
    assert animations == ["idle", "walk", "punch", "hit"]
    assert set(animations) <= set(CLIP_IDS)


def test_spec_clips_replace_the_role_clips(tmp_path):
    workspace = _workspace(tmp_path)
    game, asset = _character(clips=["idle", "wave", "look_around"])
    _cube(workspace / "hy-rigged.glb", skinned=True, clips=("Idle", "Wave", "Look Around"))
    fake = _Tools(workspace)
    result = Character3dGenerator().run(_ctx(workspace, game, asset, fake))
    assert fake.named("model3d.rig")[0]["input"]["animations"] == ["idle", "wave", "look_around"]
    assert result.metrics["missingClips"] == []
    assert "clip_missing" not in result.warnings


def test_non_humanoid_profile_sends_only_clips_its_profile_allows(tmp_path):
    from services.rig_service import RIG_PROFILES_BY_ID

    workspace = _workspace(tmp_path)
    _cube(workspace / "hy-rigged.glb", skinned=True, clips=("Idle Sway", "Jump", "Attack Lunge", "Victory Jump"))
    game, asset = _character(profile="flying")
    fake = _Tools(workspace)
    result = Character3dGenerator().run(_ctx(workspace, game, asset, fake))
    rig_call = fake.named("model3d.rig")[0]["input"]
    assert rig_call["engine"] == "procedural"
    assert rig_call["rig_profile"] == "flying"
    assert rig_call["animations"] == ["idle", "jump", "attack", "victory"]
    assert set(rig_call["animations"]) <= set(RIG_PROFILES_BY_ID["flying"]["allowed_animations"])
    assert result.metrics["missingClips"] == ["walk", "run"]


def test_procedural_clip_labels_count_as_present(tmp_path):
    workspace = _workspace(tmp_path)
    labels = ("Idle Sway", "Walk Cycle", "Attack Lunge", "Hit Reaction")
    _cube(workspace / "hy-rigged.glb", skinned=True, clips=labels)
    game, asset = _character([{"id": "lobo", "kind": "character", "spec": {"role": "enemy"}}],
                             profile="quadruped", character="lobo")
    fake = _Tools(workspace)
    result = Character3dGenerator().run(_ctx(workspace, game, asset, fake))
    assert result.metrics["clips"] == list(labels)
    assert result.metrics["missingClips"] == []
    assert "clip_missing" not in result.warnings


def test_rig_without_a_skin_fails_the_attempt(tmp_path):
    workspace = _workspace(tmp_path)
    shutil.copyfile(workspace / "hy-mesh.glb", workspace / "hy-rigged.glb")
    game, asset = _character()
    fake = _Tools(workspace)
    with pytest.raises(GameToolError) as caught:
        Character3dGenerator().run(_ctx(workspace, game, asset, fake))
    assert caught.value.code == "rig_missing"
