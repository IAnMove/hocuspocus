"""MCP access to Series Lab and Character Kits.

Each tool is a thin projection of the existing HTTP endpoint (same validation,
revision checks and locks), so an agent can create a series, its characters and
their voices, write an episode, attach takes and assemble the chapter without a
browser tab. Workspace files are copied into uploads for the import endpoint,
which only reads HocusPocus uploads.
"""
from __future__ import annotations

import json
import shutil
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Callable

WORKSPACE = {"type": "string", "minLength": 1, "maxLength": 120}
ID = {"type": "string", "minLength": 1, "maxLength": 160}
REVISION = {"type": "integer", "minimum": 0}
OBJECT = {"type": "object"}
LANGUAGE = {"type": "string", "enum": ["english", "spanish", "french", "german", "italian", "portuguese", "japanese", "korean", "chinese", "russian"]}

# name: (properties, required, mutation, description)
OPERATIONS: dict[str, tuple[dict[str, Any], list[str], bool, str]] = {
    "characters.list": (
        {"workspace": WORKSPACE}, ["workspace"], False,
        "List Character Kits in a workspace: id, name, poses, mouth states, default voice and voices by language, "
        "plus the library revision that characters.save needs.",
    ),
    "characters.get": (
        {"workspace": WORKSPACE, "character_id": ID}, ["workspace", "character_id"], False,
        "Read one Character Kit (poses, mouths, anchors, voice, voicesByLanguage) and the library revision.",
    ),
    "characters.save": (
        {"workspace": WORKSPACE, "character": OBJECT, "base_revision": REVISION}, ["workspace", "character", "base_revision"], True,
        "Create or update one Character Kit with the library revision from characters.list/get. Assets must be "
        "durable workspace URLs. voice is the default voice; voicesByLanguage {english, spanish, ...} gives a "
        "language its own voice. The server drops fields it does not know and lists their paths in ignoredFields.",
    ),
    "characters.styles": (
        {"style": {"type": "string", "maxLength": 80}, "kind": {"enum": ["character", "pose", "prop"]},
         "description": {"type": "string", "maxLength": 2000}},
        [], False,
        "List character style presets (prompt fragments, kit style, default mouth look for characters.rig.flat). "
        "With style, kind and description, also returns the prompt, negative prompt and screen colour to generate "
        "with: magenta when the description has green in it, else green. Key the result with studio.key in that mode.",
    ),
    "characters.rig.flat": (
        {"workspace": WORKSPACE, "character_id": ID, "base_revision": REVISION,
         "style": {"type": "object", "properties": {
             "screen": {"type": "boolean"}, "smile": {"type": "number", "minimum": -1, "maximum": 1},
             "smirk": {"type": "number", "minimum": 0, "maximum": 1}, "width": {"type": "number", "minimum": 0.3, "maximum": 0.9},
             "mouth_scale": {"type": "number", "minimum": 0.4, "maximum": 1.2}}},
         "poses": {"type": "array", "items": ID, "maxItems": 32}},
        ["workspace", "character_id", "base_revision"], True,
        "Make a flat cutout character talk: find the eyes and painted mouth on each keyed pose, wipe the mouth, "
        "draw nine paper mouths and a blink, and save anchors on the kit. The base pose must have a transparent "
        "background (studio.key). style: smile -1..1 (frown to grin), smirk 0..1, width, mouth_scale; screen true for "
        "a face that is a screen. Returns the saved kit, a review image URL and unwipedPoses (no painted mouth found).",
    ),
    "series.episode.render_native": (
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID, "shot_ids": {"type": "array", "items": ID, "maxItems": 500},
         "approve": {"type": "boolean"}, "language": LANGUAGE},
        ["workspace", "series_id", "episode_id"], True,
        "Render every 2D animation shot of an episode on the server, no browser needed: each line in the character's voice "
        "for the series language (checked with qa.speech, up to three takes), phonetic mouth cues, an editable Video 2D "
        "scene (framing from shot.framing or shot.layout2d, cast, sound, cards), a headless export and a take on the shot "
        "(approve: true approves it). language renders a language version (its lines, the characters' voices for that "
        "language, its own takes). Returns the job; poll series.episode.render_native.status. Resumable.",
    ),
    "series.episode.render_native.status": (
        {"workspace": WORKSPACE, "job_id": ID}, ["workspace", "job_id"], False,
        "Status of a server episode render: per shot stage (voices, scene, export, import, done), line takes and errors.",
    ),
    "series.episode.render_native.cancel": (
        {"workspace": WORKSPACE, "job_id": ID}, ["workspace", "job_id"], True,
        "Stop a server episode render after its current step. Finished shots keep their takes; resume continues.",
    ),
    "series.episode.render_native.resume": (
        {"workspace": WORKSPACE, "job_id": ID}, ["workspace", "job_id"], True,
        "Resume a stopped or failed server episode render from each shot's last stage, reusing recorded lines.",
    ),
    "series.location.plate3d": (
        {"workspace": WORKSPACE, "series_id": ID, "location_id": ID, "scene": {"type": "string", "minLength": 1, "maxLength": 200},
         "document": OBJECT, "seconds": {"type": "number", "minimum": 2, "maximum": 20}, "quality": {"enum": ["draft", "final", "master"]}},
        ["workspace", "series_id", "location_id"], True,
        "Render a Video 3D scene once as the looping background plate of a series location: give scene (a saved Video 3D "
        "scene file or a w3d- working scene id) or document. The plate is silent, without kinetic text, seconds long "
        "(default 6). Poll series.location.plate3d.status: when the export is ready it is imported as a location video "
        "and 2D shots in that location use it as their background.",
    ),
    "series.location.plate3d.status": (
        {"workspace": WORKSPACE, "series_id": ID, "location_id": ID}, ["workspace", "series_id", "location_id"], False,
        "Status of a location's 3D plate (rendering, done, failed). When the export has finished it imports the video "
        "and sets it as the location plate (idempotent).",
    ),
    "series.list": (
        {"workspace": WORKSPACE}, ["workspace"], False,
        "List Series Lab projects with their revision, language and episodes (id, number, title, shot count, status).",
    ),
    "series.get": (
        {"workspace": WORKSPACE, "series_id": ID}, ["workspace", "series_id"], False,
        "Read one complete Series Lab project, including characters, locations, canon and episodes.",
    ),
    "series.create": (
        {"workspace": WORKSPACE, "series": OBJECT}, ["workspace", "series"], True,
        "Create a Series Lab project from a full series object (title, language, spokenLanguage, visualStyle, "
        "allowedProductionMethods, characters with voiceProfile.characterKitRef, locations, canon.worldSummary).",
    ),
    "series.update": (
        {"workspace": WORKSPACE, "series_id": ID, "series": OBJECT, "base_revision": REVISION},
        ["workspace", "series_id", "series", "base_revision"], True,
        "Replace a Series Lab project at an exact revision. Changing canon inputs returns the canon to draft.",
    ),
    "series.canon.approve": (
        {"workspace": WORKSPACE, "series_id": ID, "base_revision": REVISION}, ["workspace", "series_id", "base_revision"], True,
        "Approve the reviewed canon (base_revision is canon.revision). Needs a world summary, a character and a location.",
    ),
    "series.episode.create": (
        {"workspace": WORKSPACE, "series_id": ID, "season_id": {"type": "string", "maxLength": 160}, "episode": OBJECT},
        ["workspace", "series_id"], True,
        "Create an episode (chapter) in an approved series. It freezes the approved canon and references.",
    ),
    "series.episode.update": (
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID, "episode": OBJECT, "base_revision": REVISION,
         "sync_shot_dialogue": {"type": "boolean"}},
        ["workspace", "series_id", "episode_id", "episode", "base_revision"], True,
        "Save editor fields of an episode (title, premise, script, shots with productionMethod, dialogueBeats, "
        "visible/speaking characters, locationId, durationSeconds) at the series revision.",
    ),
    "series.asset.import": (
        {"workspace": WORKSPACE, "series_id": ID, "file": {"type": "string", "minLength": 1, "maxLength": 300},
         "owner_type": {"enum": ["series", "character", "location", "prop", "episode", "shot"]}, "owner_id": ID,
         "kind": {"enum": ["image", "audio", "video", "character", "location", "prop", "other"]},
         "as_take": {"type": "boolean"}, "name": {"type": "string", "maxLength": 300},
         "reference_role": {"type": "string", "maxLength": 100}, "metadata": OBJECT},
        ["workspace", "series_id", "file", "owner_type", "owner_id", "kind"], True,
        "Import a workspace file as a reference image of a character/location, or as_take a finished shot video "
        "(metadata.sceneFilename lets Series Lab reopen its editable scene). A take is appended unapproved.",
    ),
    "series.take.approve": (
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID, "shot_id": ID, "attempt_id": ID},
        ["workspace", "series_id", "episode_id", "shot_id", "attempt_id"], True,
        "Approve one completed take for its shot. Assembly uses the approved take of every shot.",
    ),
    "series.assembly.start": (
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID, "language": LANGUAGE, "burn_subtitles": {"type": "boolean"}},
        ["workspace", "series_id", "episode_id"], True,
        "Assemble the approved takes of an episode into one chapter video (shown under Capítulos), at -16 LUFS with SRT/VTT "
        "subtitles; burn_subtitles also writes a copy with them on the picture. language assembles that language version's "
        "approved takes. Returns a job.",
    ),
    "series.episode.language_version.set": (
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID, "language": LANGUAGE,
          "title": {"type": "string", "maxLength": 300}, "dialogue": OBJECT, "cards": OBJECT},
        ["workspace", "series_id", "episode_id", "language"], True,
        "Write a language version of an episode: the same shots and line ids with their own text. dialogue maps beat id to "
        "text; cards maps shot id to {title, body}. Approved takes and cuts of the version are kept. Returns missingLines.",
    ),
    "series.episode.translate": (
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID, "language": LANGUAGE},
        ["workspace", "series_id", "episode_id", "language"], True,
        "Translate every line and card of an episode into a language version with the configured LLM (for dubbing: same "
        "meaning and joke, similar length, numbers as words). Review it with series.get, then render it with "
        "series.episode.render_native language.",
    ),
    "series.assembly.status": (
        {"workspace": WORKSPACE, "job_id": ID}, ["workspace", "job_id"], False,
        "Read an episode assembly job: stage, progress, error and the chapter output when finished.",
    ),
}


