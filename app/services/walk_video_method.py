"""Make a catalog walk from one LTX-2.3 clip guided by the gait skeleton (services/walk_guide_video.py).

``method`` ``video`` on the animation job (services/character_animation_job.py) is the only caller. The default method
stays pose by pose. The clip is keyed with the same ``studio.key`` and sampled into the same sheet the runtime plays.

The weights are the LTX-2.3 distilled checkpoint and the union-control IC-LoRA already named by ``app/defaults/ltx2_22B.json``
(``preload_URLs``). This module does not download them. When they are absent, ``method`` ``video`` fails and the pose method
is unchanged.

Licence of that LoRA and of LTX-2.3: LTX-2 Community License (Lightricks),
https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-Union-Control. Worldwide, including the EU. Commercial use is
included for an entity under USD 10,000,000 annual revenue; a larger entity needs a paid licence from Lightricks
(ltxv-licensing@lightricks.com).
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from services.character_animation_directions import contract_of
from services.character_animation_guides import gait_of, guide_for
from services.character_animations import pose_prompt
from services.character_kit_face_cleanup import resolve_character_kit_image
from services.character_styles import screen_for, style_catalog
from services.local_generation import file_url
from services.walk_guide_video import CLIP_FRAMES, render_guide_video, sample_frames
from shared.utils.files_locator import locate_file

LTX_MODEL = "ltx2_22B_distilled"
RESOLUTION = "832x1104"
UNION_LORA = "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors"
DIFFUSION = "ltx-2.3-22b-distilled_diffusion_model.safetensors"
LICENCE = ("LTX-2 Community License (Lightricks). Worldwide, including the EU. Commercial use is included under "
           "USD 10,000,000 annual revenue; a larger entity needs a paid licence from Lightricks.")
NOT_INSTALLED = ("LTX-2.3 distilled and the union-control pose LoRA are not installed "
                 f"({DIFFUSION} and {UNION_LORA}). Install LTX-2.3 Distilled 22B from Settings; its preload includes the LoRA. "
                 "Leave method out to make this walk pose by pose.")
_FACING = {"side": "in right profile", "front": "from the front, toward the camera", "front34": "in front three-quarter view",
           "back34": "in back three-quarter view", "back": "from behind"}
_LORA_DIRS = ("loras", os.path.join("loras", "ltx2"), os.path.join("ckpts", "loras"), os.path.join("ckpts", "ltx2"))


class WalkVideoError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def accept_walk_method(method: str | None, definition: dict[str, Any], pose: str | None) -> str:
    """``poses`` (the default) or ``video``. ``video`` is a whole catalog walk, never one pose and never a gesture."""
    chosen = "poses" if method in (None, "", "poses") else str(method)
    if chosen not in ("poses", "video"):
        raise WalkVideoError("invalid_method", "method is poses or video")
    if chosen != "video":
        return "poses"
    if pose:
        raise WalkVideoError("video_is_a_cycle", "method video makes the whole walk in one clip; leave pose out")
    if definition.get("custom") or definition.get("guide") != "walk":
        raise WalkVideoError("video_not_a_walk", "method video is only for a catalog walk; this animation is still made pose by pose")
    return "video"


def _found(name: str) -> bool:
    if locate_file(name, error_if_none=False):
        return True
    return any(os.path.isfile(os.path.join(folder, name)) for folder in _LORA_DIRS)


def weights_present() -> bool:
    """Whether the distilled diffusion weights and the union-control LoRA are on disk. No checkpoint is loaded."""
    return _found(DIFFUSION) and _found(UNION_LORA)


def clip_prompt(job: dict[str, Any]) -> str:
    """One sentence for the whole cycle: the character, the direction, the skeleton, the flat screen colour."""
    definition = job["definition"]
    direction = contract_of(definition["id"], definition).get("dir") or "side"
    screen = screen_for(str(job.get("description") or ""))
    colour = style_catalog()["screens"][screen]
    who = job.get("description") or "the character"
    return (f"The same character as the reference image, {who}. One full-body walk cycle in place, {_FACING.get(direction, direction)}, "
            f"matching the OpenPose skeleton in the control video exactly, pose for pose, same camera. "
            f"Flat solid {colour} background, no scenery, no ground shadow, boots fully visible.")


def video_params(job: dict[str, Any], guide: dict[str, Any], prompt: str) -> dict[str, Any]:
    """``generation.video`` version 3: the character's picture, the raw skeleton clip, and the union-control LoRA.

    ``VG`` is the raw control (the frames are already OpenPose). The letter does not load the LoRA by itself, so the
    LoRA file is sent in ``activated_loras``.
    """
    return {"prompt": prompt, "model_type": LTX_MODEL, "resolution": RESOLUTION, "video_length": CLIP_FRAMES,
            "sliding_window_size": CLIP_FRAMES, "seed": int(job["takes"][0]["seed"]), "image_start": job["reference"],
            "video_guide": file_url(str(guide["file"]), job["workspace"]), "video_prompt_type": "VG",
            "activated_loras": [UNION_LORA], "loras_multipliers": "1"}


def clip_fields(job: dict[str, Any]) -> dict[str, str]:
    """The guide video and the clip, when this job made them, so the kit keeps a way to open them."""
    return {key: job[key] for key in ("guideVideo", "clip") if job.get(key)}


def _control(job: dict[str, Any], root: str) -> dict[str, Any]:
    definition = job["definition"]
    direction = contract_of(definition["id"], definition).get("dir") or "side"
    name = f"{job['kitId']}-{definition['id']}-walk-guide-{job['jobId'][-6:]}.mp4"
    return render_guide_video(direction, os.path.join(root, name))


def _names(job: dict[str, Any]) -> list[str]:
    definition, suffix = job["definition"], job["jobId"][-6:]
    return [f"{job['kitId']}-{definition['id']}-{pose['id']}-{suffix}.png" for pose in definition["poses"]]


def _key_one(job: dict[str, Any], tools: Any, take: dict[str, Any], pose: dict[str, Any], name: str, screen: str,
             root: str, uploads: str, update: Callable[..., None]) -> None:
    workspace, definition = job["workspace"], job["definition"]
    guide = guide_for(definition, pose["id"], workspace_root=root, name=f"{job['kitId']}-{definition['id']}-{pose['id']}-guide-{job['jobId'][-6:]}.png")
    shown = file_url(guide["file"], workspace) if guide else ""
    take.update(status="keying", raw=file_url(name, workspace), **({"guide": shown} if shown else {}))
    update()
    keyed = tools.key(f"{job['jobId']}-{pose['id']}-key", name, screen)
    drawn: dict[str, Any] = {"raw": file_url(name, workspace), "keyed": keyed, "seed": take["seed"]}
    if guide:
        drawn["guide"] = shown
        drawn["gait"] = gait_of(guide, resolve_character_kit_image(keyed, uploads_root=uploads, workspace_root=root))
    take.update(status="ready", **drawn)
    update()


def _screen(job: dict[str, Any]) -> str:
    definition = job["definition"]
    return pose_prompt(definition["id"], definition["poses"][0]["id"], job.get("description") or "", job.get("style"))["screen"]


def fill_video_takes(job: dict[str, Any], tools: Any, *, workspace_root: str, uploads_root: str, update: Callable[..., None]) -> None:
    """Render the guide, ask for one clip, sample a frame per pose and key it. The caller joins the sheet."""
    guide = _control(job, workspace_root)
    prompt = clip_prompt(job)
    update(guideVideo=file_url(str(guide["file"]), job["workspace"]), prompt=prompt)
    for take in job["takes"]:
        take["status"] = "generating"
    update()
    clip = tools.video(f"{job['jobId']}-clip", video_params(job, guide, prompt))
    update(clip=file_url(clip, job["workspace"]))
    names = _names(job)
    sample_frames(os.path.join(workspace_root, clip), workspace_root, names)
    screen = _screen(job)
    for take, pose, name in zip(job["takes"], job["definition"]["poses"], names):
        _key_one(job, tools, take, pose, name, screen, workspace_root, uploads_root, update)


__all__ = ["DIFFUSION", "LICENCE", "LTX_MODEL", "NOT_INSTALLED", "RESOLUTION", "UNION_LORA", "WalkVideoError",
           "accept_walk_method", "clip_fields", "clip_prompt", "fill_video_takes", "video_params", "weights_present"]
