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
repoints ``worker_modules``.

The goldens pin today's behaviour, including its oddities. Tests whose names
start with ``test_oddity_`` pin behaviour that looks unintended; a refactor must
keep it, and a fix is its own PR that re-records the golden.

Film grain, the chunked FlashVSR upscale and the spatial-upsampling pass are
not reached from the worker tests: those tests replace film grain and spatial
upsampling, and nothing calls the chunked upscale. The tests at the bottom of
this module call the three functions and record what they do to a file. Torch,
decord, the grain kernel, the FlashVSR model and ffmpeg are stubbed: grain is
random, and FlashVSR needs a GPU this suite does not have.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import types
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

import pytest

from services.hardware_probe import hardware_cache
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
# How long a test waits for the worker to reach a state. Generous: a loaded CI machine is slow, and the wait only
# ends early when the state is reached.
WAIT = 30.0
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
    """The full server module: the jobs, the locks and ``request_cancel`` the worker and the tests share live here."""
    return sys.modules["_launch_runtime"]


# The modules of the generation worker package, in the order the worker runs them.
WORKER_PACKAGE = ("prepare", "tasks", "finalize")

# The post-processing passes the worker calls by their launch names (C4), and the launch functions each module took.
POSTFX_MODULES = {
    "services.generation_coefficients": ("_apply_per_job_coefficient", "_restore_base_coefficient"),
    "services.generation_postprocess": ("_apply_film_grain_to_file", "_apply_spatial_upsampling_to_file"),
    "services.generation_flashvsr": ("_chunked_flashvsr_upscale",),
    "services.generation_sfx": ("_run_sfx_generation",),
}
# Outpaint and blend (C5): the modules that took their launch objects, which they read under the launch names.
OUTPAINT_BLEND_MODULES = ("services.outpaint_planning", "services.outpaint_run", "routers.outpaint",
                          "services.blend_run", "routers.blend")

# The Recast helper modules (C7). The worker's bystander protection calls two of their functions by their launch
# names, and the helpers call each other through each module's own globals.
RECAST_MODULES = (
    "services.recast_masks",
    "services.recast_matte",
    "services.recast_reference_compose",
    "services.recast_reference_prepare",
)

# The Recast shot modules (C8a). The shot assembler reads its collaborators (the audio probe, the frame count, the
# worker) through its own module's globals, and the manifest and planning functions call each other the same way.
SHOT_MODULES = (
    "services.recast_shot_planning",
    "services.recast_shot_manifest",
    "services.recast_shot_run",
)
# Recast route modules (C8b). The preview handler imports its collaborators, so a stub has to
# land on that module too, not only on launch.
ROUTE_MODULES = (
    "services.recast_preview",
    "services.recast_endpoint",
)

# Repaint (C6): the modules that took their launch objects, which they read under the launch names.
REPAINT_MODULES = ("services.repaint_planning", "services.repaint_run", "routers.repaint")

# Helpers the worker calls by the launch name that C9c moved. Included once the full server has imported them.
MOVED_CALLEES = (
    "services.managed_loras",
    "services.generation_option_helpers",
)

# Canonical tasks (C10a): a generation publishes its Activity row through them, so a patch of ``time`` (or any other
# name they hold) has to land on them too, or the task clock diverges from the launch name the test patched.
CANONICAL_TASK_MODULES = (
    "services.canonical_task_fields",
    "services.canonical_task_publishers",
    "services.canonical_task_sync",
)

# Collaborators that left the server file and still read names these tests replace. Recovery and the job routes
# hold ``_cancel_h3_idle_release`` and ``time``, which a rig patch reached in launch before the move.
COLLABORATOR_MODULES = (
    "services.generation_preparation",
    "services.generation_h3_release",
    "services.generation_recovery",
    "services.generation_jobs",
)


def worker_modules() -> list:
    """The modules whose globals the worker functions, the post-processing passes, the Recast code and the Repaint,
    Recast, outpaint and blend routes that start the worker read. A move PR repoints this one function.

    That is the full server module while any worker function or pass is still in it, each module of
    ``services.generation_worker`` that exists, each module a pass moved to (C4), each Recast helper module (C7), each
    Recast shot module (C8a), each Repaint module (C6), each outpaint and blend module (C5), each collaborator module
    the generation-jobs slice moved, each canonical task module (C10a), each helper module a moved callee lives in
    (C9c) and each Recast route module (C8b). A name they read is an attribute of every module that reads it.
    """
    package = [sys.modules[f"services.generation_worker.{name}"] for name in WORKER_PACKAGE
               if f"services.generation_worker.{name}" in sys.modules]
    passes = [sys.modules[name] for name in POSTFX_MODULES if name in sys.modules]
    recast = [sys.modules[name] for name in RECAST_MODULES if name in sys.modules]
    shots = [sys.modules[name] for name in SHOT_MODULES if name in sys.modules]
    repaint = [sys.modules[name] for name in REPAINT_MODULES if name in sys.modules]
    studio = [sys.modules[name] for name in OUTPAINT_BLEND_MODULES if name in sys.modules]
    collaborators = [sys.modules[name] for name in COLLABORATOR_MODULES if name in sys.modules]
    canonical = [sys.modules[name] for name in CANONICAL_TASK_MODULES if name in sys.modules]
    callees = [sys.modules[name] for name in MOVED_CALLEES if name in sys.modules]
    routes = [sys.modules[name] for name in ROUTE_MODULES if name in sys.modules]
    return [worker_module(), *package, *passes, *recast, *shots, *repaint, *studio, *collaborators, *canonical,
            *callees, *routes]


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
        holders = [module for module in worker_modules() if hasattr(module, name)]
        assert holders, f"no worker module has a global named {name!r}"
        for module in holders:
            self.monkeypatch.setattr(module, name, value)

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

    def call_worker(self, job_id: str, *, finalize: bool = True, timeout: float = 60.0) -> bool:
        """Run ``_run_generation`` for a job :meth:`direct_job` built. It runs in a daemon thread with a deadline, so a
        worker that never returns fails this test instead of blocking the session."""
        outcome: dict[str, Any] = {}

        def run() -> None:
            try:
                outcome["returned"] = self.launch._run_generation(job_id, finalize=finalize)
            except BaseException as error:  # handed to the test thread below
                outcome["error"] = error

        thread = threading.Thread(target=run, name=f"golden-direct-worker {job_id}", daemon=True)
        thread.start()
        thread.join(timeout)
        assert not thread.is_alive(), f"_run_generation({job_id!r}) did not return within {timeout:.0f}s"
        if "error" in outcome:
            raise outcome["error"]
        return outcome["returned"]

    def settle(self) -> None:
        """Teardown: every worker must have finished. One that has not is cancelled and given ten more seconds, so a
        broken worker fails its own test; one that still runs is left to the session guard in ``conftest.py``."""
        alive = [thread for thread in self.workers() if (thread.join(30) or thread.is_alive())]
        if not alive:
            return
        launch = self.launch
        for job_id in self.job_ids:
            if job_id in launch._jobs:
                launch.request_cancel(launch._jobs[job_id], job_id=job_id, active_states=launch._active_gen_states)
        for abort_state in list(launch._active_gen_states.values()):
            abort_state["abort"] = True
        still = [thread.name for thread in alive if (thread.join(10) or thread.is_alive())]
        raise AssertionError(f"generation workers never finished: {[thread.name for thread in alive]}; "
                             f"still running after a cancel: {still}")

    def wait_until(self, condition: Callable[[], bool], what: str) -> None:
        deadline = time.monotonic() + WAIT
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
        """Poll the live job until it shows ``expected`` and the lifecycle observer has received that write; the
        engine is held, so the state is stable. The observer runs after the lifecycle lock is released, so without the
        second condition a cancel sent from the test thread could reach the recorded transitions first."""
        deadline = time.monotonic() + WAIT
        while True:
            record = self.launch.snapshot_job(self.launch._jobs[job_id])
            observed = [event for event in list(self.events) if event.get("id") == job_id][-1:]
            if all(record.get(key) == value and observed and observed[0].get(key) == value
                   for key, value in expected.items()):
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
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 0.0})
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
    # The outpaint and blend modules (C5) start the worker from their own slot: they see the wrapper too, so the
    # thread a route starts is named after it, as it was when the routes read launch's name.
    for name in OUTPAINT_BLEND_MODULES:
        if hasattr(sys.modules.get(name), "_run_generation"):
            monkeypatch.setattr(sys.modules[name], "_run_generation", run_generation)
    clear_queue()
    job_lifecycle.set_job_state_observer(record)
    yield state
    try:
        for released in state.releases:
            released.set()
        state.settle()
    finally:
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
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 24.0})
    monkeypatch.setitem(rig.server.wgp.server_config, "vram_safety_coefficient", 0.8)
    job_id = rig.run({**BODY, "resolution": "1280x720", "video_length": 241, "activated_loras": []})
    observed = rig.observe(job_id)
    adjustment = observed["record"].pop("vram_adjustment")
    during = observed["engine_calls"][0].pop("vram_safety_coefficient")
    # The numbers belong to perf_recommend; the golden pins that the worker applies them for the job and puts the base back.
    observed["coefficient"] = {"adjusted_keys": sorted(adjustment), "applied_during_the_job": during == adjustment["effective_coef"],
                               "tighter_than_base": during < 0.8, "restored_after": observed["left_behind"]["vram_coefficient"] == 0.8}
    rig.check(golden, "vram coefficient", observed)


def test_a_native_job_starts_up_in_a_fixed_order_before_its_abort_handle_is_registered(rig, monkeypatch) -> None:
    """Between taking the slot and reaching the engine, a native (WanGP) job cancels a pending H3 idle release, stops
    the isolated H3 runtime, tightens its VRAM coefficient and only then registers its abort handle. The first two
    recorded steps belong to the GPU slot's hand-off (``_coordinated_generation_slot``), not to the worker: a change
    to that hand-off moves them."""
    from services import minimax_h3_service

    launch = rig.launch
    steps: list = []
    real_coefficient, real_register = launch._apply_per_job_coefficient, launch.register_abort_state

    def register(*args, **kwargs):
        steps.append("register abort state")
        return real_register(*args, **kwargs)

    rig.patch("_cancel_h3_idle_release", lambda: steps.append("cancel H3 idle release"))
    monkeypatch.setattr(minimax_h3_service, "stop_runtime", lambda *args, **kwargs: steps.append("stop H3 runtime"))
    monkeypatch.setattr(minimax_h3_service, "cancel_idle_shutdown",
                        lambda *args, **kwargs: steps.append("keep H3 runtime"))
    rig.patch("_apply_per_job_coefficient", lambda job: (steps.append("VRAM coefficient"), real_coefficient(job))[1])
    rig.patch("register_abort_state", register)
    rig.engine.script = lambda call: (steps.append("engine"), call.save())
    job_id = rig.direct_job(BODY)
    assert rig.call_worker(job_id) is True
    # The first two are the GPU slot's hand-off from an isolated H3 runtime, before the worker's own steps.
    assert steps == ["keep H3 runtime", "stop H3 runtime", "cancel H3 idle release", "stop H3 runtime",
                     "VRAM coefficient", "register abort state", "engine"]


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
    rig.call_worker(job_id)
    rig.check(golden, f"preparation fails: {stage}", {**rig.observe(job_id), "h3 runtime release asked for": released})


