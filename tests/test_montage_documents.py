"""Editable montages: validation, compare-and-swap saves, export mapping and commands."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.montages import create_montages_router
from services.montage_commands import MontageCommands, command_catalog
from services.montage_documents import MontageError, MontageStore, export_body, normalize_montage


def _montage(**overrides):
    value = {
        "version": 1, "name": "The Bird Is Freed", "width": 1920, "height": 1080, "fps": 24,
        "clips": [{"id": "c1", "source": "shot01.mp4", "trimStart": 0, "trimEnd": 4.2, "transition": "crossfade",
                   "transitionDuration": 0.4, "origin": {"kind": "scene2d", "scene": "intro-123.scene.json"}},
                  {"id": "c2", "source": "/api/v1/file/shot02.mp4?workspace=x-song"}],
        "soundtrack": {"source": "song.wav", "volume": 1},
        "overlays": [{"id": "t1", "source": "cap/t_open.png", "start": 0.6, "end": 6.5, "width": 100, "fadeIn": 1.2, "fadeOut": 1.2}],
        "audioCues": [{"id": "vo1", "source": "vo01.wav", "start": 0.8, "volume": 1.6}],
        "duck": 0.5,
    }
    value.update(overrides)
    return value


def _store(tmp_path: Path) -> MontageStore:
    def workspace_dir(name: str) -> str:
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)
    return MontageStore(workspace_dir)


def test_normalize_keeps_layers_and_provenance():
    document = normalize_montage(_montage())
    assert document["clips"][0]["origin"] == {"kind": "scene2d", "scene": "intro-123.scene.json"}
    assert document["clips"][1]["name"].startswith("shot02.mp4")
    assert document["overlays"][0]["fadeIn"] == 1.2 and document["overlays"][0]["x"] == 50
    assert document["audioCues"][0]["volume"] == 1.6
    assert document["duck"] == 0.5


@pytest.mark.parametrize("change,message", [
    ({"clips": []}, "between 1"),
    ({"fps": 23}, "fps"),
    ({"width": 1921}, "even"),
    ({"clips": [{"source": "blob:http://x/1"}]}, "durable"),
    ({"overlays": [{"source": "cap.png", "start": 3, "end": 2}]}, "end after"),
    ({"clips": [{"source": "a.mp4", "origin": {"kind": "magic"}}]}, "origin"),
])
def test_normalize_rejects_invalid_documents(change, message):
    with pytest.raises(MontageError, match=message):
        normalize_montage(_montage(**change))


def test_save_is_revisioned_and_compare_and_swap(tmp_path):
    store = _store(tmp_path)
    first = store.save("x-song", _montage())
    assert first["file"] == "The-Bird-Is-Freed.montage.json" and first["revision"] == 1
    with pytest.raises(MontageError) as exists:
        store.save("x-song", _montage())
    assert exists.value.status == 409
    second = store.save("x-song", _montage(duck=0.2), file=first["file"], expected_revision=1)
    assert second["revision"] == 2
    with pytest.raises(MontageError) as stale:
        store.save("x-song", _montage(), file=first["file"], expected_revision=1)
    assert stale.value.code == "revision_conflict"
    listed = store.list("x-song")
    assert listed[0]["revision"] == 2 and listed[0]["overlays"] == 1 and listed[0]["audioCues"] == 1
    assert store.get("x-song", first["file"])["montage"]["duck"] == 0.2
    with pytest.raises(MontageError):
        store.get("x-song", "../escape.montage.json")


def test_export_body_matches_video_editor_contract():
    body = export_body(normalize_montage(_montage()), "x-song")
    assert body["clips"][0]["trim_end"] == 4.2 and body["clips"][0]["transition"] == "crossfade"
    assert body["soundtrack"]["source"] == "song.wav"
    assert body["overlays"][0]["fade_in"] == 1.2 and body["audio_cues"][0]["trim_start"] == 0
    assert body["duck"] == 0.5 and body["workspace"] == "x-song"


def test_commands_and_http_share_one_service(tmp_path):
    started = []

    def start_export(body):
        started.append(body)
        return {"job_id": "video-edit-1", "status": "queued"}

    commands = MontageCommands(_store(tmp_path), start_export=start_export, get_export=lambda job: {"job_id": job, "status": "completed"})
    names = [item["name"] for item in command_catalog()]
    assert names == ["montages.list", "montages.get", "montages.save", "montages.export", "montages.export.status"]
    saved = asyncio.run(commands.handlers()["montages.save"]({"version": 1, "input": {"workspace": "x-song", "montage": _montage()}}))
    file = saved["result"]["file"]
    app = FastAPI()
    app.include_router(create_montages_router(commands))
    client = TestClient(app)
    assert client.get("/api/v1/montages", params={"workspace": "x-song"}).json()["montages"][0]["file"] == file
    exported = client.post(f"/api/v1/montages/{file}/export", params={"workspace": "x-song"})
    assert exported.status_code == 202 and exported.json()["job"]["job_id"] == "video-edit-1"
    assert started[0]["audio_cues"][0]["source"] == "vo01.wav"
    conflict = client.post("/api/v1/montages", json={"workspace": "x-song", "montage": _montage()})
    assert conflict.status_code == 409 and conflict.json()["detail"]["code"] == "exists"
    invalid = asyncio.run(_raises(commands.handlers()["montages.get"], {"version": 2, "input": {}}))
    assert invalid.status_code == 422
    assert json.loads(Path(tmp_path, "x-song", file).read_text())["revision"] == 1


async def _raises(handler, arguments):
    from fastapi import HTTPException
    try:
        await handler(arguments)
    except HTTPException as error:
        return error
    raise AssertionError("expected HTTPException")