class SeriesCommandError(ValueError):
    def __init__(self, message: Any, *, status: int = 422) -> None:
        super().__init__(message if isinstance(message, str) else json.dumps(message, ensure_ascii=False))
        self.detail = message
        self.status = status


def _operation_schema(name: str, properties: dict[str, Any], required: list[str], mutation: bool, description: str) -> dict[str, Any]:
    return {
        "name": name, "version": 1, "domain": name.split(".")[0], "mutation": mutation, "description": description,
        "inputSchema": {"type": "object", "additionalProperties": False, "required": ["version", "input"], "properties": {
            "version": {"type": "integer", "const": 1},
            "input": {"type": "object", "additionalProperties": False, "properties": properties, "required": required},
        }},
    }


def command_catalog() -> list[dict[str, Any]]:
    return [_operation_schema(name, *spec) for name, spec in OPERATIONS.items()]


def _quote(value: str) -> str:
    return urllib.parse.quote(str(value), safe="")


def _kit_summary(kit: dict[str, Any]) -> dict[str, Any]:
    def label(voice: Any) -> str | None:
        if not isinstance(voice, dict):
            return None
        return voice.get("name") if voice.get("model") == "qwen3_tts_base" else voice.get("voiceId")
    return {"id": kit.get("id"), "name": kit.get("name"), "style": kit.get("style"),
            "poses": ["base", *sorted(kit.get("poses") or {})] if kit.get("base") else sorted(kit.get("poses") or {}),
            "mouths": sorted(kit.get("mouth") or {}), "voice": label(kit.get("voice")),
            "voicesByLanguage": {language: label(voice) for language, voice in (kit.get("voicesByLanguage") or {}).items()}}


