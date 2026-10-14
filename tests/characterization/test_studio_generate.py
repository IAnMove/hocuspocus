"""Cheap answers of the Studio generation routes, recorded before they leave launch.

These are the validation and error paths of ``POST /api/v1/generate``, retake,
extract-frames, edit-anything, inpaint, SAM status, segment preview, outpaint
and blend, plus accepted jobs that the C0 fake engine finishes. They do not
re-record ``goldens/test_run_generation.json``. A real mask, a real SAM
preview and a retake that reads frames need a GPU and are not here.

The Recast routes at the bottom were recorded the same way, on the tree where
both handlers still live in launch. Detection and reference preparation are
stubbed, so a golden never downloads SAM or a LoRA. The JPEG bytes of a
preview are encoder-dependent, so the golden keeps the decoded image's shape.
"""
from __future__ import annotations

import ast
import base64
import io
import json
import re
import shutil
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import replace as _replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.hardware_probe import hardware_cache

from tests.characterization import media
from tests.characterization.test_run_generation import (
    RECAST_MODULES, SHOT_MODULES, BODY, Rig, _media_writer, worker_module,
)
# Fixtures, used by name: the C0 rig and its decodable clip.
from tests.characterization.test_run_generation import (  # noqa: F401
    WAIT, _refuse_remote_network, _stub_legacy_h3, clip, rig,
)
from tests.support.fake_wgp import FakeEngine, catalog_attributes, default_script, generation_attributes

_ROUTES = (
    "/api/v1/generate",
    "/api/v1/retake",
    "/api/v1/extract-frames",
    "/api/v1/edit-anything",
    "/api/v1/sam/status",
    "/api/v1/segment/preview",
    "/api/v1/inpaint",
)


def test_studio_routes_reject_incomplete_requests(server, golden, tmp_path, monkeypatch) -> None:
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
    # The answer of a machine where the SAM service is not installed and nothing
    # listens on its port. The status reads both, so they are pinned here: a
    # machine with the SAM env would answer "installed" or "ready" instead.
    from services import inpaint_service

    def no_sam_service(*_args, **_kwargs):
        raise inpaint_service.requests.ConnectionError("no SAM service in tests")

    monkeypatch.setattr(inpaint_service, "requests", SimpleNamespace(
        get=no_sam_service, ConnectionError=inpaint_service.requests.ConnectionError))
    monkeypatch.setattr(inpaint_service, "_find_sam_env", lambda: None)
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
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 0.0})
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


# -- What each Studio route hands the worker (C3 review, recorded on the pre-move tree 8b2cd46cd) --------------------
# The cases below drive the routes with the C0 rig (``test_run_generation.rig``): every accepted job runs the real
# worker against the fake engine, and the observation keeps the job's own params (what the route built), what the
# engine received and what the worker left behind. Edit routes probe their source with decord, which CI may not
# have: ``_probe_as`` gives them a fixed 48-frame, 24 fps, 96x64 clip.

# Thread names (``Thread-N (target)``) of the edit routes' workers: production names them ``_run_generation``; under
# the rig the pre-move tree starts the rig's own ``run_generation`` wrapper.
_EDIT_WORKERS = ("(_run_generation)", "(run_generation)")
_FRAME_NAME = (r"frame_[0-9a-f]{8}_", "frame_<ID>_")


def _probe_as(monkeypatch) -> None:
    import numpy

    class VideoReader:
        def __init__(self, path: str) -> None:
            self.path = path

        def get_avg_fps(self) -> float:
            return 24.0

        def __len__(self) -> int:
            return 48

        def __getitem__(self, index: int):
            frame = numpy.zeros((64, 96, 3), dtype="uint8")
            return SimpleNamespace(shape=frame.shape, asnumpy=lambda: frame)

    monkeypatch.setitem(sys.modules, "decord", SimpleNamespace(VideoReader=VideoReader))


def _join_edit_workers() -> None:
    for thread in [t for t in threading.enumerate() if t.name.endswith(_EDIT_WORKERS)]:
        thread.join(WAIT)
        assert not thread.is_alive(), "an edit route's generation worker did not finish"


def _submit(rig, path: str, body: dict) -> tuple[int, dict]:
    response = rig.server.client.post(path, json=body)
    answer = response.json()
    if response.status_code == 200 and isinstance(answer, dict) and "job_id" in answer:
        rig.job_ids.append(answer["job_id"])
        rig.accepted[answer["job_id"]] = answer
    return response.status_code, answer


def _params(rig, job_id: str) -> dict:
    """The params the route built for the job, as JSON (what the worker and the sidecar start from)."""
    return json.loads(json.dumps(rig.launch._jobs[job_id].get("params") or {}, default=str, sort_keys=True))


def _job(rig, job_id: str, since: int = 0) -> dict:
    """The C0 observation of one job, with only the engine calls made since ``since`` and the route's params."""
    observed = rig.observe(job_id)
    observed["engine_calls"] = observed["engine_calls"][since:]
    return {**observed, "params": _params(rig, job_id)}


def _source(rig, name: str = "source.mp4", *, folder: Path | None = None) -> Path:
    target = (folder or rig.server.outputs) / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"not decoded: decord is faked")
    return target


def test_generate_hands_the_worker_what_it_built(rig, golden, tmp_path) -> None:
    loras = tmp_path / "loras"
    loras.mkdir()
    (loras / "style.safetensors").write_bytes(b"lora")
    rig.set_wgp("get_lora_dir", lambda *_args, **_kwargs: str(loras))
    uploads = rig.server.root / "uploads"
    media.image(uploads / "start.png")
    media.image(uploads / "end.png")
    cases = {
        "loras and a priority": {**BODY, "activated_loras": ["style.safetensors"], "loras_multipliers": "0.8",
                                 "priority": 3},
        "image to video with start and end images": {**BODY, "model_type": "fake_i2v", "image_prompt_type": "SE",
                                                     "image_start": "uploads/start.png",
                                                     "image_end": "uploads/end.png"},
        "stale prompt types are stripped": {**BODY, "image_prompt_type": "S", "video_prompt_type": "I"},
        "a spoofed execution mode is replaced": {**BODY, "_execution_mode": "simulate"},
        "sliding window safety bump": {**BODY, "video_length": 81, "sliding_window_size": 81},
        "a multi-line prompt without the scheduler": {**BODY, "prompt": "line one\nline two"},
        "an output name": {**BODY, "output_name": "my-clip"},
    }
    observed = {}
    for case, body in cases.items():
        since = len(rig.engine.calls)
        job_id = rig.run(body)
        observed[case] = _job(rig, job_id, since)
    rig.check(golden, "generate builds the job", observed)


def test_generate_rejections_before_a_job_exists(rig, golden, monkeypatch) -> None:
    from services import execution_mode

    rejected = {}

    def post(case: str, body: dict) -> None:
        response = rig.server.client.post("/api/v1/generate", json=body)
        rejected[case] = {"status": response.status_code, "body": response.json()}

    post("sfx job in a workspace outside the outputs", {"model_type": "mmaudio_fake", "sfx_mode": True,
                                                        "workspace": "../outside"})
    monkeypatch.setattr(execution_mode, "POLICY", _replace(execution_mode.POLICY, mode="plan"))
    post("plan mode", dict(BODY))
    monkeypatch.setattr(execution_mode, "POLICY", _replace(execution_mode.POLICY, mode="simulate",
                                                           workspace="simulated-ws"))
    post("simulate mode refuses another workspace", dict(BODY))
    rejected["jobs created"] = [job_id for job_id in rig.launch._jobs if job_id in rig.job_ids]
    rejected["queued"] = [record["id"] for record in rig.launch._durable_generation_queue.list()]
    rig.check(golden, "generate rejections", rejected)


def test_generate_passes_a_start_image_outside_the_uploads_through(rig, golden) -> None:
    """Not a path check: the route keeps a start image that is not an upload reference as it came."""
    job_id = rig.run({**BODY, "model_type": "fake_i2v", "image_prompt_type": "S", "image_start": "../../etc/passwd"})
    rig.check(golden, "generate start image outside the uploads", _job(rig, job_id))


def test_generate_answers_a_leftover_duplicate_instead_of_queueing(rig, golden) -> None:
    """A durable queue record that is not a live job (a leftover from before a restart) with the same content: the
    route answers it (``_job_leftovers.duplicate_for_submit``) and starts nothing. A live job is no duplicate."""
    launch = rig.launch
    # Built and persisted by the server's own factory, but never live and holding no queue place.
    leftover = launch._new_generation_job(dict(BODY), "default", job_id="leftover-1", created_at=1_700_000_000.0,
                                          reserve_generation=False)
    launch._persist_generation_job(leftover)
    response = rig.server.client.post("/api/v1/generate", json=dict(BODY))
    duplicate = {"status": response.status_code, "body": response.json()}
    other = rig.run({**BODY, "prompt": "another lake"})
    rig.check(golden, "generate leftover duplicate", {
        "duplicate": duplicate, "engine prompts": [call["prompt"] for call in rig.engine.calls],
        "queued": sorted(record["id"] for record in launch._durable_generation_queue.list() if record["id"] != other),
    })


def _h3_def(**extra) -> dict:
    return {"name": "Fake H3", "architecture": "minimax_h3", "fps": 24, "URLs": [],
            "minimax_h3_text_encoder_variants": {"bf16": {}, "nvfp4_awq": {}},
            "minimax_h3_text_encoder_default": "bf16", **extra}


def test_generate_h3_gates(rig, golden, monkeypatch) -> None:
    from services import minimax_h3_service

    definitions = {"fake_h3": _h3_def(), minimax_h3_service.MODEL_ID: {"name": "Legacy H3", "URLs": []}}
    real_def = rig.server.wgp.get_model_def
    rig.set_wgp("get_model_def", lambda model_type: definitions.get(model_type) or real_def(model_type))
    long_line = " ".join(["Remember every word of this long promise we made together"] * 12)
    answers = {}

    def post(case: str, body: dict) -> None:
        response = rig.server.client.post("/api/v1/generate", json=body)
        answers[case] = {"status": response.status_code, "body": response.json()}

    post("h3 dialogue longer than one clip", {**BODY, "model_type": "fake_h3", "video_length": 124,
                                              "prompt": f'A woman says "{long_line}"'})
    post("h3 dialogue longer than the model, legacy audio policy",
         {**BODY, "model_type": "fake_h3", "minimax_h3_audio_policy": "legacy",
          "prompt": f'A woman says "{long_line} {long_line}"'})
    post("h3 unknown text encoder", {**BODY, "model_type": "fake_h3", "minimax_h3_text_encoder": "int3"})
    post("legacy h3 character sheet without references",
         {**BODY, "model_type": minimax_h3_service.MODEL_ID,
          "character_sheet_engine": minimax_h3_service.CHARACTER_SHEET_ENGINE})
    since = len(rig.engine.calls)
    native = rig.run({**BODY, "model_type": "fake_h3", "video_length": 124, "minimax_h3_window_storyboard": False,
                      "prompt": 'A man whispers "see you soon" and leaves.'})
    answers["native h3 job"] = _job(rig, native, since)
    calls: list = []
    _stub_legacy_h3(rig, calls)
    legacy = rig.run({**BODY, "model_type": minimax_h3_service.MODEL_ID, "minimax_h3_turbo_mode": True,
                      "activated_loras": ["x.safetensors"], "minimax_h3_references": [{"type": "image"}]})
    answers["legacy h3 job params"] = _params(rig, legacy)
    answers["legacy h3 service calls"] = calls
    rig.check(golden, "generate h3 gates", answers)


def test_retake_and_edit_anything_jobs(rig, golden, monkeypatch, tmp_path) -> None:
    _probe_as(monkeypatch)
    # The worker fetches a managed LoRA (Edit Anything) from Hugging Face when it is missing; a test never does.
    managed: list = []
    rig.patch("_ensure_managed_loras_present",
              lambda activated, model_type, progress=None: managed.append([list(activated or []), model_type]) or [])
    source = _source(rig)
    uploads = rig.server.root / "uploads"
    media.image(uploads / "anchor_start.png")
    observed = {}
    requests = {
        "retake": ("/api/v1/retake", {"video_path": source.name, "model_type": "fake_t2v", "prompt": "a storm",
                                      "start_time": 0.5, "end_time": 1.5, "seed": 7,
                                      "loras_multipliers": "1.0;0.5 0.8"}),
        "edit anything": ("/api/v1/edit-anything", {"video_path": str(source), "model_type": "fake_t2v",
                                                    "prompt": " Remove the boat. ", "lora_strength": 3,
                                                    "activated_loras": ["mine.safetensors"],
                                                    "start_anchor_path": "anchor_start.png", "end_time": 1.0}),
        "edit anything from uploads": ("/api/v1/edit-anything", {"video_path": "elsewhere/source.mp4",
                                                                 "model_type": "fake_t2v",
                                                                 "prompt": "Convert the video into a anime style."}),
    }
    media_copy = uploads / "source.mp4"
    media_copy.write_bytes(b"not decoded")
    for case, (path, body) in requests.items():
        status, answer = _submit(rig, path, body)
        _join_edit_workers()
        observed[case] = {"status": status, "answer": answer}
        if status == 200:
            observed[case]["job"] = _job(rig, answer["job_id"])
    rejected = {}
    for case, (path, body) in {
        "retake with an empty range": ("/api/v1/retake", {"video_path": str(source), "model_type": "fake_t2v",
                                                           "start_time": 3, "end_time": 1}),
        "retake media outside its roots": ("/api/v1/retake", {"video_path": "/etc/passwd", "wangp_media": True,
                                                               "model_type": "fake_t2v"}),
        "edit anything with an empty range": ("/api/v1/edit-anything", {"video_path": str(source), "prompt": "x",
                                                                         "model_type": "fake_t2v",
                                                                         "start_time": 5}),
    }.items():
        status, answer = _submit(rig, path, body)
        rejected[case] = {"status": status, "answer": answer}
    observed["rejected"] = rejected
    observed["managed lora checks"] = managed
    rig.check(golden, "retake and edit anything", observed)


