"""Build PoopMan333 A prompts from MiniMax-M3 vision, without a user prompt."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

CompleteFn = Callable[[str, str, list[str]], str]

KIND_VALUES = frozenset({"character", "object"})
ROLE_VALUES = ("subject", "face", "outfit", "extra", "accessory")

ROLE_JOB = {
    "subject": "the complete subject: identity, body, wardrobe, materials and identifying details",
    "face": "face, hair and art style only",
    "outfit": "wardrobe colors, cut, material and details only",
    "extra": "an extra angle or appearance cue for the same subject",
    "accessory": "the attached prop or accessory only",
}

DESCRIBE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pictures"],
    "properties": {
        "kind": {"type": "string", "enum": ["character", "object"]},
        "pictures": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["keep", "ignore"],
                "properties": {
                    "keep": {"type": "string"},
                    "ignore": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM_PROMPT = (
    "You look at reference photos and write keep/ignore lines for MiniMax H3 "
    "character-sheet generation. Describe only visible facts. Name clothing, "
    "materials, colors, body, face and props in concrete words. Always say "
    "what to ignore (background, floor, lighting, other people, anything "
    "outside that picture's job). Do not write camera moves, a video script, "
    "or a 360 orbit. Return JSON only."
)


def normalize_kind(value: Any) -> str:
    kind = str(value or "character").strip().lower()
    return kind if kind in KIND_VALUES else "character"


def normalize_roles(roles: Any, image_count: int) -> list[str]:
    count = max(1, int(image_count))
    raw = list(roles or [])
    out: list[str] = []
    for index in range(count):
        role = str(raw[index] if index < len(raw) else "").strip().lower()
        if role not in ROLE_VALUES:
            role = "subject" if index == 0 else "extra"
        out.append(role)
    return out


def format_a_prompt(pictures: list[dict[str, str]]) -> str:
    lines = []
    for index, picture in enumerate(pictures, start=1):
        keep = " ".join(str(picture.get("keep") or "").split()).strip(" .")
        ignore = " ".join(str(picture.get("ignore") or "").split()).strip(" .")
        if not keep:
            keep = "the complete visible subject"
        if not ignore:
            ignore = "the background, floor and lighting"
        lines.append(f"<Picture {index}> - keep {keep}. Ignore {ignore}.")
    return "\n".join(lines)


def fallback_pictures(kind: str, roles: list[str]) -> list[dict[str, str]]:
    noun = "object" if kind == "object" else "subject"
    pictures = []
    for role in roles:
        job = ROLE_JOB.get(role, ROLE_JOB["subject"])
        pictures.append({
            "keep": job,
            "ignore": "the background, floor, lighting and anything outside this picture's job",
        })
    if not pictures:
        pictures.append({
            "keep": f"the complete {noun}",
            "ignore": "the background, floor and lighting",
        })
    return pictures


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = str(raw or "").strip()
    if not text:
        return None
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    candidates = [text]
    match = re.search(r"\{.*\}", text, flags=re.S)
    if match:
        candidates.append(match.group(0))
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


def pictures_from_response(raw: str, *, kind: str, roles: list[str]) -> list[dict[str, str]]:
    parsed = _extract_json_object(raw)
    pictures: list[dict[str, str]] = []
    if parsed:
        items = parsed.get("pictures")
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                pictures.append({
                    "keep": str(item.get("keep") or ""),
                    "ignore": str(item.get("ignore") or ""),
                })
    if not pictures:
        cleaned = " ".join(str(raw or "").split()).strip()
        if cleaned and "<Picture" not in cleaned:
            pictures = [{"keep": cleaned, "ignore": "the background, floor and lighting"}]
        else:
            pictures = fallback_pictures(kind, roles)
    while len(pictures) < len(roles):
        pictures.extend(fallback_pictures(kind, roles[len(pictures):]))
    return pictures[: len(roles)]


def build_user_prompt(kind: str, roles: list[str]) -> str:
    noun = "object" if kind == "object" else "character"
    lines = [
        f"Subject type: {noun}.",
        "The attached images are in order: Picture 1 is first, Picture 2 is second, and so on.",
        "For each picture write keep and ignore:",
    ]
    for index, role in enumerate(roles, start=1):
        lines.append(f"Picture {index} job: {ROLE_JOB.get(role, ROLE_JOB['subject'])}.")
    lines.append(
        "Ignore backgrounds, floor, lighting, watermarks and any person or prop "
        "that is not part of that picture's job. Describe fabrics and colors in words."
    )
    return "\n".join(lines)


def describe_character_sheet(
    *,
    kind: str,
    image_paths: list[str],
    roles: list[str] | None = None,
    complete: CompleteFn,
) -> str:
    """Return an A Prompt. `complete(system, user, image_paths)` talks to MiniMax."""
    paths = [path for path in image_paths if path]
    if not paths:
        raise ValueError("At least one image is required")
    kind = normalize_kind(kind)
    roles = normalize_roles(roles, len(paths))
    raw = complete(SYSTEM_PROMPT, build_user_prompt(kind, roles), paths)
    pictures = pictures_from_response(raw, kind=kind, roles=roles)
    return format_a_prompt(pictures)
