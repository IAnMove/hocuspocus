"""Outpaint and blend, recorded on the code before it left launch (C5 review).

The goldens in ``goldens/test_outpaint_blend.json`` were recorded on the tree where these functions still lived in
``_launch_runtime`` (7a58ddf1b plus the C5 goldens commit 824fb45bf), then replayed unchanged after the move. Every
helper is reached through the full server module (``worker_module()``) and every collaborator is replaced through
``Rig.patch``/``rig.set_wgp``, so the same file runs on both trees.

What is recorded:

- the planning helpers' answers for many inputs (canvas geometry, sampling, video timing, the single-stage window
  cap, the shot filter, the LTX-2 reference model choice, the shot manifest, the shot guide ffmpeg call and the camera
  cut detection);
- what ``POST /api/v1/outpaint`` and ``POST /api/v1/blend`` hand the worker (the job params and which worker they
  start) for each mode, with the worker replaced by a recorder;
- jobs the C0 fake engine runs end to end: a two-shot official outpaint, its failure and cancel paths, a blend
  assembled from two clips (the ffmpeg concat command and filter script), its ffmpeg failure, and a cancelled blend.

No model is downloaded (non-local sockets are blocked) and no GPU is used. ffmpeg is used to make test clips; the
blend concat and the outpaint trim are recorded from a stubbed ``subprocess.run`` because their commands are the
contract and the local encoder is not.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.characterization import media
from tests.characterization.test_run_generation import WAIT, worker_module
# Fixtures, used by name: the C0 rig and its decodable clip.
from tests.characterization.test_run_generation import clip, rig  # noqa: F401
from tests.characterization.test_studio_generate import _block_network, _join_route_workers, _submit

# -- helpers ------------------------------------------------------------------------------------------------------


def _outcome(call) -> dict:
    """The value a helper returns (as a golden file holds it: tuples become lists), or the error it raises."""
    try:
        return {"value": json.loads(json.dumps(call(), default=str))}
    except Exception as error:  # the recorded behaviour includes the message
        return {"error": f"{type(error).__name__}: {error}"}


def _scrub(body, *pairs: tuple[str, str]):
    """JSON round trip with machine paths (temp folders the normaliser does not know) replaced."""
    text = json.dumps(body, default=str)
    for path, placeholder in sorted(pairs, key=lambda pair: len(pair[0]), reverse=True):
        if path:
            text = text.replace(path, placeholder)
    return json.loads(text)


class _TempDirs:
    """Every ``tempfile.mkdtemp`` the routes and workers make, so a test can name them and see they are gone."""

    def __init__(self, monkeypatch) -> None:
        self.made: list[str] = []
        real = tempfile.mkdtemp

        def mkdtemp(*args, **kwargs):
            path = real(*args, **kwargs)
            self.made.append(path)
            return path

        monkeypatch.setattr(tempfile, "mkdtemp", mkdtemp)

    def pairs(self) -> tuple:
        return tuple((path, f"<TEMP{index}>") for index, path in enumerate(self.made))

    def left(self) -> list[bool]:
        return [Path(path).exists() for path in self.made]


def _two_shot_clip(path: Path, *, fps: int = 8) -> Path:
    """Blue then red, 1.5 s each: one hard camera cut in the middle."""
    media.need_ffmpeg()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y",
         "-f", "lavfi", "-i", f"color=c=blue:s=64x36:r={fps}:d=1.5",
         "-f", "lavfi", "-i", f"color=c=red:s=64x36:r={fps}:d=1.5",
         "-filter_complex", "[0:v][1:v]concat=n=2:v=1:a=0", "-c:v", "mpeg4", "-q:v", "2", str(path)],
        check=True, capture_output=True,
    )
    return path


def _video(path: Path, *, frames: int, fps: int = 8, size: str = "64x36") -> Path:
    media.need_ffmpeg()
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=green:s={size}:r={fps}",
         "-frames:v", str(frames), "-c:v", "mpeg4", "-q:v", "2", str(path)],
        check=True, capture_output=True,
    )
    return path


# A fake official LTX-2.3 Dev model: its definition short-circuits the reference resolver (nothing to download).
FAKE_LTX = {
    "architecture": "ltx2_22B",
    "ltx2_pipeline": "two_stage",
    "fps": 8,
    "frames_minimum": 1,
    "latent_size": 1,
    "URLs": [],
    "name": "Fake LTX Dev",
    "sliding_window_defaults": {"window_default": 241, "overlap_default": 9, "discard_last_frames": 8,
                                "window_min": 17, "window_max": 501},
}


def _official_ltx(rig, *, extra: dict | None = None) -> None:
    """``fake_ltx`` and friends are LTX-2.3 22B models in the fake WanGP."""
    real_base = rig.server.wgp.get_base_model_type
    real_def = rig.server.wgp.get_model_def
    models = {"fake_ltx": FAKE_LTX, **(extra or {})}

    def base_type(model_type):
        if model_type in models:
            return "ltx2_22B"
        if model_type == "fake_13b":
            return "ltxv_13B"
        return real_base(model_type)

    def model_def(model_type):
        if model_type in models:
            return dict(models[model_type])
        return real_def(model_type)

    rig.set_wgp("get_base_model_type", base_type)
    rig.set_wgp("get_model_def", model_def)


# -- planning helpers ---------------------------------------------------------------------------------------------
GEOMETRY_CASES = [
    (64, 64, 0, 0, 0, 64, "auto", 32),
    (64, 64, 0, 0, 0, 64, "auto", 64),
    (1280, 720, 0, 0, 280, 280, "auto", 64),
    (1280, 720, 100, 100, 0, 0, "720p", 64),
    (720, 1280, 0, 0, 300, 300, "480p", 32),
    (333, 197, 13, 7, 21, 5, "540p", 32),
    (333, 197, 13, 7, 21, 5, "1080p", 64),
    (1920, 1080, 0, 0, 0, 1, "weird", 64),
    (1920, 1080, 37, 0, 0, 0, "auto", 64),
    (10, 10, 0, 0, 0, 0, None, 64),
    (0, -5, -3, 2, 0, 1, "AUTO", 0),
    ("640", "360", "8", "8", "8", "8", "720P", "32"),
]


def test_outpaint_canvas_geometry(full_server, golden) -> None:
    helpers = worker_module()
    answers = {repr(case): _outcome(lambda case=case: helpers._resolve_outpaint_canvas_geometry(*case))
               for case in GEOMETRY_CASES}
    answers["defaults"] = _outcome(lambda: helpers._resolve_outpaint_canvas_geometry(100, 50, 10, 10, 10, 10))
    golden.check("outpaint canvas geometry", 200, answers)


SAMPLING_CASES = {
    "defaults from the model definition": ({}, "ltx2_22B", {"num_inference_steps": 30, "guidance_scale": 3.5}, {}),
    "defaults from saved settings": ({}, "fake", {}, {"num_inference_steps": 12, "guidance_scale": 2}),
    "built-in defaults": ({}, "fake", None, None),
    "the body wins": ({"num_inference_steps": "9", "guidance_scale": "4.5"}, "fake", {"num_inference_steps": 30}, {}),
    "locked steps": ({"num_inference_steps": 50, "guidance_scale": 7}, "fake",
                     {"num_inference_steps": 8, "lock_inference_steps": True}, {}),
    "locked guidance": ({"num_inference_steps": 50, "guidance_scale": 7}, "fake",
                        {"guidance_scale": 1.5, "lock_guidance_scale": True}, {}),
    "13B under twenty": ({"num_inference_steps": 19}, "ltxv_13B", {}, {}),
    "13B at twenty": ({"num_inference_steps": 20}, "ltxv_13B", {}, {}),
    "13B locked short": ({}, "ltxv_13B", {"num_inference_steps": 8, "lock_inference_steps": True}, {}),
    "negative steps": ({"num_inference_steps": -1}, "fake", {}, {}),
    "text guidance": ({"guidance_scale": "x"}, "fake", {}, {}),
    "text model default": ({}, "fake", {"num_inference_steps": "many"}, {}),
    "zero model defaults fall back": ({}, "fake", {"num_inference_steps": 0, "guidance_scale": 0}, {}),
    "settings not a dict": ({}, "fake", "bad", ["bad"]),
}


def test_outpaint_sampling(full_server, golden) -> None:
    helpers = worker_module()
    answers = {case: _outcome(lambda args=args: helpers._resolve_outpaint_sampling(*args))
               for case, args in SAMPLING_CASES.items()}
    golden.check("outpaint sampling", 200, answers)


TIMING_CASES = [
    (24, 8.0, {"fps": 8, "frames_minimum": 1, "latent_size": 1}, None),
    (24, 8.0, {"fps": 24, "frames_minimum": 17, "latent_size": 8}, None),
    (100, 30.0, {"fps": 24, "frames_minimum": 17, "latent_size": 8}, None),
    (100, 30.0, {"fps": 24, "frames_minimum": 17, "latent_size": 8}, 24),
    (100, 30.0, {"fps": 24, "frames_minimum": 17, "frames_steps": 4}, 24),
    (241, 23.976, {"fps": 24, "frames_minimum": 17, "latent_size": 8}, None),
    (5, 0, {}, None),
    ("x", "y", {"fps": "bad", "frames_minimum": "bad", "latent_size": "bad"}, "bad"),
    (10, float("nan"), {"fps": -3}, float("inf")),
    (10, float("inf"), {"fps": float("nan")}, -24),
    (0, 12.5, None, 0),
    (3, 25, {"frames_minimum": 0, "latent_size": 0, "frames_steps": 3}, 12.5),
]


def test_outpaint_video_timing(full_server, golden) -> None:
    helpers = worker_module()
    answers = {repr(case): _outcome(lambda case=case: list(helpers._resolve_outpaint_video_timing(*case)))
               for case in TIMING_CASES}
    golden.check("outpaint video timing", 200, answers)


CAP_CASES = [
    (241, 1280, 704, 17, 501),
    (241, 1280, 736, 17, 501),
    (257, 1920, 1088, 17, 501),
    (600, 640, 360, 17, 501),
    (5, 640, 360, 17, 501),
    (241, 3840, 2176, 17, 501),
    (241, 1920, 1088, 33, 49),
    ("97", "1280", "720", "17", "501"),
    (0, 0, 0, 0, 0),
    (241, 1920, 1088, 200, 100),
]


def test_outpaint_single_stage_window_cap(full_server, golden) -> None:
    helpers = worker_module()
    answers = {repr(case): _outcome(lambda case=case: helpers._cap_outpaint_single_stage_window(*case))
               for case in CAP_CASES}
    answers["defaults"] = _outcome(lambda: helpers._cap_outpaint_single_stage_window(1000, 1920, 1088))
    answers["constants"] = [helpers._OUTPAINT_PIXEL_BUDGETS, helpers._OUTPAINT_SINGLE_STAGE_REFERENCE_PIXELS,
                            helpers._OUTPAINT_SINGLE_STAGE_REFERENCE_FRAMES]
    golden.check("outpaint single-stage window cap", 200, answers)


def test_outpaint_percentage_and_shot_filter(full_server, golden) -> None:
    helpers = worker_module()
    percentages = {repr(value): _outcome(lambda value=value: helpers._format_outpaint_percentage(value))
                   for value in (0, 0.0, 12.5, 33.333333333, 1e-9, 100, -2.5, "7.25", 66.666666666666)}
    filters = {repr(args): _outcome(lambda args=args: helpers._build_outpaint_shot_filter(*args))
               for args in ((0, 12, 5, 8), (12, 24, 0, 23.976), ("3", "9", "-2", "30000"), (3, 3, 0, 8),
                            (-1, 4, 0, 8), (0, 4, 0, 0), (0, 4, 0, "inf"), (0, 4, 0, -24))}
    golden.check("outpaint percentage and shot filter", 200, {"percentages": percentages, "filters": filters})


# The installed-file question is the only thing the resolver asks the disk; it is answered from ``installed``.
RESOLVER_MODELS = {
    "ltx_dev": {"architecture": "ltx2_22B", "ltx2_pipeline": "two_stage"},
    "ltx_dev_default_pipeline": {"architecture": "ltx2_22B"},
    "ltx_distilled": {"architecture": "ltx2_22B", "ltx2_pipeline": "distilled"},
    "ltx_distilled_FP8": {"architecture": "ltx2_22B", "ltx2_pipeline": "distilled"},
    "wan_model": {"architecture": "wan"},
    "ltx2_22B_1_1": {"architecture": "ltx2_22B", "ltx2_pipeline": "two_stage",
                     "URLs": ["https://host/models/ltx%201.1/ltx-1.1-dev.safetensors?download=1"]},
    "ltx2_22B_fp8": {"architecture": "ltx2_22B",
                     "URLs": ["https://host/models/ltx-fp8-dev.safetensors", "relative/ltx-fp8-extra.safetensors"]},
    "ltx2_22B": {"architecture": "ltx2_22B", "ltx2_pipeline": "distilled",
                 "URLs": ["https://host/models/ltx-distilled.safetensors"]},
}
RESOLVER_CASES = [
    ("ltx_dev", []),
    ("ltx_dev_default_pipeline", []),
    ("ltx_distilled", []),
    ("ltx_distilled", ["ltx-fp8-dev.safetensors"]),
    ("ltx_distilled", ["ltx-1.1-dev.safetensors", "ltx-fp8-dev.safetensors"]),
    ("ltx_distilled_FP8", ["ltx-1.1-dev.safetensors", "ltx-fp8-dev.safetensors"]),
    ("ltx_distilled_FP8", ["ltx-fp8-extra.safetensors"]),
    ("ltx_distilled", ["ltx-distilled.safetensors"]),
    ("wan_model", ["ltx-1.1-dev.safetensors"]),
    ("missing_model", ["ltx-1.1-dev.safetensors"]),
    (None, []),
]


def test_ltx2_outpaint_reference_model(rig, golden, monkeypatch) -> None:
    from shared.utils import files_locator

    helpers = worker_module()
    asked: list = []
    installed: list[str] = []

    def model_def(model_type):
        asked.append(["def", model_type])
        found = RESOLVER_MODELS.get(model_type)
        return dict(found) if found is not None else None

    def recursive_prop(model_type, prop, return_list=False):
        asked.append(["urls", model_type, prop, return_list])
        return list(RESOLVER_MODELS.get(model_type, {}).get(prop) or [])

    def locate_file(filename, error_if_none=True):
        asked.append(["locate", filename, error_if_none])
        return f"/models/{filename}" if filename in installed else None

    rig.set_wgp("get_model_def", model_def)
    rig.set_wgp("get_model_recursive_prop", recursive_prop)
    monkeypatch.setattr(files_locator, "locate_file", locate_file)
    answers = {}
    for requested, files in RESOLVER_CASES:
        asked.clear()
        installed[:] = files
        answer = _outcome(lambda requested=requested: helpers._resolve_ltx2_outpaint_reference_model(requested))
        answers[f"{requested} with {files}"] = {**answer, "asked": list(asked)}
    golden.check("ltx2 outpaint reference model", 200, answers)


def test_outpaint_shot_manifest(rig, golden, tmp_path) -> None:
    helpers = worker_module()
    written: list = []

    def writer(source, guide, *, start_frame, end_frame, pad_frames, fps, abort_callback=None):
        written.append([Path(source).name, Path(guide).name, start_frame, end_frame, pad_frames, fps,
                        abort_callback is not None])

    # The default writer is the module's own; replaced here so the manifest is planned without ffmpeg.
    rig.patch("_write_outpaint_shot_guide", writer)
    base = {"prompt": "kept out of the tasks", "seed": 3}
    cases = {
        "two shots on the 17 + 8k grid": dict(shot_ranges=[(0, 12), (12, 24)], target_frame_count=24,
                                              generation_fps=8, minimum_frames=17, latent_size=8),
        "three uneven shots, unit grid": dict(shot_ranges=[[0, 1], [1, 10], [10, 30]], target_frame_count=30,
                                              generation_fps=23.976, minimum_frames=1, latent_size=1),
        "no ranges is one shot": dict(shot_ranges=None, target_frame_count=9, generation_fps="12",
                                      minimum_frames=5, latent_size=4),
        "a gap": dict(shot_ranges=[(0, 4), (5, 9)], target_frame_count=9, generation_fps=8,
                      minimum_frames=1, latent_size=1),
        "an empty shot": dict(shot_ranges=[(0, 0), (0, 9)], target_frame_count=9, generation_fps=8,
                              minimum_frames=1, latent_size=1),
        "past the timeline": dict(shot_ranges=[(0, 10)], target_frame_count=9, generation_fps=8,
                                  minimum_frames=1, latent_size=1),
        "short of the timeline": dict(shot_ranges=[(0, 4), (4, 8)], target_frame_count=9, generation_fps=8,
                                      minimum_frames=1, latent_size=1),
        "no timeline": dict(shot_ranges=[], target_frame_count=0, generation_fps=8, minimum_frames=1, latent_size=1),
    }
    answers = {}
    for case, kwargs in cases.items():
        written.clear()
        progress: list = []
        out = tmp_path / case.replace(" ", "-")
        answer = _outcome(lambda kwargs=kwargs, out=out, progress=progress: helpers._build_outpaint_shot_manifest(
            base, "/media/source clip.mp4", kwargs.pop("shot_ranges"), str(out), "job7",
            progress_callback=lambda index, total: progress.append([index, total]), **kwargs))
        answers[case] = {**_scrub(answer, (str(out), "<DIR>")), "written": written[:], "progress": progress,
                         "folder made": out.is_dir()}

    explicit: list = []
    calls = []

    def abort():
        calls.append("abort check")
        if len(calls) > 2:
            raise InterruptedError("cancelled at the second shot")

    out = tmp_path / "explicit"
    answer = _outcome(lambda: helpers._build_outpaint_shot_manifest(
        base, "source.mp4", [(0, 3), (3, 6)], str(out), "job8", target_frame_count=6, generation_fps=6,
        minimum_frames=1, latent_size=1, abort_callback=abort,
        guide_writer=lambda *args, **kwargs: explicit.append([Path(args[1]).name, kwargs["start_frame"]])))
    answers["an explicit writer, cancelled at shot two"] = {**_scrub(answer, (str(out), "<DIR>")),
                                                            "explicit": explicit, "default writer": written[:],
                                                            "abort checks": calls}
    golden.check("outpaint shot manifest", 200, answers)


def test_outpaint_shot_guide_is_one_ffmpeg_call(rig, golden, tmp_path, monkeypatch) -> None:
    """The guide writer's ffmpeg command, timeout and frame check. ffmpeg runs for real; the command is recorded."""
    helpers = worker_module()
    source = _video(tmp_path / "source.mp4", frames=16)
    commands: list = []
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        if command and Path(str(command[0])).name.startswith("ffmpeg") and "-vf" in command:
            commands.append([[str(part).replace(str(tmp_path), "<TMP>") for part in command],
                             kwargs.get("timeout")])
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.delenv("FFMPEG_BINARY", raising=False)
    checks: list = []
    answers = {}
    guide = tmp_path / "guides" / "shot.mp4"
    answer = _outcome(lambda: helpers._write_outpaint_shot_guide(
        str(source), str(guide), start_frame=4, end_frame=12, pad_frames=3, fps=8,
        abort_callback=lambda: checks.append("check")))
    answers["four to twelve, three padded"] = {
        **_scrub(answer, (str(tmp_path), "<TMP>")), "frames": helpers._recast_video_frame_count(str(guide)),
        "abort checks": len(checks)}
    long_guide = tmp_path / "long.mp4"
    answer = _outcome(lambda: helpers._write_outpaint_shot_guide(
        str(source), str(long_guide), start_frame=0, end_frame=16, pad_frames=-4, fps=0.1))
    answers["a slow rate stretches the timeout"] = {**_scrub(answer, (str(tmp_path), "<TMP>")),
                                                    "frames": helpers._recast_video_frame_count(str(long_guide))}
    answers["bad bounds never run ffmpeg"] = _outcome(lambda: helpers._write_outpaint_shot_guide(
        str(source), str(tmp_path / "bad.mp4"), start_frame=5, end_frame=5, pad_frames=0, fps=8))
    missing = _outcome(lambda: helpers._write_outpaint_shot_guide(
        str(tmp_path / "missing.mp4"), str(tmp_path / "out-missing.mp4"), start_frame=0, end_frame=4,
        pad_frames=0, fps=8))
    answers["a source ffmpeg cannot read"] = {
        "error": missing.get("error", "")[:len("RuntimeError: Could not prepare Outpaint camera shot: ")],
        "left": (tmp_path / "out-missing.mp4").exists()}
    rig.patch("_recast_video_frame_count", lambda path: 99)
    answers["a guide of the wrong length"] = {**_outcome(lambda: helpers._write_outpaint_shot_guide(
        str(source), str(tmp_path / "wrong.mp4"), start_frame=0, end_frame=4, pad_frames=1, fps=8)),
        "left": (tmp_path / "wrong.mp4").exists()}
    answers["commands"] = commands
    golden.check("outpaint shot guide", 200, answers)


