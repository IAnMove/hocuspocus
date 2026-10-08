"""A Video 3D shot's plan in the Video 3D editor and back (Series Lab's shot inspector).

``editor_scene`` builds the scene the server render would start from, before anyone talks: the shot's
template (or saved scene) instantiated with the shot's length, look, sound, screen effects and objects
(``series_shot3d.open_shot_scene``). The editor opens that document.

``from_editor`` takes the document the user saved there back to the shot. The whole edited scene is saved
as a Video 3D scene file and becomes the shot's ``scene3d.scene`` (so camera, lights and template objects
moved in the editor render as they are), and each of the shot's ``objects`` takes the editor's position,
rotation, scale, motion, clips, hold and appearance, since the render binds those over the scene again.
An object deleted in the editor leaves the shot's list; a cast member whose object is gone is refused.
The shot's own ``shot-*`` screen effects and ``scene-*`` sound are taken out of the saved scene: every
render lays the shot's current ones. The caller writes the new ``scene3d`` with the shot edit
(``series.shot.update``), which checks it and resets the shot's approvals.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from typing import Any
from urllib.parse import unquote, urlparse

from services import series_shot3d
from services.series_shot_extras import fx_cues
from services.series_shot_plan import sound_tracks
from services.series_stop_motion import read_fields

# What the render binds over the scene for each listed object (``series_shot3d._object_binding``).
OBJECT_FIELDS = ("position", "rotationY", "scale", "motion", "grounded", "clips", "hold", "appearance", "clipPlayback")
SHOT_FX_PREFIX, SCENE_TRACK_PREFIX = "shot-", "scene-"
_FILE_URL = re.compile(r"^/api/v1/file/(?P<name>[^?#]+)")


class Scene3DEditorError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _config(shot: dict[str, Any]) -> dict[str, Any]:
    config = series_shot3d.normalize_scene3d(shot.get("scene3d"))
    if shot.get("productionMethod") != "animation_3d" or not config:
        raise Scene3DEditorError("not_3d", f"Shot {shot.get('id')} is not a Video 3D shot with a template or a saved scene")
    return config


def _first_of_scene(episode: dict[str, Any], shot: dict[str, Any]) -> bool:
    ordered = sorted(episode.get("shots") or [], key=lambda value: value.get("order", 0))
    position = next((index for index, value in enumerate(ordered) if value.get("id") == shot.get("id")), 0)
    return position == 0 or ordered[position - 1].get("sceneId") != shot.get("sceneId")


def editor_scene(call: Callable[[str, dict], dict], workspace: str, root: str | None, series: dict[str, Any],
                 episode: dict[str, Any], shot: dict[str, Any]) -> dict[str, Any]:
    """The shot's working scene to open in the Video 3D editor: ``sceneId``, ``revision``, ``document``."""
    config = _config(shot)
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    duration = float(shot.get("durationSeconds") or 5)
    sound = series_shot3d.scene_sound(workspace, sound_tracks(series, shot, _first_of_scene(episode, shot)))
    # Effects on a line start at its second without the recording: the line timing is the render's.
    effects = series_shot3d.shot_effects(fx_cues(layout, [], duration))
    # The scene's patch carries the shot's stop-motion: a changed one is another scene (the digest stays as it was without).
    held = read_fields(shot)
    asked = [config, duration, sound, effects, *([held] if held else [])]
    digest = hashlib.sha1(json.dumps(asked, sort_keys=True, default=str).encode()).hexdigest()[:10]
    stem = f"editor-{episode.get('id')}-{shot['id']}-{digest}"[:140]
    scene = series_shot3d.open_shot_scene(call, workspace, stem, shot, duration, _tool_error, root=root, sound=sound, effects=effects)
    return {"sceneId": scene.get("sceneId"), "revision": scene.get("revision"), "document": scene.get("document"),
            "source": {key: config[key] for key in ("template", "scene") if key in config}, "duration": duration}


def _tool_error(code: str, message: str, status: int = 502) -> Scene3DEditorError:
    return Scene3DEditorError(code, message, status)


def workspace_file(url: Any) -> str | None:
    """The workspace file a ``/api/v1/file/<name>?workspace=`` URL names."""
    match = _FILE_URL.match(urlparse(url).path) if isinstance(url, str) else None
    return unquote(match.group("name")) if match else None


