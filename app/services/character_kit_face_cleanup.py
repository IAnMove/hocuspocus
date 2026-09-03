"""Clean a single Character Kit Face Rig overlay without overwriting the original."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlparse

from PIL import Image


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
DEFAULT_PADDING = 8


class CharacterKitFaceCleanupError(ValueError):
    """Raised when a Face Rig overlay cannot be resolved or cleaned."""


def _contained(path: str, root: str) -> bool:
    path_cmp = os.path.normcase(path)
    root_cmp = os.path.normcase(root)
    try:
        return os.path.commonpath((path_cmp, root_cmp)) == root_cmp
    except (TypeError, ValueError, OSError):
        return False


def resolve_character_kit_image(
    value: str,
    *,
    uploads_root: str,
    workspace_root: str,
) -> str:
    """Resolve one persistent image inside uploads or the active workspace."""
    if not isinstance(value, str) or not value.strip() or "\x00" in value:
        raise CharacterKitFaceCleanupError("Image source is not allowed")
    raw = value.strip()
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} or raw.startswith("/api/v1/"):
        path = unquote(parsed.path or raw)
        marker = "/api/v1/file/"
        upload_marker = "/api/v1/uploads/"
        if marker in path:
            raw = path.split(marker, 1)[1]
        elif upload_marker in path:
            raw = path.split(upload_marker, 1)[1]
        elif path.startswith("/api/v1/"):
            raise CharacterKitFaceCleanupError("Image source is not allowed")
    roots = tuple(dict.fromkeys(
        os.path.realpath(os.path.abspath(root))
        for root in (uploads_root, workspace_root)
        if isinstance(root, str) and root
    ))
    if len(roots) != 2:
        raise CharacterKitFaceCleanupError("Image roots are not available")
    if os.path.isabs(raw) or os.path.splitdrive(raw)[0]:
        candidates = (raw,)
    else:
        name = os.path.basename(raw)
        candidates = (raw, *(os.path.join(root, name) for root in roots))
    resolved: list[str] = []
    try:
        for candidate in candidates:
            path = os.path.realpath(os.path.abspath(candidate))
            if path not in resolved:
                resolved.append(path)
    except (OSError, ValueError) as exc:
        raise CharacterKitFaceCleanupError("Image source is not allowed") from exc
    allowed = [
        path for path in resolved
        if any(_contained(path, root) and path != root for root in roots)
        and os.path.splitext(path)[1].lower() in IMAGE_EXTENSIONS
    ]
    for path in allowed:
        if os.path.isfile(path):
            return path
    raise CharacterKitFaceCleanupError("Permitted image file was not found")


def classify_rgba_bytes(pixels: bytes, width: int, height: int) -> dict[str, Any]:
    expected = width * height * 4
    if width <= 0 or height <= 0 or len(pixels) != expected:
        return {
            "pixelCount": 0, "transparentRatio": 0.0, "translucentRatio": 0.0,
            "opaqueRatio": 0.0, "status": "unknown",
        }
    transparent = translucent = opaque = 0
    for index in range(3, len(pixels), 4):
        alpha = pixels[index]
        if alpha < 250:
            transparent += 1
            if alpha > 0:
                translucent += 1
        if alpha == 255:
            opaque += 1
    count = width * height
    transparent_ratio = transparent / count
    opaque_ratio = opaque / count
    status = "transparent" if transparent_ratio >= 0.01 else ("opaque" if opaque_ratio >= 0.99 else "unknown")
    return {
        "pixelCount": count,
        "transparentRatio": transparent_ratio,
        "translucentRatio": translucent / count,
        "opaqueRatio": opaque_ratio,
        "status": status,
    }


def crop_to_alpha(image: Image.Image, *, padding: int = DEFAULT_PADDING) -> Image.Image:
    rgba = image.convert("RGBA")
    alpha = rgba.getchannel("A")
    bbox = alpha.getbbox()
    if bbox is None:
        raise CharacterKitFaceCleanupError("Cleanup produced an empty overlay")
    left, top, right, bottom = bbox
    pad = max(0, int(padding))
    box = (
        max(0, left - pad),
        max(0, top - pad),
        min(rgba.width, right + pad),
        min(rgba.height, bottom + pad),
    )
    return rgba.crop(box)


def _rembg_remove(image: Image.Image) -> Image.Image:
    # Keep Face Rig and the general Tools operation on the same cached U2Net
    # adapter. The wrapper remains a named seam for existing tests/callers.
    from services.rembg_adapter import remove_background_image

    # Preserve Face Rig's historical rembg defaults while sharing session and
    # decoding through the common adapter.
    return remove_background_image(image, alpha_matting=False)


def clean_character_kit_overlay(
    source: str,
    *,
    uploads_root: str,
    workspace_root: str,
    output_dir: str | None = None,
    padding: int = DEFAULT_PADDING,
    remove_background: Callable[[Image.Image], Image.Image] | None = None,
) -> dict[str, Any]:
    """Matte one overlay, crop it, and publish a new PNG beside the original."""
    original = resolve_character_kit_image(
        source, uploads_root=uploads_root, workspace_root=workspace_root,
    )
    destination_root = os.path.realpath(os.path.abspath(output_dir or os.path.dirname(original)))
    if not (
        _contained(destination_root, os.path.realpath(os.path.abspath(uploads_root)))
        or _contained(destination_root, os.path.realpath(os.path.abspath(workspace_root)))
    ):
        raise CharacterKitFaceCleanupError("Cleanup destination is not allowed")
    os.makedirs(destination_root, exist_ok=True)
    with Image.open(original) as opened:
        source_image = opened.convert("RGBA")
        matted = (remove_background or _rembg_remove)(source_image)
        cropped = crop_to_alpha(matted, padding=padding)
    stem = os.path.splitext(os.path.basename(original))[0]
    filename = f"{stem}.cleanup-{uuid.uuid4().hex[:8]}.png"
    destination = os.path.join(destination_root, filename)
    if os.path.realpath(destination) == os.path.realpath(original):
        raise CharacterKitFaceCleanupError("Cleanup must not overwrite the original overlay")
    temporary = f"{destination}.{os.getpid()}.partial"
    try:
        cropped.save(temporary, format="PNG")
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
    metrics = classify_rgba_bytes(cropped.tobytes(), cropped.width, cropped.height)
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
        "width": cropped.width,
        "height": cropped.height,
        "original": os.path.basename(original),
        "alpha": metrics,
        "method": "rembg-u2net",
        "model": "u2net",
        "padding": max(0, int(padding)),
    }