def test_edit_routes_refuse_a_value_that_is_not_a_number(rig, golden, monkeypatch) -> None:
    """Retake, Edit Anything, Inpaint, frame extraction and Recast answer 422 and name the field, before the
    video is read, SAM runs or a job is registered (they answered 500)."""
    from services import inpaint_service

    _probe_as(monkeypatch)
    # Inpaint stops SAM before it registers the job; nothing listens in a test.
    monkeypatch.setattr(inpaint_service, "shutdown_sam", lambda: None)
    source = _source(rig)
    media.image(rig.server.outputs / "ref.png")
    jobs_before = set(rig.launch._jobs)
    video = {"video_path": str(source), "model_type": "fake_t2v"}
    cases = {
        "retake start_time": ("/api/v1/retake", {**video, "start_time": "abc"}),
        "retake end_time": ("/api/v1/retake", {**video, "end_time": {}}),
        "retake retake_strength": ("/api/v1/retake", {**video, "retake_strength": "strong"}),
        "edit anything start_time": ("/api/v1/edit-anything", {**video, "prompt": "Remove the boat.", "start_time": "x"}),
        "edit anything lora_strength": ("/api/v1/edit-anything",
                                        {**video, "prompt": "Remove the boat.", "lora_strength": "max"}),
        "edit anything guidance_scale": ("/api/v1/edit-anything",
                                         {**video, "prompt": "Remove the boat.", "guidance_scale": None}),
        "edit anything num_inference_steps": ("/api/v1/edit-anything",
                                              {**video, "prompt": "Remove the boat.", "num_inference_steps": "8.5"}),
        "edit anything retake_strength": ("/api/v1/edit-anything",
                                          {**video, "prompt": "Remove the boat.", "retake_strength": "x"}),
        "inpaint start_time": ("/api/v1/inpaint", {**video, "description": "the sky", "sam_target": "sky",
                                                    "start_time": "abc"}),
        "inpaint mask_padding": ("/api/v1/inpaint", {**video, "description": "the sky", "sam_target": "sky",
                                                      "mask_padding": "wide"}),
        # Read after SAM had run before: now before anything.
        "inpaint guidance_scale": ("/api/v1/inpaint", {**video, "description": "the sky", "sam_target": "sky",
                                                        "guidance_scale": "high"}),
        "inpaint num_inference_steps": ("/api/v1/inpaint", {**video, "description": "the sky", "sam_target": "sky",
                                                             "num_inference_steps": "many"}),
        "inpaint retake_strength": ("/api/v1/inpaint", {**video, "description": "the sky", "sam_target": "sky",
                                                         "retake_strength": "x"}),
        "extract frames start_time": ("/api/v1/extract-frames", {"video_path": str(source), "start_time": "abc"}),
        "extract frames end_time": ("/api/v1/extract-frames", {"video_path": str(source), "end_time": "soon"}),
        "recast start_time": ("/api/v1/recast", {"video_path": str(source), "ref_image_path": "ref.png",
                                                  "start_time": "abc", "end_time": 2}),
        "recast end_time alone": ("/api/v1/recast", {"video_path": str(source), "ref_image_path": "ref.png",
                                                      "end_time": "soon"}),
    }
    answers = {}
    for case, (path, body) in cases.items():
        status, answer = _submit(rig, path, body)
        answers[case] = {"status": status, "answer": answer}
    answers["jobs registered"] = sorted(set(rig.launch._jobs) - jobs_before)
    answers["uploads"] = sorted(path.name for path in (rig.server.root / "uploads").glob("*"))
    rig.check(golden, "edit routes refuse values that are not numbers", answers)


def test_edit_routes_follow_the_execution_mode(rig, golden, monkeypatch) -> None:
    from services import execution_mode, inpaint_service

    _probe_as(monkeypatch)
    # Inpaint stops SAM before it registers the job; nothing listens in a test.
    monkeypatch.setattr(inpaint_service, "shutdown_sam", lambda: None)
    source = _source(rig)
    monkeypatch.setattr(execution_mode, "POLICY", _replace(execution_mode.POLICY, mode="plan"))
    answers = {}
    for case, (path, body) in {
        "retake": ("/api/v1/retake", {"video_path": str(source), "model_type": "fake_t2v"}),
        "edit anything": ("/api/v1/edit-anything", {"video_path": str(source), "model_type": "fake_t2v",
                                                    "prompt": "Remove the boat."}),
        "inpaint": ("/api/v1/inpaint", {"video_path": str(source), "model_type": "fake_t2v",
                                        "description": "the sky", "sam_target": "sky",
                                        "masks_path": str(_source(rig, "mask.npy"))}),
    }.items():
        status, answer = _submit(rig, path, body)
        answers[case] = {"status": status, "answer": answer}
    answers["jobs created"] = [job_id for job_id in rig.launch._jobs if job_id in rig.job_ids]
    rig.check(golden, "edit routes in plan mode", answers)


def test_inpaint_jobs(rig, golden, monkeypatch, tmp_path) -> None:
    import numpy

    from services import inpaint_service

    _probe_as(monkeypatch)
    calls: list = []
    uploads = rig.server.root / "uploads"
    source = _source(rig, "inpaint.mp4", folder=uploads)
    cached = tmp_path / "cached_masks.npy"
    numpy.save(cached, numpy.zeros((2, 4, 4), dtype=bool))
    sam_masks = tmp_path / "sam_masks.npy"
    numpy.save(sam_masks, numpy.zeros((2, 4, 4), dtype=bool))
    sam = {"ready": True}

    def segment_video(**kwargs):
        calls.append(["segment_video", {key: (Path(value).name if key == "video_path" else value)
                                        for key, value in sorted(kwargs.items())}])
        return {"masks_path": str(sam_masks)}

    monkeypatch.setattr(inpaint_service, "ensure_sam_running", lambda: calls.append(["ensure"]) or sam["ready"])
    monkeypatch.setattr(inpaint_service, "shutdown_sam", lambda: calls.append(["shutdown"]))
    monkeypatch.setattr(inpaint_service, "segment_video", segment_video)
    monkeypatch.setattr(inpaint_service, "parse_inpaint_intent",
                        lambda description: calls.append(["intent", description])
                        or {"target": "the sky", "prompt": "a red sky", "negative_prompt": "grey"})
    observed = {}
    for case, body in {
        "cached mask and explicit target": {"video_path": "inpaint.mp4", "description": "make it red",
                                            "model_type": "fake_t2v", "sam_target": "sky",
                                            "masks_path": str(cached), "start_time": 0.5,
                                            "loras_multipliers": "1;2"},
        "sam mask, parsed intent, inverted": {"video_path": str(source), "description": "the sky goes red",
                                              "model_type": "fake_t2v", "invert_mask": True,
                                              "mask_padding": 4, "end_time": 1.0},
    }.items():
        status, answer = _submit(rig, "/api/v1/inpaint", body)
        _join_edit_workers()
        observed[case] = {"status": status, "answer": answer}
        if status == 200:
            observed[case]["job"] = _job(rig, answer["job_id"])
    observed["mask inverted"] = bool(numpy.load(sam_masks).all())
    sam["ready"] = False
    status, answer = _submit(rig, "/api/v1/inpaint", {"video_path": str(source), "description": "x",
                                                      "model_type": "fake_t2v", "sam_target": "sky"})
    observed["sam not available"] = {"status": status, "answer": answer}
    observed["service calls"] = calls
    rig.check(golden, "inpaint", observed)


def test_extract_frames_writes_png_frames(server, golden, clip) -> None:
    folder = server.outputs
    shutil.copyfile(clip, folder / "clip.mp4")
    answers = {}
    for case, body in {
        "start and end from the workspace": {"video_path": "clip.mp4", "start_time": 0, "end_time": 0.5},
        "end only, absolute": {"video_path": str(folder / "clip.mp4"), "end_time": 0.25},
        "wangp media outside its roots": {"video_path": "/etc/passwd", "wangp_media": True, "start_time": 0},
    }.items():
        response = server.client.post("/api/v1/extract-frames", json=body)
        answers[case] = {"status": response.status_code, "body": response.json()}
    uploads = server.root / "uploads"
    names = [re.sub(*_FRAME_NAME, path.name) for path in uploads.iterdir()] if uploads.exists() else []
    answers["uploads"] = sorted(names)
    golden.check("extract frames", 200, server.normalise(answers, replace=(_FRAME_NAME,)))


def test_segment_preview_and_sam_status_with_sam_stubbed(server, golden, monkeypatch, tmp_path) -> None:
    import base64
    import io

    import numpy
    from PIL import Image

    from services import inpaint_service

    uploads = server.root / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    (uploads / "shot.mp4").write_bytes(b"not decoded")
    masks = tmp_path / "preview_masks.npy"
    numpy.save(masks, numpy.zeros((1, 2, 2), dtype=bool))
    buffer = io.BytesIO()
    Image.new("RGB", (2, 1), (10, 200, 10)).save(buffer, format="PNG")
    preview = base64.b64encode(buffer.getvalue()).decode()
    calls: list = []
    outcome = {"ready": True, "raise": None}

    def segment_image_preview(**kwargs):
        calls.append(["preview", {key: (Path(value).name if key == "video_path" else value)
                                  for key, value in sorted(kwargs.items())}])
        if outcome["raise"] is not None:
            raise outcome["raise"]
        return {"mask_preview": preview, "masks_path": str(masks), "frame_index": 3}

    def segment_video(**kwargs):
        calls.append(["video", {key: (Path(value).name if key == "video_path" else value)
                                for key, value in sorted(kwargs.items())}])
        return {"masks_path": str(masks), "frames": 2}

    monkeypatch.setattr(inpaint_service, "ensure_sam_running", lambda: outcome["ready"])
    monkeypatch.setattr(inpaint_service, "segment_image_preview", segment_image_preview)
    monkeypatch.setattr(inpaint_service, "segment_video", segment_video)
    monkeypatch.setattr(inpaint_service, "check_sam_status", lambda: {"status": "ready", "model_loaded": True})
    answers = {}

    def post(case: str, body: dict) -> None:
        response = server.client.post("/api/v1/segment/preview", json=body)
        answer = response.json()
        if isinstance(answer, dict) and answer.get("mask_preview"):
            # The PNG bytes depend on the encoder; the pixels do not.
            image = Image.open(io.BytesIO(base64.b64decode(answer["mask_preview"]))).convert("RGB")
            answer["mask_preview"] = [list(pixel) for pixel in image.getdata()]
        answers[case] = {"status": response.status_code, "body": answer}

    post("preview", {"video_path": "shot.mp4", "text": "the boat", "frame_index": 3, "start_time": 0.5})
    post("inverted preview", {"video_path": "shot.mp4", "text": "the boat", "invert_mask": True})
    answers["mask inverted"] = bool(numpy.load(masks).all())
    post("full video", {"video_path": str(uploads / "shot.mp4"), "text": "the boat", "full_video": True,
                        "mask_padding": 6})
    outcome["raise"] = RuntimeError("SAM crashed")
    post("runtime error", {"video_path": "shot.mp4", "text": "the boat"})
    outcome["raise"] = ValueError("bad frame")
    post("other error", {"video_path": "shot.mp4", "text": "the boat"})
    outcome["ready"] = False
    post("sam not available", {"video_path": "shot.mp4", "text": "the boat"})
    # The numbers are read before SAM is asked for: a value that is not a number is a 422, never a 503 or a 500.
    post("start time that is not a number", {"video_path": "shot.mp4", "text": "the boat", "start_time": "abc"})
    post("end time that is not a number", {"video_path": "shot.mp4", "text": "the boat", "end_time": [1]})
    post("mask padding that is not a number, full video",
         {"video_path": "shot.mp4", "text": "the boat", "full_video": True, "mask_padding": "wide"})
    answers["sam status"] = server.client.get("/api/v1/sam/status").json()
    answers["calls"] = calls
    golden.check("segment preview", 200, server.normalise(answers))


