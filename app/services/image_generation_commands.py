"""Shared native admission using preparation, tasks and the generation FIFO.

The receipt proves admission. TaskRegistry remains the progress authority and
the native generation queue remains the sole execution/recovery mechanism.
"""
from __future__ import annotations

from copy import deepcopy
import re
import sqlite3
import time
import uuid

from fastapi import HTTPException
from services.image_generation_spec import freeze_image_generation_spec, ImageGenerationSpecError
from services.task_command_admission import TaskCommandConflict
from services.wangp_submission import JsonRequest


def command_error(status: int, code: str, message: str):
    return HTTPException(status, {"code": code, "message": message, "retryable": status >= 500})


def validate_image_model(params, *, model_definition, model_downloaded, allow_references=False):
    definition = model_definition(params["model_type"])
    if not definition or not definition.get("image_outputs") or definition.get("returns_audio"):
        raise command_error(422, "unsupported_model", "Choose an exact text-to-image model from the model catalog")
    if definition.get("at_least_one_image_ref_needed") and not (allow_references and params.get("image_refs")):
        raise command_error(422, "reference_required", "This model requires references; choose a text-to-image model")
    if not model_downloaded(params["model_type"]):
        raise command_error(409, "model_unavailable", "Required model files are not installed; install them before submitting")
    match = re.fullmatch(r"([1-9][0-9]{1,4})x([1-9][0-9]{1,4})", params["resolution"])
    if not match or any(not 64 <= int(value) <= 4096 or int(value) % 8 for value in match.groups()):
        raise command_error(422, "invalid_resolution", "Resolution must be WIDTHxHEIGHT, each 64..4096 and a multiple of 8")
    return definition


