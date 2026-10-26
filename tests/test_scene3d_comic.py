"""Comic-page chapter transition: two saved scenes, a fake export, and the failures that must not write."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest
from fastapi import HTTPException

from PIL import Image

from services.scene3d_comic import bind_comic_exporter
from services.scene3d_comic_cutout import bind_comic_cutout
from services.world3d_template_commands import command_catalog, execute_command

ROOT = Path(__file__).resolve().parents[1]
FILLER = ROOT / "ui" / "public" / "scene3d" / "comic"


def _paint_cutout(source, dest):
    image = Image.open(source).convert("RGBA")
    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            if min(x, y, width - 1 - x, height - 1 - y) < 8:
                red, green, blue, _alpha = pixels[x, y]
                pixels[x, y] = (red, green, blue, 0)
    image.save(dest)
    return dest


@pytest.fixture(autouse=True)
def _clear_exporter():
    bind_comic_exporter(None)
    bind_comic_cutout(_paint_cutout)
    yield
    bind_comic_exporter(None)
    bind_comic_cutout(None)


class _FakeExport:
    def export_clip(self, workspace, document, output_name):
        assert document["templateId"].startswith("comic-panel-")
        assert document["look"]["toneMapping"] == "none"
        return {"name": f"{output_name}.mp4", "url": f"/api/v1/file/{output_name}.mp4?workspace={workspace}"}


def _panels(cutout=False):
    panels = []
    for index in range(4):
        image = str(FILLER / f"panel-landscape-{index}.png")
        if cutout and index == 1:
            panels.append({"image": image, "cutout": str(FILLER / "cutout-landscape.png")})
        else:
            panels.append(image)
    return panels


def _call(tmp_path, panels, *, export=False, fmt="landscape", intent="comic-1", **extra):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir(exist_ok=True)
    return execute_command("scene3d.comic.transition", {
        "version": 1, "intent_id": intent,
        "input": {"workspace": "studio", "format": fmt, "panels": panels, "from_panel": 0, "to_panel": 3, "export": export, **extra},
    }, root)


def _documents(tmp_path, scenes):
    studio = tmp_path / "studio" / "world3d-edits"
    return [json.loads((studio / f"{scene['sceneId']}.json").read_text())["document"] for scene in scenes]


def _endpoint(document, end: bool):
    framing = document["camera"]["framing"]
    slot = next(item for item in document["slots"] if item["id"] == framing["targetSlot"])
    center = [slot["position"][0], slot["position"][1] + slot["scale"], slot["position"][2]]
    eye_key, look_key = ("to", "lookTo") if end else ("from", "lookFrom")
    scale = slot["scale"]
    eye = [center[i] + framing[eye_key][i] * scale for i in range(3)]
    look = [center[i] + framing[look_key][i] * scale for i in range(3)]
    return eye, look


def _written(tmp_path):
    studio = tmp_path / "studio"
    return [path.relative_to(studio).as_posix() for path in studio.rglob("*") if path.is_file()]


def test_the_scene2d_exporter_does_not_replace_the_video3d_one():
    import services.scene3d_comic as comic

    class _World:
        operation = "scenes.world3d.export"

    class _Flat:
        operation = "scenes.video2d.export"

    comic.bind_live_exporter(_World())
    bound = comic._EXPORTER
    assert bound is not None
    comic.bind_live_exporter(_Flat())
    assert comic._EXPORTER is bound
    comic.bind_live_exporter(object())
    assert comic._EXPORTER is bound


def test_the_operation_is_in_the_shared_catalog():
    named = {item["name"]: item for item in command_catalog()}
    assert named["scene3d.comic.transition"]["mutation"] is True
    assert "panels" in named["scene3d.comic.transition"]["inputSchema"]["properties"]["input"]["properties"]


def test_a_transition_saves_two_editable_scenes_and_exports_through_the_bound_exporter(tmp_path):
    bind_comic_exporter(_FakeExport())
    reply = _call(tmp_path, _panels(cutout=True), export=True)
    assert reply["status"] == "completed"
    scenes = reply["result"]["scenes"]
    assert [scene["role"] for scene in scenes] == ["exit", "enter"]
    assert {scene["templateId"] for scene in scenes} == {"comic-panel-exit", "comic-panel-enter"}
    for scene in scenes:
        assert scene["sceneId"].startswith("w3d-") and len(scene["sceneId"]) == 16
        assert (tmp_path / "studio" / "world3d-edits" / f"{scene['sceneId']}.json").is_file()
        assert (tmp_path / "studio" / scene["file"]).is_file()
    assert [clip["name"] for clip in reply["result"]["clips"]] == ["comic-panel-exit.mp4", "comic-panel-enter.mp4"]
    stored = json.loads((tmp_path / "studio" / "world3d-edits" / f"{scenes[0]['sceneId']}.json").read_text())
    slots = stored["document"]["slots"]
    ids = [slot["id"] for slot in slots]
    assert ids == ["page", "panel-0", "panel-1", "panel-2", "panel-3", "cutout-0", "cutout-1", "cutout-2", "cutout-3"]
    assert slots[0]["sourceUrl"].startswith("/api/v1/file/comic-page-landscape.png")
    panel = next(slot for slot in slots if slot["id"] == "panel-0")
    cutout = next(slot for slot in slots if slot["id"] == "cutout-0")
    distance = panel["scale"] / math.tan(math.radians(36) / 2)
    factor = (distance - 0.04) / distance
    assert cutout["scale"] == pytest.approx(panel["scale"] * factor)
    assert cutout["position"][2] == pytest.approx(panel["position"][2] + 0.04)
    assert cutout["position"][1] + cutout["scale"] == pytest.approx(panel["position"][1] + panel["scale"])
    assert stored["document"]["duration"] == pytest.approx(1.8)
    assert stored["document"]["camera"]["framing"]["yawArc"] == 8
    assert reply["result"]["warnings"] == []


def test_the_wide_pose_is_shared_and_the_durations_are_parameters(tmp_path):
    reply = _call(tmp_path, _panels(), intent="comic-arc", exit_duration=2.2, enter_duration=2.0, hold=0.5)
    exit_doc, enter_doc = _documents(tmp_path, reply["result"]["scenes"])
    assert exit_doc["duration"] == pytest.approx(2.2)
    assert enter_doc["duration"] == pytest.approx(2.0)
    assert exit_doc["camera"]["framing"]["yawArc"] == enter_doc["camera"]["framing"]["yawArc"] == 8
    assert exit_doc["camera"]["framing"]["moveStart"] == 0
    assert 0.5 < exit_doc["camera"]["framing"]["moveEnd"] < 1
    assert 0 < enter_doc["camera"]["framing"]["moveStart"] < 0.5
    exit_eye, exit_look = _endpoint(exit_doc, True)
    enter_eye, enter_look = _endpoint(enter_doc, False)
    assert exit_eye == pytest.approx(enter_eye)
    assert exit_look == pytest.approx(enter_look)
    assert abs(exit_eye[0]) > 0.05


def test_a_hold_that_eats_the_move_is_rejected(tmp_path):
    with pytest.raises(HTTPException) as eaten:
        _call(tmp_path, _panels(), intent="comic-hold", hold=1.8)
    assert eaten.value.status_code == 422 and eaten.value.detail["code"] == "invalid_duration"
    assert _written(tmp_path) == []


def test_a_missing_source_and_a_missing_exporter_write_nothing(tmp_path):
    broken = _panels()
    broken[0] = {"video": str(tmp_path / "missing.mp4"), "at": 60}
    with pytest.raises(HTTPException) as missing:
        _call(tmp_path, broken, export=False, intent="comic-missing")
    assert missing.value.status_code == 422 and missing.value.detail["code"] == "missing_source"
    assert _written(tmp_path) == []
    with pytest.raises(HTTPException) as offline:
        _call(tmp_path, _panels(), export=True, intent="comic-offline")
    assert offline.value.status_code == 503 and offline.value.detail["code"] == "export_unavailable"
    assert _written(tmp_path) == []


def test_an_empty_cutout_leaves_the_panel_flat_and_warns(tmp_path):
    bind_comic_cutout(lambda _source, _dest: None)
    reply = _call(tmp_path, _panels(), export=False, intent="comic-empty")
    assert reply["result"]["warnings"]
    assert all("cutout unavailable" in warning for warning in reply["result"]["warnings"])
    stored = json.loads(next((tmp_path / "studio" / "world3d-edits").glob("*.json")).read_text())
    assert [slot["id"] for slot in stored["document"]["slots"] if slot["id"].startswith("cutout")] == []


def test_five_panels_are_rejected(tmp_path):
    with pytest.raises(HTTPException) as counted:
        _call(tmp_path, _panels() + [_panels()[0]], intent="comic-five")
    assert counted.value.status_code == 422 and counted.value.detail["code"] == "panel_count"
    assert _written(tmp_path) == []
