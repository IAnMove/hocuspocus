"""Provider-free checks for the speech adapter's runtime wiring.

These tests deliberately stop at the native request boundary.  They exercise
the real runtime factory and the real speech preparation adapter, while the
``generate`` callable is a small stand-in for the existing native facade.  No
model, worker or provider is loaded.
"""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from pathlib import Path
import threading

from services.image_generation_runtime import create_image_generation_commands
from services.native_generation_operation import NativeGenerationOperation
from services.task_manager import TaskRegistry
from services.wangp_submission import JsonRequest, prepare_generation_inputs


FIXTURE = Path(__file__).parent / "fixtures" / "studio_speech_native_request.json"


def _run(awaitable):
    return asyncio.run(awaitable)


def _speech_command(intent_id="runtime-speech-intent"):
    params = json.loads(FIXTURE.read_text(encoding="utf-8"))
    workspace = params.pop("workspace")
    return {
        "version": 2,
        "operation": "generation.speech",
        "intent_id": intent_id,
        "input": {"workspace": workspace, "params": params},
    }


def _task_fields(job):
    return {
        "id": f"task-{job['id']}",
        "root_id": f"task-{job['id']}",
        "kind": "audio",
        "workflow": "generation",
        "title": "Audio generation",
        "status": "queued",
        "phase": "queued",
        "message": "Queued",
        "workspace": job["workspace"],
        "backend_job_id": job["id"],
        "current": 0,
        "total": 1,
        "resource_requirements": ["local_gpu:0"],
        "recoverable": True,
    }


class _Queue:
    def __init__(self):
        self.jobs = []

    def upsert(self, job):
        self.jobs.append(deepcopy(job))


class _ExecutionMode:
    class ExecutionModeError(RuntimeError):
        pass

    def validate_generation(self, _workspace):
        return None


class _WGP:
    primary_settings = {}

    def __init__(self, definition):
        self.definition = definition

    def get_model_def(self, model_type):
        return deepcopy(self.definition) if model_type == "kugelaudio_0_open" else None

    def get_lora_search_dirs(self, _model_type):
        return []


def _runtime(tmp_path, observed, monkeypatch):
    definition = {
        "audio_only": True,
        "image_outputs": False,
        "inference_steps": False,
        "guidance_max_phases": 1,
        "duration_slider": {"min": 1, "max": 600, "default": 20},
        "audio_prompt_type_sources": {"selection": ["", "A", "AB"], "default": ""},
        "audio_mode_from_voice_count": True,
        "max_voice_count": 6,
    }
    queue = _Queue()
    registry = TaskRegistry(str(tmp_path / "runtime-speech"), interrupt_stale=False)
    jobs = {}
    dispatched = []
    started = threading.Event()

    def make_job(params, workspace, *, job_id=None, created_at=None,
                 reserve_generation=False, publish_task=False, provenance=None):
        del reserve_generation, publish_task
        job = {
            "id": job_id or "runtime-speech-job",
            "status": "queued",
            "created_at": created_at or 1000.0,
            "params": deepcopy(params),
            "workspace": workspace,
            "provenance": deepcopy(provenance or {}),
        }
        return job

    async def native_generate(request):
        body = await request.json()
        observed["prepared_speech"] = getattr(request, "prepared_studio_speech", False)
        observed["trusted_tool"] = getattr(request, "trusted_tool", None)
        observed["body_before_native_boundary"] = deepcopy(body)
        # This is the same in-process capability handoff performed by the
        # real /api/v1/generate route after its ordinary validation.
        workspace = body.pop("workspace")
        provenance = body.pop("provenance")
        prepare_generation_inputs(
            body,
            definition,
            workspace,
            uploads_dir=str(tmp_path / "uploads"),
            workspace_dir=str(tmp_path / workspace),
            prepared_speech=getattr(request, "prepared_studio_speech", False) is True,
        )
        observed["body_after_native_preparation"] = deepcopy(body)
        return request.admit_generation_command(body, workspace, provenance)

    runtime = {
        "_durable_generation_queue": queue,
        "_run_generation_with_preparation": lambda _job_id: started.set(),
        "_jobs": jobs,
        "_gen_lock": object(),
        "_cancel_h3_idle_release": lambda: None,
        "_active_gen_states": {},
        "_task_registry": lambda _workspace: registry,
        "generate": native_generate,
        "_new_generation_job": make_job,
        "_generation_task_fields": _task_fields,
        "execution_mode": _ExecutionMode(),
        "wgp": _WGP(definition),
        "_check_model_downloaded": lambda _model_type: True,
        "_workspace_dir": lambda workspace: str(tmp_path / workspace),
        "_list_workspaces": lambda: [{"name": "runtime-speech"}],
        "_lora_is_compatible_with_model": lambda _definition, _path: True,
    }
    # ``dispatch`` imports the shared FIFO registration; it is not a key of the runtime dict.
    monkeypatch.setattr("services.image_generation_runtime.register_generation_job",
                        lambda _lock, job: dispatched.append(("registered", deepcopy(job))))
    service = create_image_generation_commands(runtime)
    return service, registry, queue, dispatched, started


def test_runtime_factory_speech_adapter_reaches_native_boundary_once(tmp_path, monkeypatch):
    observed = {}
    service, registry, queue, dispatched, started = _runtime(tmp_path, observed, monkeypatch)

    adapter = service.operations["generation.speech"]
    assert isinstance(adapter, NativeGenerationOperation)
    assert adapter.catalog["name"] == "generation.speech"

    command = _speech_command()
    result = _run(service.submit(command, trusted_tool="external_agent"))

    assert result["replayed"] is False
    assert result["receipt"]["operation"] == "generation.speech"
    assert observed["prepared_speech"] is True
    assert observed["trusted_tool"] == "external_agent"
    assert observed["body_before_native_boundary"]["generation_mode"] == "audio"
    assert observed["body_after_native_preparation"]["generation_mode"] == "audio"
    assert len(dispatched) == 1
    assert started.wait(1)
    assert len(queue.jobs) == 1

    entry = registry.command_admission(command["intent_id"])
    assert entry is not None
    assert entry["operation"] == "generation.speech"
    assert entry["receipt"] == result["receipt"]
    assert entry["effective"]["runtime"]["params"]["prompt"] == command["input"]["params"]["prompt"]


def test_json_payload_cannot_forge_prepared_speech_capability():
    request = JsonRequest({"prepared_studio_speech": True})

    # The marker is an in-process capability set by ImageGenerationCommands;
    # arbitrary JSON keys must not become trusted request attributes.
    assert getattr(request, "prepared_studio_speech", False) is False
