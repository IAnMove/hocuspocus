"""model3d.animate publishes clip indexes without importing pygltflib."""
import asyncio
import json

import pytest

from routers.model3d_animate import command_catalog, command_handlers, create_model3d_animate_router


def _args(**patch):
    payload = {"workspace": "movie", "source": "pet.glb", "clips": ["walk", "wave"], "bpm": 120}
    payload.update(patch)
    return {"version": 1, "intent_id": "anim-1", "input": payload}


def test_catalog_names_clips_for_a_video3d_slot():
    operation = command_catalog()[0]
    assert operation["name"] == "model3d.animate"
    fields = operation["inputSchema"]["properties"]["input"]["properties"]
    assert fields["bpm"]["minimum"] == 60 and fields["bpm"]["maximum"] == 180
    assert fields["import"]["required"] == ["file"]
    json.dumps(command_catalog())


def test_publication_replays_and_lists_clip_indexes(tmp_path):
    root = tmp_path / "ws"
    folder = root / "movie"
    folder.mkdir(parents=True)
    (folder / "pet.glb").write_bytes(b"source-glb")
    calls = []

    def runner(request, output):
        calls.append(request)
        output.write_bytes(b"animated-glb")
        return {"clips": [{"index": 0, "name": "Walk", "duration": 1.0},
                          {"index": 1, "name": "Wave", "duration": 1.0}], "warnings": []}

    handlers = command_handlers(lambda name: str(root / name), tmp_path / "journal.db", runner)
    result = asyncio.run(handlers["model3d.animate"](_args()))["result"]
    assert result["clips"][0] == {"index": 0, "name": "Walk", "duration": 1.0}
    assert result["url"].endswith("?workspace=movie")
    assert (folder / result["file"]).read_bytes() == b"animated-glb"
    manifest = json.loads((folder / result["file"]).with_suffix(".meta.json").read_text())
    assert manifest["params"]["clips"] == ["walk", "wave"]
    assert calls[0]["mode"] == "animate" and calls[0]["animations"] == ["walk", "wave"]
    retry = asyncio.run(handlers["model3d.animate"](_args()))
    assert retry["result"] == result and len(calls) == 1
    with pytest.raises(ValueError, match="different parameters"):
        asyncio.run(handlers["model3d.animate"](_args(clips=["run"])))


@pytest.mark.parametrize("patch,message", [
    ({"clips": ["spin"]}, "Unknown animations"),
    ({"clips": [], "bpm": 90}, "at least one"),
    ({"source": "../pet.glb"}, "workspace"),
    ({"bpm": 30}, "bpm"),
    ({"import": {"file": "notes.txt"}}, ".bvh"),
])
def test_invalid_animate_inputs_fail_before_the_worker(tmp_path, patch, message):
    root = tmp_path / "ws"
    folder = root / "movie"
    folder.mkdir(parents=True)
    (folder / "pet.glb").write_bytes(b"source-glb")
    handlers = command_handlers(lambda name: str(root / name), tmp_path / "journal.db", lambda *_: None)
    args = _args()
    args["input"].update(patch)
    with pytest.raises(ValueError, match=message):
        asyncio.run(handlers["model3d.animate"](args))


def test_http_route_reports_invalid_command(tmp_path):
    from fastapi import FastAPI
    import httpx

    app = FastAPI()
    app.include_router(create_model3d_animate_router(
        command_handlers(lambda name: str(tmp_path / name), tmp_path / "journal.db", lambda *_: None)))

    async def call():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/v1/model3d/animate", json={"version": 1})

    response = asyncio.run(call())
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid_command"


def test_uploaded_animations_stay_out_of_the_gallery_and_keep_one_copy(tmp_path, monkeypatch):
    from routers.model3d_animate import IMPORT_FOLDER, store_import
    from services import core_workspace

    (tmp_path / "hero.glb").write_bytes(b"glb")
    first = store_import(tmp_path, "Mixamo Walk (2).glb", b"glb-bytes")
    monkeypatch.setattr(core_workspace, "workspace_dir", lambda _workspace=None: str(tmp_path))
    assert [row["name"] for row in core_workspace.list_outputs("movie")["outputs"]] == ["hero.glb"]
    again = store_import(tmp_path, "other name.glb", b"glb-bytes")
    assert first.startswith(f"{IMPORT_FOLDER}/Mixamo-Walk-2-") and first.endswith(".glb")
    assert (tmp_path / first).read_bytes() == b"glb-bytes"
    assert again != first and len(list((tmp_path / IMPORT_FOLDER).iterdir())) == 2
    assert store_import(tmp_path, "Mixamo Walk (2).glb", b"glb-bytes") == first
    for name, payload, message in (("notes.txt", b"x", ".bvh"), ("walk.bvh", b"", "64 MB")):
        with pytest.raises(ValueError, match=message):
            store_import(tmp_path, name, payload)


