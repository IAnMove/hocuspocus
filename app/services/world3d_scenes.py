"""Editable Video 3D scenes addressed by object id.

The working copy lives under the workspace. Publishing uses the same gallery
save as the editor, so export reads that document rather than a second library.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from services import world3d_slot_fields as slot_fields
from services.agent_activity import actor_label
from services.readable_names import ascii_slug
from services.character_kit_library import read_character_kit_library
from services.scene_documents import get_document, save_document
from services.world3d_look import check_render_look, normalize_toon
from services.world3d_template_catalog import require_card, user_template_document

_ROOT = Path(__file__).resolve().parents[2]
_EDITS = "world3d-edits"
_COMPILED: dict[str, dict] = {}
_SLOT_FIELDS = {"sourceUrl", "sourceRef", "clip", "clipPlayback", "position", "rotationY", "scale", "motion", "grounded", "media"}
_MAX_SLOTS = 24
_ADDED_MEDIA = ("model3d", "image")
_SCREEN_SOURCE_FIELDS = {"sourceUrl", "sourceRef"}
_CAMERA_FIELDS = {"family", "fov", "eye", "look", "orbitRadius", "orbitHeight", "orbitTurns", "framing", "eyeOffset", "targetOffset", "frameFormat",
                  "shake"}
# Same bounds as ui/src/features/scene3d/cameraShake.ts; the editor rejects a document outside them.
_SHAKE_RANGES = {"start": (0, 600), "end": (0, 600), "amplitude": (0, 2), "frequency": (0, 60), "decay": (0, 60), "seed": (0, 1_000_000)}
_SHAKE_REQUIRED = {"start", "end", "amplitude", "frequency"}
_SHAKE_WINDOWS = 16


class World3DSceneError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


def instantiate_template(workspace: str, template_id: str, workspace_dir) -> dict:
    card = require_card(template_id, workspace_dir=workspace_dir, workspace=workspace)
    document = user_template_document(template_id, workspace_dir, workspace) if card.get("source") == "workspace" else compile_template_document(template_id)
    scene_id = "w3d-" + uuid.uuid4().hex[:12]
    record = {"revision": 1, "templateId": document.get("templateId") or template_id, "document": document, "warnings": []}
    _write(workspace, scene_id, record, workspace_dir)
    return _view(scene_id, record)


def inspect_scene(workspace: str, scene_id: str, workspace_dir) -> dict:
    return _view(scene_id, _read(workspace, scene_id, workspace_dir))


SCENE_TRACK_PREFIX = "scene-"


def _set_soundtrack(document: dict, tracks, workspace: str) -> None:
    """Replace the scene's own tracks (``scene-*``: ambience, stinger, music); talk tracks and others stay."""
    from services.world3d_talk import TalkError, _audio
    if not isinstance(tracks, list) or len(tracks) > 32:
        raise World3DSceneError("invalid_soundtrack", "soundtrack must be a list of at most 32 tracks")
    kept = [track for track in document.get("soundtrack") or [] if not str(track.get("id", "")).startswith(SCENE_TRACK_PREFIX)]
    added = []
    for index, track in enumerate(tracks):
        if not isinstance(track, dict) or not isinstance(track.get("id"), str) or not track["id"].startswith(SCENE_TRACK_PREFIX):
            raise World3DSceneError("invalid_soundtrack", f"soundtrack[{index}] needs an id starting with {SCENE_TRACK_PREFIX}")
        try:
            audio = _audio(track, index, workspace)
        except TalkError as error:
            raise World3DSceneError("invalid_soundtrack", str(error)) from error
        if audio is None:
            raise World3DSceneError("invalid_soundtrack", f"soundtrack[{index}] needs an audio URL")
        start, gain = track.get("start", 0), track.get("gain", 1)
        if type(start) not in (int, float) or not 0 <= start <= 600 or type(gain) not in (int, float) or not 0 <= gain <= 1:
            raise World3DSceneError("invalid_soundtrack", f"soundtrack[{index}] start must be 0-600 and gain 0-1")
        added.append({"id": track["id"][:120], "audio": audio, "start": round(float(start), 3), "offset": 0, "gain": round(float(gain), 3)})
    if len(kept) + len(added) > 32:
        raise World3DSceneError("too_many_tracks", "A Video 3D scene holds at most 32 soundtrack tracks")
    document["soundtrack"] = kept + added


