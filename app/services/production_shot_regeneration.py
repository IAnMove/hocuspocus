"""Resolve one reviewed shot to its existing generation operation, without running it."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from services.production_shot_actions import ActionError, snapshot_recency, stored_revision
from services.production_shot_review import load_review
from services.production_run import adapt_pipeline_record


def regeneration_target(root: str, workspace: str, production_id: str, shot_id: str, body: dict) -> dict:
    from services.production_shot_view import shot_view
    view = shot_view(root, workspace, production_id)
    if view is None:
        raise ActionError("not_found")
    shot = next((item for item in view["shots"] if item["id"] == shot_id), None)
    if shot is None:
        raise ActionError("shot_not_found")
    if ((load_review(root, production_id) or {}).get("shots", {}).get(shot_id) or {}).get("locked"):
        raise ActionError("shot_locked")
    expected = body.get("expected_revision")
    if isinstance(expected, bool) or not isinstance(expected, int) or expected != stored_revision(root, production_id):
        raise ActionError("stale_revision")
    source = shot["provenance"]["source"]
    if source == "music":
        target = _music(root, workspace, production_id, shot_id)
    elif source == "director":
        target = _director(root, workspace, production_id, shot_id)
    elif source == "series":
        target = _series(root, workspace, view["project"]["id"], shot_id)
    else:
        raise ActionError("origin_unsupported")
    if target["executor"] == "http":
        target["body"]["shared_review"] = {"production_id": production_id, "shot_id": shot_id, "expected_revision": expected}
    return {"applied": False, "regeneration": target}


def guard_shared_regeneration(root: str, workspace: str, body: dict, endpoint: str | None = None) -> None:
    """Revalidate at the actual producer endpoint, not just when proposing the target."""
    review = body.get("shared_review")
    if review is None:
        return
    from fastapi import HTTPException
    if not isinstance(review, dict):
        raise HTTPException(422, detail={"code": "invalid_request"})
    try:
        target = regeneration_target(root, workspace, str(review.get("production_id") or ""),
                                     str(review.get("shot_id") or ""), review)["regeneration"]
        if endpoint is not None:
            matches = target["executor"] == "http" and unquote(urlsplit(target["path"]).path) == endpoint
            fields = {key: value for key, value in target.get("body", {}).items() if key != "shared_review"}
            if not matches or any(body.get(key) != value for key, value in fields.items()):
                raise ActionError("invalid_request", "The reviewed shot does not match this generation request")
    except ActionError as error:
        raise HTTPException(409 if error.code == "stale_revision" else 422,
                            detail={"code": error.code, "message": str(error)}) from error


def _read(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ActionError("origin_unsupported", "The generation source is unavailable") from error
    if not isinstance(value, dict):
        raise ActionError("origin_unsupported")
    return value


def publish_music_regeneration(production, shot_id: str, mode: str) -> None:
    """Publish the new source take without replacing another shot or its montage."""
    if mode == "scene":
        return  # The existing scene exporter already rewrites the manifest.
    from services.production_package import take_rows
    path = Path(production.root) / f"{production.id}.shots.json"
    document = _read(path)
    shot = next((item for item in document.get("shots", []) if item.get("key") == shot_id), None)
    if shot is None:
        raise ActionError("shot_not_found")
    if mode == "clip":
        shot["clip"] = production.state["clips"][shot_id]["file"]
        rows = {item["file"]: item for item in shot.get("takes", []) if item.get("file")}
        rows.update({item["file"]: item for item in take_rows(production.state, shot_id)})
        shot["takes"] = list(rows.values())
    else:
        shot["start_frame"] = production.state["frames"][shot_id]
    shot["video_stale"] = True
    document["revision"] = int(document.get("revision") or 0) + 1
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _music(root: str, workspace: str, production_id: str, shot_id: str) -> dict:
    state = _read(Path(root) / f"{production_id}.production.json")
    spec = state.get("spec") or {}
    shot = next((item for item in [*(spec.get("shots") or []), *(spec.get("fill") or [])]
                 if item.get("key") == shot_id), None)
    if shot is None:
        raise ActionError("origin_unsupported", "The shot has no saved generation specification")
    if shot.get("kind") == "clip":
        raise ActionError("origin_unsupported", "An imported clip has no generator")
    mode = {"h3": "clip", "scene3d": "scene"}.get(shot.get("kind"), "frame")
    return {"executor": "http", "path": f"/api/v1/music-productions/{quote(production_id)}/shots/{quote(shot_id)}/redo?workspace={quote(workspace)}",
            "body": {"from": mode}}


def _director(root: str, workspace: str, production_id: str, shot_id: str) -> dict:
    chosen: tuple[Path, dict] | None = None
    chosen_rank: tuple[float, float] | None = None
    for path in Path(root).glob("_director_pipeline_*.json"):
        try:
            state = _read(path)
            adapted = adapt_pipeline_record(state, workspace)
        except (ActionError, TypeError, ValueError):
            continue
        if adapted["production"]["id"] != production_id:
            continue
        rank = snapshot_recency(str(path), state)
        if chosen_rank is None or rank > chosen_rank:
            chosen, chosen_rank = (path, state), rank
    if chosen is None:
        raise ActionError("origin_unsupported")
    _path, state = chosen
    for index, clip in enumerate(state.get("clips") or []):
        if (clip.get("shot_id") or f"clip-{index + 1}") == shot_id:
            return {"executor": "http", "path": f"/api/v1/director/pipelines/{quote(state['pipeline_id'])}/clips/{index}/rerun-video",
                    "body": {"workspace": workspace}}
    raise ActionError("origin_unsupported")


def _series(root: str, workspace: str, episode_id: str, shot_id: str) -> dict:
    from services.series_production import is_series_generated_shot, series_shot_method
    library = _read(Path(root) / ".series-library-v1.json")
    for series_id, series in library.get("seriesById", {}).items():
        episode = series.get("episodesById", {}).get(episode_id)
        if not isinstance(episode, dict):
            continue
        shot = next((item for item in episode.get("shots", []) if item.get("id") == shot_id), None)
        if shot is None:
            raise ActionError("shot_not_found")
        if is_series_generated_shot(series, shot):
            return {"executor": "http", "path": f"/api/v1/series/{quote(series_id)}/episodes/{quote(episode_id)}/render/start",
                    "body": {"workspace": workspace, "mode": "selected", "shotIds": [shot_id]}}
        if series_shot_method(series, shot) == "animation_2d":
            return {"executor": "series_native", "workspace": workspace, "series_id": series_id,
                    "episode_id": episode_id, "shot_id": shot_id}
        raise ActionError("origin_unsupported", "An imported take has no generator")
    raise ActionError("origin_unsupported")
