"""Serializable speech operation projected through the shared HTTP/MCP router."""
from services.studio_speech_spec import studio_speech_schema


def speech_command_catalog():
    schema = studio_speech_schema()
    input_schema = dict(schema["input"])
    definitions = input_schema.pop("$defs", {})
    return {
        "name": "generation.speech", "version": 2, "supportedVersions": [2],
        "domain": "studio", "mutation": True,
        "description": "Admit speech using an installed speech model, literal text, voice settings and canonical audio references in an explicit output workspace. Preserve the original speaker text separately from the effective native prompt. Reuse intent_id only for retries; the receipt proves admission, and its task reports completion.",
        "inputSchema": {
            "type": "object", "additionalProperties": False, "$defs": definitions,
            "properties": {"version": {"type": "integer", "const": 2},
                           "operation": {"const": "generation.speech"},
                           "intent_id": schema["intent_id"], "input": input_schema},
            "required": ["version", "operation", "intent_id", "input"],
        },
    }
