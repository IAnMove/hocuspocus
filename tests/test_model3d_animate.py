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
