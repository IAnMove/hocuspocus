"""What a Series shot's render depends on, kept on its take, so a production renders again only what changed.

``render_inputs`` fingerprints a shot in one language: its layout and lines, the location, the sound design, the
kits of the people seen or heard and, for a shot with lines in a room (``series_voice_rooms``), the room each line is
heard in and the version of the rooms' processing. A series without rooms, or a shot whose lines are all dry, keeps
the digest it had. ``series_native_render`` stores it in the take's metadata (``renderInputs``)
and ``series.episode.produce`` renders only ``stale_shot_ids``. Ambience the episode assembly lays
(``soundDesign.ambienceMode: "episode"``, ``ambienceDuckDb``) and the episode's score (``episode.score``) are not
part of a shot, so changing them renders nothing again. A shot's ``foley`` is, so a new prompt or volume renders
that shot again; a shot without one keeps the digest it had before foley existed. A location's ``layout2d.layers``
(``series_layers``) are seen only by its 2D shots that do not bring their own, so changing them renders just those;
a location without layers keeps the digests it had. Hearing (``series_hearing``) is laid at assembly; a take
depends only on a ``deaf`` one, which drops its lines and sounds, and on the room a ``muffled`` one skips, so a
``ringing`` shot or default renders nothing again. A 2D shot's finish (``series_finish``) counts only when it is not
the paper default, so a series and a shot that never chose one keep their digests.
The series frame (``provider.videoSettings.orientation``) counts only when it is portrait: a landscape series
keeps the digest it had, and turning the series to portrait (or back) is a new picture. A line counts as spoken
(``spoken``) only when its speaker's pronunciation dictionary changes it, as the text sent to the voice, so a
dictionary entry no line uses renders nothing again. A line's ``castIndex`` (which copy of a kit speaks) counts only
when the line names one.
A take saved before an input joined the fingerprint (``renderInputsVersion`` below ``INPUTS_VERSION``) is compared
with the digest of the version it was saved at, so adding an input never marks an existing production out of date.
Mutable 3D scenes and personal templates are read from the workspace, so editing the source invalidates its takes.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from services import series_finish, series_shot3d
from services.series_ambience import shot_sound_design
from services.series_hearing import hearing_of
from services.series_layers import digest_location
from services.series_shot_extras import pauses, timing_args
from services.series_scene_inputs import scene_source_digest
from services.series_shot_plan import FPS, frame_size, kit_ref, plan_timing
from services.series_voice_rooms import VERSION as ROOM_VERSION, line_rooms
from services.speech_text_es import dictionary_map, pronounce

# What a shot's picture and sound depend on, besides the render code itself.
_SHOT_INPUTS = ("productionMethod", "layout2d", "locationId", "locationVariantId", "visibleCharacterIds", "scene3d")
# ``revision`` is the per-kit counter. Pins choose which document is hashed; the
# number itself is not a picture or a voice, so adding it does not stale a take.
_KIT_VOLATILE = ("createdAt", "updatedAt", "provenance", "revision")
# Version 2 hashes the number of frames the planner will render for a silent shot.
# Version 1 stored the raw ``durationSeconds``, which the render then rewrote, so the next pass looked stale.
# Version 3 adds the series frame when it is portrait, the spoken text of the lines a pronunciation dictionary
# rewrites and a line's ``castIndex``. A take saved at version 2 or 1 never recorded them, so it is read as it was
# saved: ``_legacy_inputs`` offers its older digests.
INPUTS_VERSION = 3
_PLANNED_LENGTH_VERSION = 2
# The inputs below are hashed only from this version on; an older take never recorded them.
_EXTRA_INPUTS_VERSION = 3
# A version-1 take asked for a length on this step; the planner moves it by under one frame.
_DURATION_STEP = 0.05


def render_inputs(series: dict[str, Any], shot: dict[str, Any], kits: dict[str, Any], root: str | None = None,
                  version: int = INPUTS_VERSION) -> str:
    """Fingerprint of everything a shot's render depends on: its layout and lines in this language, the location, the
    sound design, its foley and the kits of the people seen or heard. It is kept on the take, so a production renders again only
    the shots whose inputs changed. ``root`` includes mutable 3D source documents in the fingerprint.

    A silent shot's length is the planner's frame count (version 2), not the value the render writes back into
    ``durationSeconds``. Version 1 is that raw value, so a take saved before this change still matches. A portrait
    series frame, the spoken text and a line's ``castIndex`` are part of the digest from version 3 on; versions 1 and 2
    never hashed them."""
    beats = [_beat_row(beat, version) for beat in shot.get("dialogueBeats") or []]
    people = _people(shot, beats)
    characters = {item.get("id"): item for item in series.get("characters") or []}
    kit_ids = {cid: (kit_ref(series, cid) or {}).get("id") for cid in people}
    location = next((item for item in series.get("locations") or [] if item.get("id") == shot.get("locationId")), None)
    payload = {
        "shot": _shot_inputs(shot), "beats": beats,
        "duration": _duration_input(shot, beats, version), "language": series.get("spokenLanguage"),
        "location": digest_location(location, shot),
        "sound": shot_sound_design(series.get("soundDesign")),
        "characters": {cid: (characters.get(cid) or {}).get("layout2d") for cid in people},
        "kits": {kid: {key: value for key, value in (kits.get(kid) or {}).items() if key not in _KIT_VOLATILE}
                 for kid in kit_ids.values() if kid},
        **({"foley": shot["foley"]} if shot.get("foley") else {}),
    }
    payload.update(_extra_inputs(series, shot, root, version))
    return hashlib.sha1(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _beat_row(beat: dict[str, Any], version: int) -> list[Any]:
    """Id, speaker, text, emotion, delivery and, from version 3, ``castIndex`` when the line names a copy.

    ``castIndex`` picks which on-screen copy of a kit moves its mouth (``series_shot_plan._speaker_index``). Only a
    whole number counts (a bool does not, as there), so a line that never named a copy keeps its digest."""
    row = [beat.get("id"), beat.get("characterId"), beat.get("text"), beat.get("emotion"), beat.get("delivery")]
    index = beat.get("castIndex")
    if version >= _EXTRA_INPUTS_VERSION and type(index) is int:
        row.append(index)
    return row


def _shot_inputs(shot: dict[str, Any]) -> dict[str, Any]:
    """The shot's fields its render reads, without ``layout2d.hearing`` (assembly-only but for ``deaf``)."""
    inputs = {key: shot.get(key) for key in _SHOT_INPUTS}
    layout = inputs.get("layout2d")
    if isinstance(layout, dict) and "hearing" in layout:
        inputs["layout2d"] = {key: value for key, value in layout.items() if key != "hearing"}
    return inputs


