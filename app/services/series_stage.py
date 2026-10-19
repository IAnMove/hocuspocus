"""The perspective of a 2D location plate, so a person's size comes from where they stand and how tall they are.

A painted plate has no scale of its own: a model draws the door wherever it likes. ``location.layout2d.stage`` says, once,
how this plate's perspective works (a camera at eye height looking level, the horizon where eye-level things meet)::

    {"horizon": 0.22, "ref": {"baseY": 0.72, "heightPct": 0.62, "heightM": 2.0}, "floorTop": 0.72}

All numbers are fractions of the plate's height, from the top. ``horizon`` is the y of the horizon line (an interior has
no visible one: it is where the eye height of the camera falls, about 1.6 m up any wall). ``ref`` is one object of a known
height standing on the floor: its base is at ``baseY``, it is ``heightPct`` of the plate tall and ``heightM`` metres
(a door: 2 m). ``floorTop`` (default ``baseY``) is the farthest floor a person can stand on.

For a person ``h`` metres tall whose feet are at y ``v`` the plate gives, by similar triangles to the eye-level camera::

    height on the plate = h / ref.heightM * ref.heightPct * (v - horizon) / (ref.baseY - horizon)

A cast entry of a 2D shot says where its feet stand with ``depth`` (0 to 1, or ``far`` 0, ``mid`` 0.5, ``near`` 1; as a set
layer's ``depth``, 1 is the nearest the lens): the feet line goes from ``floorTop`` at 0 to the framing's feet line (94 % of the
frame) at 1, and the figure is drawn at the height above, ``heightM`` metres (the entry's, else its character's
``layout2d.heightM``, else 1.75 times its ``layout2d.scale``). The compiler (``ui/scripts/seriesStage.ts``, which mirrors this file) does it
for ``wide`` and ``two`` shots; ``medium`` and ``close`` keep their eye-line framing. Without a ``stage`` nothing changes.

The size is the figure's, not the pose image's: the rig leaves a margin of ``FIGURE_MARGIN`` of the image's longest side above and
below it (``figure_share``). A pose cut at the bottom (a bust), a ``transform`` and a perched character keep their own placement.
"""
from __future__ import annotations

from typing import Any

# The framing's feet line (% of the frame height) where depth is 1 (``FEET`` in ui/scripts/seriesShot.ts).
FEET = 94.0
ADULT_M = 1.75
# The margin the rig leaves around a figure, as a share of the pose image's longest side (``flat_rig.crop_figure``, ``margin=0.02``).
FIGURE_MARGIN = 0.02
REF_M = 2.0
FRAMINGS = ("wide", "two")
DEPTH_WORDS = {"far": 0.0, "mid": 0.5, "near": 1.0}
# A figure drawn outside this share of what the perspective says is flagged (``figure_scale_off``).
SCALE_LOW, SCALE_HIGH = 0.75, 1.35
# The camera heights (metres) that need no remark (``eye_height_note``).
EYE_LOW, EYE_HIGH = 1.0, 2.4
# The least a figure's feet may be below the horizon (plate fraction): at it the perspective height is nil.
_MIN_BELOW = 0.01
_REF_KEYS = ("baseY", "heightPct", "heightM")


def _number(value: Any, low: float, high: float) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and low <= value <= high else None


def _fraction(value: dict[str, Any], key: str, low: float, high: float, label: str) -> float:
    found = _number(value.get(key), low, high)
    if found is None:
        raise ValueError(f"{label}.{key} must be a number from {low:g} to {high:g}")
    return round(found, 4)


