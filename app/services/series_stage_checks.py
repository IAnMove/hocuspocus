"""Checks of a 2D shot against its location's stage (``series_stage``). Warnings only: they never stop a script or an edit.

``figure_scale_off``: in a ``wide`` or ``two`` shot on a plate with a stage, a person drawn under 0.75 or over 1.35 times
what the perspective gives at their feet (by a hand-written ``transform``, or a ``scale`` that far from 1). Give ``depth`` and
``heightM`` and the compiler sizes them; drop the ``transform`` and the ``scale``.

``stage_missing``: a ``wide`` or ``two`` shot with people on a plate (an image or video of the location) that has no stage, so
they are sized by the framing alone. One warning per location, listing its shots. It is a suggestion: measure the plate once with
``series.location.stage.check`` and save it with ``series.location.stage.set``.

The same findings come from the script check (``from_script check: true``, ``series.shot.update check: true`` and
``Checker`` of ``series_script``), as grouped warnings (``code``, ``subject``, ``shots``, ``message``).
"""
from __future__ import annotations

from typing import Any

from services import series_stage as stage_math
from services.series_shot_plan import _figure_height, _shot_framing, background_view, frame_size, kit_ref

MISSING = "stage_missing"
OFF = "figure_scale_off"


def _plate(location: dict[str, Any]) -> bool:
    """Whether the location has a picture to stand people on (the shot's variant may bring its own)."""
    layout = location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {}
    variants = [ref for variant in location.get("variants") or [] if isinstance(variant, dict) for ref in variant.get("referenceAssetIds") or []]
    return bool(layout.get("plateAssetId") or layout.get("backgroundAssetId") or location.get("referenceAssetIds") or variants)


def _asset(kit: dict[str, Any], pose: str) -> dict[str, Any]:
    found = kit.get("base") if pose == "base" else (kit.get("poses") or {}).get(pose)
    return found if isinstance(found, dict) else {}


def _ratio(series: dict[str, Any], kits: dict[str, Any], entry: dict[str, Any], view: dict[str, Any], stage: dict[str, Any]) -> float | None:
    """How big this cast member is drawn against what the perspective gives, or None when the shot leaves it to the compiler."""
    transform = entry.get("transform") if isinstance(entry.get("transform"), dict) else None
    if transform is None:
        scale = entry.get("scale")
        return float(scale) if isinstance(scale, (int, float)) and not isinstance(scale, bool) and scale > 0 else None
    if not all(isinstance(transform.get(key), (int, float)) for key in ("y", "scale")):
        return None
    ref = kit_ref(series, str(entry.get("characterId") or ""))
    asset = _asset(kits.get(ref["id"]) or {}, str(entry.get("poseId") or "base")) if ref else {}
    if not asset.get("width") or not asset.get("height") or (asset.get("cut") or {}).get("bottom"):
        return None  # a pose we cannot measure, or a bust that is not a whole figure
    width, height = frame_size(series)
    zoom, _x, view_y = background_view(view["framing"], 50.0, view["detail"])
    drawn = stage_math.figure_height(asset, float(transform["scale"]), width / height)
    feet = float(transform["y"]) + drawn / 2 - drawn * 0.015
    wanted = stage_math.expected_height(stage, _figure_height(series, entry), feet, zoom, view_y)
    return drawn / wanted if wanted > 0 else None


def findings(series: dict[str, Any], kits: dict[str, Any], view: dict[str, Any]) -> list[tuple[str, str, str]]:
    """(code, subject, text) for one shot. ``view`` is {framing, location, cast: [entries], detail, flat}: ``flat`` is false for
    a card or a shot that is not a 2D one."""
    if not view["flat"] or view["framing"] not in stage_math.FRAMINGS or not view["cast"]:
        return []
    location = next((item for item in series.get("locations") or [] if item.get("id") == view["location"]), None)
    if not isinstance(location, dict):
        return []
    stage = stage_math.location_stage(location)
    if stage is None:
        if not _plate(location):
            return []
        return [(MISSING, str(location["id"]), "its plate has no stage, so people are sized by the framing alone: read the plate with "
                "series.location.stage.check and save it with series.location.stage.set")]
    found = []
    for entry in view["cast"]:
        ratio = _ratio(series, kits, entry, view, stage)
        if ratio is not None and not stage_math.SCALE_LOW <= ratio <= stage_math.SCALE_HIGH:
            found.append((OFF, str(entry.get("characterId")), f"is drawn {ratio:.2f}x of what the stage perspective gives at their feet "
                          "(0.75 to 1.35 is fine): set depth and heightM, and leave out transform and scale"))
    return found


def _cast(layout: dict[str, Any], visible: Any) -> list[dict[str, Any]]:
    entries = [item for item in layout.get("cast") or [] if isinstance(item, dict) and item.get("characterId")]
    return entries or [{"characterId": cid} for cid in visible or []]


def stored_view(shot: dict[str, Any]) -> dict[str, Any]:
    """The view of a stored shot (the ``layout2d`` the planner reads)."""
    layout = shot.get("layout2d") if isinstance(shot.get("layout2d"), dict) else {}
    card = layout.get("card") if isinstance(layout.get("card"), dict) else None
    return {"flat": shot.get("productionMethod", "animation_2d") == "animation_2d" and not card,
            "framing": _shot_framing(layout, shot, card), "location": shot.get("locationId"),
            "cast": _cast(layout, shot.get("visibleCharacterIds")), "detail": layout.get("detail") if isinstance(layout.get("detail"), dict) else None}


def shot_warnings(series: dict[str, Any], kits: dict[str, Any], shot: dict[str, Any]) -> list[dict[str, Any]]:
    """The grouped warnings of one stored shot, for a shot edit's reply."""
    return [{"code": code, "subject": subject, "shots": [shot.get("id")], "message": f"{subject}: {text} (shots {shot.get('id')})"}
            for code, subject, text in findings(series, kits, stored_view(shot))]


def check_script_shot(episode: Any, shot: dict[str, Any], where: str, shot_id: str) -> None:
    """A script shot's depth and height are checked (problems) and its stage findings noted (warnings) on ``episode``."""
    from services.series_script import _cast_entry
    from services.series_script_warnings import group_warning
    cast = [_cast_entry(raw) for raw in shot.get("cast") or []]
    for entry in cast:
        episode.checker.problems.extend(stage_math.cast_field_problems(entry, where))
    scene = episode.scenes.get(str(shot.get("scene"))) or {}
    detail = shot.get("detail") if isinstance(shot.get("detail"), dict) else None
    view = {"flat": shot.get("kind") in (None, "2d") and not isinstance(shot.get("card"), dict), "framing": shot.get("framing", "wide"),
            "location": shot.get("location") or scene.get("location"), "cast": cast, "detail": detail}
    for code, subject, text in findings(episode.series, episode.checker.kits, view):
        group_warning(episode.warnings, code, subject, shot_id, text)
