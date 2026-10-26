"""Round-headed bodies as overlapped primitives. Pure: no files, no rig, no GPU.

Metres, Y up, +Z forward. ``scale`` is the full size (the diameter), the same
rule as ``model3d.compose``. Pieces overlap on purpose. Arms are a T, feet sit
on y = 0, and the head is wider than the torso so the humanoid rig can see a neck.
"""
from __future__ import annotations

import math

HEAD_SEGMENTS = 32
LIMB_SEGMENTS = 12
BODY_SEGMENTS = 16
_HALF_TURN = round(math.pi / 2, 6)

_FIELDS = {"height", "build", "head", "arms", "legs", "hands", "feet", "colors", "accessories"}
_BUILDS = ("slim", "average", "round", "pear")
_HANDS = ("ball", "mitten")
_FEET = ("shoe", "ball")
_SHAPES = ("sphere", "egg")
# Torso width and depth, and the belly, as fractions of the head. The torso stays
# narrower than the head. The belly carries the round and pear silhouettes.
_BUILD = {
    "slim": (0.64, 0.70, 0.52, 0.00, 0.50),
    "average": (0.74, 0.84, 0.72, 0.18, 0.55),
    "round": (0.84, 1.05, 0.98, 0.32, 0.48),
    "pear": (0.70, 0.90, 1.04, 0.28, 0.74),
}
_HEAD_DEFAULT = {"width": 0.31, "height": 0.28, "depth": 0.26, "shape": "sphere"}
_HEAD_LIMITS = {"width": (0.24, 0.38), "height": (0.22, 0.36), "depth": (0.20, 0.34)}
_ARM_DEFAULT = {"length": 0.36, "thickness": 0.055}
_ARM_LIMITS = {"length": (0.30, 0.46), "thickness": (0.046, 0.068)}
_LEG_DEFAULT = {"length": 0.42, "thickness": 0.070}
_LEG_LIMITS = {"length": (0.36, 0.48), "thickness": (0.052, 0.085)}
_COLOR_DEFAULT = {
    "head": "#F2C7A0", "top": "#3A6EA5", "sleeves": "#F2C7A0",
    "bottom": "#2C3340", "shoes": "#201A18", "hands": "#F2C7A0",
}
_ACCESSORY_KINDS = (
    "cap", "sailor_cap", "top_hat", "beanie", "bucket_hat",
    "apron", "tie", "collar", "belt", "backpack", "scarf",
)
_ACCESSORY_COLOR = {
    "cap": "#C45C4A", "sailor_cap": "#F4F1EA", "top_hat": "#161616", "beanie": "#2C4C7C",
    "bucket_hat": "#D8C39A", "apron": "#E8E0D0", "tie": "#8C1D2C", "collar": "#F4F4F2",
    "belt": "#2A211C", "backpack": "#3E4A3A", "scarf": "#B23A48",
}
_MAX_ACCESSORIES = 6

