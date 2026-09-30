"""Scene export shares a CPU lane. Fakes stand in for Chromium and ffmpeg."""
from __future__ import annotations

import threading
import time
from pathlib import Path

from services import resource_scheduler
from services.resource_scheduler import ResourceCoordinator, cpu_lane
from services.scene2d_export import OPERATION, scene_export_concurrency, scene_export_lane
from services.task_manager import TaskRegistry
from services.world3d_export import write_png

WORKSPACE = "x-song"


def _layer(layer_id="bg"):
    return {"id": layer_id, "name": layer_id, "type": "image", "source": f"/api/v1/file/{layer_id}.png?workspace={WORKSPACE}",
            "visible": True, "z": 0, "transform": {"x": 50, "y": 50, "scale": 1, "opacity": 1},
            "animation": {"start": {"x": 50, "y": 50, "scale": 1}, "end": {"x": 50, "y": 50, "scale": 1}, "duration": 1, "curve": "ease"}}


def _document(**overrides):
    document = {"version": 1, "name": "Intro", "width": 64, "height": 36, "fps": 24, "duration": 0.25, "layers": [_layer()]}
    document.update(overrides)
    return document


def _command(intent, document):
    return {"version": 1, "operation": OPERATION, "intent_id": intent, "input": {"workspace": WORKSPACE, "document": document}}


def _service(tmp_path, renderer):
    from services.scene2d_export import Scene2DExportService

    def workspace_dir(name: str) -> str:
        path = Path(tmp_path) / name
        path.mkdir(parents=True, exist_ok=True)
        return str(path)

    uploads = tmp_path / "uploads"
    uploads.mkdir(exist_ok=True)
    return Scene2DExportService(
        workspace_dir=workspace_dir,
        registry_for=lambda name: TaskRegistry(workspace_dir(name), interrupt_stale=False),
        renderer=renderer,
        uploads_dir=lambda: str(uploads),
    )


def _mux(_frames, encoded, fps, duration):
    del fps, duration
    Path(encoded).write_bytes(b"mp4")


def _wait(service, receipts):
    registry = service._registry(WORKSPACE)
    task_ids = [item["receipt"]["taskIds"][0] for item in receipts]
    deadline = time.time() + 8
    while time.time() < deadline:
        tasks = [registry.get(task_id) or {} for task_id in task_ids]
        if tasks and all(task.get("status") in {"completed", "failed", "cancelled"} for task in tasks):
            return tasks
        time.sleep(0.01)
    return [registry.get(task_id) for task_id in task_ids]


def test_concurrency_is_two_unless_the_value_is_outside_one_to_four(monkeypatch):
    monkeypatch.delenv("HOCUS_SCENE_EXPORT_CONCURRENCY", raising=False)
    assert scene_export_concurrency() == 2
    for raw, expected in (("1", 1), ("3", 3), ("4", 4), ("0", 1), ("5", 1), ("-1", 1), ("abc", 1), ("2.5", 1), ("", 2)):
        monkeypatch.setenv("HOCUS_SCENE_EXPORT_CONCURRENCY", raw)
        assert scene_export_concurrency() == expected


def test_cpu_lane_capacity_rejects_zero_and_bools():
    assert cpu_lane().capacity == 1
    assert cpu_lane("scene2d-render", capacity=3).capacity == 3
    assert cpu_lane("scene2d-render", capacity=0).capacity == 1
    assert cpu_lane("scene2d-render", capacity=True).capacity == 1
    assert cpu_lane("scene2d-render", capacity=2).key == cpu_lane("scene2d-render").key


def test_two_exports_of_one_document_and_of_two_documents_finish(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUS_SCENE_EXPORT_CONCURRENCY", "2")
    monkeypatch.setattr(resource_scheduler, "coordinator", ResourceCoordinator())
    monkeypatch.setattr("services.world3d_export.mux_frame_sequence", _mux)
    active = {"n": 0, "peak": 0}
    lock = threading.Lock()
    hold = {"barrier": threading.Barrier(2)}

    def renderer(snapshot, staging, progress, cancelled):
        del snapshot, staging, progress, cancelled
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        hold["barrier"].wait(timeout=5)
        with lock:
            active["n"] -= 1
        return []

    service = _service(tmp_path, renderer)
    write_png(Path(service.workspace_dir(WORKSPACE)) / "bg.png", 8, 8, (10, 20, 30))
    same = _document()
    started = time.perf_counter()
    same_tasks = _wait(service, [
        service.submit(_command("same-a", same)),
        service.submit(_command("same-b", same)),
    ])
    pair_s = time.perf_counter() - started
    print(f"SCENE_EXPORT_PAIR_S={pair_s:.3f}")
    assert [task["status"] for task in same_tasks] == ["completed", "completed"]
    assert active["peak"] == 2
    hold["barrier"] = threading.Barrier(2)
    other = _document(name="Other")
    diff_tasks = _wait(service, [
        service.submit(_command("diff-a", same)),
        service.submit(_command("diff-b", other)),
    ])
    assert [task["status"] for task in diff_tasks] == ["completed", "completed"]
    assert active["peak"] == 2


def test_capacity_one_runs_one_export_at_a_time(tmp_path, monkeypatch):
    monkeypatch.setenv("HOCUS_SCENE_EXPORT_CONCURRENCY", "1")
    monkeypatch.setattr(resource_scheduler, "coordinator", ResourceCoordinator())
    monkeypatch.setattr("services.world3d_export.mux_frame_sequence", _mux)
    active = {"n": 0, "peak": 0}
    lock = threading.Lock()
    entered = threading.Event()
    release = threading.Event()

    def renderer(snapshot, staging, progress, cancelled):
        del snapshot, staging, progress, cancelled
        with lock:
            active["n"] += 1
            active["peak"] = max(active["peak"], active["n"])
        entered.set()
        assert release.wait(timeout=5)
        with lock:
            active["n"] -= 1
        return []

    service = _service(tmp_path, renderer)
    write_png(Path(service.workspace_dir(WORKSPACE)) / "bg.png", 8, 8, (10, 20, 30))
    document = _document()
    other = _document(name="Other")
    receipts = [service.submit(_command("serial-a", document)), service.submit(_command("serial-b", other))]
    assert entered.wait(timeout=5)
    time.sleep(0.05)
    assert active["peak"] == 1
    assert active["n"] == 1
    release.set()
    tasks = _wait(service, receipts)
    assert [task["status"] for task in tasks] == ["completed", "completed"]
    assert active["peak"] == 1


def test_preview_acquires_the_export_lane_without_starting_a_server(monkeypatch):
    monkeypatch.setenv("HOCUS_SCENE_EXPORT_CONCURRENCY", "3")
    seen = {}

    class _Lease:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def acquire(lane, **_kwargs):
        seen["lane"] = lane
        return _Lease()

    monkeypatch.setattr(resource_scheduler.coordinator, "acquire", acquire)
    monkeypatch.setattr("services.video2d_preview._serve_and_paint", lambda *_args: b"png")
    from services.video2d_preview import _paint_on_lane
    assert _paint_on_lane({"version": 1}, [0.0], (8, 8, 24)) == b"png"
    assert seen["lane"].capacity == 3
    assert seen["lane"].key == scene_export_lane().key
    assert seen["lane"].key == "local_cpu:scene2d-render"
