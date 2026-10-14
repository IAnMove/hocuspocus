"""``_run_generation``: the worker that runs every generation job, driven end to end.

``POST /api/v1/generate`` creates the job and starts the real worker thread. The
fake WanGP's ``generate_video`` (``tests/support/fake_wgp.py``, ``FakeEngine``)
stands in for the GPU, so the worker's own code runs unchanged: queue slot,
lifecycle, manifest building, progress parsing, output collection, sidecars,
canonical task and cleanup. Each test records one observation of the finished
job (every lifecycle write in order, the status route, the files and sidecars,
the canonical task, what the engine received, what the worker left behind) in
``goldens/test_run_generation.json``.

A few branches are not reachable over HTTP (the caller passes ``finalize=False``,
the model is the legacy H3 route, the slot is taken a moment before a cancel).
Those tests build the job with the server's own factory and call
``_run_generation`` directly, with the collaborators that need a GPU stubbed.
Every stub goes through :meth:`Rig.patch`, so a PR that moves the worker only
repoints ``worker_module``.

The goldens pin today's behaviour, including its oddities. Tests whose names
start with ``test_oddity_`` pin behaviour that looks unintended; a refactor must
keep it, and a fix is its own PR that re-records the golden.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from tests.characterization import media
from tests.support.fake_wgp import FakeEngine, catalog_attributes, generation_attributes

CREATED = 1_700_000_000.0
BODY = {"model_type": "fake_t2v", "prompt": "a calm lake", "generation_mode": "video", "seed": 42,
        "video_length": 17, "resolution": "64x64"}
# Measured durations, the commit and version that sidecars carry, and an encoder-dependent size:
# the golden keeps their shape, not their value.
MASKED = ("processing_time_sec", "total_seconds", "seconds", "generation_time", "inference_ms", "queue_ms",
          "total_ms", "app", "size_bytes", "performance")
WORKER = "_run_generation_with_preparation"
STATUS_KEYS = ("status", "progress", "step", "total_steps", "phase", "message", "error", "output_files",
               "oom_info", "queue_position")
TASK_KEYS = ("status", "phase", "message", "progress", "result_refs", "error", "cancelable", "acquired_resources")
# What ``_run_generation`` itself puts in a sidecar; the asset-manifest wrapper around it is pinned once.
SIDECAR_KEYS = ("params", "upload_filenames", "generation_mode", "job_id", "task_id", "root_task_id", "generation_time",
                "created_at", "director_pipeline_id", "director_clip_index", "model_prompts", "output_filename")
RECORD_KEYS = ("clip_output_files", "join_output_file", "_internal_output_files", "_internal_clip_output_files",
               "_internal_join_output_file", "acquired_resources", "cancel_requested", "recovered", "vram_adjustment")

MULTI_CLIP = {**BODY, "multi_prompts_gen_type": 3, "prompt": "first shot\nsecond shot\nthird shot",
              "per_clip_seeds": [11, 12, 13], "per_clip_frames": [17, 25, 17],
              "per_clip_negative_prompts": ["blur", "", "noise"]}


def _install_fake_decord(monkeypatch) -> list:
    """The continuation step reads the last frame of a clip with decord, which CI may not have."""
    import numpy

    reads: list = []

    class VideoReader:
        def __init__(self, path: str) -> None:
            reads.append(["open", Path(path).name])

        def __len__(self) -> int:
            return 24

        def __getitem__(self, index: int):
            reads.append(["frame", index])
            return SimpleNamespace(asnumpy=lambda: numpy.zeros((8, 8, 3), dtype="uint8"))

    monkeypatch.setitem(sys.modules, "decord", SimpleNamespace(VideoReader=VideoReader))
    return reads


def worker_module():
    """The module whose globals ``_run_generation`` reads. A move PR repoints this one function."""
    return sys.modules["_launch_runtime"]


@dataclass
class Rig:
    """One test's server, scripted engine and the lifecycle events of its jobs."""

    server: Any
    engine: FakeEngine
    monkeypatch: pytest.MonkeyPatch
    events: list[dict] = field(default_factory=list)
    job_ids: list[str] = field(default_factory=list)
    accepted: dict[str, dict] = field(default_factory=dict)
    releases: list[threading.Event] = field(default_factory=list)
    returned: dict[str, bool] = field(default_factory=dict)

    @property
    def launch(self):
        return worker_module()

    def patch(self, name: str, value: Any) -> None:
        self.monkeypatch.setattr(worker_module(), name, value)

    def event(self) -> threading.Event:
        """An event the engine script waits on; the fixture sets it at teardown so a failed test never hangs."""
        released = threading.Event()
        self.releases.append(released)
        return released

    # -- driving jobs ------------------------------------------------------------------------------
    def post(self, body: dict, *, expect: int = 200) -> dict:
        response = self.server.client.post("/api/v1/generate", json=body)
        assert response.status_code == expect, response.text
        answer = response.json()
        if "job_id" in answer:
            self.job_ids.append(answer["job_id"])
            self.accepted[answer["job_id"]] = answer
        return answer

    @staticmethod
    def workers() -> list[threading.Thread]:
        """The worker threads the route started (Python 3.10 names a thread ``Thread-N (target)``)."""
        return [thread for thread in threading.enumerate() if thread.name.endswith(f"({WORKER})")]

    def join(self, timeout: float = 30.0) -> None:
        """Wait for every worker thread, so the whole ``finally`` block has run."""
        for thread in self.workers():
            thread.join(timeout)
            assert not thread.is_alive(), "the generation worker did not finish"

    def wait_until(self, condition: Callable[[], bool], what: str) -> None:
        deadline = time.monotonic() + 10
        while not condition():
            assert time.monotonic() < deadline, f"never saw: {what}"
            time.sleep(0.01)

    def run(self, body: dict) -> str:
        job_id = self.post(body)["job_id"]
        self.join()
        return job_id

    def direct_job(self, params: dict, *, job_id: str = "golden-direct", workspace: str = "default",
                   recovered: bool = False) -> str:
        """A job the server's own factory builds and registers; the test thread then runs the worker itself."""
        launch = self.launch
        job = launch._new_generation_job(dict(params), workspace, job_id=job_id, created_at=CREATED,
                                         recovered=recovered)
        launch._jobs[job_id] = job
        launch._persist_generation_job(job)
        return job_id

    def wait_for(self, job_id: str, **expected: Any) -> dict:
        """Poll the live job until it shows ``expected``; the engine is held, so the state is stable."""
        deadline = time.monotonic() + 10
        while True:
            record = self.launch.snapshot_job(self.launch._jobs[job_id])
            if all(record.get(key) == value for key, value in expected.items()):
                return record
            assert time.monotonic() < deadline, f"job {job_id} never showed {expected}; last: {record.get('status')} {record.get('message')}"
            time.sleep(0.01)

    def cancel(self, job_id: str) -> dict:
        return self.server.client.post(f"/api/v1/cancel/{job_id}").json()

    def get(self, path: str, **params: Any) -> Any:
        return self.server.client.get(path, params=params or None).json()

    def running_job_id(self) -> str:
        """The job whose worker is running now, from its lifecycle writes (the route may not have answered yet)."""
        return next(event["id"] for event in reversed(self.events) if event.get("status") == "running")

    def set_wgp(self, name: str, value: Any) -> None:
        """Give the fake WanGP an attribute for this test (``tests/characterization/README.md``)."""
        self.monkeypatch.setattr(self.server.wgp, name, value, raising=False)

    # -- observing ---------------------------------------------------------------------------------
    def transitions(self, job_id: str) -> list[str]:
        """Every lifecycle write of the job, in order (the canonical task observer sees the same ones)."""
        return [
            f"{event.get('status')} | phase {event.get('phase')!r} | {event.get('message')!r} | "
            f"{event.get('progress')}% | step {event.get('step')}/{event.get('total_steps')} | "
            f"outputs {len(event.get('output_files') or [])}"
            for event in self.events if event.get("id") == job_id
        ]

    def files(self, folder: Path | None = None) -> list[str]:
        folder = folder or self.server.outputs
        return sorted(path.name for path in folder.iterdir() if path.is_file() and not path.name.startswith("."))

    def sidecars(self, folder: Path | None = None) -> dict[str, Any]:
        folder = folder or self.server.outputs
        return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(folder.glob("*.meta.json"))}

    def left_behind(self) -> dict:
        launch, wgp = self.launch, self.server.wgp
        free = launch._gen_lock.acquire(blocking=False)
        if free:
            launch._gen_lock.release()
        return {
            "abort_states": sorted(launch._active_gen_states),
            "durable_queue": [record["id"] for record in launch._durable_generation_queue.list()],
            "save_path": wgp.save_path,
            "image_save_path": wgp.image_save_path,
            "audio_save_path": wgp.audio_save_path,
            "vram_coefficient": wgp.args.vram_safety_coefficient,
            "gpu_lock_free": free,
        }

    def observe(self, job_id: str, *, full: bool = False, whole_sidecars: bool = False, workspace: str = "default") -> dict:
        """Everything a refactor of the worker must leave as it is. ``full`` keeps the whole status and canonical
        task; ``whole_sidecars`` keeps the whole asset manifest instead of the keys the worker writes."""
        folder = self.server.outputs if workspace == "default" else self.server.outputs / workspace
        status = self.get(f"/api/v1/status/{job_id}")
        task = self.get(f"/api/v1/tasks/{status['task_id']}", workspace=workspace)
        record = self.launch.snapshot_job(self.launch._jobs[job_id])
        sidecars = self.sidecars(folder)
        observed = {
            "status": status if full else {key: status.get(key) for key in STATUS_KEYS},
            "task": task if full else {key: task["task"].get(key) for key in TASK_KEYS},
            "record": {key: record[key] for key in RECORD_KEYS if key in record},
            "timers": [timer["status"] for timer in status.get("task_timings", [])],
            "transitions": self.transitions(job_id),
            "files": self.files(folder),
            "sidecars": sidecars if whole_sidecars else {
                name: {key: sidecar[key] for key in SIDECAR_KEYS if key in sidecar} for name, sidecar in sidecars.items()},
            "listed": [item["job_id"] for item in self.get("/api/v1/jobs")["jobs"]],
            "left_behind": self.left_behind(),
            "engine_calls": json.loads(json.dumps(self.engine.calls)),
        }
        if job_id in self.accepted:
            observed["accepted"] = self.accepted[job_id]
        # Internal callers (the Director, the shot-aware edit workers) act on what the worker returns.
        observed["returned"] = self.returned.get(job_id)
        return observed

    def check(self, golden, case: str, body: Any, *, mask: tuple[str, ...] = ()) -> None:
        # A multi-clip group id carries the second it was made in.
        replace = tuple((re.escape(job_id), "<JOB>") for job_id in self.job_ids) + ((r"mc_\d+_", "mc_<EPOCH>_"),)
        body = json.loads(json.dumps(body))  # int keys and tuples become what a golden file holds
        golden.check(case, 200, self.server.normalise(body, mask=MASKED + mask, replace=replace))


