"""MCP tools for the small animations of a character (walk, wave, anime expressions, the author's own).

``characters.animation.make`` is the way in: it starts the same server job the Character Creator and the Wizard start
(services/character_animation_job.py), so a person reviews in the app what an agent made, and the other way round.
``characters.animation.make_set`` makes several in turn as one job (the full walks of the five directions,
services/character_animation_set_job.py); ``.status`` and ``.cancel`` follow either kind of job. The catalog and
the single-pose prompt (``characters.animations``) and the sheet joiner (``characters.animation.sheet``) stay for an agent that
wants to make the poses itself. ``characters.animation.review`` approves or rejects one for a person, but only in «Modo un solo
disparo» (``agent_autonomy`` = ``one_shot``, services/agent_autonomy.py). Each tool is a thin projection of an HTTP route
(routers/character_animation_jobs.py, routers/character_animation_review.py, routers/character_kit_face.py), like the rest of
services/series_commands.py, which merges ``OPERATIONS`` and ``RUNNERS``.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

from services.character_animations import CUSTOM_VIEWS, MAX_CUSTOM_POSES, catalog

_WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_CUSTOM_VIEW = {"enum": list(CUSTOM_VIEWS)}
_SET = {"enum": list(catalog()["sets"])}
_BASE = "/api/v1/character-kits/animations"
SET_JOB_PREFIX = "animset-"

# name: (properties, required, mutation, description)
OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "characters.animations": (
        {"animation": {"type": "string", "maxLength": 64}, "pose": {"type": "string", "maxLength": 120},
         "description": {"type": "string", "maxLength": 2000}, "style": {"type": "string", "maxLength": 80},
         "custom": {"type": "object", "additionalProperties": False, "required": ["view", "text"], "properties": {
             "view": _CUSTOM_VIEW, "text": {"type": "string", "maxLength": 600}}}},
        [], False,
        "List the small animations one character can have (cycles walk, run, step, idle, jump; gestures wave, nod, shake, point, "
        "shrug, bow, clap, cheer, salute, facepalm, think; the usual anime expressions angry, surprised, sad, happy, embarrassed, "
        "scared, smug, confused, determined, tired, love, disgusted, bored, worried, nervous, laughing, wink, pout), each as a few "
        "poses, the sheet contract (equal cells, boots on the line `feet` of a cell, the figure `figure` of its height) and each "
        "animation's scaleBy. Make one with characters.animation.make. To make the poses yourself instead, pass animation and pose "
        "(and the character's look as description, style optional) and get the prompt, negative prompt, screen colour and resolution "
        "for that pose: generation.image it with the character as image_refs, key it with studio.key in that screen and join the "
        "poses with characters.animation.sheet. For one the catalog does not list pass custom {view: bust | front | side, text: the "
        "words for that pose} with any animation and pose ids of your own (a slug each). Store it on the kit with characters.save as "
        "animations.<id> = {sheet, frames, fps, loop, facing, reviewState: pending}. The Video 2D cards walk-cycle-sheet, "
        "walk-two-pose and character-reaction play the sheet. A character that moves in a 3D set has five directions "
        "(side, front, front34, back34, back; the ones that look left are these mirrored when rendered, never generated) and each "
        "animation of a kit carries motion (walk | idle) and dir; the catalog's walk-12 (side), walk-front, walk-front34, "
        "walk-back34 and walk-back are twelve-pose walks at 12 fps, idle-side, idle (front), idle-front34, idle-back34 and "
        "idle-back two-pose breaths. Make them one by one with characters.animation.make or all together with "
        "characters.animation.make_set.",
    ),
    "characters.animation.make": (
        {"workspace": _WORKSPACE, "character_id": _ID, "animation": {"type": "string", "minLength": 1, "maxLength": 64},
         "custom": {"type": "object", "additionalProperties": False, "required": ["title", "view", "poses"], "properties": {
             "title": {"type": "string", "maxLength": 80}, "view": _CUSTOM_VIEW,
             "poses": {"type": "array", "minItems": 1, "maxItems": MAX_CUSTOM_POSES, "items": {"type": "string", "maxLength": 600}}}},
         "pose": {"type": "string", "maxLength": 120}, "model": {"type": "string", "maxLength": 80},
         "method": {"enum": ["poses", "video"]}, "autoApprove": {"type": "boolean"}},
        ["workspace", "character_id", "animation"], True,
        "Make one animation of a saved character on the server: the job the Character Creator (Characters › Animaciones) and the "
        "Wizard start too. Every pose is made with the character's own picture as the identity reference (default model qwen_image_21_turbo; "
        "model minimax:image-01 uses no GPU, keeps only the face of that picture and invents the outfit), "
        "keyed on its screen, joined into one sprite sheet that keeps the figure one size, and saved on the kit as animations.<id> "
        "with reviewState pending. animation is an id from characters.animations (walk, wave, angry, cheer...); for one of your own "
        "pass a new slug and custom {title, view bust|front|side|front34|back34|back, poses: one text per pose, up to 12}. pose makes that one pose of an "
        "animation already made again and keeps the others. Returns a job: follow it with characters.animation.status (poses, "
        "stage, result); a failure keeps the poses already made, so make it again to continue. One animation is made at a time. "
        "It is saved pending: a person plays it in Characters › Animaciones and approves or rejects it. Approve it yourself only with "
        "characters.animation.review, and only when the owner turned on the one-shot mode (agent_autonomy = one_shot); otherwise that tool "
        "refuses. In that mode autoApprove: true makes the job approve it for you when the sheet passes the automatic checks (cell count "
        "and size, figures filled with clean alpha and not a keyed rectangle, feet on one ground line, figures of one size); a sheet that "
        "fails stays pending and the job lists the failed checks. autoApprove is ignored, with a note, when the mode is review. "
        "method video (optional; omit it, or pass poses, for the path above) makes a catalog walk from one LTX-2.3 clip guided by the "
        "OpenPose gait video, keys it and samples the same sheet. It needs LTX-2.3 distilled and the union-control LoRA installed, and it "
        "refuses a single pose or an animation that is not a walk. characters.animation.make_set stays pose by pose.",
    ),
    "characters.animation.make_set": (
        {"workspace": _WORKSPACE, "character_id": _ID, "set": _SET, "model": {"type": "string", "maxLength": 80}, "autoApprove": {"type": "boolean"}},
        ["workspace", "character_id", "set"], True,
        "Make several animations of a saved character in turn as ONE server job, for a character that moves in a 3D set: set walk-directions "
        "makes the twelve-pose walks of the five directions (walk-12 side, then walk-front34, walk-front, walk-back34, walk-back; the "
        "directions that look left are these mirrored when rendered, never generated), walk-12 only the profile walk, idle-directions the "
        "two-pose breaths. Only the sheets the character does not have yet are made, one after another (the GPU makes one at a time), each "
        "as the job of characters.animation.make with the character's own picture and the first pose of the neighbouring direction as "
        "identity references (default model qwen_image_21_turbo; model minimax:image-01 takes only the character's own picture). Every sheet is saved pending with motion and dir and the same automatic "
        "checks (and, for a direction, that it is not the copy or the mirror of another direction of the kit); a person plays and approves "
        "them in Characters › Animaciones, or with autoApprove: true and the owner's one-shot mode (agent_autonomy = one_shot) each sheet "
        "that passes the checks is approved for you (ignored with a note in review mode, like characters.animation.make). Returns a set "
        "job (id animset-...): follow it with characters.animation.status (status, done/total, sheets: one entry per sheet with its status "
        "waiting | running | completed | skipped | failed | cancelled, its jobId, reviewState and failed checks) and stop it with "
        "characters.animation.cancel. It is resumable: a failure, a cancel or a restart keeps every sheet and pose made, and calling "
        "make_set again skips the sheets the character has and continues.",
    ),
    "characters.animation.review": (
        {"workspace": _WORKSPACE, "character_id": _ID, "animation": {"type": "string", "minLength": 1, "maxLength": 64},
         "decision": {"enum": ["approve", "reject"]}, "note": {"type": "string", "maxLength": 500}},
        ["workspace", "character_id", "animation", "decision"], True,
        "Approve or reject an animation of a saved character, as the agent: only when the owner turned on the one-shot mode (Settings › "
        "Services, agent_autonomy = one_shot). In the default review mode it refuses with an error: a person approves it in Characters › "
        "Animaciones. Look at the sheet first (its picture is result.sheet of characters.animation.status; the figure should be the same "
        "character, one size, feet on one line). note is why, up to 500 characters; the app shows the animation as «approved by the agent» "
        "with that note so the owner can audit and revert it. A rejected animation keeps its poses: make one pose again with "
        "characters.animation.make (pose) or all of it again. A decision a person already gave is not overturned.",
    ),
    "characters.animation.status": (
        {"workspace": _WORKSPACE, "job_id": _ID}, ["workspace", "job_id"], False,
        "Read an animation job of characters.animation.make, or a set job of characters.animation.make_set (id animset-...: its sheets and "
        "done/total): queued, running (stage poses | sheet, each pose waiting | generating | "
        "keying | ready | failed), completed (result: animation, sheet, count, reviewState; with autoApprove also autoApproved and checks), "
        "failed (error), cancelling, cancelled or interrupted "
        "(a restart). Poses already made are kept for the next try.",
    ),
    "characters.animation.cancel": (
        {"workspace": _WORKSPACE, "job_id": _ID}, ["workspace", "job_id"], True,
        "Stop an animation job of characters.animation.make, or a set job of characters.animation.make_set (id animset-...); the sheets and "
        "poses already made stay for the next try.",
    ),
    "characters.animation.sheet": (
        {"workspace": _WORKSPACE, "sources": {"type": "array", "items": {"type": "string", "maxLength": 1200}, "minItems": 1, "maxItems": 12},
         "name": {"type": "string", "maxLength": 80}, "columns": {"type": "integer", "minimum": 1, "maximum": 12},
         "scaleBy": {"enum": ["height", "base", "face"]}},
        ["workspace", "sources"], True,
        "Join 1 to 12 keyed pose pictures (workspace files with alpha, from studio.key) into one sprite sheet PNG of equal "
        "cells, in the order given: each pose is cropped to its outline, the boots stand on one line (96 % of the cell) and the upper "
        "body is centred, so legs that swing do not move the torso. scaleBy height (default; cycles): all share one scale "
        "(the tallest fills 86 % of a cell, so a crouch stays lower than a stand); base (a whole figure making a gesture): each pose is "
        "scaled so its legs are as wide as in the others; face (a bust): so its head is as big as in the others (read with the face "
        "landmarks, else the height is used; the reply says scaleBy used). The model draws every pose at a slightly different size, "
        "and a raised hand only makes a figure taller. Returns source (a workspace URL), width, height, count, columns, rows and "
        "the cell: bind it to the Video 2D card walk-cycle-sheet (controls frames = count, columns) or character-reaction.",
    ),
}


def _catalog(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    result = request("GET", f"{_BASE}/catalog")
    if data.get("animation") and data.get("pose"):
        body = {key: data[key] for key in ("animation", "pose", "description", "style", "custom") if key in data}
        result = {**result, "prompt": request("POST", f"{_BASE}/prompt", body=body)}
    return result


def _sheet(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {key: data[key] for key in ("workspace", "sources", "name", "columns", "scaleBy") if key in data}
    return request("POST", f"{_BASE}/sheet", body=body)


def _make(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {"workspace": data["workspace"], "kitId": data["character_id"], "animation": data["animation"],
            **{key: data[key] for key in ("custom", "pose", "model", "method", "autoApprove") if key in data}}
    return request("POST", f"{_BASE}/make", body=body)


def _review(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {"workspace": data["workspace"], "kitId": data["character_id"], "animation": data["animation"], "decision": data["decision"],
            **({"note": data["note"]} if "note" in data else {})}
    return request("POST", f"{_BASE}/review", body=body)


def _make_set(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {"workspace": data["workspace"], "kitId": data["character_id"], "set": data["set"], **{key: data[key] for key in ("model", "autoApprove") if key in data}}
    return request("POST", f"{_BASE}/make-set", body=body)


def _job_path(job_id: Any) -> str:
    """A set job (id animset-...) lives under /sets, an animation job under /jobs."""
    kind = "sets" if str(job_id).startswith(SET_JOB_PREFIX) else "jobs"
    return f"{_BASE}/{kind}/{quote(str(job_id), safe='')}"


def _status(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    return request("GET", _job_path(data["job_id"]), query={"workspace": data["workspace"]})


def _cancel(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    return request("POST", f"{_job_path(data['job_id'])}/cancel", body={"workspace": data["workspace"]})


RUNNERS: dict[str, Callable[..., Any]] = {
    "characters.animations": _catalog,
    "characters.animation.make": _make,
    "characters.animation.make_set": _make_set,
    "characters.animation.review": _review,
    "characters.animation.status": _status,
    "characters.animation.cancel": _cancel,
    "characters.animation.sheet": _sheet,
}
