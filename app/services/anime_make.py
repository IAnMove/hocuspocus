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
GENDERS = ("girl", "boy", "man", "woman")
STYLES = ("anime", "real", "voxel", "roblox")
BOTTOMS = ("trousers", "skirt", "shorts")
_FIELDS = {"skin", "eye_color", "lash_color", "hair_style", "hair_color", "outfit", "outfit_colors", "body", "height", "gender", "blush", "face", "clips",
           "face_source", "face_image", "face_style", "face_shape", "style", "texture", "texture_head", "bottom"}
FACE_SOURCES = ("program", "qwen")
FACE_STYLES = ("anime", "cute")
_OUTFIT_COLORS = {"top", "bottom", "shoes", "accent", "socks"}
_DEFAULT_COLORS = {
    "school": {"girl": {"top": "#FFFFFF", "bottom": "#1B2350", "shoes": "#3A2A22", "accent": "#1B2350"},
               "boy": {"top": "#264361", "bottom": "#2C3340", "shoes": "#1A1A1A", "accent": "#8C1D2C"}},
    "casual": {"girl": {"top": "#F2D24A", "bottom": "#3C6EBE", "shoes": "#F4F4F2", "accent": "#C0392B"},
               "boy": {"top": "#E25B3A", "bottom": "#2C3340", "shoes": "#F4F4F2", "accent": "#F2D24A"}},
    "sport": {"girl": {"top": "#1F6F5F", "bottom": "#17403A", "shoes": "#F4F4F2", "accent": "#F2D24A"},
              "boy": {"top": "#1F6F5F", "bottom": "#17403A", "shoes": "#F4F4F2", "accent": "#F2D24A"}},
}
for _palette in _DEFAULT_COLORS.values():
    _palette["man"] = _palette["boy"]
    _palette["woman"] = _palette["girl"]
# Measured on Qwen bald sheets: width over height 0.82 (girl), 0.71 (boy), 0.69 (man); depth about 0.9 of the height.
_HEAD = {"girl": {"width": 0.12, "height": 0.146, "depth": 0.128, "shape": "anime", "kind": "fem"},
         "boy": {"width": 0.108, "height": 0.152, "depth": 0.136, "shape": "anime", "kind": "boy"},
         "man": {"width": 0.105, "height": 0.152, "depth": 0.138, "shape": "anime", "kind": "man"}}
