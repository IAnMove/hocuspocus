"""HTTP route for POST /api/v1/recast/preview.

The handler body lives in ``services.recast_preview``. This function is the
served endpoint, so the route table names this file, and it calls that handler.
"""

from fastapi import APIRouter, Request

from services.recast_preview import recast_preview_endpoint as _recast_preview_endpoint


async def recast_preview_endpoint(request: Request):
    return await _recast_preview_endpoint(request)


# The OpenAPI description is this function's docstring. Keep the moved
# handler's text instead of copying it into the wrapper.
recast_preview_endpoint.__doc__ = _recast_preview_endpoint.__doc__


def create_recast_preview_router():
    """Mount POST /api/v1/recast/preview."""
    router = APIRouter()
    router.add_api_route("/api/v1/recast/preview", recast_preview_endpoint, methods=["POST"])
    return router