SHOT_FX_PREFIX = "shot-"
_SCREEN_FX_NUMBERS = {"start": (0, 600), "end": (0, 600), "x": (0, 100), "y": (0, 100), "size": (1, 200), "intensity": (0.1, 2),
                      "volume": (0, 1), "rotation": (-180, 180)}


def _screen_fx_kinds(aimed: bool = False) -> frozenset:
    """The screen effect kinds, or with ``aimed`` the beams a cue can start at ``from`` (laser, lightning)."""
    catalog = json.loads((_ROOT / "app/shared/scene_effects.json").read_text(encoding="utf-8"))
    return frozenset(item["id"] for item in catalog if not aimed or item.get("aim"))


def _set_screen_fx(document: dict, cues) -> None:
    """Replace the caller's screen effects (``shot-*``: speed lines, manga impact, a flash) and keep the template's own."""
    if not isinstance(cues, list) or len(cues) > 32:
        raise World3DSceneError("invalid_screen_fx", "screenFx must be a list of at most 32 effects")
    kinds = _screen_fx_kinds()
    added = [_screen_fx_entry(index, cue, kinds) for index, cue in enumerate(cues)]
    kept = [cue for cue in document.get("sfx") or [] if not str(cue.get("id", "")).startswith(SHOT_FX_PREFIX)]
    if len(kept) + len(added) > 64:
        raise World3DSceneError("too_many_screen_fx", "A Video 3D scene holds at most 64 screen effects")
    document["sfx"] = kept + added


def _screen_fx_entry(index: int, cue, kinds: frozenset) -> dict:
    def refuse(message: str):
        return World3DSceneError("invalid_screen_fx", f"screenFx[{index}] {message}")
    if not isinstance(cue, dict) or not str(cue.get("id", "")).startswith(SHOT_FX_PREFIX) or cue.get("kind") not in kinds:
        raise refuse(f"needs an id starting with {SHOT_FX_PREFIX} and a known kind")
    entry = {"id": cue["id"][:120], "kind": cue["kind"]}
    for key, (low, high) in _SCREEN_FX_NUMBERS.items():
        value = cue.get(key)
        if value is not None and (type(value) not in (int, float) or not low <= value <= high):
            raise refuse(f".{key} must be {low}-{high}")
        if value is not None:
            entry[key] = round(float(value), 3)
    if "start" not in entry or "end" not in entry or entry["end"] <= entry["start"]:
        raise refuse("needs start < end")
    if isinstance(cue.get("color"), str) and len(cue["color"]) == 7 and cue["color"].startswith("#"):
        entry["color"] = cue["color"]
    if isinstance(cue.get("sound"), bool):
        entry["sound"] = cue["sound"]
    if cue.get("from") is not None:
        entry["from"] = _screen_fx_origin(cue, refuse)
    return entry


def _screen_fx_origin(cue: dict, refuse) -> dict:
    """A beam's (laser, lightning) ``from``: a point of the frame it runs from to the cue's x/y."""
    origin = cue["from"]
    if cue["kind"] not in _screen_fx_kinds(aimed=True):
        raise refuse(".from starts a beam: use it on a laser or lightning")
    if not isinstance(origin, dict) or any(type(origin.get(key)) not in (int, float) or not -50 <= origin[key] <= 150 for key in ("x", "y")):
        raise refuse(".from must be {x, y}, each -50-150 (% of the frame)")
    return {"x": round(float(origin["x"]), 3), "y": round(float(origin["y"]), 3)}


VOICE_OVER_PREFIX = "talk-voiceover-"


def _set_voice_over(document: dict, lines, workspace: str) -> None:
    """Speech with no talking object (a narrator, a voice on the radio): it ducks the music like a talking cutout."""
    from services.world3d_talk import TalkError, _replace_tracks
    if not isinstance(lines, list) or len(lines) > 24 or any(not isinstance(line, dict) for line in lines):
        raise World3DSceneError("invalid_voice_over", "voiceOver must be a list of at most 24 lines {audio, start, gain}")
    try:
        _replace_tracks(document, VOICE_OVER_PREFIX, lines, workspace)
    except TalkError as error:
        raise World3DSceneError(error.code, str(error), error.status) from error


