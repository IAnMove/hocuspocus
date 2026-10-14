"""Cheap answers of the Studio generation routes, recorded before they leave launch.

These are the validation and error paths of ``POST /api/v1/generate``, retake,
extract-frames, edit-anything, inpaint, SAM status and segment preview, plus
one accepted ``POST /generate`` that the C0 fake engine finishes. They do not
re-record ``goldens/test_run_generation.json``. A real mask, a real SAM
preview and a retake that reads frames need a GPU and are not here.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import threading
from dataclasses import replace as _replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.hardware_probe import hardware_cache

from tests.characterization import media
from tests.characterization.test_run_generation import BODY, Rig, _media_writer, worker_module
# Fixtures, used by name: the C0 rig and its decodable clip.
from tests.characterization.test_run_generation import WAIT, _stub_legacy_h3, clip, rig  # noqa: F401
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
