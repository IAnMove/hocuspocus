"""CC0 furniture: the manifest, the kind map, the footprint fit, and the box fallback."""
import hashlib
import io
import json
import struct
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.cc0_props import (
    NOT_INSTALLED, PACK, PropManifestError, choice_of, collection_fragment, dress_room, fit_block,
    furniture_objects, library_item, list_library, load_manifest, model_for, pack_ready, placements,
    validate_manifest,
)
from services.scene3d_items import ItemService, change_items
from services.world3d_stage_documents import stage_document

ROOT = Path(__file__).resolve().parents[1]
BASE = {"duration": 4, "slots": [
    {"id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "media": "model3d"},
    {"id": "subject_2", "slot": "subject_2", "position": [1, 0, 0], "rotationY": 0, "media": "model3d"},
]}


def _tiny_glb() -> bytes:
    payload = json.dumps({"asset": {"version": "2.0"}}).encode()
    payload += b" " * ((4 - len(payload) % 4) % 4)
    chunk = struct.pack("<I", len(payload)) + b"JSON" + payload
    return struct.pack("<III", 0x46546C67, 2, 12 + len(chunk)) + chunk


def _model(ident="chair", kind="chair", front="+z", size=None, centre=None):
    return {
        "id": ident, "kind": kind, "sha256": "a" * 64, "front": front,
        "size_m": size or {"x": 1.0, "y": 0.5, "z": 0.5},
        "center_m": centre or {"x": 0.5, "y": 0.25, "z": -0.25},
    }


def test_the_manifest_is_cc0_and_covers_the_mold_kinds():
    data = load_manifest()
    assert data["licence"] == "CC0-1.0" and data["pack"] == PACK and len(data["models"]) <= 40
    assert data["licence_url"].startswith("https://creativecommons.org/publicdomain/zero/")
    ids = {model["id"] for model in data["models"]}
    assert {"sofa", "armchair", "chair", "table", "desk", "bed", "wardrobe", "shelf", "bar-counter",
            "kitchen-counter", "stove", "fridge", "lamp", "plant", "tv", "bench", "cabinet", "rug"} <= ids
    chair = next(model for model in data["models"] if model["id"] == "chair")
    assert chair["size_m"]["y"] == pytest.approx(0.9, abs=1e-3)
    assert sum(model["bytes"] for model in data["models"]) == 296956


def test_a_bad_licence_or_hash_is_rejected():
    data = load_manifest()
    broken = json.loads(json.dumps(data))
    broken["models"][0]["licence"] = "CC-BY-4.0"
    with pytest.raises(PropManifestError, match="CC0-1.0"):
        validate_manifest(broken)
    broken = json.loads(json.dumps(data))
    broken["models"][0]["sha256"] = "nope"
    with pytest.raises(PropManifestError, match="sha256"):
        validate_manifest(broken)


def test_kind_mapping_picks_the_model_and_leaves_unknown_kinds():
    models = {row["id"]: row for row in load_manifest()["models"]}
    assert model_for("bedside", models=models)["id"] == "nightstand"
    assert model_for("coffee", models=models)["id"] == "coffee"
    assert model_for("wardrobe", models=models)["file"].endswith("bookcaseClosedDoors.glb")
    for kind in ("seat", "dashboard", "curtain", "bottles", "workstation", "rock", "fountain"):
        assert model_for(kind, models=models) is None


def test_a_counter_follows_the_mold():
    models = {row["id"]: row for row in load_manifest()["models"]}
    assert model_for("counter", "counter", "bar", models)["id"] == "bar-counter"
    assert model_for("counter", "counter_back", "cocina", models)["id"] == "kitchen-counter"
    assert model_for("counter", "mostrador", "sala", models)["id"] == "bar-counter"


def test_footprint_fit_keeps_aspect_on_the_floor_facing_the_block():
    model = _model()
    fitted = fit_block(model, [4.0, 0.2, -1.0, 2.0, 0.9, 1.0])
    assert fitted["stretch"] == pytest.approx(2.0)
    assert fitted["scale"] == pytest.approx(2.0 * 0.5 / 1.7)
    assert fitted["rotationY"] == 0.0
    # Centre (0.5, -0.25) * stretch 2 sits on the block centre; y stays the block bottom.
    assert fitted["position"] == pytest.approx([4.0 - 1.0, 0.2, -1.0 - (-0.5)])


def test_a_sideways_front_swaps_the_footprint():
    model = _model(front="+x", size={"x": 1.0, "y": 0.4, "z": 0.4}, centre={"x": 0.5, "y": 0.2, "z": -0.2})
    fitted = fit_block(model, [0.0, 0.0, 0.0, 0.8, 1.0, 2.0])
    assert fitted["stretch"] == pytest.approx(2.0)
    assert fitted["rotationY"] == pytest.approx(-1.5707963267948966)
    # yaw -π/2 turns local +x onto world +z. Offset of centre*stretch is (0.4, 1.0).
    assert fitted["position"][0] == pytest.approx(-0.4)
    assert fitted["position"][2] == pytest.approx(-1.0)
    assert fitted["position"][1] == 0.0


def test_an_uninstalled_pack_leaves_the_stage_as_boxes():
    assert pack_ready() is False
    document = stage_document("stage-salon", BASE)
    assert "libraryBlocks" not in document["room"]
    assert document["room"].keys() == {"mold", "skin", "camera"}
    assert [slot["id"] for slot in document["slots"]] == ["subject_1", "subject_2"]
    assert "furnitureWarning" not in document


def test_library_mode_replaces_a_known_block_when_ready():
    model = _model()
    mold = {"id": "sala", "blocks": [
        {"id": "chair_a", "kind": "chair", "box": [1, 0, 2, 2, 0.9, 1]},
        {"id": "rock", "kind": "rock", "box": [0, 0, 0, 1, 1, 1]},
    ]}
    document = {"slots": list(BASE["slots"]), "room": {"mold": mold, "skin": {}, "camera": "two_shot"}}
    dress_room(document, ready=True, models={"chair": model})
    assert document["room"]["libraryBlocks"] == ["chair_a"]
    added = document["slots"][-1]
    assert added["id"] == "furniture-chair_a" and added["slot"] == "prop" and added["grounded"] is True
    assert added["sourceUrl"].endswith(".glb")
    assert added["scale"] == pytest.approx(fit_block(model, mold["blocks"][0]["box"])["scale"])
    assert added["position"] == pytest.approx(fit_block(model, mold["blocks"][0]["box"])["position"])


def test_box_mode_and_a_missing_pack_do_not_replace():
    model = _model()
    mold = {"id": "sala", "blocks": [{"id": "chair_a", "kind": "chair", "box": [0, 0, 0, 1, 1, 1]}]}
    boxed = {"slots": [], "room": {"mold": mold, "furniture": "box"}}
    dress_room(boxed, ready=True, models={"chair": model})
    assert "libraryBlocks" not in boxed["room"] and boxed["slots"] == []
    missing = {"slots": [], "room": {"mold": mold, "furniture": "library"}}
    dress_room(missing, ready=False, models={"chair": model})
    assert "libraryBlocks" not in missing["room"] and missing["furnitureWarning"] == NOT_INSTALLED
    with pytest.raises(ValueError, match="library or box"):
        choice_of("cubes")


def test_overflow_past_the_cap_stays_a_box():
    model = _model()
    blocks = [{"id": f"chair_{index}", "kind": "chair", "box": [0, 0, 0, 1, 1, 1]} for index in range(4)]
    placed = placements({"id": "aula", "blocks": blocks}, models={"chair": model}, limit=2, taken=0)
    assert [row["block_id"] for row in placed] == ["chair_0", "chair_1"]
    rows, replaced, warning = furniture_objects(
        {"id": "aula", "blocks": blocks}, ready=True, models={"chair": model}, limit=2, file_of=lambda item: "cc0/chair.glb")
    assert warning is None and replaced == ["chair_0", "chair_1"] and rows[0]["file"] == "cc0/chair.glb"
    assert rows[0]["add"] is True and rows[0]["grounded"] is True


def test_props_list_pack_cc0_works_before_install():
    from services.prop_commands import PropService
    service = PropService(lambda name: "/tmp/cc0-props-workspace", lambda: "/tmp", lambda *args, **kwargs: None)
    listed = service.execute("props.list", {"version": 1, "input": {"workspace": "studio", "pack": "cc0"}})
    result = listed["result"]
    assert result["installed"] is False and result["licence"] == "CC0-1.0"
    assert any(row["id"] == "sofa" and row["installed"] is False for row in result["props"])
    queried = list_library("sofá")
    assert [row["id"] for row in queried["props"]] == ["sofa"]
    with pytest.raises(HTTPException, match="unknown prop pack"):
        service.execute("props.list", {"version": 1, "input": {"workspace": "studio", "pack": "nope"}})


def test_a_library_item_refuses_until_the_pack_is_installed(tmp_path):
    service = ItemService(lambda name: str(tmp_path), lambda: str(tmp_path), lambda *args, **kwargs: None)
    with pytest.raises(ValueError, match="not installed"):
        service._item({"workspace": "studio", "item": {"library": "sofa"}})
    with pytest.raises(ValueError, match="not installed"):
        library_item("sofa", tmp_path)
    rows, _warnings = change_items([], "add", {"at": {"position": [1, 0, 2]}},
                                    {"file": "cc0/chair.glb", "heightM": 0.9, "media": "model3d", "name": "chair"})
    assert rows[0]["position"] == [1, 0, 2] and rows[0]["grounded"] is True
    assert rows[0]["scale"] == pytest.approx(0.9 / 1.7)


def test_file_mode_install_checks_each_glb(tmp_path):
    from services.asset_library import AssetLibrary
    from services.example_collections import install_collection
    body = _tiny_glb()
    digest = hashlib.sha256(body).hexdigest()
    name = "cc0-furniture/chair.glb"
    url = "https://raw.githubusercontent.com/shorepine/kenney/3694c6879e487c108f55677be7dd2ca75b07cc3b/3d/furniture/chair.glb"
    files = {name: {
        "kind": "model3d", "size": len(body), "sha256": digest, "collection": "sample", "license": "CC0-1.0",
        "source": "Kenney Furniture Kit", "source_url": "https://kenney.nl/assets/furniture-kit",
        "author": "Kenney", "retrieved_at": "2026-10-24", "url": url,
    }}
    line = hashlib.sha256(f"{name}:{digest}\n".encode()).hexdigest()
    manifest = {"schema": "hocuspocus.asset-library", "revision": 1, "files": files, "collections": {
        "sample": {"title": "Sample", "files": [name], "dependencies": [], "size": len(body), "digest": line}}}
    library = AssetLibrary(tmp_path, manifest)
    opened = []

    def opener(target, timeout=30):
        opened.append(target)
        return io.BytesIO(body)

    install_collection(library, "sample", lambda: False, lambda count: None, opener)
    assert opened == [url] and library.installed("sample") is True
    assert library.resolve(name).read_bytes() == body
    served = library.key(name)
    assert served == digest + ".glb"


def test_the_merged_catalog_validates_and_is_not_installed():
    from services.asset_library import asset_library
    files, collections = collection_fragment()
    assert set(files) == set(collections[PACK]["files"])
    assert PACK in asset_library.collections
    assert asset_library.installed(PACK) is False
    assert asset_library.collections[PACK]["digest"] == collections[PACK]["digest"]
    assert "archive" not in asset_library.collections[PACK]


def _library_bytes(tmp_path, monkeypatch):
    """One installed library GLB, addressed by its real SHA-256."""
    from services.asset_library import asset_library
    body = _tiny_glb()
    digest = hashlib.sha256(body).hexdigest()
    key = digest + ".glb"
    source = tmp_path / "library" / key
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(body)
    library = asset_library
    real_for, real_resolve = library.file_for, library.resolve

    def file_for(asked):
        return "cc0-test" if asked == key else real_for(asked)

    def resolve(name):
        return source if name == "cc0-test" else real_resolve(name)

    monkeypatch.setattr(library, "file_for", file_for)
    monkeypatch.setattr(library, "resolve", resolve)
    return body, digest, key


def _furniture_table(digest):
    table = {}
    for ident in ("sofa", "coffee", "tv", "chair"):
        table[ident] = _model(ident, ident)
        table[ident]["sha256"] = digest
        table[ident]["bytes"] = 1
        table[ident]["file"] = "cc0-furniture/chair.glb"
    return table


def _export_service(tmp_path):
    from services.task_manager import TaskRegistry
    from services.world3d_export import World3DExportService

    def workspace_dir(name):
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def registry_for(name):
        return TaskRegistry(workspace_dir(name), interrupt_stale=False)

    service = World3DExportService(
        workspace_dir=workspace_dir, registry_for=registry_for, renderer=lambda *args: [],
        uploads_dir=lambda: str(tmp_path / "uploads"),
    )
    return service, workspace_dir


def _export_command(document, intent_id, workspace="studio"):
    from services.world3d_export import OPERATION
    return {"version": 1, "operation": OPERATION, "intent_id": intent_id,
            "input": {"workspace": workspace, "document": document, "refs": []}}


def test_an_instantiated_stage_copies_furniture_and_exports(tmp_path, monkeypatch):
    """A dressed stage-salon stores workspace GLBs, once, and the export check finds them."""
    from services import world3d_scenes
    from services.task_manager import forget_task_registry
    from services.world3d_template_commands import execute_command
    body, digest, key = _library_bytes(tmp_path, monkeypatch)
    monkeypatch.setattr("services.cc0_props.pack_ready", lambda: True)
    monkeypatch.setattr("services.cc0_props.models_by_id", lambda manifest=None: _furniture_table(digest))
    world3d_scenes._COMPILED.pop("stage-salon", None)
    service, workspace_dir = _export_service(tmp_path)
    try:
        scene = world3d_scenes.instantiate_template("studio", "stage-salon", workspace_dir)
        document = scene["document"]
        furniture = [slot for slot in document["slots"] if str(slot["id"]).startswith("furniture-")]
        url = f"/api/v1/file/cc0/{key}?workspace=studio"
        assert furniture and {slot["sourceUrl"] for slot in furniture} == {url}
        copied = tmp_path / "studio" / "cc0" / key
        assert copied.read_bytes() == body
        stamped = copied.stat().st_mtime_ns
        again = world3d_scenes.instantiate_template("studio", "stage-salon", workspace_dir)
        assert again["document"]["slots"][-1]["sourceUrl"] == url
        assert copied.stat().st_mtime_ns == stamped and list((tmp_path / "studio" / "cc0").iterdir()) == [copied]
        cached = world3d_scenes._COMPILED["stage-salon"]["slots"]
        assert any(str(slot.get("sourceUrl", "")).startswith("/api/v1/library/files/") for slot in cached)
        opened = execute_command("world3d.templates.get", {"version": 1, "input": {"workspace": "studio", "template_id": "stage-salon"}}, workspace_dir)
        opened_slots = [slot for slot in opened["result"]["document"]["slots"] if str(slot["id"]).startswith("furniture-")]
        assert opened_slots and {slot["sourceUrl"] for slot in opened_slots} == {url}
        receipt = service.submit(_export_command(document, "dressed-stage"))
        assert receipt["replayed"] is False
        admitted = service._registry("studio").command_admission("dressed-stage")
        snapshot = admitted["effective"]["input"]["snapshot"]
        assert all(not str(ref.get("url", "")).startswith("/api/v1/library/files/") for ref in snapshot["refs"])
        assert any(ref.get("path") == f"cc0/{key}" for ref in snapshot["refs"])
        forget_task_registry(service._registry("studio").workspace_dir)
    finally:
        world3d_scenes._COMPILED.pop("stage-salon", None)


def test_an_old_library_furniture_url_exports(tmp_path, monkeypatch):
    """A document saved before the copy still exports, and a missing library file still does not."""
    from services.task_manager import forget_task_registry
    body, digest, key = _library_bytes(tmp_path, monkeypatch)
    service, _workspace_dir = _export_service(tmp_path)
    document = {
        "version": 1, "units": "meters", "up": "y", "width": 64, "height": 64, "fps": 30, "duration": 2 / 30,
        "templateId": "stage-salon",
        "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
        "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
        "slots": [
            {"id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0, "scale": 1,
             "sourceUrl": "", "media": "model3d", "clip": None},
            {"id": "furniture-sofa", "slot": "prop", "media": "model3d", "sourceUrl": f"/api/v1/library/files/{key}",
             "position": [1, 0, 1], "rotationY": 0, "scale": 1, "clip": None, "grounded": True},
        ],
    }
    receipt = service.submit(_export_command(document, "old-library"))
    assert receipt["replayed"] is False
    copied = Path(service.workspace_dir("studio")) / "cc0" / key
    assert copied.read_bytes() == body
    stamped = copied.stat().st_mtime_ns
    service.submit(_export_command(document, "old-library-again"))
    assert copied.stat().st_mtime_ns == stamped
    admitted = service._registry("studio").command_admission("old-library")
    slot = next(item for item in admitted["effective"]["input"]["snapshot"]["document"]["slots"] if item["id"] == "furniture-sofa")
    assert slot["sourceUrl"] == f"/api/v1/file/cc0/{key}?workspace=studio"
    missing = json.loads(json.dumps(document))
    missing["slots"][1]["sourceUrl"] = "/api/v1/library/files/" + "ab" * 32 + ".glb"
    with pytest.raises(HTTPException) as error:
        service.submit(_export_command(missing, "missing-library"))
    assert error.value.status_code == 409 and error.value.detail["code"] == "missing_ref"
    forget_task_registry(service._registry("studio").workspace_dir)


def test_a_production_stage_copies_furniture_into_the_workspace(tmp_path, monkeypatch):
    from services.production_scene3d import resolve_media
    _body, digest, key = _library_bytes(tmp_path, monkeypatch)
    monkeypatch.setattr("services.cc0_props.pack_ready", lambda: True)
    monkeypatch.setattr("services.cc0_props.models_by_id", lambda manifest=None: _furniture_table(digest))
    resolved = resolve_media(
        {"template": "stage-salon", "cast": {"subject_1": "/api/v1/file/hero.glb?workspace=studio"}},
        stills={}, root=tmp_path, workspace="studio",
    )
    furniture = {name: entry for name, entry in resolved["cast"].items() if name.startswith("furniture-")}
    assert furniture
    assert {entry["source"] for entry in furniture.values()} == {f"/api/v1/file/cc0/{key}?workspace=studio"}
    assert (tmp_path / "cc0" / key).is_file()
    assert resolved["cast"]["subject_1"]["source"] == "/api/v1/file/hero.glb?workspace=studio"


def test_furniture_field_is_library_or_box():
    from services.production_rooms import check_room
    assert check_room("salon", {"kind": "room", "mold": "salon", "furniture": "library"}) is None
    assert check_room("salon", {"kind": "room", "mold": "salon", "furniture": "box"}) is None
    assert check_room("salon", {"kind": "room", "mold": "salon"}) is None
    refused = check_room("salon", {"kind": "room", "mold": "salon", "furniture": "cubes"})
    assert refused and "library or box" in refused
