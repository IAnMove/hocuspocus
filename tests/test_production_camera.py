"""Production shot cameras do what their names say, over the whole shot, without showing the picture's edge.

The scene documents are built by the real ``Production.scene_ops`` and ``services.video2d_edit.edit``. The view is
read the way the renderer draws it (``ui/src/lib/scene2d/evaluate.ts``: the camera layer's pose and shake move every
picture layer through ``applyCameraTransform``; ``pinFocus`` keeps the focus point on the layer's anchor).
"""
from __future__ import annotations

import math

import pytest
from fastapi import HTTPException

from services.music_production import Production
from services.production_camera import cover_scale
from services.production_quality_gate import blocking_problems, refuse_thin_plan
from services.video2d_edit import Video2dEditError, edit
from services.video2d_preset_catalog import camera_presets

DURATION = 8.0                    # longer than every camera preset (1.1–6 s): nothing may freeze before the cut
CAMERAS = list(camera_presets())


def _document(tmp_path, shot: dict, clips: dict | None = None) -> dict:
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    ops = production.scene_ops(shot, 0.0, DURATION, DURATION, {"lines": []}, clips or {}, {}, {})
    doc = {"version": 1, "name": shot["key"], "width": 1920, "height": 1080, "fps": 24, "duration": DURATION, "layers": [], "texts": []}
    return edit({"version": 1, "input": {"document": doc, "operations": ops, "full": True}})["result"]["document"]


def _still(camera: str | None = None, **extra) -> dict:
    shot = {"key": "s", "kind": "still", "still": "/examples/hero.png", **extra}
    if camera:
        shot["camera"] = camera
    return shot


def _clip(tmp_path, camera: str | None) -> dict:
    shot = {"key": "c", "kind": "clip", "clip": "c"}
    if camera:
        shot["camera"] = camera
    return _document(tmp_path, shot, {"c": {"url": "/api/v1/file/c.mp4", "file": "c.mp4"}})


def _layers(doc: dict) -> tuple[dict, dict]:
    picture = next(layer for layer in doc["layers"] if layer["id"] == "bg")
    camera = next(layer for layer in doc["layers"] if layer["type"] == "camera")
    return picture, camera


def _curve(u: float, curve: str) -> float:
    u = max(0.0, min(1.0, u))
    if curve == "ease":
        return u * u * (3 - 2 * u)
    if curve == "dramatic":
        return u * u
    return u


def _pose(layer: dict, t: float) -> dict:
    animation = layer["animation"]
    amount = _curve(t * DURATION / animation["duration"], animation["curve"])
    return {key: animation["start"].get(key, 0) + (animation["end"].get(key, 0) - animation["start"].get(key, 0)) * amount
            for key in ("x", "y", "scale", "rotation")}


def _box(picture: dict, view: dict) -> tuple[float, float, float, float]:
    """Centre (px), scale and rotation of the drawn picture under a camera pose, in a 1920×1080 frame."""
    width, height, aspect = 1920, 1080, 1920 / 1080
    pose = picture["animation"]["start"]
    theta = math.radians(view["rotation"])
    dx, dy = pose["x"] - 50 - (view["x"] - 50), pose["y"] - 50 - (view["y"] - 50)
    x = 50 + (dx * math.cos(theta) + dy / aspect * math.sin(theta)) * view["scale"]
    y = 50 + (-dx * aspect * math.sin(theta) + dy * math.cos(theta)) * view["scale"]
    scale, rotation = pose["scale"] * view["scale"], pose.get("rotation", 0) - view["rotation"]
    focus = picture.get("focus") or {"x": 50, "y": 50}
    ox, oy = (focus["x"] - 50) / 100 * width * scale, (focus["y"] - 50) / 100 * height * scale
    phi = math.radians(rotation)
    cx = x / 100 * width - (math.cos(phi) * ox - math.sin(phi) * oy)
    cy = y / 100 * height - (math.sin(phi) * ox + math.cos(phi) * oy)
    return cx, cy, scale, rotation


def _seen(picture: dict, view: dict) -> tuple[float, float, float]:
    """The picture point (percent of the picture) at the centre of the frame, and how many times it is enlarged."""
    cx, cy, scale, rotation = _box(picture, view)
    phi = math.radians(rotation)
    dx, dy = 960 - cx, 540 - cy
    u, v = math.cos(phi) * dx + math.sin(phi) * dy, -math.sin(phi) * dx + math.cos(phi) * dy
    return 50 + u / (1920 * scale) * 100, 50 + v / (1080 * scale) * 100, scale