@pytest.fixture(scope="module")
def clip(tmp_path_factory) -> Path:
    """A decodable one-second clip, made once per module."""
    return media.video(tmp_path_factory.mktemp("engine-media") / "clip.mp4")


def _media_writer(clip_file: Path) -> Callable[[str, str], None]:
    def write(path: str, kind: str) -> None:
        if kind == "video":
            shutil.copyfile(clip_file, path)
        elif kind == "image":
            media.image(Path(path))
        else:
            media.sound(Path(path))

    return write


@pytest.fixture
def rig(server, clip, tmp_path, monkeypatch):
    """The server with a scripted engine, and every process-wide thing the worker touches pointed at this test."""
    from services import job_lifecycle

    launch = worker_module()
    engine = FakeEngine(write_media=_media_writer(clip))
    for name, value in {**catalog_attributes(), **generation_attributes(engine, server.wgp)}.items():
        monkeypatch.setattr(server.wgp, name, value, raising=False)
    monkeypatch.setattr(launch._durable_generation_queue, "path", str(tmp_path / "queue.json"))
    # The per-job VRAM adjustment reads the machine's GPU the first time; a test must not depend on it.
    monkeypatch.setattr(launch, "_cached_hardware", {"gpu_vram_gb": 0.0})
    known = set(launch._jobs)
    state = Rig(server=server, engine=engine, monkeypatch=monkeypatch)

    def clear_queue() -> None:
        with job_lifecycle._generation_queue_condition:
            job_lifecycle._generation_queues.pop(id(launch._gen_lock), None)

    def record(snapshot) -> None:
        launch._observe_generation_job_state(snapshot)
        state.events.append(dict(snapshot))

    original_worker = launch._run_generation

    def run_generation(job_id: str, *, finalize: bool = True) -> bool:
        result = original_worker(job_id, finalize=finalize)
        state.returned[job_id] = result
        return result

    monkeypatch.setattr(launch, "_run_generation", run_generation)
    clear_queue()
    job_lifecycle.set_job_state_observer(record)
    yield state
    for released in state.releases:
        released.set()
    state.join()
    job_lifecycle.set_job_state_observer(launch._observe_generation_job_state)
    for job_id in set(launch._jobs) - known:
        launch._jobs.pop(job_id, None)
    clear_queue()