PRESETS = {
    "sailor": {
        "height": 1.75, "build": "average",
        "colors": {"head": "#F2C7A0", "top": "#1B2350", "sleeves": "#F4F1EA", "bottom": "#1B2350", "shoes": "#201A18", "hands": "#F2C7A0"},
        "accessories": [{"kind": "sailor_cap", "color": "#F4F1EA"}, {"kind": "collar", "color": "#F4F1EA"}],
    },
    "cashier": {
        "height": 1.68, "build": "slim",
        "colors": {"head": "#E8B896", "top": "#F2E6C9", "sleeves": "#F2E6C9", "bottom": "#3D4A3A", "shoes": "#3A2A22", "hands": "#E8B896"},
        "accessories": [{"kind": "apron", "color": "#C45C4A"}, {"kind": "cap", "color": "#C45C4A"}],
    },
    "boss": {
        "height": 1.88, "build": "average",
        "colors": {"head": "#D7A57A", "top": "#1A1A1A", "sleeves": "#F4F4F2", "bottom": "#1A1A1A", "shoes": "#111111", "hands": "#D7A57A"},
        "accessories": [{"kind": "top_hat", "color": "#111111"}, {"kind": "tie", "color": "#8C1D2C"}],
    },
    "kid": {
        "height": 1.25, "build": "round",
        "head": {"width": 0.38, "height": 0.34, "depth": 0.32, "shape": "sphere"},
        "arms": {"length": 0.32, "thickness": 0.062}, "legs": {"length": 0.36, "thickness": 0.080},
        "colors": {"head": "#F0C09A", "top": "#E25B3A", "sleeves": "#F2D24A", "bottom": "#3C6EBE", "shoes": "#F4F4F2", "hands": "#F0C09A"},
        "accessories": [{"kind": "beanie", "color": "#3C6EBE"}],
    },
    "big": {
        "height": 2.05, "build": "round",
        "arms": {"length": 0.34, "thickness": 0.068}, "legs": {"length": 0.40, "thickness": 0.085},
        "colors": {"head": "#C6865A", "top": "#D4782A", "sleeves": "#D4782A", "bottom": "#4A3428", "shoes": "#2A211C", "hands": "#C6865A"},
        "accessories": [{"kind": "bucket_hat", "color": "#E6D3A3"}, {"kind": "belt", "color": "#3A2A1A"}],
    },
    "lanky": {
        "height": 2.15, "build": "slim",
        "head": {"width": 0.24, "height": 0.28, "depth": 0.22, "shape": "egg"},
        "arms": {"length": 0.46, "thickness": 0.046}, "legs": {"length": 0.48, "thickness": 0.052},
        "colors": {"head": "#F2C7A0", "top": "#5C6B73", "sleeves": "#5C6B73", "bottom": "#2F3D44", "shoes": "#1C1C1C", "hands": "#F2C7A0"},
        "accessories": [{"kind": "scarf", "color": "#B23A48"}],
    },
}

# The six presets plus six edges. Every one has to stay a person the rig accepts.
EXTREMES = (
    {"height": 1.2, "build": "slim", "head": {"width": 0.24, "height": 0.22, "depth": 0.20, "shape": "sphere"},
     "arms": {"length": 0.30, "thickness": 0.046}, "legs": {"length": 0.36, "thickness": 0.052},
     "hands": "mitten", "feet": "ball"},
    {"height": 2.2, "build": "round", "head": {"width": 0.38, "height": 0.36, "depth": 0.34, "shape": "egg"},
     "arms": {"length": 0.46, "thickness": 0.068}, "legs": {"length": 0.48, "thickness": 0.085},
     "hands": "ball", "feet": "shoe",
     "accessories": [{"kind": "backpack", "color": "#334455"}, {"kind": "belt", "color": "#111111"}]},
    {"height": 1.45, "build": "pear", "head": {"width": 0.36, "height": 0.34, "depth": 0.30, "shape": "egg"},
     "accessories": [{"kind": "scarf", "color": "#6A2A3A"}, {"kind": "apron", "color": "#E8E0D0"}]},
    {"height": 2.2, "build": "slim", "head": {"width": 0.24, "height": 0.30, "depth": 0.20, "shape": "egg"},
     "arms": {"length": 0.46, "thickness": 0.046}, "legs": {"length": 0.48, "thickness": 0.052},
     "accessories": [{"kind": "top_hat", "color": "#111111"}]},
    {"height": 1.2, "build": "round", "head": {"width": 0.38, "height": 0.36, "depth": 0.34, "shape": "sphere"},
     "hands": "mitten", "feet": "shoe", "accessories": [{"kind": "beanie", "color": "#224466"}, {"kind": "collar", "color": "#F4F4F2"}]},
    {"height": 1.8, "build": "average", "hands": "mitten", "feet": "ball",
     "accessories": [{"kind": "tie", "color": "#8C1D2C"}, {"kind": "collar", "color": "#F4F4F2"},
                     {"kind": "belt", "color": "#2A211C"}, {"kind": "backpack", "color": "#3E4A3A"}]},
)