# -- Outpaint and blend, recorded before they leave launch (C5) ------------------------------------
# The route starts a non-daemon thread and returns. The rig's own settle waits
# only for ``_run_generation_with_preparation``, so these tests join the thread
# they actually started. The engine is held until that name has been read:
# a fast fake job can finish before the test looks, and the name would be gone.
_ROUTE_WORKERS = (
    "(_run_generation)",
    "(run_generation)",
    "(_prepare_and_run_outpaint)",
    "(_run_blend_generation)",
)


def _block_network(monkeypatch) -> None:
    """These routes must not download a model. Local sockets stay open."""
    import socket

    def _host(address):
        if isinstance(address, tuple) and address:
            return address[0]
        return None

    real_create = socket.create_connection

    def create_connection(address, *args, **kwargs):
        host = _host(address)
        if host in {"127.0.0.1", "::1", "localhost"}:
            return real_create(address, *args, **kwargs)
        raise RuntimeError(f"network blocked: {address}")

    real_connect = socket.socket.connect

    def connect(self, address):
        host = _host(address)
        if isinstance(host, str) and host not in {"127.0.0.1", "::1", "localhost"}:
            raise RuntimeError(f"network blocked: {address}")
        return real_connect(self, address)

    monkeypatch.setattr(socket, "create_connection", create_connection)
    monkeypatch.setattr(socket.socket, "connect", connect)


def _join_route_workers(rig, timeout: float = 60.0) -> None:
    threads = [thread for thread in threading.enumerate() if thread.name.endswith(_ROUTE_WORKERS)]
    for thread in threads:
        thread.join(timeout)
    alive = [thread for thread in threads if thread.is_alive()]
    if alive:
        launch = rig.launch
        for job_id in list(rig.job_ids):
            job = launch._jobs.get(job_id)
            if job is not None:
                launch.request_cancel(job, job_id=job_id, active_states=launch._active_gen_states)
        for abort_state in list(launch._active_gen_states.values()):
            abort_state["abort"] = True
        for thread in alive:
            thread.join(10)
        alive = [thread for thread in alive if thread.is_alive()]
    assert not alive, [thread.name for thread in alive]


def _worker_names() -> list[str]:
    names = []
    for thread in threading.enumerate():
        if thread.name.endswith(_ROUTE_WORKERS):
            names.append(thread.name[thread.name.rfind("("):])
    return sorted(names)


def _accept(rig, path: str, body: dict) -> dict:
    """Post one job, hold the engine, and record the thread the route started."""
    release = rig.event()

    def script(call) -> None:
        call.hold(release)
        default_script(call)

    rig.engine.entered.clear()
    rig.engine.scripts.append(script)
    try:
        status, answer = _submit(rig, path, body)
        reached = bool(status == 200 and rig.engine.entered.wait(WAIT))
        names = _worker_names()
    finally:
        release.set()
        _join_route_workers(rig)
    return {"status": status, "answer": answer, "worker threads": names, "reached engine": reached}


def _hide_temp(observed: dict) -> dict:
    """``mkdtemp`` lives in the server's temp folder, which the normaliser does not know."""
    params = observed.get("params") or {}
    folders = [
        params[key]
        for key in ("_blend_temp_dir", "_outpaint_shot_temp_dir")
        if isinstance(params.get(key), str) and params.get(key)
    ]
    if not folders:
        return observed
    text = json.dumps(observed)
    for folder in folders:
        text = text.replace(folder, "<TEMP>")
    return json.loads(text)


def _outpaint_body(path: Path, **extra) -> dict:
    return {
        "video_path": str(path),
        "model_type": "fake_t2v",
        "prompt": "extend the lake",
        "seed": 7,
        "pad_right": 64,
        "preserve_source_audio": False,
        "lock_source_pixels": False,
        **extra,
    }


def test_outpaint_and_blend_reject_bad_requests(server, golden, tmp_path, monkeypatch) -> None:
    _block_network(monkeypatch)
    still = media.image(tmp_path / "still.png", size=(64, 64))
    other = media.image(tmp_path / "other.png", size=(64, 64))
    monkeypatch.setattr(
        server.wgp, "get_base_model_type",
        lambda model_type: "ltxv_13B" if model_type == "fake_13b" else str(model_type),
        raising=False,
    )
    server.check(golden, "outpaint requires a video path", "POST", "/api/v1/outpaint", json={})
    server.check(
        golden, "outpaint source must exist", "POST", "/api/v1/outpaint",
        json={"video_path": "no-such-frame.png"},
    )
    server.check(
        golden, "outpaint requires a model", "POST", "/api/v1/outpaint",
        json={"video_path": str(still)},
    )
    server.check(
        golden, "outpaint requires padding", "POST", "/api/v1/outpaint",
        json={"video_path": str(still), "model_type": "fake_t2v"},
    )
    padded = {"video_path": str(still), "model_type": "fake_t2v", "pad_right": 64}
    server.check(
        golden, "outpaint rejects a non-numeric step count", "POST", "/api/v1/outpaint",
        json={**padded, "num_inference_steps": "many"},
    )
    server.check(
        golden, "outpaint rejects zero steps", "POST", "/api/v1/outpaint",
        json={**padded, "num_inference_steps": 0},
    )
    server.check(
        golden, "outpaint rejects a short 13B schedule", "POST", "/api/v1/outpaint",
        json={**padded, "model_type": "fake_13b"},
    )
    server.check(golden, "blend requires both clips", "POST", "/api/v1/blend", json={})
    server.check(
        golden, "blend clip A must exist", "POST", "/api/v1/blend",
        json={"clip_a_path": "no-such-a.png", "clip_b_path": str(other)},
    )
    server.check(
        golden, "blend clip B must exist", "POST", "/api/v1/blend",
        json={"clip_a_path": str(still), "clip_b_path": "no-such-b.png"},
    )
    server.check(
        golden, "blend requires a model", "POST", "/api/v1/blend",
        json={"clip_a_path": str(still), "clip_b_path": str(other)},
    )


def test_openapi_text_of_the_outpaint_and_blend_routes(server, golden) -> None:
    spec = server.client.get("/openapi.json").json()
    snapshot = {}
    for path in ("/api/v1/outpaint", "/api/v1/blend"):
        operations = spec["paths"][path]
        for method, operation in operations.items():
            snapshot[f"{method.upper()} {path}"] = {
                "operationId": operation.get("operationId"),
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "parameters": operation.get("parameters", []),
            }
    golden.check("outpaint and blend openapi", 200, snapshot)


def test_outpaint_hands_the_worker_the_canvas_job(rig, golden, tmp_path, monkeypatch) -> None:
    """An image and a non-official video. Both start the generation worker, not shot preparation."""
    _block_network(monkeypatch)
    still = media.image(tmp_path / "canvas.png", size=(64, 64))
    clip_path = media.video(tmp_path / "canvas.mp4", seconds=3, size="64x64", fps=8)
    observed = {}
    for case, path in ("image", still), ("video", clip_path):
        accepted = _accept(rig, "/api/v1/outpaint", _outpaint_body(path))
        job_id = accepted["answer"]["job_id"]
        observed[case] = {
            "worker threads": accepted["worker threads"],
            "reached engine": accepted["reached engine"],
            "job": _hide_temp(_job(rig, job_id)),
        }
    rig.check(golden, "outpaint hands the worker the job", observed)


def test_official_outpaint_detects_one_shot_then_generates(rig, golden, tmp_path, monkeypatch) -> None:
    """A non-distilled LTX-2 definition short-circuits the reference resolver, so nothing is downloaded.

    The clip is one solid colour, so preparation finds one shot and then calls the generation worker.
    """
    _block_network(monkeypatch)
    real_base = rig.server.wgp.get_base_model_type
    real_def = rig.server.wgp.get_model_def

    def base_type(model_type):
        if model_type == "fake_ltx":
            return "ltx2_22B"
        return real_base(model_type)

    def model_def(model_type):
        if model_type == "fake_ltx":
            return {
                "architecture": "ltx2_22B",
                "ltx2_pipeline": "two_stage",
                "fps": 8,
                "frames_minimum": 1,
                "latent_size": 1,
                "URLs": [],
                "name": "Fake LTX Dev",
            }
        return real_def(model_type)

    rig.set_wgp("get_base_model_type", base_type)
    rig.set_wgp("get_model_def", model_def)
    clip_path = media.video(tmp_path / "official.mp4", seconds=3, size="64x64", fps=8)
    accepted = _accept(rig, "/api/v1/outpaint", _outpaint_body(
        clip_path, model_type="fake_ltx", mask_preserving_outpaint=True,
    ))
    job_id = accepted["answer"]["job_id"]
    rig.check(golden, "official outpaint one shot", {
        "worker threads": accepted["worker threads"],
        "reached engine": accepted["reached engine"],
        "job": _hide_temp(_job(rig, job_id)),
    })


def test_blend_hands_the_worker_the_transition_job(rig, golden, tmp_path, monkeypatch) -> None:
    """Two stills. Overlap is longer than a still, so assembly keeps the generated transition and does not concat."""
    _block_network(monkeypatch)
    clip_a = media.image(tmp_path / "blend-a.png", size=(64, 64))
    clip_b = media.image(tmp_path / "blend-b.png", size=(64, 64))
    accepted = _accept(rig, "/api/v1/blend", {
        "clip_a_path": str(clip_a),
        "clip_b_path": str(clip_b),
        "model_type": "fake_t2v",
        "prompt": "the lake becomes a field",
        "seed": 7,
        "overlap_sec": 0.2,
        "motion_prefix_sec": 0,
        "motion_suffix_sec": 0,
    })
    job_id = accepted["answer"]["job_id"]
    rig.check(golden, "blend hands the worker the job", {
        "worker threads": accepted["worker threads"],
        "reached engine": accepted["reached engine"],
        "job": _hide_temp(_job(rig, job_id)),
    })


# -- The wiring the move added (C3 review) ---------------------------------------------------------------------------
# The moved handlers read their launch collaborators from slots on their service module, which the router factories
# fill when the full server mounts them. A slot left at None, bound to the wrong object, or captured before launch
# defines it would only show on the branch that reads it, so every slot is compared here with the object the handler
# read from launch before the move. Three are indirect on purpose: launch defines them below the mounts, so the slot
# holds a forwarder that looks the launch name up when it is called.

_INDIRECT_SLOTS = {"_run_generation", "_get_cached_hardware", "_workspace_collection_registry"}
_MOVED = {
    "services.studio_generate": ("generate",),
    "services.studio_edit_requests": ("retake_video_endpoint", "extract_frames_endpoint", "edit_anything_endpoint",
                                      "inpaint_endpoint"),
    "services.studio_segmentation": ("sam_status_endpoint", "segment_preview_endpoint"),
}


