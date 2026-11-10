"""HTTP and MCP doors for a realistic (PS2-era) 3D person made on the server. The work lives in services/real_character_job.py.

Each MCP tool and its route call the same handler with the same envelope, so the Studio 3D panel, an agent and the Wizard start
one operation and read one recipe:

* ``model3d.real.make``    ``POST /api/v1/model3d/real``          start (or remake) a character: a job
* ``model3d.real.status``  ``POST /api/v1/model3d/real/status``   follow the job (steps, result, warnings)
* ``model3d.real.cancel``  ``POST /api/v1/model3d/real/cancel``   stop it; what it made is kept for the next make
* ``model3d.real.get``     ``POST /api/v1/model3d/real/get``      the recipe of one character, to reopen and remake it
* ``model3d.real.list``    ``POST /api/v1/model3d/real/list``     the realistic characters of a workspace
* ``model3d.real.presets`` ``POST /api/v1/model3d/real/presets``  the prompt library (outfits, faces)
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from services import workspace_busy
from services.blob_builder import BlobTraitsError
from services.mcp_intent import check_intent_id
from services.real_character_job import RealCharacterJobs, RealJobDeps, RealJobError
from services.real_character_recipe import GENDERS, PROMPT_LIMIT, SEED_MAX, characters, latest, presets

MAKE, STATUS, CANCEL, GET, LIST, PRESETS = (f"model3d.real.{verb}" for verb in ("make", "status", "cancel", "get", "list", "presets"))
_WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
_NAME = {"type": "string", "minLength": 1, "maxLength": 64}
_JOB = {"type": "string", "minLength": 1, "maxLength": 80}
_PROMPT = {"type": ["string", "null"], "maxLength": PROMPT_LIMIT}
_PICTURE = {"type": ["string", "null"], "maxLength": 300}


def _make_input() -> dict:
    return {"type": "object", "additionalProperties": False, "required": ["workspace", "name"], "properties": {
        "workspace": _WORKSPACE, "name": _NAME, "gender": {"enum": list(GENDERS)},
        "skin": {"type": "string", "pattern": "^#[0-9a-fA-F]{6}$"}, "height": {"type": "number", "minimum": 1.2, "maximum": 2.2},
        "body": {"enum": ["slim", "average", "tall"]}, "bottom": {"enum": ["trousers", "skirt", "shorts"]},
        "outfit_prompt": {**_PROMPT, "description": "The clothes (and shoes), in English."},
        "face_prompt": {**_PROMPT, "description": "The face and the hair (age, eyes, beard...), in English."},
        "seed": {"type": "integer", "minimum": 0, "maximum": SEED_MAX},
        "image_model": {"type": "string", "maxLength": 80, "description": "Default qwen_image_21_turbo."},
        "texture": {**_PICTURE, "description": "A body picture of this workspace to use instead of painting one."},
        "texture_head": {**_PICTURE, "description": "A head picture of this workspace to use instead of painting one."},
        "talk_kit": {"type": "boolean", "description": "Make the photo face kit (default true)."},
        "traits": {"type": "object", "description": "More model3d.anime.make traits for style real (hair_style, face_span, face_depth, head_join...)."},
        "base_revision": {"type": "integer", "minimum": 0}}}


def _envelope(input_schema: dict, *, intent: bool = False) -> dict:
    properties = {"version": {"const": 1, "type": "integer"}, "input": input_schema}
    if intent:
        properties["intent_id"] = {"type": "string", "minLength": 1, "maxLength": 160}
    return {"type": "object", "additionalProperties": False, "required": ["version", "input", *(["intent_id"] if intent else [])], "properties": properties}


def _small(required: list[str], **properties: dict) -> dict:
    return {"type": "object", "additionalProperties": False, "required": required, "properties": properties}


def command_catalog() -> list[dict]:
    make = ("Make one REALISTIC PS2-era 3D person on the server from two English prompts, as one job: the mould's guides, Qwen paints "
            "the body guide with outfit_prompt and the head guide with face_prompt (generation.image, image_model default qwen_image_21_turbo, "
            "2048x1024), the textured character rigged on CPU, then the photo face kit that talks (warp mouths, only the mouth moves). "
            "gender man|woman; skin, height, body, bottom (trousers|skirt|shorts); seed (drawn once and stored); texture / texture_head reuse "
            "a workspace picture instead of painting; talk_kit false skips the kit; traits are more model3d.anime.make traits of style real. "
            "Takes minutes (two Qwen pictures). Returns a job: follow it with model3d.real.status. A make of a name already made reuses what "
            "did not change and takes every field you leave out from its stored recipe: pass only outfit_prompt to change the clothes (only the "
            "body is repainted) or only face_prompt to change the face (the head and the face kit are redone). The result has everything "
            "model3d.anime.make returns (rigged_file, faceAnchor, humanoid, relief, guide and face_pose files) plus kit_id (the PHOTO kit), "
            "talk_kit {review, mouthFound, warnings}, recipe and warnings [{code, message}] (picture_not_2_to_1, picture_flat, relief_skipped, "
            "the face kit's mouth_not_found..., talk_kit_failed). In a Video 3D scene: world3d.scene.face {kit_id, shape: mesh, center, radii "
            "from faceAnchor} without skin, and world3d.scene.talk with blink false. The person sees and remakes it in Studio 3D › Realista (PS2).")
    return [
        {"name": MAKE, "version": 1, "domain": "model3d", "mutation": True, "description": make,
         "inputSchema": _envelope(_make_input(), intent=True)},
        {"name": STATUS, "version": 1, "domain": "model3d", "mutation": False,
         "description": "Read a model3d.real.make job: status (queued, running, completed, failed, cancelling, cancelled, interrupted), stage, "
                        "steps (guides, body, head, character, kit: waiting, running, done, reused, given, skipped, failed) and, when completed, result.",
         "inputSchema": _envelope(_small(["workspace", "job_id"], workspace=_WORKSPACE, job_id=_JOB))},
        {"name": CANCEL, "version": 1, "domain": "model3d", "mutation": True,
         "description": "Stop a model3d.real.make job. The pictures already painted are kept: the next make of the same name reuses them.",
         "inputSchema": _envelope(_small(["workspace", "job_id"], workspace=_WORKSPACE, job_id=_JOB))},
        {"name": GET, "version": 1, "domain": "model3d", "mutation": False,
         "description": "The stored recipe of one realistic character (by name): input (the fields to pass to model3d.real.make again, "
                        "changing one), the resolved traits, both prompts, seed, model, the pictures with their keys, the files, kit_id; "
                        "missing true when its rigged GLB was deleted.",
         "inputSchema": _envelope(_small(["workspace", "name"], workspace=_WORKSPACE, name=_NAME))},
        {"name": LIST, "version": 1, "domain": "model3d", "mutation": False,
         "description": "The realistic characters of a workspace (the newest recipe of each name): name, gender, prompts, seed, kit_id, "
                        "rigged_file, the face and body picture URLs, madeAt, missing.",
         "inputSchema": _envelope(_small(["workspace"], workspace=_WORKSPACE))},
        {"name": PRESETS, "version": 1, "domain": "model3d", "mutation": False,
         "description": "Quick picks for model3d.real.make: outfits and faces, each {id, gender any|man|woman, label {es, en}, prompt}. Read only.",
         "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version"], "properties": {"version": {"const": 1, "type": "integer"}}}},
    ]


def refusal_detail(error: Exception) -> tuple[int, dict]:
    if isinstance(error, RealJobError):
        return error.status, {"code": error.code, "message": str(error), "retryable": False}
    if isinstance(error, BlobTraitsError):
        return 422, {"code": error.code, "message": str(error), "retryable": False}
    return 422, {"code": "invalid_command", "message": str(error), "retryable": False}


def _input(arguments, fields: set[str]) -> dict:
    if not isinstance(arguments, dict) or type(arguments.get("version")) is not int or arguments["version"] != 1:
        raise ValueError("Use version 1 and an input object")
    payload = arguments.get("input")
    if not isinstance(payload, dict) or set(arguments) - {"version", "input", "intent_id"}:
        raise ValueError("Use version 1 and an input object")
    missing = sorted(field for field in fields if not isinstance(payload.get(field), str) or not payload[field].strip())
    if missing:
        raise ValueError(", ".join(missing) + " must be a nonempty string")
    return payload


def _reply(operation: str, result: dict, status: str = "completed") -> dict:
    return {"version": 1, "operation": operation, "status": status, "result": result}


def command_handlers(workspace_dir, local_mcp=None, *, jobs: RealCharacterJobs | None = None) -> dict:
    """The six handlers. ``local_mcp`` is a callable that returns the server's ``LocalMcp`` (the job paints through it); a test passes
    its own ``jobs``."""
    jobs = jobs or RealCharacterJobs(RealJobDeps(call=lambda tool, arguments: local_mcp().call(tool, arguments), workspace_dir=workspace_dir))
    # The probe closes over this service: it is the only one that knows which job threads are alive.
    workspace_busy.register("real-character", lambda _workspace, folder: jobs.live_jobs(folder))

    def make(arguments):
        payload = _input(arguments, {"workspace", "name"})
        intent = check_intent_id(arguments.get("intent_id"))
        job = jobs.start(payload["workspace"], {key: value for key, value in payload.items() if key != "workspace"}, intent)
        return _reply(MAKE, job, job["status"])

    def status(arguments):
        payload = _input(arguments, {"workspace", "job_id"})
        job = jobs.status(payload["workspace"], payload["job_id"])
        return _reply(STATUS, job, job["status"])

    def cancel(arguments):
        payload = _input(arguments, {"workspace", "job_id"})
        job = jobs.cancel(payload["workspace"], payload["job_id"])
        return _reply(CANCEL, job, job["status"])

    def get(arguments):
        payload = _input(arguments, {"workspace", "name"})
        folder = Path(workspace_dir(payload["workspace"]))
        recipe = latest(folder, payload["name"])
        if recipe is None:
            raise RealJobError("character_not_found", f"No realistic character called {payload['name']} in this workspace", 404)
        rigged = (recipe.get("files") or {}).get("rigged_file") or ""
        return _reply(GET, {**{key: value for key, value in recipe.items() if key != "made"}, "missing": not (folder / rigged).is_file()})

    def listing(arguments):
        payload = _input(arguments, {"workspace"})
        return _reply(LIST, {"characters": characters(Path(workspace_dir(payload["workspace"])))})

    def library(arguments):
        if not isinstance(arguments, dict) or arguments.get("version") != 1 or set(arguments) - {"version"}:
            raise ValueError("Use version 1")
        return _reply(PRESETS, presets())

    def door(function):
        async def handle(arguments):
            try:
                return await run_in_threadpool(function, arguments)
            except (RealJobError, BlobTraitsError, ValueError) as error:
                code, detail = refusal_detail(error)
                raise HTTPException(code, detail) from error
        return handle

    return {MAKE: door(make), STATUS: door(status), CANCEL: door(cancel), GET: door(get), LIST: door(listing), PRESETS: door(library)}


def create_model3d_real_router(handlers):
    router = APIRouter()

    @router.post("/api/v1/model3d/real")
    async def real_make(request: Request):
        return await handlers[MAKE](await request.json())

    @router.post("/api/v1/model3d/real/status")
    async def real_status(request: Request):
        return await handlers[STATUS](await request.json())

    @router.post("/api/v1/model3d/real/cancel")
    async def real_cancel(request: Request):
        return await handlers[CANCEL](await request.json())

    @router.post("/api/v1/model3d/real/get")
    async def real_get(request: Request):
        return await handlers[GET](await request.json())

    @router.post("/api/v1/model3d/real/list")
    async def real_list(request: Request):
        return await handlers[LIST](await request.json())

    @router.post("/api/v1/model3d/real/presets")
    async def real_presets(request: Request):
        body = await request.body()
        return await handlers[PRESETS]({"version": 1} if not body else await request.json())

    return router
