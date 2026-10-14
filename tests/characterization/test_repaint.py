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



# -- Mapped Repaint end to end on the fake engine (C6 review) --------------------------------------------------------
# Recorded on development before the move. Magic Mask is replaced by a painter that finds coloured rectangles by
# keyword, so the route, region tracking, the shot manifest, the per-shot worker and the assembly all run on the CPU
# with small frames: WanGP is the C0 fake engine and the clip joiner is a fake that copies the first shot. What each
# case records is what a move must keep: the route's answer, every Magic Mask call, the mask video, the shot tasks the
# engine ran (prompts, lengths, references, guides), the joined call, the abort states, the job and its sidecar.
_H, _W, _T = 64, 96, 48
# keyword -> (top, bottom, left, right)
_RECTANGLES = {
    "subject one": (4, 20, 4, 24),
    "subject two": (4, 20, 36, 56),
    "subject three": (4, 20, 68, 88),
    "subject four": (36, 56, 4, 24),
    "subject five": (36, 56, 36, 56),
}
# A region that overlaps subjects one and two, for the cases where two regions cover the same pixels.
_OVERLAPPING = {"subject wide": (8, 28, 12, 44)}
_ALL_RECTANGLES = {**_RECTANGLES, **_OVERLAPPING}


class _Painter:
    """Magic Mask for one scene: which subject is visible in which source frame, and in the edited first frame."""

    def __init__(self, rig, *, present: dict, edited: set, cuts: tuple = (), cancel_on_call: int | None = None,
                 progress: tuple = (0.5, 1.0)):
        self.rig, self.present, self.edited, self.cuts = rig, present, edited, cuts
        self.cancel_on_call, self.progress = cancel_on_call, progress
        self.calls: list = []
        self.saved: list = []
        self.abort_states: list = []

    def frames(self):
        import numpy

        frames = numpy.zeros((_T, _H, _W, 3), dtype=numpy.uint8)
        bounds = [0, *self.cuts, _T]
        shades = [(40, 60, 90), (220, 200, 120), (90, 200, 60), (200, 60, 200)]
        for shot, (start, end) in enumerate(zip(bounds, bounds[1:])):
            frames[start:end] = shades[shot % len(shades)]
            frames[start:end, :, (shot * 7) % _W:(shot * 7) % _W + 8] = 255 - numpy.array(shades[shot % len(shades)])
        for keyword, indexes in self.present.items():
            top, bottom, left, right = _ALL_RECTANGLES[keyword]
            for index in indexes:
                frames[index, top:bottom, left:right] = (250, 250, 250)
        return frames

    def prepare(self, source_video):
        return source_video, self.frames(), 24.0

    def masks(self, video, keyword, *, color_palette=None, progress_callback=None, tracking_segments=None, **kwargs):
        import numpy

        launch = self.rig.launch
        running = [job_id for job_id, job in launch._jobs.items()
                   if job.get("status") == "running" and job_id in launch._active_gen_states]
        self.abort_states.append(sorted(running))
        self.calls.append({
            "keyword": keyword, "frames": int(video.shape[0]), "color": list(color_palette[0]),
            "tracking_segments": [list(segment) for segment in tracking_segments] if tracking_segments else None,
            "options": sorted(kwargs),
        })
        if self.cancel_on_call is not None and len(self.calls) == self.cancel_on_call:
            job_id = running[0]
            launch.request_cancel(launch._jobs[job_id], job_id=job_id, active_states=launch._active_gen_states)
        painted = numpy.zeros_like(video)
        subject = keyword.replace("edited ", "")
        if subject in _ALL_RECTANGLES:
            top, bottom, left, right = _ALL_RECTANGLES[subject]
            indexes = ([0] if subject in self.edited else []) if video.shape[0] == 1 else self.present.get(subject, [])
            for index in indexes:
                painted[index, top:bottom, left:right] = color_palette[0]
        if progress_callback is not None:
            for fraction in self.progress:
                progress_callback(int(int(video.shape[0]) * fraction), int(video.shape[0]))
        return painted

    def save(self, source_path, mask, fps, keywords, output_dir=None, abort_callback=None, background_color=None):
        import os

        import numpy

        colors = sorted({tuple(int(value) for value in pixel) for pixel in numpy.unique(mask.reshape(-1, 3), axis=0)})
        self.saved.append({"source": os.path.basename(source_path), "shape": list(mask.shape), "fps": fps,
                           "keywords": list(keywords), "background": list(background_color), "colors": colors})
        path = os.path.join(output_dir, "repaint_semantic_mask_stub.mp4")
        os.makedirs(output_dir, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(b"mask")
        return path


def _mapped_repaint(rig, monkeypatch, painter: _Painter, mappings: list, *, frame_count_offset: int = 0,
                    engine_script=None) -> dict:
    """POST one mapped Repaint, let the request thread and the shot worker finish, and return what they did."""
    import os
    import shutil

    from PIL import Image

    from shared import magic_mask

    _probe_as(monkeypatch)
    _install_scail(rig)
    monkeypatch.setattr(magic_mask, "prepare_video_mask_input", painter.prepare)
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", painter.masks)
    monkeypatch.setattr(magic_mask, "save_mask_video", painter.save)
    joined: list = []

    def concatenate(paths, output, audio, **options):
        joined.append({"clips": [os.path.basename(path) for path in paths], "output": os.path.basename(output),
                       "audio": os.path.basename(audio) if audio else None,
                       "options": {key: value for key, value in sorted(options.items()) if key != "abort_callback"}})
        shutil.copyfile(paths[0], output)
        return True

    def frame_count(_path):
        bundles = [job["params"]["_repaint_shot_bundle"] for job in rig.launch._jobs.values()
                   if isinstance(job.get("params"), dict) and job["params"].get("_repaint_shot_bundle")]
        return int(bundles[-1]["frame_count"]) + frame_count_offset

    rig.set_wgp("concatenate_multi_clip_videos", concatenate)
    rig.patch("_recast_video_frame_count", frame_count)
    rig.engine.script = engine_script or (lambda call: call.save())
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    edited = folder / "edited.png"
    canvas = Image.new("RGB", (_W, _H), (40, 60, 90))
    for subject in painter.edited:
        top, bottom, left, right = _RECTANGLES[subject]
        canvas.paste((240, 20, 20), (left, top, right, bottom))
    canvas.save(edited)
    since = len(rig.engine.calls)
    status, answer = _submit(rig, "/api/v1/repaint", {
        "video_path": video, "target_frame_path": "edited.png", "seed": 7, "prompt": "the edited regions",
        "region_mappings": mappings,
    })
    _join_repaint_workers()
    observed = {"status": status, "answer": answer, "mask calls": painter.calls, "saved mask": painter.saved,
                "abort states seen by Magic Mask": painter.abort_states, "joined": joined}
    if status == 200 and isinstance(answer, dict) and "job_id" in answer:
        observed["job"] = _job(rig, answer["job_id"], since)
    return observed


def _check_mapped(rig, golden, case: str, observed: dict) -> None:
    import tempfile

    text = __import__("json").dumps(observed, default=str)
    text = text.replace(tempfile.gettempdir(), "<TMP>")
    text = re.sub(r"maestro-repaint-shots-[A-Za-z0-9_]+", "maestro-repaint-shots-<RANDOM>", text)
    text = re.sub(r"repaint_reference_mask_[0-9a-f]{8}", "repaint_reference_mask_<HEX>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}-\d{2}h\d{2}m\d{2}s", "<STAMP>", text)
    rig.check(golden, case, __import__("json").loads(text))


def _mapping(*subjects: str) -> list:
    return [{"source": subject, "target": f"edited {subject}"} for subject in subjects]


def test_mapped_repaint_with_one_region_generates_both_camera_shots(rig, golden, monkeypatch) -> None:
    painter = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one"}, cuts=(24,))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one"))
    _check_mapped(rig, golden, "mapped repaint, one region, two camera shots", observed)


