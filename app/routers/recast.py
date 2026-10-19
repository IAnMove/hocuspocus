"""HTTP route for POST /api/v1/recast.

The handler body lives in ``services.recast_endpoint``. This function is the
served endpoint, so the route table names this file, and it calls that handler.
"""

from fastapi import APIRouter, Request

from services.recast_endpoint import recast_endpoint as _recast_endpoint


async def recast_endpoint(request: Request):
    return await _recast_endpoint(request)


# The OpenAPI description is this function's docstring. Keep the moved
# handler's text instead of copying it into the wrapper.
recast_endpoint.__doc__ = _recast_endpoint.__doc__


def create_recast_router():
    """Mount POST /api/v1/recast."""
    router = APIRouter()
    router.add_api_route("/api/v1/recast", recast_endpoint, methods=["POST"])
    return router
