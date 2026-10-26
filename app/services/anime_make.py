"""``model3d.anime.make``: one anime 3D character from traits, in one call.

A lofted body (``blob_loft``, ``blob_hair``) rigged on CPU, and its face drawn as an
``anime_head`` Character Kit (eleven expressions, nine visemes, a blink) that
``world3d.scene.face`` projects onto the egg head with the kit's own ``fit`` and
``taper``. The reply has everything a scene needs: the rigged file, ``faceAnchor``,
``kit_id`` and ``face``. The same door serves HTTP (``POST /api/v1/model3d/anime``),
MCP and the panels; the mesh work stays in ``blob_make`` and ``blob_face``.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from services.blob_builder import BlobTraitsError, _hex
from services.blob_make import build_body, write_body

MAKE = "model3d.anime.make"
HAIR_STYLES = ("none", "short", "bangs", "bob", "long", "twin_tails", "spiky", "ponytail", "bun")
OUTFITS = ("school", "casual", "sport")
BODIES = {"slim": ("slim", 1.0), "average": ("average", 1.0), "tall": ("slim", 1.08)}
GENDERS = ("girl", "boy")
_FIELDS = {"skin", "eye_color", "lash_color", "hair_style", "hair_color", "outfit", "outfit_colors", "body", "height", "gender", "blush", "face", "clips"}
_OUTFIT_COLORS = {"top", "bottom", "shoes", "accent", "socks"}
_DEFAULT_COLORS = {
    "school": {"girl": {"top": "#FFFFFF", "bottom": "#1B2350", "shoes": "#3A2A22", "accent": "#1B2350"},
               "boy": {"top": "#264361", "bottom": "#2C3340", "shoes": "#1A1A1A", "accent": "#8C1D2C"}},
    "casual": {"girl": {"top": "#F2D24A", "bottom": "#3C6EBE", "shoes": "#F4F4F2", "accent": "#C0392B"},
               "boy": {"top": "#E25B3A", "bottom": "#2C3340", "shoes": "#F4F4F2", "accent": "#F2D24A"}},
    "sport": {"girl": {"top": "#1F6F5F", "bottom": "#17403A", "shoes": "#F4F4F2", "accent": "#F2D24A"},
              "boy": {"top": "#1F6F5F", "bottom": "#17403A", "shoes": "#F4F4F2", "accent": "#F2D24A"}},
}
_HEAD = {"girl": {"width": 0.12, "height": 0.146, "depth": 0.11, "shape": "anime"}, "boy": {"width": 0.12, "height": 0.152, "depth": 0.11, "shape": "anime"}}


def _fail(code: str, message: str):
    raise BlobTraitsError(code, message)


def _choice(value, allowed, code, label):
    if value not in allowed:
        _fail(code, f"{label} must be one of: " + ", ".join(allowed))
    return value


def _color(value, label: str, default: str) -> str:
    if value is None:
        return default
    return _hex(value, label)


def darker(color: str, k: float) -> str:
    r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    return "#%02X%02X%02X" % (min(255, int(r * k)), min(255, int(g * k)), min(255, int(b * k)))


def resolve_traits(raw: Any) -> dict[str, Any]:
    """Character traits -> ``{body: blob traits, face: face traits, clips, public}``. Unknown fields are refused."""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        _fail("invalid_traits", "traits must be an object")
    extra = set(raw) - _FIELDS
    if extra:
        _fail("unknown_field", "Unknown trait: " + ", ".join(sorted(extra)))
    gender = _choice(raw.get("gender", "girl"), GENDERS, "invalid_gender", "gender")
    outfit = _choice(raw.get("outfit", "school"), OUTFITS, "invalid_outfit", "outfit")
    build, tall = BODIES[_choice(raw.get("body", "slim"), tuple(BODIES), "invalid_body", "body")]
    height = raw.get("height", (1.62 if gender == "girl" else 1.76) * tall)
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not 1.2 <= float(height) <= 2.2:
        _fail("invalid_height", "height must be from 1.2 to 2.2 metres")
    hair_style = _choice(raw.get("hair_style", "long" if gender == "girl" else "short"), HAIR_STYLES, "invalid_hair", "hair_style")
    hair_color = _color(raw.get("hair_color"), "hair_color", "#2A211C")
    skin = _color(raw.get("skin"), "skin", "#F3CBA4")
    given = raw.get("outfit_colors") or {}
    if not isinstance(given, dict) or set(given) - _OUTFIT_COLORS:
        _fail("invalid_color", "outfit_colors takes top, bottom, shoes, accent and socks")
    colors = {**_DEFAULT_COLORS[outfit][gender], **{key: _hex(value, f"outfit_colors.{key}") for key, value in given.items()}}
    accessories = _accessories(outfit, gender, colors)
    body = {
        "family": "anime", "mesh": "loft", "build": build, "height": float(height), "hands": "mitten", "feet": "shoe",
        "head": dict(_HEAD[gender]), "hair": {"style": hair_style, "color": hair_color}, "outfit": outfit,
        "colors": {"head": skin, "hands": skin, "top": colors["top"], "sleeves": colors["top"], "bottom": colors["bottom"], "shoes": colors["shoes"]},
        "accessories": accessories,
    }
    face_extra = raw.get("face") or {}
    if not isinstance(face_extra, dict):
        _fail("invalid_traits", "face must be an object of face traits")
    face = {"style": "anime_head", "skin": skin, "eyeColor": _color(raw.get("eye_color"), "eye_color", "#3B6FC4"),
            "lashColor": _color(raw.get("lash_color"), "lash_color", darker(hair_color, 0.75)),
            "blush": raw.get("blush", gender == "girl") is True, **{k: v for k, v in face_extra.items() if k not in ("style", "skin")}}
    clips = raw.get("clips")
    public = {"gender": gender, "outfit": outfit, "body": raw.get("body", "slim"), "height": float(height), "skin": skin, "eye_color": face["eyeColor"],
              "lash_color": face["lashColor"], "hair_style": hair_style, "hair_color": hair_color, "outfit_colors": colors, "blush": face["blush"]}
    return {"body": body, "face": face, "clips": clips, "public": public}


def _accessories(outfit: str, gender: str, colors: dict) -> list[dict]:
    if outfit == "school":
        if gender == "girl":
            return [{"kind": "skirt", "color": colors["bottom"]}, {"kind": "school_collar", "color": "#FFFFFF"}, {"kind": "tie", "color": colors["accent"]}]
        return [{"kind": "jacket", "color": colors["top"]}, {"kind": "school_collar", "color": "#F7F4EF"}, {"kind": "tie", "color": colors["accent"]}]
    if outfit == "casual":
        return [{"kind": "skirt", "color": colors["bottom"]}] if gender == "girl" else [{"kind": "shorts", "color": colors["bottom"]}]
    return []


def slug(name: str) -> str:
    text = re.sub(r"[^a-z0-9]+", "-", str(name).lower()).strip("-")
    return text[:40] or "anime"


def make_character(workspace_dir: Path, workspace: str, name: str, intent: str, traits: Any, *, base_revision: int | None = None) -> dict[str, Any]:
    """Body, rig, kit. Writes the GLBs and the kit; returns one reply with everything a scene needs."""
    from services.blob_face import save_face_kit
    from services.blob_make import _clips

    resolved = resolve_traits(traits)
    clips = _clips(resolved["clips"])
    body = build_body(resolved["body"], clips)
    written = write_body(workspace_dir, workspace, name, intent, body)
    token = "anime-" + hashlib.sha256(f"{slug(name)}:{workspace}".encode()).hexdigest()[:10]
    kit = save_face_kit(str(workspace_dir), workspace, resolved["face"], name=f"{name} face", kit_id=token, base_revision=base_revision)
    return {**written, "kit_id": kit["kit_id"], "poses": kit["poses"], "preview": kit["preview"], "face": kit.get("face"),
            "character": resolved["public"], "faceTraits": resolved["face"]}