# -- cancelling ------------------------------------------------------------------------------------------
def test_a_queued_job_cancelled_before_it_starts_never_reaches_the_engine(rig, golden, monkeypatch) -> None:
    """The slot is not acquired (``acquired`` is False): the worker returns before its ``try`` block, so it
    does not touch the running job's VRAM coefficient, abort state or save path."""
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 24.0})
    monkeypatch.setitem(rig.server.wgp.server_config, "vram_safety_coefficient", 0.8)
    release = rig.event()
    rig.engine.script = hold_then(lambda call: call.save(), release=release)
    first = rig.post({**BODY, "resolution": "1280x720", "video_length": 241})["job_id"]
    assert rig.engine.entered.wait(WAIT)
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
    assert rig.engine.entered.wait(WAIT)
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
    assert rig.engine.entered.wait(WAIT)
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
    rig.call_worker(job_id)
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
    rig.call_worker(job_id)
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
    assert rig.engine.entered.wait(WAIT)
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
    rig.call_worker(job_id, finalize=False)
    rig.check(golden, f"shot manifest: {workflow}", rig.observe(job_id))


@pytest.mark.parametrize("workflow, manifest", [("_recast_shot_manifest", "not a list"),
                                               ("_repaint_shot_manifest", [{"params": 3}]),
                                               ("_outpaint_shot_manifest", [])])
def test_a_shot_manifest_that_is_not_usable_fails_the_job(rig, golden, workflow, manifest) -> None:
    job_id = rig.direct_job({**BODY, workflow: manifest})
    rig.call_worker(job_id)
    rig.check(golden, f"unusable shot manifest: {workflow}", rig.observe(job_id))


# -- finalization -------------------------------------------------------------------------------------------------
def test_a_caller_that_finishes_the_job_itself_gets_it_at_ninety_nine_percent(rig, golden) -> None:
    job_id = rig.direct_job(BODY)
    rig.call_worker(job_id, finalize=False)
    rig.check(golden, "finalize false", rig.observe(job_id))


def test_oddity_deferred_output_publication_over_http_publishes_nothing(rig, golden) -> None:
    """With ``finalize`` True the worker completes the job but hands back no output and writes no sidecar."""
    job_id = rig.run({**BODY, "_defer_output_publication": True})
    rig.check(golden, "deferred publication, finalized", rig.observe(job_id))


def test_deferred_output_publication_keeps_the_files_for_the_caller(rig, golden) -> None:
    job_id = rig.direct_job({**BODY, "_defer_output_publication": True})
    rig.call_worker(job_id, finalize=False)
    rig.check(golden, "deferred publication, not finalized", rig.observe(job_id))


# -- finding outputs ------------------------------------------------------------------------------------------------
def test_an_output_the_engine_did_not_register_is_claimed_when_it_is_the_only_new_file(rig, golden) -> None:
    rig.engine.script = lambda call: call.save(register=False)
    job_id = rig.run(BODY)
    rig.check(golden, "unregistered output", rig.observe(job_id))


def test_a_director_job_never_claims_an_output_the_engine_did_not_register(rig, golden) -> None:
    rig.engine.script = lambda call: call.save(register=False)
    job_id = rig.direct_job({**BODY, "_director_pipeline_id": "pipeline-golden"})
    rig.call_worker(job_id)
    rig.check(golden, "unregistered output of a director job", rig.observe(job_id))


def test_a_recovered_job_says_it_restarts_from_the_beginning(rig, golden) -> None:
    job_id = rig.direct_job(BODY, recovered=True)
    rig.call_worker(job_id)
    rig.check(golden, "recovered job", rig.observe(job_id))


def test_resuming_the_recovery_queue_runs_the_leftover_from_the_beginning(rig, golden) -> None:
    """``POST /api/v1/jobs/recovery/resume`` requeues a durable leftover and starts the real preparation worker."""
    launch = rig.launch
    job_id = "golden-resume"
    launch._durable_generation_queue.upsert({
        "id": job_id, "status": "running", "created_at": CREATED, "params": dict(BODY), "workspace": "default",
    })
    response = rig.server.client.post("/api/v1/jobs/recovery/resume")
    assert response.status_code == 200, response.text
    name = f"recovered-generation-{job_id}"
    deadline = time.monotonic() + 60.0
    while time.monotonic() < deadline:
        alive = [thread for thread in threading.enumerate() if thread.name == name and thread.is_alive()]
        job = launch._jobs.get(job_id)
        if alive:
            alive[0].join(deadline - time.monotonic())
            break
        if isinstance(job, dict) and job.get("status") in {"completed", "failed", "cancelled"}:
            break
        time.sleep(0.01)
    else:
        job = launch._jobs.get(job_id)
        if isinstance(job, dict):
            launch.request_cancel(job, job_id=job_id, active_states=launch._active_gen_states)
        for state in list(launch._active_gen_states.values()):
            state["abort"] = True
        for thread in threading.enumerate():
            if thread.name == name:
                thread.join(10)
        raise AssertionError(f"{name} did not finish")
    job = launch._jobs.get(job_id)
    assert isinstance(job, dict) and job.get("status") in {"completed", "failed", "cancelled"}
    rig.job_ids.append(job_id)
    rig.check(golden, "resumed leftover", {"http": response.json(), **rig.observe(job_id)})


def test_the_real_simulated_executor_writes_an_artifact_and_finishes_the_job(rig, golden, monkeypatch) -> None:
    """The worker's simulated branch calls the real executor. Only the policy flag is replaced."""
    import services.generation_worker.prepare as prepare

    monkeypatch.setattr(
        prepare, "execution_mode", SimpleNamespace(policy=lambda: SimpleNamespace(simulated=True, mode="simulate")),
    )
    job_id = rig.direct_job({**BODY, "generation_mode": "image", "video_length": 1, "prompt": "a simulated barn"})
    rig.call_worker(job_id)
    rig.check(golden, "real simulated executor", rig.observe(job_id, full=True))


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


def _stub_legacy_h3(rig, calls: list, *, output: str = "legacy_h3_clip.mp4"):
    """The isolated Comfy runtime of the legacy H3 route, recording every call; returns the service module."""
    from services import minimax_h3_service

    def generate(params, job_id, out_dir, progress, cancelled, keep_runtime=False):
        calls.append(["generate", sorted(params), job_id, cancelled(), keep_runtime])
        progress("Sampling window", 40, 3, 8)
        progress("Almost done", 100)
        path = Path(out_dir) / output
        rig.engine.write_media(str(path), "video")
        return [str(path)]

    for name in ("cancel_idle_shutdown", "stop_runtime", "cancel"):
        rig.monkeypatch.setattr(minimax_h3_service, name, lambda *a, _name=name, **k: calls.append([_name]))
    rig.monkeypatch.setattr(minimax_h3_service, "generate", generate)
    rig.patch("_release_legacy_h3_when_queue_allows", lambda job_id: calls.append(["release when idle", job_id]))
    return minimax_h3_service


def test_the_legacy_h3_route_runs_its_isolated_runtime(rig, golden, tmp_path) -> None:
    calls: list = []
    service = _stub_legacy_h3(rig, calls)
    job_id = rig.direct_job({**BODY, "model_type": service.MODEL_ID, "_director_pipeline_id": ""})
    rig.call_worker(job_id)
    rig.check(golden, "legacy h3", {**rig.observe(job_id, full=True), "service calls": calls})


def test_the_legacy_h3_route_extends_a_source_video_for_a_caller_that_finalizes_it(rig, golden) -> None:
    """A Director job (pipeline id) extends a source video: the worker anchors on the source's last frame, keeps
    the anchored params as the job's params, stops at 99% and leaves the runtime release to the Director."""
    calls: list = []
    service = _stub_legacy_h3(rig, calls, output="legacy_h3_extend.mp4")

    def prepare_extend_anchor(params, job_id, source_path, uploads_dir):
        calls.append(["extend anchor", job_id, source_path, Path(uploads_dir).name])
        params["image_start"] = "uploads/anchor-frame.png"
        return {"ignored_references": 2, "time": 3.25, "path": "uploads/anchor-frame.png"}

    rig.monkeypatch.setattr(service, "prepare_extend_anchor", prepare_extend_anchor)
    rig.patch("_resolve_video_editor_source", lambda value: f"resolved/{value}")
    job_id = rig.direct_job({**BODY, "model_type": service.MODEL_ID, "video_source": "uploads/source.mp4",
                             "_director_pipeline_id": "pipeline-legacy"})
    rig.call_worker(job_id, finalize=False)
    rig.check(golden, "legacy h3 extend, not finalized", {**rig.observe(job_id, full=True), "service calls": calls})


def test_simulated_execution_replaces_only_the_inference(rig, golden) -> None:
    seen: list = []

    def simulated(job, finalize):
        seen.append([job["id"], finalize])
        return rig.launch.finish_job(job, "completed", progress=100, phase="", message="Done · simulated artifact")

    rig.patch("execution_mode", SimpleNamespace(policy=lambda: SimpleNamespace(simulated=True, mode="simulate")))
    rig.patch("_run_simulated_generation", simulated)
    job_id = rig.direct_job(BODY)
    rig.call_worker(job_id)
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
    rig.call_worker(job_id)
    rig.check(golden, "simulated and cancelled", rig.observe(job_id))


# -- the abort flag reaches the engine --------------------------------------------------------------------------------
def test_a_cancel_reaches_the_engine_through_the_abort_flag_and_interrupts_the_model(rig, golden) -> None:
    """The registered abort state is the engine's own generation state: a denoising loop that watches the flag stops
    by itself (this engine does not ignore it, unlike the cancel tests above), and the native model interrupt runs."""
    interrupts: list = []
    stopped: list = []
    cancel_answered = rig.event()
    rig.patch("_interrupt_wan_model", lambda: interrupts.append("interrupt"))

    def script(call) -> None:
        call.send("progress", [(1, 2), "Sampling | 1/2"])
        stopped.append(call.hold(rig.event()))
        # Return only after the cancel route has answered (and notified), so the recorded order is the real one.
        cancel_answered.wait(WAIT)
        if not stopped[-1]:
            call.save()

    rig.engine.script = script
    job_id = rig.post(BODY)["job_id"]
    assert rig.engine.entered.wait(WAIT)
    rig.wait_for(job_id, message="Sampling | 1/2")
    cancelled = rig.cancel(job_id)
    cancel_answered.set()
    rig.join()
    rig.check(golden, "cancel stops the engine", {"cancel": cancelled, "engine stopped by the abort flag": stopped,
                                                  "model interrupts": interrupts, **rig.observe(job_id)})


# -- manifests the first scenarios did not build ----------------------------------------------------------------------
BOUNDARY = "\n---CLIP_BOUNDARY---\n"