def patch_scene(workspace: str, scene_id: str, workspace_dir, changes: dict, base_revision: int) -> dict:
    record = _read(workspace, scene_id, workspace_dir)
    if type(base_revision) is not int or base_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "The scene changed since this revision. Reload before editing.", 409)
    document = record["document"]
    warnings = []
    _set_duration(document, changes)
    bindings = _bindings(changes)
    for binding in bindings:
        warnings.extend(_bind(document, binding))
    _check_carriers(document["slots"], bindings)
    if isinstance(changes.get("camera"), dict):
        if "shake" in changes["camera"]:
            _check_shake(changes["camera"]["shake"])
        document["camera"] = {**document["camera"], **{key: deepcopy(value) for key, value in changes["camera"].items() if key in _CAMERA_FIELDS}}
    if "playbackSpeed" in changes or "playback_speed" in changes:
        document["playbackSpeed"] = _speed(changes.get("playbackSpeed", changes.get("playback_speed")))
    if "soundtrack" in changes:
        _set_soundtrack(document, changes["soundtrack"], workspace)
    if "screenFx" in changes:
        _set_screen_fx(document, changes["screenFx"])
    if "voiceOver" in changes:
        _set_voice_over(document, changes["voiceOver"], workspace)
    _set_render_look(document, changes)
    _retarget(document)
    record["revision"] += 1
    record["warnings"] = warnings
    record["templateId"] = document.get("templateId") or record["templateId"]
    _write(workspace, scene_id, record, workspace_dir)
    viewed = _view(scene_id, record)
    viewed["warnings"] = warnings
    return viewed


def _number_in(value, low: float, high: float) -> bool:
    return type(value) in (int, float) and low <= value <= high


def _valid_shake_window(window) -> bool:
    if not isinstance(window, dict) or not _SHAKE_REQUIRED <= set(window) or set(window) - set(_SHAKE_RANGES):
        return False
    if not all(_number_in(window[key], *_SHAKE_RANGES[key]) for key in window):
        return False
    if "seed" in window and type(window["seed"]) is not int:
        return False
    return window["end"] > window["start"] and window["amplitude"] > 0 and window["frequency"] > 0


def _check_shake(shake) -> None:
    """``camera.shake``: at most 16 windows ``{start, end, amplitude, frequency, seed?, decay?}`` in scene seconds."""
    if not isinstance(shake, list) or len(shake) > _SHAKE_WINDOWS:
        raise World3DSceneError("invalid_camera_shake", f"camera.shake must be a list of at most {_SHAKE_WINDOWS} windows")
    for index, window in enumerate(shake):
        if not _valid_shake_window(window):
            raise World3DSceneError("invalid_camera_shake", f"camera.shake[{index}] needs start < end within 0-600 s, amplitude 0-2 m, "
                                    "frequency 0-60 Hz, and optional integer seed and decay 0-60")


def talk_scene(workspace: str, scene_id: str, workspace_dir, changes: dict, base_revision: int) -> dict:
    """Make an image object talk with a Character Kit: pose, mouths by cue, blink, and each line's audio."""
    from services.world3d_talk import TalkError, apply_talk
    record = _read(workspace, scene_id, workspace_dir)
    if type(base_revision) is not int or base_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "The scene changed since this revision. Reload before editing.", 409)
    kit_id = changes.get("kit_id")
    kit = (read_character_kit_library(str(workspace_dir(workspace))).get("kits") or {}).get(kit_id) if isinstance(kit_id, str) else None
    if kit is None:
        raise World3DSceneError("unknown_kit", f"unknown_kit:{kit_id}", 404)
    document = record["document"]
    slot = _target(document["slots"], changes)
    try:
        talked = apply_talk(document, slot, kit, changes.get("lines") or [], workspace=workspace,
                            pose=str(changes.get("pose") or "base"), blink=changes.get("blink") is not False)
    except TalkError as error:
        raise World3DSceneError(error.code, str(error), error.status) from error
    record["revision"] += 1
    record["warnings"] = []
    _write(workspace, scene_id, record, workspace_dir)
    viewed = _view(scene_id, record)
    viewed["talk"] = {key: value for key, value in talked.items() if key != "talk"}
    return viewed


