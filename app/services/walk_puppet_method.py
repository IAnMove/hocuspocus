"""Make a catalog walk by cutting ONE drawing into rigid pieces (services/walk_puppet.py).

``method`` ``puppet`` on the animation job (services/character_animation_job.py) is the only caller. The default
method stays pose by pose. The front walk uses the rest pose of ``idle``. Every other direction uses ``contact-a``
of that direction's twelve-pose walk. A reference the kit does not have yet is drawn by the same job and is not
saved as a second animation.

See-through layers, when they are installed, separate the clothes. Without them the cut follows the bones and the
job warns ``puppet_no_layers``. The drawing then needs the legs apart and no skirt. The gait check still runs.
"""
from __future__ import annotations

import hashlib
import os
from collections.abc import Callable
from typing import Any

import cv2
import numpy as np
from PIL import Image

from services.character_animation_directions import contract_of
from services.character_animations import pose_prompt
from services.character_kit_face_cleanup import resolve_character_kit_image
from services.local_generation import file_url
from services.see_through_layers import decompose_image, installed, save_layers
from services.walk_puppet import LAYER_NAMES, build, find_joints, load_layers

# The catalog has no pose id ``idle-rest``. Front is the rest pose of ``idle``; the other directions are contact-a.
REFERENCE = {"front": ("idle", "rest"), "side": ("walk-12", "contact-a"), "front34": ("walk-front34", "contact-a"),
             "back34": ("walk-back34", "contact-a"), "back": ("walk-back", "contact-a")}


class PuppetMethodError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def accept_puppet(definition: dict[str, Any], pose: str | None) -> str:
    """``puppet`` is a whole catalog walk, never one pose and never a gesture."""
    if pose:
        raise PuppetMethodError("puppet_is_a_cycle", "method puppet makes the whole walk from one drawing; leave pose out")
    if definition.get("custom") or definition.get("guide") != "walk":
        raise PuppetMethodError("puppet_not_a_walk", "method puppet is only for a catalog walk; this animation is still made pose by pose")
    return "puppet"


def reference_of(definition: dict[str, Any], override: dict[str, Any] | None) -> tuple[str, str]:
    """The drawing the cycle is cut from: an override, else the pose this direction cuts best."""
    if isinstance(override, dict) and override.get("animation") and override.get("pose"):
        return str(override["animation"]), str(override["pose"])
    if override:
        raise PuppetMethodError("invalid_reference", "reference is {animation, pose}")
    direction = contract_of(definition["id"], definition).get("dir") or "side"
    return REFERENCE.get(direction, REFERENCE["side"])


def frame_source(kit: dict[str, Any], animation_id: str, pose_id: str) -> str:
    """The keyed picture of that pose on the kit, or nothing."""
    frames = ((kit.get("animations") or {}).get(animation_id) or {}).get("frames") or []
    for frame in frames:
        if frame.get("id") == pose_id and frame.get("source"):
            return str(frame["source"])
    return ""


def _rgba_of(source: str, uploads_root: str, workspace_root: str) -> np.ndarray:
    path = resolve_character_kit_image(source, uploads_root=uploads_root, workspace_root=workspace_root)
    with Image.open(path) as image:
        return np.array(image.convert("RGBA"))


def _cached_layers(folder: str) -> dict[str, np.ndarray] | None:
    """Layers from a finished write. A folder without ``.complete`` is still being written."""
    if not os.path.isdir(folder) or not os.path.isfile(os.path.join(folder, ".complete")):
        return None
    return load_layers(folder) or None


def _write_layers(images: dict[str, Image.Image], folder: str) -> dict[str, np.ndarray]:
    os.makedirs(folder, exist_ok=True)
    arrays = {}
    for name, image in images.items():
        if name not in LAYER_NAMES:
            continue
        image.convert("RGBA").save(os.path.join(folder, f"{name}.png"))
        arrays[name] = np.array(Image.open(os.path.join(folder, f"{name}.png")).convert("RGBA"))
    with open(os.path.join(folder, ".complete"), "w", encoding="utf-8") as marker:
        marker.write("ok\n")
    return arrays


