"""Prop-library commands shared with MCP."""
from fastapi import APIRouter, HTTPException
from services.prop_commands import PropService, command_catalog

__all__ = ["create_props_router", "PropService", "command_catalog"]


def create_props_router(service):
    router = APIRouter()
    @router.post('/api/v1/props/commands')
    async def command(body: dict):
        args = dict(body); name = args.pop('operation', None)
        handler = service.handlers().get(name)
        if not handler:
            raise HTTPException(422, 'unknown prop operation')
        return await handler(args)
    return router
