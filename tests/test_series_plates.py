"""A Video 3D scene becomes the looping 2D background plate of a series location."""
from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_plates import create_series_plates_router
from services.series_plates import PlateDeps, PlateError, SeriesPlates, plate_document
from services.series_shot_plan import background_for

SCENE = {"duration": 12, "camera": {}, "soundtrack": [{"id": "music"}], "sfx": [{"id": "boom"}], "texts": [{"text": "TITLE"}],
         "slots": [{"id": "bot", "media": "model3d", "speech": {"enabled": True, "clips": [{"id": "c1", "audio": {"url": "/a.wav"}}]}}]}


class Tools:
    def __init__(self):
        self.calls, self.receipts = [], []

    def __call__(self, tool, arguments):
        self.calls.append((tool, copy.deepcopy(arguments)))
        if tool == "scenes.world3d.export":
            return {"receipt": {"commandId": arguments["intent_id"], "status": "queued"}}
        if tool == "scenes.world3d.export.receipt":
            return self.receipts.pop(0)
        if tool == "series.asset.import":
            return {"result": {"asset": {"id": "asset-plate-1"}, "revision": 9}}
        raise AssertionError(tool)


def setup():
    store = {"series": {"id": "uv", "assets": [], "locations": [{"id": "lab", "name": "Lab", "layout2d": {"homes": {"kevin": 30}}}]}}

    def change(workspace, series_id, apply):
        if series_id != "uv":
            raise KeyError(series_id)
        apply(store["series"])
        return copy.deepcopy(store["series"])

    def read(workspace, series_id):
        if series_id != "uv":
            raise KeyError(series_id)
        return copy.deepcopy(store["series"])

    tools = Tools()
    scenes = {"lab-orbit.scene.json": SCENE}
    service = SeriesPlates(PlateDeps(call=tools, read_series=read, change_series=change,
                                     read_scene=lambda workspace, name: scenes[name], now=lambda: "2026-10-04T10:00:00+00:00"))
    return service, tools, store


def test_a_plate_is_silent_without_text_and_loop_length():
    plate = plate_document(SCENE, 40)
    assert plate["duration"] == 20 and not {"soundtrack", "sfx", "texts"} & set(plate)
    assert plate["slots"][0]["speech"]["audible"] is False and plate["slots"][0]["speech"]["clips"][0]["audible"] is False
    assert SCENE["slots"][0]["speech"].get("audible") is None, "the scene itself is not touched"
    assert plate_document(SCENE, 0.5)["duration"] == 2
    with pytest.raises(PlateError):
        plate_document({"camera": {}}, 6)


def test_start_waits_imports_and_sets_the_location_plate():
    service, tools, store = setup()
    started = service.start("cast", "uv", "lab", scene="lab-orbit.scene.json", seconds=8)
    assert started["status"] == "rendering" and started["seconds"] == 8 and started["intent"].startswith("plate-uv-lab-")
    tool, exported = tools.calls[0]
    assert tool == "scenes.world3d.export" and exported["input"]["document"]["duration"] == 8 and exported["input"]["quality"] == "draft"
    assert store["series"]["locations"][0]["layout2d"]["homes"] == {"kevin": 30}, "the rest of the 2D layout stays"
    tools.receipts.append({"receipt": {"status": "running"}, "task": {"status": "running", "progress": 0.4}})
    waiting = service.status("cast", "uv", "lab")
    assert waiting["status"] == "rendering" and waiting["progress"] == 0.4
    tools.receipts.append({"result": {"receipt": {"artifacts": [{"name": "world3d-lab.mp4"}]}, "task": {"status": "completed"}}})
    done = service.status("cast", "uv", "lab")
    assert done["status"] == "done" and done["assetId"] == "asset-plate-1" and done["file"] == "world3d-lab.mp4"
    imported = next(args["input"] for tool, args in tools.calls if tool == "series.asset.import")
    assert imported["owner_type"] == "location" and imported["owner_id"] == "lab" and imported["kind"] == "video"
    assert imported["metadata"]["loop"] is True and imported["reference_role"] == "plate3d"
    assert store["series"]["locations"][0]["layout2d"]["plateAssetId"] == "asset-plate-1"
    calls = len(tools.calls)
    assert service.status("cast", "uv", "lab")["status"] == "done" and len(tools.calls) == calls, "a finished plate is not polled again"


def test_the_2d_shot_uses_the_plate_as_a_looping_video_background():
    series = {"id": "uv", "assets": {"asset-plate-1": {"id": "asset-plate-1", "kind": "video", "uri": "assets/uv/plate.mp4"},
                                     "asset-still": {"id": "asset-still", "kind": "image", "uri": "assets/uv/lab.png"}},
              "locations": [{"id": "lab", "layout2d": {"plateAssetId": "asset-plate-1"}, "referenceAssetIds": ["asset-still"]}]}
    background = background_for(series, {"locationId": "lab"}, "cast")
    assert background["kind"] == "video" and "plate.mp4" in background["source"]


def test_a_lost_export_fails_and_bad_requests_are_refused():
    service, tools, store = setup()
    service.start("cast", "uv", "lab", document=SCENE)
    tools.receipts.append({"_is_error": True, "error": {"code": "receipt_not_found", "message": "gone", "status": 404}})
    failed = service.status("cast", "uv", "lab")
    assert failed["status"] == "failed" and failed["error"] == "gone"
    assert "plateAssetId" not in store["series"]["locations"][0]["layout2d"]
    for kwargs, code in (({}, "scene_required"), ({"scene": "x", "document": SCENE}, "scene_required"),
                         ({"scene": "missing.scene.json"}, "scene_not_found"), ({"document": SCENE, "quality": "ultra"}, "invalid_quality")):
        with pytest.raises(PlateError) as error:
            service.start("cast", "uv", "lab", **kwargs)
        assert error.value.code == code
    with pytest.raises(PlateError) as missing:
        service.start("cast", "uv", "attic", document=SCENE)
    assert missing.value.status == 404
    assert service.status("cast", "uv", "lab")["status"] == "failed"


def test_the_router_starts_and_reports_a_plate():
    service, tools, _store = setup()
    app = FastAPI()
    app.include_router(create_series_plates_router(service, lambda _loop: None))
    client = TestClient(app)
    path = "/api/v1/series/uv/locations/lab/plate3d"
    started = client.post(path, json={"workspace": "cast", "scene": "lab-orbit.scene.json"})
    assert started.status_code == 200, started.text
    tools.receipts.append({"receipt": {}, "task": {"status": "queued"}})
    assert client.get(path, params={"workspace": "cast"}).json()["status"] == "rendering"
    refused = client.post(path, json={"workspace": "cast"})
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "scene_required"
    assert client.post("/api/v1/series/nope/locations/lab/plate3d", json={"workspace": "cast", "document": SCENE}).status_code == 404