_HEAD["woman"] = _HEAD["girl"]


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
    height = raw.get("height", {"girl": 1.62, "woman": 1.66, "boy": 1.76, "man": 1.82}[gender] * tall)
    if isinstance(height, bool) or not isinstance(height, (int, float)) or not 1.2 <= float(height) <= 2.2:
        _fail("invalid_height", "height must be from 1.2 to 2.2 metres")
    hair_style = _choice(raw.get("hair_style", "long" if gender in ("girl", "woman") else "short"), HAIR_STYLES, "invalid_hair", "hair_style")
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
    look = _choice(raw.get("style", "anime"), STYLES, "invalid_style", "style")
    if look == "real":
        body = _real_body(body, gender, raw, skin)
    elif look in ("voxel", "roblox"):
        body = _blocky_body(body, look, raw, skin, hair_color, colors)
    texture, texture_head = raw.get("texture"), raw.get("texture_head")
    for given in (texture, texture_head):
        if given is not None and (not isinstance(given, str) or not given.strip() or look == "anime"):
            _fail("invalid_traits", "texture and texture_head are workspace picture file names, for the styles real, voxel and roblox")
    if texture_head and look in ("voxel", "roblox"):
        _fail("invalid_traits", "a blocky body has one picture (texture), no head picture")
    if texture_head and not texture:
        _fail("invalid_traits", "texture_head goes with texture (the body picture)")
    face_extra = raw.get("face") or {}
    if not isinstance(face_extra, dict):
        _fail("invalid_traits", "face must be an object of face traits")
    source = _choice(raw.get("face_source", "program"), FACE_SOURCES, "invalid_face_source", "face_source")
    style = _choice(raw.get("face_style", "anime"), FACE_STYLES, "invalid_face_style", "face_style")
    face_image = raw.get("face_image")
    if source == "qwen" and (not isinstance(face_image, str) or not face_image.strip()):
        _fail("face_image_required", "face_source qwen needs face_image: a keyed bald face picture in this workspace (image.remove_background output)")
    if face_image is not None and not isinstance(face_image, str):
        _fail("invalid_traits", "face_image must be a workspace file name or URL")
    face = {"style": "blocky" if look in ("voxel", "roblox") else "cute" if style == "cute" else "anime_head", "blocky": look if look in ("voxel", "roblox") else "voxel", "hairColor": hair_color, "skin": skin, "eyeColor": _color(raw.get("eye_color"), "eye_color", "#3B6FC4"),
            "lashColor": _color(raw.get("lash_color"), "lash_color", darker(hair_color, 0.75)),
            "faceShape": _choice(raw.get("face_shape", "sharp" if gender == "man" else "soft"), ("soft", "sharp"), "invalid_face_shape", "face_shape"),
            "blush": raw.get("blush", gender in ("girl", "woman")) is True, **{k: v for k, v in face_extra.items() if k not in ("style", "skin")}}
    clips = raw.get("clips")
    public = {"gender": gender, "outfit": outfit, "body": raw.get("body", "slim"), "height": float(height), "skin": skin, "eye_color": face["eyeColor"],
              "lash_color": face["lashColor"], "hair_style": hair_style, "hair_color": hair_color, "outfit_colors": colors, "blush": face["blush"],
              "face_source": source, "face_style": style, "face_shape": face["faceShape"], "style": look, **({"texture": texture} if texture else {}), **({"texture_head": texture_head} if texture_head else {}), **({"face_image": face_image} if face_image else {})}
    return {"body": body, "face": face, "clips": clips, "public": public, "face_source": source, "face_image": face_image if source == "qwen" else None,
            "texture": texture, "texture_head": texture_head, "style": look}


def _blocky_body(body: dict, look: str, raw: dict, skin: str, hair_color: str, colors: dict) -> dict:
    """A voxel or roblox person: our own boxes on the humanoid rig, a 64 x 64 picture made from the colours (or ``texture``)."""
    return {"family": "anime", "mesh": "blocky", "blocky": look, "height": body["height"], "build": "average", "hair": {"style": "none", "color": hair_color},
            "blocky_colors": {"skin": skin, "hair": hair_color, "top": colors["top"], "bottom": colors["bottom"], "shoes": colors["shoes"]},
            "sleeves": "long" if raw.get("outfit") == "sport" else "short", "colors": body["colors"], "accessories": []}


def _real_body(body: dict, gender: str, raw: dict, skin: str) -> dict:
    """The mould of a realistic person: proportions of a PS2-era game, a plain body (no collar, tie or lapels: the clothes are
    the texture), UVs into the front/back atlas. Colours are a grey mannequin with a skin head and hands until a texture is given."""
    man = gender in ("man", "boy")
    bottom = _choice(raw.get("bottom", "trousers"), BOTTOMS, "invalid_bottom", "bottom")
    grey = "#B9B9BE"
    return {
        **body, "realism": "real", "atlas": True, "outfit": "plain", "build": "average" if man else "slim",
        "head": ({"width": 0.090, "height": 0.130, "depth": 0.117, "shape": "anime", "kind": "man"} if man
                 else {"width": 0.088, "height": 0.125, "depth": 0.112, "shape": "anime", "kind": "boy"}),
        "arms": {"length": 0.44, "thickness": 0.052 if man else 0.042},
        "legs": {"length": 0.50, "thickness": 0.086 if man else 0.074},
        "colors": {"head": skin, "hands": skin, "top": grey, "sleeves": grey, "bottom": "#8E8E94", "shoes": "#2A2A2E"},
        "accessories": [{"kind": bottom, "color": "#8E8E94"}] if bottom != "trousers" else [],
    }