def test_outpaint_camera_cut_detection(full_server, golden, tmp_path) -> None:
    helpers = worker_module()
    two_shots = _two_shot_clip(tmp_path / "two-shots.mp4")
    calls: list = []

    def stop_at_five():
        calls.append("check")
        if len(calls) >= 5:
            raise InterruptedError("stopped")

    answers = {
        "two shots": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(str(two_shots), 24)),
        "only the planned frames": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(str(two_shots), "10")),
        "the source ends early": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(str(two_shots), 30)),
        "one frame short": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(str(two_shots), 25)),
        "a missing source": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(
            str(tmp_path / "missing.mp4"), 4)),
        "an empty file": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(
            str((tmp_path / "empty.mp4").write_bytes(b"") or tmp_path / "empty.mp4"), 4)),
        "cancelled while reading": {**_outcome(lambda: helpers._detect_outpaint_video_shot_ranges(
            str(two_shots), 24, abort_callback=stop_at_five)), "checks": len(calls)},
        "long minimum shot": _outcome(lambda: helpers._detect_outpaint_video_shot_ranges(
            str(two_shots), 24, min_shot_frames=20)),
    }
    golden.check("outpaint camera cut detection", 200, _scrub(answers, (str(tmp_path), "<TMP>")))


# -- what the routes hand the worker ------------------------------------------------------------------------------


