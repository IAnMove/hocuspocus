"""General image background-removal operation.

This module owns file handling only. The actual matte is delegated to the
shared :mod:`services.rembg_adapter` so Face Rig, preprocessing and Tools all
use the same U2Net implementation and session cache.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any

from PIL import Image

from services.character_kit_face_cleanup import (
    CharacterKitFaceCleanupError,
    _contained,
    classify_rgba_bytes,
    resolve_character_kit_image,
)
from services.rembg_adapter import DEFAULT_MODEL, remove_background_image


class BackgroundRemovalError(ValueError):
    """Raised when a background-removal source or output is not permitted."""


def _destination_root(
    output_dir: str,
    *,
    uploads_root: str,
    workspace_root: str,
) -> str:
    destination = os.path.realpath(os.path.abspath(output_dir))
    allowed_roots = tuple(
        os.path.realpath(os.path.abspath(root))
        for root in (uploads_root, workspace_root)
        if isinstance(root, str) and root
    )
    if not allowed_roots or not any(_contained(destination, root) for root in allowed_roots):
        raise BackgroundRemovalError("Background-removal destination is not allowed")
    return destination


def remove_background_file(
    source: str,
    *,
    uploads_root: str,
    workspace_root: str,
    output_dir: str,
    destination_workspace_root: str | None = None,
    model: str = DEFAULT_MODEL,
    remove_background: Callable[[Image.Image], Image.Image] | None = None,
) -> dict[str, Any]:
    """Write a transparent PNG derived from ``source`` without mutating it."""
    try:
        original = resolve_character_kit_image(
            source,
            uploads_root=uploads_root,
            workspace_root=workspace_root,
        )
    except CharacterKitFaceCleanupError as exc:
        raise BackgroundRemovalError(str(exc)) from exc

    destination_root = _destination_root(
        output_dir,
        uploads_root=uploads_root,
        workspace_root=destination_workspace_root or workspace_root,
    )
    os.makedirs(destination_root, exist_ok=True)

    with Image.open(original) as opened:
        source_image = opened.convert("RGBA")
        matte = (remove_background or (
            lambda image: remove_background_image(image, model=model)
        ))(source_image)
        if not isinstance(matte, Image.Image):
            raise BackgroundRemovalError("Background removal did not return an image")
        result = matte.convert("RGBA")

    stem = os.path.splitext(os.path.basename(original))[0]
    filename = f"{stem}.no-background-{uuid.uuid4().hex[:8]}.png"
    destination = os.path.join(destination_root, filename)
    if os.path.realpath(destination) == os.path.realpath(original):
        raise BackgroundRemovalError("Background removal must not overwrite the source")

    temporary = f"{destination}.{os.getpid()}.partial"
    try:
        result.save(temporary, format="PNG")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass

    metrics = classify_rgba_bytes(result.tobytes(), result.width, result.height)
    uploads_real = os.path.realpath(os.path.abspath(uploads_root))
    public = (
        f"/api/v1/uploads/{filename}"
        if _contained(destination, uploads_real)
        else f"/api/v1/file/{filename}"
    )
    return {
        "filename": filename,
        "source": public,
        "path": destination,
        "width": result.width,
        "height": result.height,
        "original": os.path.basename(original),
        "alpha": metrics,
        "method": "rembg-u2net",
        "model": model or DEFAULT_MODEL,
    }


__all__ = ["BackgroundRemovalError", "remove_background_file"]
