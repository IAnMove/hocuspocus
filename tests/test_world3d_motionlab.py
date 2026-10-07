"""Native Motion Lab controls use the shared catalog and keep the export audio contract."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from services.scene_documents import get_document
from services.world3d_export import World3DExportService, _has_sound
from services.world3d_scenes import MOTION_LAB_DEFAULTS, World3DSceneError, _motion_lab_settings, inspect_scene, patch_scene, publish_scene
from services.world3d_template_commands import command_catalog, execute_command

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "studio"
SCENE_ID = "w3d-000000000001"
MOTION_IDS = (
    "motion-bouncing-ball", "motion-music-machine", "motion-sunset-flight", "motion-seasonal-carriage",
    "motion-data-assembly", "motion-lighthouse-story", "motion-poster-breakout", "motion-particle-morph",
)
needs_ui = pytest.mark.skipif(
    not (ROOT / "ui/node_modules/tsx/dist/loader.mjs").is_file(),
    reason="UI dependencies not installed in Python-only CI",
)


def _document(**overrides):
    document = {
        "version": 1, "units": "meters", "up": "y", "width": 640, "height": 360, "fps": 30,
        "duration": 8, "templateId": "two-shot", "slots": [],
        "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
        "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
    }
    return {**document, **overrides}


def _working_scene(tmp_path, document):
    workspace_dir = lambda name: str(tmp_path / name)
    path = tmp_path / WORKSPACE / "world3d-edits" / f"{SCENE_ID}.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"revision": 1, "templateId": document["templateId"], "document": document}), encoding="utf-8")
    return workspace_dir, path


def _command(operation, workspace_dir, data, intent=None):
    arguments = {"version": 1, "input": {"workspace": WORKSPACE, **data}}
    if intent:
        arguments["intent_id"] = intent
    return execute_command(operation, arguments, workspace_dir)["result"]


def test_patch_schema_exposes_bounded_partial_motion_lab_controls():
    patch = next(command for command in command_catalog() if command["name"] == "world3d.scene.patch")
    schema = patch["inputSchema"]["properties"]["input"]["properties"]["motionLab"]
    assert schema["additionalProperties"] is False
    assert {key: field["default"] for key, field in schema["properties"].items()} == MOTION_LAB_DEFAULTS
    assert "required" not in schema
    assert schema["properties"]["seed"]["type"] == "integer"
    assert schema["properties"]["density"]["maximum"] == 3000
    assert schema["properties"]["bpm"]["minimum"] == 40


@needs_ui
def test_backend_controls_match_the_real_editor_parser():
    controls = [
        {}, {"bpm": 144, "title": "  HELLO  "}, {"seed": 7.0, "density": 900.0, "color": "#ABCDEF"},
        {"title": "\ufeff HELLO \ufeff"}, {"title": "😀" * 12}, {"title": "😀" * 13}, {"title": "\u0085HELLO\u0085"},
        {"bpm": 40, "seed": 0, "density": 200, "amplitude": 0.1, "speed": 0.1, "volume": 0},
        {"bpm": 240, "seed": 2147483647, "density": 3000, "amplitude": 3, "speed": 3, "volume": 1},
        None, [], {"kind": "ball"}, {"constructor": 7}, {"toString": "shadow"}, {"__proto__": {}},
        {"bpm": True}, {"bpm": "120"}, {"seed": 1.5}, {"density": 199},
        {"title": "x" * 25}, {"color": "#abc"}, {"sound": 1}, {"volume": -1},
    ]
    script = """
