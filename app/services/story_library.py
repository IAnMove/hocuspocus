"""Durable, atomic Story Lab library storage.

The browser keeps a local cache for fast startup, but the workspace copy is
the source of truth so stories survive browser-data cleanup and can be opened
from another browser profile.
"""

from __future__ import annotations

import json
import os
import threading
import uuid
from typing import Any

from .language_intent import normalize_language_intent


STORY_LIBRARY_FILENAME = ".story-library-v1.json"
MAX_STORY_PROJECTS = 250
MAX_STORY_LIBRARY_BYTES = 50 * 1024 * 1024
_STORY_LIBRARY_LOCK = threading.RLock()


class StoryLibraryRevisionConflict(ValueError):
    def __init__(self, expected: int, current: int):
        super().__init__(f"Story library revision conflict: expected {expected}, current {current}")
        self.expected = expected
        self.current = current


def empty_story_library() -> dict[str, Any]:
    return {"version": 2, "revision": 0, "activeId": "", "projects": {}}


def normalize_story_library(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Story library must be a JSON object")
    raw_projects = value.get("projects")
    if not isinstance(raw_projects, dict):
        raise ValueError("Story library projects must be an object")
    if len(raw_projects) > MAX_STORY_PROJECTS:
        raise ValueError(f"Story library is limited to {MAX_STORY_PROJECTS} projects")

    projects: dict[str, dict] = {}
    for key, raw_project in raw_projects.items():
        if not isinstance(raw_project, dict):
            raise ValueError("Every Story Lab project must be a JSON object")
        project_id = str(raw_project.get("id") or key).strip()
        if not project_id or len(project_id) > 200 or any(ord(char) < 32 for char in project_id):
            raise ValueError("Story Lab project has an invalid id")
        project = dict(raw_project)
        project["id"] = project_id
        project["languageIntent"] = normalize_language_intent(
            project.get("languageIntent"),
            content_language=str(project.get("language") or "Español"),
            spoken_language=str(project.get("spokenLanguage") or project.get("language") or "Español de España"),
        )
        projects[project_id] = project

    active_id = str(value.get("activeId") or "").strip()
    if active_id not in projects:
        active_id = next(iter(projects), "")
    revision = value.get("revision", 0)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
        raise ValueError("Story library revision must be a non-negative integer")
    return {
        "version": 2,
        "revision": revision,
        "activeId": active_id,
        "projects": projects,
    }


def story_library_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, STORY_LIBRARY_FILENAME)


def read_story_library(workspace_dir: str) -> dict[str, Any]:
    path = story_library_path(workspace_dir)
    with _STORY_LIBRARY_LOCK:
        if not os.path.isfile(path):
            return empty_story_library()
        with open(path, "r", encoding="utf-8") as handle:
            return normalize_story_library(json.load(handle))