def _slots(module) -> list[str]:
    """The module-level names the service starts at None: the factory (or launch) fills each of them."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    return [target.id for node in tree.body if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant) and node.value.value is None
            for target in node.targets if isinstance(target, ast.Name)]


def test_the_moved_handlers_read_the_objects_launch_gave_them(full_server, monkeypatch) -> None:
    import importlib

    launch = worker_module()
    seen = []
    for module_name, handlers in _MOVED.items():
        module = importlib.import_module(module_name)
        for name in handlers:
            assert getattr(launch, name) is getattr(module, name), f"launch.{name} is not {module_name}.{name}"
        for slot in _slots(module):
            seen.append(slot)
            value = getattr(module, slot)
            assert value is not None, f"{module_name}.{slot} was never bound"
            if slot not in _INDIRECT_SLOTS:
                assert value is getattr(launch, slot), f"{module_name}.{slot} is not launch.{slot}"
    assert {"_jobs", "_job_leftovers", "wgp", "execution_mode", "_run_generation", "EDIT_ANYTHING_LORA_FILENAME",
            "_resolve_wangp_visual_media", "_register_manual_generation_job"} <= set(seen)

    import services.studio_edit_requests as edit_requests
    import services.studio_generate as studio_generate

    calls = []
    monkeypatch.setattr(launch, "_run_generation", lambda *args, **kwargs: calls.append((args, kwargs)) or "ran")
    assert edit_requests._run_generation("job-1") == "ran" and calls == [(("job-1",), {})]
    # Python names a worker thread after its target: production threads keep the name "_run_generation".
    assert edit_requests._run_generation.__name__ == "_run_generation"
    monkeypatch.setattr(launch, "_get_cached_hardware", lambda: {"gpu_vram_gb": 7.0})
    assert studio_generate._get_cached_hardware() == {"gpu_vram_gb": 7.0}
    monkeypatch.setattr(launch, "_workspace_collection_registry", SimpleNamespace(get=lambda key: ("found", key)))
    assert studio_generate._workspace_collection_registry.get("c-1") == ("found", "c-1")


# -- the wiring the C7 move added (C7 review) --------------------------------------------------------------------------
# The Recast helpers moved to four service modules that import each other directly. Launch hands two of them the
# launch objects they read through one ``bind`` each: matte gets ``_app_dir``, preparation gets ``_workspace_dir``.
# The six shot helpers the character mask calls moved to services.recast_shot_planning (C8a); masks imports them
# from there. A slot left at None, bound to a copy, or a sibling taken from the wrong module would only show on the
# branch that reads it, so every global each moved function reads is compared here with the object the same name
# holds in launch (where the function read it before the move) and with the module that defines it.
RECAST_SHOT_HELPERS = (
    "_detect_recast_shot_ranges",
    "_find_recast_unmapped_shots",
    "_normalize_recast_tracking_target",
    "_recover_recast_unmapped_shots",
    "_select_recast_timeline_anchor",
    "_summarize_recast_mapping_mask",
)


def _recast_global_reads(value) -> set[str]:
    import inspect
    import symtable
    import textwrap

    names: set[str] = set()

    def walk(scope) -> None:
        names.update(symbol.get_name() for symbol in scope.get_symbols() if symbol.is_global() and symbol.is_referenced())
        for child in scope.get_children():
            walk(child)

    walk(symtable.symtable(textwrap.dedent(inspect.getsource(value)), "<recast>", "exec"))
    return names


def test_the_recast_helpers_read_the_objects_launch_holds(full_server, monkeypatch) -> None:
    import builtins
    import importlib
    import inspect

    launch = worker_module()
    modules = {name: importlib.import_module(name) for name in RECAST_MODULES}
    slots = {name: {"_" + param for param in inspect.signature(module.bind).parameters} if hasattr(module, "bind")
             else set() for name, module in modules.items()}
    home: dict[str, object] = {}
    shot_modules = {name: importlib.import_module(name) for name in SHOT_MODULES}
    for module_name, module in {**modules, **shot_modules}.items():
        for node in ast.parse(inspect.getsource(module)).body:
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name != "bind":
                home[node.name] = module
            elif isinstance(node, ast.Assign):
                home.update({target.id: module for target in node.targets
                             if isinstance(target, ast.Name) and target.id not in slots.get(module_name, ())
                             and not (isinstance(node.value, ast.Constant) and node.value.value is None)})

    # Every name launch imports from a Recast helper module is that module's object. (The shot modules, C8a, have
    # their own check below.)
    exported = set()
    for node in ast.parse(Path(launch.__file__).read_text(encoding="utf-8")).body:
        if isinstance(node, ast.ImportFrom) and node.module in modules:
            for alias in node.names:
                assert getattr(launch, alias.asname or alias.name) is getattr(modules[node.module], alias.name)
                exported.add(alias.name)
    assert {"_RECAST_RELIGHTING_LORA_FILENAME", "_normalize_recast_lora_settings", "_build_recast_adaptive_mask",
            "_render_recast_mask_locked_video", "_prepare_recast_reference_conditioning"} <= exported

    from_launch, siblings = set(), set()
    for module_name, module in modules.items():
        namespace = vars(module)
        own = [value for name, value in namespace.items() if name != "bind"
               and (inspect.isfunction(value) or inspect.isclass(value)) and value.__module__ == module_name]
        for value in own:
            for name in sorted(_recast_global_reads(value)):
                if name not in namespace:
                    assert hasattr(builtins, name), f"{module_name}.{value.__name__} reads {name}, which is not defined"
                    continue
                held = namespace[name]
                assert held is not None, f"{module_name}.{name} was never bound"
                if name in home:
                    assert held is vars(home[name])[name], f"{module_name}.{name} is not {home[name].__name__}.{name}"
                    if name in vars(launch):
                        assert vars(launch)[name] is held, f"launch.{name} is not {module_name}.{name}"
                    siblings.add(name)
                else:
                    assert held is vars(launch)[name], f"{module_name}.{name} is not launch.{name}"
                    from_launch.add(name)
    assert from_launch == {"os", "threading", "_app_dir", "_workspace_dir"}
    assert slots["services.recast_masks"] == set() and not hasattr(modules["services.recast_masks"], "bind")
    assert set(RECAST_SHOT_HELPERS) <= siblings
    assert {"_RECAST_MASK_COLORS", "_resolve_recast_media", "_recast_reference_subject_mask",
            "_refine_recast_reference_cutout", "_recast_subject_crop_box", "_get_recast_u2net_session"} <= siblings

    # The worker's bystander protection (services.generation_worker.finalize) calls two mask helpers by their launch
    # names; launch hands it the same objects.
    masks = modules["services.recast_masks"]
    finalize = importlib.import_module("services.generation_worker.finalize")
    for name in ("_build_recast_adaptive_mask", "_render_recast_mask_locked_video"):
        assert getattr(finalize, name) is getattr(masks, name) is getattr(launch, name), name

    # The character mask calls the shot helpers recast_shot_planning defines, the objects launch re-exports; launch
    # keeps no forwarder for them.
    planning = shot_modules["services.recast_shot_planning"]
    for name in RECAST_SHOT_HELPERS:
        assert getattr(masks, name) is getattr(planning, name) is getattr(launch, name), name
        assert getattr(planning, name).__module__ == "services.recast_shot_planning", name
    assert not [name for name in vars(launch) if name.startswith("_forward_recast_")
                and name != "_forward_recast_shot_run_generation"]

    # One U2Net session, its locks and its cache: the holder in recast_matte. Launch keeps no copy of any of them.
    matte = modules["services.recast_matte"]
    for gone in ("_recast_u2net_session", "_recast_u2net_session_lock", "_recast_u2net_run_lock",
                 "_recast_u2net_cache_lock", "_recast_u2net_cache", "_recast_u2net", "RecastU2NetState",
                 "_RECAST_U2NET_CACHE_LIMIT"):
        assert not hasattr(launch, gone), f"launch still holds {gone}"
    holders = sorted(
        (module_name, attr)
        for module_name, module in list(sys.modules.items())
        for attr, value in list(getattr(module, "__dict__", {}).items())
        if isinstance(value, matte.RecastU2NetState)
    )
    assert holders == [("services.recast_matte", "_recast_u2net")]
    state = matte._recast_u2net
    assert len({id(state.session_lock), id(state.run_lock), id(state.cache_lock)}) == 3
    assert matte._RECAST_U2NET_CACHE_LIMIT == 8


def test_a_rig_patch_reaches_the_recast_helper_that_reads_the_name(rig) -> None:
    """Before the move a Recast helper read launch's globals, so patching a launch name reached it. The same patch
    still reaches it now that the helper reads its own module's globals."""
    rig.patch("_resolve_recast_media", lambda raw, workspace: f"/resolved/{workspace}/{raw}")
    mappings, explicit = rig.launch._normalize_recast_character_mappings(
        {"ref_image_path": "hero.png", "additional_ref_image_paths": ["side.png"], "target": " the hero "}, "ws-a",
    )
    assert explicit is False
    assert mappings == [{
        "id": "recast-1",
        "target": "the hero",
        "ref_image_path": "/resolved/ws-a/hero.png",
        "additional_ref_image_paths": ["/resolved/ws-a/side.png"],
        "reference_aligned_to_source": False,
    }]


# -- The wiring the C5 move added (C5 review) ------------------------------------------------------------------------
# Each outpaint and blend module imports the standard library, execution_mode and the job lifecycle itself, and takes
# the launch objects it reads (wgp, the job registry and states, the workspace and job helpers, the recast helpers)
# from one bind() (services) or its router factory (routers), which launch calls once; the Recast frame counter and
# audio probe come from their service, as in launch. The generation worker is defined further down in launch, so that
# slot holds launch's forwarder, which looks the launch name up when it is called. A slot left at None, bound to a copy
# or to another function, or a forwarder that captured its target at bind time would only show on the branch that
# reads it, so every global each moved function reads is compared here with the object the same name holds in launch,
# where it read it before.
_C5_EXPORTS = {
    "services.outpaint_planning": (
        "_resolve_outpaint_sampling", "_resolve_outpaint_video_timing", "_resolve_ltx2_outpaint_reference_model",
        "_cap_outpaint_single_stage_window", "_resolve_outpaint_canvas_geometry", "_format_outpaint_percentage",
        "_detect_outpaint_video_shot_ranges", "_build_outpaint_shot_filter", "_write_outpaint_shot_guide",
        "_build_outpaint_shot_manifest", "_OUTPAINT_PIXEL_BUDGETS", "_OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS",
        "_OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES",
    ),
    "services.outpaint_run": (
        "_prepare_and_run_outpaint", "_write_outpaint_shot_aware_sidecar", "_run_outpaint_shot_generation",
    ),
    "routers.outpaint": ("outpaint_endpoint",),
    "services.blend_run": ("_run_blend_generation",),
    "routers.blend": ("blend_endpoint",),
}
# The launch names defined below the mount block, and the forwarder launch passes for each.
_C5_FORWARDERS = {
    "_run_generation": "_forward_studio_run_generation",
}


def _global_reads(function) -> set[str]:
    """The global names a function (and the functions nested in it) reads, from its source."""
    import inspect
    import symtable
    import textwrap

    names: set[str] = set()

    def walk(scope) -> None:
        names.update(symbol.get_name() for symbol in scope.get_symbols() if symbol.is_global() and symbol.is_referenced())
        for child in scope.get_children():
            walk(child)

    for scope in symtable.symtable(textwrap.dedent(inspect.getsource(function)), "<moved>", "exec").get_children():
        walk(scope)
    return names


def _bound_slots(module) -> set[str]:
    """The module-level ``NAME = None`` placeholders that bind() or the router factory fills."""
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(module))
    return {target.id for node in tree.body if isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Constant) and node.value.value is None
            for target in node.targets if isinstance(target, ast.Name)}


def test_outpaint_and_blend_read_the_objects_launch_holds(full_server, monkeypatch) -> None:
    import builtins
    import importlib
    import inspect

    launch = worker_module()
    compared: set[str] = set()
    slots: set[str] = set()
    for module_name, exported in _C5_EXPORTS.items():
        module = importlib.import_module(module_name)
        namespace = vars(module)
        for name in exported:
            assert getattr(launch, name) is namespace[name], f"launch.{name} is not {module_name}.{name}"
        own = {name for name, value in namespace.items()
               if inspect.isfunction(value) and value.__module__ == module_name}
        plumbing = {"bind", "create_outpaint_router", "create_blend_router"}
        for function_name in sorted(own - plumbing):
            for name in sorted(_global_reads(namespace[function_name])):
                if name in own:
                    continue  # a helper that moved with it
                if name not in namespace:
                    assert hasattr(builtins, name), f"{module_name}.{function_name} reads {name}, which is not defined"
                    continue
                expected = vars(launch)[_C5_FORWARDERS.get(name, name)]
                assert namespace[name] is expected, f"{module_name}.{name} is not the object launch holds"
                compared.add(name)
        module_slots = _bound_slots(module)
        assert module_slots, module_name
        for name in module_slots:
            assert namespace[name] is not None, f"{module_name}.{name} was never bound"
        slots |= module_slots
    assert slots <= compared
    assert {"os", "math", "time", "threading", "uuid", "traceback", "wgp", "execution_mode", "HTTPException",
            "_jobs", "_active_gen_states", "_coordinated_generation_slot", "_workspace_dir", "_get_active_workspace",
            "_register_manual_generation_job", "_generation_job_acceptance", "_recast_video_has_audio",
            "_detect_recast_shot_ranges", "_quantize_recast_shot_frame_count", "_recast_video_frame_count",
            "_run_generation", "update_job", "finish_job", "is_cancel_requested", "register_abort_state",
            "unregister_abort_state", "try_start", "try_requeue", "record_job_outputs"} <= compared

    # The forwarder calls whatever launch holds under the name when it is called, not what it held at bind.
    calls = []
    monkeypatch.setattr(launch, "_run_generation",
                        lambda job_id, **kwargs: calls.append(["worker", job_id, kwargs]) or "ran")
    for module_name in ("routers.outpaint", "services.outpaint_run", "routers.blend", "services.blend_run"):
        assert importlib.import_module(module_name)._run_generation(module_name, finalize=False) == "ran"
    assert calls == [
        ["worker", "routers.outpaint", {"finalize": False}], ["worker", "services.outpaint_run", {"finalize": False}],
        ["worker", "routers.blend", {"finalize": False}], ["worker", "services.blend_run", {"finalize": False}],
    ]
    # Python names a route's worker thread from the target, so the forwarder keeps the worker's name.
    assert importlib.import_module("routers.outpaint")._run_generation.__name__ == "_run_generation"
    assert importlib.import_module("routers.blend")._run_blend_generation.__name__ == "_run_blend_generation"


