"""Location plates with people, and which picture a Video 3D shot uses behind the set.

``series.asset.import`` of a location plate (``environment``, ``plate`` or
``location_reference``) runs the same person detector as ``qa.people``. People
in the picture are a warning, ``people_in_plate``, unless the location says
``layout2d.allowPeople: true``. A detector that cannot run invents no count.

A 3D shot keeps its template's backdrop unless ``scene3d.backdrop`` is
``location`` (the shot location's plate, background or reference) or
``{asset}``. ``from_script`` warns ``template_backdrop_other_location`` when
the template backdrop is another location's image.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

PLATE_ROLES = frozenset({"environment", "plate", "location_reference"})
_ASSET = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,159}$")


def plate_people_warning(path: str, *, role: str, location: dict[str, Any] | None, detect: Callable[[str], list] | None = None) -> dict[str, Any] | None:
    """``people_in_plate`` when a location plate shows people and the location does not allow them."""
    if role not in PLATE_ROLES or _allows_people(location):
        return None
    try:
        boxes = [box for box in ((detect or detect_people)(path) or []) if box]
    except Exception:
        return None
    if not boxes:
        return None
    return {"code": "people_in_plate", "count": len(boxes), "boxes": boxes}


def with_plate_warning(response: dict[str, Any], source: str, body: dict[str, Any], series: dict[str, Any]) -> dict[str, Any]:
    """The import reply, plus the plate warning when this picture has people."""
    warning = plate_people_warning(
        source, role=str(body.get("referenceRole") or ""),
        location=location_of(series, str(body.get("ownerType") or ""), str(body.get("ownerId") or "")),
    )
    if warning is None:
        return response
    return {**response, "warnings": [*(response.get("warnings") or []), warning]}


def location_of(series: dict[str, Any], owner_type: str, owner_id: str) -> dict[str, Any] | None:
    if owner_type != "location":
        return None
    for item in series.get("locations") or []:
        if isinstance(item, dict) and item.get("id") == owner_id:
            return item
    return None


def detect_people(path: str) -> list:
    """Person boxes on one still, or the busiest sampled frame of a clip. Empty when the detector cannot run."""
    try:
        image = _still(path)
        if image is not None:
            from services.qa_people import find_weights, open_detector, people_boxes
            weights = find_weights()
            return people_boxes(open_detector(weights), image) if weights else []
        from services.qa_people import detect_clip
        rows, _reason = detect_clip(path)
        if not rows:
            return []
        best = max(rows, key=lambda row: int(row.get("people") or 0))
        return list(best.get("boxes") or [])
    except Exception:
        return []


def stored_backdrop(value: Any) -> Any:
    """The backdrop to keep on a shot. The default ``template`` is omitted so an old shot stays as it was."""
    if value == "location":
        return "location"
    asset = value.get("asset") if isinstance(value, dict) and set(value) <= {"asset"} else None
    if isinstance(asset, str) and _ASSET.match(asset):
        return {"asset": asset}
    return None


def backdrop_problem(value: Any) -> str | None:
    if value in (None, "template") or stored_backdrop(value) is not None:
        return None
    return "scene3d.backdrop must be template, location, or {asset}"


def location_plate_url(series: dict[str, Any], shot: dict[str, Any], workspace: str) -> str | None:
    """The file URL a ``location`` or ``{asset}`` backdrop paints. ``template`` (the default) paints nothing new."""
    try:
        from services.series_shot3d import normalize_scene3d
        backdrop = (normalize_scene3d(shot.get("scene3d")) or {}).get("backdrop")
        if backdrop == "location":
            asset = _place_asset(series, shot.get("locationId") or shot.get("location"))
        elif isinstance(backdrop, dict):
            asset = (series.get("assets") or {}).get(backdrop.get("asset"))
        else:
            return None
        return _file_url(asset, workspace)
    except Exception:
        return None


def backdrop_bindings(document: Any, plate: str | None) -> list[dict[str, str]]:
    """Point each backdrop slot at ``plate``. Other slots stay on the template."""
    if not plate or not isinstance(document, dict):
        return []
    return [{"object_id": slot["id"], "source_url": plate}
            for slot in _backdrop_slots(document) if isinstance(slot.get("id"), str) and slot["id"]]


def backdrop_warnings(episode: Any) -> list[dict[str, Any]]:
    """``template_backdrop_other_location`` when a 3D shot's template plate is another location's image."""
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    root = getattr(episode.checker, "root", None)
    for index, shot in enumerate(episode.script.get("shots") or []):
        other = _mismatched_backdrop(episode, shot, root)
        if not other:
            continue
        shot_id = episode.shot_id(index)
        if other not in groups:
            groups[other] = []
            order.append(other)
        groups[other].append(shot_id)
    return [_backdrop_group(other, groups[other]) for other in order]


def _allows_people(location: dict[str, Any] | None) -> bool:
    layout = location.get("layout2d") if isinstance(location, dict) else None
    return isinstance(layout, dict) and layout.get("allowPeople") is True


def _still(path: str):
    import cv2
    image = cv2.imread(path, cv2.IMREAD_COLOR)
    if image is None or getattr(image, "size", 0) == 0:
        return None
    return image


def _place_asset(series: dict[str, Any], location_id: Any) -> dict[str, Any] | None:
    location = next((item for item in series.get("locations") or []
                     if isinstance(item, dict) and item.get("id") == location_id), None)
    if not isinstance(location, dict):
        return None
    assets = series.get("assets") or {}
    layout = location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {}
    names = [layout.get("plateAssetId"), layout.get("backgroundAssetId"), *(location.get("referenceAssetIds") or [])]
    for name in names:
        asset = assets.get(name) if isinstance(name, str) else None
        if isinstance(asset, dict) and asset.get("kind") in ("image", "video") and asset.get("uri"):
            return asset
    return None


def _file_url(asset: Any, workspace: str) -> str | None:
    if not isinstance(asset, dict):
        return None
    uri = str(asset.get("uri") or "").replace("\\", "/").lstrip("/")
    if not uri or any(part in ("", ".", "..") for part in uri.split("/")):
        return None
    return f"/api/v1/file/{quote(uri)}?workspace={quote(str(workspace))}"


def _backdrop_slots(document: dict[str, Any]) -> list[dict[str, Any]]:
    slots = document.get("slots") if isinstance(document.get("slots"), list) else []
    return [slot for slot in slots if isinstance(slot, dict)
            and (slot.get("surface") == "environment" or slot.get("slot") == "background")]


def _mismatched_backdrop(episode: Any, shot: Any, root: str | None) -> str | None:
    if not isinstance(shot, dict) or shot.get("kind") != "3d" or not isinstance(shot.get("scene3d"), dict):
        return None
    scene3d = shot["scene3d"]
    if scene3d.get("backdrop") not in (None, "template"):
        return None
    document = _template_document(scene3d.get("template"), root) or _scene_file(root, scene3d.get("scene"))
    place = _shot_place(episode, shot)
    if not document or not place:
        return None
    for slot in _backdrop_slots(document):
        owner = _source_location(episode.series, slot.get("sourceUrl"), slot.get("sourceRef"))
        if owner and owner != place:
            return owner
    return None


def _shot_place(episode: Any, shot: dict[str, Any]) -> str:
    own = shot.get("location")
    if own not in (None, ""):
        return str(own)
    scene = episode.scenes.get(str(shot.get("scene")))
    if isinstance(scene, dict) and scene.get("location"):
        return str(scene["location"])
    return ""


def _template_document(template_id: Any, root: str | None) -> dict[str, Any] | None:
    if not root or not isinstance(template_id, str) or not template_id.startswith("user-"):
        return None
    try:
        from services.world3d_template_catalog import user_template_document
        document = user_template_document(template_id, lambda _name: root, "")
    except Exception:
        return None
    return document if isinstance(document, dict) else None


def _scene_file(root: str | None, filename: Any) -> dict[str, Any] | None:
    if not root or not isinstance(filename, str) or not _ASSET.match(filename):
        return None
    path = Path(root) / filename
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    document = data.get("document") if isinstance(data, dict) and isinstance(data.get("document"), dict) else data
    return document if isinstance(document, dict) and "slots" in document else None


def _source_location(series: dict[str, Any], source_url: Any, source_ref: Any) -> str | None:
    assets = series.get("assets") or {}
    asset_id = source_ref.get("assetId") if isinstance(source_ref, dict) else None
    owned = _asset_owner(assets.get(asset_id) if isinstance(asset_id, str) else None)
    if owned:
        return owned
    return _url_owner(series, str(source_url or ""), str(asset_id or ""))


def _asset_owner(asset: Any) -> str | None:
    if isinstance(asset, dict) and asset.get("ownerType") == "location" and asset.get("ownerId"):
        return str(asset["ownerId"])
    return None


def _url_owner(series: dict[str, Any], url: str, asset_id: str) -> str | None:
    if not url and not asset_id:
        return None
    for asset in (series.get("assets") or {}).values():
        if not isinstance(asset, dict):
            continue
        uri = str(asset.get("uri") or "")
        ident = str(asset.get("id") or "")
        if (uri and uri in url) or (ident and ident in url) or (asset_id and ident == asset_id):
            owner = _asset_owner(asset) or _location_pointing_at(series, ident)
            if owner:
                return owner
    return _location_pointing_at(series, asset_id) if asset_id else None


def _location_pointing_at(series: dict[str, Any], asset_id: str) -> str | None:
    if not asset_id:
        return None
    for location in series.get("locations") or []:
        if not isinstance(location, dict):
            continue
        layout = location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {}
        names = [layout.get("plateAssetId"), layout.get("backgroundAssetId"), *(location.get("referenceAssetIds") or [])]
        if asset_id in names:
            return str(location.get("id") or "") or None
    return None


def _backdrop_group(other: str, shots: list[str]) -> dict[str, Any]:
    shown = ", ".join(shots) if len(shots) <= 6 else f"{', '.join(shots[:2])} … {len(shots)} shots"
    return {"code": "template_backdrop_other_location", "subject": other, "shots": shots,
            "message": f"{other}: the template backdrop is this location's image (shots {shown})"}
