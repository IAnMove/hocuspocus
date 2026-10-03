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
from services import resource_scheduler
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


def test_explicit_cpu_renderer_uses_a_cpu_lane_and_reports_its_device(monkeypatch):
    monkeypatch.setenv("HOCUS_SCENE_RENDER_DEVICE", " CPU ")
    assert World3DExportService.resource_lane(None) == resource_scheduler.cpu_lane("world3d-render")
    assert export_capabilities()["renderDevice"] == "cpu"
    monkeypatch.delenv("HOCUS_SCENE_RENDER_DEVICE")
    assert World3DExportService.resource_lane(None) == resource_scheduler.local_gpu_lane(0)


def test_unknown_renderer_device_fails_before_resource_admission(monkeypatch):
    monkeypatch.setenv("HOCUS_SCENE_RENDER_DEVICE", "automatic-gpu-bypass")
    with pytest.raises(ValueError, match="auto or cpu"):
        World3DExportService.resource_lane(None)


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

    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    return World3DExportService(
        workspace_dir=workspace_dir, registry_for=registry_for, renderer=renderer,
        uploads_dir=lambda: str(uploads),
    )


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


def _spoken(**speech):
    return _document(duration=2, slots=[{
        "id": "subject_1", "slot": "subject_1", "position": [0, 0, 0], "rotationY": 0,
        "scale": 1, "sourceUrl": "", "media": "model3d", "clip": None,
        "speech": {"enabled": True, "audio": {"url": "/api/v1/file/voice.wav", "filename": "voice.wav"}, **speech},
    }])


def test_short_voiced_scene_is_admitted_with_its_audio_frozen_as_a_ref():
    effects = _document(duration=2, sfx=[{"id": "spark", "kind": "sparks", "start": 0, "end": 1,
                                         "sound": True, "volume": 0.4}])
    assert unsupported_capabilities(effects) == []
    spoken = _spoken()
    assert unsupported_capabilities(spoken) == []
    refs = freeze_export_command(_command(document=spoken))["effective"]["input"]["snapshot"]["refs"]
    assert refs == [{"audioId": "subject_1/voice", "url": "/api/v1/file/voice.wav", "kind": "audio",
                     "filename": "voice.wav", "workspace": WORKSPACE}]


def test_voiced_admission_requires_the_audio_file(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    with pytest.raises(Exception) as error:
        service.submit(_command(intent_id="voiced-missing", document=_spoken()))
    assert error.value.status_code == 409 and error.value.detail["code"] == "missing_ref"
    (Path(service.workspace_dir(WORKSPACE)) / "voice.wav").write_bytes(b"RIFF")
    assert service.submit(_command(intent_id="voiced-present", document=_spoken()))["replayed"] is False
    forget_task_registry(service._registry(WORKSPACE).workspace_dir)


def test_ephemeral_audio_urls_are_refused():
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=_spoken(audio={"url": "blob:http://x/1"})))
    assert error.value.detail["code"] == "unsupported_capability"


@pytest.mark.parametrize("speech", [
    {"enabled": True, "cues": [{"start": 0, "end": 1, "viseme": "A"}]},
    {"enabled": True, "audible": False, "audio": {"url": "/api/v1/file/voice.wav"}},
    {"enabled": False, "audio": {"url": "/api/v1/file/voice.wav"}},
    {"enabled": True, "audio": {"url": "/api/v1/file/unused.wav"}, "clips": []},
    {"enabled": True, "clips": [{"audio": {"url": "/api/v1/file/voice.wav"}, "audible": False}]},
])
def test_muted_mouth_animation_is_exportable(speech):
    document = _document()
    document["slots"][0]["speech"] = speech
    assert unsupported_capabilities(document) == []
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert snapshot["document"]["slots"][0]["speech"] == speech


