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
        "language its own voice. Unknown fields are dropped by the server.",
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
        {"workspace": WORKSPACE, "series_id": ID, "episode_id": ID}, ["workspace", "series_id", "episode_id"], True,
        "Assemble the approved takes of an episode into one chapter video (shown under Capítulos). Returns a job.",
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
        ws = data["workspace"]
        if name == "characters.list":
            library = request("GET", "/api/v1/character-kits/library", query={"workspace": ws})
            return {"revision": library.get("revision"), "characters": [_kit_summary(kit) for kit in (library.get("kits") or {}).values()]}
        if name == "characters.get":
            library = request("GET", "/api/v1/character-kits/library", query={"workspace": ws})
            kit = (library.get("kits") or {}).get(data["character_id"])
            if kit is None:
                raise SeriesCommandError("Character not found", status=404)
            return {"revision": library.get("revision"), "character": kit}
        if name == "characters.save":
            character = data["character"]
            if not isinstance(character.get("id"), str) or not character["id"]:
                raise SeriesCommandError("The character needs an id")
            library = request("PATCH", f"/api/v1/character-kits/library/kits/{_quote(character['id'])}",
                              body={"workspace": ws, "kit": character, "baseRevision": data["base_revision"]})
            return {"revision": library.get("revision"), "character": _kit_summary(library["kits"][character["id"]])}
        if name == "series.list":
            listed = request("GET", "/api/v1/series", query={"workspace": ws})
            return {"series": [_series_summary(item) for item in listed.get("series") or []]}
        if name == "series.get":
            return {"series": request("GET", f"/api/v1/series/{_quote(data['series_id'])}", query={"workspace": ws})}
        if name == "series.create":
            created = request("POST", "/api/v1/series", body={"workspace": ws, "series": data["series"]})
            return {"series": _series_summary(created)}
        if name == "series.update":
            updated = request("PUT", f"/api/v1/series/{_quote(data['series_id'])}",
                              body={"workspace": ws, "series": data["series"], "baseRevision": data["base_revision"]})
            return {"series": _series_summary(updated)}
        if name == "series.canon.approve":
            approved = request("POST", f"/api/v1/series/{_quote(data['series_id'])}/canon/approve",
                               body={"workspace": ws, "baseRevision": data["base_revision"]})
            return {"series": _series_summary(approved)}
        if name == "series.episode.create":
            body = {"workspace": ws, "episode": data.get("episode") or {}}
            if data.get("season_id"):
                body["seasonId"] = data["season_id"]
            episode = request("POST", f"/api/v1/series/{_quote(data['series_id'])}/episodes", body=body)
            return {"episode": episode}
        if name == "series.episode.update":
            body = {"workspace": ws, "episode": data["episode"], "baseSeriesRevision": data["base_revision"]}
            if data.get("sync_shot_dialogue"):
                body["syncShotDialogueFromScript"] = True
            episode = request("PUT", f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}", body=body)
            return {"episode": episode}
        if name == "series.asset.import":
            source = workspace_file(ws, data["file"])
            target_dir = Path(uploads_dir()) / "series-imports"
            target_dir.mkdir(parents=True, exist_ok=True)
            upload = target_dir / f"{uuid.uuid4().hex[:12]}-{source.name}"
            shutil.copy2(source, upload)
            body = {"workspace": ws, "uploadPath": str(upload), "ownerType": data["owner_type"], "ownerId": data["owner_id"],
                    "kind": data["kind"], "asTake": data.get("as_take") is True, "name": data.get("name") or source.name,
                    "metadata": data.get("metadata") or {}}
            if data.get("reference_role"):
                body["referenceRole"] = data["reference_role"]
            try:
                imported = request("POST", f"/api/v1/series/{_quote(data['series_id'])}/assets/import", body=body)
            finally:
                upload.unlink(missing_ok=True)
            series = imported.get("series") or {}
            attempt = None
            if data.get("as_take"):
                for episode in (series.get("episodesById") or {}).values():
                    for shot in episode.get("shots") or []:
                        if shot.get("id") == data["owner_id"]:
                            attempt = next((item for item in reversed(shot.get("attempts") or [])
                                            if imported["asset"]["id"] in (item.get("outputAssetIds") or [])), None)
            return {"asset": imported.get("asset"), "attempt": attempt, "revision": series.get("revision")}
        if name == "series.take.approve":
            shot = request("POST", f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}"
                                   f"/shots/{_quote(data['shot_id'])}/attempts/{_quote(data['attempt_id'])}/approve", body={"workspace": ws})
            return {"shot": {"id": shot.get("id"), "approvedAttemptId": shot.get("approvedAttemptId")}}
        if name == "series.assembly.start":
            return {"job": request("POST", f"/api/v1/series/{_quote(data['series_id'])}/episodes/{_quote(data['episode_id'])}/assembly/start",
                                   body={"workspace": ws})}
        if name == "series.assembly.status":
            return {"job": request("GET", f"/api/v1/series/assembly/jobs/{_quote(data['job_id'])}", query={"workspace": ws})}
        raise SeriesCommandError("Unknown operation")

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
