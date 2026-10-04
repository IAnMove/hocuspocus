"""Video 3D shots with dialogue in the server render (``animation_3d`` + ``shot.scene3d``).

A talking character in a 3D set used to take seven tools per language by hand. A shot now says
where and who::

    shot.scene3d = {"template": "user-moon-base",             # or "scene": "<saved>.world3d.scene.json"
                    "cast": [{"characterId": "robot", "objectId": "robot", "poseId": "wave"}],
                    "quality": "final"}

and the render records its lines like any 2D shot, instantiates the scene,
makes each cast object talk as its Character Kit cutout (``world3d.scene.talk``,
the line audio joins the soundtrack), publishes, exports with
``scenes.world3d.export`` and imports the MP4 as the shot's take.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Callable
from urllib.parse import quote

QUALITIES = ("draft", "final")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")
_SCENE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,200}\.scene\.json$")


def normalize_scene3d(value: Any) -> dict[str, Any] | None:
    """Exactly one of template or scene, and a cast of characters bound to scene objects."""
    if not isinstance(value, dict):
        return None
    source = {key: value[key] for key in ("template", "scene") if isinstance(value.get(key), str)
              and (_ID if key == "template" else _SCENE).match(value[key])}
    if len(source) != 1:
        return None
    cast = [entry for entry in (_cast_entry(item) for item in value.get("cast") or []) if entry]
    return {**source, "cast": cast[:8], "quality": value.get("quality") if value.get("quality") in QUALITIES else "draft"}


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.match(value))


def _cast_entry(entry: Any) -> dict[str, str] | None:
    if not isinstance(entry, dict) or not (_valid_id(entry.get("characterId")) and _valid_id(entry.get("objectId"))):
        return None
    return {"characterId": entry["characterId"], "objectId": entry["objectId"], **({"poseId": entry["poseId"]} if _valid_id(entry.get("poseId")) else {})}


def wants_render(shot: dict[str, Any]) -> bool:
    """A shot the server render makes: every 2D shot, and 3D shots that say their scene."""
    method = shot.get("productionMethod")
    return method == "animation_2d" or (method == "animation_3d" and normalize_scene3d(shot.get("scene3d")) is not None)


def _ok(result: dict, label: str, error: Callable[..., Exception]) -> dict:
    if not isinstance(result, dict) or result.get("_is_error"):
        detail = (result or {}).get("error") if isinstance(result, dict) else None
        raise error("tool_failed", f"{label}: {(detail or {}).get('message') if isinstance(detail, dict) else result}"[:400], 502)
    return result.get("result") if isinstance(result.get("result"), dict) else result


def _template(call: Callable, workspace: str, config: dict[str, Any], error: Callable[..., Exception]) -> str:
    """A saved scene becomes a personal template once (same file, same id), so the shot instantiates a fresh copy."""
    if "template" in config:
        return config["template"]
    document = _ok(call("scenes.document.get", {"version": 1, "input": {"workspace": workspace, "file": config["scene"]}}), "read 3D scene", error)
    stem = config["scene"][: -len(".scene.json")]
    template_id = f"user-{hashlib.sha1(stem.encode()).hexdigest()[:12]}"
    _ok(call("world3d.templates.user.put", {"version": 1, "intent_id": f"tpl-{template_id}", "input": {
        "workspace": workspace, "id": template_id, "title": stem[:80], "document": document["document"]}}), "register 3D scene", error)
    return template_id


def _talk(call: Callable, workspace: str, stem: str, scene_id: str, revision: int, entry: dict[str, str], kit_id: str,
          spoken: list[dict[str, Any]], error: Callable[..., Exception]) -> int:
    """One cast object speaks its lines as its Character Kit; returns the new scene revision."""
    payload = [{"start": line["start"], "cues": line.get("cues") or [], "audio": f"/api/v1/file/{quote(line['filename'])}?workspace={quote(workspace)}"}
               for line in spoken]
    # A template's subject may be a 3D marker: a talking cutout is an image object.
    revision = _ok(call("world3d.scene.patch", {"version": 1, "intent_id": f"{stem}-image-{entry['objectId']}", "input": {
        "workspace": workspace, "scene_id": scene_id, "base_revision": revision,
        "bindings": [{"object_id": entry["objectId"], "media": "image"}]}}), f"prepare {entry['objectId']}", error)["scene"]["revision"]
    talked = _ok(call("world3d.scene.talk", {"version": 1, "intent_id": f"{stem}-talk-{entry['objectId']}", "input": {
        "workspace": workspace, "scene_id": scene_id, "base_revision": revision, "object_id": entry["objectId"], "kit_id": kit_id,
        "pose": entry.get("poseId") or "base", "lines": payload}}), f"make {entry['characterId']} talk", error)
    return talked["scene"]["revision"]


def build_scene(call: Callable, workspace: str, job_id: str, shot: dict[str, Any], lines: list[dict[str, Any]], duration: float,
                kits: dict[str, Any], series_characters: dict[str, str], error: Callable[..., Exception]) -> dict[str, Any]:
    """Instantiate, set the length, make every cast object talk and publish; returns the published scene."""
    config = normalize_scene3d(shot.get("scene3d")) or {}
    # Intents carry a digest of what was asked: a resumed job replays them, a changed take gets new ones.
    digest = hashlib.sha1(repr((config, round(duration, 3), [(line["filename"], line["start"]) for line in lines])).encode()).hexdigest()[:10]
    stem = f"{job_id}-{shot['id']}-{digest}"
    scene = _ok(call("world3d.scene.instantiate", {"version": 1, "intent_id": f"{stem}-new", "input": {
        "workspace": workspace, "template_id": _template(call, workspace, config, error)}}), "instantiate 3D scene", error)["scene"]
    scene_id = scene["sceneId"]
    revision = _ok(call("world3d.scene.patch", {"version": 1, "intent_id": f"{stem}-length", "input": {
        "workspace": workspace, "scene_id": scene_id, "base_revision": scene["revision"], "duration": round(duration, 3)}}),
        "set 3D length", error)["scene"]["revision"]
    for entry in config.get("cast") or []:
        spoken = [line for line in lines if line["characterId"] == entry["characterId"]]
        kit_id = series_characters.get(entry["characterId"])
        if spoken and kit_id:
            revision = _talk(call, workspace, stem, scene_id, revision, entry, kit_id, spoken, error)
    unbound = {line["characterId"] for line in lines} - {entry["characterId"] for entry in config.get("cast") or []}
    if unbound:
        raise error("unbound_speaker", f"{', '.join(sorted(unbound))} speak in {shot['id']} but have no object in scene3d.cast", 400)
    return _ok(call("world3d.scene.publish", {"version": 1, "intent_id": f"{stem}-publish-{revision}", "input": {
        "workspace": workspace, "scene_id": scene_id}}), "publish 3D scene", error)["scene"]
