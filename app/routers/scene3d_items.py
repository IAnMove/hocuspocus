"""REST projection of item editing."""
from fastapi import APIRouter, HTTPException
from services.scene3d_items import ItemService, command_catalog

__all__ = ['create_scene3d_items_router', 'ItemService', 'command_catalog']


def create_scene3d_items_router(service):
    router = APIRouter()
    @router.post('/api/v1/scene3d/items/commands')
    async def command(body: dict):
        args = dict(body); name = args.pop('operation', None)
        handler = service.handlers().get(name)
        if not handler: raise HTTPException(422, 'unknown item operation')
        return await handler(args)
    return router