def preview_scene(workspace: str, scene_id: str, workspace_dir, *, times=None, expected_revision: int | None = None) -> dict:
    record = _read(workspace, scene_id, workspace_dir)
    if expected_revision is not None and expected_revision != record["revision"]:
        raise World3DSceneError("revision_conflict", "Preview revision does not match the scene.", 409)
    rendered = _run_tool("preview", json.dumps({"document": record["document"], "times": times}))
    frames = rendered.get("frames") or []
    return {
        "sceneId": scene_id, "revision": record["revision"], "templateId": record["templateId"],
        "times": [frame.get("time") for frame in frames], "frames": frames,
        "pending": rendered.get("pending") or _pending(record["document"]),
        "loadErrors": rendered.get("loadErrors") or [],
        "images": [{"mimeType": "image/png", "data": frame.get("png")} for frame in frames if frame.get("png")],
    }


def _template_title(template_id: str, workspace: str, workspace_dir) -> str:
    try:
        card = require_card(template_id, workspace_dir=workspace_dir, workspace=workspace)
    except Exception:  # noqa: BLE001 - a scene whose template is gone keeps its id as the name
        return template_id
    return str(card.get("titleEn") or card.get("title") or card.get("titleEs") or template_id)


def published_name(workspace: str, scene_id: str, record: dict, workspace_dir) -> str:
    """``Anime face-off w3d-0123456789ab``: the template's title, then the scene id that ties it to its working copy."""
    title = ascii_slug(_template_title(str(record.get("templateId") or ""), workspace, workspace_dir), 60)
    return f"{title}-{scene_id}" if title else scene_id


def publish_scene(workspace: str, scene_id: str, workspace_dir) -> dict:
    record = _read(workspace, scene_id, workspace_dir)
    saved = save_document(workspace, record["document"], name=published_name(workspace, scene_id, record, workspace_dir),
                          preview=None, workspace_dir=workspace_dir)
    opened = get_document(workspace, saved["name"], workspace_dir=workspace_dir)
    traits = _traits(opened["document"])
    # The working copy remembers what it was published as (the editor's Open dialog lists the unpublished ones).
    record["published"] = {"file": saved["name"], "revision": record["revision"]}
    _write(workspace, scene_id, record, workspace_dir)
    return {"sceneId": scene_id, "revision": record["revision"], "file": saved["name"], "url": saved.get("url"),
            "editor": opened.get("editor"), "document": opened["document"], "traits": traits}


def working_scenes(workspace: str, workspace_dir, *, unpublished_only: bool = True) -> list[dict]:
    """The working Video 3D scenes (``world3d-edits/w3d-*.json``) an agent instantiated or patched, newest first.

    A scene counts as published at its current revision when ``world3d.scene.publish`` recorded that revision, or,
    for scenes published before it recorded anything, when a ``w3d-…-<uuid>.world3d.scene.json`` file of it exists."""
    root = Path(workspace_dir(workspace))
    legacy = {name.split("-", 2)[0] + "-" + name.split("-", 2)[1] for name in os.listdir(root)
              if name.startswith("w3d-") and name.endswith(".world3d.scene.json")} if root.is_dir() else set()
    rows = []
    for path in (root / _EDITS).glob("w3d-*.json") if (root / _EDITS).is_dir() else []:
        scene_id = path.stem
        try:
            record = _read(workspace, scene_id, workspace_dir)
            changed = path.stat().st_mtime
        except (World3DSceneError, OSError):
            continue
        published = record.get("published") if isinstance(record.get("published"), dict) else None
        current = (published or {}).get("revision") == record.get("revision") or (published is None and scene_id in legacy)
        if unpublished_only and current:
            continue
        document = record["document"]
        rows.append({"sceneId": scene_id, "revision": record.get("revision"), "templateId": record.get("templateId"),
                     "title": _template_title(str(record.get("templateId") or ""), workspace, workspace_dir),
                     "updatedAt": changed, "published": published, "duration": document.get("duration"),
                     "width": document.get("width"), "height": document.get("height"),
                     "slots": len(document.get("slots") or []), "pending": len(_pending(document))})
    return sorted(rows, key=lambda row: -row["updatedAt"])


