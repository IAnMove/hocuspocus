"""Activity rows for what Ask to the Wizard changed without starting a job.

The Wizard runs in the browser: a kit, a series or a story it creates or edits
is saved through the studios' own routes, so no task records it. After such a
change the browser reports it here, and ``AgentActivity.record_wizard`` turns
it into the same trail row an MCP agent's change gets (services/agent_activity.py).
"""
from __future__ import annotations

from typing import Any, Protocol

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field


class WizardChangeRecorder(Protocol):
    def record_wizard(self, workspace: str, capability: str, targets: Any, command_id: str | None = None) -> dict | None: ...


class WizardChange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=120)
    capability: str = Field(min_length=1, max_length=120)
    commandId: str | None = Field(default=None, max_length=160)
    targets: list[dict[str, Any]] = Field(min_length=1, max_length=24)


def create_wizard_activity_router(activity: WizardChangeRecorder) -> APIRouter:
    router = APIRouter()

    @router.post("/api/v1/tasks/wizard-changes")
    def record_wizard_change(body: WizardChange):
        """One Wizard change (capability and the artifacts it touched) as a row of Activity's Agents view."""
        try:
            task = activity.record_wizard(body.workspace, body.capability, body.targets, body.commandId)
        except ValueError as error:
            raise HTTPException(422, detail={"code": "invalid_wizard_change", "message": str(error)}) from error
        return {"recorded": task is not None, "task": task}

    return router


__all__ = ["create_wizard_activity_router"]
