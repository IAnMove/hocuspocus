"""What an agent needs to see of a Video 3D working scene without seeing the frame: the camera, the light, the size and
duration, and where each object is and how big it really is, in metres.

``world3d.scene.inspect`` and every patch reply carry this next to ``objects``; ``objects`` itself is unchanged, so the
ids and roles patches address stay the same. Nothing here may fail an inspect: a model that cannot be measured has
``boundsM: null`` and a ``boundsReason``.
"""
from __future__ import annotations

from copy import deepcopy

from services.world3d_scene_bounds import CUTOUT_HEIGHT, MODEL_HEIGHT, placed_bounds, slot_native_bounds

MAX_ITEMS = 32
CONVENTION = (f"metres, y up. A 3D model is drawn {MODEL_HEIGHT:g} m x scale tall (its bounding-box height, whatever its length); "
              f"an image cutout {CUTOUT_HEIGHT:g} m x scale tall. boundsM.size is the model's own width, height and depth; "
              "boundsM.min/max/center/bottomY are in the scene after position and rotationY. A grounded object's lowest point sits at position[1].")
LAYOUT_DOC = ("It also shows the shot in metres: camera (the authored family, eye, look, fov, framing and a shake summary; an orbit, "
              "a framing or a shake moves the live camera from these), light, duration, size {width, height, fps} and layout.items, one per object "
              "(at most %d) with id, role, media, position, rotationY, scale, sourceUrl, clip and boundsM. boundsM is a 3D model's real size and place "
              "from its workspace .glb, by the renderer's own sums: a model is drawn 1.7 m x scale tall (its bounding-box height, whatever its length), "
              "so a whole-environment GLB is 1.7 m tall at scale 1. boundsM.size is its own width, height and depth; min, max, center and bottomY are "
              "scene coordinates after position and rotationY, and a grounded object's lowest point sits at position[1]. It is the rest pose, so an "
              "animation can reach outside it. boundsM is null with a boundsReason (marker, not_a_3d_model, outside_workspace, missing_file, not_glb, "
              "truncated, missing_min_max...) when the object cannot be measured. Publish a scene and it opens in the Video 3D editor's Open dialog."
              ) % MAX_ITEMS
_PLAIN_CAMERA = ("family", "eye", "look", "fov", "frameFormat", "orbitRadius", "orbitHeight", "orbitTurns", "eyeOffset", "targetOffset", "lensShift")
_FRAMING = ("targetSlot", "anchor", "from", "to", "lookFrom", "lookTo", "orbitTurns", "fovFrom", "fovTo", "relativeToFacing")


def scene_layout(document: dict, workspace: str | None, workspace_dir) -> dict:
    """``camera``, ``light``, ``duration``, ``size`` and ``layout`` of a scene document, ready to merge into a view."""
    camera, light = document.get("camera"), document.get("light")
    size = {key: document[key] for key in ("width", "height", "fps") if key in document}
    layout = _layout(document, workspace, workspace_dir)
    return {"camera": _camera(camera) if isinstance(camera, dict) else None,
            "light": deepcopy(light) if isinstance(light, dict) else None,
            "duration": document.get("duration"), "size": size, "layout": layout}


def _camera(camera: dict) -> dict:
    """The authored camera. Moving families (orbit, a framing, a shake) compute the live eye in the renderer from these."""
    summary = {key: deepcopy(camera[key]) for key in _PLAIN_CAMERA if key in camera}
    framing = camera.get("framing")
    if isinstance(framing, dict):
        summary["framing"] = {key: deepcopy(framing[key]) for key in _FRAMING if key in framing}
    windows = [window for window in camera.get("shake") or [] if isinstance(window, dict)]
    if windows:
        summary["shake"] = {"windows": len(windows), "start": _extreme(windows, "start", min), "end": _extreme(windows, "end", max),
                            "maxAmplitude": _extreme(windows, "amplitude", max)}
    return summary


def _extreme(windows: list[dict], key: str, pick):
    values = [window[key] for window in windows if isinstance(window.get(key), (int, float))]
    return pick(values) if values else None


def _layout(document: dict, workspace: str | None, workspace_dir) -> dict:
    slots = [slot for slot in document.get("slots") or [] if isinstance(slot, dict)]
    items = [_item(slot, workspace, workspace_dir) for slot in slots[:MAX_ITEMS]]
    layout = {"convention": CONVENTION, "items": items}
    if len(slots) > MAX_ITEMS:
        layout["omitted"] = len(slots) - MAX_ITEMS
    return layout


def _item(slot: dict, workspace: str | None, workspace_dir) -> dict:
    item = {"id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media") or "model3d",
            "position": slot.get("position"), "rotationY": slot.get("rotationY"), "scale": slot.get("scale"),
            "sourceUrl": slot.get("sourceUrl") or "", "clip": slot.get("clip")}
    for key in ("surface", "grounded"):
        if slot.get(key) is not None:
            item[key] = slot[key]
    item["boundsM"], reason = _bounds(slot, item["media"], workspace, workspace_dir)
    if reason:
        item["boundsReason"] = reason
    return item


def _bounds(slot: dict, media: str, workspace: str | None, workspace_dir) -> tuple[dict | None, str | None]:
    if media != "model3d":
        return None, "not_a_3d_model"
    if not workspace or workspace_dir is None:
        return None, "no_workspace"
    try:
        box = slot_native_bounds(slot, workspace, workspace_dir)
        if not box["ok"]:
            return None, box["reason"]
        return placed_bounds(box, slot), None
    except Exception:  # noqa: BLE001 - an object that cannot be measured never fails an inspect
        return None, "unmeasurable"
