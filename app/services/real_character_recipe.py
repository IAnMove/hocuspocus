"""What ``model3d.real.make`` stores with a realistic character, and reads back to reopen and remake it.

A realistic character is its recipe: the traits of the mould (with the knobs only style ``real`` has), the two prompts (the clothes,
the face and hair), the seed and the image model, the two pictures painted from them and the photo face kit. Each picture is keyed by a
hash of its whole prompt, the seed, the model and the guide it was painted over, so a changed prompt never reuses a stale picture and an
unchanged one is never painted twice. The recipe is written next to the rigged GLB as ``<rigged>.recipe.json`` (as the rig writes its
``.humanoid.json``), so it goes where the character goes. ``latest`` reads the newest recipe of one name and ``characters`` the newest
of each name. A make that leaves a field out takes it from the newest recipe of that name: a remake changes only what it names.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
import uuid
from pathlib import Path
from typing import Any

from services.anime_make import resolve_traits, slug
from services.blob_builder import BlobTraitsError
from services.production_image_defaults import DEFAULT_IMAGE_MODEL

OPERATION = "model3d.real.make"
RECIPE_SUFFIX = ".recipe.json"
PROMPT_LIMIT = 1200
GENDERS = ("man", "woman")
SEED_MAX = 2_147_483_647
# Fields a make remembers: a later make of the same name that leaves one out takes the stored value (null clears it).
REMEMBERED = ("gender", "skin", "height", "body", "bottom", "outfit_prompt", "face_prompt", "seed", "image_model", "texture",
              "texture_head", "talk_kit", "traits")
INPUT_FIELDS = frozenset({"workspace", "name", "base_revision", *REMEMBERED})
_TOP_TRAITS = ("gender", "skin", "height", "body", "bottom")
_NOT_IN_TRAITS = frozenset({"style", "texture", "texture_head", *_TOP_TRAITS})
_KNOBS = ("upper_hold", "face_span", "face_feather", "face_depth", "lighting", "head_match", "head_fit", "head_bands", "head_join")
_MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
PRESETS_FILE = Path(__file__).resolve().parents[1] / "shared" / "real_character_prompts.json"

# The texture recipe of docs/agents/CHARACTER_STYLES.md, as scripts/dev/real_character.py proved it.
BODY_PROMPT = ("Flat colour texture map for a realistic PS2-era 3D game character, the full body front view on the left and the back view on the right, "
               "exactly the same T-pose, silhouette and layout as the reference image, painted over the grey mannequin. {body} "
               "Even flat lighting with no shadows or shading, plain dark background. Photographic texture style of early 2000s games.")
HEAD_PROMPT = ("Three photographic portrait textures of the head and neck of the same realistic person for a PS2-era 3D game, side by side in three tall panels "
               "with exactly the same silhouettes and layout as the reference image, painted over the grey head. Left panel: the head seen from the front. "
               "Middle panel: the head in pure right profile, face looking to the left. Right panel: the back of the head. {face} Neutral expression, mouth closed, "
               "bare neck down to the collarbones, even flat lighting with no shading or shadows, plain dark background, photographic texture style of early 2000s games.")


def _fail(code: str, message: str):
    raise BlobTraitsError(code, message)


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > PROMPT_LIMIT:
        _fail("invalid_prompt", f"{label} is English text of 1 to {PROMPT_LIMIT} characters")
    return value.strip()


def picture_name(value: Any, label: str) -> str:
    """A workspace picture: its file name, or its /api/v1/file URL."""
    if not isinstance(value, str) or not value.strip():
        _fail("invalid_texture", f"{label} is a picture file name of this workspace")
    name = value.split("/api/v1/file/")[-1].split("?")[0].strip()
    if not name or "/" in name or "\\" in name or ".." in name:
        _fail("invalid_texture", f"{label} must name a file of this workspace")
    return name


def _merged(payload: dict, stored: dict | None) -> dict:
    """The stored input under the given fields. A new prompt drops the picture the last make was given for that part; null clears."""
    remembered = dict((stored or {}).get("input") or {})
    given = {key: payload[key] for key in REMEMBERED if key in payload}
    for prompt, picture in (("outfit_prompt", "texture"), ("face_prompt", "texture_head")):
        if prompt in given and picture not in given:
            remembered.pop(picture, None)
    return {key: value for key, value in {**remembered, **given}.items() if value is not None}


def _check_parts(merged: dict) -> None:
    for prompt, picture, label in (("outfit_prompt", "texture", "the clothes"), ("face_prompt", "texture_head", "the face and hair")):
        if picture in merged:
            merged[picture] = picture_name(merged[picture], picture)
        elif prompt in merged:
            merged[prompt] = _text(merged[prompt], prompt)
        else:
            _fail("prompt_required", f"{prompt} is required for a new character ({label}, in English), or {picture} (a picture to reuse)")


def _check_scalars(merged: dict) -> None:
    if merged["gender"] not in GENDERS:
        _fail("invalid_gender", "gender must be one of: man, woman")
    seed = merged["seed"]
    if isinstance(seed, bool) or not isinstance(seed, int) or not 0 <= seed <= SEED_MAX:
        _fail("invalid_seed", f"seed is a whole number from 0 to {SEED_MAX}")
    if not isinstance(merged["image_model"], str) or not _MODEL.fullmatch(merged["image_model"]):
        _fail("invalid_model", "image_model is the id of an image model")
    if not isinstance(merged["talk_kit"], bool):
        _fail("invalid_talk_kit", "talk_kit is true or false")
    traits = merged["traits"]
    if not isinstance(traits, dict) or set(traits) & _NOT_IN_TRAITS:
        _fail("invalid_traits", "traits is an object of more model3d.anime.make traits (face_span, hair_style, ...); gender, skin, height, body, "
                                "bottom and the pictures are fields of their own")


def resolve_input(payload: dict, stored: dict | None) -> dict:
    """The input a make runs with: what was given over what the newest recipe of the name stored, then the defaults. A new seed is
    drawn once for a new character and stored."""
    extra = set(payload) - INPUT_FIELDS
    if extra:
        _fail("unknown_field", "Unknown field: " + ", ".join(sorted(extra)))
    merged = _merged(payload, stored)
    merged.setdefault("gender", "man")
    merged.setdefault("image_model", DEFAULT_IMAGE_MODEL)
    merged.setdefault("talk_kit", True)
    merged.setdefault("traits", {})
    merged.setdefault("seed", random.randrange(SEED_MAX))
    _check_parts(merged)
    _check_scalars(merged)
    resolve_traits(make_traits(merged))   # the mould's own refusals (skin, height, body, bottom, the knobs) before anything is made
    return merged


def make_traits(effective: dict) -> dict:
    """The ``model3d.anime.make`` traits of the mould: style real, painted hair unless ``traits`` says otherwise."""
    top = {key: effective[key] for key in _TOP_TRAITS if key in effective}
    return {"hair_style": "none", **effective.get("traits", {}), **top, "style": "real"}


def resolved_traits(effective: dict) -> dict:
    """Every trait the mould was made with, defaults included, with the knobs only style real has."""
    resolved = resolve_traits(make_traits(effective))
    knobs = {key: resolved[key] for key in _KNOBS}
    return {**resolved["public"], **knobs, "bottom": make_traits(effective).get("bottom", "trousers")}


def full_prompts(effective: dict) -> dict:
    """The whole prompt of each picture to paint (a picture given instead has none)."""
    return {"body": BODY_PROMPT.format(body=effective["outfit_prompt"]) if "texture" not in effective else None,
            "head": HEAD_PROMPT.format(face=effective["face_prompt"]) if "texture_head" not in effective else None}


def _digest(*parts: Any) -> str:
    return hashlib.sha256("\n".join(str(part) for part in parts).encode("utf-8")).hexdigest()[:16]


def picture_key(model: str, steps: int, prompt: str, seed: int, guide: bytes) -> str:
    return _digest("paint", model, steps, prompt, seed, hashlib.sha256(guide).hexdigest())


def given_key(path: Path) -> str:
    return _digest("given", hashlib.sha256(path.read_bytes()).hexdigest())


def character_key(traits: dict, body_key: str, head_key: str) -> str:
    return _digest("character", json.dumps(traits, sort_keys=True), body_key, head_key)


def recipe_path(folder: Path, rigged_file: str) -> Path:
    return Path(folder) / (Path(rigged_file).name.removesuffix(".glb") + RECIPE_SUFFIX)


def write_recipe(folder: Path, recipe: dict) -> Path:
    target = recipe_path(folder, recipe["files"]["rigged_file"])
    temporary = target.with_name(f".{target.name}-{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(json.dumps(recipe, ensure_ascii=False, indent=1), encoding="utf-8")
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return target


def _recipes(folder: Path) -> list[dict]:
    found = []
    for path in sorted(Path(folder).glob(f"*{RECIPE_SUFFIX}")) if Path(folder).is_dir() else []:
        try:
            recipe = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(recipe, dict) and recipe.get("operation") == OPERATION and isinstance(recipe.get("slug"), str):
            found.append({**recipe, "recipeFile": path.name})
    return sorted(found, key=lambda item: str(item.get("madeAt") or ""), reverse=True)


def latest(folder: Path, name: str) -> dict | None:
    """The newest recipe of a character, by its name (or slug); None for a name never made."""
    wanted = slug(name)
    return next((recipe for recipe in _recipes(folder) if recipe["slug"] == wanted), None)


def _file_url(name: str | None, workspace: str) -> str | None:
    from services.local_generation import file_url

    return file_url(name, workspace) if name else None


def summary(folder: Path, recipe: dict) -> dict:
    """One line of the list: enough to show the character and open it in the form."""
    files, pictures, given = recipe.get("files") or {}, recipe.get("pictures") or {}, recipe.get("input") or {}
    workspace = recipe.get("workspace") or ""
    return {"name": recipe.get("name"), "slug": recipe["slug"], "gender": given.get("gender"), "outfit_prompt": given.get("outfit_prompt"),
            "face_prompt": given.get("face_prompt"), "seed": given.get("seed"), "image_model": given.get("image_model"),
            "kit_id": recipe.get("kit_id"), "rigged_file": files.get("rigged_file"), "rigged_url": _file_url(files.get("rigged_file"), workspace),
            "face_url": _file_url((pictures.get("face") or {}).get("file"), workspace),
            "body_url": _file_url((pictures.get("body") or {}).get("file"), workspace),
            "madeAt": recipe.get("madeAt"), "missing": not (Path(folder) / str(files.get("rigged_file") or "")).is_file(),
            "recipeFile": recipe.get("recipeFile")}


def characters(folder: Path) -> list[dict]:
    """The newest recipe of each realistic character in the workspace, newest first."""
    seen, rows = set(), []
    for recipe in _recipes(folder):
        if recipe["slug"] not in seen:
            seen.add(recipe["slug"])
            rows.append(summary(folder, recipe))
    return rows


def presets() -> dict:
    """The prompt library: outfits and faces with Spanish and English labels and an English prompt (app/shared)."""
    return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
