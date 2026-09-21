"""HTTP and MCP projections for the server-owned image → upscale workflow.

The router is testable without importing ``_launch_runtime``. Mounting it on
the live API is a separate runtime-owner change; see
``INTEGRATION_LAUNCH_RUNTIME.patch``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from services.image_generation_commands import command_error
from services.wizard_workflow_executor import catalog, command_handlers
from services.wizard_workflows import WizardWorkflowRevisionConflict
from services.wizard_workflow_supervisor import workflow_lifespan


def create_wizard_workflow_executor_router(executor, *, list_workspaces=None, interval: float = 1.0) -> APIRouter:
    """Build the isolated executor router with an injected service."""
    router = APIRouter(lifespan=workflow_lifespan(executor, list_workspaces, interval) if list_workspaces else None)

    def _translate(error: Exception) -> HTTPException:
        if isinstance(error, HTTPException):
            return error
        if isinstance(error, WizardWorkflowRevisionConflict):
            return HTTPException(409, {
                "code": "wizard_workflow_revision_conflict",
                "message": str(error),
                "expectedRevision": error.expected,
                "currentRevision": error.current,
                "retryable": False,
                "recoverable": True,
            })
        return command_error(500, "workflow_executor_failed", str(error))

    @router.get("/api/v1/wizard/workflows/executor/commands")
    def commands():
        return {"version": 1, "operations": catalog()}

    @router.get("/api/v1/wizard/workflows/executor")
    def list_workflows(workspace: str):
        return executor.list(workspace)

    @router.get("/api/v1/wizard/workflows/executor/{workflow_id}")
    def get_workflow(workflow_id: str, workspace: str):
        return executor.get(workspace, workflow_id)

    @router.post("/api/v1/wizard/workflows/executor")
    async def start(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise command_error(422, "invalid_command", "Command must be valid JSON") from error
        try:
            return await executor.start(body)
        except (HTTPException, WizardWorkflowRevisionConflict, OSError, ValueError) as error:
            raise _translate(error) from error

    @router.post("/api/v1/wizard/workflows/executor/answer")
    async def answer(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise command_error(422, "invalid_command", "Command must be valid JSON") from error
        try:
            return await executor.answer(body)
        except (HTTPException, WizardWorkflowRevisionConflict, OSError, ValueError) as error:
            raise _translate(error) from error

    @router.post("/api/v1/wizard/workflows/executor/resume")
    async def resume(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise command_error(422, "invalid_command", "Command must be valid JSON") from error
        try:
            return await executor.resume(body)
        except (HTTPException, WizardWorkflowRevisionConflict, OSError, ValueError) as error:
            raise _translate(error) from error

    @router.post("/api/v1/wizard/workflows/executor/reconcile")
    async def reconcile(request: Request):
        try:
            body = await request.json()
        except ValueError as error:
            raise command_error(422, "invalid_command", "Command must be valid JSON") from error
        workspace = str((body or {}).get("workspace") or "").strip()
        if not workspace:
            raise command_error(422, "invalid_workspace", "Use an explicit valid output workspace")
        try:
            return {"results": await executor.reconcile(workspace)}
        except (HTTPException, WizardWorkflowRevisionConflict, OSError, ValueError) as error:
            raise _translate(error) from error

    return router


__all__ = [
    "catalog",
    "command_handlers",
    "create_wizard_workflow_executor_router",
]