def normalize_stage(value: Any, label: str = "stage") -> dict[str, Any]:
    """A stage with its defaults (``ref.heightM`` 2, ``floorTop`` left out); unknown keys are dropped, a bad value is refused."""
    if not isinstance(value, dict) or not isinstance(value.get("ref"), dict):
        raise ValueError(f"{label} must be {{horizon, ref: {{baseY, heightPct, heightM}}, floorTop?}}")
    ref = value["ref"]
    horizon = _fraction(value, "horizon", 0, 0.95, label)
    base = _fraction(ref, "baseY", 0.05, 1, f"{label}.ref")
    found: dict[str, Any] = {"horizon": horizon, "ref": {
        "baseY": base, "heightPct": _fraction(ref, "heightPct", 0.01, 1.5, f"{label}.ref"),
        "heightM": _fraction({"heightM": ref.get("heightM", REF_M)}, "heightM", 0.05, 30, f"{label}.ref")}}
    if base - horizon < _MIN_BELOW:
        raise ValueError(f"{label}.ref.baseY ({base}) must be below the horizon ({horizon}): the floor under the object starts under the eye line")
    if value.get("floorTop") is not None:
        top = _fraction(value, "floorTop", 0, 1, label)
        if top - horizon < _MIN_BELOW:
            raise ValueError(f"{label}.floorTop ({top}) must be below the horizon ({horizon})")
        found["floorTop"] = top
    return found


def normalize_location_stage(location: dict[str, Any], label: str) -> dict[str, Any]:
    """Check a location's ``layout2d.stage`` in place (``label`` is the path of its ``layout2d`` in the error). A null one is dropped."""
    layout = location.get("layout2d")
    if not isinstance(layout, dict) or "stage" not in layout:
        return location
    if layout["stage"] is None:
        location["layout2d"] = {key: value for key, value in layout.items() if key != "stage"}
    else:
        location["layout2d"] = {**layout, "stage": normalize_stage(layout["stage"], f"{label}.stage")}
    return location


def eye_height_m(stage: dict[str, Any]) -> float:
    """The camera height (metres) this stage implies: how many metres lie between the reference's foot and the horizon. A person's eye
    level camera is about 1.6 m; far from 1 to 2.4 m the horizon or the reference was probably misread."""
    ref = stage["ref"]
    return round((ref["baseY"] - stage["horizon"]) * ref["heightM"] / ref["heightPct"], 2)


def eye_height_note(stage: dict[str, Any]) -> str | None:
    """A hint when the stage implies an odd camera height; None when it is plausible (a low or high camera is a choice, not an error)."""
    height = eye_height_m(stage)
    if EYE_LOW <= height <= EYE_HIGH:
        return None
    return (f"this stage puts the camera {height:g} m high (the metres between the reference's foot and the horizon); a camera at eye level "
            f"is about 1.6 m. Re-read the horizon and the reference on the grid unless the plate really is a {'low' if height < EYE_LOW else 'high'} angle")


def location_stage(location: Any) -> dict[str, Any] | None:
    """The location's stage, or None when it has none (or a hand-edited bad one: a render never stops for it)."""
    layout = location.get("layout2d") if isinstance(location, dict) else None
    raw = layout.get("stage") if isinstance(layout, dict) else None
    if raw is None:
        return None
    try:
        return normalize_stage(raw)
    except ValueError:
        return None


def depth_value(value: Any) -> float | None:
    """A cast entry's ``depth``: 0 to 1, or ``far`` / ``mid`` / ``near``; None for anything else."""
    if isinstance(value, str):
        return DEPTH_WORDS.get(value.strip().lower())
    return _number(value, 0, 1)


def cast_fields(value: dict[str, Any]) -> dict[str, float]:
    """``depth`` and ``heightM`` of a cast entry, valid ones only (the others are dropped like the rest of ``layout2d``)."""
    found: dict[str, float] = {}
    depth, height = depth_value(value.get("depth")), _number(value.get("heightM"), 0.2, 6)
    if depth is not None:
        found["depth"] = depth
    if height is not None:
        found["heightM"] = height
    return found


