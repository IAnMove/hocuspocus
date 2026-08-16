"""Durable checkpoints for long Director V2 planning jobs.

Music-video planning can require dozens of structured LLM outputs.  This store
persists every validated batch atomically so a new process can resume only the
remaining clip indexes after a provider failure or application restart.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from typing import Any


DIRECTOR_PLAN_JOBS_DIR = ".director-plan-jobs-v1"
DIRECTOR_PLAN_JOB_VERSION = 1
_STORE_LOCK = threading.RLock()
_ACTIVE_JOB_IDS: set[str] = set()


def claim_director_plan_job(job_id: str) -> bool:
    """Atomically claim one in-process worker while allowing restart recovery."""
    token = str(job_id or "").strip()
    if not token:
        return False
    with _STORE_LOCK:
        if token in _ACTIVE_JOB_IDS:
            return False
        _ACTIVE_JOB_IDS.add(token)
        return True


def release_director_plan_job(job_id: str) -> None:
    with _STORE_LOCK:
        _ACTIVE_JOB_IDS.discard(str(job_id or "").strip())


def _clip_index(plan: dict) -> int | None:
    try:
        value = int(plan.get("clip_index"))
    except (AttributeError, TypeError, ValueError):
        return None
    return value if value > 0 else None


class DirectorPlanJobStore:
    """Small atomic JSON store scoped to one workspace directory."""

    def __init__(self, workspace_dir: str):
        self.workspace_dir = os.path.abspath(workspace_dir)
        self.directory = os.path.join(self.workspace_dir, DIRECTOR_PLAN_JOBS_DIR)

    def path(self, job_id: str) -> str:
        token = str(job_id or "").strip()
        if not token or os.path.basename(token) != token or token in {".", ".."}:
            raise ValueError("Invalid Director plan job id")
        return os.path.join(self.directory, f"{token}.json")

    def _write(self, snapshot: dict) -> dict:
        job_id = str(snapshot.get("jobId") or "").strip()
        path = self.path(job_id)
        os.makedirs(self.directory, exist_ok=True)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(snapshot, handle, ensure_ascii=False, separators=(",", ":"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                if os.path.isfile(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return copy.deepcopy(snapshot)

    def create(
        self,
        request: dict,
        *,
        workspace: str,
        skill_type: str,
        total: int,
        job_id: str | None = None,
    ) -> dict:
        now = time.time()
        snapshot = {
            "version": DIRECTOR_PLAN_JOB_VERSION,
            "jobId": job_id or f"director-plan-{uuid.uuid4().hex}",
            "workspace": str(workspace or "default"),
            "skillType": str(skill_type or "music_video"),
            "status": "queued",
            "phase": "queued",
            "message": "Planning job queued",
            "request": copy.deepcopy(request),
            "total": max(0, int(total or 0)),
            "completedIndices": [],
            "completedShotPlans": [],
            "completedBatches": [],
            "activeBatch": [],
            "calls": 0,
            "usage": {},
            "result": None,
            "error": None,
            "createdAt": now,
            "updatedAt": now,
            "finishedAt": None,
        }
        with _STORE_LOCK:
            if os.path.exists(self.path(snapshot["jobId"])):
                raise ValueError("Director plan job already exists")
            return self._write(snapshot)

    def load(self, job_id: str) -> dict | None:
        path = self.path(job_id)
        with _STORE_LOCK:
            if not os.path.isfile(path):
                return None
            with open(path, "r", encoding="utf-8") as handle:
                value = json.load(handle)
        if not isinstance(value, dict) or value.get("version") != DIRECTOR_PLAN_JOB_VERSION:
            return None
        return value

    def update(self, job_id: str, **patch: Any) -> dict:
        with _STORE_LOCK:
            current = self.load(job_id)
            if current is None:
                raise KeyError(f"Director plan job not found: {job_id}")
            current.update(copy.deepcopy(patch))
            current["updatedAt"] = time.time()
            return self._write(current)

    def begin_call(
        self,
        job_id: str,
        *,
        indices: list[int],
        phase: str,
        usage: dict | None = None,
    ) -> dict:
        current = self.load(job_id)
        if current is None:
            raise KeyError(f"Director plan job not found: {job_id}")
        return self.update(
            job_id,
            status="running",
            phase=phase,
            message=f"Planning clip indexes {', '.join(map(str, indices))}",
            activeBatch=list(indices),
            calls=int(current.get("calls") or 0) + 1,
            usage=copy.deepcopy(usage or current.get("usage") or {}),
            error=None,
            finishedAt=None,
        )

    def record_batch(
        self,
        job_id: str,
        *,
        indices: list[int],
        shot_plans: list[dict],
        usage: dict | None = None,
    ) -> dict:
        with _STORE_LOCK:
            current = self.load(job_id)
            if current is None:
                raise KeyError(f"Director plan job not found: {job_id}")
            plans_by_index = {
                index: copy.deepcopy(plan)
                for plan in current.get("completedShotPlans") or []
                if isinstance(plan, dict) and (index := _clip_index(plan)) is not None
            }
            for plan in shot_plans:
                if not isinstance(plan, dict):
                    continue
                index = _clip_index(plan)
                if index is None or index not in indices:
                    raise ValueError("Batch checkpoint contains an unexpected clip index")
                if index in plans_by_index and plans_by_index[index] != plan:
                    raise ValueError(f"Batch checkpoint would overwrite clip index {index}")
                plans_by_index[index] = copy.deepcopy(plan)
            missing = sorted(set(indices) - set(plans_by_index))
            if missing:
                raise ValueError(f"Batch checkpoint is incomplete for indexes {missing}")

            batches = list(current.get("completedBatches") or [])
            normalized_indices = sorted(set(indices))
            if normalized_indices and not any(
                batch.get("indices") == normalized_indices
                for batch in batches if isinstance(batch, dict)
            ):
                batches.append({"indices": normalized_indices, "completedAt": time.time()})
            completed_indices = sorted(plans_by_index)
            current.update({
                "status": "running",
                "phase": "batch_completed",
                "message": f"Completed {len(completed_indices)} of {current.get('total') or 0} clips",
                "completedIndices": completed_indices,
                "completedShotPlans": [plans_by_index[index] for index in completed_indices],
                "completedBatches": batches,
                "activeBatch": [],
                "usage": copy.deepcopy(usage or current.get("usage") or {}),
                "error": None,
                "updatedAt": time.time(),
            })
            return self._write(current)

    def list(self) -> list[dict]:
        if not os.path.isdir(self.directory):
            return []
        result = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            try:
                job = self.load(name[:-5])
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if job:
                result.append(job)
        return sorted(result, key=lambda item: float(item.get("updatedAt") or 0), reverse=True)

    @staticmethod
    def public_snapshot(job: dict) -> dict:
        total = max(0, int(job.get("total") or 0))
        completed = sorted({
            int(value) for value in job.get("completedIndices") or []
            if isinstance(value, int) or str(value).isdigit()
        })
        return {
            "jobId": job.get("jobId"),
            "workspace": job.get("workspace"),
            "skillType": job.get("skillType"),
            "status": job.get("status"),
            "phase": job.get("phase"),
            "message": job.get("message"),
            "total": total,
            "completedIndices": completed,
            "missingIndices": [index for index in range(1, total + 1) if index not in completed],
            "completedBatches": copy.deepcopy(job.get("completedBatches") or []),
            "activeBatch": copy.deepcopy(job.get("activeBatch") or []),
            "calls": int(job.get("calls") or 0),
            "usage": copy.deepcopy(job.get("usage") or {}),
            "error": job.get("error"),
            "result": copy.deepcopy(job.get("result")) if job.get("status") == "completed" else None,
            "createdAt": job.get("createdAt"),
            "updatedAt": job.get("updatedAt"),
            "finishedAt": job.get("finishedAt"),
        }