def test_recast_shot_modules_read_the_objects_launch_holds(full_server, monkeypatch) -> None:
    """Every global a moved shot function reads is the launch object, or a forwarder.

    The forwarder is the one case that is not the object: patching the launch
    name changes what the shot module calls. A slot left at None, or bound to
    a copy, fails here.
    """
    import builtins
    import importlib
    import inspect

    launch = worker_module()
    services = Path(__file__).resolve().parents[2] / "app" / "services"
    stems = sorted(path.stem for path in services.glob("recast_shot_*.py"))
    assert "recast_shot_planning" in stems
    launch_names = vars(launch)
    launch_source = Path(launch.__file__).read_text(encoding="utf-8")
    compared: set[str] = set()
    forwarded: set[str] = set()
    for stem in stems:
        assert launch_source.count(f"from services.{stem} import (") == 1
        assert launch_source.count(f"_bind_{stem}(") in {0, 1}
        module_name = f"services.{stem}"
        module = importlib.import_module(module_name)
        namespace = vars(module)
        own = {
            name
            for name, value in namespace.items()
            if inspect.isfunction(value) and getattr(value, "__module__", None) == module_name and name != "bind"
        }
        for name in own:
            assert getattr(launch, name) is namespace[name], f"launch.{name} is not {module_name}.{name}"
        reads: set[str] = set()
        for function_name in sorted(own):
            reads.update(_global_reads(namespace[function_name]))
        for name in sorted(reads):
            if name in own or name.startswith("__") or hasattr(builtins, name):
                continue
            assert name in namespace, f"{module_name} reads {name}, which it does not define"
            value = namespace[name]
            if name in launch_names and value is launch_names[name]:
                compared.add(name)
                continue
            assert callable(value) and name in launch_names, (
                f"{module_name}.{name} is not launch.{name} and is not a forwarder"
            )
            sentinel = object()
            original = launch_names[name]

            def patched(*_args, _sentinel=sentinel, **_kwargs):
                return _sentinel

            monkeypatch.setattr(launch, name, patched)
            assert value() is sentinel, f"patching launch.{name} did not change {module_name}.{name}"
            monkeypatch.setattr(launch, name, original)
            forwarded.add(name)
    assert "_RECAST_MASK_COLORS" in compared
    assert "_normalize_recast_person_count" in compared
    if "recast_shot_run" in stems:
        assert forwarded == {"_run_generation"}
    else:
        assert forwarded == set()


def test_recast_preview_reads_the_objects_launch_holds(full_server) -> None:
    """The preview handler's collaborators are the objects launch holds.

    The served function is the router wrapper. Launch's ``recast_preview_endpoint``
    is that same wrapper, which is what the route calls.
    """
    import builtins
    import importlib

    from routers.recast_preview import recast_preview_endpoint as served

    launch = worker_module()
    module = importlib.import_module("services.recast_preview")
    assert launch.recast_preview_endpoint is served
    assert served is not module.recast_preview_endpoint
    reads = _global_reads(module.recast_preview_endpoint)
    compared = set()
    for name in sorted(reads):
        if name.startswith("__") or hasattr(builtins, name):
            continue
        assert getattr(module, name) is getattr(launch, name), name
        compared.add(name)
    assert "_resolve_recast_media" in compared
    assert "HTTPException" in compared


def test_recast_endpoint_reads_the_objects_launch_holds(full_server, monkeypatch) -> None:
    """Every global the moved handler reads is the launch object, or a forwarder.

    The served function is the router wrapper. Launch's ``recast_endpoint`` is
    that same wrapper. ``_run_generation`` and ``_get_cached_hardware`` are
    forwarders: patching the launch name changes what the handler calls, and
    the worker thread is still named ``_run_generation``.
    """
    import builtins
    import importlib

    from routers.recast import recast_endpoint as served

    launch = worker_module()
    module = importlib.import_module("services.recast_endpoint")
    assert launch.recast_endpoint is served
    # MCP's "recast" tool (the Viggle path) calls the function the route serves.
    assert launch._mcp_handlers["recast"] is served
    assert served is not module.recast_endpoint
    assert launch._bind_recast_endpoint is module.bind
    reads = _global_reads(module.recast_endpoint)
    compared = set()
    forwarded = set()
    for name in sorted(reads):
        if name.startswith("__") or hasattr(builtins, name):
            continue
        assert hasattr(module, name), name
        value = getattr(module, name)
        launch_value = getattr(launch, name)
        if value is launch_value:
            compared.add(name)
            continue
        assert callable(value), name
        sentinel = object()

        def patched(*_args, _sentinel=sentinel, **_kwargs):
            return _sentinel

        monkeypatch.setattr(launch, name, patched)
        assert value() is sentinel, name
        monkeypatch.setattr(launch, name, launch_value)
        forwarded.add(name)
    assert "_resolve_recast_media" in compared
    assert "_coordinated_generation_slot" in compared
    assert "generate" in compared
    assert forwarded == {"_run_generation", "_get_cached_hardware"}
    # The Studio routes' forwarders (C3), shared: no Recast copy of them in launch.
    assert module._run_generation is launch._forward_studio_run_generation
    assert module._get_cached_hardware is launch._forward_studio_cached_hardware
    # The route starts the worker as a thread named after it, as before the move.
    assert module._run_generation.__name__ == launch._run_generation.__name__ == "_run_generation"


# -- Recast routes (recorded on the pre-move tree; patches land on the service too) --
# ``POST /api/v1/recast`` starts its worker and then builds the HTTP body from the same params object.
# The worker can mutate those params as soon as it takes the generation slot, so a golden that reads
# the answer has to hold the slot until the response is in hand. ``_patch_recast`` writes the stub on
# launch today and, once the handler has moved, on the service module that actually reads the name.

_RECAST_MODULES = ("services.recast_endpoint", "services.recast_preview")
_RECAST_THREAD = "(_run_recast)"
_GENERATE_THREAD = "(_run_generation_with_preparation)"


def _patch_recast(monkeypatch, name, value) -> None:
    """Patch ``name`` on launch and on each recast service module that already has it."""
    launch = worker_module()
    holders = []
    if hasattr(launch, name):
        holders.append(launch)
    for module_name in _RECAST_MODULES:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, name):
            holders.append(module)
    assert holders, name
    for module in holders:
        monkeypatch.setattr(module, name, value)


def _install_recast_decord(monkeypatch, *, frames: int = 17, fps: float = 8.0, fail: str | None = None) -> None:
    """A fixed clip. The real decoder is not installed on every CI machine, and a dummy file is not a video."""
    import numpy

    class VideoReader:
        def __init__(self, path: str) -> None:
            if fail:
                raise RuntimeError(fail)
            self.path = path

        def get_avg_fps(self) -> float:
            return fps

        def __len__(self) -> int:
            return frames

        def __getitem__(self, index: int):
            frame = numpy.zeros((64, 96, 3), dtype="uint8")
            return SimpleNamespace(shape=frame.shape, asnumpy=lambda: frame)

        def get_batch(self, indices):
            count = len(list(indices))
            batch = numpy.zeros((count, 64, 96, 3), dtype="uint8")
            return SimpleNamespace(asnumpy=lambda: batch)

    monkeypatch.setitem(sys.modules, "decord", SimpleNamespace(VideoReader=VideoReader))


def _paint_keyword_mask(frames, *_args, **_kwargs):
    """One blue person (the first Recast palette color) in every frame of ``frames``."""
    import numpy

    mask = numpy.zeros(numpy.asarray(frames).shape, dtype="uint8")
    mask[..., 2] = 255
    return mask


def _empty_keyword_mask(frames, *_args, **_kwargs):
    import numpy

    return numpy.zeros(numpy.asarray(frames).shape, dtype="uint8")


def _stub_magic_mask(monkeypatch, keyword_masks) -> None:
    import shared.magic_mask as magic_mask

    monkeypatch.setattr(magic_mask, "generate_keyword_masks", keyword_masks)

    def generate_video_mask(_video_path, _target, output_dir=None, **_kwargs):
        folder = Path(output_dir or ".")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / "recast-mask.mp4"
        target.write_bytes(b"mask")
        return str(target), None

    monkeypatch.setattr(magic_mask, "generate_video_mask", generate_video_mask)


def _stub_recast_preparation(monkeypatch) -> None:
    """The route's own writes, without SAM, reference crops, or a bystander pass."""

    def prepare(mappings, _mask, _output_dir, _job_id, **_kwargs):
        reference = mappings[0]["ref_image_path"]
        return {
            "image_refs": [reference],
            "primary_mask": reference,
            "additional_masks": [],
            "expected_colors": [[0, 0, 255]],
            "clip_identity_ref": reference,
            "auto_face_detail_refs": [],
            "reference_canvas": [96, 64],
            "previews": [{"kind": "primary"}],
        }

    def scene(_params, *_args, **_kwargs):
        return {"hidden_fraction": 0.0, "expansion_pixels": 8}

    _patch_recast(monkeypatch, "_prepare_recast_reference_conditioning", prepare)
    _patch_recast(monkeypatch, "_enable_recast_dynamic_source_scene_reference", scene)
    _patch_recast(monkeypatch, "_recast_probe_needs_bystander_tracking", lambda *_args, **_kwargs: False)


@contextmanager
def _hold_recast_detection(monkeypatch):
    """Block the detection slot until the HTTP handler has returned its body."""
    launch = worker_module()
    real = launch._coordinated_generation_slot
    release = threading.Event()

    @contextmanager
    def gated(job, description=None, **kwargs):
        if "recast" in str(description or ""):
            if not release.wait(WAIT):
                raise AssertionError("the test never released the recast detection slot")
        with real(job, description=description, **kwargs) as acquired:
            yield acquired

    _patch_recast(monkeypatch, "_coordinated_generation_slot", gated)
    try:
        yield release
    finally:
        release.set()


def _live_threads(suffix: str) -> list:
    deadline = time.monotonic() + WAIT
    while time.monotonic() < deadline:
        threads = [thread for thread in threading.enumerate() if thread.name.endswith(suffix) and thread.is_alive()]
        if threads:
            return threads
        time.sleep(0.01)
    raise AssertionError(f"no live thread named {suffix}")


def _join(threads) -> None:
    for thread in threads:
        thread.join(WAIT)
        assert not thread.is_alive(), thread.name


def _finish_held_recast(release: threading.Event) -> None:
    """The worker is blocked in the detection slot. Find it, open the slot, then wait."""
    threads = _live_threads(_RECAST_THREAD)
    release.set()
    _join(threads)


def _jpeg_shape(body: dict) -> dict:
    """Drop encoder bytes. The golden keeps the decoded image's format, mode and size."""
    if not isinstance(body, dict) or "preview" not in body:
        return body
    preview = body.get("preview")
    facts: dict = {"jpeg_data_url": False}
    if isinstance(preview, str) and preview.startswith("data:image/jpeg;base64,"):
        from PIL import Image

        raw = base64.b64decode(preview.split(",", 1)[1], validate=True)
        image = Image.open(io.BytesIO(raw))
        image.load()
        facts = {"jpeg_data_url": True, "format": image.format, "mode": image.mode, "size": list(image.size)}
    recorded = dict(body)
    recorded["preview"] = facts
    return recorded