class ImageGenerationCommands:
    def __init__(self, *, registry, prepare, preflight, make_job, task_fields,
                 dispatch, persist_recovery, active_job_ids, prepare_studio=None, runtime_defaults=None,
                 operations=None):
        self.registry = registry
        self.prepare = prepare
        self.preflight = preflight
        self.make_job = make_job
        self.task_fields = task_fields
        self.dispatch = dispatch
        self.persist_recovery = persist_recovery
        self.active_job_ids = active_job_ids
        self.prepare_studio = prepare_studio
        self.runtime_defaults = runtime_defaults or (lambda: {})
        self.operations = dict(operations or {})
        if "generation.image" in self.operations:
            raise ValueError("The existing image contract cannot be overridden")
        self.owner = uuid.uuid4().hex

    def _registry(self, workspace):
        # Exact physical output location; no active-browser fallback and no
        # collection-ID substitution. The native resolver enforces containment.
        if not isinstance(workspace, str) or not re.fullmatch(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)", workspace):
            raise command_error(422, "invalid_workspace", "Use an explicit valid output workspace")
        return self.registry(workspace)

    @staticmethod
    def _validate_replay(entry, frozen):
        if (entry["operation"] != frozen["original"]["operation"] or entry["digest"] != frozen["fingerprint"]
                or entry["fingerprint_version"] != frozen["fingerprint_version"]):
            raise TaskCommandConflict("intent_id was already used with different parameters or preconditions")

    def _dispatch_admitted(self, registry, entry):
        try:
            self._dispatch_pending(registry, entry)
        except HTTPException as error:
            if error.status_code >= 500:
                raise
            raise command_error(503, "admission_recovery_needed", "Admission is durable; consult its receipt and task before recovery") from error

    def _dispatch_pending(self, registry, entry):
        task = registry.get(entry["task_id"])
        if not task or task["status"] != "queued" or entry["dispatch_owner"] is not None:
            return
        runtime = entry["effective"]["runtime"]
        job = self.make_job(deepcopy(runtime["params"]), runtime["workspace"],
                            job_id=task["backend_job_id"], created_at=task["created_at"],
                            reserve_generation=False, publish_task=False,
                            provenance=deepcopy(runtime["provenance"]))
        # A failure here keeps admission pending and safely retryable. Unlike
        # legacy best-effort persistence, this path must not dispatch on failure.
        self.persist_recovery(job)
        if registry.claim_command_dispatch(entry["intent_id"], self.owner):
            try:
                self.dispatch(job)
            except Exception:
                # Dispatch may have started before raising. Never release the
                # claim or infer that a transport retry should start it again.
                raise command_error(503, "dispatch_uncertain", "Admission is durable; inspect its task before explicitly recovering") from None

    def _admit(self, frozen, body, workspace, provenance):
        registry = self._registry(workspace)
        provenance = deepcopy(provenance)
        provenance["command"]["command_id"] = frozen["original"]["intent_id"]
        adapter = self.operations.get(frozen["original"]["operation"])
        defaults = self.runtime_defaults() if adapter is None or adapter.use_generation_defaults else {}
        native_params = {**deepcopy(defaults), **deepcopy(body)}
        job = self.make_job(native_params, workspace, reserve_generation=False, publish_task=False, provenance=provenance)
        effective = deepcopy(frozen["effective"])
        effective["runtime"] = {"params": deepcopy(job["params"]), "workspace": workspace,
                                "provenance": deepcopy(job["provenance"])}
        admitted = registry.admit_command_task(
            intent_id=frozen["original"]["intent_id"], operation=frozen["original"]["operation"],
            digest=frozen["fingerprint"], original=frozen["original"], effective=effective,
            task_fields=self.task_fields(job), fingerprint_version=frozen["fingerprint_version"],
        )
        entry = registry.command_admission(frozen["original"]["intent_id"])
        self._dispatch_admitted(registry, entry)
        return admitted

    @staticmethod
    def _provenance(frozen, trusted_tool, context):
        command = {"command_id": frozen["original"]["intent_id"]}
        for source, target in (("workflowId", "workflow_id"), ("runId", "run_id")):
            if context and context.get(source):
                command[target] = context[source]
        result = {"actor": "wizard" if trusted_tool == "wizard" else "user",
                  "capability": frozen["original"]["operation"], "command": command}
        collection = frozen["original"]["input"].get("workspace_collection_id")
        if collection is not None:
            result["workspace_id"] = collection
        return result

    async def submit(self, command, *, trusted_tool=None, submission_context=None):
        try:
            frozen, params = self._freeze(command)
            registry = self._registry(params["workspace"])
            previous = registry.command_admission(command["intent_id"])
            if previous is not None:
                self._validate_replay(previous, frozen)
                self._dispatch_admitted(registry, previous)
                return {"receipt": previous["receipt"], "replayed": True}
            adapter = self.operations.get(command["operation"])
            if adapter is not None:
                params, resources = adapter.prepare(params)
                frozen["effective"]["resources"] = resources
            elif command["version"] == 2:
                if self.prepare_studio is None:
                    raise command_error(422, "unsupported_version", "Studio image commands are unavailable in this runtime")
                params, resources = self.prepare_studio(params)
                frozen["effective"]["resources"] = resources
            else:
                self.preflight(params)
            request = JsonRequest({**deepcopy(params), "provenance": self._provenance(
                frozen, trusted_tool, submission_context)}, trusted_tool=trusted_tool)
            request.prepared_studio_images = command["operation"] == "generation.image" and command["version"] == 2
            request.prepared_studio_speech = command["operation"] == "generation.speech"
            request.prepared_studio_audio = command["operation"] == "generation.music"
            request.prepared_studio_video = command["operation"] == "generation.video"
            # This callback is an in-process capability, never a JSON option.
            # The native facade performs its ordinary validation first and then
            # transfers admission to the same canonical task/worker adapter.
            request.admit_generation_command = lambda body, workspace, provenance: self._admit(frozen, body, workspace, provenance)
            prepare_request = adapter.prepare_request if adapter and adapter.prepare_request else self.prepare
            return await prepare_request(request)
        except ImageGenerationSpecError as error:
            raise command_error(422, "invalid_command", str(error)) from error
        except TaskCommandConflict as error:
            raise command_error(409, "intent_conflict", str(error)) from error
        except (OSError, sqlite3.Error) as error:
            raise command_error(503, "storage_unavailable", "Command storage is unavailable; retry with the same intention") from error

    def _freeze(self, command):
        if isinstance(command, dict) and isinstance(command.get("operation"), str):
            adapter = self.operations.get(command["operation"])
            if adapter is not None:
                return adapter.freeze(command)
        if isinstance(command, dict) and type(command.get("version")) is int and command["version"] == 2:
            from services.studio_image_spec import freeze_studio_image_spec
            frozen = freeze_studio_image_spec(command)
            params = {**deepcopy(frozen["effective"]["input"]["params"]),
                      "workspace": frozen["effective"]["input"]["workspace"]}
        else:
            frozen = freeze_image_generation_spec(command)
            params = frozen["effective"]["input"]
        return frozen, params

    def receipt(self, workspace, intent_id):
        if not isinstance(intent_id, str) or not 1 <= len(intent_id) <= 160:
            raise command_error(422, "invalid_command", "An exact intent_id is required")
        try:
            registry = self._registry(workspace)
            entry = registry.command_admission(intent_id)
            if entry is None:
                raise command_error(404, "receipt_not_found", "No admission exists for this intention in this workspace")
            return {"receipt": entry["receipt"], "task": registry.get(entry["task_id"])}
        except (OSError, sqlite3.Error) as error:
            raise command_error(503, "storage_unavailable", "Command storage is unavailable") from error

    def native_worker(self, job):
        """Select a tool worker only for its real durable admission.

        Public generation JSON and legacy provenance can never select a tool
        by themselves. Both normal dispatch and queue recovery check the
        existing canonical receipt before entering the registered worker.
        """
        provenance = job.get("provenance")
        if not isinstance(provenance, dict) or not isinstance(provenance.get("capability"), str):
            return None
        operation = provenance["capability"]
        adapter = self.operations.get(operation)
        if adapter is None or adapter.worker is None:
            return None
        linked = self._recovery_task(job)
        if not linked or linked[1] is None:
            raise command_error(503, "recovery_mismatch", "Tool worker requires its canonical task")
        return adapter.worker

    def restore_recovery(self, workspaces):
        """Rebuild only the existing recovery projection; never start inference."""
        try:
            self._restore_recovery(workspaces)
        except (OSError, sqlite3.Error) as error:
            raise command_error(503, "storage_unavailable", "Recovery storage is unavailable; no queue records were discarded") from error

    def _restore_recovery(self, workspaces):
        active = set(self.active_job_ids())
        for workspace in workspaces:
            try:
                registry = self._registry(workspace)
            except HTTPException as error:
                # `_list_workspaces` includes every outputs/ subdirectory.
                # A backup folder such as "old copy" must not 422 list/resume/discard.
                if error.status_code == 422:
                    continue
                raise
            for entry in registry.command_recovery_candidates():
                if entry["operation"] not in {"generation.image", *self.operations}:
                    # Another domain can share TaskRegistry without using
                    # this runtime's native generation recovery projection.
                    continue
                task = registry.get(entry["task_id"])
                if not task or task["status"] != "interrupted" or task["backend_job_id"] in active:
                    continue
                runtime = entry["effective"]["runtime"]
                # No model preflight: recovering the editable request must also
                # work while the original model is unavailable.
                self.persist_recovery({"id": task["backend_job_id"], "status": "interrupted",
                                       "created_at": task["created_at"], **deepcopy(runtime)})

    def _recovery_identity(self, record):
        if not isinstance(record, dict):
            return False
        provenance = record.get("provenance")
        if provenance is None:
            return None
        if not isinstance(provenance, dict):
            return False
        capability = provenance.get("capability")
        if capability is not None and not isinstance(capability, str):
            return False
        if capability not in {"generation.image", *self.operations}:
            return None
        command = provenance.get("command")
        if not isinstance(command, dict):
            return False
        intent_id = command.get("command_id")
        if not isinstance(intent_id, str) or not 1 <= len(intent_id) <= 160 or not intent_id.strip():
            return False
        return intent_id

    def _recovery_task(self, record):
        """Link one leftover to its admission, or withhold it.

        Unregistered operations return None for legacy native recovery.
        A linked command returns ``(registry, task)``. A registered row that
        cannot be matched (missing admission, invalid queue metadata or job-id
        drift) returns False so this one row is skipped. Storage failures,
        including corrupt canonical admissions, remain errors: discard must
        not delete recovery records while their tasks cannot be verified.
        """
        intent_id = self._recovery_identity(record)
        if intent_id is None or intent_id is False:
            return intent_id
        try:
            registry = self._registry(record.get("workspace"))
            entry = registry.command_admission(intent_id)
            if (entry is None or entry["operation"] != record["provenance"]["capability"]
                    or entry["receipt"]["result"]["job_id"] != record.get("id")):
                return False
            return registry, registry.get(entry["task_id"])
        except HTTPException as error:
            if error.status_code in {404, 422}:
                return False
            raise
        except (OSError, sqlite3.Error) as error:
            raise command_error(503, "storage_unavailable", "Recovery storage is unavailable; no queue records were discarded") from error
        except (TypeError, KeyError):
            return False

    def filter_recovery(self, records):
        retained = []
        for record in records:
            linked = self._recovery_task(record)
            if linked is False:
                continue
            if linked is None or (linked[1] and linked[1]["status"] == "interrupted"):
                retained.append(record)
        return retained

    def discard_recovery(self, records):
        for record in records:
            linked = self._recovery_task(record)
            if linked and linked[1] and linked[1]["status"] == "interrupted":
                registry, task = linked
                try:
                    registry.update(task["id"], status="cancelled", phase="recovery_discarded",
                                    message="Recovery discarded", completed_at=time.time(), recoverable=False)
                except (OSError, sqlite3.Error) as error:
                    raise command_error(503, "storage_unavailable", "Recovery storage is unavailable; no queue records were discarded") from error