def _bounded_model(rig, **lattice: int) -> None:
    """fake_t2v as a bounded start/end Director model: a 9..33 frame lattice in steps of 8 unless ``lattice`` says."""
    base = rig.server.wgp.get_model_def
    bounded = {"director_video_strategy": "bounded_start_end", "frames_minimum": 9, "frames_steps": 8,
               "frames_maximum": 33, **lattice}
    rig.set_wgp("get_model_def", lambda model_type: {**(base(model_type) or {}), **bounded}
                if model_type == "fake_t2v" else base(model_type))


def test_a_bounded_director_job_continues_only_the_clips_that_ask_for_it(rig, golden, monkeypatch) -> None:
    """A bounded model checks each clip against its frame lattice, continues a clip from the true last frame only
    when the clip asks for it, keeps the visible SE duration when asked, and carries per-clip keyframes and H3
    references. The prompt splits on the Director's clip boundary; a bad seed or audio offset falls back."""
    reads = _install_fake_decord(monkeypatch)
    _bounded_model(rig)
    job_id = rig.run({
        **BODY, "multi_prompts_gen_type": 3, "video_prompt_type": "V",
        "prompt": BOUNDARY.join(["open on the pier", "a gull lands\nthe gull looks up", "close on the sea"]),
        "image_start": "start.png", "image_end": ["", "end-b.png", ""], "per_clip_frames": [17, 25, 9],
        "per_clip_seeds": [1, "not a seed", 3], "per_clip_keyframes": [None, ["kf-1.png", "kf-2.png"], []],
        "per_clip_minimax_h3_references": [{"refs": ["a"]}, {"refs": ["b"]}, {"refs": []}],
        "per_clip_continue_from_previous": [False, False, True], "_se_preserve_duration_per_clip": True,
        "audio_frame_offset": "not a number",
    })
    rig.check(golden, "multi clip, bounded director", {**rig.observe(job_id), "decord reads": reads})


def test_a_bounded_clip_off_the_models_frame_lattice_fails_the_job_before_any_model_work(rig, golden) -> None:
    _bounded_model(rig)
    job_id = rig.run({**BODY, "multi_prompts_gen_type": 3, "prompt": "one\ntwo", "per_clip_frames": [17, 20]})
    rig.check(golden, "multi clip, off the frame lattice", rig.observe(job_id))


def test_a_kept_se_duration_rounds_up_to_the_models_latent_grid(rig, golden) -> None:
    """On a lattice that is a multiple of the latent size (16, 24, ...), keeping the visible duration of an SE clip
    adds one conditioning step and rounds up to the grid: 24 visible frames are generated as 25."""
    _bounded_model(rig, frames_minimum=16, frames_maximum=40)
    job_id = rig.run({**BODY, "multi_prompts_gen_type": 3, "prompt": "walk in\nstop at the door", "per_clip_frames": [16, 24],
                      "image_end": ["", "door.png"], "_se_preserve_duration_per_clip": True})
    rig.check(golden, "multi clip, kept SE duration on a latent-multiple lattice", rig.observe(job_id))


def test_a_single_clip_with_an_end_image_trims_its_tail_and_names_its_uploads(rig, golden) -> None:
    job_id = rig.run({**BODY, "image_start": "uploads/start.png", "image_end": "uploads/end.png",
                      "image_prompt_type": "SE"})
    rig.check(golden, "single clip with an end image", rig.observe(job_id))


def test_a_shot_manifest_keeps_its_own_shot_indexes_and_hands_back_the_joined_file(rig, golden) -> None:
    def script(call) -> None:
        call.save()
        if call.index == 1:
            call.save(suffix="_multiclip")

    rig.engine.script = script
    shots = [{"shot_index": 3, "params": {"prompt": "shot three"}}, {"shot_index": 7, "params": {"prompt": "shot seven"}}]
    job_id = rig.direct_job({**BODY, "_repaint_shot_manifest": shots, "_defer_output_publication": True})
    rig.call_worker(job_id, finalize=False)
    rig.check(golden, "shot manifest with its own indexes and a joined file", rig.observe(job_id))


# -- outputs and sidecars ---------------------------------------------------------------------------------------------
def test_a_director_clip_sidecar_names_its_pipeline_and_the_prompts_the_model_saw(rig, golden) -> None:
    def script(call) -> None:
        call.gen["model_prompts"] = {"0": "a calm lake, window one"}
        call.save()

    rig.engine.script = script
    job_id = rig.direct_job({**BODY, "_director_pipeline_id": "pipeline-golden"})
    rig.call_worker(job_id)
    rig.check(golden, "director clip with model prompts", rig.observe(job_id))


def test_clips_registered_only_as_artifacts_are_bound_to_their_own_clips(rig, golden, monkeypatch) -> None:
    """WanGP lists a file in ``artifact_list`` as soon as it is written and in ``file_list`` only later. A clip whose
    engine failed in between still owns its file; a clip that wrote nothing gets none of the others'."""
    _install_fake_decord(monkeypatch)

    def script(call) -> None:
        if call.index == 1:
            raise RuntimeError("the second clip failed before writing anything")
        call.save(register="artifact")
        if call.index == 2:
            raise RuntimeError("the third clip failed after writing its file")

    rig.engine.script = script
    job_id = rig.run(MULTI_CLIP)
    rig.check(golden, "multi clip registered only as artifacts", rig.observe(job_id))


def test_the_legacy_fallback_does_not_claim_a_file_that_was_there_before_the_job(rig, golden, clip) -> None:
    shutil.copyfile(clip, rig.server.outputs / "older_render.mp4")
    rig.engine.script = lambda call: call.save(register=False)
    job_id = rig.run(BODY)
    rig.check(golden, "unregistered output beside an older file", rig.observe(job_id))


def test_a_failed_clip_is_failed_even_when_the_caller_finalizes_the_job_itself(rig, golden) -> None:
    def script(call) -> None:
        raise RuntimeError("the clip failed")

    rig.engine.script = script
    job_id = rig.direct_job(BODY)
    rig.call_worker(job_id, finalize=False)
    rig.check(golden, "failed clip, not finalized", rig.observe(job_id))


# -- finishing passes -------------------------------------------------------------------------------------------------
def _voice_clone_stub(monkeypatch, seen: list, *, fail: bool = False) -> None:
    def voice_clone(video_path, voice_ref_paths, mode):
        seen.append(["voice clone", Path(video_path).name, [Path(ref).name for ref in voice_ref_paths], mode])
        if fail:
            raise RuntimeError("no voice in this clip")

    monkeypatch.setitem(sys.modules, "postprocessing.voice_clone", SimpleNamespace(apply_voice_clone_to_file=voice_clone))


def test_voice_clone_references_resolve_in_the_jobs_own_workspace(rig, golden, monkeypatch) -> None:
    assert rig.server.client.post("/api/v1/workspaces", json={"name": "golden-ws"}).status_code == 200
    media.sound(rig.server.outputs / "golden-ws" / "narrator.wav")
    seen: list = []
    _voice_clone_stub(monkeypatch, seen)
    job_id = rig.run({**BODY, "workspace": "golden-ws", "voice_clone_enabled": True, "voice_clone_refs": ["narrator.wav"]})
    rig.check(golden, "voice clone with a workspace reference",
              {**rig.observe(job_id, workspace="golden-ws"), "voice clone": seen})


def test_post_processing_visits_every_video_and_survives_a_failing_pass(rig, golden, tmp_path, monkeypatch) -> None:
    """Two videos and a sound: each video pass skips the sound, the audio pass skips the videos, and a pass that
    raises (or an ffmpeg that fails) leaves that file as it was and the job completed."""
    media.sound(tmp_path / "uploads" / "audio" / "voice.wav")
    order: list = []

    def script(call) -> None:
        call.save()
        call.save()
        call.save("audio", suffix="_soundtrack")  # its own stem: a sidecar is named after the media file's stem

    def upscale(path, method, job=None):
        order.append(["upscale", Path(path).name, method, job["id"] if job else None])
        if "(2)" in Path(path).name:
            raise RuntimeError("upscaler out of memory")

    rig.engine.script = script
    rig.patch("_apply_spatial_upsampling_to_file", upscale)
    rig.patch("_apply_film_grain_to_file", lambda path, intensity, saturation: order.append(["film grain", Path(path).name]))
    _voice_clone_stub(monkeypatch, order, fail=True)
    commands: list = []
    real_run = subprocess.run

    def failing_ffmpeg(command, *args, **kwargs):
        if "-af" in command:
            commands.append(list(command))
            return subprocess.CompletedProcess(command, 1, "", "fake ffmpeg: no acompressor")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", failing_ffmpeg)
    job_id = rig.run({**BODY, "film_grain_intensity": 0.4, "spatial_upsampling": "flashvsr_x2", "voice_clone_enabled": True,
                      "voice_clone_refs": ["audio/voice.wav"], "tts_dynaudnorm": True})
    rig.check(golden, "post-processing on several outputs", {**rig.observe(job_id), "order": order, "ffmpeg": commands})


def test_a_cancel_during_post_processing_stops_the_remaining_passes(rig, golden) -> None:
    launch = rig.launch
    order: list = []

    def upscale(path, method, job=None):
        order.append(["upscale", Path(path).name])
        launch.request_cancel(job, job_id=job["id"], active_states=launch._active_gen_states)

    rig.patch("_apply_spatial_upsampling_to_file", upscale)
    rig.patch("_apply_film_grain_to_file", lambda path, intensity, saturation: order.append(["film grain", Path(path).name]))
    job_id = rig.run({**BODY, "repeat_generation": 2, "spatial_upsampling": "flashvsr_x2", "film_grain_intensity": 0.4})
    rig.check(golden, "cancel during post-processing", {**rig.observe(job_id), "order": order})


def test_a_failed_job_runs_no_finishing_pass_on_the_outputs_it_keeps(rig, clip, tmp_path, monkeypatch) -> None:
    """The engine saves a video and a sound, then fails: the job fails (it is not cancelled) and keeps both files.
    Every finishing pass (outpaint, Recast protection, FlashVSR, film grain, voice clone, audio normalisation) runs
    only for a job that succeeded, so none of them touches the kept files."""
    media.sound(tmp_path / "uploads" / "audio" / "voice.wav")
    source = tmp_path / "finishing-source.mp4"
    shutil.copyfile(clip, source)
    ran: list = []

    def script(call) -> None:
        call.save()
        call.save("audio", suffix="_soundtrack")
        raise RuntimeError("fake engine died after saving")

    real_run = subprocess.run

    def media_tools(command, *args, **kwargs):
        if list(command)[0] in ("ffmpeg", "ffprobe"):
            ran.append(list(command)[0])
            return subprocess.CompletedProcess(command, 1, "", "the test runs no media tool")
        return real_run(command, *args, **kwargs)

    rig.engine.script = script
    monkeypatch.setattr(subprocess, "run", media_tools)
    rig.set_wgp("wan_model", SimpleNamespace(name="resident model"))
    rig.set_wgp("release_model", lambda: ran.append("release model"))
    rig.patch("_build_recast_adaptive_mask", lambda *args, **kwargs: ran.append("trace"))
    rig.patch("_render_recast_mask_locked_video", lambda *args, **kwargs: ran.append("render"))
    rig.patch("_apply_spatial_upsampling_to_file", lambda path, method, job=None: ran.append("upscale"))
    rig.patch("_apply_film_grain_to_file", lambda path, intensity, saturation: ran.append("film grain"))
    _voice_clone_stub(monkeypatch, ran)
    job_id = rig.direct_job({**BODY, "_outpaint_source_video": str(source), "_outpaint_preserve_audio": True,
                             "_recast_protect_bystanders": True, "_recast_source_video": str(source),
                             "video_mask": "uploads/recast-mask.mp4", "spatial_upsampling": "flashvsr_x2",
                             "film_grain_intensity": 0.4, "voice_clone_enabled": True,
                             "voice_clone_refs": ["audio/voice.wav"], "tts_dynaudnorm": True})
    assert rig.call_worker(job_id) is False
    job = rig.launch._jobs[job_id]
    assert job["status"] == "failed" and not job.get("cancel_requested")
    assert len(job["output_files"]) == 2
    assert ran == []


