"""Serializable catalog for the local Studio music operation."""

from services.studio_music_spec import studio_music_schema


def music_command_catalog():
    """Return the exact closed ``generation.music`` discovery entry."""
    schema = studio_music_schema()
    input_schema = dict(schema["input"])
    definitions = input_schema.pop("$defs", {})
    return {
        "name": "generation.music",
        "version": 2,
        "supportedVersions": [2],
        "domain": "studio",
        "mutation": True,
        "description": (
            "Admit one local music generation with literal lyrics and caption "
            "through the canonical generation queue. The selected ACE-Step or "
            "MiniMax-Music3 model must already be installed; retries reuse the "
            "same intent receipt."
        ),
        "musicModelTypes": list(schema["music_model_types"]),
        "guideRevision": schema["guide_revision"],
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "$defs": definitions,
            "properties": {
                "version": {"type": "integer", "const": 2},
                "operation": {"const": "generation.music"},
                "intent_id": schema["intent_id"],
                "input": input_schema,
            },
            "required": ["version", "operation", "intent_id", "input"],
        },
    }


__all__ = ["music_command_catalog"]
