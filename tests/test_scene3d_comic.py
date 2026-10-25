"""Comic-page chapter transition: two saved scenes, a fake export, and the failures that must not write."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.scene3d_comic import bind_comic_exporter
from services.world3d_template_commands import command_catalog, execute_command

ROOT = Path(__file__).resolve().parents[1]
FILLER = ROOT / "ui" / "public" / "scene3d" / "comic"


@pytest.fixture(autouse=True)
def _clear_exporter():
    bind_comic_exporter(None)
    yield
    bind_comic_exporter(None)


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


def _call(tmp_path, panels, *, export=False, fmt="landscape", intent="comic-1"):
    root = lambda workspace: str(tmp_path / workspace)
    (tmp_path / "studio").mkdir(exist_ok=True)
    return execute_command("scene3d.comic.transition", {
        "version": 1, "intent_id": intent,
        "input": {"workspace": "studio", "format": fmt, "panels": panels, "from_panel": 0, "to_panel": 3, "export": export},
    }, root)


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
    ids = [slot["id"] for slot in stored["document"]["slots"]]
    assert ids == ["page", "panel-0", "panel-1", "panel-2", "panel-3", "cutout-1"]
    assert stored["document"]["slots"][0]["sourceUrl"].startswith("/api/v1/file/comic-page-landscape.png")


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


def test_five_panels_are_rejected(tmp_path):
    with pytest.raises(HTTPException) as counted:
        _call(tmp_path, _panels() + [_panels()[0]], intent="comic-five")
    assert counted.value.status_code == 422 and counted.value.detail["code"] == "panel_count"
    assert _written(tmp_path) == []
