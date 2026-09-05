"""Canonical identity rules shared by frontend task adapters."""

from __future__ import annotations

import re
import uuid
from collections.abc import Mapping


CLIENT_TASK_PREFIX = "task-client-"
CLIENT_TASK_SUFFIX_MAX_LENGTH = 160


def canonical_client_task_id(value: object) -> str:
    """Map an untrusted activity id into the frontend-only namespace."""

    normalized = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "")).strip("-")
    while normalized.startswith(CLIENT_TASK_PREFIX):
        normalized = normalized[len(CLIENT_TASK_PREFIX):].strip("-")
    if not normalized:
        normalized = uuid.uuid4().hex
    return f"{CLIENT_TASK_PREFIX}{normalized[:CLIENT_TASK_SUFFIX_MAX_LENGTH]}"


def canonical_client_task_identity(raw: Mapping[str, object]) -> tuple[str, str]:
    """Return an isolated task/root pair, ignoring any client-supplied root."""

    task_id = canonical_client_task_id(raw.get("id"))
    return task_id, task_id
