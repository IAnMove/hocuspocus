"""Cheap answers of the Studio generation routes, recorded before they leave launch.

These are the validation and error paths of ``POST /api/v1/generate``, retake,
extract-frames, edit-anything, inpaint, SAM status and segment preview, plus
one accepted ``POST /generate`` that the C0 fake engine finishes. They do not
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

from tests.characterization import media
from tests.characterization.test_run_generation import (
    RECAST_MODULES, SHOT_MODULES, BODY, Rig, _media_writer, worker_module,
)
# Fixtures, used by name: the C0 rig and its decodable clip.
from tests.characterization.test_run_generation import (  # noqa: F401
    WAIT, _refuse_remote_network, _stub_legacy_h3, clip, rig,
)
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
    answers["sam status"] = server.client.get("/api/v1/sam/status").json()
    answers["calls"] = calls
    golden.check("segment preview", 200, server.normalise(answers))


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


def _global_reads(function) -> set[str]:
    """Names a function reads from the module it is defined in."""
    import inspect
    import symtable
    import textwrap

    names: set[str] = set()

    def walk(scope) -> None:
        names.update(
            symbol.get_name()
            for symbol in scope.get_symbols()
            if symbol.is_global() and symbol.is_referenced()
        )
        for child in scope.get_children():
            walk(child)

    walk(symtable.symtable(textwrap.dedent(inspect.getsource(function)), "<shot>", "exec"))
    return names


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
    monkeypatch.setattr(launch, "_cached_hardware", {"gpu_vram_gb": 0.0})
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
            monkeypatch.setattr(launch, "_cached_hardware", {"gpu_vram_gb": 8.0})
        elif case == "the default model is the dedicated recast model":
            monkeypatch.setattr(launch, "_cached_hardware", {"gpu_vram_gb": 0.0})
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
