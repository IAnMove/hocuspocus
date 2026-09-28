"""``.hptemplate`` v1: a reusable Video 3D / Video 2D scene with declared slots and controls.

A template is data only: a manifest (``template.json``), the scene document
(``document.json``), an optional preview image and optional sample media stored
by SHA-256 under ``media/``. Inside a template, media are referenced as
``media/<sha>.<ext>``; applying a template into a workspace copies the sample
media there and points the document at workspace URLs again.
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Callable, Iterator

from services.scene_packages import classify_url, parse_media_locator, reject_unknown_cinema, ScenePackageError

KIND = "hocuspocus.template"
VERSION = 1
EDITORS = {"video3d": "world3d-1", "video2d": "scene2d-1"}
LICENSES = ("CC0-1.0", "CC-BY-4.0", "CC-BY-SA-4.0", "CC-BY-NC-4.0", "MIT", "all-rights-reserved")
CONTROL_TYPES = ("number", "text", "color", "boolean", "choice")
MEDIA_EXT = {".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image", ".glb": "model3d", ".gltf": "model3d",
             ".mp4": "video", ".webm": "video", ".wav": "audio", ".mp3": "audio", ".ogg": "audio", ".m4a": "audio"}
PREVIEW_EXT = (".png", ".jpg", ".jpeg", ".webp")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}/[a-z0-9][a-z0-9-]{0,63}$")
SLOT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MEDIA_REF_RE = re.compile(r"^media/([0-9a-f]{64})(\.[a-z0-9]{2,5})$")
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_DOCUMENT_BYTES = 2 * 1024 * 1024
MAX_SLOTS = 16
MAX_CONTROLS = 32
MAX_TAGS = 12


class TemplateError(ValueError):
    """Invalid template or request; the message is safe to show."""

    def __init__(self, message: str, *, status: int = 422, code: str = "invalid_template") -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def slugify(value: str, limit: int = 64) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:limit].strip("-")
    return slug or "template"


def _text(value: Any, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def media_kind(name: str) -> str | None:
    return MEDIA_EXT.get(Path(str(name)).suffix.casefold())


# ---- media references inside documents ----------------------------------

MediaRef = tuple[dict, str]  # (container, key) whose string value is a media locator


def _slot_refs(slot: dict) -> Iterator[MediaRef]:
    yield slot, "sourceUrl"
    screen = slot.get("screen")
    if isinstance(screen, dict):
        yield screen, "sourceUrl"
    speech = slot.get("speech")
    if isinstance(speech, dict):
        for key in ("audio", "atlas"):
            if isinstance(speech.get(key), dict):
                yield speech[key], "url"


def _world3d_refs(document: dict) -> Iterator[MediaRef]:
    for slot in document.get("slots") or []:
        if isinstance(slot, dict):
            yield from _slot_refs(slot)
    for track in document.get("soundtrack") or []:
        if isinstance(track, dict) and isinstance(track.get("audio"), dict):
            yield track["audio"], "url"
    for cue in document.get("worldSfx") or []:
        if isinstance(cue, dict) and cue.get("sourceUrl"):
            yield cue, "sourceUrl"


def _scene2d_refs(document: dict) -> Iterator[MediaRef]:
    for layer in document.get("layers") or []:
        if not isinstance(layer, dict):
            continue
        yield layer, "source"
        sequence = layer.get("sequence")
        if isinstance(sequence, dict):
            if sequence.get("source"):
                yield sequence, "source"
            sources = sequence.get("sources")
            if isinstance(sources, list):
                for index in range(len(sources)):
                    yield _ListSlot(sources, index), "value"
    for track in document.get("audioTracks") or []:
        if isinstance(track, dict):
            yield track, "filename"


class _ListSlot(dict):
    """Adapter so a list item can be read and written like ``container[key]``."""

    def __init__(self, items: list, index: int) -> None:
        super().__init__(value=items[index])
        self._items, self._index = items, index

    def __setitem__(self, key: str, value: Any) -> None:
        super().__setitem__(key, value)
        self._items[self._index] = value


def media_refs(editor: str, document: dict) -> Iterator[MediaRef]:
    return _world3d_refs(document) if editor == "video3d" else _scene2d_refs(document)


def rewrite_media(editor: str, document: dict, rewrite: Callable[[str], str | None]) -> dict:
    """Return a copy where every media locator is passed through ``rewrite`` (None keeps it)."""
    copy = deepcopy(document)
    for container, key in media_refs(editor, copy):
        value = container.get(key)
        if isinstance(value, str) and value:
            updated = rewrite(value)
            if updated is not None:
                container[key] = updated
    if editor == "video3d":
        for slot in copy.get("slots") or []:
            if isinstance(slot, dict) and isinstance(slot.get("sourceRef"), dict):
                workspace, filename = parse_media_locator(slot.get("sourceUrl") or "")
                slot["sourceRef"] = {**slot["sourceRef"], "url": slot.get("sourceUrl") or "", "filename": filename,
                                     "workspaceId": workspace or ""}
    return copy


def is_workspace_media(value: str) -> bool:
    return classify_url(value) in {"gallery", "uploads"}


def is_bundled_example(value: str) -> bool:
    return value.startswith("/examples/") and ".." not in value


# ---- manifest --------------------------------------------------------------

def _author(raw: Any) -> dict[str, str]:
    raw = raw if isinstance(raw, dict) else {}
    author = {"name": _text(raw.get("name"), 80)}
    handle = _text(raw.get("x"), 30).lstrip("@")
    if handle:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,30}", handle):
            raise TemplateError("author.x must be an X handle")
        author["x"] = handle
    url = _text(raw.get("url"), 300)
    if url:
        if not url.startswith("https://"):
            raise TemplateError("author.url must be an https:// link")
        author["url"] = url
    return author


def template_id(raw_id: Any, title: str, author: dict[str, str]) -> str:
    if raw_id:
        value = str(raw_id).strip().lower()
        if not ID_RE.fullmatch(value):
            raise TemplateError("id must look like author/slug using a-z, 0-9 and hyphens", code="invalid_id")
        return value
    namespace = slugify(author.get("x") or author.get("name") or "local", 40)
    return f"{namespace}/{slugify(title)}"


def _slot(raw: Any, editor: str, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict) or not SLOT_ID_RE.fullmatch(str(raw.get("id") or "")):
        raise TemplateError(f"Slot {index + 1} needs an id (letters, digits, - or _)")
    accepts = [kind for kind in raw.get("accepts") or [] if kind in ("model3d", "image", "video", "audio")]
    target = str(raw.get("target") or raw["id"])
    return {"id": raw["id"], "label": _text(raw.get("label") or raw["id"], 80), "hint": _text(raw.get("hint"), 240),
            "accepts": accepts or (["model3d", "image"] if editor == "video3d" else ["image", "video"]),
            "required": bool(raw.get("required", True)), "target": target[:64]}


def _resolve_pointer(document: Any, pointer: str) -> tuple[Any, str | int]:
    if not pointer.startswith("/"):
        raise TemplateError(f"Control pointer {pointer!r} must start with /")
    parts = [part.replace("~1", "/").replace("~0", "~") for part in pointer[1:].split("/")]
    node = document
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last: str | int = int(parts[-1]) if isinstance(node, list) else parts[-1]
    node[last]  # noqa: B018 - existence check
    return node, last


def _number(control: dict[str, Any], value: Any) -> Any:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TemplateError(f"{control['id']} must be a number")
    low, high = control.get("min"), control.get("max")
    if (low is not None and value < low) or (high is not None and value > high):
        raise TemplateError(f"{control['id']} must be between {low} and {high}")
    return value


def _boolean(control: dict[str, Any], value: Any) -> Any:
    if not isinstance(value, bool):
        raise TemplateError(f"{control['id']} must be true or false")
    return value


def _color(control: dict[str, Any], value: Any) -> Any:
    if not (isinstance(value, str) and COLOR_RE.fullmatch(value)):
        raise TemplateError(f"{control['id']} must be a #rrggbb color")
    return value


def _choice(control: dict[str, Any], value: Any) -> Any:
    if value not in control.get("options", []):
        raise TemplateError(f"{control['id']} must be one of {control.get('options')}")
    return value


def _free_text(control: dict[str, Any], value: Any) -> Any:
    if not isinstance(value, str) or len(value) > 500:
        raise TemplateError(f"{control['id']} must be text up to 500 characters")
    return value


VALUE_CHECKS = {"number": _number, "boolean": _boolean, "color": _color, "choice": _choice, "text": _free_text}


def _check_value(control: dict[str, Any], value: Any) -> Any:
    return VALUE_CHECKS[control["type"]](control, value)


def _control_limits(raw: dict, control: dict[str, Any]) -> None:
    for key_name in ("min", "max"):
        if isinstance(raw.get(key_name), (int, float)) and not isinstance(raw.get(key_name), bool):
            control[key_name] = raw[key_name]
    if raw["type"] == "choice":
        options = raw.get("options")
        if not isinstance(options, list) or not 1 <= len(options) <= 32:
            raise TemplateError(f"Control {raw['id']} needs 1-32 options")
        control["options"] = options


def _control(raw: Any, document: dict, index: int) -> dict[str, Any]:
    if not isinstance(raw, dict) or not SLOT_ID_RE.fullmatch(str(raw.get("id") or "")):
        raise TemplateError(f"Control {index + 1} needs an id")
    if raw.get("type") not in CONTROL_TYPES:
        raise TemplateError(f"Control {raw['id']} type must be one of {', '.join(CONTROL_TYPES)}")
    pointer = str(raw.get("pointer") or "")
    try:
        container, key = _resolve_pointer(document, pointer)
    except (KeyError, IndexError, ValueError, TypeError) as exc:
        raise TemplateError(f"Control {raw['id']} points at {pointer!r}, which is not in the document") from exc
    control: dict[str, Any] = {"id": raw["id"], "label": _text(raw.get("label") or raw["id"], 80), "type": raw["type"], "pointer": pointer}
    _control_limits(raw, control)
    control["default"] = _check_value(control, raw["default"] if "default" in raw else container[key])
    return control


def _default_3d_slots(document: dict) -> list[dict[str, Any]]:
    return [{"id": slot["slot"], "label": slot["slot"], "accepts": [slot.get("media") or "model3d"], "target": slot["slot"],
             "required": bool(slot.get("sourceUrl"))}
            for slot in document.get("slots") or [] if isinstance(slot, dict) and slot.get("slot")]


def _slot_layer(layer: Any) -> bool:
    return (isinstance(layer, dict) and layer.get("type") in ("image", "video") and bool(layer.get("id"))
            and bool(layer.get("source")) and not is_bundled_example(str(layer["source"])))


def default_slots(editor: str, document: dict) -> list[dict[str, Any]]:
    """Slots inferred from the document when the author declares none."""
    if editor == "video3d":
        return _default_3d_slots(document)[:MAX_SLOTS]
    return [{"id": layer["id"], "label": layer.get("name") or layer["id"], "accepts": ["image", "video"], "target": layer["id"],
             "required": True} for layer in document.get("layers") or [] if _slot_layer(layer)][:MAX_SLOTS]


def check_document(editor: str, document: Any) -> dict:
    if editor not in EDITORS:
        raise TemplateError("editor must be video3d or video2d")
    if not isinstance(document, dict) or document.get("version") != 1:
        raise TemplateError("document must be a version 1 scene")
    key = "slots" if editor == "video3d" else "layers"
    if not isinstance(document.get(key), list):
        raise TemplateError(f"A {editor} document needs a {key} list")
    if len(json.dumps(document)) > MAX_DOCUMENT_BYTES:
        raise TemplateError("document exceeds 2 MB")
    try:
        reject_unknown_cinema(document)
    except ScenePackageError as exc:
        raise TemplateError(str(exc)) from exc
    for container, field in media_refs(editor, document):
        value = container.get(field)
        if isinstance(value, str) and value and not is_bundled_example(value) and classify_url(value) in {"external", "transient", "unsafe"}:
            raise TemplateError(f"Media must be workspace, example or packaged files, not {value[:80]!r}", code="external_media")
    return document


def _license(raw: Any) -> str:
    license_name = raw or "all-rights-reserved"
    if license_name not in LICENSES:
        raise TemplateError(f"license must be one of {', '.join(LICENSES)}")
    return license_name


def _unique_ids(slots: list[dict], controls: list[dict]) -> None:
    if len({item["id"] for item in slots}) != len(slots) or len({item["id"] for item in controls}) != len(controls):
        raise TemplateError("Slot and control ids must be unique")


def _slots_and_controls(raw: dict, editor: str, document: dict) -> tuple[list[dict], list[dict]]:
    slots_raw = raw.get("slots") if raw.get("slots") is not None else default_slots(editor, document)
    controls_raw = raw.get("controls") or []
    if not isinstance(slots_raw, list) or len(slots_raw) > MAX_SLOTS or not isinstance(controls_raw, list) or len(controls_raw) > MAX_CONTROLS:
        raise TemplateError(f"Use at most {MAX_SLOTS} slots and {MAX_CONTROLS} controls")
    slots = [_slot(item, editor, index) for index, item in enumerate(slots_raw)]
    controls = [_control(item, document, index) for index, item in enumerate(controls_raw)]
    _unique_ids(slots, controls)
    missing = [slot["target"] for slot in slots if slot["target"] not in targets_of(editor, document)]
    if missing:
        raise TemplateError(f"Slot targets not found in the document: {', '.join(missing)}", code="unknown_slot_target")
    return slots, controls


def normalize_manifest(raw: Any, document: dict) -> dict[str, Any]:
    """Validate a manifest against its document (slots exist, pointers resolve)."""
    if not isinstance(raw, dict) or raw.get("kind") != KIND or raw.get("version") != VERSION:
        raise TemplateError("Not a hocuspocus.template version 1 manifest", code="unsupported_template")
    editor = raw.get("editor")
    check_document(editor, document)
    title = _text(raw.get("title"), 80)
    if not title:
        raise TemplateError("A template needs a title")
    author = _author(raw.get("author"))
    slots, controls = _slots_and_controls(raw, editor, document)
    tags = [slugify(tag, 30) for tag in raw.get("tags") or [] if str(tag).strip()][:MAX_TAGS]
    requires = raw.get("requires") if isinstance(raw.get("requires"), dict) else {}
    return {
        "kind": KIND, "version": VERSION, "id": template_id(raw.get("id"), title, author), "editor": editor,
        "title": title, "description": _text(raw.get("description"), 600), "tags": sorted(set(tags)),
        "author": author, "license": _license(raw.get("license")), "templateVersion": _text(raw.get("templateVersion") or "1.0.0", 20),
        "createdAt": _text(raw.get("createdAt"), 40), "updatedAt": _text(raw.get("updatedAt"), 40),
        "requires": {"format": EDITORS[editor], "app": _text(requires.get("app") or ">=0.9.0", 20)},
        "slots": slots, "controls": controls,
    }


def targets_of(editor: str, document: dict) -> set[str]:
    if editor == "video3d":
        return {str(item.get("slot")) for item in document.get("slots") or [] if isinstance(item, dict)}
    return {str(item.get("id")) for item in document.get("layers") or [] if isinstance(item, dict)}


def set_control(document: dict, control: dict[str, Any], value: Any) -> None:
    container, key = _resolve_pointer(document, control["pointer"])
    container[key] = _check_value(control, value)


def _fill_3d(document: dict, target: str, url: str, kind: str) -> None:
    workspace, filename = parse_media_locator(url)
    for item in document.get("slots") or []:
        if isinstance(item, dict) and item.get("slot") == target:
            item.update({"sourceUrl": url, "media": "model3d" if kind == "model3d" else "image",
                         "sourceRef": {"workspaceId": workspace or "", "filename": filename, "url": url}})
            if kind != "model3d":
                item["clip"] = None


def _fill_2d(document: dict, target: str, url: str, kind: str) -> None:
    for layer in document.get("layers") or []:
        if isinstance(layer, dict) and layer.get("id") == target:
            layer.update({"source": url, "missingAsset": False})
            if layer.get("type") in ("image", "video") and kind in ("image", "video"):
                layer["type"] = kind


def fill_slot(editor: str, document: dict, slot: dict[str, Any], url: str) -> None:
    kind = media_kind(parse_media_locator(url)[1]) or "image"
    if slot["accepts"] and kind not in slot["accepts"]:
        raise TemplateError(f"Slot {slot['id']} accepts {', '.join(slot['accepts'])}, not {kind}", code="slot_type")
    (_fill_3d if editor == "video3d" else _fill_2d)(document, slot["target"], url, kind)


def clear_slot(editor: str, document: dict, slot: dict[str, Any]) -> None:
    if editor == "video3d":
        for item in document.get("slots") or []:
            if isinstance(item, dict) and item.get("slot") == slot["target"]:
                item.update({"sourceUrl": "", "clip": None})
                item.pop("sourceRef", None)
        return
    for layer in document.get("layers") or []:
        if isinstance(layer, dict) and layer.get("id") == slot["target"]:
            layer.update({"source": "", "missingAsset": True})


__all__ = [
    "EDITORS", "KIND", "LICENSES", "MEDIA_REF_RE", "PREVIEW_EXT", "TemplateError", "VERSION", "check_document",
    "clear_slot", "default_slots", "fill_slot", "is_bundled_example", "is_workspace_media", "media_kind", "media_refs",
    "normalize_manifest", "rewrite_media", "set_control", "slugify", "targets_of", "template_id",
]