class BlobTraitsError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = str(code)
        super().__init__(message)


def trait_catalog() -> dict:
    """Limits, defaults and the six named presets. The face (moustache, glasses) is not here."""
    return {
        "height": {"min": 1.2, "max": 2.2, "default": 1.8, "unit": "m"},
        "build": list(_BUILDS),
        "head": {"limits": _HEAD_LIMITS, "shape": list(_SHAPES), "default": dict(_HEAD_DEFAULT),
                 "note": "width, height and depth are fractions of the body height. The default head is large (width 0.31)."},
        "arms": {"limits": _ARM_LIMITS, "default": dict(_ARM_DEFAULT)},
        "legs": {"limits": _LEG_LIMITS, "default": dict(_LEG_DEFAULT)},
        "hands": list(_HANDS), "feet": list(_FEET),
        "colors": {"fields": list(_COLOR_DEFAULT), "default": dict(_COLOR_DEFAULT), "format": "#RRGGBB"},
        "accessories": {"kinds": list(_ACCESSORY_KINDS), "max": _MAX_ACCESSORIES, "defaultColor": dict(_ACCESSORY_COLOR),
                        "notHere": ["moustache", "glasses", "eyebrows", "freckles"]},
        "presets": {name: _copy(traits) for name, traits in PRESETS.items()},
    }


def blob_pieces(traits: dict | None = None) -> dict:
    """``{pieces, faceAnchor, traits}`` for one body. Unknown fields raise ``BlobTraitsError``."""
    spec = _normalize({} if traits is None else traits)
    pieces, anchor = _assemble(spec)
    if not 1 <= len(pieces) <= 128:
        raise BlobTraitsError("too_many_pieces", f"A body has {len(pieces)} pieces; the limit is 128")
    return {"pieces": pieces, "faceAnchor": anchor, "traits": spec}


def _copy(value):
    if isinstance(value, dict):
        return {key: _copy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_copy(item) for item in value]
    return value


def _fail(code: str, message: str):
    raise BlobTraitsError(code, message)


def _normalize(traits: dict) -> dict:
    if not isinstance(traits, dict):
        _fail("invalid_traits", "traits must be an object")
    extra = set(traits) - _FIELDS
    if extra:
        _fail("unknown_field", "Unknown trait: " + ", ".join(sorted(extra)))
    return {
        "height": _height(traits.get("height", 1.8)),
        "build": _choice(traits.get("build", "average"), _BUILDS, "invalid_build", "build"),
        "head": _head(traits.get("head")),
        "arms": _pair_size(traits.get("arms"), _ARM_DEFAULT, _ARM_LIMITS, "invalid_arms", "arms"),
        "legs": _pair_size(traits.get("legs"), _LEG_DEFAULT, _LEG_LIMITS, "invalid_legs", "legs"),
        "hands": _choice(traits.get("hands", "ball"), _HANDS, "invalid_hands", "hands"),
        "feet": _choice(traits.get("feet", "shoe"), _FEET, "invalid_feet", "feet"),
        "colors": _colors(traits.get("colors")),
        "accessories": _accessory_list(traits.get("accessories")),
    }


