"""The generation job registry, the single-GPU FIFO slot and the durable queue.

Everything here was module state and helper functions at the top of the full
server. The server builds one ``GenerationQueue`` and keeps its old names as
aliases to the same objects (``_jobs = queue.registry``), so code that has not
moved yet still shares the one dictionary, the one lock and the one durable
queue. Nothing is created at import time.

What belongs to the engine or to the task cluster arrives as an argument:
the two MiniMax H3 model predicates, the call that cancels the isolated H3
runtime, and a lookup for the function that publishes a job as a canonical
task (looked up on every call, so it may be defined after the queue is built).
"""
from __future__ import annotations

import copy
import os
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Callable

from services import execution_mode
from services import resource_scheduler
from services.durable_generation_queue import DurableGenerationQueue
from services.job_lifecycle import (
    generation_slot,
    register_generation_job,
    request_cancel,
)
from services.kernel.config import ConfigStore
from services.kernel.workspaces import WorkspaceService

_PUBLIC_MODEL_LABELS = {
    "minimax:image-01": "MiniMax Image-01",
    "minimax_h3_legacy": "MiniMax H3 Legacy Quality — ConvRot",
    "post_processing": "Post-processing",
    "rembg-u2net": "rembg U2Net",
}


class GenerationQueue:
    """The jobs of one server and the GPU slot they take turns on."""

    def __init__(
        self,
        config: ConfigStore,
        workspaces: WorkspaceService,
        *,
        is_legacy_h3_model: Callable[[str | None], bool],
        is_minimax_h3_model: Callable[[str | None], bool],
        cancel_legacy_h3: Callable[[], Any],
        task_publisher: Callable[[], Callable[[dict], Any] | None],
    ) -> None:
        self._config = config
        self._workspaces = workspaces
        self._is_legacy_h3_model = is_legacy_h3_model
        self._is_minimax_h3_model = is_minimax_h3_model
        self._cancel_legacy_h3 = cancel_legacy_h3
        self._task_publisher = task_publisher
        self.registry: dict = {}
        self.local_gpu_lane = resource_scheduler.local_gpu_lane(0)
        # This is the coordinator's physical GPU-0 primitive. The existing generation
        # FIFO keeps using its proven job-lifecycle wrapper around the same object,
        # while migrated 3D/Rig/audio/LLM workers acquire it through the coordinator.
        self.gen_lock = resource_scheduler.coordinator.shared_lock(self.local_gpu_lane)
        self.active_states: dict = {}  # job_id -> wgp gen state dict (for abort signaling)
        self.recovery_lock = threading.Lock()
        self.durable_queue = DurableGenerationQueue(
            os.path.join(
                os.path.realpath(config.server_config.get("save_path", "outputs")),
                ".maestro_generation_queue.json",
            )
        )

    @contextmanager
    def slot(
        self,
        job: dict,
        *,
        description: str | None = None,
    ):
        """Keep the legacy FIFO while exposing its acquired GPU lease centrally."""
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        model_type = str(params.get("model_type") or "").strip()
        if not description:
            if self._is_legacy_h3_model(model_type):
                description = resource_scheduler.gpu_engine_description(
                    resource_scheduler.GPU_ENGINE_H3_LEGACY,
                    "HocusPocus Lab H3 Legacy generation",
                )
            elif model_type:
                description = resource_scheduler.gpu_engine_description(
                    resource_scheduler.GPU_ENGINE_WGP,
                    f"HocusPocus Lab WGP generation · {model_type}",
                )
            else:
                description = "HocusPocus Lab GPU generation"
        # Stand aside for a Video 3D export or another coordinator ticket that has
        # waited longer than this job, or past HOCUS_GPU_WAITER_MAX_WAIT_SECONDS.
        def owed_turn(waited: float) -> bool:
            return resource_scheduler.coordinator.has_waiter_owed_turn(self.local_gpu_lane, waited=waited)

        with generation_slot(self.gen_lock, job, yield_to=owed_turn) as acquired:
            if not acquired:
                yield False
                return
            with resource_scheduler.coordinator.adopt_acquired(
                self.local_gpu_lane,
                task_id=str(job.get("task_id") or job.get("id") or "generation"),
                description=description,
            ):
                yield True

    @staticmethod
    def is_durable_job(job: dict) -> bool:
        """Only persist ordinary Studio generations, not Director sub-jobs."""
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        return (
            bool(params.get("model_type"))
            and not params.get("_director_pipeline_id")
            and not params.get("_non_durable_tool")
        )

    def persist_job(self, job: dict) -> None:
        if not self.is_durable_job(job):
            return
        try:
            self.durable_queue.upsert({
                "id": job["id"],
                "status": job.get("status", "queued"),
                "created_at": job.get("created_at", time.time()),
                "params": copy.deepcopy(job.get("params") or {}),
                "workspace": job.get("workspace") or "default",
                "provenance": copy.deepcopy(job.get("provenance") or {}),
            })
        except Exception as exc:
            # Persistence should protect a generation, never prevent it from
            # starting if the disk is temporarily read-only or full.
            print(f"[Queue recovery] Could not persist job {job.get('id')}: {exc}")

    def remove_persisted_job(self, job: dict) -> None:
        if not self.is_durable_job(job):
            return
        try:
            self.durable_queue.remove(str(job.get("id") or ""))
        except Exception as exc:
            print(f"[Queue recovery] Could not remove job {job.get('id')}: {exc}")

    def new_job(
        self,
        params: dict,
        workspace: str,
        *,
        job_id: str | None = None,
        created_at: float | None = None,
        recovered: bool = False,
        reserve_generation: bool = True,
        provenance: dict | None = None,
        publish_task: bool = True,
    ) -> dict:
        frozen_params = copy.deepcopy(params)
        execution_mode.validate_generation(workspace)
        frozen_params["_execution_mode"] = execution_mode.policy().mode
        if self._is_minimax_h3_model(frozen_params.get("model_type")):
            from services.minimax_h3_duration import (
                apply_h3_dialogue_duration,
                apply_h3_vocal_timeline,
                h3_dialogue_split_error,
            )

            wgp = self._config.wgp
            try:
                duration_model_def = wgp.get_model_def(frozen_params.get("model_type")) or {}
            except Exception:
                duration_model_def = {}
            contract = apply_h3_dialogue_duration(frozen_params, duration_model_def)
            if contract:
                if contract.get("requires_split"):
                    raise ValueError(h3_dialogue_split_error(contract))
                print(
                    "[MiniMax H3] Mandatory dialogue duration: "
                    f"{contract['syllable_count']} syllables × "
                    f"{contract['seconds_per_syllable']:.3f}s -> "
                    f"{contract['effective_seconds']:.3f}s "
                    f"({contract['effective_frames']} frames)."
                )
            timeline = apply_h3_vocal_timeline(frozen_params, duration_model_def)
            if timeline:
                print(
                    "[MiniMax H3] Vocal timeline locked: "
                    f"{timeline['segment_count']} authored line(s), "
                    f"{len(timeline['intervals'])} timed interval(s) across "
                    f"{timeline['duration_seconds']:.3f}s."
                )
        resolved_job_id = job_id or uuid.uuid4().hex[:8]
        canonical_task_id = f"task-generation-{resolved_job_id}"
        owner_id = str(frozen_params.get("_director_pipeline_id") or "")
        if owner_id.startswith("series:"):
            canonical_root_task_id = f"task-series-render-{owner_id.split(':', 1)[1]}"
        elif owner_id:
            canonical_root_task_id = f"task-director-{owner_id}"
        else:
            canonical_root_task_id = canonical_task_id
        job = {
            "id": resolved_job_id,
            "task_id": canonical_task_id,
            "root_task_id": canonical_root_task_id,
            "status": "queued",
            "progress": 0,
            "step": 0,
            "total_steps": 0,
            "phase": "",
            "message": "Recovered · queued" if recovered else "Queued",
            "created_at": created_at or time.time(),
            "started_at": None,
            "finished_at": None,
            "params": frozen_params,
            "output_files": [],
            "acquired_resources": [],
            "error": None,
            "workspace": workspace,
            "out_dir": self._workspaces.workspace_dir(workspace),
            "provenance": copy.deepcopy(provenance or {}),
            "recovered": recovered,
        }
        # Reserve FIFO order synchronously. Starting one thread per request is
        # still useful for cancellation/recovery, but thread scheduling no longer
        # decides which submitted generation reaches the GPU first.
        if reserve_generation:
            register_generation_job(self.gen_lock, job)
        publisher = self._task_publisher()
        if publish_task and callable(publisher):
            try:
                task = publisher(job)
                if isinstance(task, dict):
                    job["task_id"] = task.get("id") or job["task_id"]
                    job["root_task_id"] = (
                        task.get("root_id") or task.get("id") or job["root_task_id"]
                    )
            except Exception as exc:
                print(f"[Task registry] Could not publish generation {job['id']}: {exc}")
        return job

    def register_manual_job(self, job: dict) -> dict:
        """Publish older edit/tool jobs before their background thread starts."""
        job_id = str(job.get("id") or "")
        if not job_id:
            raise ValueError("A manual generation job requires an id")
        params = job.get("params") if isinstance(job.get("params"), dict) else {}
        execution_mode.validate_generation(str(job.get("workspace") or self._workspaces.active()))
        params["_execution_mode"] = execution_mode.policy().mode
        if not str(params.get("model_type") or "").strip():
            params["model_type"] = "post_processing"
        params.setdefault("generation_mode", "video")
        job["params"] = params
        job.setdefault("acquired_resources", [])
        job.setdefault("started_at", None)
        job.setdefault("finished_at", None)
        job.setdefault("task_id", f"task-generation-{job_id}")
        job.setdefault("root_task_id", job["task_id"])
        self.registry[job_id] = job
        register_generation_job(self.gen_lock, job)
        publisher = self._task_publisher()
        if callable(publisher):
            try:
                task = publisher(job)
                if isinstance(task, dict):
                    job["task_id"] = task.get("id") or job["task_id"]
                    job["root_task_id"] = (
                        task.get("root_id") or task.get("id") or job["root_task_id"]
                    )
            except Exception as exc:
                print(f"[Task registry] Could not publish manual job {job_id}: {exc}")
        return job

    def job_acceptance(self, job: dict) -> dict:
        return {
            "task_id": job.get("task_id"),
            "root_task_id": job.get("root_task_id") or job.get("task_id"),
            "generation_details": self.public_details(job.get("params")),
        }

    def public_details(self, params: dict | None) -> dict:
        """Return frozen settings suitable for the canonical Activity UI.

        Local paths and reference media stay private.  The authored prompt is
        intentionally retained: Activity is the user's durable audit trail and
        must identify what a model is actually generating after the editable form
        has changed.  It is bounded before persistence and never treated as HTML.
        """
        if not isinstance(params, dict):
            return {}

        model_type = str(params.get("model_type") or "").strip()
        if not model_type:
            return {}
        wgp = self._config.wgp
        try:
            model_def = wgp.get_model_def(model_type) or {}
        except Exception:
            model_def = {}
        details = {
            "model_type": model_type,
            "model_name": str(
                model_def.get("name")
                or _PUBLIC_MODEL_LABELS.get(model_type)
                or model_type
            ),
        }

        public_values = {
            "generation_mode": params.get("generation_mode"),
            "execution_mode": params.get("_execution_mode"),
            "simulated": params.get("_execution_mode") == "simulate",
            "capability": params.get("capability"),
            "source_kind": params.get("source_kind"),
            "source_asset_id": params.get("source_asset_id"),
            "source_filename": params.get("source_filename"),
            "method": params.get("method"),
            "resolution": params.get("resolution"),
            "seed": params.get("seed"),
            "steps": params.get("num_inference_steps"),
            "guidance": params.get("guidance_scale"),
            "frames": params.get("video_length") or params.get("total_frames"),
            "duration_seconds": params.get("duration_seconds"),
            "dialogue_words": (
                params.get("_h3_dialogue_duration_contract", {}).get("word_count")
                if isinstance(params.get("_h3_dialogue_duration_contract"), dict)
                else None
            ),
            "dialogue_syllables": (
                params.get("_h3_dialogue_duration_contract", {}).get("syllable_count")
                if isinstance(params.get("_h3_dialogue_duration_contract"), dict)
                else None
            ),
            "dialogue_seconds_per_syllable": (
                params.get("_h3_dialogue_duration_contract", {}).get("seconds_per_syllable")
                if isinstance(params.get("_h3_dialogue_duration_contract"), dict)
                else None
            ),
            "dialogue_duration_calculated": (
                params.get("_h3_dialogue_duration_contract", {}).get("estimated_seconds")
                if isinstance(params.get("_h3_dialogue_duration_contract"), dict)
                else None
            ),
            "dialogue_duration_minimum_limited": (
                params.get("_h3_dialogue_duration_contract", {}).get("minimum_limited")
                if isinstance(params.get("_h3_dialogue_duration_contract"), dict)
                else None
            ),
            "repeat": params.get("repeat_generation"),
            "profile": params.get("h3_model_profile"),
            "flow_shift": params.get("flow_shift"),
            "audio_shift": params.get("h3_audio_shift"),
            "turbo": params.get("minimax_h3_turbo_mode"),
        }
        for key, value in public_values.items():
            if value is not None and value != "":
                details[key] = value

        prompt = str(params.get("prompt") or "").replace("\x00", "").strip()
        style_prompt = str(params.get("alt_prompt") or "").replace("\x00", "").strip()
        if prompt or style_prompt:
            details["prompt"] = (
                f"{style_prompt}\n\n{prompt}" if style_prompt and prompt else style_prompt or prompt
            )[:32_000]
        initiator = str(params.get("_initiator") or "").replace("\x00", "").strip()
        if initiator:
            details["initiator"] = initiator[:200]

        cache_type = str(params.get("skip_steps_cache_type") or "").strip()
        if cache_type or model_type.startswith("minimax_h3"):
            details["cache"] = bool(cache_type)
            if cache_type:
                details["cache_type"] = cache_type

        raw_loras = params.get("activated_loras")
        selected_loras = raw_loras if isinstance(raw_loras, (list, tuple)) else []
        public_loras = [
            os.path.basename(str(item).replace("\\", "/"))
            for item in selected_loras
            if str(item or "").strip()
        ]
        details["lora_count"] = len(public_loras)
        if public_loras:
            details["loras"] = public_loras
        return details

    def pending_gpu_jobs(self, exclude_job_id: str | None = None) -> list[dict]:
        """Return queued/running GPU-generation jobs, excluding a terminalizing job."""
        pending: list[dict] = []
        for candidate_id, candidate in self.registry.items():
            if candidate_id == exclude_job_id:
                continue
            if candidate.get("status") not in {"queued", "running"}:
                continue
            # Auxiliary tasks such as audio analysis share the status dictionary
            # but do not own the GPU generation lock or require a model runtime.
            if not candidate.get("params", {}).get("model_type"):
                continue
            pending.append(candidate)
        return pending

    def cancel(self, job_id: str) -> dict:
        """Atomically cancel a queued/running generation and signal its owner."""
        job = self.registry.get(job_id)
        if not job:
            return {"status": "missing", "was_running": False}
        result = request_cancel(
            job,
            job_id=job_id,
            active_states=self.active_states,
        )
        if result.was_running and self._is_legacy_h3_model(
            job.get("params", {}).get("model_type")
        ):
            self._cancel_legacy_h3()
        if result.abort_signalled:
            print(f"[Cancel] Signalling abort for job {job_id}")
        if not result.was_running and job.get("status") == "cancelled":
            self.remove_persisted_job(job)
        return {"status": job.get("status"), "was_running": result.was_running}
