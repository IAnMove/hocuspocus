"""Crash-safe persistence for Maestro's ordinary GPU generation queue.

The running model state itself cannot be checkpointed generically, but the
original request can.  On the next launch the API presents these records as a
recovery choice instead of silently starting expensive GPU work.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
import uuid
from typing import Any, Iterable


class DurableGenerationQueue:
    """Store serialisable generation requests using atomic file replacement."""

    VERSION = 1

    def __init__(self, path: str):
        self.path = os.path.realpath(path)
        self._lock = threading.RLock()

    def _read_unlocked(self) -> dict[str, Any]:
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
            return {"version": self.VERSION, "updated_at": 0, "jobs": []}
        jobs = payload.get("jobs") if isinstance(payload, dict) else None
        if not isinstance(jobs, list):
            jobs = []
        return {
            "version": self.VERSION,
            "updated_at": payload.get("updated_at", 0),
            "jobs": [job for job in jobs if isinstance(job, dict) and job.get("id")],
        }

    def _write_unlocked(self, jobs: list[dict[str, Any]]) -> None:
        parent = os.path.dirname(self.path)
        os.makedirs(parent, exist_ok=True)
        payload = {
            "version": self.VERSION,
            "updated_at": time.time(),
            "jobs": jobs,
        }
        temporary = f"{self.path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            # Make the rename durable as well on filesystems that support
            # directory fsync. Windows does not expose O_DIRECTORY.
            if hasattr(os, "O_DIRECTORY"):
                directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass

    def list(self, *, exclude_ids: Iterable[str] = ()) -> list[dict[str, Any]]:
        excluded = set(exclude_ids)
        with self._lock:
            jobs = [
                copy.deepcopy(job)
                for job in self._read_unlocked()["jobs"]
                if str(job.get("id")) not in excluded
            ]
        jobs.sort(key=lambda job: float(job.get("created_at") or 0))
        return jobs

    def upsert(self, record: dict[str, Any]) -> None:
        job_id = str(record.get("id") or "").strip()
        if not job_id:
            raise ValueError("A durable generation record needs an id")
        # Round-trip now so non-serialisable runtime objects never corrupt the
        # existing queue file.
        clean = json.loads(json.dumps(record, ensure_ascii=False))
        with self._lock:
            jobs = self._read_unlocked()["jobs"]
            replaced = False
            for index, existing in enumerate(jobs):
                if str(existing.get("id")) == job_id:
                    jobs[index] = clean
                    replaced = True
                    break
            if not replaced:
                jobs.append(clean)
            jobs.sort(key=lambda job: float(job.get("created_at") or 0))
            self._write_unlocked(jobs)

    def remove(self, job_id: str) -> bool:
        with self._lock:
            jobs = self._read_unlocked()["jobs"]
            remaining = [job for job in jobs if str(job.get("id")) != str(job_id)]
            if len(remaining) == len(jobs):
                return False
            self._write_unlocked(remaining)
            return True

    def discard(self, *, exclude_ids: Iterable[str] = ()) -> int:
        """Discard recovery candidates while preserving live in-process jobs."""
        excluded = set(exclude_ids)
        with self._lock:
            jobs = self._read_unlocked()["jobs"]
            remaining = [job for job in jobs if str(job.get("id")) in excluded]
            removed = len(jobs) - len(remaining)
            if removed:
                self._write_unlocked(remaining)
            return removed