def _series_summary(series: dict[str, Any]) -> dict[str, Any]:
    episodes = series.get("episodesById") or {}
    order = [episode_id for season in series.get("seasons") or [] for episode_id in season.get("episodeOrder") or []]
    return {"id": series.get("id"), "title": series.get("title"), "revision": series.get("revision"),
            "language": series.get("language"), "spokenLanguage": series.get("spokenLanguage"),
            "canon": (series.get("canon") or {}).get("approval"), "canonRevision": (series.get("canon") or {}).get("revision"),
            "characters": [{"id": item.get("id"), "name": item.get("name"),
                            "characterKitRef": (item.get("voiceProfile") or {}).get("characterKitRef")} for item in series.get("characters") or []],
            "episodes": [{"id": episode_id, "number": episodes[episode_id].get("number"), "title": episodes[episode_id].get("title"),
                          "status": episodes[episode_id].get("status"), "shots": len(episodes[episode_id].get("shots") or []),
                          "latestAssemblyAssetId": episodes[episode_id].get("latestAssemblyAssetId")}
                         for episode_id in order if episode_id in episodes]}


def _list_characters(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    library = request("GET", "/api/v1/character-kits/library", query={"workspace": data["workspace"]})
    kits = (library.get("kits") or {}).values()
    return {"revision": library.get("revision"), "characters": [_kit_summary(kit) for kit in kits]}


def _get_character(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    library = request("GET", "/api/v1/character-kits/library", query={"workspace": data["workspace"]})
    kit = (library.get("kits") or {}).get(data["character_id"])
    if kit is None:
        raise SeriesCommandError("Character not found", status=404)
    return {"revision": library.get("revision"), "character": kit}


def _ignored_fields(sent: Any, stored: Any, prefix: str = "") -> list[str]:
    """Paths the server dropped while normalizing. Lists are compared as whole values."""
    if not isinstance(sent, dict) or not isinstance(stored, dict):
        return []
    ignored: list[str] = []
    for key, value in sent.items():
        path = f"{prefix}{key}"
        if value is None:
            continue
        if key not in stored:
            ignored.append(path)
        else:
            ignored.extend(_ignored_fields(value, stored[key], f"{path}."))
    return ignored


def _save_character(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    character = data["character"]
    if not isinstance(character.get("id"), str) or not character["id"]:
        raise SeriesCommandError("The character needs an id")
    library = request(
        "PATCH", f"/api/v1/character-kits/library/kits/{_quote(character['id'])}",
        body={"workspace": data["workspace"], "kit": character, "baseRevision": data["base_revision"]},
    )
    stored = library["kits"][character["id"]]
    return {"revision": library.get("revision"), "character": _kit_summary(stored),
            "ignoredFields": _ignored_fields(character, stored)}


def _character_styles(data: dict[str, Any], _request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    from services.character_styles import style_catalog, style_prompt
    result: dict[str, Any] = {"styles": style_catalog()["styles"], "screens": sorted(style_catalog()["screens"])}
    if data.get("style") and data.get("kind"):
        try:
            result["prompt"] = style_prompt(data["style"], data["kind"], data.get("description") or "")
        except KeyError as error:
            raise SeriesCommandError(f"Unknown style {data['style']}", status=404) from error
    return result


def _rig_flat_character(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"workspace": data["workspace"], "baseRevision": data["base_revision"]}
    for key in ("style", "poses"):
        if key in data:
            body[key] = data[key]
    rigged = request("POST", f"/api/v1/character-kits/library/kits/{_quote(data['character_id'])}/flat-rig", body=body)
    return {**rigged, "character": _kit_summary(rigged["character"])}


def _render_native(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"workspace": data["workspace"], "approve": bool(data.get("approve"))}
    if data.get("language"):
        body["language"] = data["language"]
    if data.get("shot_ids"):
        body["shotIds"] = data["shot_ids"]
    path = f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}/native-render"
    return {"job": request("POST", path, body=body)}


def _native_job(action: str) -> Callable[..., dict[str, Any]]:
    def run(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
        path = f"/api/v1/series/native-render/jobs/{_quote(data['job_id'])}"
        if action == "status":
            return {"job": request("GET", path, query={"workspace": data["workspace"]})}
        return {"job": request("POST", f"{path}/{action}", body={"workspace": data["workspace"]})}
    return run


def _plate_path(data: dict[str, Any]) -> str:
    return f"/api/v1/series/{_quote(data['series_id'])}/locations/{_quote(data['location_id'])}/plate3d"


def _start_plate(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body = {"workspace": data["workspace"], **{key: data[key] for key in ("scene", "document", "seconds", "quality") if key in data}}
    return {"plate": request("POST", _plate_path(data), body=body)}


def _plate_status(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    return {"plate": request("GET", _plate_path(data), query={"workspace": data["workspace"]})}


def _list_series(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    listed = request("GET", "/api/v1/series", query={"workspace": data["workspace"]})
    return {"series": [_series_summary(item) for item in listed.get("series") or []]}


def _get_series(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    series = request("GET", f"/api/v1/series/{_quote(data['series_id'])}", query={"workspace": data["workspace"]})
    return {"series": series}


def _create_series(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    created = request("POST", "/api/v1/series", body={"workspace": data["workspace"], "series": data["series"]})
    return {"series": _series_summary(created)}


def _update_series(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    updated = request(
        "PUT", f"/api/v1/series/{_quote(data['series_id'])}",
        body={"workspace": data["workspace"], "series": data["series"], "baseRevision": data["base_revision"]},
    )
    return {"series": _series_summary(updated)}


def _approve_canon(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    approved = request(
        "POST", f"/api/v1/series/{_quote(data['series_id'])}/canon/approve",
        body={"workspace": data["workspace"], "baseRevision": data["base_revision"]},
    )
    return {"series": _series_summary(approved)}


def _create_episode(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"workspace": data["workspace"], "episode": data.get("episode") or {}}
    if data.get("season_id"):
        body["seasonId"] = data["season_id"]
    episode = request("POST", f"/api/v1/series/{_quote(data['series_id'])}/episodes", body=body)
    return {"episode": episode}


def _update_episode(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "workspace": data["workspace"], "episode": data["episode"], "baseSeriesRevision": data["base_revision"],
    }
    if data.get("sync_shot_dialogue"):
        body["syncShotDialogueFromScript"] = True
    path = f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}"
    return {"episode": request("PUT", path, body=body)}


def _matching_take(series: dict[str, Any], owner_id: str, asset_id: str) -> Any:
    episodes = (series.get("episodesById") or {}).values()
    for episode in episodes:
        for shot in episode.get("shots") or []:
            if shot.get("id") != owner_id:
                continue
            for item in reversed(shot.get("attempts") or []):
                if asset_id in (item.get("outputAssetIds") or []):
                    return item
    return None


def _import_asset(data: dict[str, Any], request: Callable[..., Any], *, workspace_file: Callable[[str, str], Path], uploads_dir: Callable[[], str]) -> dict[str, Any]:
    source = workspace_file(data["workspace"], data["file"])
    target_dir = Path(uploads_dir()) / "series-imports"
    target_dir.mkdir(parents=True, exist_ok=True)
    upload = target_dir / f"{uuid.uuid4().hex[:12]}-{source.name}"
    shutil.copy2(source, upload)
    body: dict[str, Any] = {
        "workspace": data["workspace"], "uploadPath": str(upload), "ownerType": data["owner_type"],
        "ownerId": data["owner_id"], "kind": data["kind"], "asTake": data.get("as_take") is True,
        "name": data.get("name") or source.name, "metadata": data.get("metadata") or {},
    }
    if data.get("reference_role"):
        body["referenceRole"] = data["reference_role"]
    try:
        imported = request("POST", f"/api/v1/series/{_quote(data['series_id'])}/assets/import", body=body)
    finally:
        upload.unlink(missing_ok=True)
    series = imported.get("series") or {}
    attempt = None
    if data.get("as_take"):
        attempt = _matching_take(series, data["owner_id"], imported["asset"]["id"])
    return {"asset": imported.get("asset"), "attempt": attempt, "revision": series.get("revision")}


def _approve_take(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    path = (
        f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}"
        f"/shots/{_quote(data['shot_id'])}/attempts/{_quote(data['attempt_id'])}/approve"
    )
    shot = request("POST", path, body={"workspace": data["workspace"]})
    return {"shot": {"id": shot.get("id"), "approvedAttemptId": shot.get("approvedAttemptId")}}


def _start_assembly(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    path = f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}/assembly/start"
    body: dict[str, Any] = {"workspace": data["workspace"]}
    if data.get("language"):
        body["language"] = data["language"]
    if data.get("burn_subtitles"):
        body["burnSubtitles"] = True
    return {"job": request("POST", path, body=body)}


def _version_path(data: dict[str, Any]) -> str:
    return (f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}"
            f"/language-versions/{_quote(data['language'])}")


def _set_language_version(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    version = {key: data[key] for key in ("title", "dialogue", "cards") if key in data}
    return request("PUT", _version_path(data), body={"workspace": data["workspace"], "version": version})


def _translate_episode(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    return request("POST", f"{_version_path(data)}/translate", body={"workspace": data["workspace"]})


def _assembly_status(data: dict[str, Any], request: Callable[..., Any], **_extra: Any) -> dict[str, Any]:
    job = request("GET", f"/api/v1/series/assembly/jobs/{_quote(data['job_id'])}", query={"workspace": data["workspace"]})
    return {"job": job}


_RUNNERS: dict[str, Callable[..., Any]] = {
    "characters.list": _list_characters,
    "characters.get": _get_character,
    "characters.save": _save_character,
    "characters.styles": _character_styles,
    "characters.rig.flat": _rig_flat_character,
    "series.episode.render_native": _render_native,
    "series.episode.render_native.status": _native_job("status"),
    "series.episode.render_native.cancel": _native_job("cancel"),
    "series.episode.render_native.resume": _native_job("resume"),
    "series.location.plate3d": _start_plate,
    "series.location.plate3d.status": _plate_status,
    "series.list": _list_series,
    "series.get": _get_series,
    "series.create": _create_series,
    "series.update": _update_series,
    "series.canon.approve": _approve_canon,
    "series.episode.create": _create_episode,
    "series.episode.update": _update_episode,
    "series.take.approve": _approve_take,
    "series.assembly.start": _start_assembly,
    "series.episode.language_version.set": _set_language_version,
    "series.episode.translate": _translate_episode,
    "series.assembly.status": _assembly_status,
}


def _run_operation(name: str, data: dict[str, Any], request: Callable[..., Any], workspace_file: Callable[[str, str], Path], uploads_dir: Callable[[], str]) -> Any:
    if name == "series.asset.import":
        return _import_asset(data, request, workspace_file=workspace_file, uploads_dir=uploads_dir)
    runner = _RUNNERS.get(name)
    if runner is None:
        raise SeriesCommandError("Unknown operation")
    return runner(data, request)


def command_handlers(app_url: Callable[[], str], workspace_dir: Callable[[str], str],
                     uploads_dir: Callable[[], str], *, opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Callable[[Any], Any]]:
    def request(method: str, path: str, *, query: dict[str, str] | None = None, body: dict[str, Any] | None = None) -> Any:
        base = app_url().rstrip("/")
        if not base:
            raise SeriesCommandError("The HocusPocus server address is not ready yet", status=503)
        url = base + path + ("?" + urllib.parse.urlencode(query) if query else "")
        data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
        headers = {"Content-Type": "application/json"} if data is not None else {}
        try:
            with opener(urllib.request.Request(url, data=data, method=method, headers=headers), timeout=120) as response:
                return json.loads(response.read().decode() or "null")
        except urllib.error.HTTPError as error:
            try:
                detail = json.loads(error.read().decode()).get("detail")
            except (ValueError, AttributeError):
                detail = error.reason
            raise SeriesCommandError(detail or f"HTTP {error.code}", status=error.code) from error

    def workspace_file(workspace: str, name: str) -> Path:
        root = Path(workspace_dir(workspace)).resolve()
        candidate = (root / name).resolve()
        if root not in candidate.parents or not candidate.is_file():
            raise SeriesCommandError("Use an existing file inside the workspace", status=404)
        return candidate

    def run(name: str, data: dict[str, Any]) -> Any:
        return _run_operation(name, data, request, workspace_file, uploads_dir)

    def handler(name: str) -> Callable[[Any], Any]:
        properties, required, _, _ = OPERATIONS[name]

        async def handle(arguments: Any) -> dict[str, Any]:
            from fastapi import HTTPException
            from starlette.concurrency import run_in_threadpool
            data = arguments.get("input") if isinstance(arguments, dict) and arguments.get("version") == 1 else None
            if not isinstance(data, dict) or set(data) - set(properties) or any(key not in data for key in required):
                raise HTTPException(422, {"code": "invalid_command", "message": f"Use version 1 with input fields: {', '.join(required)}", "retryable": False})
            try:
                result = await run_in_threadpool(run, name, data)
            except SeriesCommandError as error:
                code = "conflict" if error.status == 409 else "not_found" if error.status == 404 else "invalid_command"
                raise HTTPException(error.status if error.status < 500 else 502,
                                    {"code": code, "message": str(error.detail), "retryable": error.status in (409, 503)}) from error
            return {"version": 1, "status": "completed", "operation": name, "result": result}
        return handle

    return {name: handler(name) for name in OPERATIONS}


__all__ = ["OPERATIONS", "SeriesCommandError", "command_catalog", "command_handlers"]
