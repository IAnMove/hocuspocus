"""Shared rembg/U2Net adapter used by image cleanup workflows.

The application has several places that need the same matte operation. Keep
model/session creation here so a new tool cannot accidentally grow a second
copy of the inference contract (or reload U2Net for every image).
"""

from __future__ import annotations

from functools import lru_cache
from io import BytesIO
from typing import Any

from PIL import Image


DEFAULT_MODEL = "u2net"
_TRANSPARENT_BACKGROUND = [255, 255, 255, 0]


@lru_cache(maxsize=8)
def _session_for(model: str, force_cpu: bool = False):
    """Return one process-local rembg session per model/runtime pair."""
    from rembg import new_session

    if force_cpu:
        # Recast's edge-refinement path deliberately keeps U2Net off the
        # diffusion GPU.  Keep that policy in this shared adapter so callers
        # do not grow their own rembg/session construction copy.
        import onnxruntime as ort

        original_get_device = ort.get_device
        try:
            ort.get_device = lambda: "CPU"
            return new_session(model)
        finally:
            ort.get_device = original_get_device
    return new_session(model)


def background_session(model: str = DEFAULT_MODEL, *, force_cpu: bool = False):
    """Return the cached rembg session used by all background operations."""
    selected_model = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    return _session_for(selected_model, bool(force_cpu))


def remove_background_image(
    image: Image.Image,
    *,
    model: str = DEFAULT_MODEL,
    session: Any = None,
    **options: Any,
) -> Image.Image:
    """Remove the background from one PIL image and return an RGBA image.

    ``session`` and extra rembg options remain injectable for existing
    preprocessing paths and tests. Normal callers share the cached U2Net
    session and the same transparent-background defaults.

    Pass ``bgcolor=None`` to skip rembg's background composite. Face Rig
    overlays need that so translucent edge pixels keep their original RGB
    instead of picking up a white mix that shows as a halo.
    """
    if not isinstance(image, Image.Image):
        raise TypeError("Background removal expects a PIL image")

    from rembg import remove

    selected_model = str(model or DEFAULT_MODEL).strip() or DEFAULT_MODEL
    active_session = session if session is not None else background_session(selected_model)
    kwargs = {
        "session": active_session,
        "alpha_matting": True,
        "bgcolor": list(_TRANSPARENT_BACKGROUND),
        **options,
    }
    # rembg only composites when bgcolor is not None. Drop the key so callers
    # can restore the historical "no mix" cutout used by Face Rig overlays.
    if kwargs.get("bgcolor") is None:
        kwargs.pop("bgcolor", None)
    cleaned = remove(image.convert("RGBA"), **kwargs)
    if isinstance(cleaned, Image.Image):
        return cleaned.convert("RGBA")
    if isinstance(cleaned, (bytes, bytearray)):
        with Image.open(BytesIO(cleaned)) as opened:
            return opened.convert("RGBA")
    with Image.open(cleaned) as opened:
        return opened.convert("RGBA")


def clear_session_cache() -> None:
    """Release cached Python references, primarily for model/runtime teardown."""
    _session_for.cache_clear()


__all__ = [
    "DEFAULT_MODEL", "background_session", "clear_session_cache",
    "remove_background_image",
]