def test_only_audible_clips_become_audio_refs():
    document = _document()
    document["slots"][0]["speech"] = {"enabled": True, "audible": False, "clips": [
        {"id": "one", "audio": {"url": "/api/v1/file/one.wav"}, "audible": False},
        {"id": "two", "audio": {"url": "/api/v1/file/two.wav"}},
    ]}
    document["soundtrack"] = [{"id": "bed", "audio": {"url": "/api/v1/uploads/bed.wav"}}]
    assert unsupported_capabilities(document) == []
    refs = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]["refs"]
    assert [(ref["audioId"], ref["filename"], ref.get("root")) for ref in refs] == [
        ("soundtrack/bed", "bed.wav", "uploads"), ("subject_1/two", "two.wav", None)]


def test_publish_refuses_a_voiced_snapshot_without_its_audio_mix(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    snapshot = {
        "workspace": WORKSPACE,
        "document": _document(soundtrack=[{"id": "bed", "audio": {"url": "/api/v1/file/bed.wav"}}]),
        "refs": [],
        "plan": export_plan(_document()),
    }
    frames = [tmp_path / "frame_000001.png", tmp_path / "frame_000002.png"]
    for frame in frames:
        write_png(frame, 64, 64, (1, 2, 3))

    class _Token:
        def is_cancelled(self):
            return False

    with pytest.raises(RuntimeError, match="silent MP4"):
        service._publish(snapshot, tmp_path, frames, WORKSPACE, service._registry(WORKSPACE), "task", _Token())
    assert list(Path(service.workspace_dir(WORKSPACE)).glob("*.mp4")) == []


def test_owned_browser_script_uses_scene_clock_and_waits_for_assets():
    assert "world3d-render.html" in _OWNED_BROWSER_JS
    # The page and bridge are parameters so Video 2D reuses the same owned browser.
    assert "HOCUS_RENDER_BRIDGE || '__world3dExport'" in _OWNED_BROWSER_JS
    assert "window[name].load(scene, size)" in _OWNED_BROWSER_JS
    assert "window[name].frame(seconds)" in _OWNED_BROWSER_JS
    assert "/src/" not in _OWNED_BROWSER_JS


def test_bundled_template_refs_do_not_require_duplicate_workspace_uploads(tmp_path):
    document = _document()
    document["slots"][0].update(media="image", surface="cutout", sourceUrl="/examples/dark-fantasy/knight.png")
    frozen = freeze_export_command(_command(document=document))
    snapshot = frozen["effective"]["input"]["snapshot"]
    assert snapshot["refs"] == [{"slotId": "subject_1", "url": "/examples/dark-fantasy/knight.png", "kind": "image"}]
    _service(tmp_path)._assert_refs(snapshot["refs"], WORKSPACE)
    document["slots"][0]["sourceUrl"] = "/api/v1/file/missing.png"
    frozen = freeze_export_command(_command(document=document))
    with pytest.raises(Exception) as error:
        _service(tmp_path)._assert_refs(frozen["effective"]["input"]["snapshot"]["refs"], WORKSPACE)
    assert error.value.detail["code"] == "missing_ref"


def test_freeze_marks_uploads_gallery_file_urls():
    document = _document()
    document["slots"][0]["sourceUrl"] = "/api/v1/file/hero.glb?workspace=__uploads__"
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert snapshot["refs"] == [{
        "slotId": "subject_1", "url": "/api/v1/file/hero.glb?workspace=__uploads__",
        "kind": "model3d", "filename": "hero.glb", "root": "uploads",
    }]


def test_uploads_gallery_file_url_is_admitted(tmp_path):
    service = _service(tmp_path)
    (Path(service.uploads_dir()) / "hero.glb").write_bytes(b"glb")
    document = _document()
    document["slots"][0]["sourceUrl"] = "/api/v1/file/hero.glb?workspace=__uploads__"
    receipt = service.submit(_command(intent_id="world3d-uploads-gallery", document=document))
    assert receipt["receipt"]["taskIds"]


def test_uploads_prefix_url_is_admitted(tmp_path):
    service = _service(tmp_path)
    (Path(service.uploads_dir()) / "local.glb").write_bytes(b"glb")
    document = _document()
    document["slots"][0]["sourceUrl"] = "/api/v1/uploads/local.glb"
    snapshot = freeze_export_command(_command(document=document))["effective"]["input"]["snapshot"]
    assert snapshot["refs"][0]["root"] == "uploads"
    receipt = service.submit(_command(intent_id="world3d-uploads-prefix", document=document))
    assert receipt["receipt"]["taskIds"]


def test_scoped_workspace_file_url_is_admitted(tmp_path):
    service = _service(tmp_path)
    (Path(service.workspace_dir("assets")) / "shared.glb").write_bytes(b"glb")
    document = _document()
    document["slots"][0]["sourceUrl"] = "/api/v1/file/shared.glb?workspace=assets"
    receipt = service.submit(_command(intent_id="world3d-scoped", document=document))
    assert receipt["receipt"]["taskIds"]


def test_same_basename_in_export_workspace_does_not_admit_missing_scoped_file(tmp_path):
    service = _service(tmp_path)
    (Path(service.workspace_dir(WORKSPACE)) / "shared.glb").write_bytes(b"wrong")
    document = _document()
    document["slots"][0]["sourceUrl"] = "/api/v1/file/shared.glb?workspace=assets"
    with pytest.raises(Exception) as error:
        service.submit(_command(intent_id="world3d-scoped-missing", document=document))
    assert error.value.status_code == 409 and error.value.detail["code"] == "missing_ref"


@pytest.mark.parametrize("url", ["/examples/../private.png", "/examples/%2e%2e/private.png", "/examples/a%5cprivate.png"])
def test_bundled_template_refs_reject_traversal(url):
    document = _document()
    document["slots"][0]["sourceUrl"] = url
    with pytest.raises(Exception) as error:
        freeze_export_command(_command(document=document))
    assert error.value.detail["code"] == "missing_ref"


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
    assert task["status"] in {"queued", "waiting_resource", "running"}
    assert task["cancelable"] is True
    gate.set()
    _wait(registry, task["id"], {"completed", "failed"})
    forget_task_registry(registry.workspace_dir)


def test_render_waits_for_music_gpu_and_cancellation_does_not_need_the_lease(tmp_path):
    painted = []
    service = _service(tmp_path, renderer=lambda *a, **kw: _paint(*a, calls=painted, **kw))
    with resource_scheduler.coordinator.acquire(resource_scheduler.local_gpu_lane(0), task_id="music-in-progress"):
        receipt = service.submit(_command("waiting-render"))["receipt"]
        registry = service._registry(WORKSPACE)
        task_id = receipt["taskIds"][0]
        _wait(registry, task_id, {"waiting_resource"})
        assert painted == []
        service.cancel(WORKSPACE, "waiting-render")
        service._workers["waiting-render"].join(timeout=2)
        assert not service._workers["waiting-render"].is_alive()
        assert painted == []
        assert registry.get(task_id)["status"] == "cancelled"
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
    assert listed["maxVoicedDuration"] == 180
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


def test_draft_plan_is_unchanged_so_earlier_intents_still_replay():
    document = _document()
    assert export_plan(document) == export_plan(document, "draft")
    assert set(export_plan(document)) == {"width", "height", "fps", "duration", "count"}
    draft = freeze_export_command(_command())
    explicit = freeze_export_command(_command(quality="draft"))
    assert draft["effective"] == explicit["effective"]


def test_final_and_master_plans_carry_supersampling_and_msaa():
    final = export_plan(_document(), "final")
    master = export_plan(_document(), "master")
    assert (final["quality"], final["supersample"], final["samples"]) == ("final", 1.5, 4)
    assert (master["quality"], master["supersample"], master["samples"]) == ("master", 2, 4)
    assert (final["width"], final["height"]) == (64, 64), "the output size never changes with the level"
    assert freeze_export_command(_command(quality="final"))["fingerprint"] != freeze_export_command(_command())["fingerprint"]


def test_unknown_quality_is_refused_before_admission(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    with pytest.raises(Exception) as caught:
        service.submit(_command(quality="ultra"))
    assert caught.value.status_code == 422
    assert "quality" in caught.value.detail["message"]
    with pytest.raises(ValueError):
        export_plan(_document(), "ultra")


def test_quality_is_offered_in_the_catalog_and_capabilities():
    schema = command_catalog()[0]["inputSchema"]["properties"]["input"]["properties"]["quality"]
    assert schema["enum"] == ["draft", "final", "master"] and schema["default"] == "draft"
    assert export_capabilities()["qualities"] == ["draft", "final", "master"]


def test_each_level_encodes_with_its_profile(tmp_path, monkeypatch):
    import services.world3d_export as module

    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"mp4")
        return type("Done", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(module.shutil, "which", lambda _name: "/usr/bin/ffmpeg")
    monkeypatch.setattr(module.subprocess, "run", fake_run)
    monkeypatch.setattr(module, "validate_scene_recording_output", lambda *_args, **_kwargs: None)
    frame = tmp_path / "frames" / "frame_000001.png"
    write_png(frame, 4, 4, (1, 2, 3))
    for quality in ("draft", "final", "master"):
        mux_frame_sequence([frame], tmp_path / f"{quality}.mp4", fps=30, duration=1 / 30, quality=quality)
    settings = [(c[c.index("-preset") + 1], c[c.index("-crf") + 1], c[c.index("-threads") + 1]) for c in commands]
    assert settings == [("fast", "18", "1"), ("slow", "14", "0"), ("slow", "12", "0")]


def test_receipt_reports_the_quality_level(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    receipt = service.submit(_command(intent_id="world3d-final-1", quality="final"))["receipt"]
    registry = service._registry(WORKSPACE)
    _wait(registry, receipt["taskIds"][0], {"completed", "failed"})
    viewed = service.receipt(WORKSPACE, "world3d-final-1")
    assert viewed["receipt"]["quality"] == "final"
    assert viewed["task"]["metadata"]["quality"] == "final"
    forget_task_registry(registry.workspace_dir)


def test_final_and_master_plans_blur_motion_with_a_half_frame_shutter():
    final = export_plan(_document(), "final")
    master = export_plan(_document(), "master")
    assert (final["subframes"], final["shutter"]) == (4, 180)
    assert (master["subframes"], master["shutter"]) == (8, 180)
    assert "subframes" not in export_plan(_document()), "draft stays one sharp frame"


def test_shutter_overrides_and_pixel_worlds_stay_sharp():
    assert export_plan(_document(), "final", 90)["shutter"] == 90
    assert (export_plan(_document(), "master", 0)["subframes"], export_plan(_document(), "master", 0)["shutter"]) == (1, 0)
    pixel = export_plan(_document(pixelWorld={"pixelSize": 4, "levels": 16}), "master")
    assert (pixel["subframes"], pixel["shutter"]) == (1, 0)
    with pytest.raises(ValueError):
        export_plan(_document(), "final", 400)
    with pytest.raises(ValueError):
        export_plan(_document(), "draft", 180)


@pytest.mark.parametrize("patch", [{"shutter": 400}, {"shutter": "wide"}, {"shutter": True}, {"shutter": 180}])
def test_bad_or_draft_shutter_is_refused_before_admission(tmp_path, patch):
    service = _service(tmp_path, renderer=_paint)
    with pytest.raises(Exception) as caught:
        service.submit(_command(intent_id="world3d-shutter", **patch))
    assert caught.value.status_code == 422
    assert "shutter" in caught.value.detail["message"] or "Motion blur" in caught.value.detail["message"]


def test_catalog_offers_the_shutter():
    schema = command_catalog()[0]["inputSchema"]["properties"]["input"]["properties"]["shutter"]
    assert (schema["minimum"], schema["maximum"]) == (0, 360)
    assert export_capabilities()["motionBlur"]["default"] == 180


def _tone_wav(path: Path, seconds: float, rate: int = 48000) -> None:
    import math
    import struct
    import wave
    with wave.open(str(path), "wb") as out:
        out.setnchannels(2); out.setsampwidth(2); out.setframerate(rate)
        frames = bytearray()
        for index in range(int(seconds * rate)):
            value = int(12000 * math.sin(2 * math.pi * 440 * index / rate))
            frames += struct.pack("<hh", value, value)
        out.writeframes(bytes(frames))


def test_voiced_publish_muxes_the_page_mix_under_the_video(tmp_path):
    if not export_capabilities()["ffmpeg"]:
        pytest.skip("ffmpeg is required to mux the audio")
    service = _service(tmp_path, renderer=_paint)
    document = _document(duration=1, fps=24, soundtrack=[{"id": "bed", "audio": {"url": "/api/v1/file/bed.wav"}}])
    snapshot = {"workspace": WORKSPACE, "document": document, "refs": [], "plan": export_plan(document)}
    frames = []
    for index in range(24):
        frames.append(tmp_path / "frames" / f"frame_{index + 1:06d}.png")
        write_png(frames[-1], 64, 64, (index * 8, 40, 90))
    _tone_wav(tmp_path / "fx.wav", 1.0)

    class _Token:
        def is_cancelled(self):
            return False

    published = service._publish(snapshot, tmp_path, frames, WORKSPACE, service._registry(WORKSPACE), "task", _Token())
    output = Path(service.workspace_dir(WORKSPACE)) / published["name"]
    streams = probe_scene_recording_output(output)["streams"]
    assert sorted(item["codec_name"] for item in streams) == ["aac", "h264"]
    audio = next(item for item in streams if item["codec_type"] == "audio")
    assert abs(float(audio["duration"]) - 1.0) < 1 / 24 + 0.03


def test_a_failed_page_mix_is_reported_instead_of_a_silent_mp4(tmp_path):
    service = _service(tmp_path, renderer=_paint)
    document = _document(soundtrack=[{"id": "bed", "audio": {"url": "/api/v1/file/bed.wav"}}])
    (tmp_path / "audio-error.txt").write_text("Voice could not be loaded.")
    with pytest.raises(RuntimeError, match="Voice could not be loaded.*silent MP4"):
        service.finish_media({"document": document, "plan": export_plan(document)}, tmp_path, tmp_path / "encoded.mp4")
    assert "audio-error.txt" in _OWNED_BROWSER_JS


def test_geometry_warnings_from_the_render_page_reach_the_receipt(tmp_path):
    def painter(snapshot, staging, progress, cancelled):
        (Path(staging) / "geometry.json").write_text(json.dumps({
            "verdict": "fail", "samples": 8,
            "warnings": [{"code": "below_floor", "severity": "fail", "slot": "subject_1", "start": 0.25, "end": 1.0, "detail": "under"}]}))
        return _paint(snapshot, staging, progress, cancelled)

    service = _service(tmp_path, renderer=painter)
    receipt = service.submit(_command(intent_id="world3d-geometry-1"))["receipt"]
    registry = service._registry(WORKSPACE)
    _wait(registry, receipt["taskIds"][0], {"completed", "failed"})
    viewed = service.receipt(WORKSPACE, "world3d-geometry-1")
    assert viewed["task"]["status"] == "completed", "a warning never blocks the export"
    assert viewed["receipt"]["geometry"]["verdict"] == "fail"
    assert viewed["receipt"]["geometry"]["warnings"][0]["code"] == "below_floor"
    forget_task_registry(registry.workspace_dir)


def test_a_malformed_geometry_report_is_ignored(tmp_path):
    from services.world3d_export import read_geometry_report

    (tmp_path / "geometry.json").write_text("{not json")
    assert read_geometry_report(tmp_path) is None
    (tmp_path / "geometry.json").write_text(json.dumps({"verdict": "maybe"}))
    assert read_geometry_report(tmp_path) is None
    assert read_geometry_report(tmp_path / "missing") is None
