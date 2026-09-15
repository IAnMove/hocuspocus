"""Canonical World3D export admission, cancel, retry and optional real MP4.

These checks never import ``_launch_runtime``. A headless worker is independent
of the HTTP client: closing the request does not cancel the task. Real paint
through the Video 3D stage is PENDING unless ffmpeg/playwright are present and
a renderer is injected; admission, cancel and idempotent intent still run.
"""
from __future__ import annotations

from pathlib import Path
import json
import threading
import time

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from routers.wangp_mcp import create_wangp_mcp_router
from routers.world3d_export import create_world3d_export_router
from services.scene_recording import probe_scene_recording_output
from services.task_manager import TaskRegistry, forget_task_registry
from services.world3d_export import (
    OPERATION,
    World3DExportCancelled,
    World3DExportService,
    _OWNED_BROWSER_JS,
    command_catalog,
    command_handlers,
    export_capabilities,
    export_plan,
    freeze_export_command,
    mux_frame_sequence,
    staging_dir,
    unsupported_capabilities,
    write_png,
)


WORKSPACE = "workspace-a"


def _document(**overrides):
    document = {
        "version": 1, "units": "meters", "up": "y", "width": 64, "height": 64,
        "fps": 30, "duration": 2 / 30, "templateId": "two-shot",
        "camera": {"family": "establishment", "eye": [0, 1.6, 4.2], "look": [0, 1, 0], "fov": 50},
        "light": {"kind": "directional", "direction": [-0.35, -1, -0.25], "intensity": 1.15, "color": "#fff4e5"},
        "slots": [{
            "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
            "scale": 1, "sourceUrl": "", "media": "model3d", "clip": None,
        }],
    }
    document.update(overrides)
    return document


def _command(intent_id="world3d-intent-1", **input_overrides):
    payload = {"workspace": WORKSPACE, "document": _document(), "refs": []}
    payload.update(input_overrides)
    return {"version": 1, "operation": OPERATION, "intent_id": intent_id, "input": payload}


def _paint(snapshot, staging, progress, cancelled, *, calls=None, gate=None, fail=False, hold=None):
    if calls is not None:
        calls.append(snapshot["plan"]["count"])
    if gate is not None:
        gate.wait(2)
    if hold is not None:
        hold.wait(8)
    if fail:
        folder = Path(staging) / "frames"
        write_png(folder / "frame_000001.png", 64, 64, (12, 24, 48))
        raise RuntimeError("forced export failure")
    paths = []
    plan = snapshot["plan"]
    folder = Path(staging) / "frames"
    for index in range(plan["count"]):
        if cancelled():
            raise World3DExportCancelled()
        path = folder / f"frame_{index + 1:06d}.png"
        write_png(path, plan["width"], plan["height"], (index * 40 % 200, 90, 160))
        paths.append(path)
        progress(index + 1, plan["count"])
    return paths


def _service(tmp_path: Path, renderer=None):
    def workspace_dir(name: str) -> str:
        path = Path(tmp_path) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    def registry_for(name: str):
        return TaskRegistry(workspace_dir(name), interrupt_stale=False)

    return World3DExportService(workspace_dir=workspace_dir, registry_for=registry_for, renderer=renderer)


def _client(service, tmp_path: Path) -> TestClient:
    app = FastAPI()
    app.include_router(create_world3d_export_router(service))
    app.include_router(create_wangp_mcp_router(
        handlers=command_handlers(service), command_operations=command_catalog(),
        journal_path=str(Path(tmp_path) / "mcp-journal.sqlite"), token_getter=lambda: "test-token",
    ))
    return TestClient(app)


def _wait(registry, task_id, wanted, timeout=8.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = registry.get(task_id)
        if task and task["status"] in wanted:
            return task
        time.sleep(0.02)
    raise AssertionError(registry.get(task_id))


def _mcp(client: TestClient, name: str, arguments: dict, request_id=1):
    return client.post(
        "/api/v1/wangp/mcp", headers={"Authorization": "Bearer test-token"},
        json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}},
    )


