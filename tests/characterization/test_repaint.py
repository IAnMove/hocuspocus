"""Cheap answers of the Repaint routes, recorded before they leave launch.

``POST /api/v1/repaint/preview`` and ``POST /api/v1/repaint`` still live in
``_launch_runtime``. These cases drive the validation and error paths, one
preview that draws semantic masks from a stub (never SAM), and the no-mapping
jobs the C0 fake engine finishes. A mapped Repaint that tracks regions, writes
shot videos and restores the source audio needs a GPU and is not here; the one
mapped case stubs Magic Mask so the request thread records the failure without
downloading a model.
"""
from __future__ import annotations

import hashlib
import re
import threading
from dataclasses import replace as _replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.characterization import media
from tests.characterization.test_run_generation import WAIT, worker_module
# Fixtures, used by name: the C0 rig (fake engine, hardware cache, queue) and its clip.
from tests.characterization.test_run_generation import clip, rig  # noqa: F401
from tests.characterization.test_studio_generate import _job, _probe_as, _submit

_ROUTES = ("/api/v1/repaint/preview", "/api/v1/repaint")
_REPAINT_WORKERS = ("(_run_generation)", "(run_generation)", "(_run_repaint)")
_SCAIL = {
    "scail2_14B_fast": {
        "name": "SCAIL-2 Fast", "URLs": [], "fps": 16,
        "frames_minimum": 5, "frames_steps": 4, "latent_size": 4,
    },
    "scail2_14B": {
        "name": "SCAIL-2 HQ", "URLs": [], "fps": 16,
        "frames_minimum": 5, "frames_steps": 4, "latent_size": 4,
    },
}


def _join_repaint_workers() -> None:
    for thread in [item for item in threading.enumerate() if item.name.endswith(_REPAINT_WORKERS)]:
        thread.join(WAIT)
        assert not thread.is_alive(), f"{thread.name} did not finish"


def _present(folder: Path, name: str) -> str:
    path = folder / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"present")
    return name


def _frame(folder: Path, name: str, size: tuple[int, int]) -> str:
    media.image(folder / name, size=size)
    return name


def _install_scail(rig) -> None:
    real = rig.server.wgp.get_model_def
    rig.set_wgp("get_model_def", lambda model_type: _SCAIL.get(model_type) or real(model_type))


def _preview_pixels(answer: dict) -> dict:
    """JPEG bytes depend on the encoder. The decoded pixels do not, so the golden keeps their digest."""
    import base64
    import io

    from PIL import Image

    recorded = dict(answer)
    for key in ("source_preview", "target_preview"):
        uri = str(recorded.get(key) or "")
        encoded = uri.split(",", 1)[1] if "," in uri else ""
        image = Image.open(io.BytesIO(base64.b64decode(encoded))).convert("RGB")
        raw = image.tobytes()
        recorded[key] = {
            "size": list(image.size),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "first": list(raw[:3]),
            "last": list(raw[-3:]),
        }
    return recorded


def test_repaint_preview_rejects_incomplete_requests(server, golden, tmp_path) -> None:
    video = _present(tmp_path, "source.mp4")
    frame = _present(tmp_path, "frame.png")
    answers = {}

    def post(case: str, body: dict) -> None:
        response = server.client.post("/api/v1/repaint/preview", json=body)
        answers[case] = {"status": response.status_code, "body": response.json()}

    post("missing video", {})
    post("missing frame", {"video_path": video})
    post("mappings are not a list", {"video_path": video, "target_frame_path": frame, "region_mappings": {}})
    post("a region is not an object", {"video_path": video, "target_frame_path": frame, "region_mappings": ["person"]})
    post("a region needs both descriptions", {
        "video_path": video, "target_frame_path": frame,
        "region_mappings": [{"source": "the person in blue"}],
    })
    post("more than five regions", {
        "video_path": video, "target_frame_path": frame,
        "region_mappings": [{"source": f"s{index}", "target": f"t{index}"} for index in range(6)],
    })
    post("no regions", {"video_path": video, "target_frame_path": frame, "region_mappings": []})
    golden.check("preview rejects incomplete requests", 200, server.normalise(answers))


