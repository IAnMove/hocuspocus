"""Small atomic checkpoint store shared by Series planning and render jobs."""

from __future__ import annotations

import copy
import json
import os
import uuid
from typing import Any


SERIES_JOBS_DIR = ".series-jobs-v1"
KINDS = {"planning", "render"}


class SeriesJobStore:
    def __init__(self, workspace_dir: str, kind: str):
        if kind not in KINDS:
            raise ValueError("Unsupported Series Lab job kind")
        self.workspace_dir = workspace_dir
        self.kind = kind
        self.directory = os.path.join(workspace_dir, SERIES_JOBS_DIR, kind)

    def path(self, job_id: str) -> str:
        token = str(job_id or "").strip()
        if not token or os.path.basename(token) != token or token in {".", ".."}:
            raise ValueError("Invalid Series Lab job id")
        return os.path.join(self.directory, f"{token}.json")

    def save(self, job: dict) -> dict:
        if not isinstance(job, dict):
            raise ValueError("Series Lab job must be an object")
        snapshot = copy.deepcopy(job)
        snapshot["kind"] = self.kind
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
        return snapshot

    def load(self, job_id: str) -> dict | None:
        path = self.path(job_id)
        if not os.path.isfile(path):
            return None
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict) or value.get("kind") != self.kind:
            return None
        return value

    def list(self) -> list[dict]:
        if not os.path.isdir(self.directory):
            return []
        result = []
        for name in sorted(os.listdir(self.directory)):
            if not name.endswith(".json"):
                continue
            try:
                value = self.load(name[:-5])
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if value:
                result.append(value)
        return sorted(
            result,
            key=lambda item: float(item.get("updatedAt") or item.get("createdAt") or 0),
            reverse=True,
        )

    def recoverable(self) -> list[dict]:
        return [
            item for item in self.list()
            if item.get("status") in {"queued", "running", "failed", "cancelled"}
        ]

    def discard(self, job_id: str) -> bool:
        """Discard checkpoint state only. Output media is deliberately untouched."""
        path = self.path(job_id)
        if not os.path.isfile(path):
            return False
        os.remove(path)
        return True
