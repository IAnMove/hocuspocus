"""Creation models keep reference identities, native contracts and cancellation."""
import subprocess
import threading
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


class _FakeComfy:
    """A ComfyUI process that never starts: records the launch and answers the poll."""

    def __init__(self, command, **kwargs):
        self.command, self.kwargs = command, kwargs
        self.stdout = iter(())
        self.stopped = threading.Event()

    def poll(self):
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
    state = {"healthy": True, "history": "ok", "prompts": 0}
    output = tmp_path / "runtime" / "output"
    output.mkdir(parents=True)
    (output / "take.flac").write_bytes(b"generated audio")

    def popen(command, **kwargs):
        processes.append(_FakeComfy(command, **kwargs))
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
    assert comfy.service.runtime_status() == {"warm": False, "family": None, "idle_seconds_left": None}


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
    assert comfy.service.runtime_status() == {"warm": False, "family": None, "idle_seconds_left": None}
    comfy.job("flux3_klein", idle_seconds=120)
    status = comfy.service.runtime_status()
    assert status["warm"] is True and status["family"] == "flux"
    assert 100 < status["idle_seconds_left"] <= 120
    comfy.service.stop_runtime()
    assert comfy.service.runtime_status() == {"warm": False, "family": None, "idle_seconds_left": None}


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