def _check_user_template(template_id, title, document) -> None:
    if not isinstance(template_id, str) or not template_id.startswith("user-"):
        raise World3DSceneError("invalid_user_template", "Personal template ids start with user-")
    if template_id in {card["id"] for card in require_builtin_ids()}:
        raise World3DSceneError("invalid_user_template", "A personal id cannot replace a built-in template")
    if not isinstance(title, str) or not title.strip():
        raise World3DSceneError("invalid_user_template", "A personal template needs a title")
    if not isinstance(document, dict) or not isinstance(document.get("slots"), list):
        raise World3DSceneError("invalid_user_template", "A personal template needs a Video 3D document")


def _stamp(previous: dict) -> dict:
    """When and by whom (agent, wizard or user) a personal template was saved; a later save keeps the creation."""
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return {"createdAt": previous.get("createdAt") or now, "updatedAt": now, "createdBy": previous.get("createdBy") or actor_label()}


def put_user_template(workspace: str, workspace_dir, row: dict) -> dict:
    template_id = row.get("id")
    title = row.get("title")
    document = row.get("document")
    _check_user_template(template_id, title, document)
    path = Path(workspace_dir(workspace))
    path.mkdir(parents=True, exist_ok=True)
    target = path / "world3d-user-templates.json"
    current = {"templates": []}
    if target.is_file():
        current = json.loads(target.read_text(encoding="utf-8"))
    previous = next((item for item in current.get("templates") or [] if isinstance(item, dict) and item.get("id") == template_id), {})
    rows = [item for item in current.get("templates") or [] if not (isinstance(item, dict) and item.get("id") == template_id)]
    stored = {"id": template_id, "title": title.strip()[:80], "description": str(row.get("description") or "")[:240],
              "document": document, **_stamp(previous)}
    rows.append(stored)
    _atomic(target, {"version": 1, "templates": rows})
    return {"id": template_id, "source": "workspace", "title": stored["title"]}


def compile_template_document(template_id: str) -> dict:
    cached = _COMPILED.get(template_id)
    if cached is not None:
        return deepcopy(cached)
    require_card(template_id)
    try:
        document = _run_tool("document", None, template_id)
    except World3DSceneError as error:
        if "unknown_template:" in str(error):
            raise World3DSceneError("unknown_template", f"unknown_template:{template_id}", 404) from error
        raise
    _COMPILED[template_id] = document
    return deepcopy(document)


def require_builtin_ids() -> list[dict]:
    from services.world3d_template_catalog import builtin_cards
    return list(builtin_cards())


def _bindings(changes: dict) -> list[dict]:
    bindings = changes.get("bindings") or []
    if not isinstance(bindings, list) or any(not isinstance(item, dict) for item in bindings):
        raise World3DSceneError("invalid_patch", "bindings must be a list of objects")
    return bindings


def _bind(document: dict, binding: dict) -> list[str]:
    if binding.get("add") is True:
        _add_slot(document, binding)
    slot = _target(document["slots"], binding)
    warnings = _clip_warning(slot, binding)
    for key in _SLOT_FIELDS:
        snake = _snake(key)
        if key in binding:
            slot[key] = deepcopy(binding[key])
        elif snake in binding:
            slot[key] = deepcopy(binding[snake])
    _bind_screen(slot, binding)
    _bind_checked(slot, binding)
    return warnings


_CHECKED_FIELDS = ("clips", "hold", "appearance")
_NOT_HOLDABLE_SURFACES = ("floor", "wall", "environment")


def _bind_checked(slot: dict, binding: dict) -> None:
    """A clip sequence, a hand hold and an appearance are checked before they are stored; ``null`` removes one."""
    for key in _CHECKED_FIELDS:
        if key not in binding or (key == "clips" and _clip_names(binding) is not None):
            continue
        if binding[key] is None:
            slot.pop(key, None)
            continue
        try:
            slot[key] = _checked(key, binding[key], slot)
        except ValueError as error:
            raise World3DSceneError(f"invalid_{key}", f"{slot.get('id')}: {error}") from error


def _checked(key: str, value, slot: dict):
    media = slot.get("media") or "model3d"
    if key == "clips":
        if media != "model3d":
            raise ValueError("clips plays on a model3d object")
        return slot_fields.clip_cues(value)
    if key == "hold":
        if media not in _ADDED_MEDIA or slot.get("surface") in _NOT_HOLDABLE_SURFACES or (slot.get("loop") or {}).get("cylinder"):
            raise ValueError("only a model or an image cutout can be held")
        return slot_fields.hold(value, slot.get("id"))
    return slot_fields.appearance(value)


