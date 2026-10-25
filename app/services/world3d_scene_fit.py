"""``fit`` in a ``world3d.scene.patch`` binding: size an object in metres instead of guessing its ``scale``.

A model object is drawn ``1.7 m x scale`` tall (its bounding-box height, whatever its length), so the scale that makes a
model some size depends on the GLB. ``fit`` does the sum from the GLB's own bounds (see ``world3d_scene_bounds``):

- ``{"heightM": 2.4}`` the bounding-box height. It is ``scale = heightM / 1.7`` and needs no file.
- ``{"widthM": 30}`` or ``{"depthM": 30}`` the model's own x or z extent, before ``rotationY``.
- ``{"longestM": 120}`` the longest of its three extents (a whole-environment GLB, a long ship).
- ``"native"`` the real size of the GLB, taken as metres.

Exactly one key; positive finite numbers. A binding that gives ``fit`` and ``scale`` is refused. The size comes from the
GLB's rest-pose box, so a bone-animated pose can reach outside it. An image cutout accepts ``heightM`` only
(a cutout plane is 2 m tall at scale 1).
"""
from __future__ import annotations

import math

from services.world3d_scene_bounds import CUTOUT_HEIGHT, MODEL_HEIGHT, normalisation, slot_native_bounds

FIT_DOC = ("fit: {heightM | widthM | depthM | longestM: metres} sets scale so that dimension of the model is that many metres "
           "(heightM needs no file; the others read the GLB bound by source_url in this or an earlier patch; widthM and depthM are "
           "the model's own x and z extents, before rotationY), or fit: \"native\" for the GLB's real size taken as metres. "
           "Give fit or scale, not both. Image cutouts accept heightM only.")
_DIMENSIONS = {"heightM": 1, "widthM": 0, "depthM": 2}
_ALIASES = {"height_m": "heightM", "width_m": "widthM", "depth_m": "depthM", "longest_m": "longestM"}
_MAX_METRES = 10_000
_NATIVE_SANE = (0.01, 30)        # a GLB taller or shorter than this is probably not authored in metres


def apply_fit(slot: dict, binding: dict, workspace: str | None, workspace_dir) -> list[str]:
    """Set ``slot["scale"]`` from the binding's ``fit``. Returns warnings. Raises ``invalid_fit`` or ``bounds_unavailable``."""
    if "fit" not in binding:
        return []
    if "scale" in binding:
        raise _refuse("invalid_fit", "Give fit or scale in a binding, not both")
    mode, metres = _parse(binding["fit"])
    media = slot.get("media") or "model3d"
    if media == "image" and slot.get("surface") == "cutout":
        return _fit_cutout(slot, mode, metres)
    if media != "model3d":
        raise _refuse("invalid_fit", f"{slot.get('id')}: fit sizes 3D models and image cutouts, not {media}")
    box = _box(slot, mode, workspace, workspace_dir)
    scale, warnings = _model_scale(slot, mode, metres, box)
    _set_scale(slot, scale, MODEL_HEIGHT)
    return warnings


def _refuse(code: str, message: str):
    from services.world3d_scenes import World3DSceneError
    return World3DSceneError(code, message)


def _parse(fit) -> tuple[str, float | None]:
    """``("native", None)`` or ``(heightM|widthM|depthM|longestM, metres)``."""
    if fit == "native":
        return "native", None
    if not isinstance(fit, dict) or len(fit) != 1:
        raise _refuse("invalid_fit", "fit is \"native\" or an object with exactly one of heightM, widthM, depthM, longestM")
    (key, value), = fit.items()
    key = _ALIASES.get(key, key)
    if key not in (*_DIMENSIONS, "longestM"):
        raise _refuse("invalid_fit", f"fit.{key} is not a dimension: use heightM, widthM, depthM or longestM")
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= _MAX_METRES:
        raise _refuse("invalid_fit", f"fit.{key} must be a number of metres above 0 and at most {_MAX_METRES}")
    return key, float(value)


def _box(slot: dict, mode: str, workspace: str | None, workspace_dir) -> dict | None:
    """The model's native box. ``heightM`` works without one; it only uses it to refuse a model with no height."""
    measured = slot_native_bounds(slot, workspace, workspace_dir) if workspace and workspace_dir is not None else {"ok": False, "reason": "no_workspace"}
    if measured["ok"]:
        return measured
    if mode == "heightM":
        return None
    raise _refuse("bounds_unavailable", f"{slot.get('id')}: fit.{mode} needs the size of the model's GLB, which cannot be read "
                  f"({measured['reason']}). Bind a .glb from the workspace as source_url in this patch, or use heightM.")


def _model_scale(slot: dict, mode: str, metres: float | None, box: dict | None) -> tuple[float, list[str]]:
    if mode == "heightM":
        if box is not None and box["size"][1] <= 1e-6:
            raise _refuse("invalid_fit", f"{slot.get('id')}: the model has no height to fit; use widthM, depthM or longestM")
        return metres / MODEL_HEIGHT, []
    height = box["size"][1]
    if mode == "native":
        warnings = [] if _NATIVE_SANE[0] <= height <= _NATIVE_SANE[1] else [
            f"fit_native_unusual: {slot.get('id')} is {height:g} units tall in its file; native size takes the file's units as metres"]
        return height / MODEL_HEIGHT, warnings
    extent = max(box["size"]) if mode == "longestM" else box["size"][_DIMENSIONS[mode]]
    if extent <= 1e-6:
        raise _refuse("invalid_fit", f"{slot.get('id')}: the model has no {mode[:-1]} to fit; use another dimension")
    return metres / (normalisation(box) * extent), []


def _fit_cutout(slot: dict, mode: str, metres: float | None) -> list[str]:
    if mode != "heightM":
        raise _refuse("invalid_fit", f"{slot.get('id')}: an image cutout accepts fit.heightM only")
    _set_scale(slot, metres / CUTOUT_HEIGHT, CUTOUT_HEIGHT)
    return []


def _set_scale(slot: dict, scale: float, base_height: float) -> None:
    scale = float(f"{scale:.8g}")        # eight significant digits: a small or a huge scale keeps its precision
    if not math.isfinite(scale) or scale <= 0:
        raise _refuse("invalid_fit", f"{slot.get('id')}: that size gives a scale of {scale}; choose a size the model can reach")
    slot["scale"] = scale
    if isinstance(slot.get("setItem"), dict):          # the editor keeps a placed item's real height in step with its scale
        slot["setItem"] = {**slot["setItem"], "heightM": scale * base_height}
