"""Favorites, scene projects and scene recordings.

Favorites are launch-only. Scene save and scene recording are mounted by both
servers. Each server passes its own save: launch keeps URLs without a workspace
query and a required preview, and core keeps the workspace query and no preview.
The recording route uses the launch file fields on both servers. Launch passes
its own publish arguments, including the scan cache and the upload slots.
"""
from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from services.scene_favorites import _load_favorites, _save_favorites


# Launch assigns these before a request. The scan cache is created later in
# launch, and launch copies it here once it exists.
_workspace_dir = None
_output_scan_cache = None
_output_scan_cache_lock = None
_stream_upload = None
_UPLOAD_TRANSCODE_SLOTS = None
_safe_join = None


def list_favorites():
    """List all favorited filenames in the active workspace."""
    return {"favorites": sorted(_load_favorites())}

def toggle_favorite(name: str):
    """Toggle favorite status for a file. Returns new state."""
    from services.win_safe_files import favorites_lock
    # Hold across the whole read-modify-write so a concurrent pipeline
    # delete sweep can't be clobbered by this stale set (RLock — the
    # load/save helpers re-acquire internally).
    with favorites_lock:
        favs = _load_favorites()
        if name in favs:
            favs.discard(name)
            is_fav = False
        else:
            favs.add(name)
            is_fav = True
        _save_favorites(favs)
    return {"name": name, "favorite": is_fav}

def save_scene_output(body: dict):
    """Persist a Scene Animator project as a first-class workspace output.

    The JSON keeps lightweight references to Maestro outputs/uploads while the
    PNG is only a gallery preview. Locally imported assets are uploaded by the
    client before this endpoint is called, so no transient blob: URL is saved.
    """
    from services.scene_save import save_launch_scene

    return save_launch_scene(body, workspace_dir=_workspace_dir)

async def save_scene_recording(
    file: UploadFile = File(...),
    metadata: str = Form("{}"),
    audio: UploadFile | None = File(None),
):
    """Convert a browser WebM capture to MP4 and publish it in Videos.

    The sidecar deliberately keeps the exact user prompt, full LLM recipe,
    compiled scene, and source assets so a rendered 3D clip remains fully
    explainable and reproducible from the gallery.
    """
    from services.scene_save import http_error_detail, http_error_status, publish_from_form

    try:
        return await publish_from_form(
            {"file": file, "metadata": metadata, "audio": audio},
            workspace_dir=_workspace_dir,
            include_workspace_query=False,
            scan_cache=_output_scan_cache,
            scan_cache_lock=_output_scan_cache_lock,
            stream_upload=_stream_upload,
            transcode_slots=_UPLOAD_TRANSCODE_SLOTS,
            sidecar_error_prefix="Could not save recording metadata",
            safe_join=_safe_join,
            strip_workspace=False,
        )
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=http_error_status(error), detail=http_error_detail(error)) from error


def create_favorites_router(*, _workspace_dir, _get_active_workspace):
    """Mount the favorites routes at their old position. Launch only."""
    import services.scene_favorites as scene_favorites

    scene_favorites._workspace_dir = _workspace_dir
    scene_favorites._get_active_workspace = _get_active_workspace
    globals().update({"_workspace_dir": _workspace_dir})
    router = APIRouter()
    impl = {name: globals()[name] for name in ("list_favorites", "toggle_favorite")}

    @router.get("/api/v1/favorites")
    def list_favorites():
        """List all favorited filenames in the active workspace."""
        return impl["list_favorites"]()

    @router.post("/api/v1/favorites/{name}")
    def toggle_favorite(name: str):
        """Toggle favorite status for a file. Returns new state."""
        return impl["toggle_favorite"](name)

    return router


def create_scene_output_router(*, save_scene):
    """Mount POST /api/v1/scenes. ``save_scene`` is that server's saver."""
    router = APIRouter()

    @router.post("/api/v1/scenes")
    def save_scene_output(body: dict):
        """Persist a Scene Animator project as a first-class workspace output.

        The JSON keeps lightweight references to Maestro outputs/uploads while the
        PNG is only a gallery preview. Locally imported assets are uploaded by the
        client before this endpoint is called, so no transient blob: URL is saved.
        """
        return save_scene(body)

    return router


def create_scene_recording_router(*, publish_recording):
    """Mount POST /api/v1/scenes/recordings.

    The file fields are the launch fields, so a missing file is a validation
    error on both servers. ``publish_recording`` carries that server's arguments.
    """
    router = APIRouter()

    @router.post("/api/v1/scenes/recordings")
    async def save_scene_recording(
        file: UploadFile = File(...),
        metadata: str = Form("{}"),
        audio: UploadFile | None = File(None),
    ):
        """Convert a browser WebM capture to MP4 and publish it in Videos.

        The sidecar deliberately keeps the exact user prompt, full LLM recipe,
        compiled scene, and source assets so a rendered 3D clip remains fully
        explainable and reproducible from the gallery.
        """
        return await publish_recording(file, metadata, audio)

    return router
