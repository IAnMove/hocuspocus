"""HTTP for an episode's language versions: write lines by hand, translate with the LLM, remove.

What the LLM translates is marked ``machineTranslated`` until a person edits it (services/series_language_versions.py)."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from services.agent_activity import current_actor
from services.series_language_versions import (
    LANGUAGES, missing_lines, record_writer, translation_request, version_from_translation,
)
from services.series_shot_plan import language_key

EpisodeChange = Callable[[str, str, str, Callable[[dict, dict], None]], dict]


class VersionWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)
    version: dict[str, Any]


class VersionAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    workspace: str = Field(min_length=1, max_length=200)


def _empty() -> dict[str, Any]:
    return {"title": "", "dialogue": {}, "cards": {}, "approvedAttemptIds": {}, "assemblyAssetIds": []}


def _reply(series: dict, episode_id: str, language: str) -> dict[str, Any]:
    episode = series["episodesById"][episode_id]
    return {"revision": series.get("revision"), "language": language,
            "version": (episode.get("languageVersions") or {}).get(language), "missingLines": missing_lines(episode, language)}


def create_series_language_versions_router(*, change_episode: EpisodeChange, read_episode: Callable[[str, str, str], tuple[dict, dict]],
                                           translate: Callable[[str, str, dict], Any]) -> APIRouter:
    router = APIRouter()

    def check(series: dict, language: str) -> None:
        if language not in LANGUAGES:
            raise HTTPException(status_code=400, detail={"code": "invalid_language", "message": f"Unknown language {language}"})
        if language == language_key(series):
            raise HTTPException(status_code=400, detail={"code": "original_language", "message": "This is the series' own language"})

    def write(workspace: str, series_id: str, episode_id: str, language: str, merge: Callable[[dict, dict], dict]) -> dict[str, Any]:
        def apply(series: dict, episode: dict) -> None:
            check(series, language)
            versions = episode.setdefault("languageVersions", {})
            versions[language] = merge(versions.get(language) or _empty(), episode)
        try:
            return _reply(change_episode(workspace, series_id, episode_id, apply), episode_id, language)
        except KeyError as error:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Series episode not found"}) from error

    @router.put("/api/v1/series/{series_id}/episodes/{episode_id}/language-versions/{language}")
    def put_language_version(series_id: str, episode_id: str, language: str, body: VersionWrite):
        """Set a version's title, lines ({beatId: text}), cards or music ({shotId: file}); takes, lengths and cuts are kept.

        A person's write clears the machine-translation mark of what it wrote. An agent's or the Wizard's write marks
        the lines, cards and title it wrote. The server leaves those marks unchanged."""
        actor = current_actor()

        def merge(current: dict, _episode: dict) -> dict:
            update = body.version
            merged = {**current, **({"title": update["title"]} if isinstance(update.get("title"), str) else {}),
                      "dialogue": {**current.get("dialogue", {}), **(update.get("dialogue") or {})},
                      "cards": {**current.get("cards", {}), **(update.get("cards") or {})},
                      "music": {**current.get("music", {}), **(update.get("music") or {})}}
            return record_writer(merged, update, actor)
        return write(body.workspace, series_id, episode_id, language, merge)

    @router.post("/api/v1/series/{series_id}/episodes/{episode_id}/language-versions/{language}/translate")
    async def translate_language_version(series_id: str, episode_id: str, language: str, body: VersionAction):
        """Translate every line and card from the original with the configured LLM."""
        try:
            series, episode = read_episode(body.workspace, series_id, episode_id)
        except KeyError as error:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Series episode not found"}) from error
        check(series, language)
        requested_by = current_actor()
        prompt, system, schema = translation_request(series, episode, language)
        try:
            result = await run_in_threadpool(translate, prompt, system, schema)
        except (RuntimeError, ValueError) as error:
            raise HTTPException(status_code=503, detail={"code": "llm_unavailable", "message": str(error)}) from error
        return await run_in_threadpool(write, body.workspace, series_id, episode_id, language,
                                       lambda current, current_episode: version_from_translation(
                                           result, current_episode, current, requested_by=requested_by))

    @router.delete("/api/v1/series/{series_id}/episodes/{episode_id}/language-versions/{language}")
    def delete_language_version(series_id: str, episode_id: str, language: str, body: VersionAction):
        def apply(series: dict, episode: dict) -> None:
            (episode.get("languageVersions") or {}).pop(language, None)
        try:
            series = change_episode(body.workspace, series_id, episode_id, apply)
        except KeyError as error:
            raise HTTPException(status_code=404, detail={"code": "not_found", "message": "Series episode not found"}) from error
        return {"revision": series.get("revision"), "language": language, "deleted": True}

    return router
