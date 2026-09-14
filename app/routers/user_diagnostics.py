"""HTTP boundary for user-facing install and generation diagnostics.

Importable without the application launcher, CUDA or heavy engines.
Mount with create_user_diagnostics_router() in either application runtime.
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field

from services.user_diagnostics import collect_report


class ReportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    task_id: str | None = Field(default=None, max_length=200)
    intent_id: str | None = Field(default=None, max_length=200)
    workspace: str | None = Field(default=None, max_length=200)
    task: dict[str, Any] | None = None
    receipt: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


def _load_optional(loader: Callable[..., dict | None] | None, *args: str) -> dict | None:
    if loader is None:
        return None
    try:
        loaded = loader(*args)
    except Exception:
        return None
    return loaded if isinstance(loaded, dict) else None


def create_user_diagnostics_router(
    *,
    collect: Callable[..., dict] | None = None,
    load_task: Callable[[str], dict | None] | None = None,
    load_receipt: Callable[[str, str], dict | None] | None = None,
) -> APIRouter:
    """Build the diagnostics router. Collectors default to the lightweight service."""
    router = APIRouter()
    produce = collect or collect_report

    @router.get("/api/v1/diagnostics")
    def get_diagnostics():
        return produce()

    @router.post("/api/v1/diagnostics/report")
    def post_report(body: ReportRequest | None = None):
        payload = body or ReportRequest()
        task = payload.task
        receipt = payload.receipt
        if task is None and payload.task_id:
            task = _load_optional(load_task, payload.task_id)
        if receipt is None and payload.intent_id and payload.workspace:
            receipt = _load_optional(load_receipt, payload.workspace, payload.intent_id)
        return produce(task=task, receipt=receipt, error=payload.error)

    return router
