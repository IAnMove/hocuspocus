"""Pure canonical-task helpers shared by the full server and the core profile.

Sync and control stay in each profile. Callers pass the registry they own.
"""
from __future__ import annotations

from typing import Any


def task_status(value: object) -> str:
    raw = str(value or "queued").lower()
    if raw in {"completed", "failed", "cancelled", "interrupted"}:
        return raw
    if raw in {"created", "queued"}:
        return raw
    if raw in {"paused", "waiting", "waiting_resource"}:
        return "waiting_resource"
    return "running"


def upsert_canonical_task(
    registry: Any,
    workspace: str,
    task_id: str,
    *,
    event_exclude_fields: set[str] | frozenset[str] | None = None,
    **fields: Any,
) -> dict:
    existing = registry.get(task_id)
    if existing is None:
        return registry.create(
            id=task_id,
            workspace=workspace,
            event_exclude_fields=event_exclude_fields,
            **fields,
        )
    from services.task_manager import ACTIVE_STATUSES, TERMINAL_STATUSES
    existing_status = str(existing.get("status") or "")
    incoming_status = str(fields.get("status") or existing_status)
    if existing_status in TERMINAL_STATUSES and incoming_status in ACTIVE_STATUSES:
        # A lagging compatibility snapshot must never resurrect a task after
        # cancellation/completion won. Canonical resume explicitly transitions
        # the registry before the next active adapter snapshot arrives.
        return existing
    existing_metadata = existing.get("metadata") if isinstance(existing.get("metadata"), dict) else {}
    incoming_metadata = fields.get("metadata") if isinstance(fields.get("metadata"), dict) else None
    if incoming_metadata is not None:
        merged_metadata = dict(existing_metadata)
        for key, value in incoming_metadata.items():
            if value is not None:
                merged_metadata[key] = value
        fields["metadata"] = merged_metadata
        # Reservation owns attempt identity. Adapter snapshots must not
        # replace workflow/title after submit_music_generation wrote them.
        if any(
            existing_metadata.get(key)
            for key in ("generation_id", "candidate_id", "command_id", "idempotency_key")
        ):
            fields.pop("workflow", None)
            fields.pop("title", None)
    mutable = {
        key: value for key, value in fields.items()
        if key not in {"id", "created_at"}
        and existing.get(key) != value
    }
    if mutable:
        return registry.update(
            task_id,
            force=True,
            event_type="adapter.synced",
            event_exclude_fields=event_exclude_fields,
            **mutable,
        )
    return existing