def _check_carriers(slots: list[dict], bindings: list[dict]) -> None:
    """A hold set by this patch names another model object of the scene (one added by a later binding counts)."""
    models = [slot.get("id") for slot in slots if (slot.get("media") or "model3d") == "model3d"]
    for binding in bindings:
        if not isinstance(binding.get("hold"), dict):
            continue
        slot = _target(slots, binding)
        carrier = slot["hold"]["carrier"]
        if carrier not in models:
            others = ", ".join(str(item) for item in models if item != slot.get("id")) or "none"
            raise World3DSceneError("unknown_carrier", f"{slot.get('id')}: hold.carrier {carrier!r} is not a 3D model object of "
                                    f"the scene (models: {others})")


def _add_slot(document: dict, binding: dict) -> None:
    """A new prop object (a model or a cutout) the template did not have; binding an existing id just binds it."""
    object_id = binding.get("objectId", binding.get("object_id"))
    if not isinstance(object_id, str) or not object_id or len(object_id) > 120:
        raise World3DSceneError("object_required", "An added object needs an object id")
    slots = document["slots"]
    if any(slot.get("id") == object_id for slot in slots):
        return
    if len(slots) >= _MAX_SLOTS:
        raise World3DSceneError("too_many_objects", f"A Video 3D scene holds at most {_MAX_SLOTS} objects")
    media = binding.get("media") or "model3d"
    if media not in _ADDED_MEDIA:
        raise World3DSceneError("invalid_patch", "An added object is a model3d or an image")
    slots.append({"id": object_id, "slot": "prop", "position": [0, 0, 0], "rotationY": 0, "scale": 1, "sourceUrl": "",
                  "media": media, "clip": None, **({"surface": "cutout"} if media == "image" else {})})


_TIMED = ("sfx", "worldSfx", "texts")


def _set_duration(document: dict, changes: dict) -> None:
    if "duration" not in changes:
        return
    duration = changes["duration"]
    if type(duration) not in (int, float) or not 0 < duration <= 600:
        raise World3DSceneError("invalid_duration", "duration must be between 0 and 600 seconds")
    if changes.get("retime") is True:
        _retime(document, duration)
    document["duration"] = duration


def _retime(document: dict, duration) -> None:
    """Stretch the template's own cues (effects, world effects, texts, appearances, clip cues) to a new length.

    A template authored at 8 s keeps its beats where they belong at 5 s; the soundtrack and talk tracks are not
    scaled because they are placed by the caller.
    """
    old = document.get("duration")
    if type(old) not in (int, float) or old <= 0 or type(duration) not in (int, float) or duration <= 0:
        return
    factor = duration / old
    if abs(factor - 1) < 1e-6:
        return
    for key in _TIMED:
        for cue in _dicts(document.get(key)):
            _scale(cue, factor, "start", "end")
            for frame in _dicts(cue.get("motion")) if key == "worldSfx" else []:
                _scale(frame, factor, "time")
    for slot in _dicts(document.get("slots")):
        if isinstance(slot.get("appearance"), dict):
            _scale(slot["appearance"], factor, "start", "duration")
        for cue in _dicts(slot.get("clips")):
            _scale(cue, factor, "start", "duration")
    _retime_camera_and_backdrop(document, factor)


def _retime_camera_and_backdrop(document: dict, factor: float) -> None:
    """Shake windows and backdrop effects are template beats too; a shake keeps its shape (decay per second scales back)."""
    for window in _dicts((document.get("camera") or {}).get("shake")):
        _scale(window, factor, "start", "end")
        if type(window.get("decay")) in (int, float):
            window["decay"] = round(min(60, window["decay"] / factor), 3)
    for cue in _dicts((document.get("screenBackdrop") or {}).get("sfx")):
        _scale(cue, factor, "start", "end")


def _dicts(value) -> list[dict]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _scale(target: dict, factor: float, *keys: str) -> None:
    for key in keys:
        if type(target.get(key)) in (int, float):
            target[key] = round(target[key] * factor, 3)