def test_mapped_repaint_with_two_regions_fails_when_the_joined_timeline_is_short(rig, golden, monkeypatch) -> None:
    painter = _Painter(rig, present={"subject one": range(_T), "subject two": range(_T)},
                       edited={"subject one", "subject two"})
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one", "subject two"),
                               frame_count_offset=-1)
    _check_mapped(rig, golden, "mapped repaint, two regions, joined timeline one frame short", observed)


def test_mapped_repaint_with_three_regions_passes_a_shot_without_regions_through(rig, golden, monkeypatch) -> None:
    painter = _Painter(rig, present={"subject one": range(0, 16), "subject two": range(0, 32),
                                     "subject three": range(16, 32)},
                       edited={"subject one", "subject two", "subject three"}, cuts=(16, 32))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one", "subject two", "subject three"))
    _check_mapped(rig, golden, "mapped repaint, three regions, a passthrough shot", observed)


def test_mapped_repaint_with_four_regions_in_every_frame(rig, golden, monkeypatch) -> None:
    subjects = ("subject one", "subject two", "subject three", "subject four")
    painter = _Painter(rig, present={subject: range(_T) for subject in subjects}, edited=set(subjects), cuts=(24,))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping(*subjects))
    _check_mapped(rig, golden, "mapped repaint, four regions in every frame", observed)