def test_the_import_label_drops_the_upload_hash():
    from pathlib import Path

    from routers.model3d_animate import _import_label

    assert _import_label(Path("animation-imports/Samba_Dancing-1a2b3c4d.glb")) == "Samba Dancing"
    assert _import_label(Path("x/-.bvh")) == "Imported"
    assert _import_label(Path("mocap/dance-cafebabe.bvh")) == "dance cafebabe"


def test_rig_listing_finds_only_glbs_with_the_standard_skeleton(tmp_path):
    import struct

    from routers.model3d_animate import humanoid_rigs
    from services.humanoid_rig.names import BONE_NAMES

    def glb(document):
        text = json.dumps(document).encode()
        text += b" " * (-len(text) % 4)
        chunk = struct.pack("<II", len(text), 0x4E4F534A) + text
        return struct.pack("<III", 0x46546C67, 2, 12 + len(chunk)) + chunk

    (tmp_path / "hero.glb").write_bytes(glb({"nodes": [{"name": name} for name in BONE_NAMES], "animations": [{"name": "Walk"}, {}]}))
    (tmp_path / "prop.glb").write_bytes(glb({"nodes": [{"name": "Box"}]}))
    (tmp_path / "broken.glb").write_bytes(b"not a glb")
    (tmp_path / "list.glb").write_bytes(glb([1, 2]))
    (tmp_path / "odd-nodes.glb").write_bytes(glb({"nodes": ["Hips", None, {"name": "Hips"}], "animations": "none"}))
    rigs = humanoid_rigs(tmp_path)
    assert [item["name"] for item in rigs] == ["hero.glb"]
    assert rigs[0]["clips"] == ["Walk", "Clip 2"]


def test_http_upload_and_listing_routes(tmp_path):
    from fastapi import FastAPI
    import httpx

    folder = tmp_path / "movie"
    folder.mkdir()
    app = FastAPI()
    app.include_router(create_model3d_animate_router(
        command_handlers(lambda name: str(tmp_path / name), tmp_path / "journal.db", lambda *_: None),
        lambda name: str(tmp_path / name)))

    async def calls():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            stored = await client.post("/api/v1/model3d/animation-files", params={"workspace": "movie", "filename": "wave.bvh"}, content=b"HIERARCHY")
            refused = await client.post("/api/v1/model3d/animation-files", params={"workspace": "movie", "filename": "wave.fbx"}, content=b"x")
            listed = await client.get("/api/v1/model3d/humanoid-rigs", params={"workspace": "movie"})
            return stored, refused, listed

    stored, refused, listed = asyncio.run(calls())
    assert stored.status_code == 200 and stored.json()["file"].startswith("animation-imports/wave-")
    assert (folder / stored.json()["file"]).read_bytes() == b"HIERARCHY"
    assert refused.status_code == 422 and refused.json()["detail"]["code"] == "invalid_upload"
    assert listed.json() == {"rigs": []}


def test_animating_an_animated_file_does_not_stack_prefixes():
    from routers.model3d_animate import _output_stem

    assert _output_stem("humanoid-humanoid-compose-robot-0e2dab471091e66c-2af57e8fa7378da9") == "compose-robot"
    assert _output_stem("2026-10-03-03h42m37s_rigged_pet_453b2d6f") == "pet"
    assert _output_stem("humanoid-2026-10-03-04h56m09s_rigged_hunyuan-pet-tpose_8109e8ed-22e0ad97f6103d5e") == "hunyuan-pet-tpose"
    assert _output_stem("2026-10-03-03h42m37s_hunyuan3d_pet") == "2026-10-03-03h42m37s_hunyuan3d_pet"
    assert _output_stem("...") == "model"


def _worker_run(stdout, stderr=""):
    import subprocess

    return subprocess.CompletedProcess(["worker"], 2, stdout=stdout, stderr=stderr)


