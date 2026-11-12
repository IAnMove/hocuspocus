"""Executable generation.video schema shared by local HTTP and external MCP."""

from services.video_generation_spec import video_generation_schema
from services.video_generation_v3 import video_generation_v3_schema


def _without_defs(schema, definitions):
    fragment = dict(schema)
    definitions.update(fragment.pop("$defs", {}))
    return fragment


def video_command_catalog():
    schema = video_generation_schema()
    typed = video_generation_v3_schema()
    definitions = {}
    v2_input = _without_defs(schema["input"], definitions)
    v3_input = _without_defs(typed["input"], definitions)
    return {
        "name": "generation.video",
        "version": 3,
        "supportedVersions": [2, 3],
        "domain": "studio",
        "mutation": True,
        "description": (
            "Version 2 admits one Wan 2.1 Text2Video generation (t2v or t2v_1.3B) "
            "with a literal prompt through the canonical generation queue. "
            "Version 3 types MiniMax H3 FL2VA (image_start required, image_end optional), "
            "Ref2VA reference limits, and wired LTX-2.3 frames with audio mode A. "
            "Pass validate=true on version 3 to build the generate payload without enqueueing. "
            "A real admission still needs the selected model installed. "
            "Reuse intent_id only to recover an existing admission."
        ),
        "videoModelFamily": schema["video_model_family"],
        "videoModelTypes": list(schema["video_model_types"]),
        "typedVideo": {
            "version": 3,
            "families": typed["families"],
            "limits": typed["limits"],
        },
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "$defs": definitions,
            "properties": {
                "version": {"type": "integer", "enum": [2, 3]},
                "operation": {"const": "generation.video"},
                "intent_id": schema["intent_id"],
                "validate": {
                    "type": "boolean",
                    "description": "Version 3 only. Build the generate payload and do not enqueue.",
                },
                "input": {"type": "object"},
            },
            "required": ["version", "operation", "intent_id", "input"],
            "oneOf": [
                {"properties": {"version": {"const": 2}, "input": v2_input}},
                {"properties": {"version": {"const": 3}, "input": v3_input}},
            ],
        },
    }


__all__ = ["video_command_catalog"]
