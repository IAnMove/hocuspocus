"""MCP access to native UniRig/procedural jobs, without a second GPU queue."""
from starlette.concurrency import run_in_threadpool

from services.model3d_commands import command_catalog as model_catalog, command_handlers as model_handlers

LIBRARY_OPERATION = "model3d.meshy.animations"


def _library_schema() -> dict:
    from services.meshy_rig_service import CATEGORIES, LIBRARY_MAX_PAGE
    return {
        "name": LIBRARY_OPERATION, "version": 1, "domain": "model3d", "mutation": False,
        "description": ("Read Meshy's animation library (free; needs the user's Meshy key in Settings). Filter by search text (name or key), "
                        "category and sub_category. Each entry has action_id and key: pass them in model3d.rig animations with engine meshy "
                        "(up to 10; 3 credits each, one clip per animation in the published GLB). Nothing is stored; the list is cached for ten minutes."),
        "inputSchema": {"type": "object", "additionalProperties": False, "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "properties": {
                "search": {"type": "string", "maxLength": 80},
                "category": {"enum": list(CATEGORIES)},
                "sub_category": {"type": "string", "maxLength": 80},
                "limit": {"type": "integer", "minimum": 1, "maximum": LIBRARY_MAX_PAGE},
                "offset": {"type": "integer", "minimum": 0},
            }},
        }, "required": ["version"]},
    }


def command_catalog() -> list[dict]:
    entries = model_catalog()
    submit, status = entries
    submit.update(name="model3d.rig", description="Rig an existing workspace GLB with UniRig, procedural, the standard humanoid skeleton, or Meshy (cloud). "
                  "Preserves the source and publishes a new GLB. Engine humanoid is CPU-only: it detects the T or A pose, "
                  "names bones like Mixamo, bakes the chosen clips for that body (feet on the floor, arms clear of a big "
                  "belly or head) and fails with not_humanoid plus a reason (hands_stuck, arms_raised, turned, single_leg, "
                  "legs_too_short, asymmetry, not_upright, degenerate) instead of guessing. Procedural clips stay body-chain approximations. "
                  "Engine meshy sends the GLB to Meshy (the user's own key and credits: 5 for the rig, 3 per library animation; walking and "
                  "running clips come free as <name>-walking.glb and <name>-running.glb beside it): the model must be textured, upright, "
                  "facing +Z and at most 100 MB; its animations are library entries (action_id or key from model3d.meshy.animations, up to 10), "
                  "published as one GLB with one clip per animation. A pose Meshy cannot read fails with not_humanoid / meshy_pose_estimation_failed. "
                  "Poll model3d.rig.status; a finished humanoid job lists clips as {index, name, duration, loop, contacts} (foot landings); "
                  "loop false marks a hold such as kneel_pray or crouch, which ends in its pose: play it once. "
                  "A finished meshy job lists clips as {index, name, duration, loop: null}, the credits spent and the sibling files.")
    payload = submit["inputSchema"]["properties"]["input"]
    workspace = payload["properties"]["workspace"]
    payload.update(properties={"workspace": workspace, "source": {"type": "string", "minLength": 1},
                              "engine": {"enum": ["unirig", "procedural", "humanoid", "meshy"]},
                              "pose": {"enum": ["auto", "t", "a"], "description": "Ignored hint; the humanoid engine detects the pose."},
                              "animations": {"type": "array", "minItems": 1, "items": {"type": ["string", "integer"]},
                                             "description": "Clip ids for the local engines; for meshy, library action ids or keys (max 10)."},
                              "height_meters": {"type": "number", "exclusiveMinimum": 0, "maximum": 100,
                                                "description": "Engine meshy only: the character's height (default 1.7)."},
                              "rig_profile": {"type": "string"}, "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
                              "animation_bpm": {"type": "number", "minimum": 60, "maximum": 180}},
                   required=["workspace", "source"], description="The existing /api/v1/rig/generate request body.")
    status.update(name="model3d.rig.status", description="Read a rig job only in its exact workspace, including its GLB and clip names.")
    return entries + [_library_schema()]


def _library_route():
    """The REST route function, so the MCP read and GET /api/v1/rig/meshy/animations are one operation."""
    from routers import rig
    return rig.meshy_animation_library


def _library_handler(library=None):
    async def read(arguments: dict) -> dict:
        payload = arguments.get("input") if isinstance(arguments, dict) else None
        if not isinstance(arguments, dict) or arguments.get("version") != 1 or set(arguments) - {"version", "input"} or not isinstance(payload or {}, dict):
            raise ValueError("Use version 1 and an input object")
        payload = payload or {}
        unknown = sorted(set(payload) - {"search", "category", "sub_category", "limit", "offset"})
        if unknown:
            raise ValueError(f"Unknown input: {', '.join(unknown)}")
        route = library or _library_route()
        result = await run_in_threadpool(lambda: route(**payload))
        return {"version": 1, "operation": LIBRARY_OPERATION, "status": "completed", "result": result}
    return read


def command_handlers(*, generate, status, journal_path, library=None) -> dict:
    handlers = model_handlers(generate=generate, status=status, journal_path=journal_path,
                              operations=("model3d.rig", "model3d.rig.status"))
    return {**handlers, LIBRARY_OPERATION: _library_handler(library)}
