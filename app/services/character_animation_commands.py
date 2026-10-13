"""MCP tools for the small animations of a character (walk, wave, anime expressions, the author's own).

``characters.animation.make`` is the way in: it starts the same server job the Character Creator and the Wizard start
(services/character_animation_job.py), so a person reviews in the app what an agent made, and the other way round. The catalog and
the single-pose prompt (``characters.animations``) and the sheet joiner (``characters.animation.sheet``) stay for an agent that
wants to make the poses itself. Each tool is a thin projection of an HTTP route (routers/character_animation_jobs.py,
routers/character_kit_face.py), like the rest of services/series_commands.py, which merges ``OPERATIONS`` and ``RUNNERS``.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

_WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_CUSTOM_VIEW = {"enum": ["bust", "front", "side"]}
_BASE = "/api/v1/character-kits/animations"

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
        "walk-two-pose and character-reaction play the sheet.",
    ),
    "characters.animation.make": (
        {"workspace": _WORKSPACE, "character_id": _ID, "animation": {"type": "string", "minLength": 1, "maxLength": 64},
         "custom": {"type": "object", "additionalProperties": False, "required": ["title", "view", "poses"], "properties": {
             "title": {"type": "string", "maxLength": 80}, "view": _CUSTOM_VIEW,
             "poses": {"type": "array", "minItems": 1, "maxItems": 6, "items": {"type": "string", "maxLength": 600}}}},
         "pose": {"type": "string", "maxLength": 120}, "model": {"type": "string", "maxLength": 80}},
        ["workspace", "character_id", "animation"], True,
        "Make one animation of a saved character on the server: the job the Character Creator (Characters › Animaciones) and the "
        "Wizard start too. Every pose is made with the character's own picture as the identity reference (default model qwen_image_21), "
        "keyed on its screen, joined into one sprite sheet that keeps the figure one size, and saved on the kit as animations.<id> "
        "with reviewState pending. animation is an id from characters.animations (walk, wave, angry, cheer...); for one of your own "
        "pass a new slug and custom {title, view bust|front|side, poses: one text per pose, up to 6}. pose makes that one pose of an "
        "animation already made again and keeps the others. Returns a job: follow it with characters.animation.status (poses, "
        "stage, result); a failure keeps the poses already made, so make it again to continue. One animation is made at a time. "
        "Never approve it yourself: a person plays it in Characters › Animaciones and approves or rejects it.",
    ),
    "characters.animation.status": (
        {"workspace": _WORKSPACE, "job_id": _ID}, ["workspace", "job_id"], False,
        "Read an animation job of characters.animation.make: queued, running (stage poses | sheet, each pose waiting | generating | "
        "keying | ready | failed), completed (result: animation, sheet, count), failed (error), cancelling, cancelled or interrupted "
        "(a restart). Poses already made are kept for the next try.",
    ),
    "characters.animation.cancel": (
        {"workspace": _WORKSPACE, "job_id": _ID}, ["workspace", "job_id"], True,
        "Stop an animation job of characters.animation.make; the poses already made stay for the next try.",
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
            **{key: data[key] for key in ("custom", "pose", "model") if key in data}}
    return request("POST", f"{_BASE}/make", body=body)


def _status(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    return request("GET", f"{_BASE}/jobs/{quote(str(data['job_id']), safe='')}", query={"workspace": data["workspace"]})


def _cancel(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    return request("POST", f"{_BASE}/jobs/{quote(str(data['job_id']), safe='')}/cancel", body={"workspace": data["workspace"]})


RUNNERS: dict[str, Callable[..., Any]] = {
    "characters.animations": _catalog,
    "characters.animation.make": _make,
    "characters.animation.status": _status,
    "characters.animation.cancel": _cancel,
    "characters.animation.sheet": _sheet,
}
