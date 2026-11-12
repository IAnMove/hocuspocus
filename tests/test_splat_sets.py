"""Gaussian-splat sets: a workspace .ply/.spz, and a closed door for FlashWorld.

image and prompt are the generator shape. The weights are CC-BY-NC-SA-4.0, so
they fail before any picture job. A file needs no GPU and no optional component.
"""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.mcp_profiles import SERIES_TOOLS
from services.production_models import ModelError, check_sets, make_models
from services.production_scene3d import compile_document, resolve_media, validate_scene3d_shot
from services.production_splat import LICENCE
from services.set_commands import command_catalog
from services.splat_commands import APPLY, command_handlers, run
from services.world3d_export import MEDIA_KINDS

# The compiler test needs the UI's tsx loader (python-b installs it).
NODE = pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "ui/node_modules/tsx/dist/loader.mjs").is_file(),
    reason="UI dependencies not installed in Python-only CI",
)
SCENE = "w3d-splat0000001"


def ply(path: Path) -> None:
    """One vertex. The export still needs a rebuilt renderer; this file is the fixture."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "ply\nformat ascii 1.0\nelement vertex 1\nproperty float x\nproperty float y\nproperty float z\nend_header\n0 0 0\n",
        encoding="utf-8",
    )


class Production:
    ws = "w"

    def __init__(self, root):
        self.root, self.images, self.saves = root, [], 0
        self.state = {}

    def save(self):
        self.saves += 1

    def log(self, line):
        self.state.setdefault("log", []).append(line)

    def image(self, key, prompt, refs, res, seed, model=None, steps=None, attempt=0):
        self.images.append(key)
        return f"job-{key}"

    def wait(self, jobs):
        names = {}
        for name in jobs:
            (self.root / f"{name}.png").write_bytes(b"png")
            names[name] = f"{name}.png"
        return names

    def upload(self, name):
        return str(self.root / name), f"/api/v1/uploads/{name}"

    def _attempt(self, group, key):
        return 0


def test_a_splat_set_needs_one_workspace_file_and_a_floor():
    check_sets({"sets": {"hall": {"kind": "splat", "file": "sets/hall.ply", "floorY": 0.4, "scale": 2}}})
    check_sets({"sets": {"plaza": {"kind": "diorama", "prompt": "a plaza", "ground": "cobbles", "sky": "noon",
                                    "houses": ["a cafe", "a shop"]}}})
    bad = (
        {"kind": "splat", "file": "sets/hall.ply", "prompt": "a room"},
        {"kind": "splat", "file": "sets/hall.png"},
        {"kind": "splat", "file": "/tmp/hall.ply"},
        {"kind": "splat", "file": "sets/../hall.ply"},
        {"kind": "splat", "image": "  "},
        {"kind": "splat", "file": "sets/hall.ply", "floorY": 80},
        {"kind": "splat", "file": "sets/hall.ply", "scale": 0.01},
        {"kind": "splat", "file": "sets/hall.ply", "colour": "red"},
        {"kind": "splat"},
    )
    for entry in bad:
        with pytest.raises(ModelError):
            check_sets({"sets": {"hall": entry}})


def test_a_file_is_a_url_and_image_or_prompt_never_draws(tmp_path):
    root = tmp_path / "w"
    ply(root / "sets" / "hall.ply")
    production = Production(root)
    make_models(production, {"sets": {"hall": {"kind": "splat", "file": "sets/hall.ply", "floorY": 0.4, "scale": 2}}},
                sleep=lambda _: None)
    record = production.state["sets"]["hall"]
    assert record["url"] == "/api/v1/file/sets/hall.ply?workspace=w"
    assert record["floorY"] == 0.4 and record["scale"] == 2 and "error" not in record
    assert production.images == [] and production.saves == 1
    make_models(production, {"sets": {"hall": {"kind": "splat", "file": "sets/hall.ply", "floorY": 0.4, "scale": 2}}},
                sleep=lambda _: None)
    assert production.saves == 1, "a built file is not asked for again"

    painted = Production(root)
    make_models(painted, {"sets": {"fair": {"prompt": "a painted fair"}}}, sleep=lambda _: None)
    assert painted.images == ["set-fair"] and painted.state["sets"]["fair"]["url"].endswith("set:fair.png")

    for entry in ({"kind": "splat", "image": "plate.png"}, {"kind": "splat", "prompt": "a stone kitchen"}):
        refused = Production(root)
        with pytest.raises(ModelError, match="CC-BY-NC-SA-4.0") as caught:
            make_models(refused, {"sets": {"hall": entry}}, sleep=lambda _: None)
        assert LICENCE in str(caught.value)
        assert refused.images == [] and refused.state["sets"]["hall"]["error"] == LICENCE


def test_a_missing_file_fails_and_a_named_set_resolves_without_a_plate(tmp_path):
    production = Production(tmp_path)
    with pytest.raises(ModelError, match="inside the workspace"):
        make_models(production, {"sets": {"hall": {"kind": "splat", "file": "sets/missing.ply"}}}, sleep=lambda _: None)
    assert production.images == []
    sets = {"hall": {"kind": "splat", "url": "/api/v1/file/sets/hall.ply?workspace=w", "floorY": 0.25, "scale": 3, "error": None}}
    # error None is falsy; a real built record has no error key. Keep the url path.
    sets["hall"].pop("error")
    shot = {"template": "product-orbit", "subject": "/api/v1/file/hero.glb?workspace=w", "background": "hall"}
    resolved = resolve_media(shot, stills={}, root=tmp_path, workspace="w", sets=sets)
    assert resolved["background"] == {"source": sets["hall"]["url"], "splat": True, "floorY": 0.25, "scale": 3.0}
    broken = {"hall": {"kind": "splat", "error": LICENCE}}
    with pytest.raises(ValueError, match="CC-BY-NC-SA-4.0"):
        resolve_media(shot, stills={}, root=tmp_path, workspace="w", sets=broken)
    config = {"template": "product-orbit", "subject": "/api/v1/file/hero.glb?workspace=w",
              "background": {"source": "/api/v1/file/sets/hall.ply?workspace=w", "splat": True, "floorY": 0.4}}
    validate_scene3d_shot({"key": "hero", "kind": "scene3d", "scene3d": config})
    with pytest.raises(ValueError, match="splat: true"):
        validate_scene3d_shot({"key": "hero", "kind": "scene3d", "scene3d": {**config, "background": {**config["background"], "splat": "yes"}}})
    with pytest.raises(ValueError, match="splat: true"):
        resolve_media({**shot, "background": {"source": "/api/v1/file/a.ply?workspace=w", "splat": "yes"}},
                      stills={}, root=tmp_path, workspace="w")


def _workspace(tmp_path):
    root = tmp_path / "studio"
    ply(root / "sets" / "hall.ply")
    document = {
        "version": 1, "units": "meters", "up": "y", "duration": 6, "width": 1280, "height": 720, "fps": 24,
        "templateId": "product-orbit",
        "slots": [
            {"id": "subject_1", "slot": "subject_1", "media": "model3d", "sourceUrl": "/api/v1/file/hero.glb?workspace=studio",
             "position": [0, 0, 0], "rotationY": 0, "scale": 1, "clip": None},
            {"id": "flyer", "slot": "prop", "media": "model3d", "sourceUrl": "/api/v1/file/bird.glb?workspace=studio",
             "position": [1, 2, 0], "rotationY": 0, "scale": 1, "clip": None},
            {"id": "hover", "slot": "prop", "media": "model3d", "sourceUrl": "/api/v1/file/ufo.glb?workspace=studio",
             "position": [0, 0, 1], "rotationY": 0, "scale": 1, "clip": None, "grounded": False},
        ],
        "camera": {"family": "product", "fov": 40, "orbitRadius": 3.6, "orbitHeight": 0.35, "orbitTurns": 0.65},
    }
    folder = root / "world3d-edits"
    folder.mkdir(parents=True)
    (folder / f"{SCENE}.json").write_text(json.dumps({"revision": 1, "templateId": "product-orbit", "document": document}),
                                          encoding="utf-8")
    return lambda name: str(tmp_path / name)


def _apply(workspace, **extra):
    intent = extra.pop("intent_id", "intent-splat-1")
    data = {"workspace": "studio", "name": "hall", "file": "sets/hall.ply", "floorY": 0.4, "scale": 2, "scene_id": SCENE}
    data.update(extra)
    return run(APPLY, {"version": 1, "intent_id": intent, "input": data}, workspace)


def test_apply_stores_the_file_lifts_the_cast_and_replays(tmp_path):
    workspace = _workspace(tmp_path)
    first = _apply(workspace)
    result = first["result"]
    assert result["url"].endswith("sets/hall.ply?workspace=studio") and result["floorY"] == 0.4
    stored = json.loads((tmp_path / "studio" / "splat-sets.json").read_text(encoding="utf-8"))
    assert stored["sets"]["hall"]["kind"] == "splat" and stored["sets"]["hall"]["file"] == "sets/hall.ply"
    scene = json.loads((tmp_path / "studio" / "world3d-edits" / f"{SCENE}.json").read_text(encoding="utf-8"))
    slots = {slot["id"]: slot for slot in scene["document"]["slots"]}
    assert slots["subject_1"]["position"][1] == 0.4 and slots["subject_1"]["grounded"] is True
    assert slots["flyer"]["position"][1] == 2 and "grounded" not in slots["flyer"]
    assert slots["hover"]["grounded"] is False and slots["hover"]["position"][1] == 0
    splat = slots["set-hall"]
    assert splat["media"] == "splat" and splat["splat"] == {"floorY": 0.4} and splat["scale"] == 2
    assert splat["sourceUrl"] == result["url"] and splat["position"] == [0, 0.4, 0]
    assert scene["revision"] == 2
    again = _apply(workspace)
    assert again["result"] == result
    assert json.loads((tmp_path / "studio" / "world3d-edits" / f"{SCENE}.json").read_text(encoding="utf-8"))["revision"] == 2
    with pytest.raises(HTTPException) as conflict:
        _apply(workspace, floorY=1, intent_id="intent-splat-1")
    assert conflict.value.status_code == 409
    with pytest.raises(HTTPException) as refused:
        _apply(workspace, file=None, prompt="a stone kitchen", intent_id="intent-splat-2")
    assert refused.value.status_code == 422 and "CC-BY-NC-SA-4.0" in str(refused.value.detail)
    assert not (tmp_path / "studio" / "splat-sets.json").read_text(encoding="utf-8").count("stone kitchen")


def test_mcp_and_rest_share_the_operation(tmp_path, monkeypatch):
    assert command_catalog()[0]["name"] == "scene3d.sets.catalog"
    assert APPLY in {item["name"] for item in command_catalog()}
    assert APPLY in SERIES_TOOLS
    assert "splat" in MEDIA_KINDS
    root = _workspace(tmp_path)
    body = {"version": 1, "intent_id": "intent-splat-rest",
            "input": {"workspace": "studio", "file": "sets/hall.ply", "floorY": 0}}
    import asyncio
    got = asyncio.run(command_handlers(root)[APPLY](body))
    assert got["operation"] == APPLY and got["result"]["file"] == "sets/hall.ply"

    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.set_catalog import create_set_catalog_router
    import services.core_workspace as workspaces
    monkeypatch.setattr(workspaces, "workspace_dir", root)
    app = FastAPI()
    app.include_router(create_set_catalog_router())
    response = TestClient(app).post("/api/v1/scene3d/rooms/commands", json={
        "version": 1, "operation": APPLY, "intent_id": "intent-splat-http",
        "input": {"workspace": "studio", "name": "hall", "file": "sets/hall.ply"},
    })
    assert response.status_code == 200
    assert response.json()["result"]["url"].endswith("sets/hall.ply?workspace=studio")
    blocked = TestClient(app).post("/api/v1/scene3d/rooms/commands", json={
        "version": 1, "operation": APPLY, "intent_id": "intent-splat-http-2",
        "input": {"workspace": "studio", "image": "plates/kitchen.png"},
    })
    assert blocked.status_code == 422 and "CC-BY-NC-SA-4.0" in blocked.text


@NODE
def test_the_compiler_stands_the_subject_on_the_splat_floor_and_keeps_the_orbit():
    background = {"source": "/api/v1/file/sets/hall.ply?workspace=test", "splat": True, "floorY": 0.4, "scale": 2}
    document = compile_document({"key": "hero", "kind": "scene3d", "scene3d": {
        "template": "product-orbit", "subject": "/api/v1/file/hero.glb?workspace=test", "background": background}}, 6)
    slots = {slot["id"]: slot for slot in document["slots"]}
    assert slots["subject_1"]["position"][1] == 0.4 and slots["subject_1"]["grounded"] is True
    assert slots["set-splat"]["media"] == "splat" and slots["set-splat"]["splat"] == {"floorY": 0.4}
    assert slots["set-splat"]["sourceUrl"].endswith("hall.ply?workspace=test") and slots["set-splat"]["scale"] == 2
    assert document["dressing"] == "none" and document["environment"]["floorStyle"] == "none"
    assert abs(document["camera"].get("orbitTurns", 0)) > 0.5, "a splat keeps the template orbit; a painted plate would clamp it"
