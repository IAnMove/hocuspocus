"""REST projection of the idempotent image cutout command."""
from fastapi import APIRouter


def create_image_remove_background_router(handlers):
    router = APIRouter()
    @router.post("/api/v1/image/remove-background")
    async def remove_background(body: dict):
        return await handlers["image.remove_background"](body)
    return router
