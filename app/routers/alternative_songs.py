"""Alternative-song routes, mounted where the full server registered them.

The handlers live in ``services.alternative_songs`` under the names they had
in the launch module. The editor registry is not passed here: it does not
exist yet at this include, and launch binds it after importing the editor.
"""
from __future__ import annotations

import inspect

from fastapi import APIRouter

from services import alternative_songs


def _description(handler) -> str:
    """The OpenAPI description the handler's docstring had on the launch route."""
    return inspect.cleandoc(handler.__doc__ or "")


def create_alternative_songs_router():
    """List, attach, delete and mount, in the full server's order."""
    router = APIRouter()

    @router.get(
        "/api/v1/outputs/{name}/alternative-songs",
        description=_description(alternative_songs.list_alternative_songs),
    )
    def list_alternative_songs(name: str, workspace: str | None = None):
        return alternative_songs.list_alternative_songs(name, workspace)

    @router.post(
        "/api/v1/outputs/{name}/alternative-songs",
        description=_description(alternative_songs.attach_alternative_song),
    )
    def attach_alternative_song(name: str, body: dict, workspace: str | None = None):
        return alternative_songs.attach_alternative_song(name, body, workspace)

    @router.delete(
        "/api/v1/outputs/{name}/alternative-songs/{song_id}",
        description=_description(alternative_songs.delete_alternative_song),
    )
    def delete_alternative_song(name: str, song_id: str, workspace: str | None = None):
        return alternative_songs.delete_alternative_song(name, song_id, workspace)

    @router.post(
        "/api/v1/outputs/{name}/alternative-songs/{song_id}/mount",
        status_code=202,
        description=_description(alternative_songs.mount_alternative_song),
    )
    def mount_alternative_song(
        name: str,
        song_id: str,
        body: dict | None = None,
        workspace: str | None = None,
    ):
        return alternative_songs.mount_alternative_song(name, song_id, body, workspace)

    return router