def test_repaint_rejects_incomplete_requests(server, golden, tmp_path) -> None:
    video = _present(tmp_path, "source.mp4")
    frame = _present(tmp_path, "frame.png")
    answers = {}

    def post(case: str, body: dict) -> None:
        response = server.client.post("/api/v1/repaint", json=body)
        answer = response.json()
        # ffmpeg's own stderr carries allocator addresses. The sentences do not.
        if isinstance(answer, dict) and isinstance(answer.get("detail"), str):
            answer = {**answer, "detail": re.sub(r"0x[0-9a-fA-F]+", "0x<ADDR>", answer["detail"])}
        answers[case] = {"status": response.status_code, "body": answer}

    post("missing video", {})
    post("missing frame", {"video_path": video})
    post("mappings are not a list", {"video_path": video, "target_frame_path": frame, "region_mappings": "person"})
    post("trim times are not numeric", {
        "video_path": video, "target_frame_path": frame, "start_time": "soon", "end_time": "later",
    })
    post("trim range is inverted", {
        "video_path": video, "target_frame_path": frame, "start_time": 1.0, "end_time": 1.04,
    })
    post("trim of a file ffmpeg cannot read", {
        "video_path": video, "target_frame_path": frame, "start_time": 0.0, "end_time": 0.5,
    })
    golden.check("repaint rejects incomplete requests", 200, server.normalise(answers))


def test_repaint_preview_reads_a_stubbed_frame(rig, golden, monkeypatch) -> None:
    import numpy

    from shared import magic_mask

    _probe_as(monkeypatch)
    calls: list = []

    def masks(video, keyword, **_kwargs):
        calls.append([keyword, list(video.shape)])
        painted = numpy.zeros_like(video)
        if "blue" in keyword:
            painted[:, 8:24, 16:40] = (0, 0, 255)
        elif "red" in keyword:
            painted[:, 8:24, 16:40] = (255, 0, 0)
        return painted

    monkeypatch.setattr(magic_mask, "generate_keyword_masks", masks)
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    square = _frame(folder, "square.png", (32, 32))
    matching = _frame(folder, "frame.png", (96, 64))
    answers = {}

    def post(case: str, body: dict) -> None:
        response = rig.server.client.post("/api/v1/repaint/preview", json=body)
        answer = response.json()
        if isinstance(answer, dict) and "source_preview" in answer:
            answer = _preview_pixels(answer)
        answers[case] = {"status": response.status_code, "body": answer}

    post("aspect does not match", {"video_path": video, "target_frame_path": square,
                                    "region_mappings": [{"source": "a person", "target": "a person"}]})
    _unreadable(monkeypatch)
    post("video cannot be decoded", {"video_path": video, "target_frame_path": matching,
                                     "region_mappings": [{"source": "a person", "target": "a person"}]})
    _probe_as(monkeypatch)
    post("one region found", {"video_path": video, "target_frame_path": matching, "time": 0.5,
                              "region_mappings": [{"id": "coat", "source": "person in blue", "target": "person in red"}]})
    post("region missing from both frames", {"video_path": video, "target_frame_path": matching,
                                             "region_mappings": [{"source": "a hat", "target": "a hat"}]})
    answers["mask calls"] = calls
    golden.check("preview reads a stubbed frame", 200, rig.server.normalise(answers))


def _unreadable(monkeypatch) -> None:
    class Broken:
        def __init__(self, _path: str) -> None:
            raise RuntimeError("unreadable")

    monkeypatch.setitem(__import__("sys").modules, "decord", SimpleNamespace(VideoReader=Broken))


