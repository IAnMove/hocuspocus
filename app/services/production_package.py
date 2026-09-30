"""Make a finished production editable shot by shot.

A production renders each shot as a Video 2D scene and stitches the scene videos into a montage. That is
enough to watch, not to retouch: the scene documents lived only in memory and the montage clips were bare
files. ``package`` keeps what a person needs to open the video and fix it to their taste:

* one durable ``*.scene.json`` per shot (clip, lyric captions, title, finish), opened in Video 2D;
* montage clips named after their shot, with the lyric they carry and an ``origin`` that names the scene
  document, the production and the shot, so the Video Editor's shot board shows where each one came from;
* ``<production_id>.shots.json``, a manifest of every shot: timing, lyric, prompts, seed, start frame, every
  take (with its lip-sync number), scene document and scene video.

The manual loop is then: open the montage in the Video Editor, open a shot's scene in Video 2D, change
the clip layer to another take or retouch the text, export, replace the clip, export the montage.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

MANIFEST_SUFFIX = ".shots.json"
CONTRAST_CODES = ("text_low_contrast", "text_outside_frame", "text_overlap", "lyrics_overlap", "reserved_zone")


def workspace_url(name: str, workspace: str) -> str:
    return f"/api/v1/file/{quote(name)}?workspace={quote(workspace, safe='')}"


def durable_document(document: dict, replacements: dict[str, str]) -> dict:
    """A copy whose layer sources point at workspace files instead of the run's temporary upload copies."""
    doc = copy.deepcopy(document)
    for layer in doc.get("layers") or []:
        source = layer.get("source")
        if isinstance(source, str) and source in replacements:
            layer["source"] = replacements[source]
    return doc


def clip_replacements(clips: dict[str, dict], workspace: str) -> dict[str, str]:
    return {clip["url"]: workspace_url(clip["file"], workspace) for clip in clips.values()
            if isinstance(clip, dict) and clip.get("url") and clip.get("file")}


def doc_digest(document: dict) -> str:
    return hashlib.sha256(json.dumps(document, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]


def lyric_for(lines: list[dict], start: float, end: float) -> str:
    """The lyric lines that sound inside [start, end)."""
    return " / ".join(line["text"] for line in lines if line["t1"] > start and line["t0"] < end)


def clip_origin(production_id: str, key: str, scene: str | None, note: str = "") -> dict[str, str]:
    origin = {"kind": "scene2d", "productionId": production_id, "shotId": key}
    if scene:
        origin["scene"] = scene
    if note:
        origin["note"] = note[:500]
    return origin


def attach_origins(montage: dict, docs: dict[str, dict], production_id: str) -> int:
    """Name each montage clip after its shot and give it its origin and lyric. Returns how many clips changed."""
    changed = 0
    for clip in montage.get("clips") or []:
        row = docs.get(clip.get("id"))
        if not row:
            continue
        origin = clip_origin(production_id, clip["id"], row.get("scene"), row.get("note", ""))
        if clip.get("origin") != origin:
            clip["origin"] = origin
            changed += 1
        if row.get("lyric") and clip.get("lyric") != row["lyric"][:500]:
            clip["lyric"] = row["lyric"][:500]
            changed += 1
    return changed


def take_rows(state: dict, key: str) -> list[dict]:
    rows = []
    for take in (state.get("takes") or {}).get(key, []):
        if isinstance(take, dict) and take.get("file"):
            rows.append({k: take[k] for k in ("file", "take", "verdict", "r", "drive") if k in take})
    return rows


def manifest_rows(state: dict, spec: dict, segs: list[tuple[dict, float, float]], score: dict, saved: dict[str, dict]) -> list[dict]:
    lines = score.get("lines") or []
    clips, frames, scenes = state.get("clips") or {}, state.get("frames") or {}, state.get("scenes") or {}
    rows = []
    for shot, start, end in segs:
        key = shot["key"]
        source = shot.get("clip") if shot.get("kind") == "clip" else key
        rows.append({
            "key": key, "kind": shot.get("kind"), "start": round(start, 3), "end": round(end, 3), "sung": bool(shot.get("sing")),
            "lyric": lyric_for(lines, start, end),
            "frame_prompt": shot.get("frame"), "action": shot.get("action"), "seed": shot.get("seed"), "cast": shot.get("cast"),
            "start_frame": frames.get(key),
            "clip": (clips.get(source) or {}).get("file"),
            "clip_qa": (clips.get(source) or {}).get("qa"),
            "takes": take_rows(state, source),
            "scene_doc": (saved.get(key) or {}).get("scene"),
            "scene_video": (scenes.get(key) or {}).get("file"),
            "warnings": (saved.get(key) or {}).get("warnings") or [],
        })
    return rows


def write_manifest(root: Path, production_id: str, title: str, rows: list[dict], montage_file: str | None) -> str:
    from services.production_shot_review import with_review_fields
    rows = with_review_fields(root, production_id, rows)
    name = production_id + MANIFEST_SUFFIX
    body = {"version": 1, "production_id": production_id, "title": title, "montage": montage_file, "shots": rows}
    target, temporary = root / name, root / (name + ".tmp")
    temporary.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    temporary.replace(target)
    return name


def editable_summary(state: dict) -> dict[str, Any] | None:
    """Small block for production.status: where to open the video for editing."""
    package = state.get("package")
    if not isinstance(package, dict) or not package.get("manifest"):
        return None
    return {"montage": state.get("montage_file"), "manifest": package["manifest"], "scene_docs": package.get("scene_docs", 0),
            "warnings": package.get("warnings", 0)}


def contrast_warnings(mcp: Callable[[str, dict], dict], document: dict) -> list[dict]:
    """Text a viewer cannot read (low contrast, cut off, overlapping), from the studio's own scene validator."""
    try:
        result = mcp("scenes.video2d.validate", {"version": 1, "input": {"document": document}}).get("result") or {}
    except Exception:
        return []
    return [{"code": item["code"], "path": item.get("path", "")} for item in result.get("warnings") or [] if item.get("code") in CONTRAST_CODES][:8]
