"""Interrupted scene exports in ``jobs.leftovers``, resumed by replaying their own command.

A restart leaves a running Video 2D or Video 3D export ``interrupted``.
``jobs.leftovers`` read only the generation queue, so after the OOM restart
these exports were invisible and had to be found and resubmitted by hand.
Each export keeps its frozen command in the task registry. Resuming submits
that same command, which retries the same task (``World3DExportService._replay``)
instead of creating another; discarding cancels it.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any


class SceneExportLeftovers:
    def __init__(self, *, services: Iterable[Any], list_workspaces: Callable[[], list], registry_for: Callable[[str], Any]):
        self.services = {service.operation: service for service in services}
        self.list_workspaces = list_workspaces
        self.registry_for = registry_for

    def _workspaces(self) -> list[str]:
        names = []
        for item in self.list_workspaces() or []:
            name = item.get("name") if isinstance(item, dict) else item
            if isinstance(name, str) and name:
                names.append(name)
        return names

    def _interrupted(self) -> Iterator[tuple[str, Any, dict, dict]]:
        for workspace in self._workspaces():
            registry = self.registry_for(workspace)
            for task in registry.list(statuses={"interrupted"}, limit=1000):
                if task.get("workflow") not in self.services:
                    continue
                admission = registry.command_admission_for_task(task["id"])
                if admission is not None:
                    yield workspace, self.services[task["workflow"]], task, admission

    def _find(self, intent_id: str) -> tuple[str, Any, dict, dict] | None:
        return next((entry for entry in self._interrupted() if entry[3]["intent_id"] == intent_id), None)

    def records(self) -> list[dict]:
        return [{
            "job_id": task["id"], "intent_id": admission["intent_id"], "status": "interrupted",
            "previous_status": "interrupted", "workspace": workspace, "operation": task["workflow"],
            "prompt_preview": str(task.get("title") or ""), "created_at": float(task.get("created_at") or 0),
        } for workspace, _service, task, admission in self._interrupted()]

    def resume(self, intent_id: str) -> dict | None:
        found = self._find(intent_id)
        if found is None:
            return None
        _workspace, service, task, admission = found
        service.submit(admission["original"])
        return {"job_id": task["id"], "intent_id": intent_id, "status": "queued", "started": True}

    def discard(self, intent_id: str) -> dict | None:
        found = self._find(intent_id)
        if found is None:
            return None
        workspace, service, task, _admission = found
        service.cancel(workspace, intent_id)
        return {"job_id": task["id"], "intent_id": intent_id, "discarded": True, "status": "discarded"}