def hold_then(finish: Callable[[Any], None] | None = None, *, release: threading.Event, ignore_abort: bool = False):
    """An engine script: one progress step, then wait like a long denoising loop; ``finish`` runs if never aborted."""

    def script(call) -> None:
        call.send("progress", [(1, 2), "Sampling | 1/2"])
        aborted = call.hold(release, ignore_abort=ignore_abort)
        if finish is not None and not aborted:
            finish(call)

    return script


# -- a job that succeeds -----------------------------------------------------------------------------
def test_a_video_job_runs_start_to_finish(rig, golden) -> None:
    job_id = rig.run(BODY)
    rig.check(golden, "video job", rig.observe(job_id, full=True, whole_sidecars=True))


def test_an_image_job_and_a_random_seed(rig, golden) -> None:
    """An image keeps its film grain in the params; seed -1 comes back as the seed the file name carries."""
    job_id = rig.run({**BODY, "prompt": "a red barn", "generation_mode": "image", "seed": -1,
                      "film_grain_intensity": 0.3, "video_length": 1})
    rig.check(golden, "image job", rig.observe(job_id, full=True))


def test_a_job_in_a_named_workspace_locks_the_save_path_and_puts_it_back(rig, golden) -> None:
    assert rig.server.client.post("/api/v1/workspaces", json={"name": "golden-ws"}).status_code == 200
    job_id = rig.run({**BODY, "workspace": "golden-ws"})
    rig.check(golden, "named workspace job", {**rig.observe(job_id, full=True, workspace="golden-ws"),
                                               "outputs root": rig.files()})