def _refreshed(entry: dict[str, Any], slot: dict[str, Any]) -> dict[str, Any]:
    """The shot's object with what the editor shows for it (a field the editor dropped is dropped)."""
    updated = {key: value for key, value in entry.items() if key not in OBJECT_FIELDS and key != "clip"}
    for key in OBJECT_FIELDS:
        if slot.get(key) is not None:
            updated[key] = copy.deepcopy(slot[key])
    if "clips" not in updated and slot.get("clip") is not None:
        updated["clip"] = copy.deepcopy(slot["clip"])
    file = workspace_file(slot.get("sourceUrl"))
    if file and entry.get("file"):
        updated["file"] = file
    return updated


def _without_shot_extras(document: dict[str, Any]) -> dict[str, Any]:
    """The scene without what each render lays from the shot: its screen effects and its own sound."""
    saved = copy.deepcopy(document)
    saved["sfx"] = [cue for cue in saved.get("sfx") or [] if not str((cue or {}).get("id", "")).startswith(SHOT_FX_PREFIX)]
    saved["soundtrack"] = [track for track in saved.get("soundtrack") or []
                           if not str((track or {}).get("id", "")).startswith(SCENE_TRACK_PREFIX)]
    return saved


def _slots(document: Any) -> dict[str, dict[str, Any]]:
    slots = (document or {}).get("slots") if isinstance(document, dict) else None
    found = {slot.get("id"): slot for slot in slots or [] if isinstance(slot, dict)}
    if not found:
        raise Scene3DEditorError("invalid_document", "The editor sent no Video 3D scene (no objects)")
    return found


def _refreshed_objects(config: dict[str, Any], slots: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    """The shot's objects with the editor's values, and those the editor deleted."""
    objects = [_refreshed(entry, slots[entry["objectId"]]) for entry in config.get("objects") or [] if entry["objectId"] in slots]
    removed = [entry["objectId"] for entry in config.get("objects") or [] if entry["objectId"] not in slots]
    return objects, removed


def _editor_look(plan: dict[str, Any], document: dict[str, Any]) -> None:
    if document.get("renderLook") or plan.get("renderLook"):
        # A look the editor took off is "none", or the render would put the shot's back on.
        plan["renderLook"] = document.get("renderLook") or "none"
    if isinstance(document.get("toon"), dict):
        plan["toon"] = copy.deepcopy(document["toon"])


def plan_from_editor(shot: dict[str, Any], document: Any) -> tuple[dict[str, Any], list[str]]:
    """The shot's ``scene3d`` with its objects refreshed from the editor's document (no file saved yet), and the
    objects the editor no longer has."""
    config = _config(shot)
    slots = _slots(document)
    gone = [entry for entry in config.get("cast") or [] if entry["objectId"] not in slots]
    if gone:
        raise Scene3DEditorError("cast_object_missing", "; ".join(
            f"{entry['characterId']} speaks through object {entry['objectId']}, which the scene no longer has" for entry in gone))
    objects, removed = _refreshed_objects(config, slots)
    plan = {key: copy.deepcopy(value) for key, value in config.items() if key not in ("template", "scene", "objects")}
    if objects:
        plan["objects"] = objects
    _editor_look(plan, document)
    return plan, removed


def from_editor(call: Callable[[str, dict], dict], workspace: str, series_id: str, episode_id: str, shot: dict[str, Any],
                document: Any) -> dict[str, Any]:
    """Save the edited scene and return the shot's new ``scene3d`` (``scene`` + refreshed objects) to write."""
    plan, removed = plan_from_editor(shot, document)
    name = f"{series_id}-{episode_id}-{shot['id']}-plan"[:110]
    saved = call("scenes.document.save", {"version": 1, "input": {"workspace": workspace, "name": name,
                                                                   "document": _without_shot_extras(document)}})
    if saved.get("_is_error"):
        raise Scene3DEditorError("save_failed", f"Saving the scene: {(saved.get('error') or {}).get('message')}"[:400], 422)
    file = ((saved.get("result") or saved).get("name"))
    scene3d = series_shot3d.normalize_scene3d({"scene": file, **plan})
    if not scene3d:
        raise Scene3DEditorError("save_failed", f"The saved scene {file} is not a Video 3D scene file", 422)
    return {"scene3d": scene3d, "file": file, "removedObjects": removed}


__all__ = ["OBJECT_FIELDS", "Scene3DEditorError", "editor_scene", "from_editor", "plan_from_editor", "workspace_file"]
