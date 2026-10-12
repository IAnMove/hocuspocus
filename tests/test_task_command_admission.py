"""Contract tests for atomic TaskRegistry command admission.

These tests exercise the durable admission boundary only.  Admission creates
one queued task, its creation event and a replayable receipt; it does not start
the worker or prove that a provider has executed the task.
"""

from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import copy
import hashlib
import json
import multiprocessing
import sqlite3

import pytest

from services.task_command_admission import TaskCommandConflict
from services.task_manager import TaskRegistry


def _command_input(*, workspace: str = "workspace-a", prompt: str = "literal prompt") -> dict:
    return {
        "workspace": workspace,
        "model_type": "pi_flux2",
        "prompt": prompt,
        "negative_prompt": "avoid blur",
        "resolution": "512x512",
        "num_inference_steps": 1,
        "seed": -1,
        "guidance_scale": 1.0,
        "generation_mode": "image",
        "image_mode": 1,
        "video_length": 1,
    }


def _original_and_effective(intent_id: str, *, prompt: str = "literal prompt") -> tuple[dict, dict]:
    original = {
        "version": 1,
        "operation": "generation.image",
        "intent_id": intent_id,
        "input": _command_input(prompt=prompt),
    }
    effective = copy.deepcopy(original)
    return original, effective


