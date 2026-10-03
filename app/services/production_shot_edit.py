"""Swap one kept take, or retouch one shot, and re-export only that scene.

``music_production`` stays the runner. This module is the edit path: no GPU,
one scene export, and the montage clip replaced under the same ``expected_revision``
``repackage`` uses. The clip origin is left as it was.
"""
from __future__ import annotations

import copy
import time
from pathlib import Path
from typing import Any

from services.production_control import sleep_until
from services.production_package import (
    clip_replacements, contrast_warnings, doc_digest, durable_document, lyric_for, manifest_rows, workspace_url, write_manifest,
)
from services.production_scene_retry import finish_scene_exports


class ShotEditError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def render_shot(shot: dict, style: dict) -> tuple[dict, dict]:
    """Apply ``spec.shots[i].overrides`` to copies used for this scene only."""
    overrides = shot.get("overrides") if isinstance(shot.get("overrides"), dict) else {}
    rendered, look = dict(shot), dict(style)
    if "camera" in overrides:
        rendered["camera"] = overrides["camera"]
    if "title" in overrides:
        rendered["title"] = overrides["title"]
    if "lyric_style" in overrides:
        look["lyric_style"] = overrides["lyric_style"]
    return rendered, look


def _file_name(value: str, code: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value or value in {".", ".."}:
        raise ShotEditError(code, "use a file name from the workspace, not a path")
    return value


def _shot(spec: dict, key: str) -> dict:
    for shot in spec.get("shots") or []:
        if isinstance(shot, dict) and shot.get("key") == key:
            return shot
    raise ShotEditError("shot_not_found", f"no shot {key}")


def _take(state: dict, key: str, take_file: str) -> dict:
    for take in (state.get("takes") or {}).get(key) or []:
        if isinstance(take, dict) and take.get("file") == take_file:
            return take
    raise ShotEditError("take_not_found", f"take {take_file} is not a take of {key}")


def _qa(take: dict) -> dict:
    qa: dict[str, Any] = {}
    if take.get("verdict"):
        qa["verdict"] = take["verdict"]
    if "r" in take:
        qa["best_r"] = take["r"]
    return qa


def _windows(production: Any, spec: dict):
    from services.music_production import segments, shot_windows
    score = production.score()
    clips = production.state.get("clips") or {}
    windows = shot_windows(spec, score)
    return score, segments(windows, score, lambda key: key in clips, spec.get("fill") or [])


def _segment(production: Any, spec: dict, key: str):
    score, segs = _windows(production, spec)
    for shot, start, end in segs:
        if shot.get("key") == key:
            return shot, start, end, score
    raise ShotEditError("shot_not_found", f"shot {key} has no scene window")


def _note(shot: dict) -> str:
    parts = [shot.get("action"), f"seed {shot['seed']}" if shot.get("seed") is not None else ""]
    return " · ".join(part for part in parts if part)


def save_scene_revision(production: Any, key: str, document: dict, lyric: str, note: str) -> str:
    durable = durable_document(document, clip_replacements(production.state.get("clips") or {}, production.ws))
    digest = doc_digest(durable)
    result = production.mcp("scenes.document.save", {
        "version": 1, "intent_id": f"{production.id}-doc-{key}-{digest}",
        "input": {"workspace": production.ws, "name": f"{production.id}-{key}", "document": durable},
    })
    name = (result.get("result") or {}).get("name")
    if not name:
        raise ShotEditError("scene_doc_failed", "the scene document was not saved")
    production.state.setdefault("scene_docs", {})[key] = {
        "scene": name, "digest": digest, "lyric": lyric, "note": note,
        "warnings": contrast_warnings(production.mcp, durable),
    }
    return name


def export_scene(production: Any, key: str, document: dict, dur: float, clip_file: str | None, fingerprint: str) -> str:
    """Export this scene only. ``finish_scene_exports`` polls; it does not walk the other shots."""
    scenes = production.state.setdefault("scenes", {})
    response = production.mcp("scenes.video2d.export", {
        "version": 1, "intent_id": f"{production.id}-scene-{key}-{int(time.time())}",
        "input": {"workspace": production.ws, "document": document},
    })
    scenes[key] = {
        "intent": (response.get("receipt") or {}).get("commandId"), "dur": dur, "clip": clip_file,
        "fingerprint": fingerprint, "file": None,
    }
    production.save()

    def pause(seconds: float) -> None:
        sleep_until(getattr(production, "_cancel", None), seconds, time.sleep)

    failed = finish_scene_exports(
        production.mcp, production.ws, production.id, scenes, {key: document}, pause, production.save, production.log,
    )
    video = scenes.get(key, {}).get("file")
    if key in failed or not video:
        raise ShotEditError("scene_export_failed", f"scene {key} did not export")
    return video


def replace_montage_clip(production: Any, key: str, video_file: str, expected_revision: int | None = None) -> None:
    """Replace one clip source. Origins already on the montage are not rewritten."""
    montage_file = production.state.get("montage_file")
    if not montage_file:
        raise ShotEditError("montage_missing", "this production has no montage yet")
    current = (production.mcp("montages.get", {"version": 1, "input": {"workspace": production.ws, "file": montage_file}}).get("result") or {})
    montage = current.get("montage") or current
    found = False
    for clip in montage.get("clips") or []:
        if clip.get("id") == key:
            clip["source"] = workspace_url(video_file, production.ws)
            found = True
    if not found:
        raise ShotEditError("montage_clip_missing", f"the montage has no clip {key}")
    revision = current.get("revision") or montage.get("revision")
    if expected_revision is not None:
        revision = expected_revision
    saved = production.mcp("montages.save", {
        "version": 1, "intent_id": f"{production.id}-clip-{key}-{int(time.time())}",
        "input": {"workspace": production.ws, "montage": montage, "file": montage_file, "expected_revision": revision},
    })
    if "result" not in saved:
        raise ShotEditError("montage_failed", "the montage rejected the new clip")


def rewrite_manifest(production: Any, spec: dict) -> str:
    _score, segs = _windows(production, spec)
    score = production.score()
    production.state["segments"] = [[shot["key"], start, end] for shot, start, end in segs]
    name = write_manifest(
        production.root, production.id, spec.get("title", production.id),
        manifest_rows(production.state, spec, segs, score, production.state.get("scene_docs") or {}),
        production.state.get("montage_file"),
    )
    production.state.setdefault("package", {})["manifest"] = name
    return name


def _checkpoint(production: Any, spec: dict, key: str) -> dict[str, Any]:
    """Remember the shot so a failed export can put the production JSON back."""
    clips = production.state.get("clips") if isinstance(production.state.get("clips"), dict) else {}
    scenes = production.state.get("scenes") if isinstance(production.state.get("scenes"), dict) else {}
    docs = production.state.get("scene_docs") if isinstance(production.state.get("scene_docs"), dict) else {}
    shot = next((item for item in spec.get("shots") or [] if isinstance(item, dict) and item.get("key") == key), None)
    return {
        "had_clip": key in clips,
        "clip": copy.deepcopy(clips.get(key)),
        "had_scene": key in scenes,
        "scene": copy.deepcopy(scenes.get(key)),
        "had_doc": key in docs,
        "doc": copy.deepcopy(docs.get(key)),
        "had_overrides": bool(shot and "overrides" in shot),
        "overrides": copy.deepcopy(shot.get("overrides")) if shot else None,
    }


def _put(bucket: dict, key: str, *, had: bool, value: Any) -> None:
    if had:
        bucket[key] = value
    else:
        bucket.pop(key, None)


def _restore(production: Any, spec: dict, key: str, checkpoint: dict[str, Any]) -> None:
    """Undo a half-applied take swap or override after export or montage fails."""
    _put(production.state.setdefault("clips", {}), key, had=checkpoint["had_clip"], value=checkpoint["clip"])
    _put(production.state.setdefault("scenes", {}), key, had=checkpoint["had_scene"], value=checkpoint["scene"])
    _put(production.state.setdefault("scene_docs", {}), key, had=checkpoint["had_doc"], value=checkpoint["doc"])
    shot = next((item for item in spec.get("shots") or [] if isinstance(item, dict) and item.get("key") == key), None)
    if shot is not None:
        _put(shot, "overrides", had=checkpoint["had_overrides"], value=checkpoint["overrides"])
    production.state["spec"] = spec
    production.save()


def _publish(production: Any, spec: dict, key: str, expected_revision: int | None = None) -> dict[str, Any]:
    from services.music_production import scene_fingerprint
    shot, start, end, score = _segment(production, spec, key)
    style, stills = spec.get("style") or {}, spec.get("stills") or {}
    document = production.scene_document(shot, start, end, score, production.state.get("clips") or {}, style, stills)
    dur = round(end - start, 3)
    clip_file = (production.state.get("clips") or {}).get(key, {}).get("file")
    fingerprint = scene_fingerprint(shot, style, stills, score, start, end)
    lyric = lyric_for(score.get("lines") or [], start, end)
    scene = save_scene_revision(production, key, document, lyric, _note(shot))
    video = export_scene(production, key, document, dur, clip_file, fingerprint)
    replace_montage_clip(production, key, video, expected_revision)
    rewrite_manifest(production, spec)
    production.save()
    return {"shot": key, "clip": clip_file, "scene": scene, "video": video}


def remount_shot(production: Any, spec: dict, key: str, *, expected_revision: int | None = None) -> dict[str, Any]:
    """Re-export one scene and replace its montage clip. Redo and undo share this with use_take."""
    return _publish(production, spec, key, expected_revision)


def shot_checkpoint(production: Any, spec: dict, key: str) -> dict[str, Any]:
    return _checkpoint(production, spec, key)


def restore_shot(production: Any, spec: dict, key: str, checkpoint: dict[str, Any]) -> None:
    _restore(production, spec, key, checkpoint)


def _publish_or_restore(production: Any, spec: dict, key: str, checkpoint: dict[str, Any]) -> dict[str, Any]:
    try:
        return _publish(production, spec, key)
    except Exception:
        _restore(production, spec, key, checkpoint)
        raise


def adopt_take(production: Any, key: str, take_file: str) -> None:
    take_file = _file_name(take_file, "take_not_found")
    take = _take(production.state, key, take_file)
    if not (production.root / take_file).is_file():
        raise ShotEditError("take_not_found", f"take {take_file} is not in the workspace")
    _path, url = production.upload(take_file)
    production.state.setdefault("clips", {})[key] = {"file": take_file, "qa": _qa(take), "url": url}


def reexport_shot(production: Any, spec: dict, key: str) -> dict[str, Any]:
    """Re-export one scene with the revision check ``update_shot`` already uses."""
    _shot(spec, key)
    checkpoint = _checkpoint(production, spec, key)
    return _publish_or_restore(production, spec, key, checkpoint)


def use_take(production: Any, spec: dict, key: str, take_file: str) -> dict[str, Any]:
    """Use one kept take as the shot clip, then rebuild and re-export only that scene."""
    _shot(spec, key)
    checkpoint = _checkpoint(production, spec, key)
    adopt_take(production, key, take_file)
    return _publish_or_restore(production, spec, key, checkpoint)


def _assign_override(overrides: dict, name: str, value: Any) -> None:
    if name == "camera":
        if not isinstance(value, str) or not value:
            raise ShotEditError("invalid_update", "camera must be a preset name")
    elif not isinstance(value, dict):
        raise ShotEditError("invalid_update", f"{name} must be an object")
    overrides[name] = value


def update_shot(production: Any, spec: dict, key: str, *, lyric_style: Any = None, title: Any = None, camera: Any = None) -> dict[str, Any]:
    """Store per-shot overrides and re-export only that scene."""
    shot = _shot(spec, key)
    changes = {"lyric_style": lyric_style, "title": title, "camera": camera}
    if all(value is None for value in changes.values()):
        raise ShotEditError("empty_update", "pass lyric_style, title or camera")
    checkpoint = _checkpoint(production, spec, key)
    try:
        overrides = shot.setdefault("overrides", {})
        if not isinstance(overrides, dict):
            overrides = {}
            shot["overrides"] = overrides
        for name, value in changes.items():
            if value is not None:
                _assign_override(overrides, name, value)
        production.state["spec"] = spec
        result = _publish(production, spec, key)
    except Exception:
        _restore(production, spec, key, checkpoint)
        raise
    result["overrides"] = {name: overrides[name] for name in changes if name in overrides}
    return result