def _bind_screen(slot: dict, binding: dict) -> None:
    """Screens render `screen.sourceUrl`, not the slot-root URL the API accepts."""
    if slot.get("media") != "screen":
        return
    updates = {}
    for key in _SCREEN_SOURCE_FIELDS:
        if key in binding or _snake(key) in binding:
            updates[key] = deepcopy(slot.get(key))
    if not updates:
        return
    screen = slot.get("screen")
    if not isinstance(screen, dict):
        screen = {}
        slot["screen"] = screen
    screen.update(updates)


def _clip_names(binding: dict) -> list | None:
    """``clips`` as clip names (the model's own, to drop a bound clip it lacks), not a clip sequence of cue objects."""
    clips = binding.get("clips")
    return clips if isinstance(clips, list) and all(isinstance(item, str) for item in clips) else None


def _clip_warning(slot: dict, binding: dict) -> list[str]:
    clips = _clip_names(binding)
    current = slot.get("clip")
    name = current.get("name") if isinstance(current, dict) else None
    if isinstance(clips, list):
        if name and name not in clips:
            slot["clip"] = None
            return [f"incompatible_clip:{slot.get('id')}:{name}"]
        return []
    if name and ("sourceUrl" in binding or "source_url" in binding):
        return [f"clip_unverified:{slot.get('id')}:{name}"]
    return []


def _target(slots: list[dict], binding: dict) -> dict:
    object_id = binding.get("objectId", binding.get("object_id"))
    if isinstance(object_id, str) and object_id:
        found = [slot for slot in slots if slot.get("id") == object_id]
        if len(found) != 1:
            raise World3DSceneError("unknown_object", f"unknown_object:{object_id}", 404)
        return found[0]
    role = binding.get("role")
    if not isinstance(role, str) or not role:
        raise World3DSceneError("object_required", "Name an object id. A role resolves only when one object has it.")
    found = [slot for slot in slots if slot.get("slot") == role]
    if len(found) != 1:
        code = "ambiguous_role" if len(found) > 1 else "missing_role"
        raise World3DSceneError(code, f"{code}:{role}")
    return found[0]


def _retarget(document: dict) -> None:
    framing = (document.get("camera") or {}).get("framing")
    if not isinstance(framing, dict):
        return
    slots = document.get("slots") or []
    if any(slot.get("id") == framing.get("targetSlot") for slot in slots):
        return
    subjects = [slot for slot in slots if slot.get("slot") == "subject_1"]
    models = [slot for slot in slots if slot.get("media") == "model3d"]
    target = subjects[0] if len(subjects) == 1 else models[0] if len(models) == 1 else None
    if target is None:
        raise World3DSceneError("framing_target_missing", f"framing_target_missing:{framing.get('targetSlot')}")
    framing["targetSlot"] = target["id"]


def _view(scene_id: str, record: dict) -> dict:
    document = record["document"]
    return {
        "sceneId": scene_id, "revision": record["revision"], "templateId": record["templateId"],
        "document": document, "objects": _objects(document), "pending": _pending(document),
        "warnings": record.get("warnings") or [], "traits": _traits(document),
        "editable": ["sourceUrl", "sourceRef", "clip", "clipPlayback", "clips", "hold", "appearance", "position", "rotationY", "scale",
                     "motion", "grounded", "camera", "playbackSpeed", "duration", "dressing", "light", "renderLook", "toon"],
    }


def _objects(document: dict) -> list[dict]:
    objects = []
    for slot in document.get("slots") or []:
        source = slot.get("sourceUrl") or ""
        objects.append({
            "id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media"), "sourceUrl": source,
            "marker": not source, "finished": bool(source), "clip": slot.get("clip"), "position": slot.get("position"),
            "rotationY": slot.get("rotationY"), "scale": slot.get("scale"), "motion": slot.get("motion"),
            "accepted": [slot.get("media") or "model3d"],
            **{key: slot[key] for key in _CHECKED_FIELDS if slot.get(key) is not None},
        })
    return objects


def _pending(document: dict) -> list[dict]:
    return [{"id": slot.get("id"), "role": slot.get("slot"), "media": slot.get("media"),
             "requirements": "A durable workspace image or video" if slot.get("media") in ("image", "screen") else "A durable workspace GLB"}
            for slot in document.get("slots") or [] if not slot.get("sourceUrl")]


