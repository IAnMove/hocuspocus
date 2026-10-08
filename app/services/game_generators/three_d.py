"""Still meshes and rigged characters. Hunyuan is asked to stay inside the triangle budget.

Several candidates are ``<attemptId>-a1``, ``-a2``... in the folders ``a1``,
``a2``... of the attempt directory, as in ``still.py``. The tools answer with
names inside the workspace, so every output is resolved before it is copied.

An orbit that yields no frames does not fail the attempt. A GLB that is
corrupt or has no mesh fails it, and so does a rig without a skin. A clip the
rig does not contain is ``clip_missing``. Going more than 10% over
``maxTriangles`` is ``over_budget``; a mesh whose triangles cannot be counted
is ``triangles_unknown``. No warning blocks the file.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from services.game_generators.base import (
    AttemptResult, GenContext, candidate_dirs, candidate_result, relative, seed_for_step, spec_seed,
)
from services.game_library import game_warning
from services.game_prompts import build
from services.game_tools import GameToolError, image, model3d, orbit, resolve_path, rig

_STAGING = "single object, three-quarter view, neutral pose, plain light grey background, no shadow"
_CHARACTER_STAGING = "T-pose, front view, arms horizontal, plain light grey background"
_WARNING_TEXT = {
    "over_budget": "The mesh is over the triangle budget.",
    "triangles_unknown": "The mesh triangles could not be counted.",
    "orbit_empty": "The turnaround video has no frames.",
    "clip_missing": "A required animation clip is missing.",
}
_ORBIT = (("front", 2 / 24), ("left", 21 / 24), ("back", 42 / 24), ("right", 63 / 24))
ROLE_CLIPS = {
    "player": ("idle", "walk", "run", "jump", "punch", "victory"),
    "enemy": ("idle", "walk", "attack", "hit"),
    "npc": ("idle", "talk", "wave"),
}
# The closest clip each rig engine has for a role clip it does not know.
_CLIP_ALIASES = {"humanoid": {"attack": "punch"}, "procedural": {"punch": "attack"}}


def clips_for(role: str) -> tuple[str, ...]:
    """Clip names for a cast role. A boss uses the enemy set."""
    key = "enemy" if role == "boss" else str(role or "player")
    return ROLE_CLIPS.get(key, ROLE_CLIPS["player"])


def _mesh_warning(code: str) -> dict:
    return game_warning(code, _WARNING_TEXT[code])


def budget_warning(triangles, limit) -> list[dict]:
    """``over_budget`` more than 10% above ``limit``, ``triangles_unknown`` when uncounted."""
    if limit is None:
        return []
    if triangles is None:
        return [_mesh_warning("triangles_unknown")]
    if float(triangles) > float(limit) * 1.10:
        return [_mesh_warning("over_budget")]
    return []


def _spec(asset: dict) -> dict:
    spec = asset.get("spec")
    return spec if isinstance(spec, dict) else {}


def _count(asset: dict) -> int:
    try:
        return max(1, int(asset.get("candidates") or 1))
    except (TypeError, ValueError):
        return 1


def _positive_int(raw) -> int | None:
    if isinstance(raw, bool) or raw in (None, ""):
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 1 else None


def _limit(game: dict, asset: dict) -> int:
    """``spec.maxTriangles``, else ``style.model3d.maxTriangles``, else 3000."""
    spec_limit = _positive_int(_spec(asset).get("maxTriangles"))
    if spec_limit is not None:
        return spec_limit
    style = ((game.get("style") or {}).get("model3d") or {}).get("maxTriangles")
    return _positive_int(style) or 3000


def _orbit_steps(asset: dict, count: int) -> dict[str, int]:
    """A multiview mesh first renders one H3 orbit per candidate."""
    return {"h3": count} if _spec(asset).get("multiview") else {}


def _preset(spec: dict, game: dict) -> str:
    """Hunyuan preset. ``eco`` is never used: it skips the texture a game asset needs."""
    if spec.get("multiview"):
        return "multiview"
    look = str(((game.get("style") or {}).get("model3d") or {}).get("look") or "")
    return "quality" if look == "painted" else "balanced"


def _approved_raw(game: dict, asset: dict):
    slug = str(_spec(asset).get("character") or "")
    if not slug:
        return None
    for item in game.get("assets") or []:
        if item.get("id") != slug or item.get("status") != "approved":
            continue
        attempt_id = item.get("approvedAttemptId")
        for attempt in item.get("attempts") or []:
            if attempt.get("id") == attempt_id and attempt.get("status") == "ok":
                files = attempt.get("files") if isinstance(attempt.get("files"), dict) else {}
                return files.get("rawKey") or files.get("main")
    return None


def _role(game: dict, asset: dict) -> str:
    slug = str(_spec(asset).get("character") or "")
    for item in game.get("assets") or []:
        if item.get("id") == slug:
            return str((item.get("spec") or {}).get("role") or "player")
    return "player"


def _fetch(ctx: GenContext, name, dest: Path) -> Path:
    """Copy a tool output, named relative to the workspace, to ``dest``."""
    source = resolve_path(ctx, name)
    if not source.is_file():
        raise GameToolError("missing_output", f"tool output not found: {name}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    return dest


def _inspect(path: Path, *, skinned: bool = False):
    from services.procedural_3d.glb_inspector import inspect_glb

    report = inspect_glb(path)
    if report.status == "corrupt":
        detail = report.issues[0].message if report.issues else "corrupt"
        raise GameToolError("invalid_glb", f"{path.name}: {detail}")
    if report.status == "valid" and not report.meshes:
        raise GameToolError("invalid_glb", f"{path.name} has no mesh")
    if skinned and report.meshes and not report.skins:
        raise GameToolError("rig_missing", f"{path.name} has no skin")
    return report


def _raw_refs(ctx: GenContext, raw) -> list[str]:
    if not raw:
        return []
    file = resolve_path(ctx, raw)
    try:
        return [relative(ctx, file)]
    except ValueError:
        return [str(file)]


def _concepts(ctx: GenContext, count: int, staging: str = _STAGING, reuse_raw: bool = True) -> list[tuple[str, bool]]:
    """``(image, generated)`` per candidate. Approved art is shared when ``reuse_raw``; otherwise it is the
    reference of the new concept, so a character's T-pose keeps the approved sprite's look."""
    raw = _approved_raw(ctx.game, ctx.asset)
    if raw and reuse_raw:
        return [(str(resolve_path(ctx, raw)), False)] * count
    prompt, negative = build(ctx.game, ctx.asset, staging, chroma=False)
    files = image(
        ctx, "concept", prompt=prompt, negative=negative, resolution="1024x1024",
        refs=_raw_refs(ctx, raw), seed=spec_seed(ctx.asset), batch=count,
    )
    return [(str(name), True) for name in files[:count]]


def _grab(video: str, start: float, folder: Path) -> str:
    from services.game_frames import extract_frames

    frames = extract_frames(video, start, start + (1 / 24), folder)
    return str(frames[0]) if frames else ""


def _orbit_views(ctx: GenContext, concept: str, root: Path, suffix: str) -> tuple[dict[str, str], list[str]]:
    try:
        video = str(resolve_path(ctx, orbit(ctx, f"orbit{suffix}", concept)))
    except (GameToolError, RuntimeError):
        return {}, [_mesh_warning("orbit_empty")]
    found: dict[str, str] = {}
    for name, start in _ORBIT:
        try:
            path = _grab(video, start, root / name)
        except RuntimeError:
            path = ""
        if path:
            found[name] = path
    if not found:
        return {}, [_mesh_warning("orbit_empty")]
    return found, []


def _mesh(ctx: GenContext, concept: str, folder: Path, suffix: str) -> tuple[str, list[str]]:
    spec = _spec(ctx.asset)
    warnings: list[str] = []
    views: dict[str, str] = {}
    if spec.get("multiview"):
        views, warnings = _orbit_views(ctx, concept, folder / "orbit", suffix)
    name = model3d(
        ctx, f"mesh{suffix}", image_path=concept, images=views or None, preset=_preset(spec, ctx.game),
        reduce_face=True, target_face_num=_limit(ctx.game, ctx.asset),
        texture_resolution=spec.get("texture"), seed=seed_for_step(ctx.asset, f"mesh{suffix}"),
    )
    return name, warnings


def _clip_key(name) -> str:
    return " ".join(str(name).replace("_", " ").replace("-", " ").lower().split())


def _rig_catalog(engine: str, profile: str) -> tuple[set[str], dict[str, str]]:
    """Clip ids the engine accepts for ``profile``, and the glTF animation name of each id."""
    if engine == "humanoid":
        from services.humanoid_rig.names import CLIP_IDS, CLIP_LABELS

        return set(CLIP_IDS), dict(CLIP_LABELS)
    from services.rig_service import ANIMATIONS, RIG_PROFILES_BY_ID

    allowed = (RIG_PROFILES_BY_ID.get(profile) or {}).get("allowed_animations") or ()
    return set(allowed), {item["id"]: item["label"] for item in ANIMATIONS}


def _clip_plan(ctx: GenContext, engine: str, profile: str) -> tuple[list[str], list[str], dict[str, str]]:
    """``(wanted, sent, labels)``. ``spec.clips`` replaces the role clips.

    The rig rejects the whole job for one clip it does not know, so only
    accepted clips are sent. The others stay wanted and come back as missing.
    """
    listed = [str(item).strip() for item in _spec(ctx.asset).get("clips") or [] if str(item).strip()]
    requested = listed or clips_for(_role(ctx.game, ctx.asset))
    aliases = _CLIP_ALIASES.get(engine, {})
    wanted = list(dict.fromkeys(aliases.get(clip, clip) for clip in requested))
    allowed, labels = _rig_catalog(engine, profile)
    sent = [clip for clip in wanted if clip in allowed] or ["idle"]
    return wanted, sent, labels


def _missing(wanted, present: list[str], labels: dict[str, str]) -> list[str]:
    found = {_clip_key(name) for name in present}
    return [clip for clip in wanted if not {_clip_key(clip), _clip_key(labels.get(clip, clip))} & found]


def _metrics(report, limit: int, wanted=(), labels=None) -> tuple[dict, list[str]]:
    present = [str(clip.name) for clip in report.animations]
    missing = _missing(wanted, present, labels or {})
    warnings = budget_warning(report.total_triangles, limit)
    if missing:
        warnings.append(_mesh_warning("clip_missing"))
    metrics = {
        "triangles": report.total_triangles,
        "bones": sum(int(skin.joint_count) for skin in report.skins),
        "clips": present,
        "missingClips": missing,
    }
    return metrics, warnings


def _model_candidate(ctx: GenContext, folder: Path, suffix: str, concept: str) -> tuple[dict, list[str]]:
    mesh_name, warnings = _mesh(ctx, concept, folder, suffix)
    stored = _fetch(ctx, mesh_name, folder / "model.glb")
    metrics, extra = _metrics(_inspect(stored), _limit(ctx.game, ctx.asset))
    return {"files": {"model": relative(ctx, stored)}, "metrics": metrics}, [*warnings, *extra]


def _character_candidate(ctx: GenContext, folder: Path, suffix: str, concept: str) -> tuple[dict, list[str]]:
    mesh_name, warnings = _mesh(ctx, concept, folder, suffix)
    model = _fetch(ctx, mesh_name, folder / "model.glb")
    _inspect(model)
    profile = str(_spec(ctx.asset).get("profile") or "humanoid")
    engine = "humanoid" if profile == "humanoid" else "procedural"
    wanted, sent, labels = _clip_plan(ctx, engine, profile)
    rigged = rig(
        ctx, f"rig{suffix}", source=mesh_name, engine=engine, animations=sent,
        rig_profile=None if engine == "humanoid" else profile,
    )
    stored = _fetch(ctx, rigged, folder / "rig.glb")
    metrics, extra = _metrics(_inspect(stored, skinned=True), _limit(ctx.game, ctx.asset), wanted, labels)
    files = {"model": relative(ctx, model), "rig": relative(ctx, stored)}
    return {"files": files, "metrics": metrics}, [*warnings, *extra]


def _dedupe(items: list) -> list:
    kept: list = []
    for item in items:
        if item not in kept:
            kept.append(item)
    return kept


def _run(ctx: GenContext, make, staging: str = _STAGING, reuse_raw: bool = True) -> AttemptResult:
    """One ``make`` call per candidate. Step names get ``-a<i>`` so each candidate has its own job."""
    concepts = _concepts(ctx, _count(ctx.asset), staging, reuse_raw)
    slots = candidate_dirs(ctx, len(concepts))
    written: list[dict] = []
    for (attempt_id, folder), (concept, generated) in zip(slots, concepts):
        suffix = f"-{folder.name}" if len(slots) > 1 else ""
        item, found = make(ctx, folder, suffix, concept)
        if generated:
            kept = _fetch(ctx, concept, folder / f"concept{Path(concept).suffix or '.png'}")
            item["files"]["concept"] = relative(ctx, kept)
        written.append({"id": attempt_id, **item, "warnings": _dedupe(found)})
    return candidate_result(written, [], ctx.steps)


class Model3dGenerator:
    kind = "model3d"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        count = _count(asset)
        return {"image": count, "3d": count, **_orbit_steps(asset, count)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run(ctx, _model_candidate)


class Character3dGenerator:
    kind = "character3d"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        count = _count(asset)
        return {"image": count, "3d": count, "rig": count, **_orbit_steps(asset, count)}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run(ctx, _character_candidate, _CHARACTER_STAGING, False)
