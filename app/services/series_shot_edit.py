"""Edit one shot of an episode by instruction (``series.shot.update``): "edit the fifth shot and put X on it".

An agent or the Wizard names the shot by its id (``e1s04``) or by its number in
the episode (the ``#5`` Series Lab shows, ``shot.order``) and sends only what
changes, in the script vocabulary of ``series.episode.from_script``:
``changes`` replaces those keys (``null`` removes one) and ``append`` adds to a
list (``fx``, ``sfx``, ``props``, ``layers``, ``cast``, ``lines``) without
knowing what is there. The shot is checked like a script shot (characters,
poses, files, effects, 3D objects), and only the fields that changed are
written: the rest of the shot, its takes and the other shots stay as they are.
A change of what the shot shows clears plan, preview and take approval.
``approvalReset`` is true when any of those was set, and ``reset`` lists them
in that order (``plan``, ``preview``, ``take``). A note is not this edit: it
never clears an approval. Changing only the volume of an sfx does not clear
approval; changing its file, its timing or adding a cue does. A generated or
imported take also keeps its approval when only the sound laid at the cut
changed (``sfx``, ``music``, ``clipAudio``, ``clipVolume``, ``clipFit``,
``foley``). Lines in other languages update that language version's text.
"""
from __future__ import annotations

import copy
from typing import Any

from services.series_script import CODES, METHODS, EpisodeScript, ScriptError, _cast_entry
from services.series_shot_plan import language_key
from services.series_video_foley import VIDEO_METHODS

SCRIPT_KEYS = ("scene", "location", "variant", "framing", "camera", "cast", "lines", "card", "music", "sfx", "fx",
               "props", "timing", "voiceRoom", "layers", "castDepth", "clipAudio", "clipVolume", "clipFit", "kind",
               "scene3d", "foley", "duration", "lookRoom", "transitionIn")
LIST_KEYS = ("cast", "lines", "sfx", "fx", "props", "layers")
LAYOUT_KEYS = ("framing", "camera", "cast", "card", "music", "sfx", "fx", "props", "timing", "voiceRoom", "layers",
               "castDepth", "clipAudio", "clipVolume", "clipFit", "lookRoom")
# What a generated or imported take gets at the cut: changing only these keeps its approval.
CUT_KEYS = frozenset({"sfx", "music", "clipAudio", "clipVolume", "clipFit", "foley"})
KIND_OF = {method: kind for kind, method in METHODS.items()}


class ShotEditError(ValueError):
    def __init__(self, message: str, *, problems: list[str] | None = None, status: int = 400, code: str = "invalid_shot_edit"):
        super().__init__(message)
        self.problems, self.status, self.code = problems or [message], status, code