def test_repeat_generation_is_one_task_with_several_outputs(rig, golden) -> None:
    job_id = rig.run({**BODY, "repeat_generation": 2})
    rig.check(golden, "repeat generation", rig.observe(job_id))


def test_progress_commands_become_job_progress(rig, golden) -> None:
    """Every kind of command a model can send, as the worker turns it into progress, message and phase."""

    def script(call) -> None:
        call.send("status", "Loading weights")
        call.send("progress", [(3, 20), "Sampling | 3/20"])
        call.send("progress", [0, "Warming up"])
        call.send("progress", [(1, 10), "Segment 2/4"])
        call.send("progress", [(1, 10), "Generating | 12/600 s"])
        call.send("progress", "not a list")
        call.send("info", "Half way")
        call.send("mystery", "ignored")
        call.save()

    rig.engine.script = script
    job_id = rig.run(BODY)
    rig.check(golden, "progress commands", rig.observe(job_id))


def test_denoising_steps_anchor_the_inference_clock(rig, golden, monkeypatch) -> None:
    from services import generation_memory

    monkeypatch.setattr(generation_memory, "_PACE", {})
    monkeypatch.delenv("HOCUSPOCUS_QUEUE_PACE_PATH", raising=False)

    def script(call) -> None:
        for step in (1, 2, 3):
            call.send("progress", [(step, 3), f"Denoising | {step}/3"])
            time.sleep(0.02)
        call.save()

    rig.engine.script = script
    job_id = rig.run(BODY)
    observed = rig.observe(job_id, full=True)
    observed["has_performance"] = "performance" in observed["status"]
    observed["inference_clock"] = {key: observed["task"]["task"]["metadata"][key]
                                   for key in ("inference_started_at", "inference_start_step")}
    for key in ("status", "sidecars", "task", "files", "listed"):
        observed.pop(key)
    rig.check(golden, "denoising clock", observed)


def test_the_vram_coefficient_is_tightened_for_the_job_and_restored(rig, golden, monkeypatch) -> None:
    monkeypatch.setattr(rig.launch, "_cached_hardware", {"gpu_vram_gb": 24.0})
    monkeypatch.setitem(rig.server.wgp.server_config, "vram_safety_coefficient", 0.8)
    job_id = rig.run({**BODY, "resolution": "1280x720", "video_length": 241, "activated_loras": []})
    observed = rig.observe(job_id)
    adjustment = observed["record"].pop("vram_adjustment")
    during = observed["engine_calls"][0].pop("vram_safety_coefficient")
    # The numbers belong to perf_recommend; the golden pins that the worker applies them for the job and puts the base back.
    observed["coefficient"] = {"adjusted_keys": sorted(adjustment), "applied_during_the_job": during == adjustment["effective_coef"],
                               "tighter_than_base": during < 0.8, "restored_after": observed["left_behind"]["vram_coefficient"] == 0.8}
    rig.check(golden, "vram coefficient", observed)


# -- a job that fails ---------------------------------------------------------------------------------
def test_an_engine_error_fails_the_job_with_its_text(rig, golden) -> None:
    def script(call) -> None:
        call.send("progress", [(1, 2), "Sampling | 1/2"])
        raise RuntimeError("fake engine exploded")

    rig.engine.script = script
    job_id = rig.run(BODY)
    rig.check(golden, "engine error", rig.observe(job_id, full=True))


def test_an_engine_error_after_an_output_still_publishes_that_output(rig, golden) -> None:
    def script(call) -> None:
        call.save()
        raise RuntimeError("fake engine died after saving")

    rig.engine.script = script
    job_id = rig.run(BODY)
    rig.check(golden, "engine error after output", rig.observe(job_id))


def test_an_error_inside_the_worker_is_tagged_when_it_looks_like_out_of_memory(rig, golden) -> None:
    def validate(task, state):
        raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")

    rig.set_wgp("validate_task", validate)
    job_id = rig.run(BODY)
    rig.check(golden, "worker error out of memory", rig.observe(job_id))


def test_a_worker_error_without_out_of_memory_has_no_tag(rig, golden) -> None:
    def validate(task, state):
        raise ValueError("a plain bug")

    rig.set_wgp("validate_task", validate)
    job_id = rig.run(BODY)
    rig.check(golden, "worker error plain", rig.observe(job_id))


def test_a_manifest_the_engine_cannot_parse_fails_the_job(rig, golden) -> None:
    results = [(None, "bad manifest"), ([], None)]
    rig.set_wgp("_parse_task_manifest", lambda *_args, **_kwargs: results.pop(0))
    first = rig.run(BODY)
    second = rig.run({**BODY, "prompt": "second"})
    rig.check(golden, "manifest errors", {"error": rig.observe(first), "empty queue": rig.observe(second)})