def _instant_retries(rig) -> None:
    """The worker retries a file Windows holds open 15 times, a second apart; the test does not wait for them."""
    real = rig.launch.time
    proxy = types.ModuleType("time")
    proxy.__dict__.update({name: getattr(real, name) for name in dir(real) if not name.startswith("__")})
    proxy.sleep = lambda _seconds: None
    rig.patch("time", proxy)


def _locked_destination(monkeypatch, source_end: str, fallback_end: str) -> list:
    """``os.replace`` of a file ending in ``source_end`` fails as on Windows when the UI streams the destination,
    except into the worker's fallback name (ending in ``fallback_end``). Returns the refused destinations."""
    refused: list = []
    real = os.replace

    def replace(source, destination, *args, **kwargs):
        if str(source).endswith(source_end) and not str(destination).endswith(fallback_end):
            refused.append(Path(destination).name)
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", replace)
    return refused


def _outpaint_tools(monkeypatch, source: Path, *, source_audio: bool, mux_ok: bool) -> list:
    """ffprobe and ffmpeg for the outpaint pass (the commands are the worker's contract, the encoders are not);
    every other command runs for real. Returns the commands the pass ran."""
    commands: list = []
    real_run = subprocess.run

    def run(command, *args, **kwargs):
        command = list(command)
        if command[0] == "ffprobe" and str(source) in command:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "audio\n" if source_audio else "", "")
        if command[0] == "ffprobe" and "stream=r_frame_rate" in command:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, "8/1\n", "")
        if command[0] == "ffmpeg" and str(source) in command:
            commands.append(command)
            if not mux_ok:
                return subprocess.CompletedProcess(command, 1, "", "fake ffmpeg: unknown encoder")
            shutil.copyfile(command[3], command[-1])
            return subprocess.CompletedProcess(command, 0, "", "")
        return real_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run)
    return commands


OUTPAINT_CASES = {
    "source audio": {"_outpaint_preserve_audio": True},
    "smear trim": {"_outpaint_preserve_audio": True, "_outpaint_trim_smear": True, "_outpaint_smear_boundary_frame": 5,
                   "_outpaint_smear_count": 3},
    "feathered overlay": {"_outpaint_lock_source_pixels": True, "_outpaint_overlay_x": 8, "_outpaint_overlay_w": 48,
                          "_outpaint_overlay_h": 36, "_outpaint_canvas_w": 64, "_outpaint_canvas_h": 36},
    "full-frame overlay": {"_outpaint_lock_source_pixels": True, "_outpaint_overlay_w": 64, "_outpaint_overlay_h": 36},
    "nothing to do": {"_outpaint_preserve_audio": True, "_outpaint_lock_source_pixels": True},
    "ffmpeg fails": {"_outpaint_preserve_audio": True},
    "output locked": {"_outpaint_preserve_audio": True, "film_grain_intensity": 0.4},
}


@pytest.mark.parametrize("case", list(OUTPAINT_CASES))
def test_the_outpaint_finishing_pass_runs_once_on_the_last_video(rig, golden, clip, tmp_path, monkeypatch, case) -> None:
    """Source-audio mux, smear trim and source-pixel overlay are one ffmpeg call on the last canonical video. When
    Windows holds the output open, the post-processed copy is published under a new name, and the later passes and
    sidecars follow that name."""
    source = tmp_path / "outpaint-source.mp4"
    shutil.copyfile(clip, source)
    tools = _outpaint_tools(monkeypatch, source, source_audio=case != "nothing to do", mux_ok=case != "ffmpeg fails")
    refused: list = []
    graded: list = []
    if case == "output locked":
        _instant_retries(rig)
        refused = _locked_destination(monkeypatch, "_post.mp4", "_with_source_audio.mp4")
        rig.patch("_apply_film_grain_to_file", lambda path, intensity, saturation: graded.append(Path(path).name))
    job_id = rig.direct_job({**BODY, "repeat_generation": 2, "_outpaint_source_video": str(source),
                             **OUTPAINT_CASES[case]})
    rig.call_worker(job_id)
    rig.check(golden, f"outpaint finishing pass: {case}", {**rig.observe(job_id), "tools": tools,
                                                           "locked replace attempts": len(refused), "film grain": graded})


@pytest.mark.parametrize("case", ["protected", "output locked", "cancelled", "tracing fails"])
def test_recast_protection_restores_the_people_outside_the_replacement(rig, golden, clip, tmp_path, monkeypatch,
                                                                       case) -> None:
    """After a Recast the worker frees the resident model, traces the generated replacement (SAM3, stubbed), renders
    the source back outside it and swaps the result in. A lock publishes it under a new name, a cancel stops it, and
    a tracing failure keeps the generated video."""
    launch = rig.launch
    source = tmp_path / "recast-source.mp4"
    shutil.copyfile(clip, source)
    calls: list = []
    job_id = rig.direct_job({**BODY, "repeat_generation": 2, "_recast_protect_bystanders": True,
                             "_recast_source_video": str(source), "video_mask": "uploads/recast-mask.mp4",
                             "edit_recast_person_count": 2})
    rig.set_wgp("wan_model", SimpleNamespace(name="resident model"))
    rig.set_wgp("release_model", lambda: calls.append(["release model"]))

    def trace(generated_video, mask_video, person_count, out_dir, progress_callback=None):
        calls.append(["trace", Path(generated_video).name, mask_video, person_count,
                      Path(out_dir).name.startswith("maestro-recast-protect-")])
        if case == "tracing fails":
            raise RuntimeError("SAM3 found nobody to trace")
        if case == "cancelled":
            launch.request_cancel(launch._jobs[job_id], job_id=job_id, active_states=launch._active_gen_states)
        for done in (1, 2, 2, 4):
            progress_callback(done, 4)
        return str(Path(out_dir) / "adaptive-mask.mp4")

    def render(source_video, adaptive_mask, generated_video):
        calls.append(["render", Path(source_video).name, Path(adaptive_mask).name, Path(generated_video).name])
        protected = Path(generated_video).with_name("protected-render.mp4")
        protected.write_bytes(b"protected")
        return str(protected)

    rig.patch("_build_recast_adaptive_mask", trace)
    rig.patch("_render_recast_mask_locked_video", render)
    refused: list = []
    if case == "output locked":
        _instant_retries(rig)
        refused = _locked_destination(monkeypatch, "protected-render.mp4", "_target_locked.mp4")
    rig.call_worker(job_id)
    rig.check(golden, f"recast protection: {case}", {**rig.observe(job_id), "calls": calls,
                                                     "locked replace attempts": len(refused)})


# -- oddities the goldens above already pin, one fact each ------------------------------------------------------------
def test_oddity_a_finished_job_leaves_the_audio_save_path_in_its_workspace(rig) -> None:
    """The ``finally`` block points ``save_path`` and ``image_save_path`` back at the active workspace but leaves
    ``audio_save_path`` at the last job's folder."""
    assert rig.server.client.post("/api/v1/workspaces", json={"name": "golden-ws"}).status_code == 200
    rig.run({**BODY, "workspace": "golden-ws"})
    wgp, outputs = rig.server.wgp, str(rig.server.outputs)
    assert (wgp.save_path, wgp.image_save_path, wgp.audio_save_path) == (outputs, outputs, str(rig.server.outputs / "golden-ws"))


def test_oddity_a_cancelled_task_keeps_its_timer_running(rig) -> None:
    """The task loop breaks out on a cancel before it finishes the task's timer, so the timer still reads running."""
    release = rig.event()
    rig.engine.script = hold_then(release=release, ignore_abort=True)
    job_id = rig.post(BODY)["job_id"]
    assert rig.engine.entered.wait(WAIT)
    rig.wait_for(job_id, message="Sampling | 1/2")
    rig.cancel(job_id)
    release.set()
    rig.join()
    status = rig.get(f"/api/v1/status/{job_id}")
    assert status["status"] == "cancelled"
    assert [timer["status"] for timer in status["task_timings"]] == ["running"]


def test_oddity_tts_seconds_progress_is_overwritten_by_the_step_ratio(rig) -> None:
    """``12/600 s`` is parsed into "Generating audio... 12s" at 36%, and then the step/total branch below it
    overwrites that: the job shows the tuple's own step (1/10, 10%) and the model's message."""
    rig.engine.script = lambda call: (call.send("progress", [(1, 10), "Generating | 12/600 s"]), call.save())
    job_id = rig.run(BODY)
    writes = [event for event in rig.events if event.get("id") == job_id]
    progress = next(event for event in writes if event.get("message") == "Generating | 12/600 s")
    assert (progress["progress"], progress["step"], progress["total_steps"]) == (10, 1, 10)
    assert not any("Generating audio" in str(event.get("message")) for event in writes)


def _recording_publisher(rig) -> list:
    handed: list = []
    real = rig.launch._publish_generation_sidecar_for_studio_job

    def publish(job, output_path, sidecar, **kwargs):
        handed.append({"file": Path(output_path).name, "job_id": sidecar.get("job_id")})
        return real(job, output_path, sidecar, **kwargs)

    rig.patch("_publish_generation_sidecar_for_studio_job", publish)
    return handed


def test_oddity_a_successful_job_publishes_each_sidecar_twice(rig) -> None:
    """Once when the outputs are recorded and again after the (here empty) post-processing passes."""
    handed = _recording_publisher(rig)
    job_id = rig.run(BODY)
    assert [item["job_id"] for item in handed] == [job_id, job_id]
    assert len({item["file"] for item in handed}) == 1


def test_oddity_the_sound_effect_sidecar_reads_a_job_id_key_jobs_do_not_have(rig, monkeypatch) -> None:
    """``_run_sfx_generation`` puts ``job.get("job_id", "")`` in the sidecar, but jobs keep their id under ``id``:
    the publisher receives an empty id and fills it in."""
    _stub_mmaudio(rig, monkeypatch)
    handed = _recording_publisher(rig)
    job_id = rig.run(SFX_BODY)
    assert [item["job_id"] for item in handed] == [""]
    (sidecar,) = rig.sidecars().values()
    assert sidecar["job_id"] == job_id