def _edge_margin(picture: dict, view: dict) -> float:
    """Pixels between the frame and the picture's edge (negative: an edge shows)."""
    cx, cy, scale, rotation = _box(picture, view)
    phi = math.radians(rotation)
    margin = math.inf
    for px, py in ((0, 0), (1920, 0), (0, 1080), (1920, 1080)):
        dx, dy = px - cx, py - cy
        u, v = math.cos(phi) * dx + math.sin(phi) * dy, -math.sin(phi) * dx + math.cos(phi) * dy
        margin = min(margin, 1920 * scale / 2 - abs(u), 1080 * scale / 2 - abs(v))
    return margin


def _shaken(view: dict, shake: dict | None) -> list[dict]:
    amount = min(8.0, (shake or {}).get("amount", 0))
    if not amount:
        return [view]
    return [{**view, "x": view["x"] + sx * amount, "y": view["y"] + sy * 0.65 * amount, "rotation": view["rotation"] + sr * 0.35 * amount}
            for sx in (-1, 1) for sy in (-1, 1) for sr in (-1, 1)]


def _kinds(tmp_path):
    return [("still", lambda camera: _document(tmp_path, _still(camera))), ("clip", lambda camera: _clip(tmp_path, camera))]


@pytest.mark.parametrize("camera", CAMERAS)
def test_every_camera_moves_the_view_its_way_over_the_whole_shot(tmp_path, camera):
    for kind, build in _kinds(tmp_path):
        picture, layer = _layers(build(camera))
        assert picture["animation"]["start"] == picture["animation"]["end"], "the picture stays still; the camera moves"
        assert layer["animation"]["duration"] == DURATION, f"{camera} on a {kind} covers the shot"
        assert "shake" not in picture["animation"], "only camera layers are shaken by the renderer"
        first, middle, late, last = (_seen(picture, _pose(layer, t)) for t in (0.0, 0.5, 0.9, 1.0))
        moved = [abs(a - b) for a, b in zip(first, last)]
        if camera == "camera-locked":
            assert moved == [0, 0, 0] and "shake" not in layer["animation"]
            continue
        assert late != last, f"{camera} on a {kind} still moves just before the cut"
        assert max(moved) > 0.05, f"{camera} on a {kind} moves"
        x0, y0, zoom0 = first
        x1, y1, zoom1 = last
        if camera == "camera-push-in":
            assert zoom1 > zoom0 * 1.4 and abs(x1 - x0) < 1e-6
        elif camera in ("camera-pull-out", "camera-dolly"):
            assert zoom1 < zoom0 / 1.3
        elif camera == "camera-pan-right":
            assert x1 - x0 > 15 and abs(zoom1 - zoom0) < 1e-6
        elif camera == "camera-pan-left":
            assert x0 - x1 > 15
        elif camera == "camera-crane-up":
            assert y0 - y1 > 15, "the view rises"
        elif camera == "camera-whip-pan":
            assert x1 - x0 > 20 and middle[0] - x0 < (x1 - x0) / 2, "an accelerating pan to the right"
        elif camera == "camera-dutch-drift":
            assert layer["animation"]["start"]["rotation"] < 0 < layer["animation"]["end"]["rotation"]
        if camera in ("camera-handheld", "camera-whip-pan"):
            assert layer["animation"]["shake"]["amount"] > 0, f"{camera} shakes the picture"


@pytest.mark.parametrize("camera", [None, *CAMERAS])
def test_no_camera_shows_an_edge_of_the_picture(tmp_path, camera):
    docs = [_document(tmp_path, _still(camera)), _document(tmp_path, _still(camera, focus={"x": 72, "y": 35}, zoom=[1.0, 1.2])),
            _clip(tmp_path, camera)]
    for doc in docs:
        picture, layer = _layers(doc)
        worst = min(_edge_margin(picture, view) for step in range(101)
                    for view in _shaken(_pose(layer, step / 100), layer["animation"].get("shake")))
        assert worst > -0.5, f"{camera}: an edge shows by {-worst:.1f} px"