def test_oddity_a_job_whose_tasks_are_all_skipped_completes_with_nothing(rig, golden) -> None:
    """``completed == total - skipped`` holds at 0 == 0, so the job reports success and has no output."""
    rig.set_wgp("validate_task", lambda task, state: None)
    job_id = rig.run(BODY)
    rig.check(golden, "all tasks skipped", rig.observe(job_id))


@pytest.mark.parametrize("stage", ["depth", "h3_lora", "managed_lora"])
def test_a_failing_preparation_step_fails_the_job_before_any_model_work(rig, golden, monkeypatch, stage) -> None:
    from services import managed_preprocessors

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"{stage} is not available")

    released: list = []
    if stage == "depth":
        monkeypatch.setattr(managed_preprocessors, "uses_temporal_depth", lambda params: True)
        monkeypatch.setattr(managed_preprocessors, "ensure_video_depth_checkpoint", explode)
    elif stage == "managed_lora":
        rig.patch("_ensure_managed_loras_present", explode)
    else:
        monkeypatch.setattr(managed_preprocessors, "ensure_minimax_h3_lora_affine_maps", explode)
        rig.patch("_release_h3_when_queue_allows", released.append)
    job_id = rig.direct_job({**BODY, "activated_loras": ["golden.safetensors"]})
    if stage == "h3_lora":
        base = rig.server.wgp.get_model_def
        rig.set_wgp("get_model_def", lambda model_type: {**(base(model_type) or {}), "architecture": "minimax_h3_fake"})
    rig.launch._run_generation(job_id)
    rig.check(golden, f"preparation fails: {stage}", {**rig.observe(job_id), "h3 runtime release asked for": released})


# -- cancelling ------------------------------------------------------------------------------------------
def test_a_queued_job_cancelled_before_it_starts_never_reaches_the_engine(rig, golden, monkeypatch) -> None:
    """The slot is not acquired (``acquired`` is False): the worker returns before its ``try`` block, so it
    does not touch the running job's VRAM coefficient, abort state or save path."""
    monkeypatch.setattr(rig.launch, "_cached_hardware", {"gpu_vram_gb": 24.0})
    monkeypatch.setitem(rig.server.wgp.server_config, "vram_safety_coefficient", 0.8)
    release = rig.event()
    rig.engine.script = hold_then(lambda call: call.save(), release=release)
    first = rig.post({**BODY, "resolution": "1280x720", "video_length": 241})["job_id"]
    assert rig.engine.entered.wait(10)
    rig.wait_for(first, message="Sampling | 1/2")
    coefficient = rig.server.wgp.args.vram_safety_coefficient
    second = rig.post({**BODY, "prompt": "never started"})["job_id"]
    waiting = {"first": rig.get(f"/api/v1/status/{first}"), "second": rig.get(f"/api/v1/status/{second}"),
               "listed": rig.get("/api/v1/jobs")}
    cancelled = rig.cancel(second)
    rig.wait_until(lambda: len(rig.workers()) == 1, "the cancelled job's worker returning")
    waiting["first's coefficient untouched"] = (coefficient < 0.8
                                                 and rig.server.wgp.args.vram_safety_coefficient == coefficient)
    waiting["first's abort state kept"] = sorted(rig.launch._active_gen_states) == [first]
    release.set()
    rig.join()
    never_started = rig.observe(second)
    never_started.pop("engine_calls")
    rig.check(golden, "cancel before start", {
        "waiting": waiting, "cancel": cancelled, "first": rig.observe(first), "second": never_started,
        "engine prompts": [call["prompt"] for call in rig.engine.calls],
    })


def test_a_running_job_is_cancelled_through_its_abort_state(rig, golden) -> None:
    release = rig.event()
    rig.engine.script = hold_then(release=release, ignore_abort=True)
    job_id = rig.post(BODY)["job_id"]
    assert rig.engine.entered.wait(10)
    rig.wait_for(job_id, message="Sampling | 1/2")
    cancelled = rig.cancel(job_id)
    aborting = {"status": rig.get(f"/api/v1/status/{job_id}"),
                "abort_flag": rig.launch._active_gen_states[job_id]["abort"]}
    release.set()
    rig.join()
    rig.check(golden, "cancel during run", {"cancel": cancelled, "while aborting": aborting,
                                            **rig.observe(job_id, full=True)})


def test_a_cancel_after_an_output_keeps_that_output(rig, golden) -> None:
    release = rig.event()

    def script(call) -> None:
        call.save()
        call.send("progress", [(1, 2), "Sampling | 1/2"])
        call.hold(release, ignore_abort=True)

    rig.engine.script = script
    job_id = rig.post(BODY)["job_id"]
    assert rig.engine.entered.wait(10)
    rig.wait_for(job_id, message="Sampling | 1/2")
    cancelled = rig.cancel(job_id)
    release.set()
    rig.join()
    rig.check(golden, "cancel after output", {"cancel": cancelled, **rig.observe(job_id)})