def test_preflight_rejects_blob_urls_and_unknown_media():
    blob = _command(document=_document(slots=[{
        "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
        "scale": 1, "sourceUrl": "blob:https://hocus.local/abc", "media": "model3d", "clip": None,
    }]))
    with pytest.raises(Exception) as error:
        freeze_export_command(blob)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "unsupported_capability"
    unknown = _command(document=_document(slots=[{
        "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
        "scale": 1, "sourceUrl": "", "media": "volumetric", "clip": None,
    }]))
    with pytest.raises(Exception) as error:
        freeze_export_command(unknown)
    assert error.value.detail["code"] == "unsupported_capability"


def test_voiced_duration_is_an_explicit_preflight_reject():
    document = _document(duration=181, sfx=[{"id": "spark", "kind": "sparks", "start": 0, "end": 1,
                                            "sound": True, "volume": 0.4}])
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=document))
    assert error.value.detail["code"] == "unsupported_capability"
    assert "voiced_duration" in error.value.detail["message"]


def test_short_voiced_scene_is_rejected_instead_of_silent_mp4():
    document = _document(duration=2, sfx=[{"id": "spark", "kind": "sparks", "start": 0, "end": 1,
                                          "sound": True, "volume": 0.4}])
    assert "voiced_audio" in unsupported_capabilities(document)
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=document))
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "unsupported_capability"
    assert "voiced_audio" in error.value.detail["message"]
    spoken = _document(slots=[{
        "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
        "scale": 1, "sourceUrl": "", "media": "model3d", "clip": None,
        "speech": {"enabled": True, "audio": {"url": "/api/v1/file/voice.wav", "filename": "voice.wav"}},
    }])
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=spoken))
    assert error.value.detail["code"] == "unsupported_capability"