def _capture_workers(rig) -> list:
    """Replace the three workers a route can start with recorders; returns the names started, in order."""
    started: list = []
    lock = threading.Lock()

    def recorder(name):
        def worker(job_id, **kwargs):
            with lock:
                started.append(name)

        worker.__name__ = f"recorded {name}"
        return worker

    for name in ("_run_generation", "_prepare_and_run_outpaint", "_run_blend_generation"):
        rig.patch(name, recorder(name))
    return started


def _describe_media(value):
    """Frame count and size of a video, size of a picture: what the route wrote for the worker to read."""
    if isinstance(value, list):
        return [_describe_media(item) for item in value]
    if not isinstance(value, str) or not Path(value).is_file():
        return value
    if value.endswith(".mp4"):
        import decord

        reader = decord.VideoReader(value)
        try:
            return {"frames": len(reader), "shape": list(reader[0].shape)}
        finally:
            del reader
    from PIL import Image

    with Image.open(value) as picture:
        return {"size": list(picture.size)}


def _hand_off(rig, path: str, body: dict, started: list, *, temp=None) -> dict:
    """Post one request; with the worker recorded, return the answer, the worker started and the job's params."""
    before = len(started)
    status, answer = _submit(rig, path, body)
    observed: dict = {"status": status, "answer": answer}
    if status == 200:
        rig.wait_until(lambda: len(started) > before, "the route started its worker")
        job = rig.launch._jobs[answer["job_id"]]
        observed.update({
            "worker": started[before:],
            "params": json.loads(json.dumps(job.get("params") or {}, default=str, sort_keys=True)),
            "job": {key: job.get(key) for key in ("status", "message", "workspace", "out_dir", "phase")},
        })
        if path == "/api/v1/blend":
            params = job.get("params") or {}
            observed["media"] = {key: _describe_media(params.get(key)) for key in (
                "image_start", "image_end", "video_source", "video_end", "image_refs") if params.get(key)}
    return _scrub(observed, *(temp.pairs() if temp else ()))