def test_a_cancel_between_two_clips_stops_before_the_next_task(rig, golden, monkeypatch) -> None:
    """The loop-top check: cancel lands in the pause between clips (the worker frees CUDA memory there)."""
    _install_fake_decord(monkeypatch)

    def cancel_between_clips() -> None:
        job_id = rig.running_job_id()
        rig.launch.request_cancel(rig.launch._jobs[job_id], job_id=job_id, active_states=rig.launch._active_gen_states)

    monkeypatch.setattr(rig.launch.torch.cuda, "empty_cache", cancel_between_clips)
    job_id = rig.run(MULTI_CLIP)
    rig.check(golden, "cancel between clips", rig.observe(job_id))


def test_oddity_a_cancel_between_start_and_abort_registration_leaves_the_job_cancelling(rig, golden) -> None:
    """The job is cancelled after it started but before it registered its abort state. The worker returns, and
    nothing ever settles the job, because the ``finally`` block only acknowledges a job that never created its
    abort state."""
    launch = rig.launch
    job_id = rig.direct_job(BODY)

    def cancel_during_preparation(job) -> None:
        launch.request_cancel(job, job_id=job_id, active_states=launch._active_gen_states)

    rig.patch("_apply_per_job_coefficient", cancel_during_preparation)
    launch._run_generation(job_id)
    rig.check(golden, "cancel before abort registration", rig.observe(job_id))


def test_a_job_cancelled_after_taking_the_slot_never_starts(rig, golden) -> None:
    """``try_start`` refuses a cancelled job: the engine is never called."""
    from contextlib import contextmanager

    launch = rig.launch
    job_id = rig.direct_job(BODY)
    launch._jobs[job_id]["cancel_requested"] = True

    @contextmanager
    def slot_taken(job):
        yield True

    rig.patch("_coordinated_generation_slot", slot_taken)
    launch._run_generation(job_id)
    rig.check(golden, "cancelled after slot", rig.observe(job_id))


# -- several tasks -------------------------------------------------------------------------------------------
def test_a_multi_clip_job_runs_one_task_per_line_and_continues_each_from_the_last_frame(rig, golden, monkeypatch) -> None:
    reads = _install_fake_decord(monkeypatch)
    job_id = rig.run(MULTI_CLIP)
    rig.check(golden, "multi clip", {**rig.observe(job_id), "decord reads": reads})


def test_a_multi_clip_job_with_start_and_end_images_trims_the_tail_and_adds_a_compensation_clip(rig, golden) -> None:
    job_id = rig.run({
        **BODY, "multi_prompts_gen_type": 3, "prompt": "left\nright", "per_clip_frames": [17, 17],
        "image_start": ["start-a.png", "start-b.png"], "image_end": ["end-a.png", "end-b.png"],
        "multi_clip_audio_start_sec": 1.5, "audio_frame_offset": 24,
    })
    rig.check(golden, "multi clip with end images", rig.observe(job_id))


def test_a_skipped_clip_does_not_fail_the_job(rig, golden, monkeypatch) -> None:
    _install_fake_decord(monkeypatch)
    real = rig.server.wgp.validate_task
    rig.set_wgp("validate_task", lambda task, state: None if task["prompt"] == "second shot" else real(task, state))
    job_id = rig.run(MULTI_CLIP)
    rig.check(golden, "multi clip with a skipped clip", rig.observe(job_id))


def test_a_clip_that_fails_fails_the_whole_job_but_keeps_the_clips_before_it(rig, golden, monkeypatch) -> None:
    _install_fake_decord(monkeypatch)

    def script(call) -> None:
        if call.index == 1:
            raise RuntimeError("the second clip failed")
        call.save()

    rig.engine.script = script
    job_id = rig.run(MULTI_CLIP)
    rig.check(golden, "multi clip with a failing clip", rig.observe(job_id))


def test_a_cancel_during_the_second_clip_keeps_the_first(rig, golden, monkeypatch) -> None:
    _install_fake_decord(monkeypatch)
    release = rig.event()

    def script(call) -> None:
        if call.index == 0:
            call.save()
            return
        call.send("progress", [(1, 2), "Sampling | 1/2"])
        call.hold(release, ignore_abort=True)

    rig.engine.script = script
    job_id = rig.post(MULTI_CLIP)["job_id"]
    assert rig.engine.entered.wait(10)
    rig.wait_for(job_id, message="Clip 2/3: Sampling | 1/2")
    cancelled = rig.cancel(job_id)
    release.set()
    rig.join()
    rig.check(golden, "multi clip cancelled in the second clip", {"cancel": cancelled, **rig.observe(job_id)})


SHOT_WORKFLOWS = ["_recast_shot_manifest", "_repaint_shot_manifest", "_outpaint_shot_manifest"]


@pytest.mark.parametrize("workflow", SHOT_WORKFLOWS)
def test_shot_manifests_become_deferred_clips(rig, golden, workflow) -> None:
    """Recast, Repaint and Outpaint hand the worker exact per-shot settings; their finisher joins the clips."""
    shots = [{"shot_index": 0, "params": {"prompt": "shot zero", "video_length": 17}},
             {"shot_index": 1, "params": {"prompt": "shot one", "video_length": 25}}, {"params": "ignored"}, "ignored"]
    job_id = rig.direct_job({**BODY, workflow: shots, "_defer_output_publication": True})
    rig.launch._run_generation(job_id, finalize=False)
    rig.check(golden, f"shot manifest: {workflow}", rig.observe(job_id))


