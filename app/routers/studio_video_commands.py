"""Executable generation.video schema shared by local HTTP and external MCP."""

from services.video_generation_spec import video_generation_schema


def video_command_catalog():
    schema = video_generation_schema()
    input_schema = dict(schema["input"])
    definitions = input_schema.pop("$defs", {})
    return {
        "name": "generation.video",
        "version": 2,
        "supportedVersions": [2],
        "domain": "studio",
        "mutation": True,
        "description": (
            "Admit one Wan 2.1 Text2Video generation with a literal prompt through "
            "the canonical generation queue. The selected t2v or t2v_1.3B model must "
            "already be installed. Preserve the original prompt and reuse intent_id "
            "only to recover an existing admission; follow its task for completion."
        ),
        "videoModelFamily": schema["video_model_family"],
        "videoModelTypes": list(schema["video_model_types"]),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "$defs": definitions,
            "properties": {
                "version": {"type": "integer", "const": 2},
                "operation": {"const": "generation.video"},
                "intent_id": schema["intent_id"],
                "input": input_schema,
            },
            "required": ["version", "operation", "intent_id", "input"],
        },
    }


__all__ = ["video_command_catalog"]
