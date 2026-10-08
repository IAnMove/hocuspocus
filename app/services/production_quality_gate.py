"""Plan checks that catch a thin video before any GPU work.

``blocking_problems`` is what ``production.run`` refuses in a new or changed spec: one still image filling
three or more shots that are not marked deliberate (``allow: ["still"]``), and more runtime on still images
than the quality allows. A resume of an unchanged spec is never refused.

``plan_warnings`` is what ``dry_run`` adds: shot fields the runner ignores (a plan that promises what
nothing makes), an H3 clip replayed in several shots, H3 shots without the cast, boxes-and-cones models,
characters that never play a clip, the same 3D template over and over, and a shot pattern or lyric look
copied from another production in the workspace.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from services.production_quality import profile_of

REUSED_STILL = 3
REUSED_TEMPLATE = 4
SHOT_FIELDS = {"key", "kind", "line", "span", "t0", "t1", "after", "cast", "sing", "frame", "action", "still", "clip", "image_model",
               "image_steps", "graphic", "scene3d", "desktop", "focus", "zoom", "camera", "title", "allow", "moment", "seed"}


def _shots(spec: dict) -> list[dict]:
    shots = spec.get("shots")
    return [shot for shot in shots if isinstance(shot, dict)] if isinstance(shots, list) else []


def _still_runtime(spec: dict, shots: list[dict]) -> float:
    duration = float((spec.get("song") or {}).get("duration") or 0)
    timed = sorted((float(shot["t0"]), shot) for shot in shots if isinstance(shot.get("t0"), (int, float)))
    if duration <= 0 or len(timed) != len(shots):
        return 0.0
    ends = [start for start, _ in timed[1:]] + [duration]
    still = sum(end - start for (start, shot), end in zip(timed, ends)
                if shot.get("kind") == "still" and "still" not in (shot.get("allow") or ()))
    return still / duration


def blocking_problems(spec: dict) -> list[dict]:
    shots = _shots(spec)
    problems = []
    uses: dict[str, list[str]] = {}
    for shot in shots:
        if shot.get("kind") == "still" and isinstance(shot.get("still"), str) and "still" not in (shot.get("allow") or ()):
            uses.setdefault(shot["still"], []).append(str(shot.get("key")))
    for name, keys in uses.items():
        if len(keys) >= REUSED_STILL:
            problems.append({"code": "still_reused", "still": name, "shots": keys,
                             "hint": "one picture panned across many shots reads as filler: give each moment its own clip, "
                                     "3D shot or picture, or mark a deliberate repeat with allow: [\"still\"]"})
    ratio = _still_runtime(spec, shots)
    limit = profile_of(spec)["static"]
    if ratio > limit:
        problems.append({"code": "too_static", "ratio": round(ratio, 2), "limit": limit,
                         "hint": "replace still shots with H3 or scene3d shots"})
    return problems


def plan_warnings(spec: dict, root: Any = None, production_id: str | None = None) -> list[dict]:
    shots = _shots(spec)
    found = _ignored_fields(shots) + _replayed_clips(shots) + _castless_h3(spec, shots) + _scene3d_warnings(spec, shots, root)
    if root:
        found += _copied_from_siblings(spec, shots, Path(root), production_id)
    return found


def _ignored_fields(shots: list[dict]) -> list[dict]:
    fields: dict[str, list[str]] = {}
    for shot in shots:
        for field in set(shot) - SHOT_FIELDS:
            fields.setdefault(field, []).append(str(shot.get("key")))
    return [{"code": "ignored_shot_field", "field": field, "shots": keys,
             "hint": "the runner does nothing with this field: what it describes will not be on screen"}
            for field, keys in sorted(fields.items())]


def _replayed_clips(shots: list[dict]) -> list[dict]:
    uses: dict[str, list[str]] = {}
    for shot in shots:
        if shot.get("kind") == "clip" and isinstance(shot.get("clip"), str):
            uses.setdefault(shot["clip"], []).append(str(shot.get("key")))
    return [{"code": "clip_replayed", "clip": clip, "shots": keys} for clip, keys in uses.items() if len(keys) >= 2]


def _castless_h3(spec: dict, shots: list[dict]) -> list[dict]:
    h3 = [shot for shot in shots if shot.get("kind") == "h3"]
    empty = [str(shot.get("key")) for shot in h3 if not shot.get("cast")]
    if spec.get("cast") and h3 and len(empty) * 2 > len(h3):
        return [{"code": "h3_without_cast", "shots": empty, "hint": "the characters appear in few H3 shots; give the shots their cast"}]
    return []


def _sources(config: dict) -> list[tuple[str, dict]]:
    entries = []
    if isinstance(config.get("subject"), str):
        entries.append(("subject_1", {"source": config["subject"], "clip": config.get("clip")}))
    for key, value in (config.get("cast") or {}).items():
        entries.append((key, value if isinstance(value, dict) else {"source": value}))
    for slot in (config.get("slots") or []) + ((config.get("document") or {}).get("slots") or []):
        if isinstance(slot, dict) and slot.get("media", "model3d") == "model3d" and slot.get("sourceUrl"):
            entries.append((str(slot.get("id")), {"source": slot["sourceUrl"], "clip": slot.get("clip"), "clips": slot.get("clips")}))
    return entries


def _workspace_file(source: str) -> str | None:
    address = urlparse(source)
    if address.path.startswith("/api/v1/file/"):
        return unquote(address.path.removeprefix("/api/v1/file/"))
    return None if source.startswith(("/", "http")) else source


def _procedural(root: Path, name: str) -> bool:
    meta = root / Path(name).with_suffix(".meta.json")
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return ((data.get("generation") or {}).get("model") or {}).get("id") == "procedural-compose"


def _scene3d_warnings(spec: dict, shots: list[dict], root: Any) -> list[dict]:
    from services.production_models import rig_of
    models = spec.get("models") or {}
    cast = {entry.get("id") for entry in spec.get("cast") or [] if isinstance(entry, dict)}
    templates: dict[str, list[str]] = {}
    boxes: dict[str, list[str]] = {}
    still: list[str] = []
    for shot in shots:
        config = shot.get("scene3d") if shot.get("kind") == "scene3d" and isinstance(shot.get("scene3d"), dict) else None
        if config is None:
            continue
        template = config.get("template") or (config.get("document") or {}).get("templateId")
        if template:
            templates.setdefault(str(template), []).append(str(shot.get("key")))
        for role, entry in _sources(config):
            source = str(entry.get("source") or "")
            name = _workspace_file(source)
            if root and name and _procedural(Path(root), name):
                boxes.setdefault(name, []).append(str(shot.get("key")))
            rigged = isinstance(models.get(source), dict) and rig_of(models[source], cast) != "none"
            if rigged and not entry.get("clip") and not entry.get("clips"):
                still.append(f"{shot.get('key')}:{role}")
    found = [{"code": "procedural_model", "model": name, "shots": keys,
              "hint": "built from boxes; make it with spec.models (textured Hunyuan3D, rigged)"} for name, keys in boxes.items()]
    if still:
        found.append({"code": "model_not_animated", "objects": still, "hint": "give rigged models a clip or clips"})
    found += [{"code": "template_reused", "template": name, "shots": keys} for name, keys in templates.items() if len(keys) > REUSED_TEMPLATE]
    return found


def _pattern(shots: list[dict]) -> list[str]:
    return [str(shot.get("kind")) for shot in shots]


def _copied_from_siblings(spec: dict, shots: list[dict], root: Path, production_id: str | None) -> list[dict]:
    found = []
    pattern = _pattern(shots)
    style = spec.get("style") or {}
    look = [style.get("lyric_template"), style.get("lyric_style")]
    for path in sorted(root.glob("*.production.json")):
        other = path.name.removesuffix(".production.json")
        if other == production_id:
            continue
        try:
            sibling = (json.loads(path.read_text(encoding="utf-8")).get("spec") or {})
        except (OSError, ValueError):
            continue
        if len(pattern) >= 8 and _pattern(_shots(sibling)) == pattern:
            found.append({"code": "same_shot_pattern", "production": other,
                          "hint": "the same sequence of shot kinds as another piece: vary the structure"})
        sibling_style = sibling.get("style") or {}
        if look[0] and [sibling_style.get("lyric_template"), sibling_style.get("lyric_style")] == look:
            found.append({"code": "same_lyric_look", "production": other, "hint": "give each piece its own lyric treatment"})
    return found