def test_publish_refuses_a_voiced_snapshot_even_if_preflight_is_bypassed(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    snapshot = {
        "workspace": WORKSPACE,
        "document": _document(duration=2, soundtrack=[{"id": "bed", "audio": {"url": "/api/v1/file/bed.wav"}}]),
        "refs": [],
        "plan": export_plan(_document(duration=2)),
    }
    frames = [tmp_path / "frame_000001.png"]
    write_png(frames[0], 64, 64, (1, 2, 3))

    class _Token:
        def is_cancelled(self):
            return False

    with pytest.raises(RuntimeError, match="silent MP4"):
        service._publish(snapshot, tmp_path, frames, WORKSPACE, service._registry(WORKSPACE), "task", _Token())
    assert list(Path(service.workspace_dir(WORKSPACE)).glob("*.mp4")) == []


def test_owned_browser_script_uses_scene_clock_and_waits_for_assets():
    assert "world3d-render.html" in _OWNED_BROWSER_JS
    assert "window.__world3dExport.load(scene, size)" in _OWNED_BROWSER_JS
    assert "window.__world3dExport.frame(seconds)" in _OWNED_BROWSER_JS
    assert "/src/" not in _OWNED_BROWSER_JS


def test_staging_dir_does_not_treat_dotdot_as_workspace_root(tmp_path):
    escaped = staging_dir(str(tmp_path), "..")
    assert escaped.resolve().parent == (tmp_path / ".world3d-export").resolve()
    assert escaped.name != ".."
    assert escaped.resolve() != tmp_path.resolve()


def test_admit_freezes_snapshot_as_one_canonical_task(tmp_path):
    calls = []
    gate = threading.Event()
    service = _service(tmp_path, renderer=lambda *args, **kwargs: _paint(*args, calls=calls, gate=gate, **kwargs))
    result = service.submit(_command())
    assert result["replayed"] is False
    receipt = result["receipt"]
    assert receipt["operation"] == OPERATION
    assert receipt["status"] == "queued"
    registry = service._registry(WORKSPACE)
    stored = registry.command_admission("world3d-intent-1")
    snapshot = stored["effective"]["input"]["snapshot"]
    assert snapshot["document"]["templateId"] == "two-shot"
    assert snapshot["plan"]["count"] == 2
    task = registry.get(receipt["taskIds"][0])
    assert task["status"] in {"queued", "running"}
    assert task["cancelable"] is True
    gate.set()
    _wait(registry, task["id"], {"completed", "failed"})
    forget_task_registry(registry.workspace_dir)


def test_two_retries_of_the_same_intent_do_not_export_twice(tmp_path):
    calls = []
    service = _service(tmp_path, renderer=lambda *args, **kwargs: _paint(*args, calls=calls, **kwargs))
    first = service.submit(_command("same-intent"))
    second = service.submit(_command("same-intent"))
    assert second["replayed"] is True
    assert second["receipt"]["taskIds"] == first["receipt"]["taskIds"]
    registry = service._registry(WORKSPACE)
    task = _wait(registry, first["receipt"]["taskIds"][0], {"completed", "failed"})
    assert task["status"] == "completed"
    assert calls == [2]
    changed = _command("same-intent", document=_document(duration=3 / 30))
    with pytest.raises(Exception) as error:
        service.submit(changed)
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "intent_conflict"
    assert calls == [2]


def test_closing_http_client_does_not_cancel_the_worker(tmp_path):
    hold = threading.Event()
    service = _service(tmp_path, renderer=lambda *args, **kwargs: _paint(*args, hold=hold, **kwargs))
    client = _client(service, tmp_path)
    posted = client.post("/api/v1/scenes/world3d/export", json=_command("ui-close"))
    assert posted.status_code == 200, posted.text
    task_id = posted.json()["receipt"]["taskIds"][0]
    registry = service._registry(WORKSPACE)
    live = _wait(registry, task_id, {"queued", "running"})
    assert live["status"] != "cancelled"
    hold.set()
    finished = _wait(registry, task_id, {"completed", "failed"})
    assert finished["status"] == "completed"


def test_cancel_keeps_the_document_and_recoverable_partials(tmp_path):
    hold = threading.Event()
    started = threading.Event()

    def renderer(snapshot, staging, progress, cancelled):
        started.set()
        write_png(Path(staging) / "frames" / "frame_000001.png", 64, 64, (1, 2, 3))
        hold.wait(8)
        if cancelled():
            raise World3DExportCancelled()
        return _paint(snapshot, staging, progress, cancelled)

    service = _service(tmp_path, renderer=renderer)
    client = _client(service, tmp_path)
    posted = client.post("/api/v1/scenes/world3d/export", json=_command("cancel-me"))
    assert posted.status_code == 200, posted.text
    started.wait(2)
    cancelled = client.post("/api/v1/scenes/world3d/export/cancel",
                            json={"workspace": WORKSPACE, "intent_id": "cancel-me"})
    assert cancelled.status_code == 200, cancelled.text
    hold.set()
    registry = service._registry(WORKSPACE)
    task = _wait(registry, posted.json()["receipt"]["taskIds"][0], {"cancelled"})
    assert task["status"] == "cancelled"
    stored = registry.command_admission("cancel-me")
    assert stored["effective"]["input"]["snapshot"]["document"]["slots"][0]["id"] == "subject_1"
    staging = staging_dir(registry.workspace_dir, "cancel-me")
    assert (staging / "snapshot.json").is_file()
    assert (staging / "frames" / "frame_000001.png").is_file()
    assert list(Path(registry.workspace_dir).glob("*.mp4")) == []


def test_failure_keeps_document_and_partials_for_retry(tmp_path):
    calls = []

    def renderer(snapshot, staging, progress, cancelled):
        calls.append("run")
        if len(calls) == 1:
            return _paint(snapshot, staging, progress, cancelled, fail=True)
        return _paint(snapshot, staging, progress, cancelled)

    service = _service(tmp_path, renderer=renderer)
    first = service.submit(_command("retry-fail"))
    registry = service._registry(WORKSPACE)
    failed = _wait(registry, first["receipt"]["taskIds"][0], {"failed"})
    assert failed["status"] == "failed"
    staging = staging_dir(registry.workspace_dir, "retry-fail")
    assert json.loads((staging / "snapshot.json").read_text())["document"]["version"] == 1
    assert (staging / "frames" / "frame_000001.png").is_file()
    second = service.submit(_command("retry-fail"))
    assert second["replayed"] is True
    completed = _wait(registry, first["receipt"]["taskIds"][0], {"completed", "failed"})
    assert completed["status"] == "completed"
    assert calls == ["run", "run"]
    assert completed["result_refs"]


def test_http_and_mcp_share_the_same_receipt(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    client = _client(service, tmp_path)
    http = client.post("/api/v1/scenes/world3d/export", json=_command("shared-receipt"))
    assert http.status_code == 200, http.text
    mcp = _mcp(client, OPERATION, {key: value for key, value in _command("shared-receipt").items() if key != "operation"})
    assert mcp.status_code == 200, mcp.text
    payload = mcp.json()["result"]
    assert payload["isError"] is False
    assert payload["structuredContent"]["receipt"] == http.json()["receipt"]
    assert payload["structuredContent"]["replayed"] is True
    catalog = client.get("/api/v1/scenes/world3d/export/commands").json()
    names = [item["name"] for item in catalog["operations"]]
    assert names == [OPERATION, f"{OPERATION}.receipt", f"{OPERATION}.cancel"]


def test_mcp_recover_decodable_mp4_or_mark_real_render_pending(tmp_path):
    caps = export_capabilities()
    service = _service(tmp_path, renderer=_paint if caps["ffmpeg"] else None)
    client = _client(service, tmp_path)
    admitted = _mcp(client, OPERATION, {key: value for key, value in _command("mcp-recover").items() if key != "operation"})
    assert admitted.status_code == 200, admitted.text
    body = admitted.json()["result"]["structuredContent"]
    task_id = body["receipt"]["taskIds"][0]
    registry = service._registry(WORKSPACE)
    if not caps["ffmpeg"]:
        task = _wait(registry, task_id, {"failed", "completed"})
        assert caps["realRender"] == "pending"
        assert task["status"] == "failed"
        viewed = _mcp(client, f"{OPERATION}.receipt",
                      {"version": 1, "input": {"workspace": WORKSPACE, "intent_id": "mcp-recover"}}, request_id=2)
        assert viewed.json()["result"]["structuredContent"]["receipt"]["taskIds"] == [task_id]
        return
    task = _wait(registry, task_id, {"completed", "failed"})
    assert task["status"] == "completed"
    name = task["result_refs"][0]
    output = Path(registry.workspace_dir) / name
    metadata = probe_scene_recording_output(output)
    video = next(item for item in metadata["streams"] if item.get("codec_type") == "video")
    assert video["codec_name"] == "h264"
    if not caps["playwright"]:
        assert caps["realRender"] == "pending"
    viewed = _mcp(client, f"{OPERATION}.receipt",
                  {"version": 1, "input": {"workspace": WORKSPACE, "intent_id": "mcp-recover"}}, request_id=2)
    recovered = viewed.json()["result"]["structuredContent"]
    assert recovered["task"]["id"] == task_id
    assert recovered["task"]["result_refs"] == [name]


def test_capabilities_endpoint_matches_worker_preflight(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    client = _client(service, tmp_path)
    listed = client.get("/api/v1/scenes/world3d/export/capabilities").json()
    assert listed["renderer"] == "world3d-export-flow"
    assert listed["realRender"] in {"ready", "pending"}
    assert listed["ffmpeg"] is export_capabilities()["ffmpeg"]
    assert listed["maxVoicedDuration"] == 0
    assert listed["fps"] == [24, 30, 60]


def test_renderer_origin_uses_socket_address_and_preserves_explicit_configuration(tmp_path):
    from routers.world3d_export import bind_world3d_renderer_origin
    service = _service(tmp_path, renderer=_paint)
    service.app_url = ''
    app = FastAPI()
    bind_world3d_renderer_origin(app, service)
    app.include_router(create_world3d_export_router(service))
    client = TestClient(app, base_url='http://localhost:4192')
    response = client.get('/api/v1/scenes/world3d/export/capabilities', headers={'host': 'untrusted.example'})
    assert response.status_code == 200
    assert service.app_url == 'http://127.0.0.1:4192'
    service.app_url = 'http://127.0.0.1:8888'
    client.get('/api/v1/scenes/world3d/export/capabilities')
    assert service.app_url == 'http://127.0.0.1:8888'


def test_mux_validates_before_replacing_destination(tmp_path):
    if not export_capabilities()["ffmpeg"]:
        pytest.skip("ffmpeg is required to validate publication")
    folder = tmp_path / "frames"
    frames = []
    for index in range(2):
        path = folder / f"frame_{index + 1:06d}.png"
        write_png(path, 64, 64, (30, 60, 90))
        frames.append(path)
    destination = tmp_path / "clip.mp4"
    mux_frame_sequence(frames, destination, fps=30, duration=2 / 30)
    assert destination.is_file()
    video = next(item for item in probe_scene_recording_output(destination)["streams"]
                 if item.get("codec_type") == "video")
    assert video["codec_name"] == "h264"
