"""Creation models keep reference identities, native contracts and cancellation."""
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from services.creation_model_catalog import MODEL_TYPES, assets, model_definition, validate
from services.creation_model_graphs import build_workflow
from services.studio_speech_spec import SPEECH_MODEL_TYPES


def test_speech_registered_separately_from_images():
    assert {name for name in MODEL_TYPES if name in SPEECH_MODEL_TYPES} == {"drama3_base", "drama3_voicedesign"}
    for model in MODEL_TYPES:
        definition = model_definition(model)
        assert definition["image_outputs"] != definition["audio_only"]
        assert definition["group"] == ("flux3" if model.startswith("flux3_") else "tts")
        assert definition["required_model_assets"]
        assert len(assets(model)[1]) == 40


def test_flux_ten_references_are_encoded_in_order(tmp_path):
    refs = []
    for i in range(10):
        source = tmp_path / f"view{i}.png"
        source.write_bytes(bytes([i]))
        refs.append(str(source))
    params = {"model_type": "flux3_klein_edit", "prompt": "Same character, four views", "seed": 42,
              "image_guide": refs[0], "image_refs": refs[1:]}
    graph, output = build_workflow(params, "test", tmp_path / "inputs")
    assert graph[output]["class_type"] == "SaveImage"
    for i in range(10):
        name = graph[str(20 + 5 * i)]["inputs"]["image"]
        assert (tmp_path / "inputs" / name).read_bytes() == bytes([i])
        assert graph[str(21 + 5 * i)]["inputs"]["resolution_steps"] == 16
    assert graph["7"]["inputs"]["positive"] == ["68", 0]
    assert graph["7"]["inputs"]["negative"] == ["69", 0]
    with pytest.raises(ValueError, match="ten"):
        validate({**params, "image_refs": refs})


def test_clone_needs_both_audio_and_exact_transcript(tmp_path):
    params = {"model_type": "drama3_base", "prompt": "Hello", "seed": 7, "audio_guide": "clip.wav"}
    with pytest.raises(ValueError, match="transcript"):
        validate(params)
    source = tmp_path / "clip.wav"
    source.write_bytes(b"audio fixture")
    params.update(audio_guide=str(source), alt_prompt="Original words")
    graph, _ = build_workflow(params, "clone", tmp_path / "inputs")
    assert graph["7"]["inputs"]["transcript"] == "Original words"
    assert graph["3"]["inputs"]["voices.voice0"] == ["7", 0]
    assert graph["1"]["inputs"]["experts"] == "in RAM"


def test_voice_direction_is_not_added_to_reference_transcript(tmp_path):
    graph, _ = build_workflow({"model_type": "drama3_voicedesign", "prompt": "Hola. [language: es]",
                              "alt_prompt": "Warm and clear", "seed": 3}, "speech", tmp_path)
    assert graph["3"]["inputs"]["text"] == "Direction: Warm and clear\nLine: Hola. [language: es]"
    assert "voices.voice0" not in graph["3"]["inputs"]


def test_inactive_wangp_outpaint_sentinel_is_not_an_edit():
    validate({"model_type": "drama3_voicedesign", "prompt": "Hola", "video_guide_outpainting": "#"})
    validate({"model_type": "flux3_klein", "prompt": "A cube", "video_guide_outpainting": "0 0 0 0"})
    with pytest.raises(ValueError, match="outpainting"):
        validate({"model_type": "flux3_klein", "prompt": "A cube", "video_guide_outpainting": "0 16 0 0"})


def test_cancel_does_not_wait_for_the_generation_lock(monkeypatch):
    from services import creation_model_service as service
    done = threading.Event()
    monkeypatch.setattr(service, "_port", 1234)
    monkeypatch.setattr(service, "_request", lambda *a, **k: done.set())
    with service._lock:
        thread = threading.Thread(target=service.cancel, daemon=True)
        thread.start()
        assert done.wait(1), "Cancellation blocked on the active generation lock"
    thread.join(timeout=1)


def test_runtime_is_stopped_if_assets_fail(monkeypatch, tmp_path):
    from services import creation_model_service as service
    stopped = []
    monkeypatch.setattr(service, "download_assets", lambda *a: (_ for _ in ()).throw(RuntimeError("gated")))
    monkeypatch.setattr(service, "stop_runtime", lambda: stopped.append(True))
    with pytest.raises(RuntimeError, match="gated"):
        service.generate({"model_type": "flux3_klein"}, "job", str(tmp_path), lambda *a: None, lambda: False)
    assert stopped == [True]


def test_edit_admission_accepts_a_source_but_requires_conditioning():
    from fastapi import HTTPException
    from services.image_generation_commands import validate_image_model
    params = {"model_type": "flux3_klein_edit", "resolution": "1024x1024"}
    callbacks = {"model_definition": model_definition, "model_downloaded": lambda _: True}
    with pytest.raises(HTTPException) as missing:
        validate_image_model(params, allow_references=True, **callbacks)
    assert missing.value.detail["code"] == "reference_required"
    validate_image_model({**params, "image_guide": "source.png"}, allow_references=True, **callbacks)
    with pytest.raises(HTTPException):
        validate_image_model({**params, "image_guide": "source.png"}, **callbacks)