def test_outpaint_hands_the_worker_each_mode(rig, golden, tmp_path, monkeypatch) -> None:
    _block_network(monkeypatch)
    started = _capture_workers(rig)
    _official_ltx(rig, extra={
        "fake_ltx_distilled": {**FAKE_LTX, "ltx2_pipeline": "distilled", "name": "Fake LTX Distilled"},
    })
    rig.set_wgp("get_default_settings", lambda model_type: {"num_inference_steps": 6, "guidance_scale": 2.0}
                if model_type == "fake_i2v" else {})
    still = media.image(tmp_path / "still.png", size=(64, 48))
    clip_path = media.video(tmp_path / "clip.mp4", seconds=3, size="64x36", fps=8)
    outside = media.image(tmp_path / "outside.png", size=(32, 32))
    workspace_file = media.image(rig.server.outputs / "in-workspace.png", size=(40, 24))
    (rig.server.root / "uploads").mkdir(exist_ok=True)
    media.image(rig.server.root / "uploads" / "uploaded.png", size=(24, 40))
    cases = {
        "image, four sides, 720p, LoRAs and clamps": {
            "video_path": str(still), "model_type": "fake_t2v", "prompt": "  a wide lake  ", "seed": 11,
            "negative_prompt": "blurry", "pad_top": 16, "pad_bottom": "8", "pad_left": 32, "pad_right": 24,
            "resolution_preset": "720P",
            "activated_loras": ["user_a.safetensors", "dir/LTX-2.3-22B-IC-LORA-OUTPAINT.safetensors",
                                "dir/user_b.safetensors", "user_c.safetensors"],
            "loras_multipliers": "0.7;0.3 1.0 0.5",
            "source_preservation": 0.1, "outpaint_lora_strength": 5, "lock_source_pixels": True,
            "preserve_source_audio": True, "outpaint_aspect": "16:9", "input_video_strength": 0.6,
            "num_inference_steps": 9, "guidance_scale": 3,
        },
        "image, the default prompt, saved settings": {
            "video_path": str(still), "model_type": "fake_i2v", "prompt": "Extend the scene naturally",
            "pad_right": 64, "source_preservation": 2, "outpaint_lora_strength": -1,
            "activated_loras": ["ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors"], "loras_multipliers": "",
        },
        "video, legacy, pixels locked, audio kept, multi-window": {
            "video_path": str(clip_path), "model_type": "fake_t2v", "prompt": "", "pad_left": 32,
            "lock_source_pixels": True, "preserve_source_audio": True, "sliding_window_size": 17,
            "sliding_window_overlap": 4, "sliding_window_discard_last_frames": 2,
        },
        "video, legacy, nothing kept, no smear trim": {
            "video_path": str(clip_path), "model_type": "fake_t2v", "pad_bottom": 20, "pad_top": 4,
            "lock_source_pixels": False, "preserve_source_audio": False, "trim_window_smear": False,
            "sliding_window_size": 9, "resolution_preset": "480p",
        },
        "video, legacy, window larger than the clip": {
            "video_path": str(clip_path), "model_type": "fake_t2v", "pad_right": 8, "sliding_window_size": 1000,
            "sliding_window_overlap": 3,
        },
        "video, LTX without mask preservation": {
            "video_path": str(clip_path), "model_type": "fake_ltx", "pad_right": 64,
            "mask_preserving_outpaint": False, "num_inference_steps": 4, "lock_source_pixels": True,
            "activated_loras": ["mine.safetensors"], "loras_multipliers": "0.9",
        },
        "image, LTX (the official path is for video)": {
            "video_path": str(still), "model_type": "fake_ltx", "pad_left": 64, "num_inference_steps": 4,
        },
        "video, official, huge canvas caps the window": {
            "video_path": str(clip_path), "model_type": "fake_ltx", "pad_right": 2000, "resolution_preset": "1080p",
            "prompt": "Extend the scene naturally", "negative_prompt": "never used", "num_inference_steps": 30,
            "guidance_scale": 6, "activated_loras": ["mine.safetensors", "ltx-2.3-22b-ic-lora-outpaint.safetensors"],
            "loras_multipliers": "0.9 1", "lock_source_pixels": True, "source_preservation": 0.4,
            "outpaint_lora_strength": 0.2, "sliding_window_size": 300,
        },
        "video, official, small canvas keeps the window": {
            "video_path": str(clip_path), "model_type": "fake_ltx", "pad_right": 64, "prompt": "a red sky",
            "seed": 5, "preserve_source_audio": False,
        },
        "video, official, a distilled request with nothing installed": {
            "video_path": str(clip_path), "model_type": "fake_ltx_distilled", "pad_top": 64,
        },
        "relative path inside the workspace": {
            "video_path": workspace_file.name, "model_type": "fake_t2v", "pad_right": 8,
        },
        "relative path found in uploads by its name": {
            "video_path": "elsewhere/uploaded.png", "model_type": "fake_t2v", "pad_right": 8,
        },
        "relative path that climbs out of the workspace": {
            "video_path": f"../{outside.name}", "model_type": "fake_t2v", "pad_right": 8,
        },
        "relative path that climbs to nothing": {
            "video_path": "../../no/such/file.png", "model_type": "fake_t2v", "pad_right": 8,
        },
        "a named workspace": {
            "video_path": str(still), "model_type": "fake_t2v", "pad_right": 8, "workspace": "ws-outpaint",
        },
        "text guidance": {
            "video_path": str(still), "model_type": "fake_t2v", "pad_right": 8, "guidance_scale": "loud",
        },
        "13B at twenty steps": {
            "video_path": str(still), "model_type": "fake_13b", "pad_right": 8, "num_inference_steps": 20,
        },
    }
    answers = {case: _hand_off(rig, "/api/v1/outpaint", body, started) for case, body in cases.items()}
    # A distilled request with an installed Dev checkpoint switches to that checkpoint.
    from shared.utils import files_locator

    real_def = rig.server.wgp.get_model_def
    rig.set_wgp("get_model_def", lambda model_type: (
        {**FAKE_LTX, "URLs": ["https://host/ltx-1.1-dev.safetensors"], "name": "Fake LTX 1.1 Dev"}
        if model_type == "ltx2_22B_1_1" else real_def(model_type)))
    rig.set_wgp("get_model_recursive_prop", lambda model_type, prop, return_list=False: (
        ["https://host/ltx-1.1-dev.safetensors"] if model_type == "ltx2_22B_1_1" else []))
    monkeypatch.setattr(files_locator, "locate_file", lambda filename, error_if_none=True: (
        f"/models/{filename}" if filename == "ltx-1.1-dev.safetensors" else None))
    answers["video, official, a distilled request with Dev installed"] = _hand_off(rig, "/api/v1/outpaint", {
        "video_path": str(clip_path), "model_type": "fake_ltx_distilled", "pad_left": 64}, started)

    def broken(model_type):
        raise RuntimeError(f"no settings for {model_type}")

    rig.set_wgp("get_default_settings", broken)
    answers["image, settings that cannot be read"] = _hand_off(rig, "/api/v1/outpaint", {
        "video_path": str(still), "model_type": "fake_t2v", "pad_right": 8}, started)
    rig.patch("execution_mode", SimpleNamespace(policy=lambda: SimpleNamespace(simulated=True, mode="simulate")))
    answers["video, official, simulated"] = _hand_off(rig, "/api/v1/outpaint", {
        "video_path": str(clip_path), "model_type": "fake_ltx", "pad_right": 64}, started)
    rig.check(golden, "outpaint hands the worker each mode", _scrub(answers, (str(tmp_path), "<TMP>")))


