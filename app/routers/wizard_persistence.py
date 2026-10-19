"""Wizard conversation and workflow files, shared by both servers.

``workspace_dir(value)`` returns the workspace directory. A ``ValueError`` from it
is an invalid workspace name and answers 400. ``HTTPException`` is left alone, so
the full server's own name check still answers as it does today. An ``OSError``
from it (a folder that cannot be created) answers 500 with the Wizard message, as
both servers did before. ``lock`` is held around the read and the write.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException


def create_wizard_persistence_router(*, workspace_dir, lock) -> APIRouter:
    router = APIRouter()

    def _directory(value):
        try:
            return workspace_dir(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/api/v1/wizard/conversations")
    def get_wizard_conversation(workspace: str | None = None):
        """Load the durable Wizard conversation for one workspace."""
        from services.wizard_conversations import read_conversation

        try:
            directory = _directory(workspace)
            with lock:
                return read_conversation(directory)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not read the Wizard conversation: {exc}",
            ) from exc

    @router.put("/api/v1/wizard/conversations")
    def put_wizard_conversation(body: dict):
        """Atomically replace a workspace Wizard conversation."""
        from services.wizard_conversations import (
            WizardConversationRevisionConflict,
            write_conversation,
        )

        try:
            directory = _directory(body.get("workspace"))
            with lock:
                base_revision = body.get("baseRevision")
                if type(base_revision) is not int:
                    base_revision = 0
                return write_conversation(
                    directory,
                    body.get("conversation"),
                    base_revision=base_revision,
                )
        except WizardConversationRevisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "wizard_conversation_revision_conflict",
                    "message": str(exc),
                    "expectedRevision": exc.expected,
                    "currentRevision": exc.current,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not save the Wizard conversation: {exc}",
            ) from exc

    @router.get("/api/v1/wizard/workflows")
    def get_wizard_workflows(workspace: str | None = None):
        """Load durable Wizard workflow checkpoints for one workspace."""
        from services.wizard_workflows import read_workflows

        try:
            directory = _directory(workspace)
            with lock:
                return read_workflows(directory)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not read Wizard workflows: {exc}",
            ) from exc

    @router.put("/api/v1/wizard/workflows")
    def put_wizard_workflows(body: dict):
        """Atomically checkpoint all Wizard workflows in one workspace."""
        from services.wizard_workflows import (
            WizardWorkflowRevisionConflict,
            write_workflows,
        )

        try:
            directory = _directory(body.get("workspace"))
            with lock:
                base_revision = body.get("baseRevision")
                if type(base_revision) is not int:
                    base_revision = 0
                return write_workflows(
                    directory,
                    body.get("collection"),
                    base_revision=base_revision,
                )
        except WizardWorkflowRevisionConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "wizard_workflow_revision_conflict",
                    "message": str(exc),
                    "expectedRevision": exc.expected,
                    "currentRevision": exc.current,
                },
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"Could not save Wizard workflows: {exc}",
            ) from exc

    return router
