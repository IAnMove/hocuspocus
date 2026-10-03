"""MCP access to native UniRig/procedural jobs, without a second GPU queue."""
from routers.model3d_commands import command_catalog as model_catalog, command_handlers as model_handlers


def command_catalog() -> list[dict]:
    entries = model_catalog()
    submit, status = entries
    submit.update(name="model3d.rig", description="Rig an existing workspace GLB with UniRig, procedural, or the standard humanoid skeleton. "
                  "Preserves the source and publishes a new GLB. Engine humanoid is CPU-only: it detects the T or A pose, "
                  "names bones like Mixamo, bakes the chosen clips for that body (feet on the floor, arms clear of a big "
                  "belly or head) and fails with not_humanoid plus a reason (hands_stuck, arms_raised, turned, single_leg, "
                  "legs_too_short, asymmetry, not_upright, degenerate) instead of guessing. Procedural clips stay body-chain approximations. "
                  "Poll model3d.rig.status; a finished humanoid job lists clips as {index, name, duration}.")
    payload = submit["inputSchema"]["properties"]["input"]
    workspace = payload["properties"]["workspace"]
    payload.update(properties={"workspace": workspace, "source": {"type": "string", "minLength": 1},
                              "engine": {"enum": ["unirig", "procedural", "humanoid"]},
                              "pose": {"enum": ["auto", "t", "a"], "description": "Ignored hint; the humanoid engine detects the pose."},
                              "animations": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                              "rig_profile": {"type": "string"}, "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
                              "animation_bpm": {"type": "number", "minimum": 60, "maximum": 180}},
                   required=["workspace", "source"], description="The existing /api/v1/rig/generate request body.")
    status.update(name="model3d.rig.status", description="Read a rig job only in its exact workspace, including its GLB and clip names.")
    return entries


def command_handlers(*, generate, status, journal_path) -> dict:
    return model_handlers(generate=generate, status=status, journal_path=journal_path,
                          operations=("model3d.rig", "model3d.rig.status"))