def test_outpaint_trims_a_video_range_first(rig, golden, tmp_path, monkeypatch) -> None:
    """With start_time and end_time the route re-encodes that range into uploads/ before it reads the clip."""
    _block_network(monkeypatch)
    started = _capture_workers(rig)
    clip_path = media.video(tmp_path / "long.mp4", seconds=3, size="64x36", fps=8)
    short = _video(tmp_path / "short.mp4", frames=12)
    commands: list = []
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        if command and command[0] == "ffmpeg" and "-ss" in command:
            commands.append([list(command), kwargs.get("timeout")])
            if Path(str(command[3])).name == "fail.mp4":
                return subprocess.CompletedProcess(command, 1, "", "fake ffmpeg: no such encoder " * 20)
            shutil.copyfile(short, command[-1])
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    failing = media.video(tmp_path / "fail.mp4", seconds=2, size="64x36", fps=8)
    body = {"model_type": "fake_t2v", "pad_right": 8, "lock_source_pixels": True}
    cases = {
        "a range": {**body, "video_path": str(clip_path), "start_time": 0.5, "end_time": "2.0"},
        "a range too short": {**body, "video_path": str(clip_path), "start_time": 1.0, "end_time": 1.04},
        "a negative start": {**body, "video_path": str(clip_path), "start_time": -1, "end_time": 2},
        "a text range": {**body, "video_path": str(clip_path), "start_time": "soon", "end_time": 2},
        "only a start": {**body, "video_path": str(clip_path), "start_time": 0.5},
        "ffmpeg fails": {**body, "video_path": str(failing), "start_time": 0.0, "end_time": 1.0},
    }
    answers = {case: _hand_off(rig, "/api/v1/outpaint", request, started) for case, request in cases.items()}
    trimmed = sorted(path.name for path in (rig.server.root / "uploads").glob("outpaint_trim_*.mp4"))
    recorded = _scrub({"answers": answers, "commands": commands, "trimmed files": len(trimmed)},
                      (str(tmp_path), "<TMP>"))
    # The trim file takes 8 random hex digits.
    recorded = json.loads(re.sub(r"outpaint_trim_[0-9a-f]{8}\.mp4", "outpaint_trim_<HEX8>.mp4", json.dumps(recorded)))
    rig.check(golden, "outpaint trims a range first", recorded)


