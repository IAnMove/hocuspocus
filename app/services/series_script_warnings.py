"""Script warnings that do not block, plus the voice and castIndex errors that do.

``from_script`` returns ``warnings`` in the same grouped shape as a script error:
``code``, ``subject``, ``shots`` and ``message``. A speaker who is not in the
shot is ``speaker_not_on_screen``. A place used by several scenes, or a shot
location that is not its scene's, is ``location_differs_from_scene``. A 3D
template whose backdrop is another location's image is
``template_backdrop_other_location``. The shot checks group theirs the same way
(``group_warning``): a document too long to read is ``document_text_too_long``
by its title, and video shots past ``videoBudget.maxShots`` are ``video_budget``.
None of them stops ``check``. A line in the episode language whose kit has no voice
(``voicesByLanguage`` or ``kit.voice``) is an error, because the render would
fail; a video or generated shot is not voiced, so it is not checked. ``castIndex`` must point at the shot's cast.
"""
from __future__ import annotations

from typing import Any

from services.series_shot_plan import language_key, voice_for
from services.series_video_foley import VIDEO_METHODS

_LISTED = 2


def finish_check(episode: Any) -> None:
    """Store grouped warnings after those the shot checks already noted (a document too long), then raise when the
    check found errors."""
    episode.warnings = [*(getattr(episode, "warnings", None) or []), *script_warnings(episode)]
    _missing_voices(episode)
    _cast_indexes(episode)
    if episode.checker.problems:
        from services.series_script import ScriptError
        error = ScriptError(episode.checker.problems)
        error.warnings = episode.warnings
        raise error


def script_warnings(episode: Any) -> list[dict[str, Any]]:
    """Grouped warnings for one checked script. Order is first appearance."""
    from services.series_plate_checks import backdrop_warnings
    return [*_speaker_warnings(episode), *_location_warnings(episode), *backdrop_warnings(episode)]


def _cast_ids(shot: dict[str, Any]) -> list[str]:
    from services.series_script import _cast_entry
    found = []
    for raw in shot.get("cast") or []:
        entry = _cast_entry(raw)
        cid = str(entry.get("characterId") or "")
        if cid:
            found.append(cid)
    return found


def _screen_ids(shot: dict[str, Any]) -> list[str]:
    """Who is on screen: the 2D cast, plus a 3D shot's own cast."""
    found = _cast_ids(shot)
    scene3d = shot.get("scene3d")
    if not isinstance(scene3d, dict):
        return found
    for raw in scene3d.get("cast") or []:
        cid = str(raw.get("characterId") or "") if isinstance(raw, dict) else raw if isinstance(raw, str) else ""
        if cid and cid not in found:
            found.append(cid)
    return found


def _kit_id(episode: Any, character_id: str) -> str:
    character = episode.checker.characters.get(character_id) or {}
    ref = (character.get("voiceProfile") or {}).get("characterKitRef") or {}
    return str(ref.get("id") or "")


def _suggestion(who: str, cast: list[str], episode: Any) -> str:
    """A cast member of the same character: an id prefixed by ``who``, or a kit of that base."""
    prefixed = [cid for cid in cast if cid.startswith(f"{who}-")]
    if prefixed:
        return prefixed[0]
    base = _kit_id(episode, who)
    if not base:
        return ""
    for cid in cast:
        other = _kit_id(episode, cid)
        if other and (other.startswith(f"{base}-") or base.startswith(f"{other}-")):
            return cid
    return ""


