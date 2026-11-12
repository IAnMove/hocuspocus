"""Pitch and brightness band for one character voice.

Defaults live in ``app/shared/voice_bands.json``, measured from the lines the
owner flagged and the ones that already sounded right. A kit voice with no
``voiceType``, ``pitchBandHz``, ``maxBrightness`` or ``maxCentroidHz`` is not
gated: the wide ``pitchRange`` warning still only notes, and never retries.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_BANDS = Path(__file__).resolve().parents[1] / "shared" / "voice_bands.json"
_TYPES = ("man", "woman", "child", "robot")
_KEYS = ("voiceType", "pitchBandHz", "maxBrightness", "maxCentroidHz")


def load_bands() -> dict[str, Any]:
    return json.loads(_BANDS.read_text(encoding="utf-8"))


def band_applies(voice: dict | None) -> bool:
    """True only when the kit voice itself asks for a band. ``pitchRange`` does not."""
    return isinstance(voice, dict) and any(key in voice for key in _KEYS)


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def limits_for(voice: dict) -> dict[str, Any]:
    """The band this voice is judged against. Stored fields override the type defaults."""
    data = load_bands()
    kind = voice.get("voiceType")
    limits = dict(data[kind]) if kind in _TYPES and isinstance(data.get(kind), dict) else {}
    if "pitchBandHz" in voice:
        limits["pitchBandHz"] = [float(voice["pitchBandHz"][0]), float(voice["pitchBandHz"][1])]
    if "maxBrightness" in voice:
        limits["maxBrightness"] = float(voice["maxBrightness"])
    if "maxCentroidHz" in voice:
        limits["maxCentroidHz"] = float(voice["maxCentroidHz"])
    if kind == "man":
        limits["womanRegisterHz"] = list(data["womanRegisterHz"])
    return limits


def _pitch_reason(voice: dict, pitch: float | None, limits: dict) -> str | None:
    register = limits.get("womanRegisterHz")
    if voice.get("voiceType") == "man" and pitch is not None and register and register[0] <= pitch <= register[1]:
        return "man_in_woman_band"
    band = limits.get("pitchBandHz")
    if band and pitch is not None and not band[0] <= pitch <= band[1]:
        return "pitch"
    return None


def _tone_reason(voice: dict, bright: float | None, centroid: float | None, limits: dict) -> str | None:
    cap = limits.get("maxBrightness")
    if cap is not None and bright is not None and bright > cap:
        return "brightness"
    # The centroid cap is what separates a bright child. A man or a woman is not judged by it
    # unless that voice stores its own maxCentroidHz.
    centroid_cap = limits.get("maxCentroidHz")
    if centroid_cap is None or centroid is None or centroid <= centroid_cap:
        return None
    if voice.get("voiceType") == "child" or "maxCentroidHz" in voice:
        return "centroid"
    return None


def take_reason(voice: dict | None, notes: dict | None) -> str | None:
    """Why this take is outside the band, or None when it is in band, unmeasured, or ungated.

    A man whose median sits in the woman register is ``man_in_woman_band`` even when a custom
    ``pitchBandHz`` would have allowed that pitch. Missing pitch and brightness are not a failure.
    """
    if not band_applies(voice):
        return None
    notes = notes or {}
    pitch, bright, centroid = _number(notes.get("medianPitchHz")), _number(notes.get("brightness")), _number(notes.get("centroidHz"))
    if pitch is None and bright is None and centroid is None:
        return None
    limits = limits_for(voice)
    return _pitch_reason(voice, pitch, limits) or _tone_reason(voice, bright, centroid, limits)


def _with_band(kit: dict, voice_type: str | None, pitch_band: list | None, max_brightness: float | None,
               max_centroid: float | None, language: str | None) -> dict:
    from services.character_speech_definition import normalize_character_voice

    voice = dict(kit.get("voice") or {})
    by_language = dict(kit.get("voicesByLanguage") or {})
    if language:
        if language not in by_language or not isinstance(by_language[language], dict):
            raise ValueError(f"This character has no {language} voice.")
        voice = dict(by_language[language])
    if not voice:
        raise ValueError("This character has no voice.")
    if voice_type is not None:
        voice["voiceType"] = voice_type
    if pitch_band is not None:
        voice["pitchBandHz"] = pitch_band
    if max_brightness is not None:
        voice["maxBrightness"] = max_brightness
    if max_centroid is not None:
        voice["maxCentroidHz"] = max_centroid
    voice = normalize_character_voice(voice)
    if language:
        return {**kit, "voicesByLanguage": {**by_language, language: voice}}
    return {**kit, "voice": voice}


def set_voice_band(workspace_dir: str, kit_id: str, *, voice_type: str | None = None, pitch_band: list | None = None,
                   max_brightness: float | None = None, max_centroid: float | None = None, language: str | None = None,
                   base_revision: int | None = None) -> dict[str, Any]:
    """Store a band on one kit voice. The same function the voice-band route calls."""
    if voice_type is None and pitch_band is None and max_brightness is None and max_centroid is None:
        raise ValueError("Say a voiceType, a pitchBandHz, a maxBrightness or a maxCentroidHz.")
    from services.character_kit_library import patch_character_kit, read_character_kit_library

    library = read_character_kit_library(workspace_dir)
    kit = (library.get("kits") or {}).get(kit_id)
    if not isinstance(kit, dict):
        raise ValueError(f"No character kit {kit_id}.")
    updated = _with_band(kit, voice_type, pitch_band, max_brightness, max_centroid, language)
    revision = int(library.get("revision") or 0) if base_revision is None else int(base_revision)
    return patch_character_kit(workspace_dir, kit_id, updated, base_revision=revision, make_active=False)