# -- post-processing passes the worker tests never enter -------------------------------------------------------------
def _masked_argv(command) -> list[str]:
    """Flags stay; absolute paths do not, so a golden does not carry this machine's temp directory."""
    return ["<PATH>" if os.path.isabs(str(part)) else str(part) for part in command]


def _file_mark(path: Path) -> str:
    return {
        b"ORIGINAL": "original",
        b"SOURCE": "source",
        b"GRAIN": "grain",
        b"MUXED": "muxed",
        b"SEGMENT": "segment",
        b"JOINED": "joined",
    }.get(path.read_bytes(), f"other:{path.stat().st_size}")


def _extras(folder: Path, source: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir() if path.name != source.name)


_FLASH_KEYS = ("flashvsr_mode", "flashvsr_topk_ratio", "flashvsr_backend", "flashvsr_persistence")


def _prepare_flashvsr(rig, monkeypatch, *, fps: float, width: int, height: int, frames: int,
                      variant: str, expect_ffmpeg: bool, stop_at: str | None) -> dict:
    """Stub everything ``_chunked_flashvsr_upscale`` touches except its own chunking and persistence.

    ``get_video_info`` reports ``width`` x ``height`` so the chunk-size formula runs for real, while the
    frames handed back are 2x2. A long 4000-pixel ``tiny`` clip therefore still chunks, without allocating
    the output buffer the formula is there to avoid.
    """
    import torch
    from shared.utils import utils as video_utils

    try:
        import postprocessing.flashvsr.runtime  # noqa: F401
    except ModuleNotFoundError:
        # The CI core install has no easydict, which the real runtime imports through models.wan. The function
        # under test reads one constant from that module (the overlap), so a stand-in with the same value is enough.
        monkeypatch.setitem(
            sys.modules, "postprocessing.flashvsr.runtime", SimpleNamespace(FLASHVSR_CONTINUE_CACHE_FRAMES=11)
        )

    notes: dict = {"reads": [], "saves": [], "upscales": [], "messages": [], "commands": [], "releases": 0,
                   "persistence_during": []}

    monkeypatch.setattr(video_utils, "get_video_info", lambda _path: (fps, width, height, frames))

    def get_resampled_video(_path, start, count, got_fps):
        notes["reads"].append({"start": start, "count": count, "fps": got_fps})
        take = min(int(count), max(0, frames - int(start)))
        if take <= 0:
            return None
        return torch.zeros((take, 2, 2, 3), dtype=torch.uint8)

    def save_video(**kwargs):
        tensor = kwargs["tensor"]
        Path(kwargs["save_file"]).write_bytes(b"SEGMENT")
        notes["saves"].append({
            "file": Path(kwargs["save_file"]).name,
            "fps": kwargs["fps"],
            "nrow": kwargs["nrow"],
            "normalize": kwargs["normalize"],
            "value_range": list(kwargs["value_range"]) if "value_range" in kwargs else None,
            "codec_type": kwargs["codec_type"],
            "container": kwargs["container"],
            "shape": list(tensor.shape),
            "dtype": str(tensor.dtype),
        })

    def upscale(seg, method, **kwargs):
        notes["persistence_during"].append(rig.server.wgp.server_config.get("flashvsr_persistence"))
        notes["upscales"].append({
            "method": method,
            "frames": int(seg.shape[1]),
            "in_shape": list(seg.shape),
            "in_dtype": str(seg.dtype),
            "continue_cache": kwargs.get("continue_cache") is not None,
            "return_continue_cache": kwargs.get("return_continue_cache"),
            "profile": kwargs.get("profile"),
            "seed": kwargs.get("seed"),
            "still_image": kwargs.get("still_image"),
            "process_files": kwargs.get("process_files"),
            "vae_config": kwargs.get("vae_config"),
            "init_pipe": kwargs.get("init_pipe"),
        })
        produced = int(seg.shape[1])
        return torch.zeros((3, produced, 2, 2), dtype=torch.float32), {"n": len(notes["upscales"])}

    def run(command, *args, **kwargs):
        argv = _masked_argv(command)
        notes["commands"].append(argv)
        if not expect_ffmpeg:
            raise AssertionError(f"ffmpeg was called: {argv}")
        if argv[0] != "ffmpeg":
            raise AssertionError(argv[0])
        Path(list(command)[-1]).write_bytes(b"JOINED")
        return subprocess.CompletedProcess(list(command), 0, "", "")

    # A class body does not see this function's locals, so the callable is attached afterwards.
    flash = SimpleNamespace(
        PERSIST_RAM=2, PERSIST_UNLOAD=1,
        scale_for_upsampling=lambda _method: 2.0,
        settings=lambda: (True, variant, 1),
        upscale=upscale,
    )
    rig.set_wgp("flashvsr", flash)
    rig.set_wgp("get_resampled_video", get_resampled_video)
    rig.set_wgp("save_video", save_video)
    rig.set_wgp("loaded_profile", 4)
    rig.set_wgp("process_files_def", "process-files")
    rig.set_wgp("vae_config", {"tile": 0})
    rig.set_wgp("init_pipe", "init-pipe")
    rig.set_wgp("release_flashvsr_vram", lambda: notes.__setitem__("releases", notes["releases"] + 1))
    monkeypatch.setattr(subprocess, "run", run)

    def update_job(_job, **changes):
        message = changes.get("message")
        notes["messages"].append(message)
        if stop_at and isinstance(message, str) and message.startswith(stop_at):
            return False
        return True

    rig.patch("update_job", update_job)
    services = dict(rig.server.wgp.server_config.get("services") or {})
    services.update(flashvsr_mode=3, flashvsr_topk_ratio=1.5, flashvsr_backend="sparge")
    monkeypatch.setitem(rig.server.wgp.server_config, "services", services)
    return notes


def _clear_flash_keys(config: dict) -> None:
    """The upscale copies settings onto the shared fake and forces persistence; leave neither behind."""
    for key in _FLASH_KEYS:
        config.pop(key, None)


_FILM_GRAIN = ["silent rewrite", "audio mux", "cuda oom fallback", "unreadable video"]


@pytest.mark.parametrize("case", _FILM_GRAIN)
def test_film_grain_rewrites_the_file_and_restores_the_decord_bridge(rig, golden, tmp_path, monkeypatch, case) -> None:
    """The real grain pass re-encodes in place, muxes audio back when the source has it, falls back to CPU on
    a CUDA out-of-memory, and puts decord's bridge back to ``native`` even when the reader cannot open the file."""
    import torch

    assert not torch.cuda.is_available()
    folder = tmp_path / "grain"
    folder.mkdir()
    source = folder / "clip.mp4"
    source.write_bytes(b"ORIGINAL")
    bridge_calls: list[str] = []
    grain: list[dict] = []
    saves: list[dict] = []
    commands: list[list[str]] = []

    class _Bridge:
        current = "native"

        def set_bridge(self, name: str) -> None:
            bridge_calls.append(name)
            self.current = name

    class _Reader:
        def __init__(self, _path: str) -> None:
            if case == "unreadable video":
                raise RuntimeError("cannot open this video")

        def get_avg_fps(self) -> float:
            return 23.6

        def __len__(self) -> int:
            return 2

        def get_batch(self, _index):
            return torch.zeros((2, 4, 6, 3), dtype=torch.uint8)

    bridge = _Bridge()
    monkeypatch.setitem(sys.modules, "decord", SimpleNamespace(bridge=bridge, VideoReader=_Reader))
    monkeypatch.setattr(tempfile, "mktemp", lambda suffix="": str(folder / f"extracted{suffix}"))

    def add_film_grain(frames, intensity, saturation):
        grain.append({
            "device": str(frames.device),
            "dtype": str(frames.dtype),
            "shape": list(frames.shape),
            "intensity": intensity,
            "saturation": saturation,
        })
        if case == "cuda oom fallback" and len(grain) == 1:
            raise torch.cuda.OutOfMemoryError("out of memory")
        return torch.full_like(frames, 7)

    def save_video(**kwargs):
        tensor = kwargs["tensor"]
        Path(kwargs["save_file"]).write_bytes(b"GRAIN")
        saves.append({
            "file": Path(kwargs["save_file"]).name,
            "fps": kwargs["fps"],
            "nrow": kwargs["nrow"],
            "normalize": kwargs["normalize"],
            "codec_type": kwargs["codec_type"],
            "container": kwargs["container"],
            "shape": list(tensor.shape),
            "dtype": str(tensor.dtype),
        })

    def run(command, *args, **kwargs):
        argv = list(command)
        commands.append(_masked_argv(argv))
        if argv[0] == "ffprobe":
            stdout = "audio\n" if case == "audio mux" else ""
            return subprocess.CompletedProcess(argv, 0, stdout, "")
        if argv[0] == "ffmpeg":
            Path(argv[-1]).write_bytes(b"MUXED" if "-c:a" in argv else b"AAC")
            return subprocess.CompletedProcess(argv, 0, "", "")
        raise AssertionError(argv[0])

    monkeypatch.setattr("postprocessing.film_grain.add_film_grain", add_film_grain)
    monkeypatch.setattr("shared.utils.audio_video.save_video", save_video)
    monkeypatch.setattr(subprocess, "run", run)

    returned = None
    error = None
    try:
        returned = rig.launch._apply_film_grain_to_file(str(source), 0.4, 0.7)
    except RuntimeError as exc:
        error = str(exc)

    if case == "unreadable video":
        assert error == "cannot open this video" and grain == [] and saves == []
        assert _file_mark(source) == "original"
    elif case == "cuda oom fallback":
        assert error is None and returned is None and len(grain) == 2
        assert [item["device"] for item in grain] == ["cpu", "cpu"]
        assert _file_mark(source) == "grain"
    elif case == "audio mux":
        assert error is None and _file_mark(source) == "muxed" and len(commands) == 3
        assert commands[1][commands[1].index("-vn") + 1:commands[1].index("-vn") + 3] == ["-acodec", "copy"]
        assert "-shortest" in commands[2] and commands[2][commands[2].index("-c:a") + 1] == "aac"
    else:
        assert error is None and _file_mark(source) == "grain" and len(grain) == 1 and len(commands) == 1
    assert bridge_calls == ["torch", "native"] and bridge.current == "native" and _extras(folder, source) == []
    if saves:
        assert saves[0]["fps"] == 24 and saves[0]["codec_type"] == "libx264_8" and saves[0]["container"] == "mp4"
        assert saves[0]["normalize"] is False and saves[0]["shape"] == [1, 3, 2, 4, 6]
    rig.check(golden, f"film grain: {case}", {
        "bridge": bridge_calls,
        "bridge_after": bridge.current,
        "grain": grain,
        "saves": saves,
        "commands": commands,
        "file": _file_mark(source),
        "leftovers": _extras(folder, source),
        "error": error,
        "returned": returned,
    })