def test_repaint_prepares_a_job_for_the_worker(rig, golden, monkeypatch, tmp_path) -> None:
    from services import execution_mode

    _install_scail(rig)
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    square = _frame(folder, "square.png", (32, 32))
    matching = _frame(folder, "frame.png", (96, 64))
    before = set(rig.launch._jobs)
    observed: dict = {}

    def reject(case: str, body: dict) -> None:
        status, answer = _submit(rig, "/api/v1/repaint", body)
        _join_repaint_workers()
        observed[case] = {"status": status, "answer": answer}

    _unreadable(monkeypatch)
    reject("source cannot be decoded", {"video_path": video, "target_frame_path": matching})
    _probe_as(monkeypatch)
    reject("edited frame aspect does not match", {"video_path": video, "target_frame_path": square})
    rig.launch._cached_hardware = {"gpu_vram_gb": 8.0}
    reject("704p below 16 GB", {"video_path": video, "target_frame_path": matching, "resolution_profile": "704p"})
    rig.launch._cached_hardware = {"gpu_vram_gb": 0.0}
    reject("model is not SCAIL-2", {"video_path": video, "target_frame_path": matching, "model_type": "fake_t2v"})
    rig.set_wgp("get_model_def", lambda _model_type: None)
    reject("SCAIL-2 is not installed", {"video_path": video, "target_frame_path": matching})
    _install_scail(rig)
    monkeypatch.setattr(execution_mode, "POLICY", _replace(execution_mode.POLICY, mode="plan"))
    reject("plan mode", {"video_path": video, "target_frame_path": matching, "prompt": "a calm lake", "seed": 7})
    monkeypatch.setattr(execution_mode, "POLICY", _replace(execution_mode.POLICY, mode="real"))
    observed["jobs from the rejections"] = sorted(set(rig.launch._jobs) - before)
    observed["queued after the rejections"] = [record["id"] for record in rig.launch._durable_generation_queue.list()]

    clip = media.video(tmp_path / "range.mp4", seconds=1, size="96x64", fps=8)
    requests = {
        "whole frame, fast profile": {"video_path": video, "target_frame_path": matching, "prompt": "a calm lake",
                                      "seed": 7, "negative_prompt": "blur"},
        "704p with unknown VRAM": {"video_path": video, "target_frame_path": matching,
                                   "resolution_profile": "704p", "seed": 3},
        "HQ profile": {"video_path": video, "target_frame_path": matching, "model_type": "scail2_14B",
                       "num_inference_steps": 12, "guidance_scale": 7, "seed": 9},
        "trimmed range": {"video_path": str(clip), "target_frame_path": matching,
                          "start_time": 0.0, "end_time": 0.4, "seed": 11},
    }
    for case, body in requests.items():
        since = len(rig.engine.calls)
        status, answer = _submit(rig, "/api/v1/repaint", body)
        _join_repaint_workers()
        observed[case] = {"status": status, "answer": answer}
        if status == 200 and isinstance(answer, dict) and "job_id" in answer:
            observed[case]["job"] = _job(rig, answer["job_id"], since)
    rig.check(golden, "repaint prepares a job", observed)


def test_repaint_with_mappings_stops_when_magic_mask_refuses(rig, golden, monkeypatch) -> None:
    """The mapped branch starts ``_run_repaint``. The stub raises before SAM, so nothing is downloaded."""
    from shared import magic_mask

    _probe_as(monkeypatch)
    _install_scail(rig)

    def refuse(*_args, **_kwargs):
        raise RuntimeError("SAM stub: tests do not download Magic Mask")

    monkeypatch.setattr(magic_mask, "prepare_video_mask_input", refuse)
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", refuse)
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    matching = _frame(folder, "frame.png", (96, 64))
    since = len(rig.engine.calls)
    status, answer = _submit(rig, "/api/v1/repaint", {
        "video_path": video, "target_frame_path": matching, "seed": 5,
        "region_mappings": [{"source": "person in blue", "target": "person in red"}],
    })
    _join_repaint_workers()
    observed = {"status": status, "answer": answer, "engine calls since": len(rig.engine.calls) - since}
    if status == 200 and isinstance(answer, dict) and "job_id" in answer:
        observed["job"] = _job(rig, answer["job_id"], since)
    rig.check(golden, "mapped repaint stops when magic mask refuses", observed)


