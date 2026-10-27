"""The catalogue of 3D character styles: what each one is, how to make it, how good it is, what is missing.

One place for people and models to read before they touch a style, and the list ``model3d.blob.presets`` returns under ``styles``.
Update ``status``, ``limits`` and ``next`` whenever a round changes them (``docs/agents/CHARACTER_STYLES.md`` explains the loop).
Each style is a mould (geometry, one rig) plus a way to dress it (vertex colours, a drawn face, or a texture atlas)."""
from __future__ import annotations

STATUS = ("stable", "experimental", "planned")

STYLES: dict[str, dict] = {
    "blob": {
        "label": "Blob / chubby", "status": "stable", "operation": "model3d.blob.make",
        "make": {"family": "blob"}, "mould": "round-headed body of primitives (spheres, capsules), 15 presets", "dress": "vertex colours, accessories",
        "face": "characters.face.make kit projected on the head (cap)", "look": "toon default",
        "strengths": ["cute and readable at any distance", "cheapest to produce"], "limits": ["no realism, no texture", "arms are tubes"],
        "next": ["a texture atlas like the real style"], "doc": "docs/agents/MODEL3D_BLOB.md",
    },
    "chibi": {
        "label": "Chibi", "status": "stable", "operation": "model3d.blob.make",
        "make": {"family": "chibi"}, "mould": "big head (2.5 to 3 heads tall), short limbs", "dress": "vertex colours, accessories",
        "face": "kit projected on the head", "look": "toon default",
        "strengths": ["expressive big face"], "limits": ["same as blob"], "next": [], "doc": "docs/agents/MODEL3D_BLOB.md",
    },
    "anime": {
        "label": "Anime (cel-shaded 3D)", "status": "experimental", "operation": "model3d.anime.make",
        "make": {"style": "anime", "gender": "girl|boy|man"}, "mould": "lofted PS2-style body, a skull measured from anime head sheets (fem, boy, man tables), strand-card hair",
        "dress": "vertex colours: outfit school|casual|sport, outfit_colors", "face": "an anime face drawn by the app (11 expressions, 9 visemes, blink) or a Qwen bald painting",
        "look": "toon shade anime (outline 3) or retro (steps 4, outline 0, classic)",
        "strengths": ["talking faces with lipsync", "a generator from traits", "head shapes by gender"],
        "limits": ["still reads cartoon-3D, not anime", "hair is cards without motion", "open mouths look like lipstick"],
        "next": ["a photo-like or painted face kit for the real style", "hair motion"], "doc": "docs/agents/ANIME_CHARACTERS.md",
    },
    "real": {
        "label": "Realistic PS2-era (textured)", "status": "experimental", "operation": "model3d.anime.make",
        "make": {"style": "real", "gender": "man|woman", "bottom": "trousers|skirt|shorts", "texture": "<body picture>", "texture_head": "<head picture>"},
        "mould": "lofted body with real proportions, man/boy skull, real nose, a texture atlas (body front|back, head front|side|back)",
        "dress": "two pictures painted by Qwen over the guides (guide_body_file, guide_head_file); the viewer drapes them per pixel",
        "face": "the head picture (a photo-like portrait); no expressions yet", "look": "toon steps 4, outline 0, classic; look.exposure about 1.5",
        "strengths": ["change the clothes by repainting one guide", "same mould for any outfit", "reads as a PS2/PS3 game character"],
        "limits": ["a face is a picture: no expressions or lipsync mouths yet", "the mould's face is smooth (no cheekbones, lips)", "hands and shoes are blocks", "a faint double feature near 35 degrees"],
        "next": ["a photo face kit with warped mouths and blink", "sculpted face relief", "woman mould tuning", "UI and Wizard doors for style and texture"],
        "doc": "docs/agents/ANIME_CHARACTERS.md",
    },
    "voxel": {
        "label": "Voxel (Minecraft-like)", "status": "experimental", "operation": "model3d.anime.make",
        "make": {"style": "voxel", "gender": "boy|girl|man|woman", "outfit_colors": "{top, bottom, shoes}", "hair_color": "#RRGGBB", "texture": "<64x64 picture>"},
        "mould": "our own boxes: an 8x8x8 head, an 8x12x4 torso, 3.5x12 arms and 4x12 legs, one rig", "dress": "a 64x64 skin made from the colours (pixel noise on the cloth), or your own picture in the usual voxel-skin layout; nearest filtering",
        "face": "a pixel face quad (blocky kit): 11 expressions, 9 mouths, blink", "look": "toon steps 4, outline 0, classic; exposure 1.4",
        "strengths": ["easy to animate (boxes), easy to dress (paint 64x64)", "the lipsync works on the quad"],
        "limits": ["arms 3.5 wide (4 wide is refused by the rig as hands_stuck)", "the face quad shows only from the front", "no second layer (hat, jacket) yet"],
        "next": ["a second skin layer", "outfit presets (overalls, hoodie)", "hands that grip"], "doc": "docs/agents/CHARACTER_STYLES.md",
    },
    "roblox": {
        "label": "Blocky (Roblox-like)", "status": "experimental", "operation": "model3d.anime.make",
        "make": {"style": "roblox", "gender": "boy|girl|man|woman", "outfit_colors": "{top, bottom, shoes}", "texture": "<64x64 picture>"},
        "mould": "our own boxes with R15-like proportions: a wide 1.6 x 1.3 head, a 2x2x1 torso, 1x2x1 limbs in two segments each", "dress": "a 64x64 picture made from the colours (flat plastic with a soft gradient), or your own; smooth filtering",
        "face": "a round-eyed decal quad (blocky kit) with a smile at rest", "look": "toon steps 4, outline 0, classic",
        "strengths": ["reads as a plastic toy avatar", "split limbs bend at the elbow and knee"],
        "limits": ["do not download or reuse Roblox's avatar meshes, shirt and pants templates, faces or logos: this is our own geometry and our own picture layout"],
        "next": ["head variants (round, tall)", "accessories (hats, hair pieces) as extra boxes", "hands that grip"], "doc": "docs/agents/CHARACTER_STYLES.md",
    },
    "ps1": {
        "label": "PS1 / low-poly retro", "status": "planned", "operation": "model3d.anime.make",
        "make": {"style": "ps1"}, "mould": "the real mould decimated to a few hundred triangles", "dress": "a 128x128 atlas with nearest filtering, vertex jitter",
        "face": "a tiny painted face", "look": "renderLook n64 or a PS1 shader (affine textures, snapped vertices)", "strengths": ["a strong, cheap retro look"],
        "limits": [], "next": ["decimate the mould", "a nearest-filter atlas"], "doc": "docs/agents/CHARACTER_STYLES.md",
    },
    "clay": {
        "label": "Clay / stop-motion", "status": "planned", "operation": "model3d.anime.make",
        "make": {"style": "clay"}, "mould": "the chibi or blob mould with soft proportions", "dress": "a clay texture with fingerprints, painted by Qwen",
        "face": "swappable mouth and eye pieces like a stop-motion puppet", "look": "lit, soft shadows, 12 fps motion", "strengths": ["distinct and charming"],
        "limits": [], "next": ["a clay atlas prompt", "a stepped-motion option"], "doc": "docs/agents/CHARACTER_STYLES.md",
    },
}


def catalog() -> dict[str, dict]:
    """A copy, for ``model3d.blob.presets``."""
    return {key: {**value, **{k: list(v) for k, v in value.items() if isinstance(v, list)}, "make": dict(value["make"])} for key, value in STYLES.items()}
