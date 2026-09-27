"""Provider-free adversarial tests for shared image command admission.

The fake native facade below deliberately calls the admission capability only
after it has validated the request.  No test starts a model worker: these
checks exercise the durable task boundary, replay/claim semantics and the HTTP
and MCP projections around it.
"""

from __future__ import annotations

import asyncio
import ast
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
import sqlite3
import threading

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from routers.image_generation_commands import (
    create_image_generation_commands_router,
    image_command_catalog,
    image_command_handlers,
)
from routers.wangp_mcp import create_wangp_mcp_router
from services.image_generation_commands import (
    ImageGenerationCommands,
    validate_image_model,
)
from services.image_generation_runtime import create_image_generation_commands
from services.image_generation_spec import freeze_image_generation_spec
from services.task_manager import TaskRegistry


def _run(awaitable):
    return asyncio.run(awaitable)


def _command(intent_id: str = "image-intent-1", **input_overrides) -> dict:
    image_input = {
        "workspace": "workspace-a",
        "model_type": "pi_flux2",
        "prompt": '  literal "mañana"\nsecond line  ',
        "negative_prompt": " avoid blur  ",
        "resolution": "512x512",
        "num_inference_steps": 1,
        "seed": -1,
        "guidance_scale": 1.0,
    }
    image_input.update(input_overrides)
    return {
        "version": 1,
        "operation": "generation.image",
        "intent_id": intent_id,
        "input": image_input,
    }


def _task_fields(job: dict) -> dict:
    task_id = f"task-{job['id']}"
    return {
        "id": task_id,
        "root_id": f"root-{task_id}",
        "kind": "image",
        "workflow": "generation.image",
        "title": "Image admission",
        "status": "queued",
        "phase": "queued",
        "message": "Queued for image generation",
        "workspace": job["workspace"],
        "backend_job_id": job["id"],
        "current": 0,
        "total": 1,
        "resource_requirements": ["local_gpu:0"],
        "recoverable": True,
        "metadata": {"command_scope": "test"},
    }


class FakeNative:
    """Small native facade with no inference side effects."""

    def __init__(self, root, *, interrupt_stale=False):
        self.root = Path(root)
        self.interrupt_stale = interrupt_stale
        self._registries = {}
        self._job_number = 0
        self._lock = threading.RLock()
        self.prepare_calls = 0
        self.preflight_calls = 0
        self.native_validated = False
        self.callback_after_validation = False
        self.prepare_error = None
        self.preflight_error = None
        self.make_job_error = None
        self.persist_error = None
        self.dispatch_error = None
        self.persist_calls = []
        self.dispatch_calls = []
        self.persisted = {}
        self.active = set()

    def registry(self, workspace):
        with self._lock:
            if workspace not in self._registries:
                self._registries[workspace] = TaskRegistry(
                    str(self.root / workspace), interrupt_stale=self.interrupt_stale,
                )
            return self._registries[workspace]

    def preflight(self, _params):
        self.preflight_calls += 1
        if self.preflight_error is not None:
            raise self.preflight_error

    async def prepare(self, request):
        self.prepare_calls += 1
        if self.prepare_error is not None:
            raise self.prepare_error
        body = await request.json()
        # This is the ordering contract of the native facade: model/request
        # validation happens before transferring the in-process capability.
        self.native_validated = True
        workspace = body.pop("workspace")
        provenance = body.pop("provenance")
        self.callback_after_validation = self.native_validated
        return request.admit_generation_command(body, workspace, provenance)

    def make_job(self, body, workspace, *, job_id=None, created_at=None,
                 reserve_generation=False, publish_task=False, provenance=None):
        del reserve_generation, publish_task
        if self.make_job_error is not None:
            raise self.make_job_error
        with self._lock:
            self._job_number += 1
            number = self._job_number
        return {
            "id": job_id or f"backend-image-{number}",
            "status": "queued",
            "created_at": created_at if created_at is not None else float(1000 + number),
            "params": deepcopy(body),
            "workspace": workspace,
            "provenance": deepcopy(provenance or {}),
        }

    @staticmethod
    def task_fields(job):
        return _task_fields(job)

    def persist_recovery(self, job):
        if self.persist_error is not None:
            raise self.persist_error
        with self._lock:
            self.persist_calls.append(deepcopy(job))
            self.persisted[job["id"]] = deepcopy(job)

    def dispatch(self, job):
        # Record the attempted start before raising to model a lost response
        # after a worker was handed the job.
        with self._lock:
            self.dispatch_calls.append(deepcopy(job))
            self.active.add(job["id"])
        if self.dispatch_error is not None:
            raise self.dispatch_error

    def active_job_ids(self):
        with self._lock:
            return set(self.active)

    def service(self):
        return ImageGenerationCommands(
            registry=self.registry,
            prepare=self.prepare,
            preflight=self.preflight,
            make_job=self.make_job,
            task_fields=self.task_fields,
            dispatch=self.dispatch,
            persist_recovery=self.persist_recovery,
            active_job_ids=self.active_job_ids,
        )