def test_mapped_repaint_with_five_regions_uses_a_region_sheet_when_they_never_meet(rig, golden, monkeypatch) -> None:
    subjects = tuple(_RECTANGLES)
    present = {subject: range(0, 24) for subject in subjects}
    present["subject one"] = [*range(0, 24), *range(24, 36)]
    present["subject two"] = [*range(0, 24), *range(36, 48)]
    painter = _Painter(rig, present=present, edited=set(subjects), cuts=(24,))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping(*subjects))
    _check_mapped(rig, golden, "mapped repaint, five regions, a shot whose regions never meet", observed)


def test_mapped_repaint_fails_when_a_region_is_missing(rig, golden, monkeypatch) -> None:
    missing_source = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one", "subject two"})
    observed = {"from the video": _mapped_repaint(rig, monkeypatch, missing_source,
                                                  _mapping("subject one", "subject two"))}
    missing_edit = _Painter(rig, present={"subject one": range(_T), "subject two": range(_T)},
                            edited={"subject one"})
    observed["from the edited frame"] = _mapped_repaint(rig, monkeypatch, missing_edit,
                                                        _mapping("subject one", "subject two"))
    _check_mapped(rig, golden, "mapped repaint, a region missing", observed)


def test_mapped_repaint_cancelled_while_mapping_regions(rig, golden, monkeypatch) -> None:
    painter = _Painter(rig, present={"subject one": range(_T), "subject two": range(_T)},
                       edited={"subject one", "subject two"}, cancel_on_call=2)
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one", "subject two"))
    _check_mapped(rig, golden, "mapped repaint, cancelled while mapping", observed)


def test_mapped_repaint_cancelled_during_the_first_shot(rig, golden, monkeypatch) -> None:
    def script(call) -> None:
        call.save()
        if call.index == 0:
            job_id = rig.running_job_id()
            rig.launch.request_cancel(rig.launch._jobs[job_id], job_id=job_id,
                                      active_states=rig.launch._active_gen_states)

    painter = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one"}, cuts=(24,))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one"), engine_script=script)
    _check_mapped(rig, golden, "mapped repaint, cancelled during the first shot", observed)


def test_mapped_repaint_removes_its_shot_folder_when_the_manifest_fails(rig, golden, monkeypatch) -> None:
    import glob
    import os
    import tempfile

    def refuse(path, *_args, **_kwargs):
        raise OSError(f"cannot write {os.path.basename(path)}")

    def shot_folders() -> set:
        return set(glob.glob(os.path.join(tempfile.gettempdir(), "maestro-repaint-shots-*")))

    rig.patch("_write_recast_shot_video", refuse)
    painter = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one"}, cuts=(24,))
    before = shot_folders()
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one"))
    observed["shot folders left"] = len(shot_folders() - before)
    _check_mapped(rig, golden, "mapped repaint, the shot manifest fails", observed)

def test_mapped_repaint_reports_region_mapping_progress_in_five_percent_steps(rig, golden, monkeypatch) -> None:
    painter = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one"},
                       progress=tuple(step / 40 for step in range(41)))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one"))
    _check_mapped(rig, golden, "mapped repaint, mapping progress in fine steps", observed)


def test_repaint_preview_gives_overlapping_pixels_to_the_first_region(rig, golden, monkeypatch) -> None:
    from shared import magic_mask

    _probe_as(monkeypatch)
    painter = _Painter(rig, present={"subject one": range(_T), "subject wide": range(_T)},
                       edited={"subject one", "subject wide"})
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", painter.masks)
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    matching = _frame(folder, "frame.png", (96, 64))
    response = rig.server.client.post("/api/v1/repaint/preview", json={
        "video_path": video, "target_frame_path": matching, "region_mappings": _mapping("subject one", "subject wide")})
    answer = response.json()
    if isinstance(answer, dict) and "source_preview" in answer:
        answer = _preview_pixels(answer)
    golden.check("preview gives overlapping pixels to the first region", 200, rig.server.normalise(
        {"status": response.status_code, "body": answer, "mask calls": painter.calls}))