def _extra_inputs(series: dict, shot: dict, root: str | None, version: int = INPUTS_VERSION) -> dict:
    """Omit absent additions so existing dry, unpaused 2D takes keep their fingerprints."""
    payload = {}
    if version >= _EXTRA_INPUTS_VERSION:
        payload.update(_version_three_inputs(series, shot))
    rooms = line_rooms(series, shot)
    if rooms:
        payload["room"] = {"version": ROOM_VERSION, "lines": rooms}
    if hearing_of(series, shot) == "deaf":
        payload["hearing"] = "deaf"
    timing = pauses(shot.get("dialogueBeats") or [])
    if any(timing):
        payload["pauses"] = timing
    finish = series_finish.fingerprint(series, shot) if shot.get("productionMethod") == "animation_2d" else None
    if finish is not None:
        payload["finish"] = finish
    config = series_shot3d.normalize_scene3d(shot.get("scene3d")) if shot.get("productionMethod") == "animation_3d" else None
    source = scene_source_digest(config, root) if config else None
    if source is not None:
        payload["sceneSource"] = source
    return payload


def _version_three_inputs(series: dict, shot: dict) -> dict:
    """What a take saved at version 2 never recorded: the portrait frame and the lines the dictionary rewrites."""
    payload = {}
    if _portrait(series):
        payload["orientation"] = "portrait"
    spoken = _spoken_lines(series, shot)
    if spoken:
        payload["spoken"] = spoken
    return payload


def _spoken_lines(series: dict[str, Any], shot: dict[str, Any]) -> list[list[Any]]:
    """``[beat id, text sent to the voice]`` for each line its speaker's pronunciation dictionary changes.

    The recording is named by that spoken text (``SeriesNativeRender.line_voice``), so this is what the voice
    receives; a line the dictionary leaves alone adds nothing and an entry no line uses changes nothing."""
    profiles = {item.get("id"): (item.get("voiceProfile") or {}) for item in series.get("characters") or []
                if isinstance(item, dict)}
    spoken = []
    for beat in shot.get("dialogueBeats") or []:
        text = str(beat.get("text") or "").strip() if isinstance(beat, dict) else ""
        profile = profiles.get(beat.get("characterId")) if text else None
        dictionary = dictionary_map(profile.get("pronunciationDictionary")) if isinstance(profile, dict) else None
        said = pronounce(text, dictionary) if dictionary else text
        if said != text:
            spoken.append([beat.get("id"), said])
    return spoken


def _portrait(series: dict[str, Any]) -> bool:
    """The series frame is vertical (``build_shot_spec`` plans 1080x1920 instead of 1920x1080)."""
    width, height = frame_size(series)
    return height > width


def _people(shot: dict[str, Any], beats: list[list[Any]]) -> list[str]:
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    scene3d = shot.get("scene3d") if isinstance(shot.get("scene3d"), dict) else {}
    cast = [entry.get("characterId") for entry in [*(layout.get("cast") or []), *(scene3d.get("cast") or [])] if isinstance(entry, dict)]
    return sorted({*(shot.get("visibleCharacterIds") or []), *(beat[1] for beat in beats), *cast} - {None, ""})


