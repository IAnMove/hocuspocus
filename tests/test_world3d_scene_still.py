"""world3d.scene.preview {still: true} paints real frames with the export's renderer (replaced here by a fake one), and a
preview reply carries each picture once: as an image block over MCP, never again as base64 in its text."""
import base64
import io
import json

import pytest

from routers.wangp_mcp import _tool_content
import services.world3d_scene_still as still
from services.world3d_template_commands import execute_command
from tests.test_world3d_scene_layout import WORKSPACE, workspace_dir


def _png(colour) -> bytes:
    from PIL import Image
    buffer = io.BytesIO()
    Image.new("RGB", (64, 36), colour).save(buffer, "PNG")
    return buffer.getvalue()


@pytest.fixture
def blank(tmp_path):
    (tmp_path / WORKSPACE).mkdir()
    made = execute_command("world3d.scene.instantiate", {"version": 1, "intent_id": "still-blank", "input": {
        "workspace": WORKSPACE, "template_id": "blank", "width": 1080, "height": 1920, "duration": 4}}, workspace_dir(tmp_path))
    return tmp_path, made["result"]["scene"]["sceneId"]


def test_a_still_paints_the_scene_with_the_export_renderer_at_each_time(blank, monkeypatch):
    tmp_path, scene_id = blank
    seen = []

    def fake(snapshot, staging, cancelled):
        seen.append(snapshot)
        paths = []
        for index, _time in enumerate(snapshot["plan"]["times"]):
            path = staging / f"frame_{index}.png"
            path.write_bytes(_png((40 * index, 90, 160)))
            paths.append(path)
        return paths

    monkeypatch.setattr(still, "RENDERER", fake)
    reply = execute_command("world3d.scene.preview", {"version": 1, "input": {"workspace": WORKSPACE, "scene_id": scene_id, "still": True,
                                                                              "times": [0.5, 3]}}, workspace_dir(tmp_path))["result"]
    plan = seen[0]["plan"]
    assert (plan["width"], plan["height"], plan["times"]) == (360, 640, [0.5, 3.0]), "640 px on the long side, the scene's aspect"
    assert seen[0]["document"]["templateId"] == "blank" and seen[0]["workspace"] == WORKSPACE
    assert reply["still"] is True and reply["times"] == [0.5, 3.0] and len(reply["images"]) == 2
    assert reply["images"][0]["mimeType"] == "image/jpeg" and base64.b64decode(reply["images"][0]["data"])[:2] == b"\xff\xd8"
    assert all("data" not in frame and "png" not in frame for frame in reply["frames"])
    with pytest.raises(Exception, match="times is a list of 1 to 3"):
        execute_command("world3d.scene.preview", {"version": 1, "input": {"workspace": WORKSPACE, "scene_id": scene_id, "still": True,
                                                                          "times": [0, 1, 2, 3]}}, workspace_dir(tmp_path))


def test_no_renderer_is_a_clear_refusal_not_a_broken_picture(blank, monkeypatch):
    tmp_path, scene_id = blank
    monkeypatch.setattr(still, "RENDERER", None)
    monkeypatch.setattr(still, "_SERVICE", None)
    with pytest.raises(Exception) as refused:
        execute_command("world3d.scene.preview", {"version": 1, "input": {"workspace": WORKSPACE, "scene_id": scene_id, "still": True}},
                        workspace_dir(tmp_path))
    detail = refused.value.detail
    assert refused.value.status_code == 503 and detail["code"] == "still_renderer_unavailable" and "still: false" in detail["message"]


def test_mcp_text_names_the_image_blocks_instead_of_repeating_them():
    data = base64.b64encode(_png((1, 2, 3))).decode()
    content = _tool_content({"frames": [{"time": 1, "sha256": "abc"}], "images": [{"mimeType": "image/png", "data": data}]})
    assert [block["type"] for block in content] == ["text", "image"] and content[1]["data"] == data
    assert data not in content[0]["text"] and json.loads(content[0]["text"])["images"][0]["data"] == "(image block 1 below)"
    assert _tool_content({"value": 1}) == [{"type": "text", "text": '{"value": 1}'}]