def test_repaint_preview_maps_five_regions(rig, golden, monkeypatch) -> None:
    from shared import magic_mask

    _probe_as(monkeypatch)
    subjects = tuple(_RECTANGLES)
    painter = _Painter(rig, present={subject: range(_T) for subject in subjects}, edited=set(subjects))
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", painter.masks)
    folder = rig.server.root
    video = _present(folder, "source.mp4")
    matching = _frame(folder, "frame.png", (96, 64))
    response = rig.server.client.post("/api/v1/repaint/preview", json={
        "video_path": video, "target_frame_path": matching, "time": 1.0, "region_mappings": _mapping(*subjects)})
    answer = response.json()
    if isinstance(answer, dict) and "source_preview" in answer:
        answer = _preview_pixels(answer)
    golden.check("preview maps five regions", 200, rig.server.normalise(
        {"status": response.status_code, "body": answer, "mask calls": painter.calls}))


def test_repaint_paths_that_climb_out_of_the_workspace(rig, golden, monkeypatch) -> None:
    """Media names are looked up by their base name in the workspace, uploads and outputs; an absolute path that
    exists is taken as it is."""
    from shared import magic_mask

    _probe_as(monkeypatch)
    _install_scail(rig)
    painter = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one"})
    monkeypatch.setattr(magic_mask, "generate_keyword_masks", painter.masks)
    folder = rig.server.root
    (folder / "uploads").mkdir(exist_ok=True)
    _present(folder / "uploads", "source.mp4")
    _frame(folder / "uploads", "frame.png", (96, 64))
    outside = folder / "outside"
    outside.mkdir()
    _frame(outside, "frame.png", (96, 64))
    answers = {}
    for case, body in {
        "climbing names resolve to uploads": {"video_path": "../../source.mp4", "target_frame_path": "../frame.png"},
        "a missing climbing name": {"video_path": "../../nothing.mp4", "target_frame_path": "../frame.png"},
        "an absolute frame outside the workspace": {"video_path": "../../source.mp4",
                                                    "target_frame_path": str(outside / "frame.png")},
    }.items():
        for route in _ROUTES:
            payload = {**body, "seed": 3}
            if route.endswith("/preview"):
                payload["region_mappings"] = _mapping("subject one")
            status, answer = _submit(rig, route, payload)
            _join_repaint_workers()
            if isinstance(answer, dict) and "source_preview" in answer:
                answer = _preview_pixels(answer)
            answers[f"{route} {case}"] = {"status": status, "answer": answer}
            if status == 200 and isinstance(answer, dict) and "job_id" in answer:
                params = rig.launch._jobs[answer["job_id"]]["params"]
                answers[f"{route} {case}"]["inputs"] = {key: params.get(key) for key in (
                    "video_guide", "image_start", "edit_video_path", "edit_repaint_target_frame")}
    rig.check(golden, "paths that climb out of the workspace", answers)


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


def test_standard_library_names_the_rig_patches_reach_every_repaint_module(rig, monkeypatch) -> None:
    """The Repaint modules import ``uuid`` and ``time`` themselves. A rig patch of those launch names still reaches the
    route (the job id), the planning module (the reference mask's name) and the shot worker (the joined file's name),
    as it did when the code lived in launch."""
    import itertools
    import time as real_time
    import uuid as real_uuid

    counter = itertools.count(1)
    fake_uuid = SimpleNamespace(uuid4=lambda: SimpleNamespace(hex=f"{next(counter):032x}"), UUID=real_uuid.UUID)
    fake_time = SimpleNamespace(**{name: getattr(real_time, name) for name in dir(real_time) if not name.startswith("_")})
    fake_time.strftime = lambda *_args: "stamped"
    rig.patch("uuid", fake_uuid)
    rig.patch("time", fake_time)
    painter = _Painter(rig, present={"subject one": range(_T)}, edited={"subject one"}, cuts=(24,))
    observed = _mapped_repaint(rig, monkeypatch, painter, _mapping("subject one"))
    job = rig.launch._jobs[observed["answer"]["job_id"]]
    assert re.fullmatch(r"0{5}[0-9a-f]{3}", observed["answer"]["job_id"]), observed["answer"]["job_id"]
    assert re.search(r"repaint_reference_mask_0{5}[0-9a-f]{3}\.png$", job["params"]["edit_repaint_reference_mask"])
    assert observed["joined"][0]["output"] == "stamped_seed7_repaint_shot_aware.mp4", observed["joined"]
    assert job["status"] == "completed", job.get("error")
