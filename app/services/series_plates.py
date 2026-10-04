"""A Video 3D scene rendered once as the looping background plate of a series location.

2D shots take their background from ``location.layout2d.plateAssetId`` first
(``series_shot_plan.background_for``) and loop a video one. ``start`` admits a
silent Video 3D export of a scene (a saved gallery scene, a ``w3d-`` working
scene or an inline document) with a loop length; ``status`` follows its
receipt and, once the MP4 is published, imports it as a location video and
sets it as the plate. The state lives in ``location.layout2d.plate3d``, so a
restart or another client continues where it was; no thread is needed.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from services.production_scene_retry import _artifact_name, receipt_action

EXPORT = "scenes.world3d.export"
RECEIPT = "scenes.world3d.export.receipt"
SILENT_KEYS = ("soundtrack", "sfx", "worldSfx", "texts")
QUALITIES = ("draft", "final", "master")


class PlateError(ValueError):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        self.code = code
        self.status = status
        super().__init__(message)


@dataclass
class PlateDeps:
    call: Callable[[str, dict], dict]
    read_series: Callable[[str, str], dict]
    change_series: Callable[[str, str, Callable[[dict], None]], dict]
    read_scene: Callable[[str, str], dict]
    now: Callable[[], str] = lambda: datetime.now(timezone.utc).isoformat()


def plate_document(document: dict, seconds: float) -> dict:
    """The scene as a background: silent, without overlaid text or speech audio, ``seconds`` long."""
    if not isinstance(document, dict) or not isinstance(document.get("slots"), list):
        raise PlateError("not_a_world3d_scene", "A plate needs a Video 3D scene document")
    plate = {key: copy.deepcopy(value) for key, value in document.items() if key not in SILENT_KEYS}
    for slot in plate["slots"]:
        speech = slot.get("speech") if isinstance(slot, dict) else None
        if isinstance(speech, dict):
            speech["audible"] = False
            for clip in speech.get("clips") or []:
                if isinstance(clip, dict):
                    clip["audible"] = False
    plate["duration"] = round(min(20.0, max(2.0, float(seconds))), 3)
    return plate


def _location(series: dict, location_id: str) -> dict:
    found = next((item for item in series.get("locations") or [] if item.get("id") == location_id), None)
    if found is None:
        raise PlateError("not_found", f"Location {location_id} not found", 404)
    return found


def _plate(location: dict) -> dict:
    layout = location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {}
    return layout.get("plate3d") if isinstance(layout.get("plate3d"), dict) else {}


def _error(reply: dict, what: str) -> PlateError:
    error = reply.get("error") if isinstance(reply.get("error"), dict) else {}
    return PlateError(str(error.get("code") or "failed"), f"{what}: {error.get('message') or 'failed'}", int(error.get("status") or 502))


class SeriesPlates:
    def __init__(self, deps: PlateDeps) -> None:
        self.deps = deps

    def _set(self, workspace: str, series_id: str, location_id: str, update: Callable[[dict, dict], None]) -> dict:
        def change(series: dict) -> None:
            location = _location(series, location_id)
            if not isinstance(location.get("layout2d"), dict):
                location["layout2d"] = {}
            update(location, location["layout2d"])
        try:
            series = self.deps.change_series(workspace, series_id, change)
        except KeyError as error:
            raise PlateError("not_found", "Series not found", 404) from error
        return _location(series, location_id)

    def start(self, workspace: str, series_id: str, location_id: str, *, document: dict | None = None, scene: str | None = None,
              seconds: float = 6.0, quality: str = "draft") -> dict:
        try:
            _location(self.deps.read_series(workspace, series_id), location_id)
        except KeyError as error:
            raise PlateError("not_found", "Series not found", 404) from error
        if (document is None) == (not scene):
            raise PlateError("scene_required", "Give either a saved Video 3D scene or a document")
        if quality not in QUALITIES:
            raise PlateError("invalid_quality", f"quality must be one of {', '.join(QUALITIES)}")
        if document is None:
            try:
                document = self.deps.read_scene(workspace, str(scene))
            except (KeyError, FileNotFoundError) as error:
                raise PlateError("scene_not_found", f"Video 3D scene {scene} not found", 404) from error
        plate = plate_document(document, seconds)
        fingerprint = hashlib.sha256(json.dumps([plate, quality], sort_keys=True).encode()).hexdigest()[:12]
        safe = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{series_id[:48]}-{location_id[:48]}").strip("-.") or "plate"
        intent = f"plate-{safe}-{fingerprint}"
        reply = self.deps.call(EXPORT, {"version": 1, "intent_id": intent, "input": {"workspace": workspace, "document": plate, "quality": quality}})
        if reply.get("_is_error"):
            raise _error(reply, "Video 3D export")
        record = {"intent": intent, "fingerprint": fingerprint, "status": "rendering", "seconds": plate["duration"],
                  "quality": quality, "scene": scene or "document", "startedAt": self.deps.now()}

        def update(_location: dict, layout: dict) -> None:
            layout["plate3d"] = record
        self._set(workspace, series_id, location_id, update)
        return {"locationId": location_id, **record}

    def status(self, workspace: str, series_id: str, location_id: str) -> dict:
        try:
            location = _location(self.deps.read_series(workspace, series_id), location_id)
        except KeyError as error:
            raise PlateError("not_found", "Series not found", 404) from error
        plate = _plate(location)
        if not plate:
            return {"locationId": location_id, "status": "none", "plateAssetId": (location.get("layout2d") or {}).get("plateAssetId")}
        if plate.get("status") != "rendering":
            return {"locationId": location_id, **plate}
        reply = self.deps.call(RECEIPT, {"version": 1, "input": {"workspace": workspace, "intent_id": plate["intent"]}})
        reply = reply["result"] if isinstance(reply.get("result"), dict) else reply
        action = receipt_action(reply)
        if action == "wait":
            task = reply.get("task") if isinstance(reply.get("task"), dict) else {}
            return {"locationId": location_id, **plate, "progress": task.get("progress")}
        if action == "retry":
            task = reply.get("task") if isinstance(reply.get("task"), dict) else {}
            message = task.get("error") or (reply.get("error") or {}).get("message") or "The Video 3D export did not finish"
            return {"locationId": location_id, **self._finish(workspace, series_id, location_id, status="failed", error=str(message)[:500])}
        return {"locationId": location_id, **self._import(workspace, series_id, location, plate, _artifact_name(reply) or "")}

    def _import(self, workspace: str, series_id: str, location: dict, plate: dict, filename: str) -> dict:
        imported = self.deps.call("series.asset.import", {"version": 1, "input": {
            "workspace": workspace, "series_id": series_id, "file": filename, "owner_type": "location", "owner_id": location["id"],
            "kind": "video", "name": f"{location.get('name') or location['id']} · 3D plate", "reference_role": "plate3d",
            "metadata": {"world3dIntent": plate["intent"], "loop": True, "seconds": plate.get("seconds")}}})
        if imported.get("_is_error"):
            raise _error(imported, "Import plate")
        asset = (imported.get("result") or imported).get("asset") or {}
        if not asset.get("id"):
            raise PlateError("import_failed", "The plate import returned no asset", 502)
        return self._finish(workspace, series_id, location["id"], status="done", assetId=asset["id"], file=filename)

    def _finish(self, workspace: str, series_id: str, location_id: str, **fields: Any) -> dict:
        result: dict[str, Any] = {}

        def update(_location: dict, layout: dict) -> None:
            plate = {**(layout.get("plate3d") or {}), **fields, "finishedAt": self.deps.now()}
            layout["plate3d"] = plate
            if fields.get("status") == "done":
                layout["plateAssetId"] = fields["assetId"]
            result.update(plate)
        self._set(workspace, series_id, location_id, update)
        return result
