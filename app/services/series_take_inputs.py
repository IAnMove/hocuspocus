"""What a Series shot's render depends on, kept on its take, so a production renders again only what changed.

``render_inputs`` fingerprints a shot in one language: its layout and lines, the location, the sound design, the
kits of the people seen or heard and, for a shot with lines in a room (``series_voice_rooms``), the room. A series
without rooms keeps the digests it had. ``series_native_render`` stores it in the take's metadata (``renderInputs``)
and ``series.episode.produce`` renders only ``stale_shot_ids``. Ambience the episode assembly lays
(``soundDesign.ambienceMode: "episode"``) is not part of a shot, so changing it renders nothing again.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from services import series_shot3d
from services.series_ambience import shot_sound_design
from services.series_shot_plan import kit_ref
from services.series_voice_rooms import shot_room

# What a shot's picture and sound depend on, besides the render code itself.
_SHOT_INPUTS = ("productionMethod", "layout2d", "locationId", "locationVariantId", "visibleCharacterIds", "scene3d")
_KIT_VOLATILE = ("createdAt", "updatedAt", "provenance")


def render_inputs(series: dict[str, Any], shot: dict[str, Any], kits: dict[str, Any]) -> str:
    """Fingerprint of everything a shot's render depends on: its layout and lines in this language, the location, the
    sound design and the kits of the people seen or heard. It is kept on the take, so a production renders again only
    the shots whose inputs changed (a 3D template edited in place is not seen: render those shots by id)."""
    beats = [[beat.get("id"), beat.get("characterId"), beat.get("text"), beat.get("emotion"), beat.get("delivery")]
             for beat in shot.get("dialogueBeats") or []]
    people = _people(shot, beats)
    characters = {item.get("id"): item for item in series.get("characters") or []}
    kit_ids = {cid: (kit_ref(series, cid) or {}).get("id") for cid in people}
    payload = {
        "shot": {key: shot.get(key) for key in _SHOT_INPUTS}, "beats": beats,
        "duration": None if beats else shot.get("durationSeconds"), "language": series.get("spokenLanguage"),
        "location": next((item for item in series.get("locations") or [] if item.get("id") == shot.get("locationId")), None),
        "sound": shot_sound_design(series.get("soundDesign")),
        "characters": {cid: (characters.get(cid) or {}).get("layout2d") for cid in people},
        "kits": {kid: {key: value for key, value in (kits.get(kid) or {}).items() if key not in _KIT_VOLATILE}
                 for kid in kit_ids.values() if kid},
    }
    room = shot_room(series, shot) if any(str(beat[2] or "").strip() for beat in beats) else None
    if room:
        payload["room"] = room
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _people(shot: dict[str, Any], beats: list[list[Any]]) -> list[str]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    scene3d = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    cast = [entry.get("characterId") for entry in [*(layout.get("cast") or []), *(scene3d.get("cast") or [])] if isinstance(entry, dict)]
    return sorted({*(shot.get("visibleCharacterIds") or []), *(beat[1] for beat in beats), *cast} - {None, ""})


def _kept_inputs(shot: dict[str, Any], assets: dict[str, Any]) -> str | None:
    attempt = next((item for item in shot.get("attempts") or [] if item.get("id") == shot.get("approvedAttemptId")), None)
    outputs = (attempt or {}).get("outputAssetIds") or []
    return ((assets.get(outputs[0]) or {}).get("metadata") or {}).get("renderInputs") if outputs else None


def stale_shot_ids(series: dict[str, Any], episode: dict[str, Any], kits: dict[str, Any]) -> list[str]:
    """Rendered shots of a (localized) episode with no approved take, or one made from other inputs. Takes from before
    the inputs were kept count as out of date."""
    assets = series.get("assets") or {}
    shots = sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0))
    return [shot["id"] for shot in shots if series_shot3d.wants_render(shot)
            and _kept_inputs(shot, assets) != render_inputs(series, shot, kits)]
