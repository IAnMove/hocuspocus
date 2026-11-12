"""HTTP surface of the Installation tab. Thin: every route is one InstallManager call."""
from __future__ import annotations

from typing import Callable

from fastapi import APIRouter, HTTPException, Query

from services.install_manager import InstallManager, ManagerError, default_manager


def create_install_manager_router(manager: Callable[[], InstallManager] = default_manager) -> APIRouter:
    router = APIRouter(prefix="/api/v1/system/install", tags=["system-install"])

    def call(operation, *args):
        try:
            return operation(*args)
        except ManagerError as error:
            raise HTTPException(status_code=error.status, detail={"code": error.code, "message": error.message}) from error

    @router.get("")
    def status():
        return call(manager().status)

    @router.post("/{component_id}/install", status_code=202)
    def install(component_id: str):
        return call(manager().install, component_id)

    @router.post("/{component_id}/uninstall", status_code=202)
    def uninstall(component_id: str):
        return call(manager().uninstall, component_id)

    @router.get("/{component_id}/output")
    def output(component_id: str, lines: int = Query(60, ge=1, le=400)):
        return {"lines": call(manager().output, component_id, lines)}

    return router
