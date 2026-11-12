"""Uploads: POST /api/v1/upload and GET /api/v1/uploads/{filename}, one implementation for both servers.

The full server (``_launch_runtime``) and the core server (``core_runtime``) mount
this router and inject what differs between them: the uploads folder, how an
upload is streamed to disk and transcoded, how a video is probed, how a name is
joined under the folder, and where a name that is not an upload falls back to. The
module imports nothing heavy, so the core server runs it without Torch.

What an upload may be called is decided here, once: only the extensions in
``UPLOAD_EXTENSIONS`` are kept, and every other name is stored as ``.bin``, so a
stored ``x.html`` or ``x.svg`` can never be served as a page of the app.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile

from services.upload_stream import UploadTooLargeError, UploadTranscodeError

MAX_IMAGE_UPLOAD_BYTES = 500 * 1024 * 1024   # 500 MB (generic /api/v1/upload handles images and videos)

UPLOAD_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".avif",
    ".mp4", ".mov", ".webm", ".mkv", ".m4v", ".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus",
    ".glb", ".gltf", ".obj", ".fbx", ".json", ".txt", ".srt", ".vtt", ".lrc", ".csv", ".md", ".pdf", ".zip", ".safetensors", ".pt",
})


def create_uploads_router(
    *,
    uploads_dir: Callable[[], str],
    stream_upload: Callable[..., Awaitable[int]],
    transcode_upload: Callable[..., Awaitable[None]],
    probe_video_metadata: Callable[[str], dict[str, Any] | None],
    safe_join: Callable[..., str | None],
    output_fallback: Callable[[str], Any],
) -> APIRouter:
    """Build the upload and serve-upload routes.

    ``stream_upload(upload, destination, *, max_bytes)`` copies the request's file
    to disk within the byte cap and raises ``UploadTooLargeError`` above it.
    ``transcode_upload(source, destination, *, is_video)`` raises
    ``UploadTranscodeError`` when the audio cannot be decoded.
    ``probe_video_metadata(path)`` returns the ``fps``, ``frame_count``,
    ``duration_seconds`` and ``has_audio`` of an uploaded video, or nothing.
    ``safe_join(base, *parts)`` returns the path under ``base`` or ``None``.
    ``output_fallback(filename)`` answers a name that is not in the uploads folder.
    """

    router = APIRouter()

    @router.post("/api/v1/upload")
    async def upload_image(file: UploadFile = File(...)):
        """Upload an image or audio/video asset. Image was the original use;
        audio/video also flow through here when the frontend doesn't hit the
        dedicated /api/v1/upload-audio endpoint. Compressed audio formats get
        transcoded to wav so downstream libsndfile callers work."""
        if file.size is not None and file.size > MAX_IMAGE_UPLOAD_BYTES:
            await file.close()
            raise HTTPException(status_code=413, detail="File too large (max 500 MB)")

        upload_dir = uploads_dir()
        os.makedirs(upload_dir, exist_ok=True)

        ext = os.path.splitext(file.filename or "img.png")[1].lower() or ".png"
        if ext not in UPLOAD_EXTENSIONS:
            ext = ".bin"  # keeps the bytes; never a name a browser would run
        unique_name = f"{uuid.uuid4().hex}{ext}"
        filepath = os.path.join(upload_dir, unique_name)

        try:
            await stream_upload(
                file,
                filepath,
                max_bytes=MAX_IMAGE_UPLOAD_BYTES,
            )
        except UploadTooLargeError as err:
            raise HTTPException(status_code=413, detail="File too large (max 500 MB)") from err

        # libsndfile-incompatible audio → transcode to wav so slice_audio_window
        # and friends can read it without a downstream crash. Mirrors the logic
        # in /api/v1/upload-audio.
        if ext in (".mp3", ".m4a", ".aac"):
            wav_name = f"{os.path.splitext(unique_name)[0]}.wav"
            wav_path = os.path.join(upload_dir, wav_name)
            compressed_original = filepath
            transcode_ok = False
            try:
                await transcode_upload(filepath, wav_path, is_video=False)
                transcode_ok = True
                os.remove(compressed_original)
                filepath = wav_path
                unique_name = wav_name
            except UploadTranscodeError as err:
                raise HTTPException(
                    status_code=400,
                    detail=f"Failed to decode {ext} audio: {(err.stderr or str(err)).strip()[:300]}",
                ) from err
            except Exception as err:
                raise HTTPException(status_code=500, detail=f"Audio transcode failed: {err}") from err
            finally:
                if not transcode_ok:
                    for stale in (wav_path, compressed_original):
                        if stale and os.path.isfile(stale):
                            try:
                                os.remove(stale)
                            except OSError:
                                pass

        result = {
            "filename": unique_name,
            "path": filepath,
            "url": f"/api/v1/uploads/{unique_name}",
        }
        # For video uploads, report the source frame rate so the client can
        # compute frame counts for models that follow the control video's
        # fps (force_fps="control" — the SCAIL-2 class). The UI otherwise
        # converts seconds to frames at the model's nominal 16 fps and
        # under-counts: a "10s" request against a 25fps guide covered only
        # 6.4s of the performance.
        if ext in (".mp4", ".webm", ".mkv", ".mov", ".avi", ".m4v"):
            try:
                result.update(probe_video_metadata(filepath) or {})
            except Exception:
                pass
        return result

    @router.get("/api/v1/uploads/{filename}")
    def serve_upload(filename: str):
        """Serve an uploaded image.

        Falls back to output-workspace resolution: Director-mode start frames are
        keyframe images that live in the pipeline's outputs workspace, never in
        uploads/, yet sidecars record only their basename — so gallery thumbnails,
        the info bar, and pencil-restore all ask this endpoint for them.
        """
        from services.win_safe_files import share_delete_file_response
        base = uploads_dir()
        filepath = safe_join(base, filename)
        if filepath is not None and os.path.isfile(filepath):
            response = share_delete_file_response(filepath)
        else:
            response = output_fallback(filename)
        # Whatever was uploaded, a browser must take it for the type the server says.
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    return router
