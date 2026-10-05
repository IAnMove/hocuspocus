"""What an agent needs to make an episode, in one call: the guide and the series bible.

``series.guide`` returns ``shared/series_agent_guide.md`` (how to work with the
tools, the shot format, the house conventions, the pitfalls) and a bible built
from the live data: characters with their kits, poses and voices, locations
with variants, anchors and plates, the music and sound files in the
workspace, and the episodes so far. ``compact_episode`` gives one episode
without the render history noise, for copying an earlier episode's style.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

GUIDE_PATH = Path(__file__).resolve().parents[1] / "shared" / "series_agent_guide.md"
AUDIO = (".wav", ".mp3", ".flac", ".ogg", ".m4a")
SHOT_FIELDS = ("id", "order", "sceneId", "locationId", "locationVariantId", "productionMethod", "durationSeconds",
               "visibleCharacterIds", "speakingCharacterIds", "layout2d", "scene3d", "approvedAttemptId")


def guide_text() -> str:
    return GUIDE_PATH.read_text(encoding="utf-8")


def _character(character: dict[str, Any], kits: dict[str, Any]) -> dict[str, Any]:
    ref = ((character.get("voiceProfile") or {}).get("characterKitRef") or {}).get("id")
    kit = kits.get(ref) or {}
    voices = kit.get("voicesByLanguage") or {}
    entry = {"id": character["id"], "name": character.get("name"), "role": character.get("role"),
             "personality": character.get("personality"), "voiceAndDialogue": character.get("voiceAndDialogue"),
             "appearance": character.get("appearance"), "kitId": ref or None,
             "poses": (["base"] if kit.get("base") else []) + sorted((kit.get("poses") or {}).keys()),
             "voices": sorted(voices) or ([kit["voice"].get("language")] if isinstance(kit.get("voice"), dict) else []),
             "rigged": bool(kit.get("mouth"))}
    if isinstance(character.get("layout2d"), dict) and character["layout2d"]:
        entry["layout2d"] = character["layout2d"]
    if not ref or not kit:
        entry["missing"] = "no Character Kit yet: make one before rendering a shot with this character"
    return entry


def _location(location: dict[str, Any]) -> dict[str, Any]:
    layout = location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {}
    entry = {"id": location["id"], "name": location.get("name"), "description": location.get("description"),
             "variants": [variant.get("id") for variant in location.get("variants") or [] if variant.get("id")],
             "hasImage": bool(location.get("referenceAssetIds") or layout.get("backgroundAssetId") or layout.get("plateAssetId"))}
    for key in ("homes", "anchors"):
        if layout.get(key):
            entry[key] = layout[key]
    if layout.get("plateAssetId"):
        entry["plate3d"] = True
    return entry


def _episode_summary(episode: dict[str, Any]) -> dict[str, Any]:
    shots = episode.get("shots") or []
    versions = episode.get("languageVersions") or {}
    return {"id": episode["id"], "number": episode.get("number"), "title": episode.get("title"), "status": episode.get("status"),
            "shots": len(shots), "firstShotId": shots[0]["id"] if shots else None,
            "approvedShots": sum(1 for shot in shots if shot.get("approvedAttemptId")),
            "languageVersions": {lang: {"title": version.get("title"), "approvedShots": len(version.get("approvedAttemptIds") or {}),
                                        "cut": bool(version.get("latestAssemblyAssetId"))} for lang, version in versions.items()},
            "cut": bool(episode.get("latestAssemblyAssetId"))}


def audio_files(names: list[str]) -> dict[str, list[str]]:
    """Workspace audio a shot can use, by kind: music (mus-*), sound effects (sfx*) and the rest."""
    found: dict[str, list[str]] = {"music": [], "sfx": [], "other": []}
    for name in sorted(names):
        if not name.lower().endswith(AUDIO) or name.startswith((".", "_", "ln-", "voice-", "uv2-", "e2e-")):
            continue
        kind = "music" if name.startswith("mus") else "sfx" if name.startswith("sfx") else "other"
        if kind != "other" or len(found["other"]) < 40:
            found[kind].append(name)
    return found


def _series_summary(series: dict[str, Any]) -> dict[str, Any]:
    canon = series.get("canon") or {}
    keys = ("logline", "premise", "tone", "visualStyle", "characterVisualStyle", "cameraLanguage")
    return {"id": series["id"], "title": series.get("title"), "language": series.get("spokenLanguage") or series.get("language"),
            **{key: series.get(key) for key in keys}, "canonApproved": canon.get("approval") == "approved",
            "world": canon.get("worldSummary"), "rules": [rule.get("description") for rule in canon.get("immutableRules") or []],
            "themes": canon.get("themes") or []}


def build_bible(series: dict[str, Any], kits: dict[str, Any], workspace_files: list[str]) -> dict[str, Any]:
    episodes = sorted((series.get("episodesById") or {}).values(), key=lambda item: item.get("number") or 0)
    next_number = max([episode.get("number") or 0 for episode in episodes] + [0]) + 1
    return {
        "series": _series_summary(series),
        "characters": [_character(character, kits) for character in series.get("characters") or []],
        "locations": [_location(location) for location in series.get("locations") or []],
        "soundDesign": series.get("soundDesign") or {},
        "audio": audio_files(workspace_files),
        "episodes": [_episode_summary(episode) for episode in episodes],
        "nextEpisode": {"number": next_number, "idPrefix": f"e{next_number}s", "scenePrefix": f"e{next_number}_"},
    }


VERSION_FIELDS = ("title", "dialogue", "cards", "music", "durations", "approvedAttemptIds", "latestAssemblyAssetId")


def _take(assets: dict[str, Any], attempt: dict[str, Any]) -> dict[str, Any]:
    meta = (assets.get((attempt.get("outputAssetIds") or [None])[0]) or {}).get("metadata") or {}
    return {"id": attempt.get("id"), "status": attempt.get("status"), "language": meta.get("language"),
            "seconds": meta.get("duration") or (attempt.get("settings") or {}).get("sourceDurationSeconds"),
            "sceneFilename": meta.get("sceneFilename")}


def _compact_shot(assets: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    entry = {key: shot[key] for key in SHOT_FIELDS if key in shot}
    entry["dialogueBeats"] = [{"id": beat.get("id"), "characterId": beat.get("characterId"), "text": beat.get("text")}
                              for beat in shot.get("dialogueBeats") or []]
    entry["takes"] = [_take(assets, attempt) for attempt in shot.get("attempts") or [] if attempt.get("status") == "completed"][-4:]
    return entry


def compact_episode(series: dict[str, Any], episode: dict[str, Any]) -> dict[str, Any]:
    """An episode as an agent edits it: shots with their layout and lines, takes reduced to id, language, length."""
    assets = series.get("assets") or {}
    versions = {lang: {key: value for key, value in version.items() if key in VERSION_FIELDS}
                for lang, version in (episode.get("languageVersions") or {}).items()}
    script = [{key: scene.get(key) for key in ("id", "order", "locationId", "purpose")} for scene in episode.get("script") or []]
    return {"id": episode["id"], "number": episode.get("number"), "title": episode.get("title"), "premise": episode.get("premise"),
            "status": episode.get("status"), "script": script, "shots": [_compact_shot(assets, shot) for shot in episode.get("shots") or []],
            "languageVersions": versions, "latestAssemblyAssetId": episode.get("latestAssemblyAssetId"),
            **({"score": episode["score"]} if episode.get("score") else {})}
