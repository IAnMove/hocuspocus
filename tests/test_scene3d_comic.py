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
    stored = json.loads((tmp_path / "studio" / "world3d-edits" / f"{scenes[0]['sceneId']}.json").read_text())
    ids = [slot["id"] for slot in stored["document"]["slots"]]
    assert ids == ["page", "panel-0", "panel-1", "panel-2", "panel-3", "cutout-1"]
    page_url = stored["document"]["slots"][0]["sourceUrl"]
    assert page_url.startswith("/api/v1/file/comic-") and "-page-landscape.png" in page_url
    token = page_url.split("/api/v1/file/comic-", 1)[1].split("-page-", 1)[0]
    assert [clip["name"] for clip in reply["result"]["clips"]] == [f"comic-{token}-exit.mp4", f"comic-{token}-enter.mp4"]
    assert (tmp_path / "studio" / f"comic-{token}-panel-0.png").is_file()
    assert (tmp_path / "studio" / f"comic-{token}-cutout-1.png").is_file()


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


def _panel_url(tmp_path, scene_id: str, slot_id: str) -> str:
    stored = json.loads((tmp_path / "studio" / "world3d-edits" / f"{scene_id}.json").read_text())
    slot = next(item for item in stored["document"]["slots"] if item["id"] == slot_id)
    return slot["sourceUrl"]


def _file_of(url: str) -> str:
    return url.split("/api/v1/file/", 1)[1].split("?", 1)[0]


def test_a_second_transition_keeps_the_first_scene_pictures(tmp_path):
    first = _call(tmp_path, _panels(), intent="comic-first")
    first_id = first["result"]["scenes"][0]["sceneId"]
    first_panel = _file_of(_panel_url(tmp_path, first_id, "panel-0"))
    first_bytes = (tmp_path / "studio" / first_panel).read_bytes()
    other = []
    for index in range(4):
        dest = tmp_path / "studio" / f"other-{index}.png"
        dest.write_bytes((FILLER / f"panel-landscape-{3 - index}.png").read_bytes())
        other.append(f"/api/v1/file/other-{index}.png?workspace=studio")
    second = _call(tmp_path, other, intent="comic-second")
    second_id = second["result"]["scenes"][0]["sceneId"]
    second_panel = _file_of(_panel_url(tmp_path, second_id, "panel-0"))
    assert first_panel != second_panel
    assert (tmp_path / "studio" / first_panel).read_bytes() == first_bytes
    assert (tmp_path / "studio" / first_panel).read_bytes() != (tmp_path / "studio" / second_panel).read_bytes()
    assert _panel_url(tmp_path, first_id, "panel-0") == f"/api/v1/file/{first_panel}?workspace=studio"


def test_five_panels_are_rejected(tmp_path):
    with pytest.raises(HTTPException) as counted:
        _call(tmp_path, _panels() + [_panels()[0]], intent="comic-five")
    assert counted.value.status_code == 422 and counted.value.detail["code"] == "panel_count"
    assert _written(tmp_path) == []