def _db_counts(registry: TaskRegistry) -> dict[str, int]:
    with sqlite3.connect(registry.path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("tasks", "task_events", "task_command_admissions")
        }


def test_submit_uses_native_validation_then_one_durable_dispatch_and_preserves_literals(tmp_path):
    native = FakeNative(tmp_path)
    command = _command()
    result = _run(native.service().submit(command))

    assert result["replayed"] is False
    assert result["receipt"]["status"] == "queued"
    assert native.prepare_calls == 1
    assert native.native_validated is True
    assert native.callback_after_validation is True
    assert len(native.dispatch_calls) == 1

    stored = native.registry("workspace-a").command_admission(command["intent_id"])
    assert stored["original"] == command
    assert stored["original"]["input"]["prompt"] == '  literal "mañana"\nsecond line  '
    assert stored["effective"]["input"]["prompt"] == stored["original"]["input"]["prompt"]
    assert stored["effective"]["input"]["generation_mode"] == "image"
    assert stored["effective"]["input"]["image_mode"] == 1
    assert stored["effective"]["runtime"]["workspace"] == "workspace-a"
    assert _db_counts(native.registry("workspace-a")) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


def test_same_intent_replays_without_a_second_worker_but_changed_content_conflicts(tmp_path):
    native = FakeNative(tmp_path)
    service = native.service()
    command = _command()
    first = _run(service.submit(command))
    second = _run(service.submit(deepcopy(command)))

    assert second == {"receipt": first["receipt"], "replayed": True}
    assert len(native.dispatch_calls) == 1
    assert _db_counts(native.registry("workspace-a"))["tasks"] == 1

    changed = deepcopy(command)
    changed["input"]["prompt"] = "different literal"
    with pytest.raises(HTTPException) as error:
        _run(service.submit(changed))
    assert error.value.status_code == 409
    assert error.value.detail["code"] == "intent_conflict"
    assert len(native.dispatch_calls) == 1


def _seed_undispatched(native: FakeNative, command: dict):
    frozen = freeze_image_generation_spec(command)
    params = deepcopy(frozen["effective"]["input"])
    workspace = params.pop("workspace")
    provenance = {
        "actor": "user",
        "capability": "generation.image",
        "command": {"command_id": command["intent_id"]},
    }
    job = native.make_job(params, workspace, provenance=provenance,
                          reserve_generation=False, publish_task=False)
    effective = deepcopy(frozen["effective"])
    effective["runtime"] = {
        "params": deepcopy(job["params"]),
        "workspace": workspace,
        "provenance": deepcopy(job["provenance"]),
    }
    registry = native.registry(workspace)
    registry.admit_command_task(
        intent_id=command["intent_id"], operation="generation.image",
        digest=frozen["fingerprint"], original=frozen["original"],
        effective=effective, task_fields=native.task_fields(job),
    )
    return native.service(), registry, registry.command_admission(command["intent_id"])