def ordered_shots(episode: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted((shot for shot in episode.get("shots") or [] if isinstance(shot, dict)),
                  key=lambda shot: (int(shot.get("order") or 0), str(shot.get("id") or "")))


def find_shot(episode: dict[str, Any], ref: Any) -> tuple[dict[str, Any], int]:
    """A shot by id, or by its number in the episode (``order``, else its position); and that number."""
    shots = ordered_shots(episode)
    if isinstance(ref, str) and not ref.strip().lstrip("#").isdigit():
        for index, shot in enumerate(shots):
            if shot.get("id") == ref.strip():
                return shot, int(shot.get("order") or index + 1)
        raise ShotEditError(f"The episode has no shot {ref}", status=404, code="shot_not_found")
    try:
        number = int(str(ref).strip().lstrip("#")) if not isinstance(ref, bool) else 0
    except (TypeError, ValueError):
        number = 0
    by_order = [shot for shot in shots if int(shot.get("order") or 0) == number]
    if len(by_order) == 1:
        return by_order[0], number
    if 1 <= number <= len(shots):
        return shots[number - 1], number
    raise ShotEditError(f"The episode has {len(shots)} shots; there is no shot number {ref}", status=404, code="shot_not_found")


def _prefix(episode: dict[str, Any]) -> str:
    return f"e{int(episode.get('number') or 1)}_"


def _scene_key(episode: dict[str, Any], scene_id: Any) -> str:
    text, prefix = str(scene_id or ""), _prefix(episode)
    return text[len(prefix):] if text.startswith(prefix) else text


def _scenes(episode: dict[str, Any], shot: dict[str, Any], wanted: set[str]) -> list[dict[str, Any]]:
    """The episode's scenes the edit names (the shot's own and the one it moves to), as script scenes."""
    scenes = [{"id": _scene_key(episode, item.get("id")), "location": item.get("locationId"), "purpose": item.get("purpose", "")}
              for item in episode.get("script") or [] if isinstance(item, dict) and item.get("id")]
    key = _scene_key(episode, shot.get("sceneId"))
    if key and key not in {item["id"] for item in scenes}:
        scenes.append({"id": key, "location": shot.get("locationId")})
    return [scene for scene in scenes if scene["id"] in wanted]


def _versions(episode: dict[str, Any]) -> dict[str, dict[str, Any]]:
    found = episode.get("languageVersions")
    return {key: value for key, value in found.items() if isinstance(value, dict)} if isinstance(found, dict) else {}


def _line(beat: dict[str, Any], original: str, versions: dict[str, dict[str, Any]]) -> dict[str, Any]:
    line = {"who": beat.get("characterId"), original: beat.get("text") or ""}
    for language, version in versions.items():
        text = (version.get("dialogue") or {}).get(beat.get("id"))
        if text:
            line[language] = text
    for key in ("pauseBefore", "voiceRoom", "emotion", "delivery"):
        if beat.get(key) not in (None, ""):
            line[key] = beat[key]
    return line


def _card(layout: dict[str, Any], shot_id: str, original: str, versions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    card = layout.get("card") if isinstance(layout.get("card"), dict) else None
    if not card:
        return None
    found = {"kind": card.get("kind"), original: [card.get("title") or "", card.get("body") or ""]}
    for language, version in versions.items():
        own = (version.get("cards") or {}).get(shot_id)
        if isinstance(own, dict):
            found[language] = [own.get("title") or "", own.get("body") or ""]
    return found


def _music(layout: dict[str, Any], shot_id: str, versions: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    music = layout.get("music") if isinstance(layout.get("music"), dict) else None
    if not music:
        return None
    found = {"file": music.get("file"), "volume": music.get("volume", 0.6), "start": music.get("start", 0)}
    for language, version in versions.items():
        own = (version.get("music") or {}).get(shot_id)
        if own:
            found[CODES.get(language, language)] = own
    return found


def _script_lines(shot: dict[str, Any], original: str, versions: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    return [_line(beat, original, versions) for beat in shot.get("dialogueBeats") or []
            if isinstance(beat, dict) and str(beat.get("text") or "").strip()]


def to_script(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    """The stored shot in the script vocabulary of ``series.episode.from_script``."""
    original, versions = language_key(series), _versions(episode)
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    script: dict[str, Any] = {"scene": _scene_key(episode, shot.get("sceneId")), "location": shot.get("locationId")}
    if shot.get("locationVariantId"):
        script["variant"] = shot["locationVariantId"]
    for key in LAYOUT_KEYS:
        if key not in ("card", "music") and layout.get(key) is not None:
            script[key] = copy.deepcopy(layout[key])
    lines = _script_lines(shot, original, versions)
    if lines:
        script["lines"] = lines
    optional = {"card": _card(layout, shot["id"], original, versions), "music": _music(layout, shot["id"], versions),
                "kind": KIND_OF.get(shot.get("productionMethod")), "scene3d": copy.deepcopy(shot.get("scene3d")),
                "foley": copy.deepcopy(shot.get("foley")), "duration": None if lines else shot.get("durationSeconds")}
    script.update({key: value for key, value in optional.items() if value is not None})
    if shot.get("transitionIn"):
        script["transitionIn"] = copy.deepcopy(shot["transitionIn"])
    return script


def _check_keys(changes: dict[str, Any], append: dict[str, Any]) -> None:
    unknown = sorted((set(changes) - set(SCRIPT_KEYS)) | (set(append) - set(LIST_KEYS)))
    if unknown:
        raise ShotEditError(f"Unknown shot keys: {', '.join(unknown)} (changes: {', '.join(SCRIPT_KEYS)}; "
                            f"append: {', '.join(LIST_KEYS)})")
    if not changes and not append:
        raise ShotEditError("Send changes or append")


def merge_changes(current: dict[str, Any], changes: dict[str, Any] | None, append: dict[str, Any] | None) -> tuple[dict[str, Any], list[str]]:
    """``changes`` replaces keys (null removes one), ``append`` adds items to list keys; returns the shot and what changed."""
    changes, append = changes or {}, append or {}
    _check_keys(changes, append)
    merged = copy.deepcopy(current)
    for key, value in changes.items():
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = copy.deepcopy(value)
    for key, items in append.items():
        if not isinstance(items, list):
            raise ShotEditError(f"append.{key} must be a list")
        merged[key] = [*(merged.get(key) or []), *copy.deepcopy(items)]
    if "lines" in merged and not merged["lines"]:
        merged.pop("lines")
    changed = [key for key in SCRIPT_KEYS if merged.get(key) != current.get(key)]
    return merged, changed


class _OneShot(EpisodeScript):
    """The episode script machinery for one stored shot: its own id, its episode's number and scenes."""

    def __init__(self, series, episode, shot, merged, kits, files, root):
        self.stored_id = shot["id"]
        wanted = {_scene_key(episode, shot.get("sceneId")), str(merged.get("scene") or "")}
        script = {"scenes": _scenes(episode, shot, wanted), "shots": [merged]}
        super().__init__(series, script, int(episode.get("number") or 1), kits, files, root)
        # Every language version of the episode, not only the languages this shot's lines are written in.
        self.languages = [self.original, *sorted(set(_versions(episode)) - {self.original})]

    def shot_id(self, index: int) -> str:
        return self.stored_id


def _layout_patch(shot: dict[str, Any], built: dict[str, Any], changed: list[str]) -> dict[str, Any]:
    """The stored layout2d with only the changed keys taken from the built shot (a key it no longer has is removed)."""
    layout = copy.deepcopy(shot.get("layout2d")) if isinstance(shot.get("layout2d"), dict) else {}
    for key in (key for key in LAYOUT_KEYS if key in changed):
        if key in built["layout2d"]:
            layout[key] = built["layout2d"][key]
        else:
            layout.pop(key, None)
    patch: dict[str, Any] = {"layout2d": layout} if set(changed) & set(LAYOUT_KEYS) else {}
    patch.update({key: layout[key] for key in ("framing", "camera") if key in changed and key in layout})
    return patch


def build_patch(series: dict[str, Any], episode: dict[str, Any], shot: dict[str, Any], merged: dict[str, Any], changed: list[str],
                kits: dict[str, Any], files: set[str], root: str | None) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    """Check the merged shot like a script shot; return the stored-shot patch (only what changed) and each language
    version's new texts for this shot."""
    one = _OneShot(series, episode, shot, merged, kits, files, root)
    languages = one.languages
    # A version's missing voice is checked when the lines change, not when an effect is added to the shot.
    one.languages = languages if "lines" in changed else languages[:1]
    try:
        one.check()
    except ScriptError as error:
        raise ShotEditError(str(error), problems=error.problems) from error
    one.languages = languages
    built = one.shots()[0]
    patch: dict[str, Any] = {"id": shot["id"], **_layout_patch(shot, built, changed)}
    if "cast" in changed:
        patch["visibleCharacterIds"] = [_cast_entry(raw)["characterId"] for raw in merged.get("cast") or []]
    if "lines" in changed:
        patch.update(dialogueBeats=built["dialogueBeats"], speakingCharacterIds=built["speakingCharacterIds"])
    if set(changed) & {"scene", "location", "variant"}:
        # A hand-made scene id without the episode prefix stays as it is while the shot stays in that scene.
        same_scene = merged.get("scene") == _scene_key(episode, shot.get("sceneId"))
        patch.update(sceneId=shot.get("sceneId") if same_scene else built["sceneId"], locationId=built["locationId"])
        patch["locationVariantId"] = built.get("locationVariantId")
    for key, field in (("kind", "productionMethod"), ("scene3d", "scene3d"), ("foley", "foley")):
        if key in changed:
            patch[field] = built.get(field)
    if "transitionIn" in changed:
        patch["transitionIn"] = built.get("transitionIn")
    # A shot with lines takes its take's length; one without says it (duration, 5 s when it has none).
    if set(changed) & {"duration", "lines"} and "durationSeconds" in built:
        patch["durationSeconds"] = built["durationSeconds"]
    versions = {language: one.version(language) for language in one.languages[1:]} if set(changed) & {"lines", "card", "music"} else {}
    return patch, versions


def take_still_fits(shot: dict[str, Any], changed: list[str]) -> bool:
    """A generated or imported take gets its sound at the cut: changing only that keeps its approval.

    ``transitionIn`` is applied at the join, so it keeps the take on every production method."""
    if not changed:
        return shot.get("productionMethod") in VIDEO_METHODS
    if set(changed) <= {"transitionIn"}:
        return True
    if shot.get("productionMethod") in VIDEO_METHODS and set(changed) <= CUT_KEYS | {"transitionIn"}:
        return True
    return False


def _spoken_beats(episode: dict[str, Any], shot_id: str) -> list[str]:
    shot = next(item for item in episode.get("shots") or [] if item.get("id") == shot_id)
    return [beat["id"] for beat in shot.get("dialogueBeats") or [] if str(beat.get("text") or "").strip()]


def _version_dialogue(version: dict[str, Any], old_beats: list[str], new: dict[str, str], beats: list[str]) -> list[str]:
    """The version's lines of this shot replaced by the new ones; returns the beats it still lacks."""
    dialogue = {key: value for key, value in (version.get("dialogue") or {}).items() if key not in old_beats}
    dialogue.update(new)
    version["dialogue"] = dialogue
    return [beat for beat in beats if beat not in dialogue]


def _version_shot_map(version: dict[str, Any], key: str, shot_id: str, new: dict[str, Any]) -> None:
    """A version's per-shot ``cards`` or ``music`` entry for this shot replaced by the new one (or removed)."""
    own = dict(version.get(key) or {})
    own.pop(shot_id, None)
    own.update(new)
    version[key] = own


def _write_versions(episode: dict[str, Any], shot_id: str, old_beats: list[str], texts: dict[str, dict[str, Any]],
                    changed: list[str]) -> dict[str, list[str]]:
    missing: dict[str, list[str]] = {}
    beats = _spoken_beats(episode, shot_id)
    maps = [key for key, field in (("cards", "card"), ("music", "music")) if field in changed]
    for language, version in _versions(episode).items():
        new = texts.get(language) or {}
        if "lines" in changed:
            missing[language] = _version_dialogue(version, old_beats, new.get("dialogue") or {}, beats)
        for key in maps:
            _version_shot_map(version, key, shot_id, new.get(key) or {})
    return missing


def _approved_stages(episode: dict[str, Any], shot_id: str, before: str, after: str) -> list[str]:
    """Plan and preview approvals this edit drops. ``changes`` is not an approval, and a same digest keeps both."""
    if before == after:
        return []
    review = episode.get("review") if isinstance(episode.get("review"), dict) else {}
    shots = review.get("shots") if isinstance(review.get("shots"), dict) else {}
    entry = shots.get(shot_id) if isinstance(shots.get(shot_id), dict) else {}
    return [stage for stage in ("plan", "preview") if entry.get(stage) == "approved"]


def _approval_report(episode: dict[str, Any], shot_id: str, stored: dict[str, Any], changed: list[str],
                     keep_approval: bool) -> dict[str, Any]:
    """What this edit cleared. Volume-only sfx keeps the take; other digest-stable edits (foley) still drop it."""
    from services.series_review import content_digest
    shot = next(item for item in episode.get("shots") or [] if item.get("id") == shot_id)
    before, after = content_digest(stored), content_digest(shot)
    cleared = _approved_stages(episode, shot_id, before, after)
    volume_only = set(changed) <= {"sfx"} and before == after
    if not keep_approval and not volume_only and reset_approvals(episode, shot_id):
        cleared.append("take")
    return {"approvalReset": bool(cleared), "reset": cleared}


def reset_approvals(episode: dict[str, Any], shot_id: str) -> bool:
    """The shot's approved take and every language version's approval of it are cleared; True when one was set."""
    shot = next(item for item in episode.get("shots") or [] if item.get("id") == shot_id)
    had = bool(shot.pop("approvedAttemptId", None))
    for version in _versions(episode).values():
        approved = version.get("approvedAttemptIds")
        if isinstance(approved, dict) and approved.pop(shot_id, None):
            had = True
    return had


def apply_edit(series: dict[str, Any], episode_id: str, shot_id: str, patch: dict[str, Any], texts: dict[str, dict[str, Any]],
               changed: list[str], keep_approval: bool, *, updated_at: str | None = None) -> tuple[dict[str, Any], dict[str, Any]]:
    """The series with the shot edited (through ``update_series_episode``, so it is normalized and checked like any
    editor save), approvals reset when the take no longer fits, and the language versions' texts updated."""
    from services.series_library import update_series_episode
    episode = series["episodesById"][episode_id]
    stored = next(item for item in episode.get("shots") or [] if item.get("id") == shot_id)
    old_beats = [beat.get("id") for beat in stored.get("dialogueBeats") or []]
    updated = update_series_episode(series, episode_id, {"shots": [patch]}, base_series_revision=series.get("revision"),
                                    updated_at=updated_at)
    episode = updated["episodesById"][episode_id]
    missing = _write_versions(episode, shot_id, old_beats, texts, changed)
    report = _approval_report(episode, shot_id, stored, changed, keep_approval)
    return updated, {**report, "missingLines": {key: value for key, value in missing.items() if value}}


__all__ = ["CUT_KEYS", "LIST_KEYS", "SCRIPT_KEYS", "ShotEditError", "apply_edit", "build_patch", "find_shot", "merge_changes",
           "ordered_shots", "reset_approvals", "take_still_fits", "to_script"]
