"""MCP tool that stores a character voice's pitch band (``characters.voice.band``).

A thin projection of ``POST /api/v1/character-kits/library/kits/{kit_id}/voice-band``.
The Wizard's ``set_voice_band`` posts the same body. Merged into ``series_commands``
through ``OPERATIONS`` and ``RUNNERS``, like the card and animation tools.
"""
from __future__ import annotations

from typing import Any, Callable
from urllib.parse import quote

_ID = {"type": "string", "minLength": 1, "maxLength": 160}
_WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
_HZ = {"type": "number", "minimum": 40, "maximum": 600}

OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "characters.voice.band": (
        {"workspace": _WORKSPACE, "character_id": _ID,
         "voiceType": {"enum": ["man", "woman", "child", "robot"]},
         "pitchBandHz": {"type": "array", "minItems": 2, "maxItems": 2, "items": _HZ},
         "maxBrightness": {"type": "number", "minimum": 0, "maximum": 1},
         "maxCentroidHz": {"type": "number", "minimum": 40, "maximum": 8000},
         "language": {"type": "string", "maxLength": 40},
         "baseRevision": {"type": "integer", "minimum": 0}},
        ["workspace", "character_id"], True,
        "Set the pitch and brightness band of one saved character's voice (voiceType man, woman, child or robot, "
        "or an explicit pitchBandHz [low, high], maxBrightness 0–1, maxCentroidHz). The server render retries a "
        "take outside that band up to 3 seeds and, if none lands inside, keeps the best take and warns "
        "voice_out_of_band. A man whose median pitch sits in the woman register is always retried. A voice with "
        "none of these fields is recorded exactly as before (pitch_out_of_range still only warns). language "
        "picks voicesByLanguage; omit it for the kit's default voice. Returns the saved kit library.",
    ),
}


def _band(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {"workspace": data["workspace"]}
    for key in ("voiceType", "pitchBandHz", "maxBrightness", "maxCentroidHz", "language", "baseRevision"):
        if key in data:
            body[key] = data[key]
    kit_id = quote(str(data["character_id"]), safe="")
    return request("POST", f"/api/v1/character-kits/library/kits/{kit_id}/voice-band", body=body)


RUNNERS: dict[str, Callable[..., Any]] = {"characters.voice.band": _band}
