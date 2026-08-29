import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import model3d_service


WORKER_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "hunyuan3d" / "worker.py"


def _load_worker():
    spec = importlib.util.spec_from_file_location("hunyuan3d_worker_under_test", WORKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_prepare_request_rejects_decode_chunks_that_can_oom_the_host():
    request = model3d_service._prepare_request(
        {
            "prompt": "a wooden chair",
            "num_chunks": 500000,
            "octree_resolution": 256,
        },
        {},
        None,
    )
    assert request["settings"]["num_chunks"] == model3d_service._MAX_DECODE_CHUNKS
    assert request["settings"]["num_chunks"] <= 40000


def test_prepare_request_tightens_chunks_when_octree_is_512():
    request = model3d_service._prepare_request(
        {
            "prompt": "a wooden chair",
            "num_chunks": 40000,
            "octree_resolution": 512,
        },
        {},
        None,
    )
    assert request["settings"]["octree_resolution"] == 512
    assert request["settings"]["num_chunks"] == model3d_service._MAX_CHUNKS_AT_OCTREE_512


def test_prepare_request_tightens_chunks_when_octree_is_384():
    request = model3d_service._prepare_request(
        {
            "prompt": "a wooden chair",
            "num_chunks": 40000,
            "octree_resolution": 384,
        },
        {},
        None,
    )
    assert request["settings"]["num_chunks"] == model3d_service._MAX_CHUNKS_AT_OCTREE_384


def test_safe_decode_chunks_keeps_sane_minimum():
    assert model3d_service._safe_decode_chunks(100, 128) == 1000


def test_guard_mesh_complexity_reduces_only_when_over_the_hang_limit():
    worker = _load_worker()
    small = SimpleNamespace(faces=list(range(1000)))
    huge = SimpleNamespace(faces=list(range(worker._MAX_TEXTURE_FACES + 50)))
    reduced = SimpleNamespace(faces=list(range(10)))

    def fake_reduce(mesh, max_faces):
        assert mesh is huge
        assert max_faces == worker._MAX_TEXTURE_FACES
        return reduced

    worker.reduce_faces = fake_reduce
    assert worker.guard_mesh_complexity(small, {}, for_texture=True) is small
    assert worker.guard_mesh_complexity(huge, {}, for_texture=True) is reduced


def test_guard_mesh_complexity_fails_closed_when_simplify_cannot_meet_hang_limit():
    worker = _load_worker()
    huge = SimpleNamespace(faces=list(range(worker._MAX_TEXTURE_FACES + 50)))

    def fake_reduce(mesh, max_faces):
        assert mesh is huge
        assert max_faces == worker._MAX_TEXTURE_FACES
        return mesh

    worker.reduce_faces = fake_reduce
    with pytest.raises(RuntimeError, match="after simplification"):
        worker.guard_mesh_complexity(huge, {}, for_texture=True)


def test_guard_mesh_complexity_honors_user_face_target():
    worker = _load_worker()
    mesh = SimpleNamespace(faces=list(range(80_000)))
    seen = {}

    def fake_reduce(current, max_faces):
        seen["max_faces"] = max_faces
        return current

    worker.reduce_faces = fake_reduce
    worker.guard_mesh_complexity(
        mesh,
        {"reduce_face": True, "target_face_num": 40_000},
        for_texture=True,
    )
    assert seen["max_faces"] == 40_000


def test_heartbeat_emits_newlines_so_the_parent_watchdog_stays_alive(monkeypatch):
    worker = _load_worker()
    events = []

    def capture(phase, progress, message):
        events.append((phase, progress, message))

    monkeypatch.setattr(worker, "event", capture)
    with worker.Heartbeat("shape", 0.38, "Generating 3D geometry", interval=0.05):
        worker.time.sleep(0.16)
    assert events
    assert all(phase == "shape" for phase, _progress, _message in events)
    assert any("elapsed" in message for _phase, _progress, message in events)