def test_blend_hands_the_worker_each_mode(rig, golden, tmp_path, monkeypatch) -> None:
    _block_network(monkeypatch)
    temp = _TempDirs(monkeypatch)
    started = _capture_workers(rig)
    still_a = media.image(tmp_path / "a.png", size=(64, 64))
    still_b = media.image(tmp_path / "b.png", size=(96, 64))
    video_a = media.video(tmp_path / "a.mp4", seconds=2, size="64x48", fps=8)
    video_b = media.video(tmp_path / "b.mp4", seconds=2, size="80x48", fps=8)
    tiny = media.image(tmp_path / "tiny.png", size=(16, 40))
    (rig.server.root / "uploads").mkdir(exist_ok=True)
    media.image(rig.server.root / "uploads" / "uploaded-a.png", size=(64, 32))
    media.image(rig.server.outputs / "workspace-b.png", size=(64, 32))
    cases = {
        "two stills, every default": {"clip_a_path": str(still_a), "clip_b_path": str(still_b),
                                      "model_type": "fake_t2v"},
        "two videos, anchors and inherited settings": {
            "clip_a_path": str(video_a), "clip_b_path": str(video_b), "model_type": "fake_t2v",
            "prompt": "a door opens", "seed": 5, "blend_mode": "insert", "overlap_sec": 1.0,
            "motion_prefix_sec": 0.5, "motion_suffix_sec": 0.25, "anchor_frames": 3, "injection_strength": 1.5,
            "activated_loras": ["x.safetensors"], "loras_multipliers": "1;0.5 0.8",
            "base_params": {"video_length": 99, "image_mode": 1, "repeat_generation": 4, "reference_pipeline": True,
                            "prompt": "dropped", "seed": 1, "negative_prompt": "inherited negative",
                            "guidance_scale": 2.5, "num_inference_steps": 20, "input_video_strength": 0.05,
                            "progressive_pipeline": True, "stage2_steps": 3, "video_source": "dropped.mp4"},
        },
        "the body beats inherited settings": {
            "clip_a_path": str(video_a), "clip_b_path": str(still_b), "model_type": "fake_t2v",
            "negative_prompt": "", "guidance_scale": "4", "num_inference_steps": "7", "input_video_strength": 1.7,
            "motion_prefix_sec": 0, "motion_suffix_sec": 9, "anchor_frames": 99, "injection_strength": -2,
            "base_params": {"negative_prompt": "inherited", "guidance_scale": 2.5, "num_inference_steps": 20},
        },
        "a long overlap, still anchors only": {
            "clip_a_path": str(still_a), "clip_b_path": str(still_b), "model_type": "fake_t2v",
            "overlap_sec": 4.4, "motion_prefix_sec": 0, "motion_suffix_sec": 0, "base_params": None,
        },
        "a short overlap": {
            "clip_a_path": str(video_a), "clip_b_path": str(video_b), "model_type": "fake_t2v",
            "overlap_sec": 0.1, "motion_prefix_sec": 0.05, "motion_suffix_sec": 0,
        },
        "clip A too small": {"clip_a_path": str(tiny), "clip_b_path": str(still_b), "model_type": "fake_t2v"},
        "names found in uploads and the workspace": {
            "clip_a_path": "somewhere/uploaded-a.png", "clip_b_path": "workspace-b.png", "model_type": "fake_t2v",
            "motion_prefix_sec": 0, "motion_suffix_sec": 0, "workspace": "",
        },
    }
    answers = {case: _hand_off(rig, "/api/v1/blend", body, started, temp=temp) for case, body in cases.items()}
    rig.patch("execution_mode", SimpleNamespace(policy=lambda: SimpleNamespace(simulated=True, mode="simulate")))
    answers["simulated"] = _hand_off(rig, "/api/v1/blend", {
        "clip_a_path": str(still_a), "clip_b_path": str(still_b), "model_type": "fake_t2v", "motion_prefix_sec": 0,
        "motion_suffix_sec": 0}, started, temp=temp)
    with pytest.raises(ValueError) as refused:
        rig.server.client.post("/api/v1/blend", json={"clip_a_path": str(still_a), "clip_b_path": str(still_b),
                                                      "model_type": "fake_t2v", "overlap_sec": "long"})
    answers["text overlap"] = str(refused.value)
    with pytest.raises(ValueError) as refused:
        rig.server.client.post("/api/v1/blend", json={"clip_a_path": str(still_a), "clip_b_path": str(still_b),
                                                      "model_type": "fake_t2v", "base_params": "not a dict"})
    answers["base params that are not a dict"] = str(refused.value)
    answers["temp folders made, and still there"] = temp.left()
    rig.check(golden, "blend hands the worker each mode", _scrub(answers, (str(tmp_path), "<TMP>"), *temp.pairs()))


