"""Cheap answers of the Studio generation routes, recorded before they leave launch.

These are the validation and error paths of ``POST /api/v1/generate``, retake,
extract-frames, edit-anything, inpaint, SAM status and segment preview, plus
one accepted ``POST /generate`` that the C0 fake engine finishes. They do not
re-record ``goldens/test_run_generation.json``. A real mask, a real SAM
preview and a retake that reads frames need a GPU and are not here.
"""
from __future__ import annotations

import shutil

import pytest

from tests.characterization import media
from tests.characterization.test_run_generation import BODY, Rig, _media_writer, worker_module
from tests.support.fake_wgp import FakeEngine, catalog_attributes, generation_attributes

_ROUTES = (
    "/api/v1/generate",
    "/api/v1/retake",
    "/api/v1/extract-frames",
    "/api/v1/edit-anything",
    "/api/v1/sam/status",
    "/api/v1/segment/preview",
    "/api/v1/inpaint",
)


def test_studio_routes_reject_incomplete_requests(server, golden, tmp_path) -> None:
    present = tmp_path / "empty.mp4"
    present.write_bytes(b"")
    present_path = str(present)
    server.check(golden, "generate requires model_type", "POST", "/api/v1/generate", json={})
    server.check(
        golden, "generate requires a prompt", "POST", "/api/v1/generate",
        json={"model_type": "fake_t2v"},
    )
    server.check(
        golden, "generate rejects an unknown model", "POST", "/api/v1/generate",
        json={"model_type": "not_a_model", "prompt": "a calm lake"},
    )
    server.check(
        golden, "generate rejects a non-integer priority", "POST", "/api/v1/generate",
        json={"priority": "high", "model_type": "fake_t2v", "prompt": "a calm lake"},
    )
    server.check(
        golden, "generate rejects an output name that leaves the workspace", "POST", "/api/v1/generate",
        json={"output_name": "../secret"},
    )
    server.check(
        golden, "generate rejects an unknown workspace collection", "POST", "/api/v1/generate",
        json={"provenance": {"workspace_id": "does-not-exist"}},
    )
    server.check(golden, "retake requires a video path", "POST", "/api/v1/retake", json={})
    server.check(
        golden, "retake video must exist", "POST", "/api/v1/retake",
        json={"video_path": "no-such-video.mp4"},
    )
    server.check(
        golden, "retake requires a model", "POST", "/api/v1/retake",
        json={"video_path": present_path},
    )
    server.check(golden, "extract-frames requires a video path", "POST", "/api/v1/extract-frames", json={})
    server.check(
        golden, "extract-frames video must exist", "POST", "/api/v1/extract-frames",
        json={"video_path": "no-such-video.mp4"},
    )
    server.check(
        golden, "extract-frames requires a time", "POST", "/api/v1/extract-frames",
        json={"video_path": present_path},
    )
    server.check(golden, "edit-anything requires a video path", "POST", "/api/v1/edit-anything", json={})
    server.check(
        golden, "edit-anything video must exist", "POST", "/api/v1/edit-anything",
        json={"video_path": "no-such-video.mp4"},
    )
    server.check(
        golden, "edit-anything requires a prompt", "POST", "/api/v1/edit-anything",
        json={"video_path": present_path},
    )
    server.check(
        golden, "edit-anything requires a model", "POST", "/api/v1/edit-anything",
        json={"video_path": present_path, "prompt": "Remove the boat."},
    )
    server.check(golden, "inpaint requires a video path", "POST", "/api/v1/inpaint", json={})
    server.check(
        golden, "inpaint requires a description", "POST", "/api/v1/inpaint",
        json={"video_path": "no-such-video.mp4"},
    )
    server.check(
        golden, "inpaint requires a model", "POST", "/api/v1/inpaint",
        json={"video_path": "no-such-video.mp4", "description": "replace the sky"},
    )
    server.check(
        golden, "inpaint video must exist", "POST", "/api/v1/inpaint",
        json={"video_path": "no-such-video.mp4", "description": "replace the sky", "model_type": "fake_t2v"},
    )
    server.check(golden, "segment preview requires a video path", "POST", "/api/v1/segment/preview", json={})
    server.check(
        golden, "segment preview requires text", "POST", "/api/v1/segment/preview",
        json={"video_path": "no-such-video.mp4"},
    )
    server.check(
        golden, "segment preview video must exist", "POST", "/api/v1/segment/preview",
        json={"video_path": "no-such-video.mp4", "text": "the boat"},
    )
    # The body is whichever SAM install this machine has. A box with the SAM
    # env answers "installed" or "ready" instead, so this golden is the answer
    # of a machine where the service is not installed. See the report.
    server.check(golden, "sam status", "GET", "/api/v1/sam/status")


def test_openapi_text_of_the_studio_generate_routes(server, golden) -> None:
    spec = server.client.get("/openapi.json").json()
    snapshot = {}
    for path in _ROUTES:
        operations = spec["paths"][path]
        for method, operation in operations.items():
            snapshot[f"{method.upper()} {path}"] = {
                "operationId": operation.get("operationId"),
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "parameters": operation.get("parameters", []),
            }
    golden.check("openapi", 200, snapshot)


@pytest.fixture
def generation(server, tmp_path, monkeypatch):
    """The C0 fake engine, installed the same way as ``test_run_generation.rig``."""
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        pytest.skip("ffmpeg and ffprobe are needed on PATH (CI installs them)")
    from services import job_lifecycle

    launch = worker_module()
    clip = media.video(tmp_path / "clip.mp4")
    engine = FakeEngine(write_media=_media_writer(clip))
    for name, value in {**catalog_attributes(), **generation_attributes(engine, server.wgp)}.items():
        monkeypatch.setattr(server.wgp, name, value, raising=False)
    monkeypatch.setattr(launch._durable_generation_queue, "path", str(tmp_path / "queue.json"))
    monkeypatch.setattr(launch, "_cached_hardware", {"gpu_vram_gb": 0.0})
    state = Rig(server=server, engine=engine, monkeypatch=monkeypatch)
    known = set(launch._jobs)

    def clear_queue() -> None:
        with job_lifecycle._generation_queue_condition:
            job_lifecycle._generation_queues.pop(id(launch._gen_lock), None)

    clear_queue()
    yield state
    try:
        state.settle()
    finally:
        for job_id in set(launch._jobs) - known:
            launch._jobs.pop(job_id, None)
        clear_queue()


def test_generate_accepts_a_minimal_job(generation, golden) -> None:
    answer = generation.post(dict(BODY))
    generation.join()
    golden.check(
        "generate accepts a minimal job",
        200,
        generation.server.normalise(answer, mask=("job_id", "task_id", "root_task_id")),
    )
