"""HTTP and MCP doors for one round-headed body. The mesh work lives in blob_make."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from services.blob_builder import PRESETS, BlobTraitsError, trait_catalog
from services.anime_make import MAKE as ANIME_MAKE, make_character
from services.blob_face import BlobFaceError
from services.blob_face_qwen import QwenFaceError
from services.blob_make import MAKE, PRESETS_OP, BlobRigError, build_body, resolve_request, write_body
from services.mcp_intent import check_intent_id, intent_digest

_ENVELOPE = {"version", "intent_id", "input"}


def command_catalog():
    traits = {"type": "object", "description": "Optional body traits. They override the same fields of a preset. "
              "colors is nested because head is already the shape. The face is not an accessory."}
    return [
        {"name": MAKE, "version": 1, "domain": "model3d", "mutation": True,
         "description": "Build one round-headed person from traits or a preset and rig it on CPU in this call. "
                        "family is blob (the default), anime or chibi. hair.style is none, short, bangs, spiky, long, "
                        "ponytail, twin_tails or bun. Synchronous: the reply is the finished GLB, so model3d.rig.status is not used. "
                        "Omit clips for idle, walk, talk, nod, wave, shrug, point and run. "
                        "A mesh the rig refuses returns not_humanoid and the rig's reason (hands_stuck, single_leg, …). "
                        "No GPU. The face, visemes and set textures are not part of this body.",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "intent_id", "input"],
                          "properties": {"version": {"const": 1, "type": "integer"},
                                         "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                                         "input": {"type": "object", "additionalProperties": False,
                                                   "required": ["workspace", "name"],
                                                   "properties": {
                                                       "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                                                       "name": {"type": "string", "minLength": 1, "maxLength": 64},
                                                       "preset": {"type": "string", "enum": list(PRESETS)},
                                                       "traits": traits,
                                                       "clips": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 32},
                                                   }}}}},
        {"name": ANIME_MAKE, "version": 1, "domain": "model3d", "mutation": True,
         "description": "Make one anime 3D character from traits in one call: a lofted PS2-style body (tapered limbs, egg head with a jaw, "
                        "fingers, outfit as colour regions, hair as curved clumps) rigged on CPU, plus its face as an anime_head Character Kit "
                        "(neutral, happy, sad, angry, surprised, smug, shy, sleepy, suspicious, tired, shout; nine visemes; blink) that "
                        "world3d.scene.face projects onto the head with the kit's own fit and taper. traits: gender (girl|boy|man; a man has a longer, narrower head with a squarer jaw), body (slim|average|tall), "
                        "height (m), skin, eye_color, lash_color, hair_style (none|short|bangs|bob|long|twin_tails|spiky|ponytail|bun), hair_color, "
                        "outfit (school|casual|sport), outfit_colors {top, bottom, shoes, accent}, blush, face_shape (soft|sharp), face_style (anime|cute: the round-eyed mascot face), "
                        "face_source (program, or qwen: a painted bald face given as face_image, a keyed workspace picture from image.remove_background, with the expressions as overlays), "
                        "face {nose, brows, line, ink}, clips. A PS2-era REALISTIC person instead: style real (gender man|woman, body, height, bottom trousers|skirt|shorts, skin, hair_style): "
                        "real proportions, a plain body and head with UVs into a texture atlas, no clothes: the answer gives guide_body_file and guide_head_file (grey pictures of the body and the head tiles in the same layout); paint them with generation.image (image_refs the guide, Qwen) and pass the results as texture (the body picture) and texture_head (the head picture) in a second call to dress the same body, as many times as you like. "
                        "Returns rigged_file, faceAnchor, kit_id, poses, preview, face {fit, taper}, and for style real guide_body_file, guide_head_file, texture_file. Bind the rigged file to a model slot, then "
                        "world3d.scene.face {kit_id, center, radii} and world3d.scene.talk. No GPU.",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "intent_id", "input"],
                          "properties": {"version": {"const": 1, "type": "integer"},
                                         "intent_id": {"type": "string", "minLength": 1, "maxLength": 160},
                                         "input": {"type": "object", "additionalProperties": False, "required": ["workspace", "name"],
                                                   "properties": {"workspace": {"type": "string", "minLength": 1, "maxLength": 120},
                                                                  "name": {"type": "string", "minLength": 1, "maxLength": 64},
                                                                  "traits": {"type": "object", "description": "Character traits (see the description)."},
                                                                  "base_revision": {"type": "integer", "minimum": 0}}}}}},
        {"name": PRESETS_OP, "version": 1, "domain": "model3d", "mutation": False,
         "description": "Limits, defaults and the named presets in the blob, anime and chibi families. Read only.",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version"],
                          "properties": {"version": {"const": 1, "type": "integer"}}}},
    ]


def refusal_detail(error: Exception) -> dict:
    """Structured error for HTTP and MCP. A rig refusal keeps the real reason."""
    if isinstance(error, BlobRigError):
        return {"code": "not_humanoid", "reason": error.reason, "message": str(error), "retryable": False}
    if isinstance(error, BlobTraitsError):
        return {"code": error.code, "message": str(error), "retryable": False}
    if isinstance(error, (BlobFaceError, QwenFaceError)):
        return {"code": error.code, "message": str(error), "retryable": False}
    return {"code": "invalid_command", "message": str(error), "retryable": False}


def command_handlers(workspace_dir, journal):
    def make(arguments):
        payload, intent = _input(arguments)
        traits, clips = resolve_request(payload)
        digest = intent_digest(payload)
        identity = hashlib.sha256(f"{MAKE}:{payload['workspace']}:{intent}".encode()).hexdigest()
        body = build_body(traits, clips)
        stored = journal.reserve(identity, digest)
        if stored is not None:
            return stored
        try:
            result = write_body(Path(workspace_dir(payload["workspace"])), payload["workspace"], payload["name"], intent, body)
        except Exception:
            journal.forget(identity)
            raise
        envelope = {"version": 1, "operation": MAKE, "status": "completed", "result": result}
        journal.finish(identity, envelope)
        return envelope

    def anime(arguments):
        payload, intent = _input(arguments)
        extra = set(payload) - {"workspace", "name", "traits", "base_revision"}
        if extra:
            raise BlobTraitsError("unknown_field", "Unknown field: " + ", ".join(sorted(extra)))
        digest = intent_digest(payload)
        identity = hashlib.sha256(f"{ANIME_MAKE}:{payload['workspace']}:{intent}".encode()).hexdigest()
        stored = journal.reserve(identity, digest)
        if stored is not None:
            return stored
        try:
            result = make_character(Path(workspace_dir(payload["workspace"])), payload["workspace"], payload["name"], intent, payload.get("traits"),
                                    base_revision=payload.get("base_revision"))
        except Exception:
            journal.forget(identity)
            raise
        envelope = {"version": 1, "operation": ANIME_MAKE, "status": "completed", "result": result}
        journal.finish(identity, envelope)
        return envelope

    def presets(arguments):
        if not isinstance(arguments, dict) or arguments.get("version") != 1 or set(arguments) - {"version"}:
            raise ValueError("Use version 1")
        return {"version": 1, "operation": PRESETS_OP, "status": "completed", "result": trait_catalog()}

    async def handle_make(arguments):
        try:
            return await run_in_threadpool(make, arguments)
        except (BlobTraitsError, BlobRigError, ValueError) as error:
            raise HTTPException(422, refusal_detail(error)) from error

    async def handle_anime(arguments):
        try:
            return await run_in_threadpool(anime, arguments)
        except (BlobTraitsError, BlobRigError, BlobFaceError, QwenFaceError, ValueError) as error:
            raise HTTPException(422, refusal_detail(error)) from error

    async def handle_presets(arguments):
        try:
            return await run_in_threadpool(presets, arguments)
        except ValueError as error:
            raise HTTPException(422, refusal_detail(error)) from error

    return {MAKE: handle_make, ANIME_MAKE: handle_anime, PRESETS_OP: handle_presets}


def create_model3d_blob_router(handlers):
    router = APIRouter()

    @router.post("/api/v1/model3d/blob")
    async def blob_make(request: Request):
        return await handlers[MAKE](await request.json())

    @router.post("/api/v1/model3d/anime")
    async def anime_make(request: Request):
        return await handlers[ANIME_MAKE](await request.json())

    @router.post("/api/v1/model3d/blob/presets")
    async def blob_presets(request: Request):
        body = await request.body()
        payload = {} if not body else await request.json()
        return await handlers[PRESETS_OP](payload)

    return router


def _input(arguments):
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1, intent_id and input")
    if set(arguments) - _ENVELOPE:
        raise ValueError("Unknown envelope field")
    payload = arguments.get("input")
    if not isinstance(payload, dict):
        raise ValueError("input must be an object")
    for field, limit in (("workspace", 120), ("name", 64)):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise ValueError(f"{field} must be a nonempty string (max {limit})")
    return payload, check_intent_id(arguments.get("intent_id"))
