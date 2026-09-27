"""Application-owned polling for durable Wizard workflows; no second job queue."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress

log = logging.getLogger(__name__)


def workflow_lifespan(executor, list_workspaces, interval: float = 1.0):
    async def supervise():
        while True:
            try:
                workspaces = list_workspaces()
                for item in workspaces:
                    workspace = item["name"] if isinstance(item, dict) else item
                    try:
                        await executor.reconcile(workspace)
                    except Exception:
                        log.exception("Wizard recovery failed for workspace %s", workspace)
            except Exception:
                log.exception("Wizard workspace enumeration failed")
            await asyncio.sleep(interval)

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(supervise(), name="wizard-workflow-supervisor")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    return lifespan
