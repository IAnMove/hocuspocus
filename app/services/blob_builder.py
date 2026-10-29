"""Round-headed bodies as overlapped primitives. Pure: no files, no rig, no GPU.

Metres, Y up, +Z forward. ``scale`` is the full size (the diameter), the same
rule as ``model3d.compose``. Pieces overlap on purpose. Arms are a T, feet sit
on y = 0. A blob head stays wider than its torso. Anime shoulders are wider
than the small head, and the neck between them is the narrow notch the rig uses.
"""
from __future__ import annotations

import math

HEAD_SEGMENTS = 32
LIMB_SEGMENTS = 12
BODY_SEGMENTS = 16
_HALF_TURN = round(math.pi / 2, 6)

_FIELDS = {"height", "build", "family", "head", "arms", "legs", "hands", "feet", "colors", "accessories", "hair", "mesh", "outfit"}
_MESHES = ("pieces", "loft")
_OUTFITS = ("school", "casual", "sport")
_BUILDS = ("slim", "average", "round", "pear")
_FAMILIES = ("blob", "anime", "chibi")
_HANDS = ("ball", "mitten")
_FEET = ("shoe", "ball", "boot")
_SHAPES = ("sphere", "egg", "anime", "chibi")
_HAIR_STYLES = ("none", "short", "bangs", "spiky", "long", "ponytail", "twin_tails", "bun", "bob")
_HAIR_COLOR = "#2A211C"
# Torso width and depth, and the belly, as fractions of the head. The torso stays
# narrower than the head. The belly carries the round and pear silhouettes.
_BUILD = {
    "slim": (0.64, 0.70, 0.52, 0.00, 0.50),
    "average": (0.74, 0.84, 0.72, 0.18, 0.55),
    "round": (0.84, 1.05, 0.98, 0.32, 0.48),
    "pear": (0.70, 0.90, 1.04, 0.28, 0.74),
}
_HEAD_DEFAULT = {"width": 0.31, "height": 0.28, "depth": 0.26, "shape": "sphere"}
_ANIME_HEAD = {"width": 0.138, "height": 0.140, "depth": 0.128, "shape": "anime"}
_CHIBI_HEAD = {"width": 0.42, "height": 0.38, "depth": 0.36, "shape": "chibi"}
_HEAD_LIMITS = {"width": (0.12, 0.46), "height": (0.12, 0.44), "depth": (0.11, 0.42)}
_ARM_DEFAULT = {"length": 0.36, "thickness": 0.055}
_ANIME_ARMS = {"length": 0.44, "thickness": 0.040}
_CHIBI_ARMS = {"length": 0.30, "thickness": 0.070}
_ARM_LIMITS = {"length": (0.26, 0.50), "thickness": (0.030, 0.080)}
_LEG_DEFAULT = {"length": 0.42, "thickness": 0.070}
_ANIME_LEGS = {"length": 0.52, "thickness": 0.050}
_CHIBI_LEGS = {"length": 0.36, "thickness": 0.088}
_LEG_LIMITS = {"length": (0.30, 0.56), "thickness": (0.040, 0.100)}
_FAMILY = {
    "blob": {"head": dict(_HEAD_DEFAULT), "arms": dict(_ARM_DEFAULT), "legs": dict(_LEG_DEFAULT)},
    "anime": {"head": dict(_ANIME_HEAD), "arms": dict(_ANIME_ARMS), "legs": dict(_ANIME_LEGS)},
    "chibi": {"head": dict(_CHIBI_HEAD), "arms": dict(_CHIBI_ARMS), "legs": dict(_CHIBI_LEGS)},
}
# Shoulder width as a fraction of height (anime) or of the head (chibi). Waist and hip are fractions of that shoulder.
# Narrow: an anime shoulder line is about a head and a half wide, so a painted bust on the head plane covers it.
_ANIME_SHOULDER = {"slim": 0.18, "average": 0.22, "round": 0.27, "pear": 0.23}
_ANIME_WAIST = {"slim": 0.58, "average": 0.66, "round": 0.84, "pear": 0.72}
_CHIBI_SHOULDER = {"slim": 0.62, "average": 0.70, "round": 0.78, "pear": 0.74}
# Fraction of the torso height, measured from the hip. Blob and chibi stay low:
# 0.46 already swings lanky's wave through the egg. Anime sits up at the shoulder.
_SHOULDER_AT = {"blob": 0.40, "anime": 0.74, "chibi": 0.46}
# Drawn reach as a fraction of height. The stored trait can be longer; a wave folds that reach up.
# Anime arms end near the hip, not the knee: 0.42 of the height from the shoulder.
_ARM_CAP = {"blob": 0.30, "anime": 0.42, "chibi": 0.26}
_COLOR_DEFAULT = {
    "head": "#F2C7A0", "top": "#3A6EA5", "sleeves": "#F2C7A0",
    "bottom": "#2C3340", "shoes": "#201A18", "hands": "#F2C7A0",
}
_ACCESSORY_KINDS = (
    "cap", "sailor_cap", "top_hat", "beanie", "bucket_hat",
    "apron", "tie", "collar", "belt", "backpack", "scarf",
    "skirt", "jacket", "sleeves_long", "shorts", "school_collar", "cape",
)
_ACCESSORY_COLOR = {
    "cap": "#C45C4A", "sailor_cap": "#F4F1EA", "top_hat": "#161616", "beanie": "#2C4C7C",
    "bucket_hat": "#D8C39A", "apron": "#E8E0D0", "tie": "#8C1D2C", "collar": "#F4F4F2",
    "belt": "#2A211C", "backpack": "#3E4A3A", "scarf": "#B23A48",
    "skirt": "#1B2350", "jacket": "#1A1A1A", "sleeves_long": "#F4F4F2",
    "shorts": "#2C3340", "school_collar": "#F7F4EF", "cape": "#6B1D2A",
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
    "blob_chef": {
        "height": 1.72, "build": "round", "family": "blob", "hands": "mitten",
        "colors": {"head": "#F2C7A0", "top": "#F7F4EF", "sleeves": "#F7F4EF", "bottom": "#1C1C1C", "shoes": "#1C1C1C", "hands": "#F2C7A0"},
        "accessories": [{"kind": "top_hat", "color": "#F4F4F2"}, {"kind": "apron", "color": "#EFE6D6"}],
    },
    "blob_pirate": {
        "height": 1.84, "build": "pear", "family": "blob", "feet": "boot", "hands": "mitten",
        "colors": {"head": "#E0B090", "top": "#6B1D2A", "sleeves": "#F2C7A0", "bottom": "#2A211C", "shoes": "#1A120E", "hands": "#E0B090"},
        "accessories": [{"kind": "beanie", "color": "#1A120E"}, {"kind": "scarf", "color": "#8C1D2C"}, {"kind": "belt", "color": "#C4A35A"}],
    },
    "blob_scout": {
        "height": 1.58, "build": "slim", "family": "blob", "hands": "mitten",
        "hair": {"style": "short", "color": "#6B4423"},
        "colors": {"head": "#F0C09A", "top": "#2F6B3A", "sleeves": "#F2E6C9", "bottom": "#C4A35A", "shoes": "#3A2A22", "hands": "#F0C09A"},
        "accessories": [{"kind": "beanie", "color": "#2F6B3A"}, {"kind": "shorts", "color": "#C4A35A"}, {"kind": "backpack", "color": "#6B4423"}],
    },
    "anime_girl": {
        "height": 1.65, "build": "slim", "family": "anime", "hands": "mitten",
        "head": dict(_ANIME_HEAD), "hair": {"style": "long", "color": "#1A1428"},
        "colors": {"head": "#F3D0B8", "top": "#F7F4EF", "sleeves": "#F7F4EF", "bottom": "#1B2350", "shoes": "#201A18", "hands": "#F3D0B8"},
        "accessories": [{"kind": "school_collar", "color": "#F7F4EF"}, {"kind": "skirt", "color": "#1B2350"}, {"kind": "sleeves_long", "color": "#F7F4EF"}],
    },
    "anime_boy": {
        "height": 1.78, "build": "average", "family": "anime", "hands": "mitten",
        "head": dict(_ANIME_HEAD), "hair": {"style": "spiky", "color": "#3D2A1A"},
        "colors": {"head": "#E8C0A0", "top": "#F4F1EA", "sleeves": "#E8C0A0", "bottom": "#2C3340", "shoes": "#201A18", "hands": "#E8C0A0"},
        "accessories": [{"kind": "jacket", "color": "#2E5A8C"}, {"kind": "shorts", "color": "#2C3340"}, {"kind": "school_collar", "color": "#F4F1EA"}],
    },
    "anime_senpai": {
        "height": 1.90, "build": "slim", "family": "anime", "hands": "mitten",
        "head": dict(_ANIME_HEAD), "hair": {"style": "ponytail", "color": "#2A1A12"},
        "colors": {"head": "#E8C4A4", "top": "#161616", "sleeves": "#E8C4A4", "bottom": "#1A1A1A", "shoes": "#111111", "hands": "#E8C4A4"},
        "accessories": [{"kind": "jacket", "color": "#161616"}, {"kind": "cape", "color": "#4A1C2A"}],
    },
    "chibi_kid": {
        "height": 1.24, "build": "round", "family": "chibi", "hands": "ball",
        "head": dict(_CHIBI_HEAD), "hair": {"style": "bangs", "color": "#5A3318"},
        "colors": {"head": "#F0C09A", "top": "#F08A24", "sleeves": "#F2D24A", "bottom": "#3C6EBE", "shoes": "#F4F4F2", "hands": "#F0C09A"},
    },
    "chibi_mage": {
        "height": 1.34, "build": "round", "family": "chibi", "hands": "mitten",
        "head": dict(_CHIBI_HEAD), "hair": {"style": "bun", "color": "#E4D8F0"},
        "colors": {"head": "#F2C7A0", "top": "#5C3A8A", "sleeves": "#5C3A8A", "bottom": "#3A2060", "shoes": "#2A1840", "hands": "#F2C7A0"},
        "accessories": [{"kind": "top_hat", "color": "#2A1840"}, {"kind": "skirt", "color": "#3A2060"}, {"kind": "cape", "color": "#2A1848"}],
    },
    "chibi_knight": {
        "height": 1.40, "build": "average", "family": "chibi", "feet": "boot", "hands": "mitten",
        "head": dict(_CHIBI_HEAD), "hair": {"style": "short", "color": "#3A2A22"},
        "colors": {"head": "#E8C4A4", "top": "#8A8E96", "sleeves": "#8A8E96", "bottom": "#4A4E56", "shoes": "#2A2E34", "hands": "#E8C4A4"},
        "accessories": [{"kind": "bucket_hat", "color": "#C0C4CC"}, {"kind": "cape", "color": "#A32020"}, {"kind": "belt", "color": "#C4A35A"}],
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
    """Limits, defaults and the fifteen named presets. The face (moustache, glasses) is not here."""
    return {
        "height": {"min": 1.2, "max": 2.2, "default": 1.8, "unit": "m"},
        "build": list(_BUILDS),
        "family": list(_FAMILIES),
        "head": {"limits": _HEAD_LIMITS, "shape": list(_SHAPES), "default": dict(_HEAD_DEFAULT),
                 "note": "width, height and depth are fractions of the body height. Omit family for a blob. "
                         "anime is about 7 heads tall. chibi is about 2.5 to 3."},
        "arms": {"limits": _ARM_LIMITS, "default": dict(_ARM_DEFAULT)},
        "legs": {"limits": _LEG_LIMITS, "default": dict(_LEG_DEFAULT)},
        "hands": list(_HANDS), "feet": list(_FEET),
        "hair": {"style": list(_HAIR_STYLES), "default": {"style": "none", "color": _HAIR_COLOR}},
        "mesh": {"choices": list(_MESHES), "default": "pieces", "note": "loft (anime only) is one smooth lofted body: tapered limbs, a jaw, hair geometry, clothes as colour regions."},
        "outfit": {"choices": list(_OUTFITS), "default": "school", "note": "With mesh loft: school (collar, bow or tie, skirt or trousers), casual (short sleeves, shorts or skirt, sneakers), sport (tracksuit, sneakers)."},
        "colors": {"fields": list(_COLOR_DEFAULT), "default": dict(_COLOR_DEFAULT), "format": "#RRGGBB"},
        "accessories": {"kinds": list(_ACCESSORY_KINDS), "max": _MAX_ACCESSORIES, "defaultColor": dict(_ACCESSORY_COLOR),
                        "notHere": ["moustache", "glasses", "eyebrows", "freckles"]},
        "presets": {name: _copy(traits) for name, traits in PRESETS.items()},
    }


def blob_pieces(traits: dict | None = None) -> dict:
    """``{pieces, faceAnchor, traits}`` for one body. Unknown fields raise ``BlobTraitsError``."""
    spec = _normalize({} if traits is None else traits)
    pieces, anchor = _assemble(spec)
    if spec.get("mesh") == "loft":
        return {"pieces": pieces, "faceAnchor": anchor, "traits": spec, "layout": _layout(spec)}
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
    family = _choice(traits.get("family", "blob"), _FAMILIES, "invalid_family", "family")
    stock = _FAMILY[family]
    mesh = _choice(traits.get("mesh", "pieces"), _MESHES, "invalid_mesh", "mesh")
    if mesh == "loft" and family != "anime":
        _fail("invalid_mesh", "mesh loft is for the anime family")
    outfit = _choice(traits.get("outfit", "school"), _OUTFITS, "invalid_outfit", "outfit")
    if "outfit" in traits and mesh != "loft":
        _fail("invalid_outfit", "outfit is for a lofted body (mesh loft)")
    return {
        **({"mesh": mesh} if "mesh" in traits else {}),
        **({"outfit": outfit} if "outfit" in traits else {}),
        "height": _height(traits.get("height", 1.8)),
        "build": _choice(traits.get("build", "average"), _BUILDS, "invalid_build", "build"),
        "family": family,
        "head": _head(traits.get("head"), stock["head"]),
        "arms": _pair_size(traits.get("arms"), stock["arms"], _ARM_LIMITS, "invalid_arms", "arms"),
        "legs": _pair_size(traits.get("legs"), stock["legs"], _LEG_LIMITS, "invalid_legs", "legs"),
        "hands": _choice(traits.get("hands", "ball"), _HANDS, "invalid_hands", "hands"),
        "feet": _choice(traits.get("feet", "shoe"), _FEET, "invalid_feet", "feet"),
        "colors": _colors(traits.get("colors")),
        "hair": _hair(traits.get("hair")),
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


def _head(value, default: dict) -> dict:
    if value is None:
        return dict(default)
    if not isinstance(value, dict):
        _fail("invalid_head", "head must be an object with width, height, depth and shape")
    extra = set(value) - set(_HEAD_DEFAULT)
    if extra:
        _fail("unknown_field", "Unknown head field: " + ", ".join(sorted(extra)))
    found = dict(default)
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


def _hair(value) -> dict:
    if value is None:
        return {"style": "none", "color": _HAIR_COLOR}
    if not isinstance(value, dict):
        _fail("invalid_hair", "hair must be an object with style and color")
    extra = set(value) - {"style", "color"}
    if extra:
        _fail("unknown_field", "Unknown hair field: " + ", ".join(sorted(extra)))
    style = value.get("style", "none")
    if style not in _HAIR_STYLES:
        _fail("invalid_hair", "hair.style must be one of: " + ", ".join(_HAIR_STYLES))
    color = _HAIR_COLOR if "color" not in value else _hex(value["color"], "hair.color")
    return {"style": style, "color": color}


def _assemble(spec: dict) -> tuple[list, dict]:
    from services.blob_wear import hair_pieces

    layout = _layout(spec)
    pieces = _torso(spec, layout) + _arms(spec, layout) + _legs(spec, layout)
    pieces += _accessory_pieces(spec, layout)
    pieces += hair_pieces(layout, spec["hair"])
    return pieces, _anchor(layout)


def _layout(spec: dict) -> dict:
    height = spec["height"]
    sx, sy, sz = _head_size(spec["head"], height)
    torso_w, torso_d, waist_w, belly, forward, drop = _widths(spec, sx, sz, height)
    foot = _foot_height(spec, height)
    leg_len, leg_d = spec["legs"]["length"] * height, spec["legs"]["thickness"] * height
    stack = _stack(height, sy, leg_len, foot)
    torso_h = stack["torso_top"] - stack["torso_bottom"]
    arm_d = min(spec["arms"]["thickness"] * height, torso_w * 0.45)
    # A wave folds the forearm up by about a third of the reach. A wide head meets a longer arm.
    arm_len = min(spec["arms"]["length"], _ARM_CAP[spec["family"]]) * height
    upper_x, fore_x, upper_len, fore_len, wrist_x, tip_x = _arm_centers(torso_w / 2, torso_w, arm_len)
    gap = max(0.045 * height, leg_d * 0.55)
    # Above the belly. Higher than about half the torso swings a bent wave into the head.
    shoulder_at = _SHOULDER_AT[spec["family"]]
    return {
        "h": height, "sx": sx, "sy": sy, "sz": sz, "head_y": stack["head_y"],
        "torso_w": torso_w, "torso_d": torso_d, "torso_h": torso_h, "waist_w": waist_w,
        "waist_taper": min(1.0, max(0.35, waist_w / torso_w)) if spec["family"] == "anime" else 1.0,
        "torso_y": (stack["torso_top"] + stack["torso_bottom"]) / 2,
        "torso_top": stack["torso_top"], "torso_bottom": stack["torso_bottom"],
        "shoulder_y": stack["torso_bottom"] + torso_h * shoulder_at,
        "waist_y": stack["torso_bottom"] + torso_h * 0.22,
        "knee": stack["leg_bottom"] + leg_len * 0.46,
        "leg_len": leg_len, "leg_d": leg_d, "leg_x": gap / 2 + leg_d / 2,
        "leg_bottom": stack["leg_bottom"], "leg_top": stack["leg_top"], "foot": foot,
        "belly": belly, "forward": forward, "drop": drop,
        "arm_len": arm_len, "arm_d": arm_d,
        "upper_x": upper_x, "fore_x": fore_x, "upper_len": upper_len, "fore_len": fore_len,
        "elbow_x": upper_x + upper_len / 2, "wrist_x": wrist_x, "tip_x": tip_x,
    }


def _widths(spec: dict, sx: float, sz: float, height: float):
    width, depth, belly, forward, drop = _BUILD[spec["build"]]
    if spec["family"] == "anime":
        shoulder = height * _ANIME_SHOULDER[spec["build"]]
        return shoulder, height * 0.115, shoulder * _ANIME_WAIST[spec["build"]], belly, forward, drop
    if spec["family"] == "chibi":
        shoulder = sx * _CHIBI_SHOULDER[spec["build"]]
        return shoulder, min(sz * 0.82, sx * 0.78), shoulder * 0.90, belly, forward, drop
    torso_w = sx * width
    return torso_w, min(sz * depth, sx * 0.95), torso_w * 0.92, belly, forward, drop


def _arm_centers(arm_root: float, torso_w: float, arm_len: float):
    # The rig puts the elbow at 44% of the reach and the wrist at 76%. Pieces follow that line, or a vertex past the elbow is shared by two bones and tears when the arm swings.
    shoulder = arm_root
    elbow = shoulder + arm_len * 0.44
    wrist = shoulder + arm_len * 0.76
    inner = shoulder - min(torso_w * 0.08, arm_len * 0.04)
    upper_len = elbow - inner
    gap = wrist - elbow
    return (inner + elbow) / 2, elbow + gap * 0.45, upper_len, gap * 1.15, wrist, shoulder + arm_len


def _head_size(head: dict, height: float) -> tuple[float, float, float]:
    sx, sy, sz = head["width"] * height, head["height"] * height, head["depth"] * height
    if head["shape"] == "egg":
        sy, sz = max(sy, sx * 1.12), min(sz, sx * 0.92)
    elif head["shape"] == "anime":
        sy, sz = max(sy, sx * 1.08), min(sz, sx * 0.96)
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


def _p(kind, pos, scale, color, rot=(0.0, 0.0, 0.0), segments=None, taper=None) -> dict:
    item = {
        "type": kind,
        "position": [float(v) for v in pos],
        "scale": [float(v) for v in scale],
        "rotation": [float(v) for v in rot],
        "color": color,
    }
    if segments is not None:
        item["segments"] = int(segments)
    if kind != "box":
        item["smooth"] = True
    if taper is not None:
        item["taper"] = float(taper)
    return item


def _mirror(item: dict) -> dict:
    return _p(item["type"], (-item["position"][0], item["position"][1], item["position"][2]), item["scale"], item["color"],
              (item["rotation"][0], -item["rotation"][1], -item["rotation"][2]), item.get("segments"), item.get("taper"))


def _pair(item: dict) -> list:
    return [item, _mirror(item)]


def _torso(spec: dict, layout: dict) -> list:
    return _head_pieces(spec, layout) + _neck(spec, layout) + _chest(spec, layout) + _shoulders(spec, layout) + _hips(spec, layout)


def _head_pieces(spec: dict, layout: dict) -> list:
    skin = spec["colors"]["head"]
    main = _p("sphere", (0, layout["head_y"], 0), (layout["sx"], layout["sy"], layout["sz"]), skin, segments=HEAD_SEGMENTS)
    shape = spec["head"]["shape"]
    if shape == "anime":
        return [main, *_jaw(layout, skin)]
    if shape == "chibi":
        return [main, _chin(layout, skin)]
    return [main]


def _jaw(layout: dict, skin: str) -> list:
    """Two spheres inside the cranium so the chin reads and the face anchor stays the cranium."""
    sx, sy, sz, y = layout["sx"], layout["sy"], layout["sz"], layout["head_y"]
    jaw = _p("sphere", (0, y - sy * 0.20, sz * 0.16), (sx * 0.70, sy * 0.40, sz * 0.58), skin, segments=BODY_SEGMENTS)
    chin = _p("sphere", (0, y - sy * 0.32, sz * 0.24), (sx * 0.32, sy * 0.20, sz * 0.26), skin, segments=LIMB_SEGMENTS)
    return [jaw, chin]


def _chin(layout: dict, skin: str) -> dict:
    sx, sy, sz, y = layout["sx"], layout["sy"], layout["sz"], layout["head_y"]
    return _p("sphere", (0, y - sy * 0.30, sz * 0.20), (sx * 0.40, sy * 0.22, sz * 0.28), skin, segments=LIMB_SEGMENTS)


def _neck(spec: dict, layout: dict) -> list:
    skin = spec["colors"]["head"]
    share = {"blob": 0.062, "anime": 0.078, "chibi": 0.045}[spec["family"]]
    neck_h = max(share * layout["h"], layout["sy"] * 0.16)
    top = layout["head_y"] - layout["sy"] * 0.28
    y = top - neck_h / 2
    width = min(layout["sx"] * 0.42, layout["torso_w"] * 0.70)
    depth = min(layout["sz"] * 0.42, layout["torso_d"] * 0.70)
    return [_p("capsule", (0, y, 0), (width, neck_h, depth), skin, segments=LIMB_SEGMENTS)]


def _chest(spec: dict, layout: dict) -> list:
    top = spec["colors"]["top"]
    if spec["family"] == "anime":
        return torso_shell(layout, top, taper=layout["waist_taper"])
    belly_d = layout["sx"] * layout["belly"]
    belly_y = layout["torso_y"] - (layout["drop"] - 0.5) * layout["torso_h"] * 0.65
    belly_z = layout["torso_d"] * 0.5 * layout["forward"] * 0.45
    return [*torso_shell(layout, top), _p("sphere", (0, belly_y, belly_z), (belly_d, belly_d * 0.82, belly_d * 0.72), top, segments=BODY_SEGMENTS)]


def torso_shell(layout: dict, color: str, grow: float = 1.0, taper: float | None = None) -> list:
    """A barrel under a dome. A flat top reads as a shelf wider than the neck; the dome rounds the shoulders and keeps the top where it was.

    ``taper`` narrows the bottom (anime waist). ``grow`` makes a garment a little bigger than the body it covers.
    """
    width, depth = layout["torso_w"] * grow, layout["torso_d"] * grow
    dome = min(width * 0.40, layout["torso_h"] * 0.34)
    barrel_h = layout["torso_h"] - dome
    barrel_y = layout["torso_bottom"] + barrel_h / 2
    cap = _p("sphere", (0, layout["torso_bottom"] + barrel_h, 0), (width, dome * 2, depth), color, segments=BODY_SEGMENTS)
    if taper is None:
        return [_p("cylinder", (0, barrel_y, 0), (width, barrel_h, depth), color, segments=BODY_SEGMENTS), cap]
    # Local bottom is the wide end. Half a turn about X puts the shoulders on top.
    return [_p("frustum", (0, barrel_y, 0), (width, barrel_h, depth), color, (math.pi, 0.0, 0.0), BODY_SEGMENTS, taper), cap]


def _shoulders(spec: dict, layout: dict) -> list:
    # An anime shoulder is the sleeve's own round end, not a ball wider than the arm: the sphere stays inside the sleeve.
    diameter = layout["arm_d"] if spec["family"] == "anime" else max(layout["arm_d"] * 1.35, layout["h"] * 0.045)
    item = _p("sphere", (layout["torso_w"] / 2, layout["shoulder_y"], 0), (diameter, diameter, diameter), spec["colors"]["top"], segments=LIMB_SEGMENTS)
    return _pair(item)


def _hips(spec: dict, layout: dict) -> list:
    diameter = layout["leg_d"] * 1.12
    item = _p("sphere", (layout["leg_x"], layout["leg_top"], 0), (diameter, diameter, diameter * 0.9), spec["colors"]["bottom"], segments=LIMB_SEGMENTS)
    return _pair(item)


def _arms(spec: dict, layout: dict) -> list:
    sleeve, skin = spec["colors"]["sleeves"], spec["colors"]["hands"]
    diameter, y = layout["arm_d"], layout["shoulder_y"]
    turn = (0.0, 0.0, _HALF_TURN)
    # An anime arm is one smooth tube: the elbow sphere and the forearm keep the upper arm's diameter, so no ball and no step
    # draw an ink ring at the elbow. Blob and chibi keep their thinner forearm and smaller elbow.
    anime = spec["family"] == "anime"
    elbow_k, fore_k = (1.0, 1.0) if anime else (0.82, 0.86)
    elbow = (diameter * elbow_k, diameter * elbow_k, diameter * elbow_k)
    arm = [
        *_pair(_p("capsule", (layout["upper_x"], y, 0), (diameter, layout["upper_len"], diameter), sleeve, turn, LIMB_SEGMENTS)),
        *_pair(_p("sphere", (layout["elbow_x"], y, 0), elbow, sleeve, segments=LIMB_SEGMENTS)),
        *_pair(_p("capsule", (layout["fore_x"], y, 0), (diameter * fore_k, layout["fore_len"], diameter * fore_k), sleeve, turn, LIMB_SEGMENTS)),
    ]
    return arm + _hands(spec, layout, skin, diameter, y, turn)


def _hands(spec: dict, layout: dict, skin: str, diameter: float, y: float, turn: tuple) -> list:
    wrist_at, tip = layout["wrist_x"], layout["tip_x"]
    span = max(tip - wrist_at, diameter * 0.8)
    wrist_len = span * 0.62
    wrist_x = wrist_at + wrist_len * 0.42
    wrist = _pair(_p("capsule", (wrist_x, y, 0), (diameter * 0.70, wrist_len, diameter * 0.70), skin, turn, LIMB_SEGMENTS))
    hand_x = tip - span * 0.26
    if spec["hands"] == "mitten":
        palm = _pair(_p("sphere", (hand_x, y, 0), (span * 0.62, diameter * 0.88, diameter * 0.62), skin, segments=LIMB_SEGMENTS))
        thumb = _pair(_p("sphere", (hand_x - span * 0.06, y + diameter * 0.28, diameter * 0.36), (diameter * 0.40, diameter * 0.40, diameter * 0.40), skin, segments=LIMB_SEGMENTS))
        return wrist + palm + thumb
    ball = min(span * 0.72, diameter * 1.35)
    return wrist + _pair(_p("sphere", (tip - ball * 0.42, y, 0), (ball, ball, ball), skin, segments=LIMB_SEGMENTS))


def _legs(spec: dict, layout: dict) -> list:
    x = layout["leg_x"]
    y = (layout["leg_bottom"] + layout["leg_top"]) / 2
    legs = _pair(_p("capsule", (x, y, 0), (layout["leg_d"], layout["leg_len"], layout["leg_d"]), spec["colors"]["bottom"], segments=LIMB_SEGMENTS))
    return legs + _feet(spec, layout)


def _feet(spec: dict, layout: dict) -> list:
    x, shoes, diameter = layout["leg_x"], spec["colors"]["shoes"], layout["leg_d"]
    if spec["feet"] == "ball":
        size = layout["foot"]
        ankle_r = diameter * 0.42
        ankle = _pair(_p("sphere", (x, size * 0.62, 0), (ankle_r * 2, ankle_r * 2, ankle_r * 2), shoes, segments=LIMB_SEGMENTS))
        ball = _pair(_p("sphere", (x, size / 2, diameter * 0.2), (size, size, size), shoes, segments=LIMB_SEGMENTS))
        return ankle + ball
    sole_h = layout["foot"] * (0.46 if spec["feet"] == "boot" else 0.40)
    sole_d = diameter * (2.15 if spec["feet"] == "boot" else 1.9)
    sole = _pair(_p("box", (x, sole_h / 2, sole_d * 0.08), (diameter * 1.12, sole_h, sole_d), shoes))
    toe_r = diameter * 0.42
    toe = _pair(_p("sphere", (x, toe_r, sole_d * 0.42), (toe_r * 2, toe_r * 2, toe_r * 2), shoes, segments=LIMB_SEGMENTS))
    if spec["feet"] == "boot":
        shaft = max(layout["foot"] * 2.1, layout["h"] * 0.09)
        center = sole_h + shaft / 2 - diameter * 0.12
        ankle = _pair(_p("capsule", (x, center, 0), (diameter * 1.08, shaft, diameter * 1.08), shoes, segments=LIMB_SEGMENTS))
        return sole + toe + ankle
    ankle_r = diameter * 0.46
    ankle_y = max(ankle_r, sole_h * 0.85)
    ankle = _pair(_p("sphere", (x, ankle_y, 0), (ankle_r * 2, ankle_r * 2, ankle_r * 2), shoes, segments=LIMB_SEGMENTS))
    return sole + toe + ankle


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
    crown_h = max(0.045 * layout["h"], layout["sy"] * 0.16)
    top = layout["head_y"] + layout["sy"] / 2
    # The face's brows sit about 0.28 of the head height above its centre: the brim goes above them.
    brim_y = layout["head_y"] + layout["sy"] * 0.36
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
    brim_y = layout["head_y"] + layout["sy"] * 0.38
    crown_h = 0.11 * layout["h"]
    brim_h = 0.016 * layout["h"]
    return [
        _p("cylinder", (0, brim_y, 0), (layout["sx"] * 1.12, brim_h, layout["sz"] * 1.12), color, segments=HEAD_SEGMENTS),
        _p("cylinder", (0, brim_y + crown_h / 2, 0), (layout["sx"] * 0.62, crown_h, layout["sz"] * 0.62), color, segments=HEAD_SEGMENTS),
    ]


def _beanie(layout, color):
    # A low dome: its lower edge stays above the brows (0.30 of the head height over the centre), the top clears the head.
    return [_p("sphere", (0, layout["head_y"] + layout["sy"] * 0.45, 0),
               (layout["sx"] * 0.92, layout["sy"] * 0.30, layout["sz"] * 0.92), color, segments=HEAD_SEGMENTS)]


def _bucket_hat(layout, color):
    brim_y = layout["head_y"] + layout["sy"] * 0.37
    crown_h = max(0.05 * layout["h"], layout["sy"] * 0.14)
    return [
        _p("cylinder", (0, brim_y + crown_h * 0.45, 0), (layout["sx"] * 0.84, crown_h, layout["sz"] * 0.84), color, segments=HEAD_SEGMENTS),
        _p("cylinder", (0, brim_y, 0), (layout["sx"] * 1.16, 0.014 * layout["h"], layout["sz"] * 1.16), color, segments=HEAD_SEGMENTS),
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


def _clothes():
    from services.blob_wear import CLOTHES
    return CLOTHES


_ACCESSORY_BUILDERS = {
    "cap": _cap, "sailor_cap": _sailor_cap, "top_hat": _top_hat, "beanie": _beanie, "bucket_hat": _bucket_hat,
    "apron": _apron, "tie": _tie, "collar": _collar, "belt": _belt, "backpack": _backpack, "scarf": _scarf,
    **_clothes(),
}