def _accessories(outfit: str, gender: str, colors: dict) -> list[dict]:
    if outfit == "school":
        if gender in ("girl", "woman"):
            return [{"kind": "skirt", "color": colors["bottom"]}, {"kind": "school_collar", "color": "#FFFFFF"}, {"kind": "tie", "color": colors["accent"]}]
        return [{"kind": "jacket", "color": colors["top"]}, {"kind": "school_collar", "color": "#F7F4EF"}, {"kind": "tie", "color": colors["accent"]}]
    if outfit == "casual":
        return [{"kind": "skirt", "color": colors["bottom"]}] if gender in ("girl", "woman") else [{"kind": "shorts", "color": colors["bottom"]}]
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
    picture = _picture(workspace_dir, workspace, resolved["face_image"]) if resolved["face_source"] == "qwen" else None
    token = "anime-" + hashlib.sha256(f"{slug(name)}:{workspace}".encode()).hexdigest()[:10]
    Path(workspace_dir).mkdir(parents=True, exist_ok=True)
    # the kit first: a painted face brings its own skin, and the body's head and hands take it so the face is not a mask
    kit = save_face_kit(str(workspace_dir), workspace, resolved["face"], name=f"{name} face", kit_id=token, base_revision=base_revision, picture=picture)
    painted = (kit.get("face") or {}).get("skin")
    if picture is not None and isinstance(painted, str):
        resolved["body"]["colors"].update({"head": painted.upper(), "hands": painted.upper()})
        resolved["public"]["skin"] = painted.upper()
    relief = _face_relief(workspace_dir, workspace, resolved) if resolved["style"] == "real" and resolved["texture_head"] else None
    body = build_body(resolved["body"], clips, relief=relief)
    if resolved["style"] in ("voxel", "roblox"):
        extra = _blocky_files(workspace_dir, workspace, resolved, body)
    else:
        extra = _texture_files(workspace_dir, workspace, name, resolved, body) if resolved["style"] == "real" else {}
    written = write_body(workspace_dir, workspace, name, intent, body)
    return {**written, **extra, "kit_id": kit["kit_id"], "poses": kit["poses"], "preview": kit["preview"], "face": kit.get("face"),
            "character": resolved["public"], "faceTraits": resolved["face"]}


def _texture_files(workspace_dir: Path, workspace: str, name: str, resolved: dict, body: dict) -> dict:
    """A realistic mould: write the two guides (the body views and the head tiles, the pictures to repaint) and, when ``texture``
    names a picture of this workspace (with ``texture_head`` for the face), write the atlas into the GLBs. Painting other pictures
    over the same guides and calling make again dresses the same body anew."""
    from services.blob_builder import blob_pieces
    from services.blob_loft import loft_parts
    from services.blob_texture import ATLAS, atlas_frame, attach_texture, guide_png, stack_atlas

    lofted = blob_pieces({**resolved["body"], "mesh": "loft"})
    parts = loft_parts(lofted["traits"], lofted["layout"])
    base = f"anime-{slug(name)}"
    guides = {part: guide_png(parts, lofted["layout"], part) for part in ("body", "head")}
    for part, data in guides.items():
        (Path(workspace_dir) / f"{base}-guide-{part}.png").write_bytes(data)
    out = {"guide_body_file": f"{base}-guide-body.png", "guide_head_file": f"{base}-guide-head.png",
           "atlas": {"width": ATLAS[0], "height": ATLAS[1], "layout": "body views (front left, back right) over three head tiles (front, side, back; 3x the scale)"}}
    if resolved["texture"]:
        painted = _picture_of(workspace_dir, workspace, resolved["texture"], "texture")
        head = _picture_of(workspace_dir, workspace, resolved["texture_head"], "texture_head") if resolved["texture_head"] else None
        png = stack_atlas(painted, head, (guides["body"], guides["head"]))
        frame = atlas_frame([parts[0][0]], lofted["layout"])
        body["glb"] = attach_texture(body["glb"], png, frame=frame)
        body["rigged"] = attach_texture(body["rigged"], png, frame=frame)
        out["texture_file"] = Path(resolved["texture"]).name
    return out