def cast_field_problems(entry: dict[str, Any], where: str) -> list[str]:
    """What a script cast entry says wrong in ``depth`` / ``heightM`` (the check refuses it)."""
    problems = []
    if entry.get("depth") is not None and depth_value(entry["depth"]) is None:
        problems.append(f"{where}: depth must be a number from 0 to 1 or one of {', '.join(DEPTH_WORDS)}")
    if entry.get("heightM") is not None and _number(entry["heightM"], 0.2, 6) is None:
        problems.append(f"{where}: heightM must be a number of metres from 0.2 to 6")
    return problems


def frame_y(zoom: float, view_y: float, plate_y: float) -> float:
    """Where a plate y (fraction) falls in the frame (%), the plate shown at ``zoom`` centred on ``view_y`` (``backgroundLayer``)."""
    return view_y + (plate_y - 0.5) * 100 * zoom


def plate_y(zoom: float, view_y: float, frame: float) -> float:
    """The plate y (fraction) a frame y (%) shows: the inverse of ``frame_y``."""
    return 0.5 + (frame - view_y) / (100 * zoom)


def perspective_height(stage: dict[str, Any], height_m: float, feet: float) -> float:
    """A ``height_m`` figure's height as a fraction of the plate height when its feet are at plate y ``feet``."""
    ref, horizon = stage["ref"], stage["horizon"]
    below = max(feet - horizon, _MIN_BELOW)
    return height_m / ref["heightM"] * ref["heightPct"] * below / (ref["baseY"] - horizon)


def standing(stage: dict[str, Any], height_m: float, depth: float, zoom: float = 1.0, view_y: float = 50.0,
             near: float = FEET) -> tuple[float, float]:
    """(feet y, figure height), both in % of the frame height, of a ``height_m`` figure standing at ``depth`` on the
    plate shown at ``zoom`` (``view_y``: the frame y of the plate's centre). ``near`` is the frame feet line of depth 1."""
    far_plate = stage.get("floorTop", stage["ref"]["baseY"])
    near_plate = max(plate_y(zoom, view_y, near), far_plate)
    feet = far_plate + (near_plate - far_plate) * depth
    return round(frame_y(zoom, view_y, feet), 3), round(perspective_height(stage, height_m, feet) * 100 * zoom, 3)


def expected_height(stage: dict[str, Any], height_m: float, feet_frame: float, zoom: float = 1.0, view_y: float = 50.0) -> float:
    """What the perspective gives (% of the frame height) for a figure whose feet are at frame y ``feet_frame``."""
    return perspective_height(stage, height_m, plate_y(zoom, view_y, feet_frame)) * 100 * zoom


def figure_height(size: dict[str, Any], scale: float, aspect: float) -> float:
    """The height (% of the frame) a pose image of ``size`` takes at layer ``scale`` (the layer is contained in the frame)."""
    ratio = size["width"] / size["height"]
    return scale * 100 if ratio < aspect else scale * 100 * aspect / ratio


def figure_share(size: dict[str, Any]) -> float:
    """The share of a pose image's height the figure takes: the rig crops each pose with a margin of ``FIGURE_MARGIN`` of its longest
    side above and below the figure (``flat_rig.crop_figure``)."""
    return max(0.5, 1 - 2 * FIGURE_MARGIN * max(size["width"], size["height"]) / size["height"])


def placement(size: dict[str, Any], feet: float, figure: float, aspect: float) -> tuple[float, float]:
    """(layer y %, layer scale) of a pose whose figure is ``figure`` % of the frame tall with its feet on frame y ``feet``."""
    share = figure_share(size)
    image = figure / share
    ratio = size["width"] / size["height"]
    scale = image / 100 if ratio < aspect else image / 100 * ratio / aspect
    return feet + (1 - share) / 2 * image - image / 2, scale


def figure_of(size: dict[str, Any], y: float, scale: float, aspect: float) -> tuple[float, float]:
    """(feet y %, figure height %) of a pose drawn at layer ``y`` and ``scale``: the inverse of ``placement``."""
    image, share = figure_height(size, scale, aspect), figure_share(size)
    return y + image / 2 - (1 - share) / 2 * image, image * share
