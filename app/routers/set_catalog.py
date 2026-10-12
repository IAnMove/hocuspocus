"""REST discovery of interior molds."""
from fastapi import APIRouter
from services.set_molds import catalog


def create_set_catalog_router():
    router = APIRouter()
    @router.get("/api/v1/scene3d/sets/catalog")
    def list_molds():
        return {"molds": catalog()}
    return router
