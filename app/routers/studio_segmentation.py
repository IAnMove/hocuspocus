"""HTTP routes for SAM status and segment preview.

The handler bodies live in ``services.studio_segmentation``. These functions
are the served endpoints, so the route table names this file.
"""

from fastapi import APIRouter, Request

from services.studio_segmentation import (
    sam_status_endpoint as _sam_status_endpoint,
    segment_preview_endpoint as _segment_preview_endpoint,
)


async def sam_status_endpoint():
    """Check if the SAM segmentation service is available."""
    return await _sam_status_endpoint()


async def segment_preview_endpoint(request: Request):
    """Preview mask segmentation on a video frame.

    Body: {
        video_path: str, text: str,
        start_time?: float, end_time?: float, frame_index?: int
    }
    """
    return await _segment_preview_endpoint(request)


def create_studio_segmentation_router(*, get_active_workspace, workspace_dir):
    """Mount SAM status and segment preview in the order the launch server registered them."""
    from services import studio_segmentation as module

    module._get_active_workspace = get_active_workspace
    module._workspace_dir = workspace_dir
    router = APIRouter()
    router.add_api_route("/api/v1/sam/status", sam_status_endpoint, methods=["GET"])
    router.add_api_route("/api/v1/segment/preview", segment_preview_endpoint, methods=["POST"])
    return router