_FLASH_CASES = ["three chunks", "persistence already resident", "aborted before the first frame",
                "stopped on the second chunk"]


@pytest.mark.parametrize("case", _FLASH_CASES)
def test_chunked_flashvsr_upscale_chunks_a_long_clip_and_restores_persistence(rig, golden, tmp_path, monkeypatch,
                                                                             case) -> None:
    """A 100-frame 4000-pixel ``tiny`` clip is three 49-frame chunks with an 11-frame overlap, joined by ffmpeg.
    Persistence is forced to resident for the call and put back afterwards, and an abort leaves no segment files."""
    folder = tmp_path / "flash"
    folder.mkdir()
    source = folder / "long.mp4"
    source.write_bytes(b"SOURCE")
    config = rig.server.wgp.server_config
    notes = _prepare_flashvsr(
        rig, monkeypatch, fps=8.9, width=4000, height=4000, frames=100, variant="tiny",
        expect_ffmpeg=case in ("three chunks", "persistence already resident"),
        stop_at="Upscaling chunk 2/" if case == "stopped on the second chunk" else None,
    )
    if case == "persistence already resident":
        monkeypatch.setitem(config, "flashvsr_persistence", rig.server.wgp.flashvsr.PERSIST_RAM)
    try:
        result = rig.launch._chunked_flashvsr_upscale(
            str(source), "flashvsr2", job={"id": "flash-job"},
            abort_check=(lambda: True) if case == "aborted before the first frame" else None,
        )
        copied = {key: config.get(key) for key in ("flashvsr_mode", "flashvsr_topk_ratio", "flashvsr_backend")}
        persistence_after = config.get("flashvsr_persistence")
        if case in ("three chunks", "persistence already resident"):
            assert notes["reads"] == [
                {"start": 0, "count": 49, "fps": 8.9},
                {"start": 38, "count": 60, "fps": 8.9},
                {"start": 87, "count": 60, "fps": 8.9},
            ]
            assert [item["frames"] for item in notes["upscales"]] == [49, 60, 13]
            assert [item["return_continue_cache"] for item in notes["upscales"]] == [True, True, False]
            assert notes["persistence_during"] == [2, 2, 2]
            assert _file_mark(Path(result)) == "joined" and _file_mark(source) == "source"
            assert len(notes["commands"]) == 1 and notes["commands"][0][1:8] == ["-y", "-f", "concat", "-safe", "0", "-i", "<PATH>"]
        elif case == "aborted before the first frame":
            assert result is None and notes["reads"] == [] and notes["upscales"] == [] and _extras(folder, source) == []
        else:
            assert result is None and len(notes["reads"]) == 2 and len(notes["upscales"]) == 1
            assert notes["messages"] == [
                "Upscaling chunk 1/3 (FlashVSR)...",
                "Upscaling chunk 2/3 (FlashVSR)...",
            ]
            assert _extras(folder, source) == []
        if case == "persistence already resident":
            assert notes["releases"] == 0 and persistence_after == 2
        else:
            assert notes["releases"] == 1 and persistence_after == 1
        assert copied == {"flashvsr_mode": 3, "flashvsr_topk_ratio": 1.5, "flashvsr_backend": "sparge"}
        rig.check(golden, f"flashvsr chunks: {case}", {
            "reads": notes["reads"],
            "upscales": notes["upscales"],
            "saves": notes["saves"],
            "messages": notes["messages"],
            "commands": notes["commands"],
            "persistence_during": notes["persistence_during"],
            "persistence_after": persistence_after,
            "released": notes["releases"],
            "settings_copied": copied,
            "returned": None if result is None else Path(result).name,
            "returned_bytes": None if result is None else _file_mark(Path(result)),
            "source": _file_mark(source),
            "leftovers": _extras(folder, source),
        })
    finally:
        _clear_flash_keys(config)


_SPATIAL_CASES = ["keeps the audio", "silent clip", "cancelled before upscale"]


@pytest.mark.parametrize("case", _SPATIAL_CASES)
def test_spatial_upsampling_replaces_the_file_and_keeps_its_audio(rig, golden, tmp_path, monkeypatch, case) -> None:
    """The real spatial pass upscales through the chunked function, muxes the original audio back, and replaces
    the file. A cancel before the first frame leaves the file untouched and still cleans the extracted tracks."""
    folder = tmp_path / "spatial"
    folder.mkdir()
    source = folder / "spatial.mp4"
    source.write_bytes(b"ORIGINAL")
    config = rig.server.wgp.server_config
    notes = _prepare_flashvsr(
        rig, monkeypatch, fps=8.9, width=16, height=16, frames=8, variant="tiny",
        expect_ffmpeg=False, stop_at=None,
    )
    audio = case != "silent clip"
    extracted: list = []

    def extract_audio_tracks(_path):
        extracted.append(Path(_path).name)
        if audio:
            return ["guide.aac"], {"codec": "aac"}
        return [], None

    def combine_video_with_audio_tracks(_video, tracks, dest, audio_metadata=None):
        notes.setdefault("combine", []).append({"tracks": list(tracks), "metadata": audio_metadata})
        Path(dest).write_bytes(b"MUXED")

    def cleanup_temp_audio_files(tracks):
        notes.setdefault("cleaned", []).append(list(tracks) if tracks else [])

    rig.set_wgp("extract_audio_tracks", extract_audio_tracks)
    rig.set_wgp("combine_video_with_audio_tracks", combine_video_with_audio_tracks)
    rig.set_wgp("cleanup_temp_audio_files", cleanup_temp_audio_files)
    job = {"id": "spatial-job", "status": "running", "cancel_requested": case == "cancelled before upscale"}
    try:
        error = None
        try:
            rig.launch._apply_spatial_upsampling_to_file(str(source), "flashvsr2", job)
        except RuntimeError as exc:
            error = str(exc)
        if case == "keeps the audio":
            assert error is None and _file_mark(source) == "muxed" and notes["combine"] == [
                {"tracks": ["guide.aac"], "metadata": {"codec": "aac"}},
            ]
        elif case == "silent clip":
            assert error is None and _file_mark(source) == "segment" and "combine" not in notes
        else:
            assert error == "FlashVSR upscale was aborted" and _file_mark(source) == "original"
            assert notes["reads"] == [] and "combine" not in notes
        assert extracted == ["spatial.mp4"]
        assert notes["cleaned"] == [["guide.aac"] if audio else []]
        assert _extras(folder, source) == []
        assert notes["releases"] == 1 and config.get("flashvsr_persistence") == 1
        rig.check(golden, f"spatial upsampling: {case}", {
            "error": error,
            "file": _file_mark(source),
            "extracted": extracted,
            "combine": notes.get("combine", []),
            "cleaned": notes["cleaned"],
            "reads": notes["reads"],
            "upscales": notes["upscales"],
            "saves": notes["saves"],
            "commands": notes["commands"],
            "messages": notes["messages"],
            "persistence_after": config.get("flashvsr_persistence"),
            "released": notes["releases"],
            "leftovers": _extras(folder, source),
        })
    finally:
        _clear_flash_keys(config)


# -- the per-job VRAM coefficient, value by value (C4 review) ------------------------------------------------------
# The worker test above pins that the coefficient is applied for the job and put back, not the value. These call the
# launch name with one job at a time and record every number it computes, the reason lines it prints and what it
# leaves on the engine, then put the base back as the worker's ``finally`` block does.
_LORA_SIZES = {"style.safetensors": 1_610_612_736, "detail.safetensors": 402_653_184}
_VIDEO = {"model_type": "fake_t2v", "resolution": "1280x720", "video_length": 241}
_H3_OMNI = {"architecture": "minimax_h3_fake", "omni_reference": True, "minimax_h3_transformer_working_vram_gb": 6.0}
_H3_REFERENCES = [{"type": "video"}, {"kind": "Video"}, {"type": "image"}, "not a dict"]
_COEFFICIENT_CASES = {
    "loras and a progressive pipeline": {
        "params": {**_VIDEO, "activated_loras": [*_LORA_SIZES, "missing.safetensors", ""], "progressive_pipeline": True}},
    "image mode": {"params": {"model_type": "fake_t2v", "image_mode": 1, "resolution": "1024x1024", "video_length": 1}},
    "outpaint refine": {"params": {**_VIDEO, "outpaint_full_resolution_refine": True, "single_stage_pipeline": True}},
    "single stage": {"params": {**_VIDEO, "single_stage_pipeline": True}},
    "sliding window clamp": {"params": {**_VIDEO, "video_length": 5400, "sliding_window_size": 241}},
    "unreadable lengths": {"params": {**_VIDEO, "video_length": "long", "sliding_window_size": "wide"}},
    "engine lookups fail": {"params": _VIDEO, "engine_fails": True},
    "scail2 dedicated": {"params": {**_VIDEO, "resolution": "848x480", "video_length": 81}, "base_model": "scail2_14B"},
    "scail2 shared, unreadable resolution": {"params": {**_VIDEO, "resolution": "widexhigh", "video_length": 81},
                                             "base_model": "scail2_1.3B", "dedicated": "off"},
    "h3 video references reload the profile": {
        "params": {**_VIDEO, "resolution": "960x544", "video_length": 345, "activated_loras": ["style.safetensors"],
                   "minimax_h3_references": _H3_REFERENCES},
        "model_def": _H3_OMNI, "loaded": 0.95},
    "h3 already loaded tighter": {"params": {**_VIDEO, "resolution": "960x544", "video_length": 97},
                                  "model_def": {"architecture": "minimax_h3_fake"}, "loaded": 0.05},
    "h3 with no model loaded": {"params": {**_VIDEO, "resolution": "640x352", "video_length": 49},
                                "model_def": {"architecture": "minimax_h3_fake"}},
    # No size, no LoRA, one stage, a base under the H3 cap: the value equals the base and is still written for H3.
    "h3 at the base value still applies and reloads": {"params": {"model_type": "fake_t2v"}, "base": 0.45,
                                                       "model_def": {"architecture": "minimax_h3_fake"}, "loaded": 0.6},
    "sound effect": {"params": {**_VIDEO, "sfx_mode": True}},
    "no gpu": {"params": _VIDEO, "vram": 0.0},
    "unreadable probe": {"params": _VIDEO, "vram": "unknown"},
    "small card": {"params": {**_VIDEO, "resolution": "1920x1088"}, "vram": 8.0},
    "base not a number": {"params": _VIDEO, "base": "eighty"},
}