def _digest(effective: dict) -> str:
    payload = json.dumps(effective, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _task_fields(
    task_id: str,
    *,
    backend_job_id: str | None = None,
    workspace: str = "workspace-a",
    status: str = "queued",
) -> dict:
    return {
        "id": task_id,
        "root_id": f"root-{task_id}",
        "parent_id": None,
        "kind": "image",
        "workflow": "generation.image",
        "title": "Image admission",
        "status": status,
        "phase": "queued",
        "message": "Queued for image generation",
        "workspace": workspace,
        "backend_job_id": backend_job_id if backend_job_id is not None else f"backend-{task_id}",
        "current": 0,
        "total": 1,
        "resource_requirements": ["local_gpu:0"],
        "recoverable": True,
        "metadata": {"command_scope": "test"},
    }


def _admit(
    registry: TaskRegistry,
    intent_id: str,
    *,
    operation: str = "generation.image",
    digest: str | None = None,
    original: dict | None = None,
    effective: dict | None = None,
    task_id: str | None = None,
    workspace: str = "workspace-a",
    status: str = "queued",
    backend_job_id: str | None = None,
) -> dict:
    if original is None or effective is None:
        original, effective = _original_and_effective(intent_id)
    return registry.admit_command_task(
        intent_id=intent_id,
        operation=operation,
        digest=digest or _digest(effective),
        original=original,
        effective=effective,
        task_fields=_task_fields(
            task_id or f"task-{intent_id}",
            backend_job_id=backend_job_id,
            workspace=workspace,
            status=status,
        ),
    )


def _db_counts(registry: TaskRegistry) -> dict[str, int]:
    with sqlite3.connect(registry.path) as connection:
        return {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in ("tasks", "task_events", "task_command_admissions")
        }


def test_admission_commits_task_event_and_receipt_as_one_canonical_unit(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-atomic")

    result = _admit(
        registry,
        "intent-atomic",
        original=original,
        effective=effective,
        task_id="task-atomic",
    )

    assert result["replayed"] is False
    receipt = result["receipt"]
    assert receipt["status"] == "queued"
    assert receipt["taskIds"] == ["task-atomic"]
    assert receipt["result"] == {
        "job_id": "backend-task-atomic",
        "task_id": "task-atomic",
        "root_task_id": "root-task-atomic",
        "workspace": "workspace-a",
        "status": "queued",
    }
    assert registry.get("task-atomic")["status"] == "queued"
    assert [event["type"] for event in registry.events("task-atomic")] == ["task.created"]

    stored = registry.command_admission("intent-atomic")
    assert stored is not None
    assert stored["operation"] == "generation.image"
    assert stored["digest"] == _digest(effective)
    assert stored["task_id"] == "task-atomic"
    assert stored["original"] == original
    assert stored["effective"] == effective
    assert stored["receipt"] == receipt
    assert _db_counts(registry) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


def test_same_intent_and_digest_replays_without_second_task_or_event(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-replay")
    first = _admit(
        registry,
        "intent-replay",
        original=original,
        effective=effective,
        task_id="task-first",
    )

    # A retry may reconstruct a different local task candidate.  The durable
    # intent receipt remains authoritative and must be returned unchanged.
    retry_original, retry_effective = _original_and_effective(
        "intent-replay", prompt="candidate that must not replace the first request"
    )
    second = _admit(
        registry,
        "intent-replay",
        original=retry_original,
        effective=retry_effective,
        task_id="task-retry",
        digest=_digest(effective),
    )

    assert first["replayed"] is False
    assert second == {"receipt": first["receipt"], "replayed": True}
    assert registry.get("task-first") is not None
    assert registry.get("task-retry") is None
    assert registry.command_admission("intent-replay")["original"] == original
    assert _db_counts(registry) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


@pytest.mark.parametrize(
    ("operation", "digest"),
    [
        ("generation.video", None),
        ("generation.image", "different-digest"),
    ],
    ids=["operation-conflict", "digest-conflict"],
)
def test_same_intent_with_changed_operation_or_digest_is_rejected_atomically(
    tmp_path,
    operation,
    digest,
):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-conflict")
    first_digest = _digest(effective)
    _admit(
        registry,
        "intent-conflict",
        original=original,
        effective=effective,
        digest=first_digest,
        task_id="task-conflict",
    )

    with pytest.raises(TaskCommandConflict, match="different parameters"):
        _admit(
            registry,
            "intent-conflict",
            operation=operation,
            digest=digest or first_digest,
            task_id="task-conflicting-retry",
        )

    assert registry.get("task-conflicting-retry") is None
    assert registry.command_admission("intent-conflict")["digest"] == first_digest
    assert _db_counts(registry) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


def test_distinct_intents_with_identical_content_are_independent(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    first_original, first_effective = _original_and_effective("intent-one")
    second_original, second_effective = _original_and_effective("intent-two")
    digest = _digest(first_effective)

    first = _admit(
        registry,
        "intent-one",
        original=first_original,
        effective=first_effective,
        digest=digest,
        task_id="task-one",
    )
    second = _admit(
        registry,
        "intent-two",
        original=second_original,
        effective=second_effective,
        digest=digest,
        task_id="task-two",
    )

    assert first["replayed"] is False
    assert second["replayed"] is False
    assert first["receipt"]["taskIds"] != second["receipt"]["taskIds"]
    assert {task["id"] for task in registry.list()} == {"task-one", "task-two"}
    assert _db_counts(registry) == {
        "tasks": 2,
        "task_events": 2,
        "task_command_admissions": 2,
    }


def test_long_original_and_effective_literals_are_snapshotted_without_mutation(tmp_path):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    literal = ('  literal ñ line\nwith spaces and "quotes"  ' * 1_200)
    original, effective = _original_and_effective("intent-snapshot", prompt=literal)
    original_before = copy.deepcopy(original)
    effective_before = copy.deepcopy(effective)
    task_fields = _task_fields("task-snapshot")
    task_fields_before = copy.deepcopy(task_fields)

    result = registry.admit_command_task(
        intent_id="intent-snapshot",
        operation="generation.image",
        digest=_digest(effective),
        original=original,
        effective=effective,
        task_fields=task_fields,
    )

    original["input"]["prompt"] = "caller mutation"
    effective["input"]["prompt"] = "caller mutation"
    task_fields["metadata"]["command_scope"] = "caller mutation"
    result["receipt"]["result"]["status"] = "caller mutation"

    stored = registry.command_admission("intent-snapshot")
    assert stored["original"] == original_before
    assert stored["effective"] == effective_before
    assert registry.get("task-snapshot")["metadata"] == task_fields_before["metadata"]
    assert stored["receipt"]["status"] == "queued"
    assert stored["original"]["input"]["prompt"] == literal
    assert len(stored["original"]["input"]["prompt"]) == len(literal)


@pytest.mark.parametrize(
    ("status", "backend_job_id"),
    [("running", "backend-running"), ("queued", "")],
    ids=["non-queued-status", "missing-backend-id"],
)
def test_admission_requires_queued_task_with_backend_id(tmp_path, status, backend_job_id):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-invalid-task")

    with pytest.raises(ValueError, match="queued task and exact backend job ID"):
        _admit(
            registry,
            "intent-invalid-task",
            original=original,
            effective=effective,
            task_id="task-invalid-task",
            status=status,
            backend_job_id=backend_job_id,
        )

    assert registry.command_admission("intent-invalid-task") is None
    assert registry.get("task-invalid-task") is None
    assert registry.events("task-invalid-task") == []
    assert _db_counts(registry) == {
        "tasks": 0,
        "task_events": 0,
        "task_command_admissions": 0,
    }


def test_failure_before_commit_rolls_back_task_event_and_receipt(tmp_path, monkeypatch):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-before-commit")

    def fail_before_commit(*_args, **_kwargs):
        raise RuntimeError("injected insert failure")

    monkeypatch.setattr(registry, "_insert_task", fail_before_commit)
    with pytest.raises(RuntimeError, match="injected insert failure"):
        _admit(
            registry,
            "intent-before-commit",
            original=original,
            effective=effective,
            task_id="task-before-commit",
        )

    assert registry.get("task-before-commit") is None
    assert registry.events("task-before-commit") == []
    assert registry.command_admission("intent-before-commit") is None
    assert _db_counts(registry) == {
        "tasks": 0,
        "task_events": 0,
        "task_command_admissions": 0,
    }


def test_failure_after_commit_is_recoverable_as_replay(tmp_path, monkeypatch):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-after-commit")
    digest = _digest(effective)

    def fail_after_commit(_task):
        raise RuntimeError("injected post-commit notification failure")

    monkeypatch.setattr(registry, "_after_task_created", fail_after_commit)
    with pytest.raises(RuntimeError, match="post-commit"):
        _admit(
            registry,
            "intent-after-commit",
            original=original,
            effective=effective,
            digest=digest,
            task_id="task-after-commit",
        )

    # A fresh registry models process restart and supplies the unpatched
    # post-admission hook for the replay.  The committed receipt is durable.
    restarted = TaskRegistry(str(tmp_path), interrupt_stale=False)
    replay = _admit(
        restarted,
        "intent-after-commit",
        original=original,
        effective=effective,
        digest=digest,
        task_id="task-after-retry",
    )

    assert replay["replayed"] is True
    assert replay["receipt"]["taskIds"] == ["task-after-commit"]
    assert restarted.get("task-after-commit")["status"] == "queued"
    assert restarted.get("task-after-retry") is None
    assert _db_counts(restarted) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


def test_restart_rehydrates_admission_and_replay_without_dispatch(tmp_path):
    first = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-restart")
    admitted = _admit(
        first,
        "intent-restart",
        original=original,
        effective=effective,
        task_id="task-restart",
    )

    restarted = TaskRegistry(str(tmp_path), interrupt_stale=False)
    stored = restarted.command_admission("intent-restart")
    replay = _admit(
        restarted,
        "intent-restart",
        original=original,
        effective=effective,
        digest=_digest(effective),
        task_id="task-restart-retry",
    )

    assert stored["receipt"] == admitted["receipt"]
    assert replay == {"receipt": admitted["receipt"], "replayed": True}
    assert restarted.get("task-restart")["status"] == "queued"
    assert restarted.get("task-restart-retry") is None
    assert _db_counts(restarted) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


def _admit_from_process(arguments):
    workspace, intent_id, digest, original, effective, task_fields = arguments
    registry = TaskRegistry(workspace, interrupt_stale=False)
    result = registry.admit_command_task(
        intent_id=intent_id,
        operation="generation.image",
        digest=digest,
        original=original,
        effective=effective,
        task_fields=task_fields,
    )
    return result["replayed"], result["receipt"]


def test_independent_processes_serialize_one_intent_without_duplicates(tmp_path):
    workspace = str(tmp_path)
    intent_id = "intent-processes"
    original, effective = _original_and_effective(intent_id)
    digest = _digest(effective)
    task_fields = _task_fields("task-processes")
    arguments = (workspace, intent_id, digest, original, effective, task_fields)
    context = multiprocessing.get_context("spawn")

    with ProcessPoolExecutor(max_workers=4, mp_context=context) as pool:
        results = list(pool.map(_admit_from_process, [arguments] * 6))

    assert [replayed for replayed, _receipt in results].count(False) == 1
    assert [replayed for replayed, _receipt in results].count(True) == 5
    assert all(receipt == results[0][1] for _replayed, receipt in results)

    registry = TaskRegistry(workspace, interrupt_stale=False)
    assert registry.get("task-processes")["status"] == "queued"
    assert registry.command_admission(intent_id)["receipt"] == results[0][1]
    assert _db_counts(registry) == {
        "tasks": 1,
        "task_events": 1,
        "task_command_admissions": 1,
    }


@pytest.mark.parametrize("delete_terminal", [False, True], ids=["retained", "deleted"])
def test_receipt_survives_terminal_retention_or_deletion(tmp_path, delete_terminal):
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    original, effective = _original_and_effective("intent-terminal")
    admitted = _admit(
        registry,
        "intent-terminal",
        original=original,
        effective=effective,
        task_id="task-terminal",
    )
    registry.update(
        "task-terminal",
        status="completed",
        phase="completed",
        force=True,
        event_type="task.finished",
    )
    if delete_terminal:
        assert registry.delete("task-terminal") is True
        assert registry.get("task-terminal") is None
        assert registry.events("task-terminal")[-1]["type"] == "task.deleted"
    else:
        assert registry.get("task-terminal")["status"] == "completed"

    replay = _admit(
        registry,
        "intent-terminal",
        original=original,
        effective=effective,
        digest=_digest(effective),
        task_id="task-terminal-retry",
    )

    assert replay == {"receipt": admitted["receipt"], "replayed": True}
    assert registry.command_admission("intent-terminal")["receipt"] == admitted["receipt"]
    assert registry.get("task-terminal-retry") is None
    assert _db_counts(registry)["task_command_admissions"] == 1


def test_every_command_spec_fingerprint_version_can_be_admitted_and_replayed(tmp_path):
    """generation.video v3 (typed H3/LTX) froze fingerprint version 3 while the store took only 1 and 2: every real
    admission failed with "Unsupported command fingerprint version" and only validate=true worked."""
    import importlib
    from services.task_command_admission import FINGERPRINT_VERSIONS
    specs = ["image_generation_spec", "video_generation_spec", "video_generation_v3", "studio_sfx_spec", "tools_upscale_spec",
             "studio_music_spec", "studio_speech_spec", "studio_image_spec"]
    versions = {name: importlib.import_module(f"services.{name}").FINGERPRINT_VERSION for name in specs}
    assert set(versions.values()) <= set(FINGERPRINT_VERSIONS), versions
    registry = TaskRegistry(str(tmp_path), interrupt_stale=False)
    for version in sorted(set(versions.values())):
        intent = f"intent-v{version}"
        original, effective = _original_and_effective(intent)
        original["version"] = effective["version"] = 3
        admitted = registry.admit_command_task(intent_id=intent, operation="generation.video", digest=_digest(effective),
                                               original=original, effective=effective, task_fields=_task_fields(f"task-{intent}"),
                                               fingerprint_version=version)
        again = registry.admit_command_task(intent_id=intent, operation="generation.video", digest=_digest(effective),
                                            original=original, effective=effective, task_fields=_task_fields(f"task-{intent}-2"),
                                            fingerprint_version=version)
        assert again["receipt"] == admitted["receipt"] and registry.command_admission(intent)["fingerprint_version"] == version
        if version >= 2:
            assert admitted["receipt"]["fingerprintVersion"] == version and admitted["receipt"]["contentFingerprint"] == _digest(effective)
