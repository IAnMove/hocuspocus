"""What an agent makes with the media tools and studio.key shows in Activity's agent trail and names the agent on the file."""
from __future__ import annotations

import json
import shutil
import subprocess
import wave

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image

from routers.wangp_mcp import create_wangp_mcp_router
from services.agent_activity import AgentActivity
from services.production_media_commands import command_catalog, command_handlers
from services.studio_key import command_catalog as key_catalog, command_handlers as key_handlers
from services.task_manager import TaskRegistry


def _app(tmp_path):
    workspace, uploads = tmp_path / "show", tmp_path / "uploads"
    workspace.mkdir()
    uploads.mkdir()
    folder = lambda name: str(workspace if name == "show" else tmp_path / name)
    registry = TaskRegistry(str(workspace))
    activity = AgentActivity(lambda _workspace: registry, lambda: "show")
    handlers = {**command_handlers(folder, lambda: str(uploads)), **key_handlers(folder, lambda: str(uploads), find_model=lambda: None)}
    app = FastAPI()
    app.include_router(create_wangp_mcp_router(
        handlers=handlers, journal_path=tmp_path / "requests.sqlite3", token_getter=lambda: "token",
        command_operations=[*command_catalog(), *key_catalog()], on_mutation=activity.record))
    return app, workspace, registry


def _call(client, name, data, intent):
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
            "params": {"name": name, "arguments": {"version": 1, "intent_id": intent, "input": {"workspace": "show", **data}}}}
    response = client.post("/api/v1/mcp", json=body, headers={"Authorization": "Bearer token"})
    assert response.status_code == 200, response.text
    return json.loads(response.json()["result"]["content"][0]["text"])["result"]


def _sound(path, seconds=2.0, rate=44100):
    samples = (np.sin(np.linspace(0, 2 * np.pi * 440 * seconds, int(rate * seconds))) * 12000).astype("<i2")
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())


@pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")), reason="ffmpeg required")
def test_agent_media_files_are_in_the_trail_and_their_sidecars_name_the_call(tmp_path):
    app, workspace, registry = _app(tmp_path)
    screen = np.zeros((40, 40, 3), dtype=np.uint8)
    screen[:] = (48, 155, 80)
    screen[10:30, 10:30] = (200, 60, 50)
    Image.fromarray(screen).save(workspace / "pose.png")
    _sound(workspace / "steps.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=24:duration=1",
                    "-pix_fmt", "yuv420p", str(workspace / "clip.mp4")], check=True)
    with TestClient(app) as client:
        keyed = _call(client, "studio.key", {"source": "pose.png"}, "key-1")
        frame = _call(client, "media.frame", {"source": "clip.mp4", "at": "last"}, "frame-1")
        still = _call(client, "media.compose", {"base": frame["file"], "layers": [{"file": keyed["file"], "scale": 0.5}]}, "still-1")
        cut = _call(client, "audio.trim", {"source": "steps.wav", "start": 0.5, "length": 0.3}, "trim-1")
    made = [keyed["file"], frame["file"], still["file"], cut["file"]]
    trail = {ref: task for task in registry.list(limit=50) if task["kind"] == "agent" for ref in task["result_refs"]}
    for name, tool in zip(made, ("studio.key", "media.frame", "media.compose", "audio.trim")):
        assert trail[name]["metadata"]["tool"] == "external_agent" and trail[name]["metadata"]["capability"] == tool
        sidecar = json.loads((workspace / name).with_suffix(".meta.json").read_text())
        assert sidecar["origin"]["tool"] == "external_agent", name
        assert sidecar["requested_by"]["capability"] == tool and sidecar["command_id"].endswith("-1")
    key_sidecar = json.loads((workspace / keyed["file"]).with_suffix(".meta.json").read_text())
    assert key_sidecar["lineage"]["parents"][0]["uri"] == "pose.png"