# -- jobs the fake engine runs ------------------------------------------------------------------------------------


def _blend_tools(monkeypatch, *, audio_in: tuple[str, ...], concat_ok: bool) -> list:
    """ffprobe and ffmpeg of the blend assembly, recorded; the filter script is read when ffmpeg is called."""
    commands: list = []
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        command = [str(part) for part in command]
        if command[0] == "ffprobe" and "stream=codec_type" in command and "-select_streams" in command:
            target = command[-1]
            commands.append(["ffprobe", Path(target).name])
            has_audio = any(Path(target).name.startswith(prefix) for prefix in audio_in)
            return subprocess.CompletedProcess(command, 0, "audio\n" if has_audio else "", "")
        if command[0] == "ffmpeg" and "-/filter_complex" in command:
            script = Path(command[command.index("-/filter_complex") + 1]).read_text(encoding="utf-8")
            commands.append(["ffmpeg", command, script, kwargs.get("timeout")])
            if not concat_ok:
                return subprocess.CompletedProcess(command, 1, "", "fake ffmpeg: concat refused")
            shutil.copyfile(command[command.index("-i", command.index("-i") + 1) + 1], command[-1])
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return commands


def _blend_body(clip_a: Path, clip_b: Path, **extra) -> dict:
    return {"clip_a_path": str(clip_a), "clip_b_path": str(clip_b), "model_type": "fake_t2v",
            "prompt": "the road turns into a river", "seed": 9, "overlap_sec": 1.0, "motion_prefix_sec": 0,
            "motion_suffix_sec": 0, **extra}


@pytest.mark.parametrize("case", ["assembled", "ffmpeg fails"])
def test_blend_assembles_a_before_the_transition_and_b_after(rig, golden, tmp_path, monkeypatch, case) -> None:
    """Two three-second clips: A's head, the generated transition and B's tail go to one ffmpeg concat."""
    _block_network(monkeypatch)
    temp = _TempDirs(monkeypatch)
    clip_a = media.video(tmp_path / "audio-a.mp4", seconds=3, size="64x36", fps=8)
    clip_b = media.video(tmp_path / "silent-b.mp4", seconds=3, size="64x36", fps=8)
    tools = _blend_tools(monkeypatch, audio_in=("audio-",), concat_ok=case == "assembled")
    status, answer = _submit(rig, "/api/v1/blend", _blend_body(clip_a, clip_b))
    assert status == 200, answer
    _join_route_workers(rig)
    job_id = answer["job_id"]
    rig.check(golden, f"blend run: {case}", _scrub({
        **rig.observe(job_id), "tools": tools, "temp folders left": temp.left(),
    }, (str(tmp_path), "<TMP>"), *temp.pairs()))


def test_blend_cancelled_while_the_transition_renders(rig, golden, tmp_path, monkeypatch) -> None:
    _block_network(monkeypatch)
    temp = _TempDirs(monkeypatch)
    clip_a = media.video(tmp_path / "a.mp4", seconds=3, size="64x36", fps=8)
    clip_b = media.video(tmp_path / "b.mp4", seconds=3, size="64x36", fps=8)
    tools = _blend_tools(monkeypatch, audio_in=(), concat_ok=True)
    release = rig.event()

    def script(call) -> None:
        call.send("progress", [(1, 2), "Sampling | 1/2"])
        if not call.hold(release):
            call.save()

    rig.engine.entered.clear()
    rig.engine.scripts.append(script)
    status, answer = _submit(rig, "/api/v1/blend", _blend_body(clip_a, clip_b))
    assert status == 200, answer
    job_id = answer["job_id"]
    assert rig.engine.entered.wait(WAIT)
    rig.wait_for(job_id, message="Sampling | 1/2")
    cancelled = rig.cancel(job_id)
    release.set()
    _join_route_workers(rig)
    rig.check(golden, "blend run: cancelled", _scrub({
        "cancel": cancelled, **rig.observe(job_id), "tools": tools, "temp folders left": temp.left(),
    }, (str(tmp_path), "<TMP>"), *temp.pairs()))