def _snap_duration(seconds: float) -> float:
    """Nearest 0.05 s, so a frame of rounding (about 0.02 s) stays on the length that was asked for."""
    return round(round(float(seconds) / _DURATION_STEP) * _DURATION_STEP, 2)


def _planned_length(shot: dict[str, Any]) -> float | None:
    """The length the planner renders a silent shot at. None for a spoken shot or a length that is not a number."""
    raw = shot.get("durationSeconds")
    if shot.get("dialogueBeats") or isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    return plan_timing([], **timing_args(layout), at_least=float(raw))[1]


def _duration_input(shot: dict[str, Any], beats: list[list[Any]], version: int) -> Any:
    """Silent shots only. Lines already time themselves, so their duration is left out of the fingerprint."""
    if beats:
        return None
    if version < _PLANNED_LENGTH_VERSION:
        return shot.get("durationSeconds")
    planned = _planned_length(shot)
    return shot.get("durationSeconds") if planned is None else round(planned * FPS)


def _legacy_inputs(series: dict[str, Any], shot: dict[str, Any], kits: dict[str, Any], root: str | None) -> list[str]:
    """Digests an older take can carry: the raw length, or the length that was asked before the render wrote the
    planner's length back (the planned one snapped to 0.05 s), both version 1; and the version-2 digest, which has
    the planned frame count and never saw the series frame."""
    found = [render_inputs(series, shot, kits, root, version=1),
             render_inputs(series, shot, kits, root, version=_PLANNED_LENGTH_VERSION)]
    planned = _planned_length(shot)
    if planned is not None:
        found.append(render_inputs(series, {**shot, "durationSeconds": _snap_duration(planned)}, kits, root, version=1))
    return found


def _kept_take(shot: dict[str, Any], assets: dict[str, Any]) -> tuple[Any, Any]:
    attempt = next((item for item in shot.get("attempts") or [] if item.get("id") == shot.get("approvedAttemptId")), None)
    outputs = (attempt or {}).get("outputAssetIds") or []
    meta = (assets.get(outputs[0]) or {}).get("metadata") if outputs else None
    if not isinstance(meta, dict):
        return None, None
    return meta.get("renderInputs"), meta.get("renderInputsVersion")


def _fresh(kept: Any, version: Any, series: dict[str, Any], shot: dict[str, Any], kits: dict[str, Any],
           root: str | None) -> bool:
    """A current-version take matches the current digest. An older take still matches the digest of the version it was
    saved with (version 2 never hashed the series frame; version 1 held the raw length, or the planned length snapped
    to 0.05 s, so the render's write-back of that length does not make it stale)."""
    if not isinstance(kept, str):
        return False
    if kept == render_inputs(series, shot, kits, root):
        return True
    if version == INPUTS_VERSION:
        return False
    return kept in _legacy_inputs(series, shot, kits, root)


def _attempt_inputs(shot: dict[str, Any], assets: dict[str, Any]) -> list[tuple[Any, str, Any]]:
    found = []
    for attempt in shot.get("attempts") or []:
        if not isinstance(attempt, dict):
            continue
        outputs = attempt.get("outputAssetIds") or []
        meta = (assets.get(outputs[0]) or {}).get("metadata") if outputs else None
        if isinstance(meta, dict) and isinstance(meta.get("renderInputs"), str):
            found.append((attempt.get("id"), meta["renderInputs"], meta.get("renderInputsVersion")))
    return found


def accepted_inputs(series: dict[str, Any], shot: dict[str, Any], kits: dict[str, Any], root: str | None = None) -> str:
    """Fingerprint a review compares with a take.

    A take from an older version still carries the digest of that version. The approved take wins: an earlier
    pass can share the new digest by accident while the approved one still has the old one. With no approved take,
    several takes can each be current under the version they were saved at (one from before version 2 and one after,
    nothing changed since): the newest is the one a review looks at, so its digest is returned. A changed shot returns
    the current digest."""
    current = render_inputs(series, shot, kits, root)
    saved = _attempt_inputs(shot, series.get("assets") or {})
    approved = shot.get("approvedAttemptId")
    for attempt_id, kept, version in saved:
        if attempt_id == approved and _fresh(kept, version, series, shot, kits, root):
            return kept
    legacy = [kept for _attempt_id, kept, version in saved if _fresh(kept, version, series, shot, kits, root)]
    return legacy[-1] if legacy else current


def stale_shot_ids(series: dict[str, Any], episode: dict[str, Any], kits: dict[str, Any], root: str | None = None) -> list[str]:
    """Rendered shots of a (localized) episode with no approved take, or one made from other inputs. Takes from before
    the inputs were kept count as out of date. A take saved at an older version stays current while it matches the
    digest of that version."""
    assets = series.get("assets") or {}
    shots = sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0))
    return [shot["id"] for shot in shots if series_shot3d.wants_render(shot)
            and not _fresh(*_kept_take(shot, assets), series, shot, kits, root)]
