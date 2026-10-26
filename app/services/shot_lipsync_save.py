"""Save a lip-sync redo as a new take and leave the selected original in place."""
from __future__ import annotations

import json
import os
import shutil
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from services.production_media_common import MediaToolError, publish_sidecar, source_ref
from services.workspace_store_lock import workspace_store_lock

OPERATION = "shot.lipsync.redo"


def _write_json(path: str, body: dict) -> None:
    temporary = f"{path}.{uuid.uuid4().hex}.tmp"
    try:
        with open(temporary, "w", encoding="utf-8") as handle:
            json.dump(body, handle, ensure_ascii=False, indent=1)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        if os.path.isfile(temporary):
            try:
                os.remove(temporary)
            except OSError:
                pass
        raise


def _read_json(path: str) -> dict | None:
    if not os.path.isfile(path):
        return None
    try:
        body = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MediaToolError("shots_unreadable", "The shot record could not be read.", 422) from exc
    if not isinstance(body, dict):
        raise MediaToolError("shots_unreadable", "The shot record could not be read.", 422)
    return body


def _sidecar(path: str, workspace: str, params: dict[str, Any], sources: list[str]) -> None:
    publish_sidecar(path, workspace, OPERATION, "video", params, [source_ref(item, workspace) for item in sources])


def _take_row(name: str, number: int, qa: dict[str, Any], engine: str) -> dict[str, Any]:
    row: dict[str, Any] = {"file": name, "take": number, "verdict": qa.get("verdict"), "engine": engine}
    if "best_r" in qa:
        row["r"] = qa.get("best_r")
    return row


def _append_unique(rows: list, original: str | None) -> list:
    kept = [item for item in rows if isinstance(item, dict)]
    if original and not any(item.get("file") == original for item in kept):
        kept.insert(0, {"file": original, "take": 1, "kept": True})
    return kept


def _next_number(rows: list) -> int:
    numbers = [item.get("take") for item in rows if isinstance(item, dict) and isinstance(item.get("take"), int)]
    return max(numbers or [0]) + 1


@contextmanager
def _production_edit(workspace: str, production_id: str):
    """The slot ``production.run`` and music shot edits already hold."""
    from services.production_shot_actions import ActionError, _hold_edit
    try:
        with _hold_edit(workspace, production_id):
            yield
    except ActionError as exc:
        raise MediaToolError(exc.code, str(exc) or exc.code, 409) from exc


def _revise(document: dict, expected: Any) -> None:
    """Bump the shots revision. Check it only when the caller sent one."""
    from services.production_shot_actions import ActionError, _bump, _expect
    if expected is not None:
        try:
            _expect(document, expected)
        except ActionError as exc:
            raise MediaToolError(exc.code, str(exc) or exc.code, 409) from exc
    _bump(document)


def save_production(folder: str, workspace: str, target: dict, video: str, qa: dict, engine: str) -> dict[str, Any]:
    """Append one take on ``<id>.shots.json`` and, when present, ``<id>.production.json``."""
    production_id, shot_id = target["production_id"], target["shot"]
    name = os.path.basename(video)
    manifest = os.path.join(folder, f"{production_id}.shots.json")
    with _production_edit(workspace, production_id):
        with workspace_store_lock(Path(manifest)):
            body = _read_json(manifest)
            if body is None:
                raise MediaToolError("shot_not_found", "Production shots were not found.", 404)
            row = _production_row(body, shot_id)
            original = row.get("clip") if isinstance(row.get("clip"), str) else target["original_name"]
            takes = _append_unique(list(row.get("takes") or []), original if isinstance(original, str) else None)
            record = _take_row(name, _next_number(takes), qa, engine)
            takes.append(record)
            row["takes"] = takes
            _revise(body, target.get("expected_revision"))
            _write_json(manifest, body)
            _append_state_take(folder, production_id, shot_id, record, original if isinstance(original, str) else None)
    _sidecar(video, workspace, {"engine": engine, "shot": shot_id, "production_id": production_id}, [target["video"]])
    return {"file": name, "kept_original": original, "take": record, "target": "production"}


def _production_row(body: dict, shot_id: str) -> dict:
    rows = body.get("shots")
    if not isinstance(rows, list):
        raise MediaToolError("shots_unreadable", "The shot record could not be read.", 422)
    for item in rows:
        if isinstance(item, dict) and item.get("key") == shot_id:
            return item
    raise MediaToolError("shot_not_found", "Production shot was not found.", 404)


def _append_state_take(folder: str, production_id: str, shot_id: str, record: dict, original: str | None) -> None:
    path = os.path.join(folder, f"{production_id}.production.json")
    state = _read_json(path)
    if state is None:
        return
    takes = state.get("takes")
    if not isinstance(takes, dict):
        takes = {}
        state["takes"] = takes
    rows = takes.get(shot_id)
    rows = _append_unique(list(rows) if isinstance(rows, list) else [], original)
    if not any(isinstance(item, dict) and item.get("file") == record["file"] for item in rows):
        rows.append(record)
    takes[shot_id] = rows
    _write_json(path, state)