def _base_revision(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("baseRevision must be a non-negative integer")
    return value


def write_story_library(
    workspace_dir: str,
    value: Any,
    *,
    base_revision: int,
) -> dict[str, Any]:
    expected_revision = _base_revision(base_revision)
    library = normalize_story_library(value)
    with _STORY_LIBRARY_LOCK:
        current = read_story_library(workspace_dir)
        current_revision = int(current["revision"])
        if expected_revision != current_revision:
            raise StoryLibraryRevisionConflict(expected_revision, current_revision)
        library["revision"] = current_revision + 1
        encoded = json.dumps(library, ensure_ascii=False, separators=(",", ":"))
        if len(encoded.encode("utf-8")) > MAX_STORY_LIBRARY_BYTES:
            raise ValueError("Story library is too large to save")

        os.makedirs(workspace_dir, exist_ok=True)
        path = story_library_path(workspace_dir)
        temporary = f"{path}.{uuid.uuid4().hex}.tmp"
        try:
            with open(temporary, "w", encoding="utf-8") as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        finally:
            try:
                if os.path.isfile(temporary):
                    os.remove(temporary)
            except OSError:
                pass
        return library


def patch_story_project(
    workspace_dir: str,
    project_id: str,
    project: Any,
    *,
    base_revision: int,
    make_active: bool = False,
) -> dict[str, Any]:
    """Upsert one Story without requiring clients to replace unrelated projects."""
    token = str(project_id or "").strip()
    if not token or not isinstance(project, dict):
        raise ValueError("Story project patch must include an id and project object")
    candidate = dict(project)
    candidate_id = str(candidate.get("id") or token).strip()
    if candidate_id != token:
        raise ValueError("Story project id does not match the request path")
    candidate["id"] = token
    with _STORY_LIBRARY_LOCK:
        current = read_story_library(workspace_dir)
        expected = _base_revision(base_revision)
        if expected != current["revision"]:
            raise StoryLibraryRevisionConflict(expected, int(current["revision"]))
        next_library = dict(current)
        next_library["projects"] = {**current["projects"], token: candidate}
        if make_active or not current.get("activeId"):
            next_library["activeId"] = token
        return write_story_library(workspace_dir, next_library, base_revision=expected)


def _story_id_token(value: Any) -> str:
    return str(value or "").strip()


def _index_by_id(items: list[Any], token: str) -> int:
    for index, item in enumerate(items):
        if isinstance(item, dict) and _story_id_token(item.get("id")) == token:
            return index
    return -1


def _require_music_row(project: dict[str, Any], cue_id: str, candidate_id: str) -> tuple[dict, list, int, list, int]:
    music = dict(project.get("music") or {})
    cues = list(music.get("cues") or [])
    cue_index = _index_by_id(cues, cue_id)
    if cue_index < 0:
        raise KeyError(cue_id)
    cue = dict(cues[cue_index])
    candidates = list(cue.get("candidates") or [])
    candidate_index = _index_by_id(candidates, candidate_id)
    if candidate_index < 0:
        raise KeyError(candidate_id)
    return music, cues, cue_index, candidates, candidate_index


def _apply_song_candidate_patch(
    candidate: dict[str, Any],
    *,
    project_id: str,
    cue_id: str,
    candidate_id: str,
    source: str,
    filename: str,
    status: str,
    duration_seconds: float | int | None,
    task_id: str | None,
    root_task_id: str | None,
    job_id: str | None,
) -> dict[str, Any]:
    patched = dict(candidate)
    patched["id"] = candidate_id
    patched["source"] = str(source or "")
    patched["name"] = str(filename or patched.get("name") or "")
    patched["status"] = status
    if duration_seconds is not None:
        patched["durationSeconds"] = duration_seconds
    if task_id:
        patched["taskId"] = task_id
    if root_task_id:
        patched["rootTaskId"] = root_task_id
    provenance = dict(patched.get("provenance") or {})
    provenance.update({
        "projectId": project_id,
        "cueId": cue_id,
        "candidateId": candidate_id,
    })
    if job_id:
        provenance["jobId"] = job_id
    if task_id:
        provenance["taskId"] = task_id
    if root_task_id:
        provenance["rootTaskId"] = root_task_id
    patched["provenance"] = provenance
    return patched


def attach_story_song_candidate(
    workspace_dir: str,
    *,
    project_id: str,
    cue_id: str,
    candidate_id: str,
    source: str,
    filename: str,
    status: str = "ready",
    base_revision: int,
    duration_seconds: float | int | None = None,
    task_id: str | None = None,
    root_task_id: str | None = None,
    job_id: str | None = None,
    update_selection: bool = True,
) -> dict[str, Any]:
    """CAS-patch one pending Story song row by project/cue/candidate IDs.

    Operates only on the library file inside ``workspace_dir``. A matching
    candidate in another folder is never visible here. ``update_selection``
    false leaves the user's current selection untouched.
    """
    token_project = _story_id_token(project_id)
    token_cue = _story_id_token(cue_id)
    token_candidate = _story_id_token(candidate_id)
    if not token_project or not token_cue or not token_candidate:
        raise ValueError("Story song attach requires project, cue and candidate IDs")
    if status not in {"pending", "ready", "failed"}:
        raise ValueError("Story song status must be pending, ready or failed")
    with _STORY_LIBRARY_LOCK:
        current = read_story_library(workspace_dir)
        expected = _base_revision(base_revision)
        if expected != current["revision"]:
            raise StoryLibraryRevisionConflict(expected, int(current["revision"]))
        project = current["projects"].get(token_project)
        if not isinstance(project, dict):
            raise KeyError(token_project)
        music, cues, cue_index, candidates, candidate_index = _require_music_row(
            project, token_cue, token_candidate,
        )
        cue = dict(cues[cue_index])
        candidates[candidate_index] = _apply_song_candidate_patch(
            dict(candidates[candidate_index]),
            project_id=token_project,
            cue_id=token_cue,
            candidate_id=token_candidate,
            source=source,
            filename=filename,
            status=status,
            duration_seconds=duration_seconds,
            task_id=task_id,
            root_task_id=root_task_id,
            job_id=job_id,
        )
        cue["candidates"] = candidates
        if update_selection:
            cue["selectedCandidateId"] = token_candidate
        cues[cue_index] = cue
        music["cues"] = cues
        if update_selection:
            music["selectedCandidateId"] = token_candidate
        next_project = dict(project)
        next_project["music"] = music
        return write_story_library(
            workspace_dir,
            {**current, "projects": {**current["projects"], token_project: next_project}},
            base_revision=expected,
        )


def delete_story_project(
    workspace_dir: str,
    project_id: str,
    *,
    base_revision: int,
) -> dict[str, Any]:
    """Delete one Story under the same monotonic compare-and-swap contract."""
    token = str(project_id or "").strip()
    with _STORY_LIBRARY_LOCK:
        current = read_story_library(workspace_dir)
        expected = _base_revision(base_revision)
        if expected != current["revision"]:
            raise StoryLibraryRevisionConflict(expected, int(current["revision"]))
        if token not in current["projects"]:
            raise KeyError(token)
        projects = dict(current["projects"])
        del projects[token]
        next_library = {
            **current,
            "projects": projects,
            "activeId": (
                current["activeId"]
                if current.get("activeId") in projects
                else next(iter(projects), "")
            ),
        }
        return write_story_library(workspace_dir, next_library, base_revision=expected)