def _answer(response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {"<text>": response.text}


def _recast_files(server) -> tuple[Path, Path]:
    video = server.outputs / "recast-source.mp4"
    video.parent.mkdir(parents=True, exist_ok=True)
    video.write_bytes(b"not decoded: decord is faked")
    reference = media.image(server.root / "uploads" / "hero.png")
    return video, reference


def _post(server, path: str, body: dict):
    return server.client.post(path, json=body)


def test_recast_preview_rejects_a_bad_request(server, golden, monkeypatch) -> None:
    _refuse_remote_network(monkeypatch)
    _install_recast_decord(monkeypatch)
    video, _reference = _recast_files(server)
    launch = worker_module()
    before = set(launch._jobs)
    cases = {
        "preview video must exist": ({}, None),
        "preview allows at most five mappings": (
            {"video_path": str(video), "character_mappings": [{"target": f"person {index}"} for index in range(6)]},
            None,
        ),
        "preview mapping must be an object": (
            {"video_path": str(video), "character_mappings": ["nope"]},
            None,
        ),
        "preview mapping needs a target": (
            {"video_path": str(video), "character_mappings": [{"ref_image_path": "hero.png"}]},
            None,
        ),
    }
    for case, (body, _unused) in cases.items():
        response = _post(server, "/api/v1/recast/preview", body)
        golden.check(case, response.status_code, server.normalise(_answer(response)))
    _install_recast_decord(monkeypatch, fail="unreadable clip")
    response = _post(server, "/api/v1/recast/preview", {"video_path": str(video), "target": "person"})
    golden.check("preview cannot read a broken video", response.status_code, server.normalise(_answer(response)))
    _install_recast_decord(monkeypatch)
    response = _post(server, "/api/v1/recast/preview", {"video_path": str(video), "end_time": "nope"})
    golden.check("preview rejects a bad end time", response.status_code, server.normalise(_answer(response)))
    import shared.magic_mask as magic_mask

    def fail_value(*_args, **_kwargs):
        raise ValueError("no person")

    def fail_runtime(*_args, **_kwargs):
        raise RuntimeError("mask exploded")

    monkeypatch.setattr(magic_mask, "generate_keyword_masks", fail_value)
    response = _post(server, "/api/v1/recast/preview", {"video_path": str(video), "target": "person"})
    golden.check("preview segmentation value error", response.status_code, server.normalise(_answer(response)))
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", fail_runtime)
    response = _post(server, "/api/v1/recast/preview", {"video_path": str(video), "target": "person"})
    golden.check("preview segmentation crash", response.status_code, server.normalise(_answer(response)))
    golden.check("preview rejections create no job", 200, {"jobs created": len(set(launch._jobs) - before)})


def test_recast_preview_returns_a_jpeg_and_reference_previews(server, golden, monkeypatch) -> None:
    _refuse_remote_network(monkeypatch)
    _install_recast_decord(monkeypatch)
    _stub_magic_mask(monkeypatch, _paint_keyword_mask)
    video, reference = _recast_files(server)
    recorded = {}

    def keep(case: str, body: dict) -> None:
        response = _post(server, "/api/v1/recast/preview", body)
        recorded[case] = {"status": response.status_code, "body": _jpeg_shape(server.normalise(_answer(response)))}

    keep("one person", {"video_path": str(video), "target": "person"})
    keep("one mapped person", {"video_path": str(video), "character_mappings": [{"target": "person"}]})

    def prepare_previews(*_args, **_kwargs):
        return {"previews": [{"kind": "primary"}]}

    _patch_recast(monkeypatch, "_prepare_recast_reference_conditioning", prepare_previews)
    keep("reference previews pass through", {
        "video_path": str(video), "target": "person", "ref_image_path": str(reference),
    })

    def fail_value(*_args, **_kwargs):
        raise ValueError("missing crop")

    def fail_runtime(*_args, **_kwargs):
        raise RuntimeError("encoder broke")

    _patch_recast(monkeypatch, "_prepare_recast_reference_conditioning", fail_value)
    response = _post(server, "/api/v1/recast/preview", {
        "video_path": str(video), "target": "person", "ref_image_path": str(reference),
    })
    recorded["reference preview value error"] = {"status": response.status_code, "body": server.normalise(_answer(response))}
    _patch_recast(monkeypatch, "_prepare_recast_reference_conditioning", fail_runtime)
    response = _post(server, "/api/v1/recast/preview", {
        "video_path": str(video), "target": "person", "ref_image_path": str(reference),
    })
    recorded["reference preview crash"] = {"status": response.status_code, "body": server.normalise(_answer(response))}
    golden.check("recast preview", 200, recorded)


def test_recast_rejects_before_a_job_exists(server, golden, monkeypatch) -> None:
    _refuse_remote_network(monkeypatch)
    _install_recast_decord(monkeypatch)
    video, reference = _recast_files(server)
    launch = worker_module()
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 0.0})
    before = set(launch._jobs)
    present = {"video_path": str(video), "ref_image_path": str(reference), "prompt": "a calm lake"}
    cases = {
        "video must exist": {},
        "reference must exist": {"video_path": str(video)},
        "additional views must be a list": {**present, "additional_ref_image_paths": "nope"},
        "a mapping must be an object": {**present, "character_mappings": ["nope"]},
        "a mapping needs a reference": {**present, "character_mappings": [{"target": "person"}]},
        "the video must be readable": present,
        "704p below 16 GB": {**present, "resolution_profile": "704p"},
        "the default model is the dedicated recast model": present,
        "a legacy fast model migrates to the dedicated model": {**present, "model_type": "scail2_14B_fast"},
        "enhancement off rejects an empty prompt": {**present, "model_type": "fake_t2v", "prompt": ""},
        "viggle needs a video and a frame": {"model_type": "viggle_animate"},
    }
    recorded = {}
    for case, body in cases.items():
        if case == "the video must be readable":
            _install_recast_decord(monkeypatch, fail="unreadable clip")
        elif case == "704p below 16 GB":
            _install_recast_decord(monkeypatch)
            monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 8.0})
        elif case == "the default model is the dedicated recast model":
            monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 0.0})
            _install_recast_decord(monkeypatch)
        response = _post(server, "/api/v1/recast", body)
        recorded[case] = {"status": response.status_code, "body": server.normalise(_answer(response))}
    recorded["jobs created"] = len(set(launch._jobs) - before)
    golden.check("recast rejections", 200, recorded)


def test_recast_legacy_job_reaches_the_fake_engine(rig, golden, monkeypatch) -> None:
    """A legacy single-reference Recast. Stubs stand in for SAM and the reference crops.

    The HTTP body is what the handler returns before detection mutates the params. The job
    observation is what the worker and the fake engine left after detection.
    """
    _refuse_remote_network(monkeypatch)
    _install_recast_decord(monkeypatch)
    _stub_magic_mask(monkeypatch, _paint_keyword_mask)
    _stub_recast_preparation(monkeypatch)
    rig.patch("_ensure_managed_loras_present", lambda *_args, **_kwargs: [])
    video, reference = _recast_files(rig.server)
    body = {
        "video_path": str(video),
        "ref_image_path": str(reference),
        "model_type": "fake_t2v",
        "prompt": "a calm lake",
        "seed": 7,
        "resolution_profile": "512p",
        "num_inference_steps": 99,
        "guidance_scale": 99,
    }
    with _hold_recast_detection(monkeypatch) as release:
        status, answer = _submit(rig, "/api/v1/recast", body)
        assert status == 200, answer
        _finish_held_recast(release)
    job = _job(rig, answer["job_id"])
    assert job["engine_calls"], "the recast worker never called the fake engine"
    assert job["status"]["status"] != "failed", job["status"]
    rig.check(golden, "recast legacy job", {"status": status, "answer": answer, "job": job})


def test_recast_stops_when_the_mask_finds_nobody(rig, golden, monkeypatch) -> None:
    _refuse_remote_network(monkeypatch)
    _install_recast_decord(monkeypatch)
    _stub_magic_mask(monkeypatch, _empty_keyword_mask)
    _stub_recast_preparation(monkeypatch)
    rig.patch("_ensure_managed_loras_present", lambda *_args, **_kwargs: [])
    video, reference = _recast_files(rig.server)
    body = {
        "video_path": str(video),
        "ref_image_path": str(reference),
        "model_type": "fake_t2v",
        "prompt": "a calm lake",
        "seed": 7,
    }
    with _hold_recast_detection(monkeypatch) as release:
        status, answer = _submit(rig, "/api/v1/recast", body)
        assert status == 200, answer
        _finish_held_recast(release)
    job = _job(rig, answer["job_id"])
    assert job["engine_calls"] == []
    rig.check(golden, "recast finds nobody", {"status": status, "answer": answer, "job": job})


def test_recast_viggle_uses_the_generate_route(rig, golden, monkeypatch) -> None:
    """Viggle is not a Recast worker. A bad request stops first; a stubbed prepare is an ordinary generate."""
    _refuse_remote_network(monkeypatch)
    from services import wangp_submission

    rejected = _post(rig.server, "/api/v1/recast", {"model_type": "viggle_animate"})
    monkeypatch.setattr(wangp_submission, "prepare_viggle_recast", lambda *_args, **_kwargs: dict(BODY))
    since = len(rig.engine.calls)
    status, answer = _submit(rig, "/api/v1/recast", {"model_type": "viggle_animate"})
    assert status == 200, answer
    _join(_live_threads(_GENERATE_THREAD))
    job = _job(rig, answer["job_id"], since)
    assert job["engine_calls"], "viggle recast never reached the fake engine"
    rig.check(golden, "recast viggle", {
        "rejected": {"status": rejected.status_code, "body": rejected.json()},
        "accepted": {"status": status, "answer": answer, "job": job},
    })


def test_openapi_text_of_the_recast_routes(server, golden) -> None:
    spec = server.client.get("/openapi.json").json()
    snapshot = {}
    for path in ("/api/v1/recast/preview", "/api/v1/recast"):
        operations = spec["paths"][path]
        for method, operation in operations.items():
            snapshot[f"{method.upper()} {path}"] = {
                "operationId": operation.get("operationId"),
                "summary": operation.get("summary"),
                "description": operation.get("description"),
                "parameters": operation.get("parameters", []),
            }
    golden.check("recast openapi", 200, snapshot)


# -- Recast: the blocks the first goldens did not reach (C8b review) -------------------------------------------------
# Recorded on the tree where the handler still lived in launch (5367e7efe plus the goldens above). SAM, the reference
# crops, the cast and bystander references, the shot manifest and the shot runner are recorders: each keeps what the
# handler handed it (a frame or a mask as its shape, first value and sum), so a golden pins the handler's choices and
# not only its HTTP answer. The jobs then run on the C0 fake engine.

_RECAST_SCAIL = {
    "scail2_14B_recast_fast": {
        "name": "SCAIL-2 Recast Fast", "URLs": [], "fps": 16,
        "frames_minimum": 5, "frames_steps": 4, "latent_size": 4,
    },
    "scail2_14B": {
        "name": "SCAIL-2 HQ", "URLs": [], "fps": 16,
        "frames_minimum": 5, "frames_steps": 4, "latent_size": 4,
    },
}


def _install_recast_scail(rig) -> None:
    real = rig.server.wgp.get_model_def
    rig.set_wgp("get_model_def", lambda model_type: _RECAST_SCAIL.get(model_type) or real(model_type))


def _recast_normalised(value, *patterns: tuple[str, str]):
    text = json.dumps(value, default=str)
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return json.loads(text)


