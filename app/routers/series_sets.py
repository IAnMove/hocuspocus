"""REST projection of location room commands."""
from fastapi import APIRouter, HTTPException
from services.series_sets import SeriesSets, command_catalog

__all__=['create_series_sets_router','SeriesSets','command_catalog']


def create_series_sets_router(service, bind_loop=lambda: None):
    router=APIRouter()
    @router.post('/api/v1/series/sets/commands')
    async def command(body:dict):
        bind_loop()
        args=dict(body);name=args.pop('operation',None);handler=service.handlers().get(name)
        if not handler:raise HTTPException(422,'unknown set operation')
        return await handler(args)
    return router