def _face_relief(workspace_dir: Path, workspace: str, resolved: dict):
    """The depth of the painted face as a relief sampler (see ``blob_face_relief``), or None when the depth model is not installed."""
    from services.blob_builder import blob_pieces
    from services.blob_face_relief import relief_from_picture
    from services.blob_texture import atlas_frame
    from services.blob_loft import loft_parts

    picture = _picture_of(workspace_dir, workspace, resolved["texture_head"], "texture_head")
    lofted = blob_pieces({**resolved["body"], "mesh": "loft"})
    parts = loft_parts(lofted["traits"], lofted["layout"])
    frame = atlas_frame([parts[0][0]], lofted["layout"])
    return relief_from_picture(picture, frame, lofted["layout"]["sy"])


def _blocky_files(workspace_dir: Path, workspace: str, resolved: dict, body: dict) -> dict:
    """The body's 64 x 64 picture: made from the colours, or ``texture`` (a picture of the workspace in the same layout)."""
    import io

    from services.blob_blocky import SIZE, blocky_picture
    from services.blob_texture import attach_texture

    if resolved["texture"]:
        picture = _picture_of(workspace_dir, workspace, resolved["texture"], "texture").convert("RGBA")
        if picture.size != (SIZE, SIZE):
            from PIL import Image

            picture = picture.resize((SIZE, SIZE), Image.NEAREST)
        out = io.BytesIO()
        picture.save(out, format="PNG")
        png = out.getvalue()
    else:
        png = blocky_picture(body_spec(resolved))
    face = _neutral_face_png(resolved)
    for key in ("glb", "rigged"):
        body[key] = attach_texture(body[key], png, ("body",), nearest=resolved["style"] == "voxel")
        body[key] = attach_texture(body[key], face, ("face",), nearest=resolved["style"] == "voxel")   # until a kit paints it
    return {"texture_file": Path(resolved["texture"]).name} if resolved["texture"] else {"picture": "made from the colours"}


def _neutral_face_png(resolved: dict) -> bytes:
    """The neutral pose over the skin, small: what the face quad shows before a kit is projected on it."""
    import io

    from PIL import Image

    from services.blob_face import face_kit

    look = resolved["face"]
    pose = face_kit(look)["poses"]["neutral"].convert("RGBA")
    skin = tuple(int(look["skin"][i:i + 2], 16) for i in (1, 3, 5)) if isinstance(look["skin"], str) else tuple(look["skin"][:3])
    flat = Image.new("RGBA", pose.size, skin + (255,))
    flat.alpha_composite(pose)
    out = io.BytesIO()
    small = flat.convert("RGB").resize((256, 256), Image.NEAREST if resolved["style"] == "voxel" else Image.LANCZOS)
    small.transpose(Image.FLIP_TOP_BOTTOM).save(out, format="PNG")   # the quad's UVs are v-up (as the kit painter's), a glTF picture is v-down
    return out.getvalue()


def body_spec(resolved: dict) -> dict:
    return {**resolved["body"], "blocky": resolved["style"]}


def _picture_of(workspace_dir: Path, workspace: str, given: str, label: str):
    from PIL import Image

    name = given.split("/api/v1/file/")[-1].split("?")[0]
    path = Path(workspace_dir) / name
    if "/" in name or ".." in name or not path.is_file():
        _fail("texture_missing", f"{label} {name} is not a picture of workspace {workspace}")
    return Image.open(path)


def _picture(workspace_dir: Path, workspace: str, face_image: str):
    """The keyed bald picture: a workspace file name or its /api/v1/file URL."""
    from PIL import Image

    name = face_image.split("/api/v1/file/")[-1].split("?")[0] if "/api/v1/file/" in face_image else face_image
    if "/" in name or ".." in name:
        _fail("invalid_traits", "face_image must name a file of this workspace")
    path = Path(workspace_dir) / name
    if not path.is_file():
        _fail("face_image_missing", f"face_image {name} is not in workspace {workspace}")
    picture = Image.open(path).convert("RGBA")
    if picture.getextrema()[3][0] == 255:
        _fail("face_image_not_keyed", "face_image must be keyed (transparent background): run image.remove_background first")
    return picture