def _speaker_warnings(episode: Any) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    order: list[tuple[str, str]] = []
    for index, shot in enumerate(episode.script.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        cast = _screen_ids(shot)
        shot_id = episode.shot_id(index)
        for line in shot.get("lines") or []:
            who = str(line.get("who") or "") if isinstance(line, dict) else ""
            if not who or who in cast or who not in episode.checker.characters:
                continue
            hint = _suggestion(who, cast, episode)
            key = (who, hint)
            bucket = buckets.get(key)
            if bucket is None:
                bucket = {"who": who, "hint": hint, "shots": []}
                buckets[key] = bucket
                order.append(key)
            if shot_id not in bucket["shots"]:
                bucket["shots"].append(shot_id)
    return [_speaker_group(buckets[key]) for key in order]


def _speaker_group(bucket: dict[str, Any]) -> dict[str, Any]:
    who, hint, shots = bucket["who"], bucket["hint"], bucket["shots"]
    if hint:
        text = f"{who}: did you mean {hint}? The line is voice-over and the cutout won't move its mouth"
    else:
        text = f"{who}: not on screen"
    return {"code": "speaker_not_on_screen", "subject": who, "shots": shots,
            "message": f"{text} {listed_shots(shots)}"}


def _variant(scene_id: str, place: str) -> bool:
    return place == scene_id or place.startswith(scene_id) or scene_id.startswith(place)


def _location_rows(episode: Any) -> list[tuple[str, str, str, str | None]]:
    """(scene, place, shot id, the scene's own place when the shot moved elsewhere) for each placed shot."""
    rows: list[tuple[str, str, str, str | None]] = []
    for index, shot in enumerate(episode.script.get("shots") or []):
        scene = episode.scenes.get(str(shot.get("scene"))) if isinstance(shot, dict) else None
        if not isinstance(scene, dict):
            continue
        scene_place = str(scene.get("location") or "")
        own_place = str(shot["location"]) if shot.get("location") not in (None, "") else ""
        place = own_place or scene_place
        if place:
            # None: the shot inherits the scene. A shot location equal to the scene is the same.
            rows.append((str(shot.get("scene")), place, episode.shot_id(index),
                         scene_place if own_place and own_place != scene_place else None))
    return rows


def _location_warnings(episode: Any) -> list[dict[str, Any]]:
    rows = _location_rows(episode)
    # The scenes shown in their own location. A shot that moves elsewhere warns on its own and shares nothing.
    users: dict[str, dict[str, None]] = {}
    for scene_id, place, _shot, instead in rows:
        if instead is None:
            users.setdefault(place, {})[scene_id] = None
    grouped: dict[tuple[str, str, str | None], list[str]] = {}
    for scene_id, place, shot_id, instead in rows:
        shared = len(users.get(place, ())) > 1 and not _variant(scene_id, place)
        if instead is not None or shared:
            grouped.setdefault((scene_id, place, instead), []).append(shot_id)
    return [_location_group(key, shots, [other for other in users.get(key[1], {}) if other != key[0]])
            for key, shots in grouped.items()]


def _location_group(key: tuple[str, str, str | None], shots: list[str], others: list[str]) -> dict[str, Any]:
    """A shot moved to another place than its scene's, or a scene whose place other scenes show too."""
    scene_id, place, explicit = key
    if explicit:
        count = f"{len(shots)} shot uses" if len(shots) == 1 else f"{len(shots)} shots use"
        text = f"{scene_id}: {count} {place} instead of {explicit}"
    else:
        text = f"{scene_id}: {place} is also the location of {', '.join(others)}"
    return {"code": "location_differs_from_scene", "subject": scene_id, "shots": shots, "message": f"{text} {listed_shots(shots)}"}


def listed_shots(shots: list[str]) -> str:
    if len(shots) <= 6:
        listed = ", ".join(shots)
    else:
        listed = f"{', '.join(shots[:_LISTED])} … {len(shots)} shots"
    return f"(shots {listed})"


def group_warning(warnings: list[dict[str, Any]], code: str, subject: str, shot_id: str, text: str) -> None:
    """Add a shot to the warning with this code and subject, or start that warning, in the grouped shape."""
    found = next((item for item in warnings if item.get("code") == code and item.get("subject") == subject), None)
    if found is None:
        found = {"code": code, "subject": subject, "shots": []}
        warnings.append(found)
    if shot_id not in found["shots"]:
        found["shots"].append(shot_id)
    found["message"] = f"{subject}: {text} {listed_shots(found['shots'])}"


def _missing_voices(episode: Any) -> None:
    """A video or generated take carries its lines in the clip: the render voices none of them (``_drawn``)."""
    from services.series_script import METHODS, _line_text
    language = language_key(episode.series)
    problems = episode.checker.problems
    for index, shot in enumerate(episode.script.get("shots") or []):
        if not isinstance(shot, dict) or METHODS.get(shot.get("kind")) in VIDEO_METHODS:
            continue
        where = f"shot {index} ({episode.shot_id(index)})"
        for who in _voiceless_speakers(episode, shot, language, _line_text):
            problem = f"{where}: {who} has no {language} voice"
            if problem not in problems:
                problems.append(problem)


def _voiceless_speakers(episode: Any, shot: dict, language: str, line_text: Any) -> list[str]:
    """Speakers of this shot's lines whose kit has no voice in the episode language."""
    found = []
    for line in shot.get("lines") or []:
        who = str(line.get("who") or "") if isinstance(line, dict) else ""
        if not who or who not in episode.checker.characters or not line_text(line, language):
            continue
        kit_id = _kit_id(episode, who)
        kit = episode.checker.kits.get(kit_id) if kit_id else None
        if kit and not voice_for(kit, language):
            found.append(who)
    return found


def _cast_indexes(episode: Any) -> None:
    problems = episode.checker.problems
    for index, shot in enumerate(episode.script.get("shots") or []):
        if not isinstance(shot, dict):
            continue
        cast = _cast_ids(shot)
        where = f"shot {index} ({episode.shot_id(index)})"
        for line_index, line in enumerate(shot.get("lines") or []):
            if not isinstance(line, dict) or "castIndex" not in line:
                continue
            value = line.get("castIndex")
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value < len(cast):
                problems.append(f"{where}: line {line_index} castIndex is not in the cast")