@pytest.mark.parametrize("case", list(_COEFFICIENT_CASES))
def test_the_per_job_coefficient_value_for_each_kind_of_job(rig, golden, tmp_path, monkeypatch, capsys, case) -> None:
    spec = _COEFFICIENT_CASES[case]
    wgp = rig.server.wgp
    loras = tmp_path / "loras"
    loras.mkdir()
    for name, size in _LORA_SIZES.items():
        with open(loras / name, "wb") as handle:
            handle.truncate(size)  # sparse: the size is what the coefficient reads
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": spec.get("vram", 24.0)})
    monkeypatch.setitem(wgp.server_config, "vram_safety_coefficient", spec.get("base", 0.85))
    if spec.get("dedicated"):
        monkeypatch.setenv("MAESTRO_SCAIL2_DEDICATED_MODEL", spec["dedicated"])
    else:
        monkeypatch.delenv("MAESTRO_SCAIL2_DEDICATED_MODEL", raising=False)
    rig.set_wgp("reload_needed", False)
    if spec.get("engine_fails"):
        def fail(*_args, **_kwargs):
            raise RuntimeError("engine lookup failed")

        for name in ("get_lora_dir", "get_base_model_type", "get_model_def"):
            rig.set_wgp(name, fail)
    else:
        rig.set_wgp("get_lora_dir", lambda *_args, **_kwargs: str(loras))
        rig.set_wgp("get_base_model_type", lambda model_type: spec.get("base_model", model_type))
        rig.set_wgp("get_model_def", lambda _model_type: dict(spec.get("model_def", {})))
    if "loaded" in spec:
        rig.set_wgp("wan_model", SimpleNamespace(_maestro_profile_vram_coefficient=spec["loaded"]))
    job = {"id": "coefficient-job", "params": dict(spec["params"])}
    capsys.readouterr()
    returned = rig.launch._apply_per_job_coefficient(job)
    applied = wgp.args.vram_safety_coefficient
    rig.launch._restore_base_coefficient()
    printed = [line for line in capsys.readouterr().out.splitlines() if line.startswith("[VRAM]")]
    rig.check(golden, f"vram coefficient value: {case}", {
        "returned": returned,
        "adjustment": job.get("vram_adjustment"),
        "applied": applied,
        "reload_needed": wgp.reload_needed,
        "restored": wgp.args.vram_safety_coefficient,
        "printed": printed,
    })


def test_consecutive_jobs_each_start_from_the_saved_base_coefficient(rig, golden, monkeypatch) -> None:
    """One coefficient on ``wgp.args`` for the whole process: a heavy job tightens it, the worker puts the saved base
    back, a light job computes its own value from that base, a sound effect leaves it alone, and the same heavy job
    gets the same value again."""
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 24.0})
    monkeypatch.setitem(rig.server.wgp.server_config, "vram_safety_coefficient", 0.85)
    seen = _stub_mmaudio(rig, monkeypatch)
    heavy = {**BODY, "resolution": "1280x720", "video_length": 241}
    sequence = []
    for label, body in (("heavy video", heavy),
                        ("light image", {**BODY, "prompt": "a small still", "generation_mode": "image",
                                         "video_length": 1, "resolution": "512x512"}),
                        ("sound effect", SFX_BODY),
                        ("heavy video again", {**heavy, "prompt": "the lake again"})):
        engine_calls = len(rig.engine.calls)
        before = rig.server.wgp.args.vram_safety_coefficient
        job_id = rig.run(body)
        record = rig.launch.snapshot_job(rig.launch._jobs[job_id])
        sequence.append({
            "job": label,
            "status": record.get("status"),
            "before": before,
            "during": [call["vram_safety_coefficient"] for call in rig.engine.calls[engine_calls:]],
            "adjustment": record.get("vram_adjustment"),
            "after": rig.server.wgp.args.vram_safety_coefficient,
        })
    rig.check(golden, "vram coefficient across consecutive jobs", {
        "sequence": sequence, "audio model": seen, "base kept": rig.server.wgp.server_config["vram_safety_coefficient"]})


# -- sound-effect paths the Studio job does not take (C4 review) ---------------------------------------------------
_SFX_CASES = ["video guide sets the duration", "unreadable video guide keeps the asked duration",
              "missing video guide falls back to text", "out of memory is tagged"]


@pytest.mark.parametrize("case", _SFX_CASES)
def test_sound_effect_paths_through_the_worker(rig, golden, tmp_path, monkeypatch, case) -> None:
    """A legacy video-guided request reads the guide's duration with decord and remuxes onto it; a guide that is not
    there falls back to text; an audio model that runs out of memory fails the job with the OOM tag."""
    seen = _stub_mmaudio(rig, monkeypatch)
    guide = tmp_path / "guide.mp4"
    guide.write_bytes(b"GUIDE")

    class _Reader:
        def __init__(self, path: str) -> None:
            if case.startswith("unreadable"):
                raise RuntimeError("cannot decode the guide")
            seen.setdefault("decoded", []).append(Path(path).name)

        def get_avg_fps(self) -> float:
            return 24.0

        def __len__(self) -> int:
            return 60

    monkeypatch.setitem(sys.modules, "decord", SimpleNamespace(VideoReader=_Reader))
    params = dict(SFX_BODY)
    if case in ("video guide sets the duration", "unreadable video guide keeps the asked duration"):
        params["video_guide"] = str(guide)
    elif case == "missing video guide falls back to text":
        params["video_guide"] = "never-uploaded-guide.mp4"
    else:
        def video_to_audio(**_kwargs) -> None:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")

        monkeypatch.setitem(sys.modules, "postprocessing.mmaudio.mmaudio", SimpleNamespace(video_to_audio=video_to_audio))
    job_id = rig.direct_job(params, job_id="golden-sfx")
    returned = rig.call_worker(job_id)
    rig.check(golden, f"sound effect path: {case}", {**rig.observe(job_id), "audio model": seen, "returned": returned})


# -- FlashVSR progress and failures (C4 review) --------------------------------------------------------------------
_FLASH_EDGE_CASES = ["progress reaches the job", "progress goes to the caller", "no frames back", "concat fails",
                     "full variant keeps uint8", "tiny-long sizes its chunks for uint8", "full sizes its chunks for uint8"]


@pytest.mark.parametrize("case", _FLASH_EDGE_CASES)
def test_chunked_flashvsr_upscale_forwards_progress_and_cleans_up_a_failure(rig, golden, tmp_path, monkeypatch,
                                                                           case) -> None:
    """The model's progress callback becomes job progress (or goes to the caller's callback), a model that returns
    nothing or a failed concat raises after the persistence is put back and every segment is deleted, and the full
    variant's uint8 frames are saved without normalising."""
    import torch

    folder = tmp_path / "flash-edge"
    folder.mkdir()
    source = folder / "long.mp4"
    source.write_bytes(b"SOURCE")
    config = rig.server.wgp.server_config
    # A 1000-pixel 400-frame clip is one tiny-long or full chunk (uint8 output) but three plain tiny chunks (float32).
    sized = case.endswith("sizes its chunks for uint8")
    notes = _prepare_flashvsr(
        rig, monkeypatch, fps=8.9, width=1000 if sized else 4000, height=1000 if sized else 4000,
        frames=400 if sized else 100,
        variant=case.split()[0] if sized else "full" if case == "full variant keeps uint8" else "tiny",
        expect_ffmpeg=not sized and case != "no frames back", stop_at=None,
    )
    flash = rig.server.wgp.flashvsr
    model = flash.upscale
    changes: list = []
    received: list = []

    def update_job(_job, **kwargs):
        changes.append(kwargs)
        return True

    rig.patch("update_job", update_job)

    def upscale(seg, method, **kwargs):
        if case.startswith("progress"):
            kwargs["progress_callback"]("Denoising", 1, 4)
            kwargs["progress_callback"]("", None, None)
            kwargs["progress_callback"]("Decoding", "x", 5)
        if case == "no frames back":
            return None, None
        out, cache = model(seg, method, **kwargs)
        if case.startswith("full"):
            out = out.to(torch.uint8)
        return out, cache

    flash.upscale = upscale
    if case == "concat fails":
        def run(command, *args, **kwargs):
            notes["commands"].append(_masked_argv(command))
            return subprocess.CompletedProcess(list(command), 1, "", "concat: invalid data")

        monkeypatch.setattr(subprocess, "run", run)
    try:
        error = None
        result = None
        try:
            result = rig.launch._chunked_flashvsr_upscale(
                str(source), "flashvsr2", job={"id": "flash-edge-job"},
                progress_callback=(lambda *values: received.append(list(values)))
                if case == "progress goes to the caller" else None,
            )
        except RuntimeError as exc:
            error = str(exc)
        rig.check(golden, f"flashvsr edge: {case}", {
            "error": error,
            "returned": None if result is None else Path(result).name,
            "reads": notes["reads"],
            "upscales": notes["upscales"],
            "saves": notes["saves"],
            "job_updates": changes,
            "caller_progress": received,
            "commands": notes["commands"],
            "persistence_after": config.get("flashvsr_persistence"),
            "released": notes["releases"],
            "leftovers": _extras(folder, source) if result is None else sorted(
                name for name in _extras(folder, source) if name != Path(result).name),
        })
    finally:
        _clear_flash_keys(config)


# -- the wiring the C4 move added (C4 review) ------------------------------------------------------------------------
# Each pass module imports the standard library and the job lifecycle itself and receives the launch objects it reads
# (wgp, the hardware probe, the task registry, the sidecar publisher) from one ``bind`` call that launch makes when it
# defines them. A slot left at None, bound to a copy or to another function, or a pass that reads a name its module
# does not have would only show on the branch that reads it, so every global each moved function reads is compared
# here with the object the same name holds in launch, where the function read it before the move.
def _global_reads(function) -> set[str]:
    import inspect
    import symtable
    import textwrap

    names: set[str] = set()

    def walk(scope) -> None:
        names.update(symbol.get_name() for symbol in scope.get_symbols() if symbol.is_global() and symbol.is_referenced())
        for child in scope.get_children():
            walk(child)

    walk(symtable.symtable(textwrap.dedent(inspect.getsource(function)), "<pass>", "exec"))
    return names


def test_the_post_processing_passes_read_the_objects_launch_holds(server, monkeypatch) -> None:
    import builtins
    import importlib
    import inspect

    launch = worker_module()
    compared: set[str] = set()
    for module_name, exported in POSTFX_MODULES.items():
        module = importlib.import_module(module_name)
        namespace = vars(module)
        for name in exported:
            assert getattr(launch, name) is namespace[name], f"launch.{name} is not {module_name}.{name}"
        own = {name for name, value in namespace.items()
               if inspect.isfunction(value) and value.__module__ == module_name}
        for function_name in sorted(own - {"bind"}):
            for name in sorted(_global_reads(namespace[function_name])):
                if name in own:
                    continue  # a helper that moved with the pass
                if name not in namespace:
                    assert hasattr(builtins, name), f"{module_name}.{function_name} reads {name}, which is not defined"
                    continue
                assert namespace[name] is vars(launch)[name], f"{module_name}.{name} is not launch.{name}"
                compared.add(name)
    assert {"wgp", "os", "time", "copy", "traceback", "update_job", "finish_job", "is_cancel_requested",
            "new_media_files", "record_job_outputs", "_task_registry", "_publish_generation_sidecar_for_studio_job",
            "_get_cached_hardware", "_chunked_flashvsr_upscale"} == compared

    import routers.tools as tools

    assert tools._chunked_flashvsr_upscale is launch._chunked_flashvsr_upscale
    # The probe is one function. The coefficient pass calls it, and it reads the one cache.
    coefficients = importlib.import_module("services.generation_coefficients")
    assert coefficients._get_cached_hardware is launch._get_cached_hardware
    monkeypatch.setattr(hardware_cache, "value", {"gpu_vram_gb": 7.0})
    assert coefficients._get_cached_hardware() == {"gpu_vram_gb": 7.0}


