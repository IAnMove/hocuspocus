"""``series.location.stage.set`` and ``series.location.stage.check``: calibrate a location plate's perspective (``series_stage``).

``set`` stores ``layout2d.stage`` on the location (or clears it); the 2D wide and two-shots with people in that location are then sized
by it and render again on the next production (``series_layers.digest_location``). ``check`` reads nothing into the series: it draws
the grid over the plate (``series_stage_grid``) into the workspace and answers with its file, the plate's size, the saved stage and a
cheap horizon guess, so the one who calibrates LOOKS at the plate and reads numbers. Given ``horizon`` and ``ref`` it draws that
proposal too (the horizon, the reference, three 1.75 m bars), to confirm it before ``set``.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote

from services import series_stage as stage_math
from services import series_stage_grid as grid

_SAFE_FILE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,199}$")


class StageError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code, self.status = code, status


def _location(series: dict[str, Any], location_id: str) -> dict[str, Any]:
    found = next((item for item in series.get("locations") or [] if item.get("id") == location_id), None)
    if not isinstance(found, dict):
        raise StageError("not_found", f"Series location {location_id} not found", 404)
    return found


def _proposal(body: dict[str, Any]) -> dict[str, Any] | None:
    """The stage a request spells out (``horizon``, ``ref``, ``floorTop``), normalized, or None when it spells out none."""
    if body.get("horizon") is None and body.get("ref") is None:
        return None
    try:
        return stage_math.normalize_stage({key: body[key] for key in ("horizon", "ref", "floorTop") if body.get(key) is not None})
    except ValueError as error:
        raise StageError("invalid_stage", str(error)) from error


def affected_shots(series: dict[str, Any], location_id: str) -> list[str]:
    """The 2D wide and two-shots with people in this location: the ones a stage resizes."""
    from services.series_stage_checks import stored_view
    found = []
    for episode in (series.get("episodesById") or {}).values():
        for shot in episode.get("shots") or []:
            view = stored_view(shot) if isinstance(shot, dict) else None
            if view and view["flat"] and view["location"] == location_id and view["framing"] in stage_math.FRAMINGS and view["cast"]:
                found.append(shot["id"])
    return found


def _plate_path(series: dict[str, Any], location_id: str, workspace: str, root: str, body: dict[str, Any]) -> Path:
    """The still to calibrate: a workspace ``file``, a series ``asset_id``, else the location's own plate."""
    from services.series_shot_bridge import _workspace_path
    from services.series_shot_plan import _asset_url, background_for
    if body.get("file") is not None:
        name = str(body["file"])
        if not _SAFE_FILE.match(name) or ".." in name:
            raise StageError("bad_file", "file must be the name of an image in the workspace")
        source = f"/api/v1/file/{quote(name)}?workspace={quote(workspace)}"
    elif body.get("asset_id") is not None:
        found = _asset_url(series, str(body["asset_id"]), workspace, ("image",))
        source = found[0] if found else None
    else:
        found = background_for(series, {"locationId": location_id}, workspace, ("image",))
        source = found["source"] if found else None
    if not source:
        raise StageError("no_plate", "the location has no still picture to calibrate: give file or asset_id (a plate3d loop is a video)")
    path = _workspace_path(source, root)
    if path is None:
        raise StageError("plate_not_found", "the plate's file is not in the workspace")
    return path


class SeriesStage:
    def __init__(self, *, read_library: Callable[[str], dict], change_series: Callable[..., dict], workspace_dir: Callable[[str], str]) -> None:
        self.read_library, self.change_series, self.workspace_dir = read_library, change_series, workspace_dir

    def _series(self, workspace: str, series_id: str) -> dict[str, Any]:
        found = (self.read_library(workspace).get("seriesById") or {}).get(series_id)
        if not isinstance(found, dict):
            raise StageError("not_found", f"Series {series_id} not found", 404)
        return found

    def set(self, workspace: str, series_id: str, location_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """Store the stage on the location (``clear: true`` takes it away) and say which shots it resizes."""
        _location(self._series(workspace, series_id), location_id)
        stage = None if body.get("clear") else _proposal(body)
        if stage is None and not body.get("clear"):
            raise StageError("invalid_stage", "give horizon and ref {baseY, heightPct, heightM?} (measure them with series.location.stage.check), or clear: true")

        def change(series: dict[str, Any]) -> None:
            location = _location(series, location_id)
            layout = dict(location.get("layout2d") if isinstance(location.get("layout2d"), dict) else {})
            if stage is None:
                layout.pop("stage", None)
            else:
                layout["stage"] = stage
            location["layout2d"] = layout

        try:
            stored = self.change_series(workspace, series_id, change)
        except KeyError as error:
            raise StageError("not_found", f"Series {series_id} not found", 404) from error
        return {"locationId": location_id, "stage": stage, "affectedShots": affected_shots(stored, location_id), "revision": stored.get("revision")}

    def check(self, workspace: str, series_id: str, location_id: str, body: dict[str, Any]) -> dict[str, Any]:
        """The grid over the plate, as a workspace file, with the numbers to read it by (nothing is written to the series)."""
        series = self._series(workspace, series_id)
        location = _location(series, location_id)
        root = self.workspace_dir(workspace)
        path = _plate_path(series, location_id, workspace, root, body)
        step = float(body.get("step") if body.get("step") is not None else 0.1)
        saved, proposal = stage_math.location_stage(location), _proposal(body)
        try:
            plate = grid.load_plate(path)
            picture = grid.grid_image(plate, step=step, stage=proposal or saved)
        except ValueError as error:
            raise StageError("invalid_step", str(error)) from error
        stat = path.stat()
        digest = hashlib.sha1(repr((path.name, stat.st_size, stat.st_mtime_ns, step, proposal or saved)).encode()).hexdigest()[:8]
        name = f"stage-check-{re.sub(r'[^A-Za-z0-9_-]', '-', location_id)[:60]}-{digest}.png"
        picture.save(Path(root) / name)
        return {"locationId": location_id, "plate": {"file": path.name, "width": plate.width, "height": plate.height},
                "grid": {"file": name, "url": f"/api/v1/file/{quote(name)}?workspace={quote(workspace)}", "step": step,
                         "width": picture.width, "height": picture.height},
                "stage": saved, **({"proposal": proposal} if proposal else {}), "suggestion": grid.suggest_horizon(plate),
                "how": ("LOOK at the grid image and read numbers off it, as fractions of the plate's height from the top: baseY = the line where "
                        "a reference object of known height stands on the floor (a door's foot), heightPct = how tall it is (its top to its foot), "
                        "horizon = the camera's eye line (a room has none visible: eye height is about 1.6 m up any wall, so a 2 m door's "
                        "foot-to-top is 1.25 times the foot-to-horizon distance). Check a guess with horizon and ref here (it draws three 1.75 m "
                        "bars), then save it with series.location.stage.set.")}