def _height(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        _fail("invalid_height", "height must be a number of metres from 1.2 to 2.2")
    if not 1.2 <= float(value) <= 2.2:
        _fail("invalid_height", "height must be from 1.2 to 2.2 metres")
    return float(value)


def _choice(value, allowed, code: str, label: str) -> str:
    if value not in allowed:
        _fail(code, f"{label} must be one of: " + ", ".join(allowed))
    return value


def _head(value) -> dict:
    if value is None:
        return dict(_HEAD_DEFAULT)
    if not isinstance(value, dict):
        _fail("invalid_head", "head must be an object with width, height, depth and shape")
    extra = set(value) - set(_HEAD_DEFAULT)
    if extra:
        _fail("unknown_field", "Unknown head field: " + ", ".join(sorted(extra)))
    found = dict(_HEAD_DEFAULT)
    for key, limits in _HEAD_LIMITS.items():
        if key not in value:
            continue
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            _fail("invalid_head", f"head.{key} must be a fraction of the height")
        if not limits[0] <= float(number) <= limits[1]:
            _fail("invalid_head", f"head.{key} must be from {limits[0]} to {limits[1]}")
        found[key] = float(number)
    if "shape" in value:
        found["shape"] = _choice(value["shape"], _SHAPES, "invalid_head", "head.shape")
    return found


def _pair_size(value, default: dict, limits: dict, code: str, label: str) -> dict:
    if value is None:
        return dict(default)
    if not isinstance(value, dict):
        _fail(code, f"{label} must be an object with length and thickness")
    extra = set(value) - {"length", "thickness"}
    if extra:
        _fail("unknown_field", f"Unknown {label} field: " + ", ".join(sorted(extra)))
    found = dict(default)
    for key, bounds in limits.items():
        if key not in value:
            continue
        number = value[key]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            _fail(code, f"{label}.{key} must be a fraction of the height")
        if not bounds[0] <= float(number) <= bounds[1]:
            _fail(code, f"{label}.{key} must be from {bounds[0]} to {bounds[1]}")
        found[key] = float(number)
    return found


def _colors(value) -> dict:
    if value is None:
        return dict(_COLOR_DEFAULT)
    if not isinstance(value, dict):
        _fail("invalid_color", "colors must be an object of #RRGGBB values")
    extra = set(value) - set(_COLOR_DEFAULT)
    if extra:
        _fail("unknown_field", "Unknown color: " + ", ".join(sorted(extra)))
    found = dict(_COLOR_DEFAULT)
    for key, color in value.items():
        found[key] = _hex(color, f"colors.{key}")
    return found


def _hex(value, label: str) -> str:
    if not isinstance(value, str) or len(value) != 7 or value[0] != "#" or any(c not in "0123456789abcdefABCDEF" for c in value[1:]):
        _fail("invalid_color", f"{label} must be #RRGGBB")
    return value.upper()


def _accessory_list(value) -> list:
    if value is None:
        return []
    if not isinstance(value, list):
        _fail("invalid_accessory", "accessories must be a list")
    if len(value) > _MAX_ACCESSORIES:
        _fail("invalid_accessory", f"Use at most {_MAX_ACCESSORIES} accessories")
    found = [_one_accessory(item) for item in value]
    kinds = [item["kind"] for item in found]
    if len(kinds) != len(set(kinds)):
        _fail("invalid_accessory", "Each accessory kind is used once")
    return found


def _one_accessory(item) -> dict:
    if not isinstance(item, dict):
        _fail("invalid_accessory", "An accessory is an object with kind and an optional color")
    extra = set(item) - {"kind", "color"}
    if extra:
        _fail("unknown_field", "Unknown accessory field: " + ", ".join(sorted(extra)))
    kind = item.get("kind")
    if kind not in _ACCESSORY_KINDS:
        _fail("invalid_accessory", "accessory kind must be one of: " + ", ".join(_ACCESSORY_KINDS))
    color = _ACCESSORY_COLOR[kind] if "color" not in item else _hex(item["color"], "accessory.color")
    return {"kind": kind, "color": color}


def _assemble(spec: dict) -> tuple[list, dict]:
    layout = _layout(spec)
    pieces = _torso(spec, layout) + _arms(spec, layout) + _legs(spec, layout)
    pieces += _accessory_pieces(spec, layout)
    return pieces, _anchor(layout)


def _layout(spec: dict) -> dict:
    height = spec["height"]
    sx, sy, sz = _head_size(spec["head"], height)
    width, depth, belly, forward, drop = _BUILD[spec["build"]]
    torso_w, torso_d = sx * width, min(sz * depth, sx * 0.95)
    foot = _foot_height(spec, height)
    stack = _stack(height, sy, spec["legs"]["length"] * height, foot)
    torso_h = stack["torso_top"] - stack["torso_bottom"]
    return {
        "h": height, "sx": sx, "sy": sy, "sz": sz, "head_y": stack["head_y"],
        "torso_w": torso_w, "torso_d": torso_d, "torso_h": torso_h,
        "torso_y": (stack["torso_top"] + stack["torso_bottom"]) / 2,
        "torso_top": stack["torso_top"], "torso_bottom": stack["torso_bottom"],
        "shoulder_y": stack["torso_bottom"] + torso_h * 0.72,
        "leg_len": spec["legs"]["length"] * height, "leg_d": spec["legs"]["thickness"] * height,
        "leg_bottom": stack["leg_bottom"], "leg_top": stack["leg_top"], "foot": foot,
        "belly": belly, "forward": forward, "drop": drop,
        "arm_len": spec["arms"]["length"] * height,
        "arm_d": min(spec["arms"]["thickness"] * height, torso_w * 0.45),
    }


def _head_size(head: dict, height: float) -> tuple[float, float, float]:
    sx, sy, sz = head["width"] * height, head["height"] * height, head["depth"] * height
    if head["shape"] == "egg":
        sy, sz = max(sy, sx * 1.12), min(sz, sx * 0.92)
    return sx, sy, sz


def _foot_height(spec: dict, height: float) -> float:
    if spec["feet"] == "ball":
        return spec["legs"]["thickness"] * height * 1.15
    return 0.046 * height


def _stack(height: float, head_h: float, leg_len: float, foot: float) -> dict:
    leg_bottom = max(0.0, foot - 0.018 * height)
    leg_top = leg_bottom + leg_len
    head_y = height - head_h / 2
    overlap = max(0.045 * height, head_h * 0.20)
    torso_top = head_y - head_h / 2 + overlap
    torso_bottom = leg_top - 0.09 * height
    if torso_top - torso_bottom < 0.14 * height:
        raise BlobTraitsError("invalid_proportions", "The head and the legs leave no room for a torso")
    return {"head_y": head_y, "torso_top": torso_top, "torso_bottom": torso_bottom, "leg_bottom": leg_bottom, "leg_top": leg_top}


def _p(kind, pos, scale, color, rot=(0.0, 0.0, 0.0), segments=None) -> dict:
    item = {
        "type": kind,
        "position": [float(v) for v in pos],
        "scale": [float(v) for v in scale],
        "rotation": [float(v) for v in rot],
        "color": color,
    }
    if segments is not None:
        item["segments"] = int(segments)
    return item


def _mirror(item: dict) -> dict:
    other = _p(item["type"], (-item["position"][0], item["position"][1], item["position"][2]), item["scale"], item["color"],
               (item["rotation"][0], -item["rotation"][1], -item["rotation"][2]), item.get("segments"))
    return other


def _pair(item: dict) -> list:
    return [item, _mirror(item)]


def _torso(spec: dict, layout: dict) -> list:
    colors = spec["colors"]
    skin, top = colors["head"], colors["top"]
    neck_h = min(0.04 * layout["h"], (layout["torso_top"] - (layout["head_y"] - layout["sy"] / 2)) * 0.8)
    neck_y = layout["torso_top"] - neck_h / 2
    belly_d = layout["sx"] * layout["belly"]
    belly_y = layout["torso_y"] - (layout["drop"] - 0.5) * layout["torso_h"] * 0.65
    belly_z = layout["torso_d"] * 0.5 * layout["forward"] * 0.45
    return [
        _p("sphere", (0, layout["head_y"], 0), (layout["sx"], layout["sy"], layout["sz"]), skin, segments=HEAD_SEGMENTS),
        _p("cylinder", (0, neck_y, 0), (layout["sx"] * 0.34, max(neck_h, 0.02 * layout["h"]), layout["sz"] * 0.34), skin, segments=LIMB_SEGMENTS),
        _p("cylinder", (0, layout["torso_y"], 0), (layout["torso_w"], layout["torso_h"], layout["torso_d"]), top, segments=BODY_SEGMENTS),
        _p("sphere", (0, belly_y, belly_z), (belly_d, belly_d * 0.82, belly_d * 0.72), top, segments=BODY_SEGMENTS),
    ]


def _arms(spec: dict, layout: dict) -> list:
    colors = spec["colors"]
    sleeve, skin = colors["sleeves"], colors["hands"]
    diameter = layout["arm_d"]
    upper, fore = layout["arm_len"] * 0.46, layout["arm_len"] * 0.40
    inset = upper * 0.38
    half = layout["torso_w"] / 2
    upper_x = half - inset + upper / 2
    fore_x = upper_x + upper / 2 - fore * 0.18 + fore / 2
    hand_reach = diameter * (0.85 if spec["hands"] == "mitten" else 0.62)
    hand_x = fore_x + fore / 2 - hand_reach * 0.35
    y = layout["shoulder_y"]
    turn = (0.0, 0.0, _HALF_TURN)
    arm = [
        *_pair(_p("cylinder", (upper_x, y, 0), (diameter, upper, diameter), sleeve, turn, LIMB_SEGMENTS)),
        *_pair(_p("cylinder", (fore_x, y, 0), (diameter * 0.92, fore, diameter * 0.92), sleeve, turn, LIMB_SEGMENTS)),
    ]
    if spec["hands"] == "mitten":
        arm += _pair(_p("box", (hand_x, y, 0), (diameter * 1.35, diameter * 1.05, diameter * 0.62), skin))
    else:
        arm += _pair(_p("sphere", (hand_x, y, 0), (hand_reach * 2, hand_reach * 2, hand_reach * 2), skin, segments=LIMB_SEGMENTS))
    return arm


def _legs(spec: dict, layout: dict) -> list:
    colors = spec["colors"]
    gap = max(0.04 * layout["h"], layout["leg_d"] * 0.4)
    x = gap / 2 + layout["leg_d"] / 2
    y = (layout["leg_bottom"] + layout["leg_top"]) / 2
    legs = _pair(_p("cylinder", (x, y, 0), (layout["leg_d"], layout["leg_len"], layout["leg_d"]), colors["bottom"], segments=LIMB_SEGMENTS))
    if spec["feet"] == "ball":
        size = layout["foot"]
        return legs + _pair(_p("sphere", (x, size / 2, 0), (size, size, size), colors["shoes"], segments=LIMB_SEGMENTS))
    height, depth = layout["foot"], layout["leg_d"] * 1.85
    return legs + _pair(_p("box", (x, height / 2, depth * 0.12), (layout["leg_d"] * 1.15, height, depth), colors["shoes"]))


def _anchor(layout: dict) -> dict:
    center = [0.0, layout["head_y"], 0.0]
    radii = [layout["sx"] / 2, layout["sy"] / 2, layout["sz"] / 2]
    return {"center": center, "radii": radii, "front": [center[0], center[1], center[2] + radii[2]]}


def _accessory_pieces(spec: dict, layout: dict) -> list:
    made = []
    for item in spec["accessories"]:
        made.extend(_ACCESSORY_BUILDERS[item["kind"]](layout, item["color"]))
    return made


def _cap(layout, color):
    crown_h = 0.045 * layout["h"]
    top = layout["head_y"] + layout["sy"] / 2
    brim_y = layout["head_y"] + layout["sy"] * 0.18
    return [
        _p("cylinder", (0, top - crown_h * 0.35, 0), (layout["sx"] * 0.78, crown_h, layout["sz"] * 0.78), color, segments=LIMB_SEGMENTS),
        _p("box", (0, brim_y, layout["sz"] * 0.42), (layout["sx"] * 0.62, 0.012 * layout["h"], layout["sz"] * 0.42), color),
    ]


def _sailor_cap(layout, color):
    top = layout["head_y"] + layout["sy"] / 2
    disk_h = 0.028 * layout["h"]
    crown_h = 0.055 * layout["h"]
    return [
        _p("cylinder", (0, top - disk_h * 0.25, 0), (layout["sx"] * 1.06, disk_h, layout["sz"] * 1.06), color, segments=LIMB_SEGMENTS),
        _p("cylinder", (0, top + crown_h * 0.35, 0), (layout["sx"] * 0.62, crown_h, layout["sz"] * 0.62), color, segments=LIMB_SEGMENTS),
    ]


def _top_hat(layout, color):
    brim_y = layout["head_y"] + layout["sy"] * 0.30
    crown_h = 0.11 * layout["h"]
    brim_h = 0.016 * layout["h"]
    return [
        _p("cylinder", (0, brim_y, 0), (layout["sx"] * 1.12, brim_h, layout["sz"] * 1.12), color, segments=LIMB_SEGMENTS),
        _p("cylinder", (0, brim_y + crown_h / 2, 0), (layout["sx"] * 0.62, crown_h, layout["sz"] * 0.62), color, segments=LIMB_SEGMENTS),
    ]


def _beanie(layout, color):
    return [_p("sphere", (0, layout["head_y"] + layout["sy"] * 0.28, 0),
               (layout["sx"] * 0.90, layout["sy"] * 0.55, layout["sz"] * 0.90), color, segments=HEAD_SEGMENTS)]


def _bucket_hat(layout, color):
    brim_y = layout["head_y"] + layout["sy"] * 0.12
    crown_h = 0.05 * layout["h"]
    return [
        _p("cylinder", (0, brim_y + crown_h * 0.45, 0), (layout["sx"] * 0.84, crown_h, layout["sz"] * 0.84), color, segments=LIMB_SEGMENTS),
        _p("cylinder", (0, brim_y, 0), (layout["sx"] * 1.16, 0.014 * layout["h"], layout["sz"] * 1.16), color, segments=LIMB_SEGMENTS),
    ]


def _apron(layout, color):
    width, height = layout["torso_w"] * 0.70, layout["torso_h"] * 0.62
    y = layout["torso_bottom"] + layout["torso_h"] * 0.42
    return [_p("box", (0, y, layout["torso_d"] * 0.42), (width, height, 0.02 * layout["h"]), color)]


def _tie(layout, color):
    return [_p("box", (0, layout["torso_y"] + layout["torso_h"] * 0.08, layout["torso_d"] * 0.48),
               (0.028 * layout["h"], layout["torso_h"] * 0.42, 0.016 * layout["h"]), color)]


def _collar(layout, color):
    y = layout["head_y"] - layout["sy"] * 0.38
    return [_p("box", (0, y, layout["sz"] * 0.36), (layout["sx"] * 0.28, 0.022 * layout["h"], 0.04 * layout["h"]), color)]


def _belt(layout, color):
    y = layout["torso_y"] - layout["torso_h"] * 0.28
    return [_p("cylinder", (0, y, 0), (layout["torso_w"] * 1.06, 0.026 * layout["h"], layout["torso_d"] * 1.08), color, segments=LIMB_SEGMENTS)]


def _backpack(layout, color):
    # The box bites the torso. A deep torso used to leave it floating behind the body.
    depth = max(0.08 * layout["h"], layout["torso_d"] * 0.36)
    bite = depth * 0.40
    z = -(layout["torso_d"] / 2 + depth / 2 - bite)
    return [_p("box", (0, layout["torso_y"] + layout["torso_h"] * 0.06, z),
               (layout["torso_w"] * 0.52, layout["torso_h"] * 0.40, depth), color)]


def _scarf(layout, color):
    y = layout["torso_top"] - 0.01 * layout["h"]
    return [_p("cylinder", (0, y, 0), (layout["torso_w"] * 0.78, 0.03 * layout["h"], layout["torso_d"] * 0.90), color, segments=LIMB_SEGMENTS)]


_ACCESSORY_BUILDERS = {
    "cap": _cap, "sailor_cap": _sailor_cap, "top_hat": _top_hat, "beanie": _beanie, "bucket_hat": _bucket_hat,
    "apron": _apron, "tie": _tie, "collar": _collar, "belt": _belt, "backpack": _backpack, "scarf": _scarf,
}
