"""Gallery routes that stay between the list, the file route and the editor.

Each factory is mounted at the first route it replaces, so the registration
order of the full server stays the same. The handlers live in
``services.output_ops`` under the names they had in the launch module.
"""
from __future__ import annotations

import inspect

from fastapi import APIRouter, Request

from services import output_ops


def _description(handler) -> str:
    """The OpenAPI description the handler's docstring had on the launch route."""
    return inspect.cleandoc(handler.__doc__ or "")


def create_output_thumbnail_router():
    """GET /api/v1/outputs/thumbnail/{filename} at the full server's original position."""
    router = APIRouter()

    @router.get(
        "/api/v1/outputs/thumbnail/{filename:path}",
        description=_description(output_ops.serve_output_thumbnail),
    )
    def serve_output_thumbnail(filename: str, workspace: str | None = None, size: str | None = None):
        return output_ops.serve_output_thumbnail(filename, workspace, size)

    return router


def create_output_metadata_router():
    """GET /api/v1/outputs/{name}/metadata at the full server's original position."""
    router = APIRouter()

    @router.get(
        "/api/v1/outputs/{name}/metadata",
        description=_description(output_ops.get_output_metadata),
    )
    def get_output_metadata(name: str, workspace: str | None = None):
        return output_ops.get_output_metadata(name, workspace)

    return router


def create_output_extra_router():
    """Extra info, rejoin and group clips, in the full server's order."""
    router = APIRouter()

    @router.get(
        "/api/v1/outputs/{name}/extra-info",
        description=_description(output_ops.get_video_extra_info),
    )
    def get_video_extra_info(name: str, language: str = "en"):
        return output_ops.get_video_extra_info(name, language)

    @router.post(
        "/api/v1/outputs/{name}/extra-info",
        description=_description(output_ops.generate_output_extra_info),
    )
    async def generate_output_extra_info(name: str, request: Request):
        return await output_ops.generate_output_extra_info(name, request)

    @router.post(
        "/api/v1/outputs/rejoin",
        description=_description(output_ops.rejoin_clips),
    )
    def rejoin_clips(body: dict):
        return output_ops.rejoin_clips(body)

    @router.get(
        "/api/v1/outputs/group/{group_id}",
        description=_description(output_ops.get_group_clips),
    )
    def get_group_clips(group_id: str):
        return output_ops.get_group_clips(group_id)

    return router


def create_output_move_router():
    """Move and delete, after the editor jobs and before uploads."""
    router = APIRouter()

    @router.post(
        "/api/v1/outputs/{name:path}/move",
        description=_description(output_ops.move_output),
    )
    async def move_output(name: str, request: Request):
        return await output_ops.move_output(name, request)

    @router.delete(
        "/api/v1/outputs/{name}",
        description=_description(output_ops.delete_output),
    )
    def delete_output(name: str, workspace: str | None = None):
        return output_ops.delete_output(name, workspace)

    return router