def garment_layers(rgba: np.ndarray, workspace_root: str, kit_id: str, workspace: str, *,
                   installed_fn: Callable[[], bool], decompose: Callable[..., dict]) -> tuple[dict[str, np.ndarray] | None, bool]:
    """Garment layers for this drawing. The second value is false only when See-through is not installed.

    A later job with the same pixels reads ``puppet-layers/<hash>/``. ``save_layers`` also keeps a content-hashed copy.
    The kit record stores only the boolean: the library drops keys it does not know.
    """
    folder = os.path.join(workspace_root, "puppet-layers", hashlib.sha256(rgba.tobytes()).hexdigest()[:20])
    cached = _cached_layers(folder)
    if cached:
        return cached, True
    if not installed_fn():
        return None, False
    from services import resource_scheduler
    lane = resource_scheduler.local_gpu_lane(0)
    task = f"see-through-puppet-{kit_id or 'rig'}"
    with resource_scheduler.coordinator.acquire(lane, task_id=task, description="See-through layers"):
        pack = decompose(Image.fromarray(rgba), "puppet")
    arrays = _write_layers(pack.get("images") or {}, folder)
    save_layers({"puppet": pack}, kit_id, workspace_root, workspace)
    return (arrays or None), True


def _names(job: dict[str, Any]) -> list[str]:
    definition, suffix = job["definition"], job["jobId"][-6:]
    return [f"{job['kitId']}-{definition['id']}-{pose['id']}-{suffix}.png" for pose in definition["poses"]]


# The flat colour each screen mode of ``studio.key`` removes.
SCREEN_RGB = {"green": (0, 255, 0), "blue": (0, 0, 255), "magenta": (255, 0, 255)}


def _on_screen(frame: np.ndarray, screen: str) -> np.ndarray:
    """A mould frame is transparent, but ``studio.key`` reads colour only and would keep a black rectangle. Lay the
    frame on the screen colour the same job keys, as the pose-by-pose and the video paths draw theirs."""
    ground = np.array(SCREEN_RGB.get(screen, SCREEN_RGB["green"]), np.float32)
    alpha = frame[..., 3:4].astype(np.float32) / 255.0
    return np.rint(frame[..., :3].astype(np.float32) * alpha + ground * (1.0 - alpha)).astype(np.uint8)


def _store_frames(frames: list[np.ndarray], size: tuple[int, int], root: str, names: list[str], screen: str = "green") -> None:
    """The mould draws at twice the picture. The sheet wants the picture's own size, on the screen colour."""
    height, width = size
    for frame, name in zip(frames, names):
        small = cv2.resize(_on_screen(frame, screen), (width, height), interpolation=cv2.INTER_AREA)
        Image.fromarray(small).save(os.path.join(root, name))


def _screen(job: dict[str, Any]) -> str:
    definition = job["definition"]
    return pose_prompt(definition["id"], definition["poses"][0]["id"], job.get("description") or "", job.get("style"))["screen"]


def _key_all(job: dict[str, Any], tools: Any, names: list[str], screen: str, update: Callable[..., None]) -> None:
    for take, name in zip(job["takes"], names):
        take["status"] = "keying"
        update()
        take.update(status="ready", raw=file_url(name, job["workspace"]), keyed=tools.key(f"{job['jobId']}-{take['id']}-key", name, screen))
    update()


def fill_puppet_takes(job: dict[str, Any], tools: Any, *, workspace_root: str, uploads_root: str, kit: dict[str, Any],
                      draw: Callable[[str, str], str], installed_fn: Callable[[], bool] | None = None,
                      update: Callable[..., None]) -> None:
    """Cut the reference drawing into one keyed frame per pose. The caller joins the sheet.

    ``draw(animation, pose)`` returns a keyed picture when the kit does not have that pose yet. It must not save a
    second animation. ``installed_fn`` defaults to See-through's own probe.
    """
    animation, pose = reference_of(job["definition"], job.get("puppetReference"))
    source = frame_source(kit, animation, pose) or draw(animation, pose)
    rgba = _rgba_of(source, uploads_root, workspace_root)
    layers, used = garment_layers(rgba, workspace_root, job["kitId"], job["workspace"],
                                  installed_fn=installed if installed_fn is None else installed_fn, decompose=decompose_image)
    if not used:
        job["warnings"] = ["puppet_no_layers"]
    direction = contract_of(job["definition"]["id"], job["definition"]).get("dir") or "side"
    frames, info = build(rgba, direction, len(job["definition"]["poses"]), layers, find_joints(rgba))
    names, screen = _names(job), _screen(job)
    _store_frames(frames, rgba.shape[:2], workspace_root, names, screen)
    _key_all(job, tools, names, screen, update)
    record = {"method": "puppet", "reference": {"animation": animation, "pose": pose}, "start": float(info["start"]), "layers": used}
    job["puppet"] = record
    update(puppet=record, **({"warnings": job["warnings"]} if job.get("warnings") else {}))


__all__ = ["REFERENCE", "PuppetMethodError", "accept_puppet", "fill_puppet_takes", "frame_source", "reference_of"]
