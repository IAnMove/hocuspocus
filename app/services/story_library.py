"""Durable, atomic Story Lab library storage.

The browser keeps a local cache for fast startup, but the workspace copy is
the source of truth so stories survive browser-data cleanup and can be opened
from another browser profile.
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any


STORY_LIBRARY_FILENAME = ".story-library-v1.json"
MAX_STORY_PROJECTS = 250
MAX_STORY_LIBRARY_BYTES = 50 * 1024 * 1024


def empty_story_library() -> dict[str, Any]:
    return {"version": 2, "activeId": "", "projects": {}}


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
        projects[project_id] = project

    active_id = str(value.get("activeId") or "").strip()
    if active_id not in projects:
        active_id = next(iter(projects), "")
    return {
        "version": 2,
        "activeId": active_id,
        "projects": projects,
    }


def story_library_path(workspace_dir: str) -> str:
    return os.path.join(workspace_dir, STORY_LIBRARY_FILENAME)


def read_story_library(workspace_dir: str) -> dict[str, Any]:
    path = story_library_path(workspace_dir)
    if not os.path.isfile(path):
        return empty_story_library()
    with open(path, "r", encoding="utf-8") as handle:
        return normalize_story_library(json.load(handle))


def write_story_library(workspace_dir: str, value: Any) -> dict[str, Any]:
    library = normalize_story_library(value)
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