def _shot_outpaint(rig, tmp_path, monkeypatch, *, shot_frames: int | None, concat=True, timeline_frames=24):
    """An official outpaint of a two-shot clip whose shot guides are written by a recorder; the engine renders each
    shot as a clip of ``shot_frames`` frames and the fake WanGP joins them into the 24-frame timeline."""
    _block_network(monkeypatch)
    _official_ltx(rig)
    temp = _TempDirs(monkeypatch)
    source = _two_shot_clip(tmp_path / "two-shots.mp4")
    guides: list = []
    guide_clip = _video(tmp_path / "guide.mp4", frames=12, fps=8)

    def guide_writer(source_video, output_path, *, start_frame, end_frame, pad_frames, fps, abort_callback=None):
        guides.append([Path(source_video).name, Path(output_path).name, start_frame, end_frame, pad_frames, fps,
                       abort_callback is not None])
        shutil.copyfile(guide_clip, output_path)
        return output_path

    rig.patch("_write_outpaint_shot_guide", guide_writer)
    if shot_frames is not None:
        shot_clip = _video(tmp_path / "shot.mp4", frames=shot_frames, fps=8)
        real_write = rig.engine.write_media

        def write_media(path, kind):
            if kind == "video":
                shutil.copyfile(shot_clip, path)
            else:
                real_write(path, kind)

        rig.engine.write_media = write_media
    joined: list = []
    timeline = _video(tmp_path / "timeline.mp4", frames=timeline_frames, fps=8)

    def concatenate(paths, output, audio, **kwargs):
        joined.append([[Path(path).name for path in paths], Path(output).name, audio and Path(audio).name,
                       {key: (value if not callable(value) else "callable") for key, value in kwargs.items()}])
        if concat:
            shutil.copyfile(timeline, output)
        return concat

    rig.set_wgp("concatenate_multi_clip_videos", concatenate)
    body = {"video_path": str(source), "model_type": "fake_ltx", "prompt": "a forest", "seed": 7,
            "pad_right": 64, "preserve_source_audio": True}
    return temp, source, guides, joined, body


def _shot_observation(rig, job_id, temp, tmp_path, guides, joined) -> dict:
    observed = rig.observe(job_id)
    job = rig.launch._jobs[job_id]
    observed.update({
        "params": json.loads(json.dumps(job.get("params") or {}, default=str, sort_keys=True)),
        "out_dir": job.get("out_dir"),
        "guides": guides,
        "joined": joined,
        "temp folders left": temp.left(),
    })
    return _scrub(observed, (str(tmp_path), "<TMP>"), *temp.pairs())


@pytest.mark.parametrize("case", ["joined", "joined with the source audio", "the audio probe fails",
                                  "a shot of the wrong length", "the join fails", "the join changes the length"])
def test_official_outpaint_generates_each_camera_shot_then_joins_them(rig, golden, tmp_path, monkeypatch,
                                                                      case) -> None:
    temp, _source, guides, joined, body = _shot_outpaint(
        rig, tmp_path, monkeypatch, shot_frames=None if case == "a shot of the wrong length" else 12,
        concat=case != "the join fails", timeline_frames=20 if case == "the join changes the length" else 24)
    if case == "joined with the source audio":
        rig.patch("_recast_video_has_audio", lambda path: Path(path).name == "two-shots.mp4")
    elif case == "the audio probe fails":
        def probe(path):
            raise OSError("ffprobe is busy")

        rig.patch("_recast_video_has_audio", probe)
    status, answer = _submit(rig, "/api/v1/outpaint", body)
    assert status == 200, answer
    _join_route_workers(rig)
    rig.check(golden, f"official outpaint shots: {case}",
              _shot_observation(rig, answer["job_id"], temp, tmp_path, guides, joined))


@pytest.mark.parametrize("case", ["detection fails", "cancelled while preparing", "cancelled in the second shot"])
def test_official_outpaint_shot_preparation_failure_and_cancel(rig, golden, tmp_path, monkeypatch, case) -> None:
    temp, _source, guides, joined, body = _shot_outpaint(rig, tmp_path, monkeypatch, shot_frames=12)
    submitted: dict = {}
    if case == "detection fails":
        def detect(thumbnails, **kwargs):
            raise ValueError("no cuts today")

        rig.patch("_detect_recast_shot_ranges", detect)
    elif case == "cancelled while preparing":
        def detect(thumbnails, **kwargs):
            rig.wait_until(lambda: "job_id" in submitted, "the route answered")
            submitted["cancel"] = rig.cancel(submitted["job_id"])
            return [(0, 12), (12, 24)]

        rig.patch("_detect_recast_shot_ranges", detect)
    else:
        release = rig.event()

        def first_shot(call) -> None:
            call.save()

        def second_shot(call) -> None:
            call.send("progress", [(1, 2), "Sampling | 1/2"])
            if not call.hold(release):
                call.save()

        rig.engine.entered.clear()
        rig.engine.scripts.extend([first_shot, second_shot])
    status, answer = _submit(rig, "/api/v1/outpaint", body)
    assert status == 200, answer
    submitted["job_id"] = answer["job_id"]
    if case == "cancelled in the second shot":
        assert rig.engine.entered.wait(WAIT)
        rig.wait_for(answer["job_id"], message="Shot 2/2: Sampling | 1/2")
        submitted["cancel"] = rig.cancel(answer["job_id"])
        release.set()
    _join_route_workers(rig)
    rig.check(golden, f"official outpaint shots: {case}", {
        "cancel": submitted.get("cancel"),
        **_shot_observation(rig, answer["job_id"], temp, tmp_path, guides, joined)})