@pytest.mark.parametrize("workflow, manifest", [("_recast_shot_manifest", "not a list"),
                                               ("_repaint_shot_manifest", [{"params": 3}]),
                                               ("_outpaint_shot_manifest", [])])
def test_a_shot_manifest_that_is_not_usable_fails_the_job(rig, golden, workflow, manifest) -> None:
    job_id = rig.direct_job({**BODY, workflow: manifest})
    rig.launch._run_generation(job_id)
    rig.check(golden, f"unusable shot manifest: {workflow}", rig.observe(job_id))


# -- finalization -------------------------------------------------------------------------------------------------
def test_a_caller_that_finishes_the_job_itself_gets_it_at_ninety_nine_percent(rig, golden) -> None:
    job_id = rig.direct_job(BODY)
    rig.launch._run_generation(job_id, finalize=False)
    rig.check(golden, "finalize false", rig.observe(job_id))


def test_oddity_deferred_output_publication_over_http_publishes_nothing(rig, golden) -> None:
    """With ``finalize`` True the worker completes the job but hands back no output and writes no sidecar."""
    job_id = rig.run({**BODY, "_defer_output_publication": True})
    rig.check(golden, "deferred publication, finalized", rig.observe(job_id))


def test_deferred_output_publication_keeps_the_files_for_the_caller(rig, golden) -> None:
    job_id = rig.direct_job({**BODY, "_defer_output_publication": True})
    rig.launch._run_generation(job_id, finalize=False)
    rig.check(golden, "deferred publication, not finalized", rig.observe(job_id))


# -- finding outputs ------------------------------------------------------------------------------------------------
def test_an_output_the_engine_did_not_register_is_claimed_when_it_is_the_only_new_file(rig, golden) -> None:
    rig.engine.script = lambda call: call.save(register=False)
    job_id = rig.run(BODY)
    rig.check(golden, "unregistered output", rig.observe(job_id))


def test_a_director_job_never_claims_an_output_the_engine_did_not_register(rig, golden) -> None:
    rig.engine.script = lambda call: call.save(register=False)
    job_id = rig.direct_job({**BODY, "_director_pipeline_id": "pipeline-golden"})
    rig.launch._run_generation(job_id)
    rig.check(golden, "unregistered output of a director job", rig.observe(job_id))


def test_a_recovered_job_says_it_restarts_from_the_beginning(rig, golden) -> None:
    job_id = rig.direct_job(BODY, recovered=True)
    rig.launch._run_generation(job_id)
    rig.check(golden, "recovered job", rig.observe(job_id))


# -- post-processing -------------------------------------------------------------------------------------------------
def test_post_processing_runs_in_a_fixed_order_on_every_video(rig, golden, tmp_path, monkeypatch) -> None:
    media.sound(tmp_path / "uploads" / "audio" / "voice.wav")
    order: list = []

    def upscale(path, method, job=None):
        order.append(["upscale", Path(path).name, method])
        Path(path).write_bytes(b"upscaled")

    def film_grain(path, intensity, saturation):
        order.append(["film grain", Path(path).name, intensity, saturation])
        Path(path).write_bytes(b"graded")

    rig.patch("_apply_spatial_upsampling_to_file", upscale)
    rig.patch("_apply_film_grain_to_file", film_grain)

    def voice_clone(video_path, voice_ref_paths, mode):
        order.append(["voice clone", Path(video_path).name, [Path(ref).name for ref in voice_ref_paths], mode])

    monkeypatch.setitem(sys.modules, "postprocessing.voice_clone", SimpleNamespace(apply_voice_clone_to_file=voice_clone))
    job_id = rig.run({**BODY, "film_grain_intensity": 0.4, "film_grain_saturation": 0.7, "spatial_upsampling": "flashvsr_x2",
                      "voice_clone_enabled": True, "voice_clone_refs": ["audio/voice.wav", "audio/missing.wav"],
                      "voice_clone_mode": "two"})
    observed = rig.observe(job_id, full=True)
    # The sidecar is written again after post-processing, so it describes the file the passes left behind.
    (name, sidecar), = rig.sidecars().items()
    sizes = {"file": (rig.server.outputs / sidecar["output_filename"]).stat().st_size,
             "sidecar": sidecar["asset"]["media"]["size_bytes"]}
    rig.check(golden, "post-processing order", {**observed, "order": order, "bytes": sizes})