def test_a_delayed_history_poll_does_not_discard_a_finished_output(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_service as service
    output = tmp_path / "runtime"
    output.mkdir()
    (output / "take.flac").write_bytes(b"generated audio")
    polls = []

    def request(method, base, suffix, **kwargs):
        if suffix == "/prompt":
            return SimpleNamespace(json=lambda: {"prompt_id": "one"})
        polls.append(suffix)
        if len(polls) == 1:
            raise service.requests.Timeout("kernel busy")
        return SimpleNamespace(json=lambda: {"one": {"outputs": {"5": {"audio": [{"filename": "take.flac"}]}}}})

    monkeypatch.setattr(service, "_request", request)
    monkeypatch.setattr(service, "_process", SimpleNamespace(poll=lambda: None))
    monkeypatch.setattr(service, "OUTPUT_DIR", output)
    monkeypatch.setattr(service, "INPUT_DIR", tmp_path / "inputs")
    monkeypatch.setattr(service, "download_assets", lambda *args: None)
    monkeypatch.setattr(service, "ensure_runtime", lambda *args: "http://runtime")
    monkeypatch.setattr(service, "stop_runtime", lambda: None)
    monkeypatch.setattr(service, "build_workflow", lambda *args: ({}, "5"))
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    result = service.generate({"model_type": "drama3_base", "seed": 1}, "job", tmp_path / "published",
                              lambda *args: None, lambda: False)
    assert Path(result[0]).read_bytes() == b"generated audio"
    assert len(polls) == 2


def test_shared_weights_cannot_be_deleted_while_the_other_variant_is_queued(monkeypatch, tmp_path):
    from fastapi import HTTPException
    from services import creation_model_service as service, model_downloads
    monkeypatch.setattr(model_downloads, "_active_gen_states", {})
    monkeypatch.setattr(model_downloads, "_jobs", {"queued": {"status": "queued", "params": {"model_type": "flux3_klein_edit"}}})
    with pytest.raises(HTTPException) as busy:
        model_downloads.delete_model("flux3_klein")
    assert busy.value.status_code == 409
    monkeypatch.setattr(model_downloads, "_jobs", {})
    monkeypatch.setattr(service, "ASSET_ROOT", tmp_path)
    for name in assets("flux3_klein")[2]:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fixture")
    result = model_downloads.delete_model("flux3_klein")
    assert set(result["affected_models"]) == {"flux3_klein", "flux3_klein_edit"}
    assert len(result["deleted"]) == 3
    assert all(not (tmp_path / name).exists() for name in result["deleted"])


def test_random_seed_is_resolved_and_each_repeat_keeps_its_effective_seed(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_execution as execution
    observed, published = [], []
    paths = [str(tmp_path / f"flux3_klein_job_{i}_00001_.png") for i in range(2)]
    monkeypatch.setattr(execution.secrets, "randbelow", lambda _: 12345)
    monkeypatch.setattr(execution.service, "generate", lambda params, *args: observed.append(params) or paths)
    monkeypatch.setattr(execution, "record_job_outputs", lambda *args: None)
    monkeypatch.setattr(execution, "is_cancel_requested", lambda _: False)
    monkeypatch.setattr(execution, "finish_job", lambda *args, **kwargs: True)
    original = {"model_type": "flux3_klein", "seed": -1}
    state = SimpleNamespace(job={"out_dir": str(tmp_path)}, raw_params=original, job_id="job", start_time=0, finalize=True)
    execution.run_creation_job(state, engine=SimpleNamespace(), publish=lambda job, path, meta: published.append(meta))
    assert original["seed"] == -1
    assert observed[0]["seed"] == 12345
    assert [meta["params"]["seed"] for meta in published] == [12345, 12346]


def test_drama_flac_outputs_appear_in_the_audio_gallery(monkeypatch, tmp_path):
    from fastapi import Response
    from services import output_listing
    (tmp_path / "drama.flac").write_bytes(b"fLaC fixture")
    monkeypatch.setattr(output_listing, "_workspace_dir", lambda _: str(tmp_path))
    monkeypatch.setattr(output_listing, "_load_favorites", lambda: set())
    result = output_listing.list_outputs(Response(), workspace="demo", media_type="audio")
    assert result["total"] == 1
    assert result["outputs"][0]["name"] == "drama.flac"
    assert result["outputs"][0]["type"] == "audio"


# --- the warm runtime ------------------------------------------------------------

IDLE_STATUS = {"warm": False, "family": None, "idle_seconds_left": None, "confined": False, "memory_max_gb": None}


class _FakeComfy:
    """A ComfyUI process that never starts: records the launch and answers the poll."""

    next_pid = 41000

    def __init__(self, command, exit_code=None, **kwargs):
        self.command, self.kwargs = command, kwargs
        self.stdout = iter(())
        self.stopped = threading.Event()
        self.exit_code = exit_code
        type(self).next_pid += 1
        self.pid = type(self).next_pid

    def poll(self):
        if self.exit_code is not None:
            return self.exit_code
        return 0 if self.stopped.is_set() else None

    def terminate(self):
        self.stopped.set()

    kill = terminate

    def wait(self, timeout=None):
        return 0


@pytest.fixture
def comfy(monkeypatch, tmp_path):
    """Run ``generate`` end to end with a fake process and a stubbed HTTP surface."""
    from types import SimpleNamespace
    from services import creation_model_service as service
    processes, calls = [], []
    state = {"healthy": True, "history": "ok", "prompts": 0, "pending": 0, "exit_code": None}
    output = tmp_path / "runtime" / "output"
    output.mkdir(parents=True)
    (output / "take.flac").write_bytes(b"generated audio")

    def popen(command, **kwargs):
        processes.append(_FakeComfy(command, exit_code=state["exit_code"], **kwargs))
        return processes[-1]

    def request(method, base, suffix, **kwargs):
        calls.append(suffix)
        if suffix == "/system_stats":
            if not state["healthy"]:
                raise service.requests.ConnectionError("down")
            return SimpleNamespace(json=lambda: {})
        if suffix == "/prompt":
            state["prompts"] += 1
            return SimpleNamespace(json=lambda: {"prompt_id": f"p{state['prompts']}"})
        if state["pending"] > 0:
            state["pending"] -= 1
            return SimpleNamespace(json=lambda: {})
        if state["history"] == "error":
            status = {"status_str": "error", "messages": [["execution_error", {"exception_message": "boom"}]]}
            return SimpleNamespace(json=lambda: {suffix.rsplit("/", 1)[1]: {"status": status}})
        return SimpleNamespace(json=lambda: {suffix.rsplit("/", 1)[1]: {"outputs": {"5": {"audio": [{"filename": "take.flac"}]}}}})

    monkeypatch.setattr(service, "subprocess", SimpleNamespace(
        Popen=popen, PIPE=subprocess.PIPE, STDOUT=subprocess.STDOUT, TimeoutExpired=subprocess.TimeoutExpired))
    monkeypatch.setattr(service, "_request", request)
    monkeypatch.setattr(service, "_drain", lambda process: None)
    monkeypatch.setattr(service, "is_runtime_installed", lambda: True)
    monkeypatch.setattr(service, "engine_python", lambda name: "python")
    monkeypatch.setattr(service, "isolated_environment", lambda python: {})
    monkeypatch.setattr(service, "download_assets", lambda *args: None)
    monkeypatch.setattr(service, "build_workflow", lambda *args: ({}, "5"))
    monkeypatch.setattr(service, "SERVICE_DIR", tmp_path / "runtime")
    monkeypatch.setattr(service, "COMFY_DIR", tmp_path / "runtime")
    monkeypatch.setattr(service, "INPUT_DIR", tmp_path / "runtime" / "input")
    monkeypatch.setattr(service, "OUTPUT_DIR", output)
    monkeypatch.setattr(service.time, "sleep", lambda _: None)
    # Every test runs unconfined unless it asks for the fake systemd of ``confined``.
    monkeypatch.setattr(service.confinement, "_support", False)
    service.stop_runtime()

    def job(model="drama3_base", name="job", cancelled=lambda: False, **options):
        return service.generate({"model_type": model, "seed": 1}, name, tmp_path / "published",
                                lambda *args: None, cancelled, **options)

    yield SimpleNamespace(service=service, processes=processes, calls=calls, state=state, job=job)
    service.stop_runtime()


def test_two_consecutive_jobs_start_one_process(comfy):
    comfy.job(name="one")
    comfy.job(name="two")
    assert len(comfy.processes) == 1
    assert not comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["warm"] is True


def test_idle_timer_stops_the_warm_runtime(comfy):
    comfy.job(idle_seconds=0.05)
    assert comfy.processes[0].stopped.wait(2), "The idle timer never stopped the runtime"
    assert comfy.service.runtime_status() == IDLE_STATUS


def test_a_new_job_cancels_the_idle_timer(comfy):
    comfy.job(name="one", idle_seconds=0.2)
    comfy.job(name="two", idle_seconds=600)
    assert not comfy.processes[0].stopped.wait(0.4), "The first job's timer stopped a runtime a later job kept"
    assert len(comfy.processes) == 1


def test_a_family_switch_restarts_the_runtime(comfy):
    comfy.job("drama3_base", "a")
    comfy.job("drama3_voicedesign", "b")
    assert len(comfy.processes) == 1, "Both Drama models share one family"
    comfy.job("flux3_klein", "c")
    assert len(comfy.processes) == 2 and comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["family"] == "flux"
    comfy.job("flux3_klein_edit", "d")
    assert len(comfy.processes) == 2


def test_a_dead_process_or_a_failed_health_check_restarts_the_runtime(comfy, monkeypatch):
    comfy.job(name="one")
    comfy.processes[0].stopped.set()
    comfy.job(name="two")
    assert len(comfy.processes) == 2
    comfy.job(name="three")
    assert len(comfy.processes) == 2
    # The process is alive but /system_stats stops answering: replace it.
    answers = iter([False])
    real = comfy.service._request

    def flaky(method, base, suffix, **kwargs):
        if suffix == "/system_stats" and next(answers, True) is False:
            raise comfy.service.requests.ConnectionError("hung")
        return real(method, base, suffix, **kwargs)

    monkeypatch.setattr(comfy.service, "_request", flaky)
    comfy.job(name="four")
    assert len(comfy.processes) == 3 and comfy.processes[1].stopped.is_set()


def test_an_error_stops_the_warm_runtime(comfy):
    comfy.job(name="one")
    comfy.state["history"] = "error"
    with pytest.raises(RuntimeError, match="boom"):
        comfy.job(name="two")
    assert comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["warm"] is False
    comfy.state["history"] = "ok"
    comfy.job(name="three")
    assert len(comfy.processes) == 2


def test_a_cancellation_stops_the_warm_runtime(comfy):
    comfy.job(name="one")
    with pytest.raises(RuntimeError, match="cancelled"):
        comfy.job(name="two", cancelled=lambda: True)
    assert comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["warm"] is False


def test_a_zero_idle_setting_stops_the_runtime_at_once(comfy):
    comfy.job(idle_seconds=0)
    assert comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["warm"] is False
    assert comfy.service.idle_seconds_setting({"creation_runtime_idle_seconds": 0}) == 0
    assert comfy.service.idle_seconds_setting({}) == 300
    assert comfy.service.idle_seconds_setting({"creation_runtime_idle_seconds": "12.5"}) == 12.5
    assert comfy.service.idle_seconds_setting({"creation_runtime_idle_seconds": -4}) == 0
    assert comfy.service.idle_seconds_setting({"creation_runtime_idle_seconds": "soon"}) == 300
    assert comfy.service.idle_seconds_setting({"creation_runtime_idle_seconds": True}) == 300


def test_runtime_status_reports_the_family_and_the_time_left(comfy):
    assert comfy.service.runtime_status() == IDLE_STATUS
    comfy.job("flux3_klein", idle_seconds=120)
    status = comfy.service.runtime_status()
    assert status["warm"] is True and status["family"] == "flux"
    assert 100 < status["idle_seconds_left"] <= 120
    assert status["confined"] is False and status["memory_max_gb"] is None
    comfy.service.stop_runtime()
    assert comfy.service.runtime_status() == IDLE_STATUS


@pytest.fixture
def gpu_hand_off(monkeypatch):
    """A coordinator wired like the server: the prepare hook sits on the local GPU lane only."""
    from services import generation_preparation, llm_service, resource_scheduler
    monkeypatch.setattr(llm_service, "get_status", lambda: {"provider": "remote"})
    monkeypatch.setattr(generation_preparation, "wgp", None)
    coordinator = resource_scheduler.ResourceCoordinator()
    coordinator.set_prepare_hook(resource_scheduler.local_gpu_lane(0), generation_preparation._prepare_local_gpu_owner)
    return coordinator


@pytest.mark.parametrize("owner", [
    "GPU_ENGINE_WGP", "GPU_ENGINE_H3_LEGACY", "GPU_ENGINE_LOCAL_LLM",
])
def test_another_engine_taking_the_gpu_stops_the_warm_runtime(comfy, gpu_hand_off, owner):
    from services import resource_scheduler
    comfy.job(name="one")
    description = resource_scheduler.gpu_engine_description(getattr(resource_scheduler, owner), "next owner")
    with gpu_hand_off.acquire(resource_scheduler.local_gpu_lane(0), task_id="next", description=description):
        assert comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["warm"] is False


def test_an_untagged_gpu_owner_stops_the_warm_runtime(comfy, gpu_hand_off):
    from services import resource_scheduler
    comfy.job(name="one")
    with gpu_hand_off.acquire(resource_scheduler.local_gpu_lane(0), task_id="whisper", description="Audio analysis"):
        assert comfy.processes[0].stopped.is_set()


def test_a_creation_job_keeps_the_runtime_across_the_gpu_hand_off(comfy, gpu_hand_off):
    from services import resource_scheduler
    comfy.job(name="one")
    description = resource_scheduler.gpu_engine_description(resource_scheduler.GPU_ENGINE_CREATION, "creation job")
    with gpu_hand_off.acquire(resource_scheduler.local_gpu_lane(0), task_id="next", description=description):
        assert not comfy.processes[0].stopped.is_set()
        comfy.job(name="two")
    assert len(comfy.processes) == 1


def test_cpu_work_between_two_drama_lines_keeps_one_process(comfy, gpu_hand_off):
    """Series render: voice, then the CPU Whisper check (speech_qa takes the audio CPU lane), then the next line."""
    from services import resource_scheduler
    comfy.job(name="line1")
    for name in ("audio-analysis", "speech-analysis", "world3d-render"):
        with gpu_hand_off.acquire(resource_scheduler.cpu_lane(name), task_id=f"cpu-{name}", description="Speech check"):
            assert not comfy.processes[0].stopped.is_set()
    comfy.job(name="line2")
    assert len(comfy.processes) == 1


def test_the_sam_service_start_evicts_an_idle_warm_runtime(comfy, monkeypatch):
    """SAM is a GPU subprocess that never takes the GPU lane, so it asks the creation runtime to go itself."""
    from services import inpaint_service
    comfy.job(name="one")
    monkeypatch.setattr(inpaint_service, "check_sam_status", lambda: {"status": "stopped"})
    monkeypatch.setattr(inpaint_service, "_find_sam_env", lambda: "python")
    monkeypatch.setattr(inpaint_service, "_find_sam_service_script", lambda: "sam_service.py")

    def refuse(*args, **kwargs):
        raise OSError("the test never starts SAM")

    monkeypatch.setattr(subprocess, "Popen", refuse)
    with pytest.raises(OSError, match="never starts SAM"):
        inpaint_service.ensure_sam_running()
    assert comfy.processes[0].stopped.is_set()


def test_a_lane_less_eviction_never_waits_for_a_running_job(comfy, monkeypatch):
    started, release = threading.Event(), threading.Event()
    original = comfy.service._request

    def slow(method, base, suffix, **kwargs):
        if suffix.startswith("/history/"):
            started.set()
            release.wait(2)
        return original(method, base, suffix, **kwargs)

    monkeypatch.setattr(comfy.service, "_request", slow)
    worker = threading.Thread(target=comfy.job, kwargs={"name": "busy"}, daemon=True)
    worker.start()
    assert started.wait(2)
    assert comfy.service.evict_if_idle() is False
    assert not comfy.processes[0].stopped.is_set()
    release.set()
    worker.join(2)
    assert comfy.service.evict_if_idle() is True
    assert comfy.processes[0].stopped.is_set()


def test_the_idle_setting_reaches_the_runtime_and_a_bad_one_means_the_default(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_execution as execution
    seen = []

    def generate(params, job_id, out_dir, progress, cancelled, on_produce=None, idle_seconds=None):
        seen.append(idle_seconds)
        return []

    monkeypatch.setattr(execution.service, "generate", generate)
    monkeypatch.setattr(execution, "record_job_outputs", lambda *args: None)
    monkeypatch.setattr(execution, "is_cancel_requested", lambda _: False)
    monkeypatch.setattr(execution, "finish_job", lambda *args, **kwargs: True)
    for services in ({"creation_runtime_idle_seconds": 7}, {"creation_runtime_idle_seconds": "later"}, {}):
        engine = SimpleNamespace(server_config={"services": services})
        state = SimpleNamespace(job={"out_dir": str(tmp_path)}, raw_params={"model_type": "drama3_base", "seed": 1},
                                job_id="job", start_time=0, finalize=True)
        execution.run_creation_job(state, engine=engine, publish=lambda *args: None)
    assert seen == [7.0, 300.0, 300.0]


# --- the stall guard ----------------------------------------------------------------


class _Clock:
    """A monotonic clock the test moves: ``sleep`` advances it, nothing really waits."""

    def __init__(self, now=10_000.0):
        self.now, self.ticks = now, []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds
        for tick in self.ticks:
            tick(self.now)


@pytest.fixture
def clock(comfy, monkeypatch):
    fake = _Clock()
    monkeypatch.setattr(comfy.service, "time", fake)
    monkeypatch.setattr(comfy.service, "_last_output", fake.now)
    return fake


def test_a_silent_runtime_with_a_pending_prompt_is_stopped_after_fifteen_minutes(comfy, clock):
    comfy.state["pending"] = 10**9
    with pytest.raises(RuntimeError, match="no progress for 15 minutes.*try again"):
        comfy.job()
    assert comfy.processes[0].stopped.is_set()
    assert comfy.service.runtime_status()["warm"] is False
    assert 900 <= clock.now - 10_000 < 1000, "The guard fired at the one-hour limit instead of after 15 quiet minutes"


def test_printed_output_keeps_a_slow_prompt_alive_until_the_one_hour_limit(comfy, clock):
    comfy.state["pending"] = 10**9

    def print_a_line(now):
        if int(now) % 300 == 0:
            comfy.service._last_output = now

    clock.ticks.append(print_a_line)
    with pytest.raises(RuntimeError, match="one-hour limit"):
        comfy.job()
    assert clock.now - 10_000 >= 3600
    assert comfy.processes[0].stopped.is_set()


def test_time_a_warm_runtime_sat_silent_before_the_prompt_does_not_count(comfy, clock):
    comfy.service._last_output = 0.0
    clock.now = 50_000.0
    comfy.state["pending"] = 3
    assert len(comfy.job()) == 1
    assert len(comfy.processes) == 1 and not comfy.processes[0].stopped.is_set()


def test_the_output_reader_stamps_every_line(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_service as service
    fake = _Clock()
    monkeypatch.setattr(service, "time", fake)
    monkeypatch.setattr(service, "ROOT", tmp_path / "app")
    monkeypatch.setattr(service, "_last_output", 0.0)

    def lines():
        fake.now = 111.0
        yield "first\n"
        fake.now = 222.0
        yield "second\n"

    service._drain(SimpleNamespace(stdout=lines()))
    assert service._last_output == 222.0
    assert (tmp_path / "logs" / "creation_models" / "latest.log").read_text(encoding="utf-8") == "first\nsecond\n"


# --- memory confinement ----------------------------------------------------------------

GIB = 1 << 30
SYSTEMD_RUN = "/usr/bin/systemd-run"
OOM_MESSAGE = "ran out of memory and was stopped; the server and your other programs were not touched"


@pytest.fixture
def confined(comfy, monkeypatch):
    """The ``comfy`` runtime on a fake 64 GiB Linux machine whose systemd user manager answers."""
    from types import SimpleNamespace
    from services import creation_runtime_confinement as confinement
    comfy.probes, comfy.cgroup = [], SimpleNamespace(path="/sys/fs/cgroup/fake.scope", oom_kills=0)

    def probe(command, **kwargs):
        comfy.probes.append((command, kwargs))
        return SimpleNamespace(returncode=comfy.state.get("probe_code", 0))

    monkeypatch.setattr(confinement, "subprocess", SimpleNamespace(
        run=probe, TimeoutExpired=subprocess.TimeoutExpired, DEVNULL=subprocess.DEVNULL))
    monkeypatch.setattr(confinement, "shutil", SimpleNamespace(which=lambda name: comfy.state.get("which", SYSTEMD_RUN)))
    monkeypatch.setattr(confinement, "_on_linux", lambda: True)
    monkeypatch.setattr(confinement, "physical_memory_bytes", lambda: 64 * GIB)
    monkeypatch.setattr(confinement, "verify_scope", lambda pid, limits: Path(comfy.cgroup.path))
    monkeypatch.setattr(confinement, "oom_kills", lambda cgroup: comfy.cgroup.oom_kills)
    monkeypatch.setattr(confinement, "_support", None)
    comfy.confinement = confinement
    return comfy


def test_ensure_runtime_wraps_the_command_with_systemd_run_and_the_limits(confined, monkeypatch):
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1234/bus")
    confined.job(name="one")
    memory_max = 64 * GIB * 80 // 100
    memory_high = memory_max * 90 // 100
    assert (memory_max, memory_high) == (54975581388, 49478023249)
    command = confined.processes[0].command
    assert command[:12] == [SYSTEMD_RUN, "--user", "--scope", "--quiet", "--collect", "-p", f"MemoryHigh={memory_high}",
                            "-p", f"MemoryMax={memory_max}", "-p", "MemorySwapMax=0", "--"]
    assert command[12:15] == ["/usr/bin/env", "-i", "--"]
    assert command[15:17] == ["python", "main.py"] and "--listen" in command
    assert confined.processes[0].kwargs["env"]["XDG_RUNTIME_DIR"] == "/run/user/1234"
    assert confined.processes[0].kwargs["env"]["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1234/bus"
    status = confined.service.runtime_status()
    assert status["confined"] is True and status["memory_max_gb"] == 51.2
    confined.job(name="two")
    assert len(confined.probes) == 1, "The systemd probe must run once per process"
    assert confined.probes[0][0] == [SYSTEMD_RUN, "--user", "--scope", "--quiet", "true"]
    assert confined.probes[0][1]["timeout"] == 5


def test_a_setting_of_zero_or_a_runtime_that_is_not_confined_runs_the_plain_command(confined):
    confined.job(name="one", memory_percent=0)
    assert confined.processes[0].command[0] == "python"
    status = confined.service.runtime_status()
    assert status["confined"] is False and status["memory_max_gb"] is None
    assert not confined.probes, "Setting 0 must not even ask systemd"


@pytest.mark.parametrize("percent, share", [(10, 30), (30, 30), (62, 62), (95, 95), (99, 95), (None, 80)])
def test_the_percent_is_clamped_to_30_95_of_the_physical_memory(confined, percent, share):
    confined.job(memory_percent=percent)
    expected = 64 * GIB * share // 100
    command = confined.processes[0].command
    assert f"MemoryMax={expected}" in command and f"MemoryHigh={expected * 90 // 100}" in command


def test_the_percent_setting_reads_like_the_idle_setting():
    from services.creation_runtime_confinement import memory_percent_setting as read
    key = "creation_runtime_memory_percent"
    assert read({}) == 80 and read(None) == 80
    assert read({key: 0}) == 0 and read({key: "0"}) == 0
    assert read({key: 5}) == 30 and read({key: 200}) == 95 and read({key: "70"}) == 70 and read({key: 62.9}) == 62
    for bad in ("lots", True, None, -5, float("nan"), float("inf")):
        assert read({key: bad}) == 80, bad


@pytest.mark.parametrize("failure", ["no systemd-run", "probe exits 1", "probe times out", "probe cannot start"])
def test_without_a_working_systemd_the_command_is_plain_and_one_line_says_why(confined, monkeypatch, capsys, failure):
    state = confined.state
    if failure == "no systemd-run":
        state["which"] = None
    elif failure == "probe exits 1":
        state["probe_code"] = 1
    else:
        error = subprocess.TimeoutExpired("systemd-run", 5) if failure == "probe times out" else OSError("denied")

        def refuse(command, **kwargs):
            raise error

        monkeypatch.setattr(confined.confinement.subprocess, "run", refuse)
    confined.job("drama3_base", "one")
    confined.job("flux3_klein", "two")
    assert [process.command[0] for process in confined.processes] == ["python", "python"]
    assert confined.service.runtime_status()["confined"] is False
    lines = [line for line in capsys.readouterr().out.splitlines() if "not confined" in line]
    assert len(lines) == 1 and "systemd" in lines[0]


def test_another_platform_runs_the_plain_command_without_a_log_line(confined, monkeypatch, capsys):
    monkeypatch.setattr(confined.confinement, "_on_linux", lambda: False)
    monkeypatch.setattr(confined.confinement, "physical_memory_bytes", lambda: None)
    confined.job(name="one")
    assert confined.processes[0].command[0] == "python" and not confined.probes
    assert "not confined" not in capsys.readouterr().out


def test_the_child_environment_keeps_what_systemd_run_needs():
    from services.creation_runtime_confinement import session_environment
    from services.runtime_environment import isolated_environment
    inherited = {"XDG_RUNTIME_DIR": "/run/user/1000", "DBUS_SESSION_BUS_ADDRESS": "unix:path=/run/user/1000/bus",
                 "PYTHONPATH": "/leak", "PATH": "/usr/bin"}
    env = isolated_environment(Path("/engine/bin/python"), inherited)
    assert env["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert env["DBUS_SESSION_BUS_ADDRESS"] == "unix:path=/run/user/1000/bus"
    assert "PYTHONPATH" not in env
    # Whatever an environment lost is copied back from the server's own, never overwritten.
    assert session_environment({"A": "1"}, inherited)["XDG_RUNTIME_DIR"] == "/run/user/1000"
    assert session_environment({"XDG_RUNTIME_DIR": "/mine"}, inherited)["XDG_RUNTIME_DIR"] == "/mine"


def test_confine_gives_systemd_run_the_server_libraries_and_comfy_the_engine_env(monkeypatch):
    """The probe uses the server env; systemd-run must too, or conda libcrypto shadows libsystemd."""
    from services import creation_runtime_confinement as confinement
    monkeypatch.setattr(confinement, "_support", SYSTEMD_RUN)
    monkeypatch.setattr(confinement, "_on_linux", lambda: True)
    monkeypatch.setattr(confinement, "physical_memory_bytes", lambda: 64 * GIB)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/server/lib")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1234/bus")
    engine = {"LD_LIBRARY_PATH": "/engine/lib", "PATH": "/engine/bin", "PYTHONNOUSERSITE": "1"}
    wrapped, runner_env, limits = confinement.confine(["/engine/bin/python", "main.py"], engine, 80)
    assert limits is not None
    assert wrapped[0] == SYSTEMD_RUN and wrapped[wrapped.index("--") + 1:wrapped.index("--") + 4] == ["/usr/bin/env", "-i", "--"]
    assert "LD_LIBRARY_PATH=/engine/lib" in wrapped and wrapped[-2:] == ["/engine/bin/python", "main.py"]
    assert runner_env["LD_LIBRARY_PATH"] == "/server/lib"
    assert runner_env["XDG_RUNTIME_DIR"] == "/run/user/1234"
    assert "LD_LIBRARY_PATH=/server/lib" not in wrapped


def test_systemd_run_does_not_inherit_the_engine_ld_library_path(confined, monkeypatch):
    monkeypatch.setattr(confined.service, "isolated_environment",
                        lambda python: {"LD_LIBRARY_PATH": "/engine/lib", "PATH": "/engine/bin"})
    monkeypatch.setenv("LD_LIBRARY_PATH", "/server/lib")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1234")
    confined.job(name="one")
    command, popen_env = confined.processes[0].command, confined.processes[0].kwargs["env"]
    assert popen_env["LD_LIBRARY_PATH"] == "/server/lib"
    assert "LD_LIBRARY_PATH=/engine/lib" in command
    assert command[command.index("--") + 1:command.index("--") + 4] == ["/usr/bin/env", "-i", "--"]
    assert "python" in command and "main.py" in command


def test_the_runtime_record_is_written_on_start_and_removed_on_stop(confined):
    confined.job(name="one")
    record = confined.service._record_path()
    saved = json.loads(record.read_text(encoding="utf-8"))
    assert saved["pid"] == confined.processes[0].pid and saved["owner"]["pid"] == os.getpid()
    assert saved["marker"] == str(confined.service.SERVICE_DIR / "extra_model_paths.json")
    confined.service.stop_runtime()
    assert not record.exists()
    confined.job(name="two", idle_seconds=0)
    assert not record.exists(), "A job that stops the runtime at once must not leave a record"


@pytest.fixture
def world(monkeypatch, tmp_path):
    """Fake /proc and fake signals: the orphan sweep never touches a real pid."""
    from types import SimpleNamespace
    from services import creation_runtime_confinement as confinement
    clock = _Clock()
    fake = SimpleNamespace(procs={}, ticks={}, sent=[], stubborn=set(), path=tmp_path / "runtime.json",
                           marker=str(tmp_path / "extra_model_paths.json"), confinement=confinement, clock=clock)

    def send(pid, number):
        fake.sent.append((pid, number))
        if number == signal.SIGKILL or pid not in fake.stubborn:
            fake.procs.pop(pid, None)

    def write(pid=777, owner=900, owner_start=5):
        fake.path.write_text(json.dumps({"pid": pid, "started": 1.0, "marker": fake.marker,
                                         "owner": {"pid": owner, "start": owner_start}}), encoding="utf-8")

    fake.write = write
    fake.comfy_cmdline = ["/engine/bin/python", "main.py", "--extra-model-paths-config", fake.marker]
    monkeypatch.setattr(confinement, "_cmdline", lambda pid: fake.procs.get(pid, []))
    monkeypatch.setattr(confinement, "_start_ticks", lambda pid: fake.ticks.get(pid))
    monkeypatch.setattr(confinement, "_send", send)
    monkeypatch.setattr(confinement, "time", SimpleNamespace(monotonic=clock.monotonic, sleep=clock.sleep, time=lambda: 1.0))
    return fake


def test_a_live_runtime_whose_server_died_is_stopped(world):
    world.procs[777] = world.comfy_cmdline
    world.write()
    assert world.confinement.sweep_orphan_runtime(world.path) == 777
    assert world.sent == [(777, signal.SIGTERM)]
    assert not world.path.exists()


def test_a_runtime_that_ignores_sigterm_is_killed_after_fifteen_seconds(world):
    world.procs[777] = world.comfy_cmdline
    world.stubborn.add(777)
    world.write()
    assert world.confinement.sweep_orphan_runtime(world.path) == 777
    assert world.sent == [(777, signal.SIGTERM), (777, signal.SIGKILL)]
    assert 15 <= world.clock.now - 10_000 < 25
    assert not world.path.exists()


def test_the_sweep_ignores_a_pid_that_is_not_the_runtime(world):
    world.procs[777] = ["/usr/bin/vim", "main.py"]  # the pid was reused by another program
    world.write()
    assert world.confinement.sweep_orphan_runtime(world.path) is None
    assert world.sent == [] and not world.path.exists(), "A stale record is dropped, the program it names is left alone"
    world.write(pid=778)
    assert world.confinement.sweep_orphan_runtime(world.path) is None and world.sent == [] and not world.path.exists()


def test_the_sweep_ignores_the_current_child_and_runtimes_of_a_live_server(world):
    world.procs[777] = world.comfy_cmdline
    world.write()
    assert world.confinement.sweep_orphan_runtime(world.path, keep_pid=777) is None
    assert world.sent == [] and world.path.exists()
    world.ticks[900] = 5  # the server that started it is still running (maybe this very process)
    assert world.confinement.sweep_orphan_runtime(world.path) is None
    assert world.sent == [] and world.path.exists()
    world.ticks[900] = 6  # same pid, other start time: that server is gone and its pid was reused
    assert world.confinement.sweep_orphan_runtime(world.path) == 777
    assert world.sent == [(777, signal.SIGTERM)]


def test_the_sweep_survives_a_missing_or_broken_record(world):
    assert world.confinement.sweep_orphan_runtime(world.path) is None
    world.path.write_text("{not json", encoding="utf-8")
    assert world.confinement.sweep_orphan_runtime(world.path) is None
    assert world.sent == []


def test_ensure_runtime_stops_an_orphan_before_it_starts_a_new_runtime(confined, world, monkeypatch):
    service = confined.service
    monkeypatch.setattr(service, "SERVICE_DIR", world.path.parent)
    world.marker = str(world.path.parent / "extra_model_paths.json")
    world.procs[777] = ["/engine/bin/python", "main.py", "--extra-model-paths-config", world.marker]
    world.write()
    confined.job(name="one")
    assert world.sent == [(777, signal.SIGTERM)]
    assert json.loads(world.path.read_text(encoding="utf-8"))["pid"] == confined.processes[0].pid


def _die_on_history(confined, monkeypatch, code):
    """The first history poll finds the process gone with exit ``code`` (the HTTP connection drops)."""
    service = confined.service
    real = service._request

    def die(method, base, suffix, **kwargs):
        if suffix.startswith("/history/"):
            confined.processes[-1].exit_code = code
            raise service.requests.ConnectionError("gone")
        return real(method, base, suffix, **kwargs)

    monkeypatch.setattr(service, "_request", die)
    return lambda: monkeypatch.setattr(service, "_request", real)


@pytest.mark.parametrize("code", [-9, 137])
def test_a_runtime_killed_while_a_job_is_pending_fails_with_the_memory_message(confined, monkeypatch, code):
    service = confined.service
    confined.job(name="one")
    heal = _die_on_history(confined, monkeypatch, code)
    with pytest.raises(RuntimeError, match=OOM_MESSAGE) as failure:
        confined.job(name="two")
    assert "lower creation_runtime_memory_percent and try again" in str(failure.value)
    assert service.runtime_status() == IDLE_STATUS and service._process is None
    assert not service._record_path().exists()
    heal()
    confined.job(name="three")
    assert len(confined.processes) == 2, "A runtime killed for memory must never be reused"


def test_a_runtime_killed_while_it_starts_fails_with_the_memory_message(confined):
    confined.state.update(healthy=False, exit_code=-9)
    with pytest.raises(RuntimeError, match=OOM_MESSAGE):
        confined.job(name="one")
    assert confined.service.runtime_status() == IDLE_STATUS


def test_any_other_exit_keeps_the_plain_message(confined, monkeypatch):
    confined.job(name="one")
    _die_on_history(confined, monkeypatch, 1)
    with pytest.raises(RuntimeError, match="stopped before returning its output"):
        confined.job(name="two")


def test_an_oom_kill_counted_in_the_cgroup_fails_the_job_even_if_the_process_survives(confined):
    confined.state["pending"] = 10**9
    confined.cgroup.oom_kills = 1
    with pytest.raises(RuntimeError, match=OOM_MESSAGE):
        confined.job(name="one")
    assert confined.processes[0].stopped.is_set() and confined.service.runtime_status() == IDLE_STATUS


def test_a_scope_the_kernel_did_not_limit_is_reported_as_not_confined(confined, monkeypatch, capsys):
    monkeypatch.setattr(confined.confinement, "verify_scope", lambda pid, limits: None)
    confined.job(name="one")
    assert confined.processes[0].command[0] == SYSTEMD_RUN
    assert confined.service.runtime_status()["confined"] is False
    assert "NOT confined" in capsys.readouterr().out


def test_the_memory_setting_reaches_the_runtime(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from services import creation_model_execution as execution
    seen = []

    def generate(params, job_id, out_dir, progress, cancelled, on_produce=None, idle_seconds=None, memory_percent=None):
        seen.append(memory_percent)
        return []

    monkeypatch.setattr(execution.service, "generate", generate)
    monkeypatch.setattr(execution, "record_job_outputs", lambda *args: None)
    monkeypatch.setattr(execution, "is_cancel_requested", lambda _: False)
    monkeypatch.setattr(execution, "finish_job", lambda *args, **kwargs: True)
    for services in ({"creation_runtime_memory_percent": 70}, {"creation_runtime_memory_percent": "lots"},
                     {"creation_runtime_memory_percent": 0}, {}):
        engine = SimpleNamespace(server_config={"services": services})
        state = SimpleNamespace(job={"out_dir": str(tmp_path)}, raw_params={"model_type": "drama3_base", "seed": 1},
                                job_id="job", start_time=0, finalize=True)
        execution.run_creation_job(state, engine=engine, publish=lambda *args: None)
    assert seen == [70, 80, 0, 80]


def test_services_config_accepts_the_memory_percent(monkeypatch):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.settings import create_settings_services_router
    from services import settings_store
    monkeypatch.setattr(settings_store, "wgp", None, raising=False)  # the router factory assigns it; the patch undoes that
    wgp = SimpleNamespace(server_config={})
    saved = []
    router = create_settings_services_router(
        wgp=wgp, _save_server_config=lambda: saved.append(True), _effective_llm_routing=lambda services: ("local", "", ""),
        _active_production_profile=lambda: {}, _normalize_production_profile=lambda profile: profile,
        _PRODUCTION_PROFILE_CONFIG_KEY="production_profile")
    app = FastAPI()
    app.include_router(router)
    reply = TestClient(app).put("/api/v1/services-config", json={"creation_runtime_memory_percent": 70})
    assert reply.status_code == 200 and reply.json()["updated"] == {"creation_runtime_memory_percent": 70}
    assert wgp.server_config["services"]["creation_runtime_memory_percent"] == 70 and saved


def _systemd_user_scope_works():
    import shutil
    launcher = shutil.which("systemd-run")
    if not sys.platform.startswith("linux") or launcher is None:
        return False
    try:
        return subprocess.run([launcher, "--user", "--scope", "--quiet", "true"], timeout=5,
                              capture_output=True, env=_real_session_environment()).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _real_session_environment():
    from services.creation_runtime_confinement import session_environment
    return session_environment(dict(os.environ))


def test_a_real_scope_has_its_own_cgroup_with_the_memory_limit(capsys):
    """No mocks: systemd itself puts a child in a cgroup of its own and the kernel holds the limit."""
    import shutil
    from services import creation_runtime_confinement as confinement
    if not _systemd_user_scope_works():
        pytest.skip("no systemd user manager on this machine")
    limits = {"max": 200 * 1024 * 1024, "high": 180 * 1024 * 1024}
    command = confinement.scope_command(shutil.which("systemd-run"), ["sleep", "20"], limits)
    assert "MemoryMax=209715200" in command
    process = subprocess.Popen(command, env=_real_session_environment())
    try:
        own = confinement.scope_cgroup(os.getpid())
        deadline = time.monotonic() + 10
        cgroup = confinement.scope_cgroup(process.pid)
        while cgroup == own and time.monotonic() < deadline:
            time.sleep(0.05)
            cgroup = confinement.scope_cgroup(process.pid)
        if cgroup is None or cgroup == own:
            pytest.skip("systemd did not move the child into a scope of its own")
        memory_max = cgroup / "memory.max"
        if not memory_max.is_file():
            pytest.skip("the memory controller is not delegated to this user manager")
        observed = {"own": f"/proc/{os.getpid()}/cgroup -> {own}", "scope": f"/proc/{process.pid}/cgroup -> {cgroup}",
                    "memory.max": memory_max.read_text().strip(), "memory.high": (cgroup / "memory.high").read_text().strip(),
                    "verify_scope": confinement.verify_scope(process.pid, limits)}
        with capsys.disabled():
            print()
            for name, value in observed.items():
                print(f"[real scope] {name}: {value}")
        assert cgroup != own and not cgroup.is_relative_to(own), "The runtime scope must not live inside the server's cgroup"
        assert observed["memory.max"] == "209715200" and observed["memory.high"] == "188743680"
        assert observed["verify_scope"] == cgroup
    finally:
        process.terminate()
        exit_code = process.wait(timeout=10)
    assert exit_code == -signal.SIGTERM, "terminate() must reach the program, not a wrapper"
