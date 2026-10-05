"""Video 3D shots with dialogue in the server render (``animation_3d`` + ``shot.scene3d``).

A talking character in a 3D set used to take seven tools per language by hand. A shot now says
where and who::

    shot.scene3d = {"template": "user-moon-base",             # or "scene": "<saved>.world3d.scene.json"
                    "cast": [{"characterId": "robot", "objectId": "robot", "poseId": "wave"}],
                    "objects": [{"objectId": "ship", "file": "ship.glb", "clip": "Fly", "add": True, "grounded": False,
                                 "position": [0, 2, -6], "motion": {"to": [4, 2, -6], "faceTravel": True}}],
                    "renderLook": "toon",                       # models drawn as cel anime with ink
                    "quality": "final"}

and the render records its lines like any 2D shot, instantiates the scene,
stretches the template's own effects to the shot's length, places the objects
(3D models with their animation clip, or image cutouts; ``add`` puts one the
template lacks), makes each cast object talk as its Character Kit cutout
(``world3d.scene.talk``, the line audio joins the soundtrack), publishes,
exports with ``scenes.world3d.export`` and imports the MP4 as the shot's take.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import struct
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

QUALITIES = ("draft", "final")
OBJECT_MEDIA = ("model3d", "image")
MAX_OBJECTS = 12
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
    return {**source, "cast": cast[:8], **_extras(value), "quality": value.get("quality") if value.get("quality") in QUALITIES else "draft"}


def _extras(value: dict[str, Any]) -> dict[str, Any]:
    """Objects when there are any, and ``retime: false`` only when the shot keeps the template's seconds."""
    extras: dict[str, Any] = {}
    objects = [entry for entry in (_object_entry(item) for item in value.get("objects") or []) if entry] \
        if isinstance(value.get("objects"), list) else []
    if objects:
        extras["objects"] = objects[:MAX_OBJECTS]
    if value.get("retime") is False:
        extras["retime"] = False
    extras.update(_look(value))
    return extras


def _look(value: dict[str, Any]) -> dict[str, Any]:
    """``renderLook`` (``toon`` draws the 3D models as cel anime with ink, ``n64``, ``none``) and its ``toon`` settings."""
    from services.world3d_look import RENDER_LOOKS, normalize_toon
    look: dict[str, Any] = {"renderLook": value["renderLook"]} if value.get("renderLook") in (*RENDER_LOOKS, "none") else {}
    try:
        toon = normalize_toon(value["toon"]) if "toon" in value else {}
    except ValueError:
        toon = {}
    return {**look, **({"toon": toon} if toon else {})}


def _valid_id(value: Any) -> bool:
    return isinstance(value, str) and bool(_ID.match(value))


def _cast_entry(entry: Any) -> dict[str, str] | None:
    if not isinstance(entry, dict) or not (_valid_id(entry.get("characterId")) and _valid_id(entry.get("objectId"))):
        return None
    return {"characterId": entry["characterId"], "objectId": entry["objectId"], **({"poseId": entry["poseId"]} if _valid_id(entry.get("poseId")) else {})}


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if type(value) in (int, float) and math.isfinite(value) and low <= value <= high else None