def test_dynamic_audio_normalisation_runs_ffmpeg_on_audio_outputs(rig, golden, monkeypatch) -> None:
    commands: list = []
    real_run = subprocess.run

    def recording_run(command, *args, **kwargs):
        if "-af" in command:
            commands.append(list(command))
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", recording_run)
    job_id = rig.run({**BODY, "generation_mode": "audio", "tts_dynaudnorm": True, "tts_comp_threshold": -30})
    rig.check(golden, "dynamic audio normalisation", {**rig.observe(job_id), "ffmpeg": commands})


# -- other engines -------------------------------------------------------------------------------------------------------
def _stub_mmaudio(rig, monkeypatch, *, enabled: bool = True) -> dict:
    seen: dict = {"downloads": [], "synthesis": []}
    rig.set_wgp("get_mmaudio_settings",
                lambda config, variant_override=None: (enabled, None, 2, "fake-mmaudio", "ckpts/fake-mmaudio"))
    rig.set_wgp("download_mmaudio", lambda variant_override=None: seen["downloads"].append(variant_override))
    rig.set_wgp("MMAUDIO_PERSIST_RAM", 2)

    def video_to_audio(**kwargs) -> None:
        seen["synthesis"].append({key: kwargs[key] for key in ("prompt", "negative_prompt", "seed", "duration",
                                                               "audio_file_only", "model_name", "text_weight")}
                                 | {"file": Path(kwargs["save_path"]).name})
        media.sound(Path(kwargs["save_path"]))

    monkeypatch.setitem(sys.modules, "postprocessing.mmaudio.mmaudio", SimpleNamespace(video_to_audio=video_to_audio))
    return seen


SFX_BODY = {"model_type": "mmaudio_v2", "sfx_mode": True, "generation_mode": "audio", "prompt": "rain on a tin roof",
            "duration_seconds": 40, "seed": 7, "_mmaudio_variant": "v2"}


def test_a_sound_effect_job_runs_the_audio_model_instead_of_the_engine(rig, golden, monkeypatch) -> None:
    seen = _stub_mmaudio(rig, monkeypatch)
    job_id = rig.run(SFX_BODY)
    rig.check(golden, "sound effect", {**rig.observe(job_id, full=True), "audio model": seen})


def test_a_sound_effect_job_fails_when_the_audio_model_is_off(rig, golden, monkeypatch) -> None:
    seen = _stub_mmaudio(rig, monkeypatch, enabled=False)
    job_id = rig.run({**SFX_BODY, "_mmaudio_variant": None})
    rig.check(golden, "sound effect disabled", {**rig.observe(job_id), "audio model": seen})


def test_the_legacy_h3_route_runs_its_isolated_runtime(rig, golden, tmp_path) -> None:
    from services import minimax_h3_service

    launch = rig.launch
    calls: list = []

    def generate(params, job_id, out_dir, progress, cancelled, keep_runtime=False):
        calls.append(["generate", sorted(params), job_id, cancelled(), keep_runtime])
        progress("Sampling window", 40, 3, 8)
        progress("Almost done", 100)
        path = Path(out_dir) / "legacy_h3_clip.mp4"
        rig.engine.write_media(str(path), "video")
        return [str(path)]

    for name in ("cancel_idle_shutdown", "stop_runtime", "cancel"):
        rig.monkeypatch.setattr(minimax_h3_service, name, lambda *a, _name=name, **k: calls.append([_name]))
    rig.monkeypatch.setattr(minimax_h3_service, "generate", generate)
    rig.patch("_release_legacy_h3_when_queue_allows", lambda job_id: calls.append(["release when idle", job_id]))
    job_id = rig.direct_job({**BODY, "model_type": minimax_h3_service.MODEL_ID, "_director_pipeline_id": ""})
    launch._run_generation(job_id)
    rig.check(golden, "legacy h3", {**rig.observe(job_id, full=True), "service calls": calls})


def test_simulated_execution_replaces_only_the_inference(rig, golden) -> None:
    seen: list = []

    def simulated(job, finalize):
        seen.append([job["id"], finalize])
        return rig.launch.finish_job(job, "completed", progress=100, phase="", message="Done · simulated artifact")

    rig.patch("execution_mode", SimpleNamespace(policy=lambda: SimpleNamespace(simulated=True, mode="simulate")))
    rig.patch("_run_simulated_generation", simulated)
    job_id = rig.direct_job(BODY)
    rig.launch._run_generation(job_id)
    rig.check(golden, "simulated", {**rig.observe(job_id), "simulated calls": seen})


def test_a_cancelled_simulated_job_is_settled_by_the_worker(rig, golden) -> None:
    """The simulated executor only returns False when it is cancelled; the worker's ``finally`` block settles the job."""
    launch = rig.launch

    def cancelled_executor(job, finalize):
        launch.request_cancel(job, job_id=job["id"], active_states=launch._active_gen_states)
        return False

    rig.patch("execution_mode", SimpleNamespace(policy=lambda: SimpleNamespace(simulated=True, mode="simulate")))
    rig.patch("_run_simulated_generation", cancelled_executor)
    job_id = rig.direct_job(BODY)
    launch._run_generation(job_id)
    rig.check(golden, "simulated and cancelled", rig.observe(job_id))
