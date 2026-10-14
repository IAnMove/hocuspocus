"""Gallery routes of the core server: the list, the thumbnail and the file of an output.

The full server mounts these three one by one, with the output facts router between the list and the thumbnail,
and binds them to its engine, favorites and editor. Core has none of those, so it mounts them together here and
binds what they read to its own workspace folders. Without the thumbnail route every ``thumbnail_url`` of a row
and every sized preview a gallery tile asks for answered 404.
"""
from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter

from routers.outputs_ops import create_output_thumbnail_router
from routers.workspace_outputs import create_list_outputs_router, create_serve_file_router
from services import core_workspace as core, output_listing, output_ops


def _gallery_workspace_dir(workspace: str | None = None) -> str:
    return core.uploads_dir() if workspace == "__uploads__" else core.workspace_dir(workspace)


def create_core_gallery_router() -> APIRouter:
    """GET /api/v1/outputs, /api/v1/outputs/thumbnail/{filename:path} and /api/v1/file/{filename:path} on core."""
    output_listing.configure(
        workspace_dir=_gallery_workspace_dir,
        load_favorites=set,
        safe_join=core.safe_join,
        engine=SimpleNamespace(server_config={"save_path": "outputs"}),
    )
    output_ops.configure_thumbnails(safe_join=core.safe_join)
    router = APIRouter()
    router.include_router(create_list_outputs_router())
    router.include_router(create_output_thumbnail_router())
    router.include_router(create_serve_file_router())
    return router