def test_openapi_text_of_the_repaint_routes(server, golden) -> None:
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


# -- The wiring the move added --------------------------------------------------------------------------
# Each Repaint module is bound once, to launch's own globals. A proxy reads that dict when the function
# runs, so a patch of the launch name is what the moved function calls. A second bind to another dict
# is refused and leaves the first one in place.

_PLANNING_EXPORTS = (
    "bind_repaint_planning",
    "_normalize_repaint_region_mappings",
    "_repaint_resolution_for_aspect",
    "_validate_repaint_target_aspect",
    "_prepare_repaint_target_frame",
    "_repaint_preview_data_uri",
    "_build_repaint_semantic_conditioning",
    "_build_repaint_shot_prompt",
    "_build_repaint_shot_reference_conditioning",
    "_build_repaint_shot_manifest",
)


def _repaint_runtime_modules():
    import importlib

    modules = [importlib.import_module("services.repaint_planning")]
    try:
        modules.append(importlib.import_module("services.repaint_run"))
    except ModuleNotFoundError:
        pass
    try:
        modules.append(importlib.import_module("routers.repaint"))
    except ModuleNotFoundError:
        pass
    return modules


def test_repaint_modules_read_the_objects_launch_gave_them(full_server, monkeypatch) -> None:
    from services.repaint_binding import LaunchName

    del full_server
    launch = worker_module()
    modules = _repaint_runtime_modules()
    planning = modules[0]
    for module in modules:
        assert module._NAMESPACE[0] is vars(launch), module.__name__
        for name in module._LAUNCH_NAMES:
            proxy = getattr(module, name)
            assert isinstance(proxy, LaunchName), f"{module.__name__}.{name} is not a launch proxy"
            assert proxy.resolve() is getattr(launch, name), f"{module.__name__}.{name} is not launch.{name}"
    for name in _PLANNING_EXPORTS:
        assert getattr(launch, name) is getattr(planning, name), name

    sentinel = ("slot-color",)
    monkeypatch.setattr(launch, "_RECAST_MASK_COLORS", sentinel)
    colors = planning._RECAST_MASK_COLORS
    assert colors.resolve() is sentinel
    assert len(colors) == 1 and colors[0] == "slot-color" and colors[:1] == sentinel
    assert bool(colors) is True

    seen: list[str] = []

    def _patched(*_args, **_kwargs):
        seen.append("called")
        return "patched"

    monkeypatch.setattr(launch, "_detect_recast_shot_ranges", _patched)
    assert planning._detect_recast_shot_ranges(None) == "patched"
    assert seen == ["called"]
    assert planning._detect_recast_shot_ranges.__name__ == "_patched"

    with pytest.raises(RuntimeError, match="already bound"):
        planning.bind_repaint_planning({})
    assert planning._NAMESPACE[0] is vars(launch)

    run = next(module for module in modules if module.__name__ == "services.repaint_run")
    for name in (
        "bind_repaint_run",
        "_write_repaint_shot_aware_sidecar",
        "_run_repaint_shot_generation",
    ):
        assert getattr(launch, name) is getattr(run, name), name

    def _generation(*args, **kwargs):
        return ("generation", args, kwargs)

    monkeypatch.setattr(launch, "_run_generation", _generation)
    assert run._run_generation("job", finalize=False) == ("generation", ("job",), {"finalize": False})
    assert run._run_generation.__name__ == "_generation"
    with pytest.raises(RuntimeError, match="already bound"):
        run.bind_repaint_run({})
    assert run._NAMESPACE[0] is vars(launch)