import { readFileSync } from 'node:fs';
import { parseMotionLab } from './src/features/scene3d/motionlab/types.ts';
const cases = JSON.parse(readFileSync(0, 'utf8'));
process.stdout.write(JSON.stringify(cases.map(value => {
  try { return { settings: parseMotionLab(value) }; }
  catch { return { invalid: true }; }
})));
"""
    result = subprocess.run(
        [shutil.which("node"), "--import", str(ROOT / "ui/node_modules/tsx/dist/loader.mjs"), "--input-type=module", "-e", script],
        input=json.dumps(controls), capture_output=True, text=True, cwd=ROOT / "ui", timeout=30, check=False,
    )
    assert result.returncode == 0, result.stderr
    for raw, editor in zip(controls, json.loads(result.stdout), strict=True):
        try:
            settings = _motion_lab_settings(raw)
        except World3DSceneError:
            assert editor == {"invalid": True}, raw
        else:
            assert editor == {"settings": settings}, raw


def test_partial_patch_preserves_controls_and_gallery_round_trip(tmp_path):
    configured = {**MOTION_LAB_DEFAULTS, "seed": 53, "color": "#AB34EF", "density": 1600, "speed": 1.4}
    document = _document(dressing="motion-bouncing-ball", motionLab=configured)
    workspace_dir, _ = _working_scene(tmp_path, document)
    first = _command("world3d.scene.patch", workspace_dir,
                     {"scene_id": SCENE_ID, "base_revision": 1, "motionLab": {"bpm": 144, "title": "  HELLO  "}}, "motion-patch-1")["scene"]
    expected = {**configured, "bpm": 144, "title": "HELLO"}
    assert first["document"]["motionLab"] == expected
    assert first["traits"]["motionLab"] == expected
    assert "motionLab" in first["editable"]
    first["traits"]["motionLab"]["seed"] = 999
    assert first["document"]["motionLab"]["seed"] == 53

    second = patch_scene(WORKSPACE, SCENE_ID, workspace_dir, {"motionLab": {"sound": False}}, 2)
    expected["sound"] = False
    assert second["document"]["motionLab"] == expected
    published = publish_scene(WORKSPACE, SCENE_ID, workspace_dir)
    reopened = get_document(WORKSPACE, published["file"], workspace_dir=workspace_dir)["document"]
    assert reopened == second["document"]
    assert reopened["motionLab"] == expected
    assert not _has_sound(reopened)


@pytest.mark.parametrize("raw", [
    None, [], {"kind": "bouncing-ball"}, {"unknown": 1}, {"bpm": 39}, {"bpm": 241}, {"bpm": True},
    {"bpm": float("nan")}, {"speed": float("inf")}, {"seed": -1}, {"seed": 2147483648}, {"seed": 1.5},
    {"density": 199}, {"density": 3001}, {"density": 900.5}, {"amplitude": 0}, {"speed": 3.1},
    {"volume": -0.1}, {"volume": 1.1}, {"sound": 1}, {"title": 123}, {"title": "x" * 25},
    {"color": "#fff"}, {"secondaryColor": "#zzzzzz"},
])
def test_invalid_patch_leaves_stored_revision_and_controls_unchanged(tmp_path, raw):
    workspace_dir, path = _working_scene(tmp_path, _document(motionLab=deepcopy(MOTION_LAB_DEFAULTS)))
    before = path.read_bytes()
    with pytest.raises(World3DSceneError) as caught:
        patch_scene(WORKSPACE, SCENE_ID, workspace_dir, {"motionLab": raw}, 1)
    assert caught.value.code == "invalid_motion_lab"
    assert path.read_bytes() == before


def test_motion_controls_default_only_when_explicitly_patched_and_accept_boundaries(tmp_path):
    workspace_dir, _ = _working_scene(tmp_path, _document())
    unchanged = patch_scene(WORKSPACE, SCENE_ID, workspace_dir, {"duration": 12}, 1)
    assert "motionLab" not in unchanged["document"]
    assert "motionLab" not in unchanged["traits"]
    defaulted = patch_scene(WORKSPACE, SCENE_ID, workspace_dir, {"motionLab": {}}, 2)
    assert defaulted["document"]["motionLab"] == MOTION_LAB_DEFAULTS
    low = {"bpm": 40, "seed": 0, "density": 200, "amplitude": 0.1, "speed": 0.1, "volume": 0, "title": ""}
    assert patch_scene(WORKSPACE, SCENE_ID, workspace_dir, {"motionLab": low}, 3)["document"]["motionLab"] == {
        **MOTION_LAB_DEFAULTS, **low,
    }
    high = {"bpm": 240, "seed": 2147483647, "density": 3000, "amplitude": 3, "speed": 3, "volume": 1}
    bounded = patch_scene(WORKSPACE, SCENE_ID, workspace_dir, {"motionLab": high}, 4)
    assert bounded["document"]["motionLab"] == {**MOTION_LAB_DEFAULTS, **high, "title": ""}


@pytest.mark.parametrize("dressing", MOTION_IDS)
def test_export_audio_gate_uses_musical_dressing_and_effective_controls(dressing, tmp_path):
    expected = dressing in MOTION_IDS[:2]
    document = _document(templateId="user-my-motion-scene", dressing=dressing)
    assert _has_sound(document) is expected
    configured = {**document, "motionLab": deepcopy(MOTION_LAB_DEFAULTS)}
    assert _has_sound(configured) is expected
    encoded = tmp_path / "silent.mp4"
    if expected:
        with pytest.raises(RuntimeError, match="produced no audio"):
            World3DExportService.finish_media(None, {"document": configured}, tmp_path, encoded)
    else:
        assert World3DExportService.finish_media(None, {"document": configured}, tmp_path, encoded) == encoded
    for muted in ({"sound": False}, {"volume": 0}):
        quiet = {**document, "motionLab": muted}
        assert not _has_sound(quiet)
        assert World3DExportService.finish_media(None, {"document": quiet}, tmp_path, encoded) == encoded


def test_existing_soundtracks_and_effects_still_require_export_audio():
    assert not _has_sound(_document(motionLab=deepcopy(MOTION_LAB_DEFAULTS)))
    assert not _has_sound(_document(templateId="motion-bouncing-ball"))
    assert _has_sound(_document(soundtrack=[{"audio": {"url": "/api/v1/file/score.wav?workspace=studio"}}]))
    assert _has_sound(_document(sfx=[{"kind": "sparks", "start": 0, "end": 1, "sound": True, "volume": 0.4}]))
    assert _has_sound(_document(dressing="motion-bouncing-ball", motionLab={"sound": False},
                                soundtrack=[{"audio": "/api/v1/file/voice.wav?workspace=studio"}]))


@needs_ui
@pytest.mark.parametrize("template_id", MOTION_IDS)
def test_catalog_discovery_and_apply_query_compile_real_native_documents(tmp_path, template_id):
    workspace_dir = lambda name: str(tmp_path / name)
    hits = _command("world3d.templates.list", workspace_dir, {"query": template_id})["templates"]
    assert hits[0]["id"] == template_id
    exact = _command("world3d.templates.get", workspace_dir, {"template_id": template_id})
    assert exact["document"]["templateId"] == template_id
    assert exact["document"]["dressing"] == template_id
    assert exact["document"]["motionLab"] == MOTION_LAB_DEFAULTS
    assert exact["document"]["slots"] == []
    applied = _command("world3d.scene.apply_query", workspace_dir, {"query": template_id}, f"apply-{template_id}")
    assert applied["chosenId"] == template_id
    scene = applied["scene"]
    assert scene["document"] == exact["document"]
    assert scene["pending"] == []
    assert scene["traits"]["motionLab"] == MOTION_LAB_DEFAULTS
    assert inspect_scene(WORKSPACE, scene["sceneId"], workspace_dir)["document"] == exact["document"]