def _vec3(value: Any) -> list[float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return None
    numbers = [_number(item, -1000, 1000) for item in value]
    return None if None in numbers else numbers


def _file(value: Any) -> str | None:
    """A workspace-relative file: no absolute path, no parent segment."""
    if not isinstance(value, str) or not 0 < len(value) <= 240 or value.startswith(("/", "~")) or "\\" in value:
        return None
    return value if all(part not in ("", ".", "..") for part in value.split("/")) and not re.search(r"[?#:]", value) else None


def _clip(value: Any) -> str | dict[str, Any] | None:
    if isinstance(value, str) and 0 < len(value) <= 200:
        return value
    if isinstance(value, dict) and type(value.get("index")) is int and value["index"] >= 0 \
            and isinstance(value.get("name"), str) and 0 < len(value["name"]) <= 200:
        return {"index": value["index"], "name": value["name"]}
    return None


def _motion(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict) or _vec3(value.get("to")) is None:
        return None
    motion: dict[str, Any] = {"to": _vec3(value["to"])}
    if _vec3(value.get("via")) is not None:
        motion["via"] = _vec3(value["via"])
    points = [_vec3(item) for item in value.get("points") or []] if isinstance(value.get("points"), list) else []
    if points and None not in points:
        motion["points"] = points[:16]
    if isinstance(value.get("faceTravel"), bool):
        motion["faceTravel"] = value["faceTravel"]
    for key, low, high in (("turnTo", -100, 100), ("headingOffset", -6.3, 6.3)):
        if _number(value.get(key), low, high) is not None:
            motion[key] = _number(value[key], low, high)
    if value.get("easing") in ("linear", "smooth"):
        motion["easing"] = value["easing"]
    return motion


def _object_entry(entry: Any) -> dict[str, Any] | None:
    """A non-speaking object of the shot: a model (with its clip) or an image, on a template object or added."""
    if not isinstance(entry, dict) or not _valid_id(entry.get("objectId")):
        return None
    media = entry.get("media") or "model3d"
    if media not in OBJECT_MEDIA:
        return None
    result: dict[str, Any] = {"objectId": entry["objectId"], "media": media}
    if _file(entry.get("file")):
        result["file"] = entry["file"]
    if entry.get("add") is True:
        if "file" not in result:
            return None
        result["add"] = True
    if media == "model3d":
        result.update(_clip_fields(entry))
    checks = {"position": _vec3, "motion": _motion, "rotationY": lambda value: _number(value, -20, 20),
              "scale": lambda value: _number(value, 0.01, 100)}
    result.update({key: checked for key, check in checks.items() if (checked := check(entry.get(key))) is not None})
    if isinstance(entry.get("grounded"), bool):
        result["grounded"] = entry["grounded"]
    return result if len(result) > 2 else None


def _clip_fields(entry: dict[str, Any]) -> dict[str, Any]:
    fields: dict[str, Any] = {"clip": _clip(entry.get("clip"))} if _clip(entry.get("clip")) is not None else {}
    playback = entry.get("clipPlayback") if isinstance(entry.get("clipPlayback"), dict) else {}
    kept = {key: number for key, low, high in (("speed", 0.05, 8), ("start", 0, 600))
            if (number := _number(playback.get(key), low, high)) is not None}
    if isinstance(playback.get("loop"), bool):
        kept["loop"] = playback["loop"]
    return {**fields, **({"clipPlayback": kept} if kept else {})}


def glb_clip_names(path: Path) -> list[str]:
    """The animation names of a .glb (or .gltf), in the order the renderer indexes them."""
    try:
        with path.open("rb") as handle:
            if path.suffix.lower() == ".gltf":
                data = json.loads(handle.read(64 * 1024 * 1024))
            else:
                header = handle.read(20)
                if len(header) < 20 or header[:4] != b"glTF":
                    return []
                length, kind = struct.unpack("<I4s", header[12:20])
                if kind != b"JSON" or length > 64 * 1024 * 1024:
                    return []
                data = json.loads(handle.read(length))
    except (OSError, ValueError):
        return []
    return [str(item.get("name") or "") for item in data.get("animations") or [] if isinstance(item, dict)]


def _resolve_clip(root: str | None, entry: dict[str, Any], error: Callable[..., Exception]) -> dict[str, Any]:
    """A clip named by its name gets its index from the GLB, so a re-exported model does not silently play another clip."""
    clip = entry["clip"]
    if isinstance(clip, dict):
        return clip
    names = []
    if root and entry.get("file"):
        base = Path(root).resolve()
        path = (base / entry["file"]).resolve()
        if path.is_relative_to(base) and path.is_file():
            names = glb_clip_names(path)
    if clip not in names:
        raise error("unknown_clip", f"{entry['objectId']}: no clip {clip!r} in {entry.get('file') or 'its model'}"
                    f" (clips: {', '.join(names) or 'none'})", 400)
    return {"index": names.index(clip), "name": clip}


def _object_binding(workspace: str, root: str | None, entry: dict[str, Any], error: Callable[..., Exception]) -> dict[str, Any]:
    binding: dict[str, Any] = {"object_id": entry["objectId"], "media": entry["media"], **({"add": True} if entry.get("add") else {})}
    if entry.get("file"):
        binding["source_url"] = f"/api/v1/file/{quote(entry['file'])}?workspace={quote(workspace)}"
    if "clip" in entry:
        binding["clip"] = _resolve_clip(root, entry, error)
    for key in ("clipPlayback", "position", "rotationY", "scale", "motion", "grounded"):
        if key in entry:
            binding[key] = entry[key]
    return binding


def _shot_effects(screen_fx: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """The shot's screen effects under ``shot-`` ids, which the scene patch replaces on every render."""
    return [{**cue, "id": f"shot-{cue['id']}"} for cue in screen_fx or []]


def _setup(workspace: str, root: str | None, config: dict[str, Any], sound: list[dict[str, Any]],
           error: Callable[..., Exception], effects: list[dict[str, Any]]) -> dict[str, Any]:
    """What the length patch also sets: retiming, the look, the scene's sound, the screen effects and the objects."""
    setup: dict[str, Any] = {"retime": True} if config.get("retime", True) else {}
    setup.update({key: config[key] for key in ("renderLook", "toon") if key in config})
    if effects:
        setup["screenFx"] = effects
    if sound:
        setup["soundtrack"] = sound
    objects = [_object_binding(workspace, root, entry, error) for entry in config.get("objects") or []]
    if objects:
        setup["bindings"] = objects
    return setup


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
                kits: dict[str, Any], series_characters: dict[str, str], error: Callable[..., Exception],
                tracks: list[dict[str, Any]] | None = None, root: str | None = None,
                screen_fx: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Instantiate, set the length, sound and objects, make every cast object talk and publish; returns the published scene.

    ``tracks`` are the shot's ambience, stinger and music (``series_shot_plan.sound_tracks``); they join the scene
    soundtrack, where the page ducks them under the dialogue like it does in a 2D shot. ``root`` is the workspace
    folder, where a clip named by name is looked up in its model. ``screen_fx`` are the shot's timed screen effects
    (``series_shot_extras.fx_cues``), drawn over the 3D frame like over a 2D one.
    """
    config = normalize_scene3d(shot.get("scene3d")) or {}
    sound = [{"id": f"scene-{track['id']}", "audio": f"/api/v1/file/{quote(str(track['filename']))}?workspace={quote(workspace)}",
              "start": round(float(track.get("startTime") or 0), 3), "gain": round(max(0.0, min(1.0, float(track.get("volume", 1)))), 3)}
             for track in tracks or []]
    # Intents carry a digest of what was asked: a resumed job replays them, a changed take gets new ones.
    effects = _shot_effects(screen_fx)
    digest = hashlib.sha1(repr((config, round(duration, 3), [(line["filename"], line["start"]) for line in lines], sound, effects)).encode()).hexdigest()[:10]
    stem = f"{job_id}-{shot['id']}-{digest}"
    scene = _ok(call("world3d.scene.instantiate", {"version": 1, "intent_id": f"{stem}-new", "input": {
        "workspace": workspace, "template_id": _template(call, workspace, config, error)}}), "instantiate 3D scene", error)["scene"]
    scene_id = scene["sceneId"]
    revision = _ok(call("world3d.scene.patch", {"version": 1, "intent_id": f"{stem}-length", "input": {
        "workspace": workspace, "scene_id": scene_id, "base_revision": scene["revision"], "duration": round(duration, 3),
        **_setup(workspace, root, config, sound, error, effects)}}), "set 3D length", error)["scene"]["revision"]
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