def _recast_facts(value):
    """JSON facts of what the handler handed a stub: arrays as shape, first value and sum; callables by kind."""
    import numpy

    if isinstance(value, numpy.ndarray):
        flat = value.reshape(-1)
        return {"shape": list(value.shape), "first": int(flat[0]) if flat.size else None, "sum": int(value.sum())}
    if isinstance(value, dict):
        return {str(key): _recast_facts(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_recast_facts(item) for item in value]
    if callable(value):
        return "<callable>"
    return value


def _paint_people(count: int):
    """A keyword mask with ``count`` people, one Recast palette color each, side by side."""

    def paint(frames, *_args, **_kwargs):
        import numpy

        from services.recast_masks import _RECAST_MASK_COLORS

        mask = numpy.zeros(numpy.asarray(frames).shape, dtype="uint8")
        width = mask.shape[-2]
        for index in range(count):
            mask[..., index * width // count:(index + 1) * width // count, :] = _RECAST_MASK_COLORS[index]
        return mask

    return paint


class _RecastStubs:
    """Recorders for the collaborators the Recast handler calls after it has answered.

    ``shots``, ``segments``, ``common``, ``timeline_aware`` and ``tracking_fps`` shape the mapped tracking;
    ``bystanders`` is the probe's answer; ``native`` is how the bystander pass ends ("group", "none", "error",
    "cancel"); ``manifest`` is how the shot manifest ends ("ok", "error", "cancel"); ``on_tracking`` runs inside the
    mapped tracking (a cancel); ``tracking_progress`` and ``native_progress`` are the progress reports each pass makes.
    """

    def __init__(self, rig, monkeypatch, *, people: int = 1, shots: int = 1, segments: int | None = None,
                 common: int | None = 0, timeline_aware: bool = False, bystanders: bool = False,
                 native: str = "group", manifest: str = "ok", face_details: int = 0, on_tracking=None,
                 tracking_fps: float = 8.0, tracking_progress=None, native_progress=None) -> None:
        import numpy
        import shared.magic_mask as magic_mask

        self.rig, self.calls = rig, []
        self.on_tracking = on_tracking
        uploads = rig.server.root / "uploads"
        uploads.mkdir(parents=True, exist_ok=True)
        frames = [numpy.full((64, 96, 3), index, dtype="uint8") for index in range(17)]
        masks = [numpy.full((64, 96, 3), 100 + index, dtype="uint8") for index in range(17)]
        bounds = [[0, 17]] if shots == 1 else [[0, 9], [9, 17]]
        count = people

        def record(name, *args, **kwargs):
            # One line per call in the golden: the name, then what the handler passed.
            self.calls.append(json.dumps([name, _recast_facts(list(args)), _recast_facts(kwargs)], sort_keys=True,
                                         default=str))

        def keyword_masks(frames_in, target, **kwargs):
            record("generate_keyword_masks", target, **kwargs)
            return _paint_people(count)(frames_in)

        def video_mask(video_path, target, output_dir=None, **kwargs):
            record("generate_video_mask", Path(video_path).name, target, **kwargs)
            path = Path(output_dir) / "recast-mask.mp4"
            path.write_bytes(b"mask")
            return str(path), None

        monkeypatch.setattr(magic_mask, "generate_keyword_masks", keyword_masks)
        monkeypatch.setattr(magic_mask, "generate_video_mask", video_mask)

        def character_mask(video_path, mappings, output_dir, progress_callback=None, abort_callback=None):
            record("_build_recast_character_mask", Path(video_path).name, [m["id"] for m in mappings], output_dir)
            total = len(mappings)
            for mapping_index, done, of in tracking_progress or (
                (0, 0, 10), (0, 0, 10), (0, 5, 10), (total - 1, 5, 10), (total - 1, 10, 10),
            ):
                progress_callback(mapping_index, total, done, of)
            if self.on_tracking:
                self.on_tracking(self)
            abort_callback()
            path = Path(output_dir) / "mapped-mask.mp4"
            path.write_bytes(b"mask")
            return {
                "fps": tracking_fps, "mapping_masks": ["<mapping masks>"], "shot_ranges": bounds, "shot_count": shots,
                "common_frame_index": common, "scene_anchor_index": 4, "source_frames": frames, "mask_frames": masks,
                "mapping_summaries": [{"id": m["id"], "anchor_frame_index": 2 + index} for index, m in
                                      enumerate(mappings)],
                "recovered_shots": [{"shot_index": 1, "mapping_id": mappings[0]["id"]}],
                "timeline_aware": timeline_aware, "video_mask": str(path),
            }

        def plan(mapping_masks, shot_ranges, **kwargs):
            record("_plan_recast_shot_segments", mapping_masks, shot_ranges, **kwargs)
            return [{"segment": index} for index in range(segments if segments is not None else shots)]

        def probe(frame, mask, person_count):
            record("_recast_probe_needs_bystander_tracking", frame, mask, person_count)
            return bystanders

        def prepare(mappings, mask, output_dir, job_id, **kwargs):
            record("_prepare_recast_reference_conditioning", [m["id"] for m in mappings], mask, output_dir, job_id,
                   **kwargs)
            reference = mappings[0]["ref_image_path"]
            return {
                "image_refs": [m["ref_image_path"] for m in mappings], "primary_mask": reference,
                "additional_masks": [f"mask-{m['id']}" for m in mappings[1:]],
                "expected_colors": [[0, 0, 255]] * len(mappings), "clip_identity_ref": reference,
                "auto_face_detail_refs": [f"face-{index}" for index in range(face_details)],
                "reference_canvas": [96, 64], "primary_target_refs": [reference], "previews": [],
            }

        def cast_reference(prepared, output_dir, job_id, person_count, **kwargs):
            record("_build_recast_target_group_reference", sorted(prepared), output_dir, job_id, person_count,
                   **kwargs)
            return {"image": f"{output_dir}/cast.png", "mask": f"{output_dir}/cast-mask.png", "mode": "shared_frame"}

        def native_people(video_path, mask_path, person_count, output_dir, job_id, **kwargs):
            record("_build_recast_native_people_conditioning", Path(video_path).name, Path(mask_path).name,
                   person_count, output_dir, job_id, **kwargs)
            progress = kwargs["progress_callback"]
            if native == "cancel":
                rig.cancel(job_id)
            for done, of in native_progress or ((0, 4), (0, 4), (2, 4), (4, 4)):
                progress(done, of)
            if native == "error":
                raise RuntimeError("ambiguous people")
            if native == "none":
                return {"reference_image": None, "assignments": []}
            return {
                "reference_image": f"{output_dir}/group.png", "reference_mask": f"{output_dir}/group-mask.png",
                "video_mask": f"{output_dir}/group-mask.mp4", "conditioning_count": person_count + 2,
                "assignments": [{"track": 1}, {"track": 2}],
            }

        def scene(params, frame, mask, person_count, output_dir, job_id):
            record("_enable_recast_dynamic_source_scene_reference", sorted(params), frame, mask, person_count,
                   output_dir, job_id)
            return {"hidden_fraction": 0.25, "expansion_pixels": 12}

        def shot_manifest(params, tracking, prepared, temp_dir, job_id, **kwargs):
            record("_build_recast_shot_manifest", sorted(params), sorted(tracking), sorted(prepared),
                   Path(temp_dir).name, job_id, **kwargs)
            if manifest == "error":
                raise RuntimeError("manifest broke")
            if manifest == "cancel":
                rig.cancel(job_id)
            return {
                "tasks": [{"prompt": "shot one"}], "shots": [{"mode": "generate"}, {"mode": "passthrough"}],
                "published_shots": [{"index": 0}, {"index": 1}], "frame_count": 17, "fps": 8.0,
                "camera_shot_count": shots, "cast_transition_count": max(0, (segments or shots) - shots),
            }

        def shot_run(job_id):
            from services.job_lifecycle import finish_job, try_start

            job = rig.launch._jobs[job_id]
            record("_run_recast_shot_generation", job_id, Path(job["out_dir"]).name,
                   sorted(key for key in job["params"] if key.startswith("_")))
            if try_start(job, phase="Joining shots", message="Joining shots..."):
                finish_job(job, "completed", message="Shots joined")

        shot_folder = rig.server.root / "shot-tmp"

        def mkdtemp(prefix="tmp", **_kwargs):
            rig.recast_folders = getattr(rig, "recast_folders", 0) + 1
            folder = shot_folder / f"{prefix}{rig.recast_folders}"
            folder.mkdir(parents=True)
            return str(folder)

        import tempfile

        monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)
        for name, value in (
            ("_build_recast_character_mask", character_mask), ("_plan_recast_shot_segments", plan),
            ("_recast_probe_needs_bystander_tracking", probe), ("_prepare_recast_reference_conditioning", prepare),
            ("_build_recast_target_group_reference", cast_reference),
            ("_build_recast_native_people_conditioning", native_people),
            ("_enable_recast_dynamic_source_scene_reference", scene), ("_build_recast_shot_manifest", shot_manifest),
            ("_run_recast_shot_generation", shot_run),
        ):
            _patch_recast(monkeypatch, name, value)
        rig.patch("_ensure_managed_loras_present", lambda *_args, **_kwargs: [])


def _recast_mappings(rig, count: int) -> list[dict]:
    uploads = rig.server.root / "uploads"
    return [
        {"id": f"cast-{index + 1}", "target": f"person {index + 1}",
         "ref_image_path": str(media.image(uploads / f"hero-{index + 1}.png"))}
        for index in range(count)
    ]


def _recast_run(rig, monkeypatch, body: dict, stubs: _RecastStubs) -> dict:
    """Submit; keep the params the handler built before detection; let detection and the fake engine finish."""
    since = len(rig.engine.calls)
    with _hold_recast_detection(monkeypatch) as release:
        try:
            status, answer = _submit(rig, "/api/v1/recast", body)
        except Exception as error:  # the test client re-raises what the server did not turn into an answer
            return {"server error": f"{type(error).__name__}: {error}", "calls": stubs.calls}
        if status != 200:
            return {"status": status, "answer": answer}
        built = _params(rig, answer["job_id"])
        _finish_held_recast(release)
    return {"status": status, "answer": answer, "built": built, "calls": stubs.calls,
            "job": _recast_job_facts(rig, answer["job_id"], since, built)}


def _recast_job_facts(rig, job_id: str, since: int, built: dict | None = None, workspace: str = "default") -> dict:
    """The C0 observation without what accumulates across cases (files, sidecars, the job list): the status, the
    transitions, the engine's inputs, the params the worker changed or added after ``built``, what was left held."""
    observed = rig.observe(job_id, workspace=workspace)
    final = _params(rig, job_id)
    params = final
    if built is not None:
        params = {key: value for key, value in final.items() if built.get(key, "<absent>") != value}
        params["<removed>"] = sorted(key for key in built if key not in final)
    return {
        "status": observed["status"], "record": observed["record"], "transitions": observed["transitions"],
        "engine_inputs": [json.dumps(call.get("kwargs"), sort_keys=True, default=str)
                          for call in observed["engine_calls"][since:]], "params": params,
        "left_behind": observed["left_behind"], "returned": observed["returned"],
    }


def test_recast_answers_by_model_profile_and_option(rig, golden, monkeypatch) -> None:
    """The HTTP answer and the params the handler builds, by model, resolution profile, VRAM, fps and options."""
    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    video, reference = _recast_files(rig.server)
    loras = rig.server.root / "loras"
    loras.mkdir(parents=True, exist_ok=True)
    for name in ("style.safetensors", "scail2_relighting_lora.safetensors"):
        (loras / name).write_bytes(b"lora")
    rig.set_wgp("get_lora_dir", lambda *_args, **_kwargs: str(loras))
    present = {"video_path": str(video), "ref_image_path": str(reference), "prompt": "a calm lake", "seed": 3}
    cases = {
        "fast by default at 480p": ({**present}, 0.0, 8.0),
        "fast with steps, a fixed guidance and relighting next to a user LoRA": (
            {**present, "num_inference_steps": 12, "guidance_scale": 9, "use_relighting": True,
             "activated_loras": ["style.safetensors"], "loras_multipliers": "0.7;0.3"}, 0.0, 8.0),
        "HQ at 512p from 60 fps with three grouped people and every option flipped": (
            {**present, "model_type": "scail2_14B", "resolution_profile": "quality", "person_count": 3,
             "guidance_scale": 7.5, "num_inference_steps": 30, "protect_bystanders": True,
             "preserve_scene_reference": False, "isolate_reference": False, "auto_face_detail": False,
             "enhance_prompt": True, "prompt": "Replace the man with a knight", "negative_prompt": "blur"},
            0.0, 60.0),
        "704p with 24 GB": ({**present, "resolution_profile": "704p"}, 24.0, 8.0),
        "704p with unknown VRAM": ({**present, "resolution_profile": "1280x704"}, 0.0, 8.0),
        "a reference given by a path outside the uploads resolves by its name": (
            {**present, "ref_image_path": "../../elsewhere/hero.png"}, 0.0, 8.0),
    }
    recorded = {}
    for case, (body, vram, fps) in cases.items():
        people = int(body.get("person_count") or 1)
        stubs = _RecastStubs(rig, monkeypatch, people=people)
        _install_recast_decord(monkeypatch, fps=fps)
        monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": vram})
        if body.get("protect_bystanders"):
            def adaptive(generated, mask, count, folder, progress_callback=None):
                progress_callback(1, 1)
                return str(Path(folder) / "adaptive.mp4")

            def locked(source, mask, generated):
                target = Path(generated).with_name("locked.mp4")
                shutil.copyfile(generated, target)
                return str(target)

            rig.patch("_build_recast_adaptive_mask", adaptive)
            rig.patch("_render_recast_mask_locked_video", locked)
        recorded[case] = _recast_run(rig, monkeypatch, body, stubs)
    rig.check(golden, "recast answers by model profile and option", recorded)


def test_recast_rejects_what_the_first_goldens_did_not_send(rig, golden, monkeypatch) -> None:
    """Rejections that need a model the fake engine knows, and requests that resolve no file."""
    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch)
    video, reference = _recast_files(rig.server)
    before = set(rig.launch._jobs)
    present = {"video_path": str(video), "ref_image_path": str(reference), "prompt": "a calm lake"}
    two = _recast_mappings(rig, 2)
    cases = {
        "enhancement off rejects an empty prompt": {**present, "prompt": " ", "enhance_prompt": False},
        "a video path that climbs out of the workspace and names no file": {
            **present, "video_path": "../../../no-such-folder/no-such-clip.mp4"},
        "an edited full frame maps one replacement only": {
            **present, "character_mappings": [{**two[0], "reference_aligned_to_source": True}, two[1]]},
        "six mappings": {**present, "character_mappings": [{**two[0], "id": f"m{index}"} for index in range(6)]},
    }
    recorded = {}
    for case, body in cases.items():
        response = rig.server.client.post("/api/v1/recast", json=body)
        recorded[case] = {"status": response.status_code, "body": _answer(response)}
    recorded["jobs created"] = len(set(rig.launch._jobs) - before)
    rig.check(golden, "recast rejects what the first goldens did not send", recorded)


def test_recast_trims_the_source_before_it_reads_it(rig, golden, monkeypatch) -> None:
    """A trim runs ffmpeg once (recorded, not run) and the trimmed file becomes the guide; a failed or invalid trim
    keeps the full clip."""
    import subprocess

    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch)
    video, reference = _recast_files(rig.server)
    commands = []
    outcome = {"code": 0}
    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if not (isinstance(cmd, list) and cmd[:2] == ["ffmpeg", "-y"] and "recast_trim_" in str(cmd[-1])):
            return real_run(cmd, *args, **kwargs)
        commands.append({"cmd": [Path(part).name if "/" in str(part) else part for part in cmd],
                         "kwargs": sorted(kwargs)})
        if outcome["code"] == 0:
            Path(cmd[-1]).write_bytes(b"trimmed")
        return SimpleNamespace(returncode=outcome["code"], stderr="trim refused", stdout="")

    monkeypatch.setattr(subprocess, "run", run)
    present = {"video_path": str(video), "ref_image_path": str(reference), "prompt": "a calm lake", "seed": 3}
    recorded = {}
    for case, body, code in (
        ("a trim", {**present, "start_time": 0.5, "end_time": "1.5"}, 0),
        ("a trim ffmpeg refuses", {**present, "start_time": 0.5, "end_time": 1.5}, 1),
        ("a trim too short to cut", {**present, "start_time": 1.0, "end_time": 1.04}, 0),
        ("trim times that are not numbers", {**present, "start_time": "soon", "end_time": "later"}, 0),
    ):
        outcome["code"] = code
        stubs = _RecastStubs(rig, monkeypatch)
        result = _recast_run(rig, monkeypatch, body, stubs)
        recorded[case] = {**result, "ffmpeg": list(commands)}
        commands.clear()
    rig.check(golden, "recast trims the source",
              _recast_normalised(recorded, (r"recast_trim_[0-9a-f]{8}\.mp4", "recast_trim_<ID>.mp4")))


