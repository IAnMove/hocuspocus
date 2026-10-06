"""Still meshes and rigged characters. Hunyuan is asked to stay inside the triangle budget.

An orbit that yields no frames does not fail the attempt. A clip the rig does
not contain is ``clip_missing``. Going more than 10% over ``maxTriangles`` is
``over_budget``. Neither warning blocks the file.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from services.game_generators.base import AttemptResult, GenContext, attempt_dir
from services.game_prompts import build
from services.game_tools import GameToolError, image, model3d, orbit, resolve_path, rig

_STAGING = "single object, three-quarter view, neutral pose, plain light grey background, no shadow"
_ORBIT = (("front", 2 / 24), ("left", 21 / 24), ("back", 42 / 24), ("right", 63 / 24))
_FACE_PRESETS = frozenset({"eco", "balanced", "quality", "multiview"})
ROLE_CLIPS = {
    "player": ("idle", "walk", "run", "jump", "punch", "victory"),
    "enemy": ("idle", "walk", "attack", "hit"),
    "npc": ("idle", "talk", "wave"),
}


def clips_for(role: str) -> tuple[str, ...]:
    """Clip names for a cast role. A boss uses the enemy set."""
    key = "enemy" if role == "boss" else str(role or "player")
    return ROLE_CLIPS.get(key, ROLE_CLIPS["player"])


def budget_warning(triangles, limit) -> list[str]:
    """``over_budget`` when the mesh is more than 10% above ``limit``."""
    if triangles is None or limit is None:
        return []
    if float(triangles) > float(limit) * 1.10:
        return ["over_budget"]
    return []


def _spec(asset: dict) -> dict:
    spec = asset.get("spec")
    return spec if isinstance(spec, dict) else {}


def _count(asset: dict) -> int:
    try:
        return max(1, int(asset.get("candidates") or 1))
    except (TypeError, ValueError):
        return 1


def _seed(asset: dict) -> int:
    try:
        return int(_spec(asset).get("seed") or 1)
    except (TypeError, ValueError):
        return 1


def _limit(asset: dict) -> int:
    try:
        return max(1, int(_spec(asset).get("maxTriangles") or 3000))
    except (TypeError, ValueError):
        return 3000


def _folder(ctx: GenContext) -> Path:
    folder = attempt_dir(ctx)
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _relative(ctx: GenContext, path: Path) -> str:
    return str(path.relative_to(Path(ctx.workspace_dir(ctx.workspace))))


def _preset(spec: dict, game: dict) -> str:
    if spec.get("multiview"):
        return "multiview"
    look = str(((game.get("style") or {}).get("model3d") or {}).get("look") or "")
    if look == "lowpoly":
        return "eco"
    if look == "painted":
        return "quality"
    return "balanced"


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


def _copy(ctx: GenContext, source: str, name: str) -> Path:
    dest = _folder(ctx) / name
    shutil.copyfile(source, dest)
    return dest


def _inspect(path: Path):
    from services.procedural_3d.glb_inspector import inspect_glb

    return inspect_glb(path)


def _concept(ctx: GenContext) -> tuple[str, bool]:
    raw = _approved_raw(ctx.game, ctx.asset)
    if raw:
        return str(resolve_path(ctx, raw)), False
    prompt, negative = build(ctx.game, ctx.asset, _STAGING, chroma=False)
    files = image(
        ctx, "concept", prompt=prompt, negative=negative, resolution="1024x1024",
        seed=_seed(ctx.asset), batch=1,
    )
    return files[0], True


def _grab(video: str, start: float, folder: Path) -> str:
    from services.game_frames import extract_frames

    frames = extract_frames(video, start, start + (1 / 24), folder)
    return str(frames[0]) if frames else ""


def _orbit_views(ctx: GenContext, concept: str) -> tuple[dict[str, str], list[str]]:
    try:
        video = orbit(ctx, "orbit", concept)
    except (GameToolError, RuntimeError):
        return {}, ["orbit_empty"]
    found: dict[str, str] = {}
    root = _folder(ctx) / "orbit"
    for name, start in _ORBIT:
        try:
            path = _grab(video, start, root / name)
        except RuntimeError:
            path = ""
        if path:
            found[name] = path
    if not found:
        return {}, ["orbit_empty"]
    return found, []


def _mesh(ctx: GenContext, concept: str) -> tuple[str, list[str]]:
    spec = _spec(ctx.asset)
    preset = _preset(spec, ctx.game)
    warnings: list[str] = []
    views: dict[str, str] = {}
    if spec.get("multiview"):
        views, warnings = _orbit_views(ctx, concept)
    reduce = True if preset in _FACE_PRESETS else None
    faces = _limit(ctx.asset) if reduce else None
    path = model3d(
        ctx, "mesh", image_path=concept, images=views or None, preset=preset,
        reduce_face=reduce, target_face_num=faces,
    )
    return path, warnings


def _metrics(report, limit: int, requested: tuple[str, ...] = ()) -> tuple[dict, list[str]]:
    present = [str(clip.name) for clip in report.animations]
    known = {name.lower() for name in present}
    missing = [name for name in requested if name.lower() not in known]
    warnings = budget_warning(report.total_triangles, limit)
    if missing:
        warnings.append("clip_missing")
    metrics = {
        "triangles": report.total_triangles,
        "bones": sum(int(skin.joint_count) for skin in report.skins),
        "clips": present,
        "missingClips": missing,
    }
    return metrics, warnings


def _run_model(ctx: GenContext) -> AttemptResult:
    concept, generated = _concept(ctx)
    mesh_path, warnings = _mesh(ctx, concept)
    stored = _copy(ctx, mesh_path, "model.glb")
    report = _inspect(stored)
    metrics, extra = _metrics(report, _limit(ctx.asset))
    files = {"model": _relative(ctx, stored)}
    if generated:
        files["concept"] = _relative(ctx, _copy(ctx, concept, "concept.png"))
    return AttemptResult(files, metrics, [*warnings, *extra], {"steps": list(ctx.steps)})


def _run_character(ctx: GenContext) -> AttemptResult:
    concept, generated = _concept(ctx)
    mesh_path, warnings = _mesh(ctx, concept)
    profile = str(_spec(ctx.asset).get("profile") or "humanoid")
    engine = "humanoid" if profile == "humanoid" else "procedural"
    requested = clips_for(_role(ctx.game, ctx.asset))
    rigged = rig(
        ctx, "rig", source=mesh_path, engine=engine, animations=list(requested),
        rig_profile=None if engine == "humanoid" else profile,
    )
    stored = _copy(ctx, rigged, "rig.glb")
    report = _inspect(stored)
    metrics, extra = _metrics(report, _limit(ctx.asset), requested)
    files = {"model": _relative(ctx, _copy(ctx, mesh_path, "model.glb")), "rig": _relative(ctx, stored)}
    if generated:
        files["concept"] = _relative(ctx, _copy(ctx, concept, "concept.png"))
    return AttemptResult(files, metrics, [*warnings, *extra], {"steps": list(ctx.steps)})


class Model3dGenerator:
    kind = "model3d"

    def estimate(self, _game: dict, asset: dict) -> dict[str, int]:
        count = _count(asset)
        return {"image": count, "3d": count}

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_model(ctx)


class Character3dGenerator:
    kind = "character3d"

    def estimate(self, game: dict, asset: dict) -> dict[str, int]:
        count = _count(asset)
        counts = {"3d": count, "rig": count}
        if not _approved_raw(game, asset):
            counts["image"] = count
        return counts

    def run(self, ctx: GenContext) -> AttemptResult:
        return _run_character(ctx)