def save_clip(folder: str, workspace: str, target: dict, video: str, qa: dict, engine: str) -> dict[str, Any]:
    """A new file next to the clip, plus a small list that names the original and the new take."""
    original = target["original_name"]
    name = os.path.basename(video)
    path = os.path.join(folder, f"{Path(original).stem}.lipsync-takes.json")
    body = _read_json(path) or {"version": 1, "original": original, "takes": [{"file": original, "kept": True}]}
    rows = body.get("takes") if isinstance(body.get("takes"), list) else []
    rows = _append_unique(rows, original)
    record = _take_row(name, _next_number(rows), qa, engine)
    rows.append(record)
    body["takes"] = rows
    body["original"] = original
    body["version"] = 1
    _write_json(path, body)
    _sidecar(video, workspace, {"engine": engine, "clip": original}, [target["video"]])
    return {"file": name, "kept_original": original, "take": record, "target": "clip", "takes": os.path.basename(path)}


def _with_library_lock(action: Callable[[], Any]) -> Any:
    """The series library RLock launch binds. Tests that leave it unset still write."""
    from routers import series_library as routes
    lock = getattr(routes, "_library_lock", None)
    if lock is None:
        return action()
    with lock:
        return action()


def save_series(folder: str, workspace: str, target: dict, video: str, qa: dict, engine: str) -> dict[str, Any]:
    """Append a completed attempt. ``approvedAttemptId`` stays on the original take."""
    from services.series_library import (
        append_shot_render_attempt, read_series_library, update_shot_render_attempt, write_series_library,
    )

    series_id, episode_id, shot_id = target["series_id"], target["episode_id"], target["shot"]

    def store() -> dict[str, Any]:
        library = read_series_library(folder, workspace)
        series, episode, index, shot = _series_shot(library, series_id, episode_id, shot_id)
        asset_id = f"asset_{uuid.uuid4().hex[:12]}"
        relative = f"assets/{series_id}/{asset_id}.mp4"
        destination = os.path.join(folder, *relative.split("/"))
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        shutil.copy2(video, destination)
        approved = shot.get("approvedAttemptId")
        from services.shot_lipsync_catalog import PROMPT
        updated, attempt = append_shot_render_attempt(
            shot, manifest=shot.get("referenceManifest") or {}, model=engine,
            settings={"engine": engine, "source": "shot.lipsync.redo", "verdict": qa.get("verdict")},
            seed=None, prompt=PROMPT,
        )
        updated = update_shot_render_attempt(
            updated, attempt["id"], status="completed", outputAssetIds=[asset_id],
        )
        if approved:
            updated["approvedAttemptId"] = approved
        episode["shots"][index] = updated
        series.setdefault("assets", {})[asset_id] = {
            "id": asset_id, "workspaceId": workspace, "kind": "video", "uri": relative,
            "ownerType": "attempt", "ownerId": attempt["id"], "isDerivedThumbnail": False,
            "metadata": {"engine": engine, "verdict": qa.get("verdict"), "source": target["original_name"]},
        }
        if isinstance(series.get("revision"), int):
            series["revision"] = series["revision"] + 1
        try:
            write_series_library(folder, library, workspace)
        except ValueError as exc:
            if os.path.isfile(destination):
                os.remove(destination)
            raise MediaToolError("save_failed", str(exc), 500) from exc
        return {"destination": destination, "relative": relative, "attempt_id": attempt["id"]}

    saved = _with_library_lock(store)
    _sidecar(saved["destination"], workspace, {"engine": engine, "shot": shot_id, "series_id": series_id}, [target["video"]])
    return {
        "file": os.path.basename(video), "asset": saved["relative"], "attempt_id": saved["attempt_id"],
        "kept_original": target["original_name"], "take": {"file": saved["relative"], "verdict": qa.get("verdict")},
        "target": "series",
    }


def _series_shot(library: dict, series_id: str, episode_id: str, shot_id: str):
    series = (library.get("seriesById") or {}).get(series_id)
    if not isinstance(series, dict):
        raise MediaToolError("shot_not_found", "Series was not found.", 404)
    episode = (series.get("episodesById") or {}).get(episode_id)
    if not isinstance(episode, dict):
        raise MediaToolError("shot_not_found", "Episode was not found.", 404)
    for index, shot in enumerate(episode.get("shots") or []):
        if isinstance(shot, dict) and shot.get("id") == shot_id:
            return series, episode, index, shot
    raise MediaToolError("shot_not_found", "Series shot was not found.", 404)
