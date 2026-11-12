"""REST discovery of interior molds."""
from fastapi import APIRouter
from services.set_molds import catalog


def create_set_catalog_router(call=None):
    router = APIRouter()
    @router.get("/api/v1/scene3d/sets/catalog")
    def list_molds():
        return {"molds": catalog()}

    @router.post("/api/v1/scene3d/rooms/commands")
    def room_command(body: dict):
        from services.splat_commands import APPLY, run as splat_run
        if body.get("operation") == APPLY:
            return splat_run(APPLY, body)
        from services.room_box_commands import run
        return run(body.get("operation"), body, call)
    return router