def test_recast_maps_characters_in_one_shot(rig, golden, monkeypatch) -> None:
    """Two explicit mappings that share a frame in one camera shot: timeline tracking, one native cast reference, and
    each way the bystander pass can end."""
    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch)
    video, _reference = _recast_files(rig.server)
    mappings = _recast_mappings(rig, 2)
    body = {"video_path": str(video), "character_mappings": mappings, "prompt": "two knights", "seed": 5}
    recorded = {}
    for case, options in (
        ("bystanders mapped into the native group", {"bystanders": True, "native": "group", "face_details": 2}),
        ("no bystander survives full tracking", {"bystanders": True, "native": "none"}),
        ("the bystander pass fails and Recast goes on target-only", {"bystanders": True, "native": "error"}),
        ("no bystander in the anchor frame", {"bystanders": False}),
        ("no shared frame: per-character anchors and timeline scene references",
         {"bystanders": False, "common": None, "timeline_aware": True}),
    ):
        stubs = _RecastStubs(rig, monkeypatch, people=2, **options)
        recorded[case] = _recast_run(rig, monkeypatch, body, stubs)
    recorded["one mapping"] = _recast_run(
        rig, monkeypatch, {**body, "character_mappings": mappings[:1]},
        _RecastStubs(rig, monkeypatch, people=1, bystanders=True, native="group"))
    rig.check(golden, "recast maps characters in one shot", recorded)


def test_recast_hands_shots_and_cast_changes_to_the_shot_runner(rig, golden, monkeypatch) -> None:
    """Two camera shots, or one shot with a cast change: the shot manifest goes to the shot runner, which gets the
    private folder; the strict pixel lock is switched off. A manifest that fails removes its folder."""
    import secrets

    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch, fps=60.0)
    monkeypatch.setattr(secrets, "randbelow", lambda bound: 424242)
    video, _reference = _recast_files(rig.server)
    mappings = _recast_mappings(rig, 2)
    body = {"video_path": str(video), "character_mappings": mappings, "prompt": "two knights",
            "protect_bystanders": True, "seed": 9}
    frames_and_step = {"fail": False}

    def min_frames_and_step(model_type):
        if frames_and_step["fail"]:
            raise KeyError(model_type)
        return 9, 4, 4

    rig.set_wgp("get_model_min_frames_and_step", min_frames_and_step)
    recorded = {}
    for case, request, options in (
        ("two camera shots", body, {"shots": 2, "segments": 2}),
        ("one camera shot with a cast change and a random seed", {**body, "seed": -1}, {"shots": 1, "segments": 2}),
        ("a seed that is not a number", {**body, "seed": "soon"}, {"shots": 2, "segments": 2}),
        ("the manifest fails", body, {"shots": 2, "segments": 2, "manifest": "error"}),
    ):
        frames_and_step["fail"] = options.get("manifest") == "error"
        stubs = _RecastStubs(rig, monkeypatch, people=2, **options)
        result = _recast_run(rig, monkeypatch, request, stubs)
        shot_folder = rig.server.root / "shot-tmp"
        result["shot folders left"] = sorted(path.name for path in shot_folder.iterdir()) if shot_folder.exists() \
            else []
        recorded[case] = result
    rig.check(golden, "recast hands shots to the shot runner", recorded)


def test_recast_stops_when_cancelled_during_detection(rig, golden, monkeypatch) -> None:
    """A cancel while the mapped characters are tracked, while the bystanders are mapped, or once the shot manifest
    exists: the handler stops, the job never reaches the engine, and a private shot folder is removed."""
    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch)
    video, _reference = _recast_files(rig.server)
    mappings = _recast_mappings(rig, 2)
    body = {"video_path": str(video), "character_mappings": mappings, "prompt": "two knights", "seed": 5}

    def cancel_during_tracking(stubs):
        stubs.rig.cancel(stubs.rig.job_ids[-1])

    recorded = {}
    for case, options in (
        ("during mapped tracking", {"on_tracking": cancel_during_tracking}),
        ("during the bystander pass", {"bystanders": True, "native": "cancel"}),
        ("after the shot manifest", {"shots": 2, "segments": 2, "manifest": "cancel"}),
    ):
        stubs = _RecastStubs(rig, monkeypatch, people=2, **options)
        result = _recast_run(rig, monkeypatch, body, stubs)
        assert result["job"]["engine_inputs"] == [], case
        shot_folder = rig.server.root / "shot-tmp"
        result["shot folders left"] = sorted(path.name for path in shot_folder.iterdir()) if shot_folder.exists() \
            else []
        recorded[case] = result
    rig.check(golden, "recast stops when cancelled during detection", recorded)


def test_recast_follows_the_execution_mode(rig, golden, monkeypatch) -> None:
    """Plan mode refuses before any job; simulate mode skips SAM and hands the job straight to the generation worker,
    in the test workspace only."""
    from services import execution_mode

    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch)
    video, reference = _recast_files(rig.server)
    stubs = _RecastStubs(rig, monkeypatch)
    body = {"video_path": str(video), "ref_image_path": str(reference), "prompt": "a calm lake", "seed": 3}
    workspace = execution_mode.POLICY.workspace
    recorded = {}
    for case, mode, request in (
        ("plan mode", "plan", {**body, "workspace": workspace}),
        ("simulate mode in the default workspace", "simulate", body),
        ("simulate mode in the test workspace", "simulate", {**body, "workspace": workspace}),
    ):
        monkeypatch.setattr(execution_mode, "POLICY", _replace(execution_mode.POLICY, mode=mode, step_delay=0.0))
        since = len(rig.engine.calls)
        status, answer = _submit(rig, "/api/v1/recast", request)
        recorded[case] = {"status": status, "answer": answer}
        if status == 200:
            _join_edit_workers()
            recorded[case]["job"] = _recast_job_facts(rig, answer["job_id"], since,
                                                      workspace=request.get("workspace", "default"))
    recorded["calls"] = stubs.calls
    rig.check(golden, "recast follows the execution mode", recorded)


# -- Recast: what the mutation run of the C8b review showed no case pinned ------------------------------------------
# Recorded on the tree where both handlers still lived in launch, like the cases above. Each case is named after the
# behaviour it pins; together they make every mutation that survived the cases above fail.


def test_recast_edges_the_first_cases_let_through(rig, golden, monkeypatch) -> None:
    """A short trim is still cut; two people asked and one found stops the job; a cast change is held for 0.2 s of
    the tracked clip; progress is reported every 5%; a cancel during tracking ends quietly (no traceback)."""
    import subprocess
    import traceback

    _refuse_remote_network(monkeypatch)
    _install_recast_scail(rig)
    _install_recast_decord(monkeypatch)
    video, reference = _recast_files(rig.server)
    commands = []
    real_run = subprocess.run

    def run(cmd, *args, **kwargs):
        if not (isinstance(cmd, list) and cmd[:2] == ["ffmpeg", "-y"] and "recast_trim_" in str(cmd[-1])):
            return real_run(cmd, *args, **kwargs)
        commands.append([Path(part).name if "/" in str(part) else part for part in cmd])
        Path(cmd[-1]).write_bytes(b"trimmed")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(subprocess, "run", run)
    tracebacks = []
    real_print_exc = traceback.print_exc

    def print_exc(*args, **kwargs):
        tracebacks.append("print_exc")
        return real_print_exc(*args, **kwargs)

    monkeypatch.setattr(traceback, "print_exc", print_exc)
    mappings = _recast_mappings(rig, 2)
    present = {"video_path": str(video), "ref_image_path": str(reference), "prompt": "a calm lake", "seed": 3}
    mapped = {"video_path": str(video), "character_mappings": mappings, "prompt": "two knights", "seed": 5}

    def cancel_during_tracking(stubs):
        stubs.rig.cancel(stubs.rig.job_ids[-1])

    recorded = {}
    for case, body, options in (
        ("a 0.1 s trim is cut", {**present, "start_time": 0.5, "end_time": 0.6}, {}),
        ("two people asked and one found", {**present, "person_count": 2}, {"people": 1}),
        ("a cast change in a 40 fps tracking is held for eight frames", mapped,
         {"people": 2, "segments": 2, "tracking_fps": 40.0}),
        ("tracking and bystander progress every 5%", mapped,
         {"people": 2, "bystanders": True, "native": "group",
          "tracking_progress": ((0, 0, 20), (0, 2, 20), (0, 3, 20), (0, 4, 20), (1, 20, 20)),
          "native_progress": ((0, 20), (1, 20), (2, 20), (3, 20), (20, 20))}),
        ("a cancel during tracking prints no traceback", mapped,
         {"people": 2, "on_tracking": cancel_during_tracking}),
    ):
        stubs = _RecastStubs(rig, monkeypatch, **options)
        tracebacks.clear()
        result = _recast_run(rig, monkeypatch, body, stubs)
        recorded[case] = {**result, "ffmpeg": list(commands), "tracebacks": len(tracebacks)}
        commands.clear()
    rig.check(golden, "recast edges the first cases let through",
              _recast_normalised(recorded, (r"recast_trim_[0-9a-f]{8}\.mp4", "recast_trim_<ID>.mp4")))


def test_recast_preview_edges_the_first_cases_let_through(server, golden, monkeypatch) -> None:
    """The preview's own choices: the colour each mapping is tracked in, the overlay it draws, the anchors and the
    defaults it hands reference preparation, a timeline whose end equals its start, and no reference preview when
    nobody was found."""
    import hashlib

    import numpy
    import shared.magic_mask as magic_mask
    from PIL import Image

    _refuse_remote_network(monkeypatch)
    _install_recast_decord(monkeypatch)
    video, reference = _recast_files(server)
    uploads = server.root / "uploads"
    second = media.image(uploads / "villain.png")
    calls = []
    # Where each target is found: the left half of the frame, or the right half.
    found_targets = {"person": slice(0, 48), "the knight": slice(48, 96)}

    def keyword_masks(frames, target, **kwargs):
        palette = [list(color) for color in kwargs.get("color_palette") or []]
        calls.append(["generate_keyword_masks", target, palette, kwargs.get("max_colored_objects"),
                      len(kwargs.get("tracking_segments") or []), list(numpy.asarray(frames).shape)])
        mask = numpy.zeros(numpy.asarray(frames).shape, dtype="uint8")
        if target in found_targets:
            mask[..., :, found_targets[target], :] = palette[0]
        return mask

    def prepare(mappings, mask, folder, job_id, **kwargs):
        calls.append(["_prepare_recast_reference_conditioning", [Path(m["ref_image_path"]).name for m in mappings],
                      _recast_facts(mask), Path(folder).name.startswith("maestro-recast-preview-"), job_id,
                      _recast_facts(kwargs)])
        return {"previews": [{"kind": "primary", "mappings": len(mappings)}]}

    real_fromarray = Image.fromarray

    def fromarray(array, *args, **kwargs):
        raw = numpy.ascontiguousarray(array)
        calls.append(["Image.fromarray", list(raw.shape), str(raw.dtype), hashlib.sha256(raw.tobytes()).hexdigest(),
                      raw.reshape(-1)[:6].tolist()])
        return real_fromarray(array, *args, **kwargs)

    monkeypatch.setattr(magic_mask, "generate_keyword_masks", keyword_masks)
    monkeypatch.setattr(Image, "fromarray", fromarray)
    _patch_recast(monkeypatch, "_prepare_recast_reference_conditioning", prepare)
    recorded = {}
    for case, body in (
        ("one person with a reference, defaults", {"video_path": str(video), "target": "person",
                                                   "ref_image_path": str(reference)}),
        ("a reference and nobody found", {"video_path": str(video), "target": "nobody",
                                          "ref_image_path": str(reference)}),
        ("a timeline whose end equals its start", {"video_path": str(video), "target": "person", "time": 1.0,
                                                    "end_time": 1.0}),
        ("two mappings, both found, with references", {"video_path": str(video), "character_mappings": [
            {"target": "person", "ref_image_path": str(reference)},
            {"target": "the knight", "ref_image_path": str(second)}]}),
        ("two mappings, one found", {"video_path": str(video), "character_mappings": [
            {"target": "person"}, {"target": "the villain"}]}),
    ):
        calls.clear()
        response = server.client.post("/api/v1/recast/preview", json=body)
        recorded[case] = {"status": response.status_code, "body": _jpeg_shape(server.normalise(_answer(response))),
                          "calls": [json.dumps(call, sort_keys=True, default=str) for call in calls]}
    golden.check("recast preview edges the first cases let through", 200, server.normalise(recorded))


def test_a_rig_patch_reaches_the_recast_routes(rig) -> None:
    """``Rig.patch`` writes a stub on every module that reads the name, the two Recast route modules included."""
    import importlib

    def stub(*_args, **_kwargs):
        return None

    endpoint = importlib.import_module("services.recast_endpoint")
    preview = importlib.import_module("services.recast_preview")
    rig.patch("_prepare_recast_reference_conditioning", stub)
    assert endpoint._prepare_recast_reference_conditioning is stub
    assert preview._prepare_recast_reference_conditioning is stub
    rig.patch("_coordinated_generation_slot", stub)
    assert endpoint._coordinated_generation_slot is stub
