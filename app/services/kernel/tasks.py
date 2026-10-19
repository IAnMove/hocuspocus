"""Where a workspace's canonical task registry is found, and the adapter registry skeleton.

``services.task_manager`` owns the per-workspace task store (its own
``TaskRegistry`` class); this module only answers "which store is it" for the
active or a named workspace. Each feature slice will register a ``TaskAdapter``
for its kind here (list, snapshot and cancel its own tasks) so that the
canonical task aggregator no longer has to know every slice. Nothing calls
``register_adapter`` yet: the aggregator in the full server still reads each
registry directly, and moving it is a later step.
"""
from __future__ import annotations

from typing import Any, Protocol

from services.kernel.workspaces import WorkspaceService


class TaskAdapter(Protocol):
    """What a slice offers the canonical task registry for one kind of task."""

    def list(self, workspace: str) -> list[dict]:
        """The slice's tasks in ``workspace`` as canonical task records."""

    def snapshot(self, workspace: str, task_id: str) -> dict | None:
        """One task of the slice, or ``None`` when the slice does not know it."""

    def cancel(self, workspace: str, task_id: str) -> dict | None:
        """Ask the slice to cancel one of its tasks; ``None`` when it does not know it."""


class CanonicalTasks:
    """The canonical task store of a workspace, and the adapters slices register."""

    def __init__(self, workspaces: WorkspaceService) -> None:
        self._workspaces = workspaces
        self._adapters: dict[str, TaskAdapter] = {}

    def for_workspace(self, workspace: str | None = None):
        from services.task_manager import get_task_registry

        target = self._workspaces.active() if workspace is None else workspace
        return get_task_registry(self._workspaces.workspace_dir(target))

    def register_adapter(self, kind: str, adapter: TaskAdapter) -> None:
        """Offer ``adapter`` for tasks of ``kind``. A kind has one adapter."""
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("A task adapter needs a kind")
        if kind in self._adapters:
            raise ValueError(f"A task adapter is already registered for {kind!r}")
        self._adapters[kind] = adapter

    def adapter_for(self, kind: str) -> TaskAdapter | None:
        return self._adapters.get(kind)

    def adapters(self) -> dict[str, Any]:
        """The registered adapters by kind, in registration order (a copy)."""
        return dict(self._adapters)
