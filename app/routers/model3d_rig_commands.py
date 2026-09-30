"""MCP access to native UniRig/procedural jobs, without a second GPU queue."""
from routers.model3d_commands import command_catalog as model_catalog, command_handlers as model_handlers


def command_catalog() -> list[dict]:
    entries = model_catalog()
    submit, status = entries
    submit.update(name="model3d.rig", description="Rig an existing workspace GLB with native UniRig or procedural rigging. "
                  "Preserves the source and publishes a new GLB. Procedural clips are body-chain approximations; "
                  "UniRig humanoid idle/walk/wobble clips articulate recognizable Y-up limb branches; other clips "
                  "remain approximations. Inspect animation_mode and animation_warnings. Poll model3d.rig.status.")
    payload = submit["inputSchema"]["properties"]["input"]
    workspace = payload["properties"]["workspace"]
    payload.update(properties={"workspace": workspace, "source": {"type": "string", "minLength": 1},
                              "engine": {"enum": ["unirig", "procedural"]},
                              "animations": {"type": "array", "minItems": 1, "items": {"type": "string"}},
                              "rig_profile": {"type": "string"}, "seed": {"type": "integer", "minimum": 0, "maximum": 2147483647},
                              "animation_bpm": {"type": "number", "minimum": 60, "maximum": 180}},
                   required=["workspace", "source"], description="The existing /api/v1/rig/generate request body.")
    status.update(name="model3d.rig.status", description="Read a rig job only in its exact workspace, including its GLB and clip names.")
    return entries


def command_handlers(*, generate, status, journal_path) -> dict:
    return model_handlers(generate=generate, status=status, journal_path=journal_path,
                          operations=("model3d.rig", "model3d.rig.status"))