# -- recast shot assembly (recorded before the helpers leave launch) --------------------------------
def _refuse_remote_network(monkeypatch) -> None:
    """The shot assembler must not download a model. Localhost stays open for the test client."""
    import socket

    real = socket.create_connection

    def refuse(address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host in {"127.0.0.1", "localhost", "::1"}:
            return real(address, *args, **kwargs)
        raise AssertionError(f"this test must not open a network connection to {address!r}")

    monkeypatch.setattr(socket, "create_connection", refuse)


def _call_recast_shot_generation(rig, job_id: str) -> None:
    """Run the assembler on a daemon thread, the same deadline ``Rig.call_worker`` gives the worker."""
    outcome: dict[str, Any] = {}

    def run() -> None:
        try:
            outcome["done"] = rig.launch._run_recast_shot_generation(job_id)
        except BaseException as error:  # handed to the test thread below
            outcome["error"] = error

    thread = threading.Thread(target=run, name=f"golden-recast-shots {job_id}", daemon=True)
    thread.start()
    thread.join(60)
    assert not thread.is_alive(), "_run_recast_shot_generation did not return within 60s"
    if "error" in outcome:
        raise outcome["error"]


@pytest.mark.parametrize("case", [
    "source audio",
    "video only",
    "passthrough segment",
    "generation fails",
    "missing segment",
    "timeline length changed",
    "cancelled during assembly",
])
def test_recast_shot_generation_joins_the_worker_clips(rig, golden, clip, monkeypatch, case) -> None:
    """The assembler runs the worker with ``finalize=False``, then joins the clips and publishes one file.

    Recorded while ``_run_recast_shot_generation`` still lives in launch. Concatenation, the audio probe and the
    decoded frame count are the real callables' neighbours; the fake engine still runs the worker.
    """
    _refuse_remote_network(monkeypatch)
    launch = rig.launch
    temp = rig.server.outputs / "maestro-recast-shots-golden"
    temp.mkdir()
    source = None
    if case in {"source audio", "passthrough segment"}:
        source = rig.server.outputs / "recast-source.mp4"
        shutil.copyfile(clip, source)
    manifest: Any = [{"shot_index": 0, "params": {"prompt": "shot zero", "video_length": 17}}]
    if case == "generation fails":
        manifest = "not a list"
    shot_index = 4 if case == "missing segment" else 0
    shot: dict[str, Any] = {"shot_index": shot_index, "mode": "generate"}
    if case == "passthrough segment":
        shot = {"shot_index": 0, "mode": "passthrough", "passthrough_path": str(source)}
    bundle = {
        "shots": [shot],
        "published_shots": [{"id": "s0"}],
        "frame_count": 8,
        "fps": 8,
        "resolved_seed": 42,
    }
    params = {
        **BODY,
        "_defer_output_publication": True,
        "_recast_shot_manifest": manifest,
        "_recast_shot_temp_dir": str(temp),
        "_recast_final_out_dir": str(rig.server.outputs),
        "_recast_shot_bundle": bundle,
    }
    if source is not None:
        params["_recast_source_video"] = str(source)
    job_id = rig.direct_job(params)
    launch._jobs[job_id]["out_dir"] = str(temp)

    probes: list = []
    assembly: list = []

    def has_audio(path: str) -> bool:
        probes.append(["audio", Path(path).name])
        return case == "source audio"

    def frame_count(path: str) -> int:
        probes.append(["frames", Path(path).name])
        return 3 if case == "timeline length changed" else 8

    def concatenate(clip_paths, output_path, audio_path=None, audio_start_sec=0.0, abort_callback=None,
                    pad_audio=False, audio_duration_sec=None):
        assembly.append({
            "clips": [Path(path).name for path in clip_paths],
            "audio": None if audio_path is None else Path(audio_path).name,
            "audio_start_sec": audio_start_sec,
            "pad_audio": pad_audio,
            "audio_duration_sec": audio_duration_sec,
            "already_cancelled": bool(abort_callback and abort_callback()),
        })
        shutil.copyfile(clip_paths[0], output_path)
        if case == "cancelled during assembly":
            launch._jobs[job_id]["cancel_requested"] = True
        return True

    rig.patch("_recast_video_has_audio", has_audio)
    rig.patch("_recast_video_frame_count", frame_count)
    rig.set_wgp("concatenate_multi_clip_videos", concatenate)
    _call_recast_shot_generation(rig, job_id)
    kept = launch._jobs[job_id].get("params") or {}
    rig.check(golden, f"recast shot generation: {case}", {
        **rig.observe(job_id),
        "assembly": assembly,
        "probes": probes,
        "private_left": sorted(
            key for key in kept
            if key.startswith("_recast") or key == "_defer_output_publication"
        ),
        "shot_aware": kept.get("edit_recast_shot_aware"),
        "shot_plan": kept.get("edit_recast_shot_plan"),
        "temp_removed": not temp.exists(),
    })


# -- recast shot assembly: the paths the seven cases above do not take (C8a review) ---------------------------------
@pytest.mark.parametrize("case", [
    "three shots in order",
    "no segments",
    "audio probe fails",
    "join fails",
    "frame probe fails",
    "cancelled after the join",
    "join longer than the timeline",
])
def test_recast_shot_generation_other_paths(rig, golden, clip, monkeypatch, case) -> None:
    """More assembler paths, recorded while ``_run_recast_shot_generation`` still lived in launch (C7 head e393f5746).

    Three shots join in timeline order, the passthrough between the two generated clips; an empty shot list, a failed
    audio probe, a failed join and a failed frame count each end the job their own way; a cancel that lands after the
    join leaves no final file and no sidecar behind; a join one frame longer than the timeline fails like a shorter
    one.
    """
    _refuse_remote_network(monkeypatch)
    launch = rig.launch
    temp = rig.server.outputs / "maestro-recast-shots-golden"
    temp.mkdir()
    source = rig.server.outputs / "recast-source.mp4"
    shutil.copyfile(clip, source)
    manifest: Any = [{"shot_index": 0, "params": {"prompt": "shot zero", "video_length": 17}}]
    shots: list = [{"shot_index": 0, "mode": "generate"}]
    if case == "three shots in order":
        manifest = [{"shot_index": 2, "params": {"prompt": "shot two", "video_length": 17}},
                    {"shot_index": 0, "params": {"prompt": "shot zero", "video_length": 17}}]
        shots = [{"shot_index": 0, "mode": "generate"},
                 {"shot_index": 1, "mode": "passthrough", "passthrough_path": str(source)},
                 {"shot_index": 2, "mode": "generate"}]
    elif case == "no segments":
        shots = []
    bundle = {
        "shots": shots,
        "published_shots": [{"id": f"s{shot['shot_index']}"} for shot in shots],
        "frame_count": 8,
        "fps": 8,
        "resolved_seed": 42,
    }
    params = {
        **BODY,
        "_defer_output_publication": True,
        "_recast_shot_manifest": manifest,
        "_recast_shot_temp_dir": str(temp),
        "_recast_final_out_dir": str(rig.server.outputs),
        "_recast_shot_bundle": bundle,
        "_recast_source_video": str(source),
    }
    job_id = rig.direct_job(params)
    launch._jobs[job_id]["out_dir"] = str(temp)

    probes: list = []
    assembly: list = []
    finals: list = []

    def has_audio(path: str) -> bool:
        probes.append(["audio", Path(path).name])
        if case == "audio probe fails":
            raise RuntimeError("ffprobe is not here")
        return True

    def frame_count(path: str) -> int:
        probes.append(["frames", Path(path).name])
        if case == "frame probe fails":
            raise RuntimeError("decord is not here")
        if case == "cancelled after the join":
            launch._jobs[job_id]["cancel_requested"] = True
        return 9 if case == "join longer than the timeline" else 8

    def concatenate(clip_paths, output_path, audio_path=None, audio_start_sec=0.0, abort_callback=None,
                    pad_audio=False, audio_duration_sec=None):
        assembly.append({
            "clips": [Path(path).name for path in clip_paths],
            "audio": None if audio_path is None else Path(audio_path).name,
            "audio_duration_sec": audio_duration_sec,
        })
        finals.append(Path(output_path))
        if case == "join fails":
            return False
        shutil.copyfile(clip_paths[0], output_path)
        # The real join can leave a metadata sibling next to its output; cleanup must take it too.
        Path(output_path).with_suffix(".meta.json").write_text("{}", encoding="utf-8")
        return True

    rig.patch("_recast_video_has_audio", has_audio)
    rig.patch("_recast_video_frame_count", frame_count)
    rig.set_wgp("concatenate_multi_clip_videos", concatenate)
    _call_recast_shot_generation(rig, job_id)
    kept = launch._jobs[job_id].get("params") or {}
    rig.check(golden, f"recast shot generation, other paths: {case}", {
        **rig.observe(job_id),
        "assembly": assembly,
        "probes": probes,
        "final_left": [path.exists() for path in finals],
        "final_meta_left": [path.with_suffix(".meta.json").exists() for path in finals],
        "private_left": sorted(
            key for key in kept
            if key.startswith("_recast") or key == "_defer_output_publication"
        ),
        "shot_aware": kept.get("edit_recast_shot_aware"),
        "shot_plan": kept.get("edit_recast_shot_plan"),
        "temp_removed": not temp.exists(),
    })


def test_a_rig_patch_reaches_every_recast_module(full_server) -> None:
    """``Rig.patch`` writes a name on every module of ``worker_modules()`` that holds it. Each Recast service module
    reads its collaborators through its own globals, so each one must be in that list, or a stub would miss the
    module that calls it (C8a review: dropping a shot module from the list left every golden green)."""
    import importlib

    services = Path(__file__).resolve().parents[2] / "app" / "services"
    stems = sorted(path.stem for path in services.glob("recast_*.py"))
    assert "recast_masks" in stems
    for stem in stems:
        importlib.import_module(f"services.{stem}")
    held = {module.__name__ for module in worker_modules()}
    assert {f"services.{stem}" for stem in stems} <= held


def test_a_rig_patch_of_time_reaches_the_canonical_task_clock(rig) -> None:
    """Before C10a the canonical publishers read launch's ``time``, so a Rig patch of ``time`` set the clock a task
    falls back to when its record has no creation time. The same patch still reaches the publishers in their module."""
    real = rig.launch.time
    clock = types.ModuleType("time")
    clock.__dict__.update({name: getattr(real, name) for name in dir(real) if not name.startswith("__")})
    clock.time = lambda: 1_600_000_000.0
    rig.patch("time", clock)
    task = rig.launch._publish_generic_legacy_task({"id": "rig-clock", "workspace": "default", "status": "queued"}, "rig")
    assert task["created_at"] == 1_600_000_000.0