def test_a_pan_needs_a_bigger_picture_and_a_locked_clip_keeps_its_size(tmp_path):
    pan, _ = _layers(_clip(tmp_path, "camera-pan-right"))
    locked, _ = _layers(_clip(tmp_path, None))
    assert pan["animation"]["start"]["scale"] == pytest.approx(1.3, abs=0.002)
    assert locked["animation"]["start"]["scale"] == 1


def test_a_still_keeps_its_zoom_and_its_focus(tmp_path):
    picture, layer = _layers(_document(tmp_path, _still()))
    assert layer["name"] == "zoom" and layer["animation"]["duration"] == DURATION
    assert (layer["animation"]["start"]["scale"], layer["animation"]["end"]["scale"]) == (1.0, 1.1)
    picture, layer = _layers(_document(tmp_path, _still(focus={"x": 70, "y": 40}, zoom=[1.15, 1.3])))
    for t in (0.0, 0.5, 1.0):
        x, y, _zoom = _seen(picture, _pose(layer, t))
        assert (round(x, 6), round(y, 6)) == (70, 40), "the focus point stays centred while the camera zooms"
    picture, layer = _layers(_document(tmp_path, _still("camera-pan-right", zoom=[1.2, 1.35])))
    assert (layer["animation"]["start"]["scale"], layer["animation"]["end"]["scale"]) == (1.2, 1.35)
    assert _seen(picture, _pose(layer, 1))[0] > _seen(picture, _pose(layer, 0))[0] + 10


def test_cover_scale_is_one_without_movement_and_grows_with_the_pan():
    still = {"x": 50, "y": 50, "scale": 1, "rotation": 0}
    assert cover_scale(still, still) == 1
    assert cover_scale(still, {**still, "x": 70}) == pytest.approx(1.4, abs=0.002)
    assert cover_scale(still, still, {"amount": 1, "frequency": 3}) > 1


def test_a_camera_layer_has_no_source_and_a_picture_layer_needs_one():
    doc = {"version": 1, "name": "s", "width": 1920, "height": 1080, "fps": 24, "duration": 4, "layers": [], "texts": []}
    made = edit({"version": 1, "input": {"document": doc, "operations": [
        {"op": "add_layer", "id": "cam", "type": "camera", "preset": "camera-handheld"}], "full": True}})["result"]["document"]
    assert made["layers"][0]["type"] == "camera" and made["layers"][0]["source"] == ""
    assert made["layers"][0]["animation"]["shake"]["amount"] == 0.75
    for operation in ({"op": "add_layer", "id": "cam", "type": "camera", "source": "/examples/hero.png"},
                      {"op": "add_layer", "id": "pic", "type": "image"}):
        with pytest.raises(Video2dEditError) as error:
            edit({"version": 1, "input": {"document": doc, "operations": [operation]}})
        assert error.value.code == "invalid_input"


def test_an_unknown_camera_in_a_resumed_spec_fails_with_its_name(tmp_path):
    with pytest.raises(Video2dEditError) as error:
        _document(tmp_path, _still("camera-orbit"))
    assert error.value.code == "unknown_camera" and "camera-orbit" in str(error.value)


def test_an_unknown_camera_is_refused_before_any_gpu_work():
    spec = {"song": {"duration": 20}, "shots": [
        {"key": "a", "kind": "h3", "t0": 0, "camera": "camera-orbit"},
        {"key": "b", "kind": "clip", "t0": 5, "clip": "a", "camera": "camera-pan-right"},
        {"key": "c", "kind": "clip", "t0": 10, "clip": "a", "overrides": {"camera": "slow push"}}],
        "fill": [{"kind": "still", "still": "k", "camera": "pan"}]}
    problem = next(item for item in blocking_problems(spec) if item["code"] == "unknown_camera")
    assert problem["shots"] == ["a", "c", "fill[0]"]
    assert problem["cameras"] == ["camera-orbit", "pan", "slow push"]
    assert "camera-pan-right" in problem["hint"]
    with pytest.raises(HTTPException) as refused:
        refuse_thin_plan(spec, None)
    message = refused.value.detail["message"]
    assert refused.value.status_code == 422 and problem["uses"][1] == {"shot": "c", "camera": "slow push"}
    assert 'Shot "a" asks for the camera "camera-orbit"; shot "c" asks for the camera "slow push"; shot "fill[0]" asks for the camera "pan"' in message
    fine = {**spec, "shots": spec["shots"][1:2], "fill": []}
    assert not [item for item in blocking_problems(fine) if item["code"] == "unknown_camera"]
