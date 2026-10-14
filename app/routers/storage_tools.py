"""HTTP routes for the storage duplicate finder.

The handler bodies live in ``services.storage_tools``. These wrappers are the
served endpoints, so the route table names this file, and each one calls that
handler. The full server mounts this factory before storage usage, which is
the order the three routes had when they lived in the full server.
"""
from __future__ import annotations

import inspect

from fastapi import APIRouter, Request

from services.storage_tools import storage_duplicates as _storage_duplicates
from services.storage_tools import storage_reclaim as _storage_reclaim
from services.storage_tools import storage_remove_linked as _storage_remove_linked


def create_storage_tools_router():
    """Mount the three storage-duplicate routes in their original order."""
    router = APIRouter()

    @router.get(
        "/api/v1/storage/duplicates",
        description=inspect.cleandoc(_storage_duplicates.__doc__ or ""),
    )
    def storage_duplicates():
        return _storage_duplicates()

    @router.post(
        "/api/v1/storage/duplicates/reclaim",
        description=inspect.cleandoc(_storage_reclaim.__doc__ or ""),
    )
    async def storage_reclaim(request: Request):
        return await _storage_reclaim(request)

    @router.post(
        "/api/v1/storage/duplicates/remove-linked",
        description=inspect.cleandoc(_storage_remove_linked.__doc__ or ""),
    )
    async def storage_remove_linked(request: Request):
        return await _storage_remove_linked(request)

    return router