def test_worker_refusals_and_crashes_are_told_apart():
    from routers.model3d_animate import AnimateRefused, _worker_payload

    refused = 'MAESTRO_RESULT {"ok": false, "error": "invalid_input", "reason": "the file has no animation"}'
    with pytest.raises(AnimateRefused, match="no animation") as caught:
        _worker_payload(_worker_run(refused))
    assert caught.value.code == "invalid_input"
    crashed = 'MAESTRO_RESULT {"ok": false, "error": "rig_failed", "reason": "index 9 is out of bounds"}'
    with pytest.raises(RuntimeError, match="out of bounds"):
        _worker_payload(_worker_run(crashed, "Traceback (most recent call last): ..."))


def _route(tmp_path, runner):
    from fastapi import FastAPI
    import httpx

    root = tmp_path / "ws"
    (root / "movie").mkdir(parents=True, exist_ok=True)
    (root / "movie" / "pet.glb").write_bytes(b"source-glb")
    app = FastAPI()
    app.include_router(create_model3d_animate_router(command_handlers(lambda name: str(root / name), tmp_path / "journal.db", runner)))

    async def call(intent):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            args = _args()
            args["intent_id"] = intent
            return await client.post("/api/v1/model3d/animate", json=args)

    return lambda intent="anim-1": asyncio.run(call(intent))


def test_a_refused_animation_answers_422_again_on_retry(tmp_path):
    from routers.model3d_animate import AnimateRefused

    calls = []

    def runner(request, output):
        calls.append(request)
        raise AnimateRefused("not_humanoid", "not_humanoid: standard humanoid skeleton not found")

    post = _route(tmp_path, runner)
    first, again = post(), post()
    assert first.status_code == again.status_code == 422
    assert first.json()["detail"] == again.json()["detail"]
    assert first.json()["detail"]["code"] == "not_humanoid" and len(calls) == 1
    assert not list((tmp_path / "ws" / "movie").glob("humanoid-*"))


def test_a_worker_crash_is_a_server_error(tmp_path):
    def runner(request, output):
        raise RuntimeError("Humanoid animate worker failed: index 9 is out of bounds")

    response = _route(tmp_path, runner)()
    assert response.status_code == 500
    assert response.json()["detail"]["code"] == "animate_failed"
    assert "new intent_id" in response.json()["detail"]["message"]


@pytest.mark.parametrize("path,message", [
    ({"points": [[0, 0]], "duration": 2}, "2 to 64"),
    ({"points": [[0, 0], [1, "x"]], "duration": 2}, "2 to 64"),
    ({"points": [[0, 0], [1, 1]], "duration": 0.1}, "duration"),
    ({"points": [[0, 0], [1, 1]]}, "points and duration"),
    ({"points": [[0, 0], [1, 1]], "duration": 2, "speed": 3}, "points and duration"),
])
def test_a_bad_path_is_refused_before_the_worker(tmp_path, path, message):
    root = tmp_path / "ws"
    (root / "movie").mkdir(parents=True)
    (root / "movie" / "pet.glb").write_bytes(b"source-glb")
    handlers = command_handlers(lambda name: str(root / name), tmp_path / "journal.db", lambda *_: None)
    args = _args(clips=[])
    args["input"]["path"] = path
    with pytest.raises(ValueError, match=message):
        asyncio.run(handlers["model3d.animate"](args))


def test_a_path_alone_reaches_the_worker_and_is_part_of_the_intent(tmp_path):
    root = tmp_path / "ws"
    (root / "movie").mkdir(parents=True)
    (root / "movie" / "pet.glb").write_bytes(b"source-glb")
    calls = []

    def runner(request, output):
        calls.append(request)
        output.write_bytes(b"animated-glb")
        return {"clips": [{"index": 3, "name": "Path Walk", "duration": 4.0, "contacts": []}], "warnings": []}

    handlers = command_handlers(lambda name: str(root / name), tmp_path / "journal.db", runner)
    args = _args(clips=[])
    args["input"]["path"] = {"points": [[0, 0], [0, 2]], "duration": 4}
    result = asyncio.run(handlers["model3d.animate"](args))["result"]
    assert result["clips"][0]["name"] == "Path Walk"
    assert calls[0]["path"] == {"points": [[0.0, 0.0], [0.0, 2.0]], "duration": 4.0}
    other = _args(clips=[])
    other["input"]["path"] = {"points": [[0, 0], [0, 3]], "duration": 4}
    with pytest.raises(ValueError, match="different parameters"):
        asyncio.run(handlers["model3d.animate"](other))
