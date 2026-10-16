"""An inpainted picture keeps the transparency of its source.

``studio_image_alpha`` flattens a guide with alpha onto grey and a mask with alpha onto black before the engine reads them, and the
engine returns plain RGB: the transparent area outside the mask came back as opaque grey (Sol, 2026-10-15). After the job has made
its picture, the source's alpha is put back here, from the copy of it saved beside the flattened guide:

* outside the mask: the source's alpha, exactly (a soft edge of the mask blends towards opaque);
* inside the mask, the edited region: opaque;
* the colour of a partly transparent source pixel outside the mask (at least 30 % opaque) had the grey mixed in by the flattening: it is
  taken out again.

Only a PNG or WebP can carry it. A JPEG output, a source without transparency, an outpaint, a picture that already has alpha, or a
picture of another shape than the source is left exactly as the engine wrote it, and the sidecar says why. The result is written to the
same file name, so the gallery, the sidecar and every link keep working. The vendored engine is not touched.
"""
from __future__ import annotations

import os
import uuid
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin

from services.studio_image_alpha import FLATTEN_ROLES, alpha_plane_path

FORMATS = {".png": "PNG", ".webp": "WEBP"}
PICTURES = {*FORMATS, ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff"}
GREY = FLATTEN_ROLES["image_guide"][0]
# Taking the grey out divides by the opacity, which multiplies any difference between what the engine returned and the flattened
# source (the engine does not give the composite back pixel-exact). Under this share of opacity the engine's colour is kept: a
# slightly grey tint on a pixel that is at most a third opaque is hardly seen, a clipped colour is.
LEAST_OPACITY = 0.3
# How far the output's shape may be from the source's (one pixel of rounding on a large picture) and still be the same picture.
ASPECT_TOLERANCE = 0.02


class _Skipped(Exception):
    """The picture is left as the engine wrote it; the reason goes to the sidecar."""


def _single(value):
    if isinstance(value, list):
        value = value[0] if len(value) == 1 else None
    return value if isinstance(value, str) and value else None


def _inpaint_sources(params) -> tuple[Path, Path] | None:
    """The saved alpha of the guide and the mask picture of an inpaint (a guide, a mask and the selectors that use both)."""
    guide, mask = _single(params.get("image_guide")), _single(params.get("image_mask"))
    selector = str(params.get("video_prompt_type") or "")
    if not guide or not mask or params.get("video_guide_outpainting") or not {"V", "A"} <= set(selector):
        return None
    plane = alpha_plane_path(guide)
    if plane is None or not plane.is_file() or not Path(mask).is_file():
        return None
    return plane, Path(mask)


def _layer(path: Path, size: tuple[int, int]) -> Image.Image:
    """A grey layer of the source's shape at the output's size."""
    with Image.open(path) as opened:
        opened.load()
        layer = opened.convert("L")
    if layer.size == size:
        return layer
    if abs(layer.width / layer.height - size[0] / size[1]) > ASPECT_TOLERANCE * size[0] / size[1]:
        raise _Skipped("size_mismatch")
    return layer.resize(size, Image.Resampling.BILINEAR)


def _composite(colour: np.ndarray, original: np.ndarray, weight: np.ndarray) -> np.ndarray:
    """RGBA from the engine's RGB, the source's alpha and the mask's weight (all 8 bit, one pixel each)."""
    opacity = original.astype(np.float32)[..., None] / 255
    inside = weight.astype(np.float32)[..., None] / 255
    pixels = colour.astype(np.float32)
    # What the engine kept of the source outside the mask is the source over grey: take the grey out again.
    clean = np.where(opacity >= LEAST_OPACITY, (pixels - (1 - opacity) * GREY) / np.maximum(opacity, LEAST_OPACITY), pixels)
    colour = inside * pixels + (1 - inside) * np.clip(clean, 0, 255)
    alpha = original.astype(np.float32) + np.rint((255 - original.astype(np.float32)) * inside[..., 0])
    return np.dstack([np.rint(colour), alpha]).clip(0, 255).astype(np.uint8)


def _write(path: str, result: np.ndarray, kind: str, text: dict) -> None:
    options: dict = {}
    if kind == "PNG":
        info = PngImagePlugin.PngInfo()
        for key, value in text.items():
            info.add_text(str(key), str(value))
        options["pnginfo"] = info
    else:
        options["lossless"] = True
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        Image.fromarray(result).save(temporary, format=kind, **options)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _restore(path: str, plane: Path, mask: Path) -> dict | None:
    kind = FORMATS.get(Path(path).suffix.lower())
    with Image.open(plane) as opened:
        opened.load()
        original = opened.convert("L")
    if original.getextrema()[0] == 255:
        return None  # a source that is opaque all over (the app's compose writes an alpha channel even then)
    if kind is None:
        raise _Skipped("output_format_without_alpha")
    with Image.open(path) as opened:
        opened.load()
        text = dict(getattr(opened, "text", {}) or {})
        rgba = opened.convert("RGBA")
    if rgba.getchannel("A").getextrema()[0] < 255:
        raise _Skipped("output_already_has_alpha")
    size = rgba.size
    if original.size != size:
        original = _layer(plane, size)
    result = _composite(np.asarray(rgba.convert("RGB")), np.asarray(original), np.asarray(_layer(mask, size)))
    _write(path, result, kind, text)
    return {"status": "restored", "from": "image_guide", "mask": "image_mask"}


def restore_inpaint_alpha(job, out_dir: str, name: str) -> dict | None:
    """The sidecar note for the output ``name`` of an inpaint job whose source had transparency, after putting that transparency back
    (None for any other output). It is done once per file: the sidecar is written more than once and the note is kept on the job."""
    sources = _inpaint_sources(job.get("params") or {})
    if sources is None or Path(name).suffix.lower() not in PICTURES:
        return None
    done = job.setdefault("_alpha_restored", {})
    if name not in done:
        try:
            done[name] = _restore(os.path.join(out_dir, name), *sources)
        except _Skipped as skipped:
            done[name] = {"status": "skipped", "reason": str(skipped)}
        except Exception as error:  # noqa: BLE001 - a picture that cannot be read or written stays as the engine made it
            done[name] = {"status": "skipped", "reason": f"unreadable ({type(error).__name__})"}
    return done[name]