def _traits(document: dict) -> dict:
    camera = document.get("camera") or {}
    framing = camera.get("framing") or {}
    return {
        "templateId": document.get("templateId"), "playbackSpeed": document.get("playbackSpeed") or 1,
        "duration": document.get("duration"), "width": document.get("width"), "height": document.get("height"),
        "format": "portrait" if (document.get("height") or 0) > (document.get("width") or 0) else "landscape",
        "fov": camera.get("fov"), "fovTo": framing.get("fovTo"), "orbitTurns": framing.get("orbitTurns"),
        "targetSlot": framing.get("targetSlot"), "dressing": document.get("dressing"), "renderLook": document.get("renderLook"),
        "worldSfx": [cue.get("kind") for cue in document.get("worldSfx") or [] if isinstance(cue, dict)],
        "roles": [slot.get("slot") for slot in document.get("slots") or []],
        "slotIds": [slot.get("id") for slot in document.get("slots") or []],
    }


def _set_render_look(document: dict, changes: dict) -> None:
    """``renderLook``: ``n64``, ``toon`` or ``none`` (authored materials). ``toon`` merges into the stored settings."""
    try:
        if "renderLook" in changes:
            look = None if changes["renderLook"] in (None, "none") else changes["renderLook"]
            check_render_look(look)
            if look is None:
                document.pop("renderLook", None)
            else:
                document["renderLook"] = look
        if "toon" in changes:
            document["toon"] = {**(document.get("toon") or {}), **normalize_toon(changes["toon"])}
    except ValueError as error:
        raise World3DSceneError("invalid_render_look", str(error)) from error


def _speed(value) -> float:
    if type(value) not in (int, float) or not value > 0:
        raise World3DSceneError("invalid_speed", "playbackSpeed must be a positive number")
    return max(0.25, min(4.0, float(value)))


def _snake(key: str) -> str:
    return "".join(f"_{char.lower()}" if char.isupper() else char for char in key)


def _path(workspace: str, scene_id: str, workspace_dir) -> Path:
    if not isinstance(scene_id, str) or not scene_id.startswith("w3d-") or len(scene_id) != 16:
        raise World3DSceneError("unknown_scene", f"unknown_scene:{scene_id}", 404)
    return Path(workspace_dir(workspace)) / _EDITS / f"{scene_id}.json"


def _read(workspace: str, scene_id: str, workspace_dir) -> dict:
    path = _path(workspace, scene_id, workspace_dir)
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise World3DSceneError("unknown_scene", f"unknown_scene:{scene_id}", 404) from error
    except (OSError, ValueError) as error:
        raise World3DSceneError("scene_unreadable", "The Video 3D scene is unreadable", 409) from error
    if not isinstance(record, dict) or not isinstance(record.get("document"), dict):
        raise World3DSceneError("scene_unreadable", "The Video 3D scene is unreadable", 409)
    return record


def _write(workspace: str, scene_id: str, record: dict, workspace_dir) -> None:
    path = _path(workspace, scene_id, workspace_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic(path, record)


def _atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def _run_tool(command: str, payload: str | None, template_id: str | None = None) -> dict:
    node = shutil.which("node")
    loader = _ROOT / "ui/node_modules/tsx/dist/loader.mjs"
    if not node or not loader.is_file():
        raise World3DSceneError("template_tool_missing", "Video 3D template compilation requires the app's installed UI dependencies", 500)
    args = [node, "--import", str(loader), str(_ROOT / "ui/scripts/world3d-template-tool.mjs"), command]
    if template_id:
        args.append(template_id)
    result = subprocess.run(args, input=payload, capture_output=True, text=True, cwd=_ROOT / "ui", timeout=60, check=False)
    if result.returncode:
        detail = f"{result.stderr or ''}\n{result.stdout or ''}"
        if "unknown_template:" in detail:
            raise World3DSceneError("unknown_template", f"unknown_template:{template_id or ''}", 404)
        message = next((line for line in reversed(detail.splitlines()) if line.strip()), "template tool failed")
        raise World3DSceneError("template_tool_failed", message)
    try:
        parsed = json.loads(result.stdout)
    except ValueError as error:
        raise World3DSceneError("template_tool_failed", "Video 3D template tool did not return JSON") from error
    if not isinstance(parsed, dict):
        raise World3DSceneError("template_tool_failed", "Video 3D template tool did not return an object")
    return parsed
