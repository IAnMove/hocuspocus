"""A guide or mask picture with an alpha channel, made fit for the engine's frame readers before the job is admitted.

The native engine reads an image guide and mask as one video frame of three colour channels. A PNG with an alpha channel (the app's own
``media.compose`` writes them, even when every pixel is opaque) arrives with four, and the job fails in its first stage with a shape
error (``operands could not be broadcast together``, ``expanded size of the tensor (4) must match the existing size (3)``). The picture is
composited onto a flat background, as a copy next to the uploads: a mask onto black (transparent is not masked), a source onto neutral
grey. The copy is named by the sha256 of the picture it comes from, so the same picture is flattened once. The vendored engine is not touched.

A guide's own alpha is kept beside its copy (``{sha256[:32]}-image_guide.alpha.png``, 8 bit grey): the engine returns plain RGB, and
``studio_image_alpha_restore`` puts the source's transparency back on an inpainted picture from it.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

from PIL import Image

FLATTENED_DIR = ".studio-flattened"
FLATTEN_ROLES = {"image_mask": (0, 0, 0), "image_guide": (127, 127, 127)}


def has_alpha(picture: Image.Image) -> bool:
    return picture.mode in ("RGBA", "LA", "PA") or "transparency" in picture.info


def alpha_plane_path(flat_copy: str) -> Path | None:
    """Where the alpha of the guide that ``flat_copy`` is the flattened copy of is kept (None for any other file)."""
    path = Path(flat_copy)
    if path.parent.name != FLATTENED_DIR or not path.name.endswith("-image_guide.png"):
        return None
    return path.with_name(path.name[: -len(".png")] + ".alpha.png")


def _write_png(picture: Image.Image, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_name(f"{target.name}.{uuid.uuid4().hex}.tmp")
    picture.save(temporary, format="PNG")
    os.replace(temporary, target)


def flattened(path: str, role: str, sha256: str, folder: str) -> str:
    """``path`` itself, or for a picture with alpha the RGB copy of it in ``folder`` (created when it is not there yet). A guide's
    alpha is saved beside its copy, also for a copy made before that existed."""
    with Image.open(path) as picture:
        if role not in FLATTEN_ROLES or not has_alpha(picture):
            return path
        target = Path(folder) / FLATTENED_DIR / f"{sha256[:32]}-{role}.png"
        plane = alpha_plane_path(str(target))
        if target.is_file() and (plane is None or plane.is_file()):
            return str(target)
        rgba = picture.convert("RGBA")
    if plane is not None:
        _write_png(rgba.getchannel("A"), plane)
    if not target.is_file():
        flat = Image.new("RGB", rgba.size, FLATTEN_ROLES[role])
        flat.paste(rgba, mask=rgba.getchannel("A"))
        _write_png(flat, target)
    return str(target)
