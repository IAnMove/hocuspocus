"""Cheap answers of the Repaint routes, recorded before they left launch.

``POST /api/v1/repaint/preview`` and ``POST /api/v1/repaint`` now live in
``app/routers/repaint.py`` and answer the same way. These cases drive the
validation and error paths, one preview that draws semantic masks from a stub
(never SAM), and the no-mapping jobs the C0 fake engine finishes. A mapped
Repaint that tracks regions, writes shot videos and restores the source audio
needs a GPU and is not here; the one mapped case stubs Magic Mask so the
request thread records the failure without downloading a model.
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


# -- The wiring the move added (C6 review) ---------------------------------------------------------------------------
# Each Repaint module imports the standard library, execution_mode and the job lifecycle itself, and takes the launch
# objects it reads (wgp, the job registry and states, the workspace and job helpers, the mask colours, the recast and
# SCAIL-2 helpers) from one bind() (services) or its router factory, which launch calls once. The recast helpers are
# leaving launch in other PRs, and the generation worker and the hardware probe are defined further down, so those
# slots hold launch's forwarders, which look the launch name up when they are called. A slot left at None, bound to a
# copy or to another function, or a forwarder that captured its target at bind time would only show on the branch that
# reads it, so every global each moved function reads is compared here with the object launch holds under that name
# (or launch's forwarder for it), where the function read it before the move.
_C6_EXPORTS = {
    "services.repaint_planning": (
        "_normalize_repaint_region_mappings", "_repaint_resolution_for_aspect", "_validate_repaint_target_aspect",
        "_prepare_repaint_target_frame", "_repaint_preview_data_uri", "_build_repaint_semantic_conditioning",
        "_build_repaint_shot_prompt", "_build_repaint_shot_reference_conditioning", "_build_repaint_shot_manifest",
    ),
    "services.repaint_run": ("_write_repaint_shot_aware_sidecar", "_run_repaint_shot_generation"),
    "routers.repaint": ("create_repaint_router", "repaint_preview_endpoint", "repaint_endpoint"),
}
# Launch names a slot reaches through a forwarder, and the forwarder launch passes for each.
_C6_FORWARDERS = {
    "_run_generation": "_forward_studio_run_generation",
    "_get_cached_hardware": "_forward_studio_cached_hardware",
    **{name: f"_forward_repaint{name}" for name in (
        "_build_recast_source_scene_reference", "_compose_recast_cast_reference_frame",
        "_compose_recast_character_masks", "_compose_recast_group_reference_frame", "_detect_recast_shot_ranges",
        "_plan_recast_shot_segments", "_quantize_recast_shot_frame_count", "_recolor_recast_reference_mask",
        "_remap_recast_shot_mask", "_resample_recast_tracking_timeline", "_resize_recast_shot_frames",
        "_save_recast_reference_pair", "_summarize_recast_mapping_mask", "_write_recast_shot_video",
        "_recast_video_frame_count", "_recast_video_has_audio", "_normalize_recast_resolution_profile",
        "_recast_resolution_for_source", "_recast_window_size_for_profile", "_resolve_recast_media",
    )},
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


def test_repaint_modules_read_the_objects_launch_holds(full_server, monkeypatch) -> None:
    import builtins
    import importlib
    import inspect

    del full_server
    launch = worker_module()
    compared: set[str] = set()
    slots: set[str] = set()
    for module_name, exported in _C6_EXPORTS.items():
        module = importlib.import_module(module_name)
        namespace = vars(module)
        for name in exported:
            assert getattr(launch, name) is namespace[name], f"launch.{name} is not {module_name}.{name}"
        own = {name for name, value in namespace.items()
               if inspect.isfunction(value) and value.__module__ == module_name}
        for function_name in sorted(own - {"bind", "create_repaint_router"}):
            for name in sorted(_global_reads(namespace[function_name])):
                if name in own:
                    continue  # a helper that moved with it
                if name not in namespace:
                    assert hasattr(builtins, name), f"{module_name}.{function_name} reads {name}, which is not defined"
                    continue
                expected = vars(launch)[_C6_FORWARDERS.get(name, name)]
                assert namespace[name] is expected, f"{module_name}.{name} is not the object launch holds"
                compared.add(name)
        module_slots = _bound_slots(module)
        assert module_slots, module_name
        for name in module_slots:
            assert namespace[name] is not None, f"{module_name}.{name} was never bound"
        slots |= module_slots
    assert slots <= compared
    # Generated from the AST: every global the moved functions read, other than the ones that moved with them.
    assert compared == {
        "os", "uuid", "time", "traceback", "threading", "HTTPException", "execution_mode", "wgp",
        "finish_job", "is_cancel_requested", "register_abort_state", "unregister_abort_state", "update_job",
        "try_start", "try_requeue", "_jobs", "_active_gen_states", "_coordinated_generation_slot",
        "_generation_job_acceptance", "_get_active_workspace", "_register_manual_generation_job", "_workspace_dir",
        "_RECAST_MASK_COLORS", "_normalize_scail2_guidance_scale", "_normalize_scail2_inference_steps",
        "_normalize_repaint_region_mappings", "_validate_repaint_target_aspect", "_prepare_repaint_target_frame",
        "_repaint_preview_data_uri", "_build_repaint_semantic_conditioning", "_build_repaint_shot_manifest",
        "_run_repaint_shot_generation", *_C6_FORWARDERS,
    }
    router = importlib.import_module("routers.repaint")
    run = importlib.import_module("services.repaint_run")
    # The abort registry the route and the shot worker write is the one the job kernel owns, not a copy.
    assert router._active_gen_states is launch.ctx.jobs.active_states
    assert run._active_gen_states is launch.ctx.jobs.active_states
    assert run._jobs is launch.ctx.jobs.registry
    # The hardware probe stays in launch and reads launch's cache when the route calls it.
    monkeypatch.setattr(launch, "_cached_hardware", {"gpu_vram_gb": 7.0})
    assert router._get_cached_hardware() == {"gpu_vram_gb": 7.0}

    # Each forwarder calls whatever launch holds under the name when it is called, not what it held at bind.
    for name, forwarder in sorted(_C6_FORWARDERS.items()):
        calls: list = []
        monkeypatch.setattr(launch, name, lambda *args, _seen=calls, _name=name, **kwargs:
                            _seen.append([_name, args, kwargs]) or _name)
        # The hardware probe takes no arguments; every other forwarder passes its arguments through.
        args, kwargs = ((), {}) if name == "_get_cached_hardware" else (("a",), {"key": "b"})
        assert getattr(launch, forwarder)(*args, **kwargs) == name, forwarder
        assert calls == [[name, args, kwargs]], forwarder
    for module in (router, run):
        assert module._run_generation("job-1", finalize=False) == "_run_generation"
    # Python names a route's worker thread from the target, so the forwarder keeps the worker's name.
    assert router._run_generation.__name__ == "_run_generation"


def test_a_launch_name_the_rig_patches_reaches_the_repaint_route(rig, monkeypatch) -> None:
    """Before the move a patch of a launch name reached the route. The rig patches every module that holds the name
    (``worker_modules()``), so the moved route still reads the patched object."""
    _probe_as(monkeypatch)
    _install_scail(rig)
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    matching = _frame(folder, "frame.png", (96, 64))
    rig.patch("_get_active_workspace", lambda: "patched-workspace")
    status, answer = _submit(rig, "/api/v1/repaint", {"video_path": video, "target_frame_path": matching, "seed": 1})
    _join_repaint_workers()
    assert status == 200, answer
    assert rig.launch._jobs[answer["job_id"]]["workspace"] == "patched-workspace"