def test_concurrent_dispatch_claim_starts_only_one_worker(tmp_path):
    native = FakeNative(tmp_path)
    service, registry, entry = _seed_undispatched(native, _command("claim-race"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(service._dispatch_admitted, registry, entry) for _ in range(2)]
        [future.result() for future in futures]

    assert len(native.dispatch_calls) == 1
    assert registry.command_admission("claim-race")["dispatch_owner"] == service.owner


def test_native_failure_before_callback_has_no_admission_or_dispatch(tmp_path):
    native = FakeNative(tmp_path)
    native.prepare_error = HTTPException(422, {"code": "native_invalid", "message": "bad native input"})
    service = native.service()

    with pytest.raises(HTTPException) as error:
        _run(service.submit(_command("before-callback")))

    assert error.value.status_code == 422
    assert native.callback_after_validation is False
    assert native.dispatch_calls == []
    assert _db_counts(native.registry("workspace-a")) == {
        "tasks": 0,
        "task_events": 0,
        "task_command_admissions": 0,
    }


def test_make_job_storage_failure_happens_before_admission(tmp_path):
    native = FakeNative(tmp_path)
    native.make_job_error = OSError("cannot allocate native job")

    with pytest.raises(HTTPException) as error:
        _run(native.service().submit(_command("before-admission")))

    assert error.value.status_code == 503
    assert error.value.detail["code"] == "storage_unavailable"
    assert native.dispatch_calls == []
    assert _db_counts(native.registry("workspace-a"))["task_command_admissions"] == 0


def test_post_commit_notification_failure_leaves_replayable_admission(tmp_path, monkeypatch):
    native = FakeNative(tmp_path)
    service = native.service()
    registry = native.registry("workspace-a")

    def fail_after_commit(_task):
        raise RuntimeError("notification lost after commit")

    original_hook = registry._after_task_created
    monkeypatch.setattr(registry, "_after_task_created", fail_after_commit)
    with pytest.raises(RuntimeError, match="after commit"):
        _run(service.submit(_command("after-admission")))
    monkeypatch.setattr(registry, "_after_task_created", original_hook)

    assert len(native.dispatch_calls) == 0
    assert registry.command_admission("after-admission") is not None
    retry = _run(service.submit(_command("after-admission")))
    assert retry["replayed"] is True
    assert len(native.dispatch_calls) == 1
    assert _db_counts(registry)["tasks"] == 1


def test_recovery_persistence_failure_is_retryable_without_new_task(tmp_path):
    native = FakeNative(tmp_path)
    service = native.service()
    command = _command("persist-failure")
    native.persist_error = OSError("durable queue unavailable")

    with pytest.raises(HTTPException) as error:
        _run(service.submit(command))
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "storage_unavailable"
    assert native.dispatch_calls == []
    assert native.registry("workspace-a").command_admission(command["intent_id"])["dispatch_owner"] is None

    native.persist_error = None
    retry = _run(service.submit(command))
    assert retry["replayed"] is True
    assert len(native.dispatch_calls) == 1
    assert _db_counts(native.registry("workspace-a"))["tasks"] == 1


def test_dispatch_started_then_raised_claims_once_and_never_retries_implicitly(tmp_path):
    native = FakeNative(tmp_path)
    service = native.service()
    command = _command("dispatch-uncertain")
    native.dispatch_error = RuntimeError("thread start response lost")

    with pytest.raises(HTTPException) as error:
        _run(service.submit(command))
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "dispatch_uncertain"
    assert len(native.dispatch_calls) == 1

    native.dispatch_error = None
    retry = _run(service.submit(command))
    assert retry["replayed"] is True
    assert len(native.dispatch_calls) == 1
    assert native.registry("workspace-a").command_admission(command["intent_id"])["dispatch_owner"] is not None


def test_native_thread_start_failure_removes_job_and_marks_task_interrupted(tmp_path, monkeypatch):
    native = FakeNative(tmp_path)
    registry = native.registry("workspace-a")
    job = {
        "id": "backend-thread-start-failure",
        "task_id": "task-backend-thread-start-failure",
        "workspace": "workspace-a",
        "status": "queued",
        "phase": "queued",
        "message": "Queued",
        "created_at": 1001.0,
    }
    registry.create(**_task_fields(job))
    registered = []
    cancelled_idle_release = []

    class FailingThread:
        ident = None

        def __init__(self, *_args, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("thread start failed")

    monkeypatch.setattr("services.image_generation_runtime.threading.Thread", FailingThread)
    service = create_image_generation_commands({
        "_durable_generation_queue": object(),
        "_run_generation_with_preparation": lambda _job_id: None,
        "_jobs": {},
        "register_generation_job": lambda _lock, current: registered.append(current),
        "_gen_lock": object(),
        "_cancel_h3_idle_release": lambda: cancelled_idle_release.append(True),
        "_active_gen_states": {},
        "_task_registry": lambda _workspace: registry,
        "generate": None,
        "_new_generation_job": None,
        "_generation_task_fields": None,
    })

    with pytest.raises(RuntimeError, match="thread start failed"):
        service.dispatch(job)

    assert registered == [job]
    assert cancelled_idle_release == [True]
    assert service.active_job_ids() == set()
    task = registry.get(job["task_id"])
    assert task["status"] == "interrupted"
    assert task["phase"] == "dispatch_failed"


def test_restart_marks_queued_task_interrupted_and_projects_recovery_without_starting(tmp_path):
    native = FakeNative(tmp_path)
    command = _command("restart-recovery")
    first = _run(native.service().submit(command))
    first_registry = native.registry("workspace-a")
    task_id = first["receipt"]["taskIds"][0]
    backend_id = first["receipt"]["result"]["job_id"]
    assert first_registry.get(task_id)["status"] == "queued"

    restarted_native = FakeNative(tmp_path, interrupt_stale=True)
    restarted_service = restarted_native.service()
    restarted_registry = restarted_native.registry("workspace-a")
    assert restarted_registry.get(task_id)["status"] == "interrupted"

    restarted_service.restore_recovery(["workspace-a"])

    assert restarted_native.dispatch_calls == []
    assert restarted_native.persisted[backend_id]["status"] == "interrupted"
    assert restarted_native.persisted[backend_id]["params"]["prompt"] == command["input"]["prompt"]
    receipt = restarted_service.receipt("workspace-a", command["intent_id"])
    assert receipt["receipt"] == first["receipt"]
    assert receipt["task"]["status"] == "interrupted"


@pytest.mark.parametrize("invalid", ["old copy", "backup.old", "café", "../outside"])
def test_invalid_listed_workspace_does_not_block_recovery_restore(tmp_path, invalid):
    native = FakeNative(tmp_path)
    command = _command("listed-invalid-workspace")
    first = _run(native.service().submit(command))
    backend_id = first["receipt"]["result"]["job_id"]

    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = restarted.service()
    service.restore_recovery([invalid, "workspace-a"])

    assert restarted.dispatch_calls == []
    assert restarted.persisted[backend_id]["status"] == "interrupted"
    assert service.filter_recovery([restarted.persisted[backend_id]]) == [restarted.persisted[backend_id]]


def _queue_record(job_id, workspace, *, capability, command_id=None, params=None):
    provenance = {"capability": capability}
    if command_id is not None:
        provenance["command"] = {"command_id": command_id}
    return {
        "id": job_id,
        "status": "interrupted",
        "workspace": workspace,
        "params": params or {"model_type": "pi_flux2", "prompt": job_id},
        "provenance": provenance,
    }


def test_orphaned_image_leftover_does_not_block_other_recovery(tmp_path):
    native = FakeNative(tmp_path)
    command = _command("linked-recovery")
    first = _run(native.service().submit(command))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = restarted.service()
    service.restore_recovery(["workspace-a"])
    linked = restarted.persisted[first["receipt"]["result"]["job_id"]]
    video = _queue_record("video-leftover", "workspace-b", capability="generation.video")
    orphan = _queue_record(
        "orphan-image", "deleted-workspace",
        capability="generation.image", command_id="missing-admission",
    )
    drifted = _queue_record(
        "drifted-job", "workspace-a",
        capability="generation.image", command_id=command["intent_id"],
    )
    invalid_workspace = _queue_record(
        "bad-workspace", "../outside",
        capability="generation.image", command_id="any-intent",
    )

    retained = service.filter_recovery([video, orphan, drifted, invalid_workspace, linked])

    assert [record["id"] for record in retained] == ["video-leftover", linked["id"]]
    service.discard_recovery([video, orphan, drifted, invalid_workspace, linked])
    assert restarted.registry("workspace-a").get(first["receipt"]["taskIds"][0])["status"] == "cancelled"
    assert service.filter_recovery([video, orphan, linked]) == [video]


@pytest.mark.parametrize("provenance", ["corrupt", ["bad"], {"capability": []}, {"capability": "generation.image", "command": "bad"},
                                        {"capability": "generation.image", "command": {"command_id": ["bad"]}}])
def test_malformed_leftover_metadata_does_not_block_valid_legacy_rows(tmp_path, provenance):
    service = FakeNative(tmp_path).service()
    malformed = _queue_record("malformed", "workspace-a", capability="generation.image")
    malformed["provenance"] = provenance
    legacy = _queue_record("legacy", "workspace-a", capability="generation.video")
    assert service.filter_recovery([malformed, legacy]) == [legacy]
    service.discard_recovery([malformed, legacy])


def _recovery_http_app(service, queue, workspaces=None):
    """Execute the actual route so storage failure cannot fall through to discard."""
    source = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    names = {"_recovery_job_summary", "get_generation_queue_recovery", "discard_generation_queue"}
    app = FastAPI()
    listed = workspaces if workspaces is not None else [{"name": "workspace-a"}]
    namespace = {"api": app, "_queue_recovery_lock": threading.Lock(), "_jobs": {},
                 "_image_generation_commands": service, "_durable_generation_queue": queue,
                 "_list_workspaces": lambda: listed}
    selected = ast.Module(body=[node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names],
                          type_ignores=[])
    exec(compile(selected, str(source), "exec"), namespace)
    return app


@pytest.mark.parametrize("storage_error", [sqlite3.OperationalError("database is locked"), OSError("disk unavailable")])
@pytest.mark.parametrize("failure_phase", ["restore", "link", "update"])
def test_recovery_http_storage_failure_preserves_queue_and_interrupted_task(tmp_path, monkeypatch, storage_error, failure_phase):
    from services.durable_generation_queue import DurableGenerationQueue

    native = FakeNative(tmp_path)
    accepted = _run(native.service().submit(_command("storage-recovery")))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = restarted.service()
    service.restore_recovery(["workspace-a"])
    queue = DurableGenerationQueue(str(tmp_path / "queue.json"))
    for record in restarted.persisted.values():
        queue.upsert(record)
    before = queue.list()
    registry = restarted.registry("workspace-a")

    def unavailable(*_args, **_kwargs):
        raise storage_error

    monkeypatch.setattr(registry, "update" if failure_phase == "update" else "command_admission", unavailable)
    if failure_phase == "link":
        monkeypatch.setattr(service, "restore_recovery", lambda _workspaces: None)
    with TestClient(_recovery_http_app(service, queue)) as client:
        for method, path in (("get", "/api/v1/jobs/recovery"), ("post", "/api/v1/jobs/recovery/discard")):
            response = getattr(client, method)(path)
            if failure_phase == "update" and method == "get":
                assert response.status_code == 200
            else:
                assert response.status_code == 503
                assert response.json()["detail"]["code"] == "storage_unavailable"
            assert queue.list() == before
            assert registry.get(accepted["receipt"]["taskIds"][0])["status"] == "interrupted"


def test_recovery_http_skips_invalid_listed_workspaces_and_keeps_valid_leftovers(tmp_path):
    from services.durable_generation_queue import DurableGenerationQueue

    native = FakeNative(tmp_path)
    accepted = _run(native.service().submit(_command("listed-folder-recovery")))
    restarted = FakeNative(tmp_path, interrupt_stale=True)
    service = restarted.service()
    service.restore_recovery(["workspace-a"])
    queue = DurableGenerationQueue(str(tmp_path / "queue.json"))
    for record in restarted.persisted.values():
        queue.upsert(record)
    listed = [{"name": "old copy"}, {"name": "workspace-a"}, {"name": "backup.old"}]
    with TestClient(_recovery_http_app(service, queue, listed)) as client:
        response = client.get("/api/v1/jobs/recovery")
        assert response.status_code == 200
        assert response.json()["jobs"][0]["job_id"] == accepted["receipt"]["result"]["job_id"]
        discarded = client.post("/api/v1/jobs/recovery/discard")
        assert discarded.status_code == 200
        assert discarded.json()["discarded"]
        assert queue.list() == []
        assert restarted.registry("workspace-a").get(accepted["receipt"]["taskIds"][0])["status"] == "cancelled"


def test_queued_admission_is_not_a_recovery_candidate_while_dispatch_is_pending(tmp_path):
    native = FakeNative(tmp_path)
    service, registry, _entry = _seed_undispatched(native, _command("queued-not-recovery"))

    assert registry.command_recovery_candidates() == []
    service.restore_recovery(["workspace-a"])
    assert registry.command_recovery_candidates() == []
    assert native.persist_calls == []
    assert native.dispatch_calls == []


def test_discarded_interrupted_admission_does_not_reappear_on_restore(tmp_path):
    native = FakeNative(tmp_path)
    command = _command("discard-recovery")
    first = _run(native.service().submit(command))
    task_id = first["receipt"]["taskIds"][0]

    restarted_native = FakeNative(tmp_path, interrupt_stale=True)
    restarted_service = restarted_native.service()
    registry = restarted_native.registry("workspace-a")
    restarted_service.restore_recovery(["workspace-a"])
    record = restarted_native.persisted[first["receipt"]["result"]["job_id"]]
    assert restarted_service.filter_recovery([record]) == [record]
    persist_count = len(restarted_native.persist_calls)

    restarted_service.discard_recovery([record])

    assert registry.get(task_id)["status"] == "cancelled"
    assert restarted_service.filter_recovery([record]) == []
    restarted_service.restore_recovery(["workspace-a"])
    assert len(restarted_native.persist_calls) == persist_count


def test_recovery_skips_an_interrupted_record_still_owned_by_an_active_job(tmp_path):
    native = FakeNative(tmp_path)
    command = _command("active-recovery-owner")
    first = _run(native.service().submit(command))
    backend_id = first["receipt"]["result"]["job_id"]

    restarted_native = FakeNative(tmp_path, interrupt_stale=True)
    restarted_native.active.add(backend_id)
    restarted_native.service().restore_recovery(["workspace-a"])

    assert restarted_native.persist_calls == []
    assert restarted_native.dispatch_calls == []


def test_preflight_rejects_uninstalled_or_non_image_models_before_native_prepare(tmp_path):
    native = FakeNative(tmp_path)
    native.preflight_error = HTTPException(
        409, {"code": "model_unavailable", "message": "not downloaded", "retryable": False},
    )
    service = native.service()
    with pytest.raises(HTTPException) as unavailable:
        _run(service.submit(_command("missing-model")))
    assert unavailable.value.status_code == 409
    assert native.prepare_calls == 0

    with pytest.raises(HTTPException) as wrong_model:
        validate_image_model(
            {"model_type": "audio-model", "resolution": "512x512"},
            model_definition=lambda _name: {"image_outputs": True, "returns_audio": True},
            model_downloaded=lambda _name: True,
        )
    assert wrong_model.value.status_code == 422
    assert wrong_model.value.detail["code"] == "unsupported_model"


@pytest.mark.parametrize(
    ("params", "code"),
    [
        ({"model_type": "pi_flux2", "resolution": "513x512"}, "invalid_resolution"),
        ({"model_type": "pi_flux2", "resolution": "64x4097"}, "invalid_resolution"),
        ({"model_type": "pi_flux2", "resolution": "512x512"}, "model_unavailable"),
    ],
    ids=["bad-resolution", "out-of-range-resolution", "not-downloaded"],
)
def test_model_validation_rejects_bad_resolution_and_missing_files(tmp_path, params, code):
    del tmp_path
    definitions = {"pi_flux2": {"image_outputs": True, "returns_audio": False}}
    downloaded = lambda _name: code != "model_unavailable"
    with pytest.raises(HTTPException) as error:
        validate_image_model(
            params,
            model_definition=lambda name: definitions.get(name),
            model_downloaded=downloaded,
        )
    assert error.value.detail["code"] == code


def test_missing_image_weights_identify_the_model_and_files():
    with pytest.raises(HTTPException) as error:
        validate_image_model(
            {"model_type": "qwen_image_21_uncensored_gguf_q6_k", "resolution": "1024x1024"},
            model_definition=lambda _: {"image_outputs": True, "name": "Qwen Image 2.1 GGUF Q6_K"},
            model_downloaded=lambda _: False,
            missing_model_files=lambda _: ["qwen-image-2.1-Q6_K.gguf"],
        )
    assert error.value.status_code == 409
    assert error.value.detail["missing_files"] == ["qwen-image-2.1-Q6_K.gguf"]
    assert "Qwen Image 2.1 GGUF Q6_K" in error.value.detail["message"]
    assert "qwen-image-2.1-Q6_K.gguf" in error.value.detail["message"]


def test_service_rejects_unsupported_fields_and_workspace_paths_before_native_prepare(tmp_path):
    native = FakeNative(tmp_path)
    service = native.service()
    unsupported = _command("unsupported-field")
    unsupported["input"]["image_refs"] = []
    with pytest.raises(HTTPException) as extra:
        _run(service.submit(unsupported))
    assert extra.value.status_code == 422
    assert native.prepare_calls == 0

    invalid_workspace = _command("invalid-workspace")
    invalid_workspace["input"]["workspace"] = "../outside"
    with pytest.raises(HTTPException) as workspace:
        _run(service.submit(invalid_workspace))
    assert workspace.value.status_code == 422
    assert workspace.value.detail["code"] == "invalid_command"
    assert "workspace" in workspace.value.detail["message"]
    assert native.prepare_calls == 0


def _mcp_call(client, name, arguments, *, request_id=1, authorization="Bearer test-token"):
    return client.post(
        "/api/v1/wangp/mcp",
        headers={"Authorization": authorization},
        json={"jsonrpc": "2.0", "id": request_id, "method": "tools/call",
              "params": {"name": name, "arguments": arguments}},
    )


def _command_app(native: FakeNative, tmp_path):
    app = FastAPI()
    service = native.service()
    app.include_router(create_image_generation_commands_router(service))
    app.include_router(create_wangp_mcp_router(
        handlers=image_command_handlers(service),
        command_operations=image_command_catalog(),
        journal_path=Path(tmp_path) / "mcp-journal.sqlite",
        token_getter=lambda: "test-token",
    ))
    return TestClient(app)


def test_http_and_mcp_use_the_same_image_operation_and_receipt(tmp_path):
    native = FakeNative(tmp_path)
    client = _command_app(native, tmp_path)
    command = _command("http-mcp-same")

    http = client.post("/api/v1/generation/commands", json=command)
    assert http.status_code == 200
    http_body = http.json()
    assert http_body["replayed"] is False

    listed = client.post(
        "/api/v1/wangp/mcp",
        headers={"Authorization": "Bearer test-token"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ).json()["result"]["tools"]
    image_tool = next(tool for tool in listed if tool["name"] == "generation.image")
    assert "operation" not in image_tool["inputSchema"]["properties"]
    assert "operation" not in image_tool["inputSchema"]["required"]

    arguments = {key: value for key, value in command.items() if key != "operation"}
    mcp = _mcp_call(client, "generation.image", arguments, request_id=3).json()["result"]
    assert mcp["isError"] is False
    assert mcp["structuredContent"] == {**http_body, "replayed": True}
    assert len(native.dispatch_calls) == 1

    receipt_http = client.get(
        "/api/v1/generation/commands/receipt",
        params={"workspace": "workspace-a", "intent_id": command["intent_id"]},
    )
    assert receipt_http.status_code == 200
    receipt_mcp = _mcp_call(
        client, "generation.receipt",
        {"version": 1, "input": {"workspace": "workspace-a", "intent_id": command["intent_id"]}},
        request_id=4,
    ).json()["result"]
    assert receipt_mcp["isError"] is False
    assert receipt_mcp["structuredContent"] == receipt_http.json()

    assert _mcp_call(client, "generation.image", arguments, authorization="Bearer wrong").status_code == 401


def test_mcp_image_handler_rejects_transport_operation_field_outside_declared_schema(tmp_path):
    native = FakeNative(tmp_path)
    client = _command_app(native, tmp_path)
    arguments = {key: value for key, value in _command("mcp-operation-field").items() if key != "operation"}
    arguments["operation"] = "generation.video"

    result = _mcp_call(client, "generation.image", arguments, request_id=11).json()["result"]

    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "invalid_command"
    assert native.dispatch_calls == []


def test_http_and_mcp_expose_policy_rejection_without_admitting(tmp_path):
    native = FakeNative(tmp_path)
    native.preflight_error = HTTPException(
        403, {"code": "policy_denied", "message": "workspace policy", "retryable": False},
    )
    client = _command_app(native, tmp_path)
    command = _command("policy-denied")

    http = client.post("/api/v1/generation/commands", json=command)
    assert http.status_code == 403
    assert http.json()["detail"]["code"] == "policy_denied"

    arguments = {key: value for key, value in command.items() if key != "operation"}
    mcp = _mcp_call(client, "generation.image", arguments, request_id=8).json()["result"]
    assert mcp["isError"] is True
    assert mcp["structuredContent"]["status"] == "failed"
    assert mcp["structuredContent"]["error"]["code"] == "policy_denied"
    assert native.dispatch_calls == []


@pytest.mark.parametrize(
    ("column", "value"),
    [("effective", "not-json"), ("receipt", "{}"), ("dispatch_owner", "")],
    ids=["invalid-json-snapshot", "invalid-receipt-shape", "empty-dispatch-owner"],
)
def test_corrupt_admission_snapshots_fail_closed_without_replaying_or_dispatching(tmp_path, column, value):
    native = FakeNative(tmp_path)
    service = native.service()
    command = _command(f"corrupt-{column}")
    _run(service.submit(command))
    registry = native.registry("workspace-a")
    with sqlite3.connect(registry.path) as connection:
        connection.execute(
            f"UPDATE task_command_admissions SET {column} = ? WHERE intent_id = ?",
            (value, command["intent_id"]),
        )

    with pytest.raises(HTTPException) as error:
        _run(service.submit(command))
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "storage_unavailable"
    assert len(native.dispatch_calls) == 1
    assert _db_counts(registry)["tasks"] == 1
