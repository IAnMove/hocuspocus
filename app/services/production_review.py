"""Closed questions on one contact sheet already in the workspace.

``production.review`` returns ok, retake, or unreliable. The vision step is
injectable. Qwen3-VL-8B in this tree is an image-generation encoder that
loads weights, and no CPU-free asker is installed, so the default does not
load a model and does not invent yes/no answers.

``review_production`` is the code review attached to ``production.status``.
It scores black bars, a held or frozen scene, title boxes, and duplicate
people without a vision model. Protagonist identity stays unknown unless a
caller injects an embedding backend that is already loaded.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, quote, unquote, urlsplit

from fastapi import HTTPException


OPERATION = "production.review"
QUESTIONS = (
    "words_readable",
    "duplicate_people",
    "face_consistent",
    "text_covers_face",
)
_FAIL_VALUE = {
    "words_readable": "no",
    "face_consistent": "no",
    "duplicate_people": "yes",
    "text_covers_face": "yes",
}
_ANSWER_VALUES = frozenset({"yes", "no", "unknown"})
_IMAGE_EXTENSIONS = frozenset({".jpeg", ".jpg", ".png", ".webp"})
_WORKSPACE = re.compile(r"(?:default|[A-Za-z0-9][A-Za-z0-9_-]*)")
_FILE_PREFIX = "/api/v1/file/"
_OMITTED_SHOT = "montage"


class ReviewError(Exception):
    def __init__(self, code: str, message: str, status: int = 422) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class VisionUnavailable(Exception):
    """The sheet was not asked. No yes/no answer exists."""


def command_catalog() -> list[dict[str, Any]]:
    payload = {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "workspace": {"type": "string", "minLength": 1, "maxLength": 120},
            "sheet": {
                "type": "string",
                "minLength": 1,
                "maxLength": 2000,
                "description": "Workspace-relative image path, or an /api/v1/file URL in that workspace.",
            },
            "shots": {
                "type": "array",
                "maxItems": 60,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["key"],
                    "properties": {"key": {"type": "string", "minLength": 1, "maxLength": 80}},
                },
            },
        },
        "required": ["workspace", "sheet"],
    }
    return [{
        "name": OPERATION,
        "version": 1,
        "domain": "production",
        "mutation": False,
        "description": (
            "Answer four closed questions about one contact sheet already in the "
            "workspace: words_readable, duplicate_people, face_consistent, "
            "text_covers_face. Each value is yes, no, or unknown. Verdict is ok, "
            "retake, or unreliable. no on words_readable or face_consistent, or yes "
            "on duplicate_people or text_covers_face, retakes the supplied shot keys. "
            "When shots is omitted, that retake is the single key montage. unknown "
            "does not by itself force a retake; if any answer is unknown and none "
            "fail, verdict is unreliable with reason incomplete. When the vision "
            "backend cannot run, verdict is unreliable, reason is vision_unavailable, "
            "answers and retake are empty, and no yes/no is invented. The default "
            "does not load Qwen3-VL weights. The reply has no image bytes; a stored "
            "review is file, url, and sha256. path_not_allowed, invalid_command, "
            "invalid_workspace, invalid_sheet, invalid_shots, unsupported_media, and "
            "media_not_found are stable errors."
        ),
        "inputSchema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "version": {"type": "integer", "const": 1},
                "input": payload,
            },
            "required": ["version", "input"],
        },
    }]


def command_handlers(
    workspace_dir: Callable[[str], str],
    vision: Callable[..., Any] | None = None,
) -> dict[str, Callable[[Any], Any]]:
    async def production_review(arguments: Any) -> dict[str, Any]:
        import asyncio

        try:
            result = await asyncio.to_thread(execute, arguments, workspace_dir, vision)
        except ReviewError as error:
            raise HTTPException(error.status, {
                "code": error.code,
                "message": error.message,
                "retryable": False,
            }) from error
        return {"version": 1, "status": "completed", "operation": OPERATION, "result": result}

    return {OPERATION: production_review}


def execute(arguments: Any, workspace_dir: Callable[[str], str], vision: Callable[..., Any] | None) -> dict:
    payload = _require_input(arguments)
    workspace = _workspace_name(payload)
    sheet = _sheet_value(payload)
    keys = shot_keys(payload)
    root = workspace_dir(workspace)
    path = resolve_sheet(sheet, workspace, root)
    return publish(root, workspace, sheet, path, keys, vision)


def cpu_free_asker() -> Callable[..., Any] | None:
    """Return a weight-free Qwen3-VL-8B asker, or None.

    The local Qwen3-VL-8B stack is the image encoder checkpoint. Invoking it
    loads weights. Nothing in-tree answers a sheet without that load, and this
    function does not download or construct the model.
    """
    return None


def default_vision(path: str, questions: tuple[str, ...]) -> dict[str, str]:
    asker = cpu_free_asker()
    if asker is None:
        raise VisionUnavailable()
    return asker(path, questions)


def collect_answers(path: str, vision: Callable[..., Any] | None) -> list[dict] | None:
    ask = default_vision if vision is None else vision
    try:
        raw = ask(path, QUESTIONS)
    except Exception:
        return None
    return normalize_answers(raw)


def normalize_answers(raw: Any) -> list[dict] | None:
    if not isinstance(raw, dict):
        return None
    answers = []
    for question in QUESTIONS:
        value = raw.get(question)
        if value not in _ANSWER_VALUES:
            return None
        answers.append({"question": question, "value": value})
    return answers


def score_answers(answers: list[dict], keys: list[str] | None) -> dict:
    if any_failed(answers):
        retake = [_OMITTED_SHOT] if keys is None else list(keys)
        return _decision("retake", None, answers, retake)
    if any_unknown(answers):
        return _decision("unreliable", "incomplete", answers, [])
    return _decision("ok", None, answers, [])


def any_failed(answers: list[dict]) -> bool:
    for item in answers:
        if item["value"] == _FAIL_VALUE[item["question"]]:
            return True
    return False


def any_unknown(answers: list[dict]) -> bool:
    for item in answers:
        if item["value"] == "unknown":
            return True
    return False


def publish(
    root: str,
    workspace: str,
    sheet: str,
    path: str,
    keys: list[str] | None,
    vision: Callable[..., Any] | None,
) -> dict:
    answers = collect_answers(path, vision)
    if answers is None:
        decision = _decision("unreliable", "vision_unavailable", [], [])
    else:
        decision = score_answers(answers, keys)
    decision.update(store_review(root, workspace, sheet, decision))
    return decision


def resolve_sheet(sheet: str, workspace: str, root: str) -> str:
    relative = file_url_relative(sheet, workspace) if sheet.startswith("/api/") else sheet
    if path_leaves_workspace(relative):
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.")
    return contained_image(root, relative)


def file_url_relative(sheet: str, workspace: str) -> str:
    parsed = urlsplit(sheet)
    if parsed.scheme or parsed.netloc:
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.")
    if not parsed.path.startswith(_FILE_PREFIX):
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.")
    query = parse_qsl(parsed.query, keep_blank_values=True)
    if query != [("workspace", workspace)]:
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.")
    relative = _unquote_path(parsed.path[len(_FILE_PREFIX):])
    if path_leaves_workspace(relative):
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.")
    return relative


def path_leaves_workspace(value: str) -> bool:
    if not value:
        return True
    if value[:1] in {"/", "\\"} or os.path.isabs(value):
        return True
    return _bad_relative(value)


def contained_image(root: str, relative: str) -> str:
    base = os.path.realpath(os.path.abspath(root))
    candidate = os.path.realpath(os.path.abspath(os.path.join(base, relative)))
    if not _inside(candidate, base):
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.")
    extension = os.path.splitext(candidate)[1].lower()
    if extension not in _IMAGE_EXTENSIONS:
        raise ReviewError("unsupported_media", "Sheet must be an image.")
    if not os.path.isfile(candidate):
        raise ReviewError("media_not_found", "Sheet was not found.", 404)
    return candidate


def shot_keys(payload: dict) -> list[str] | None:
    if "shots" not in payload or payload.get("shots") is None:
        return None
    shots = payload["shots"]
    if isinstance(shots, list) and len(shots) <= 60:
        return _unique_keys(shots)
    raise ReviewError("invalid_shots", "shots must be a list of {key}.")


def store_review(root: str, workspace: str, sheet: str, decision: dict) -> dict:
    document = {
        "version": 1,
        "sheet": sheet,
        "verdict": decision["verdict"],
        "reason": decision["reason"],
        "answers": decision["answers"],
        "retake": decision["retake"],
    }
    folder = Path(root)
    folder.mkdir(parents=True, exist_ok=True)
    raw = json.dumps(document, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    name = f"production-review-{digest[:20]}.json"
    target = folder / name
    if not target.is_file():
        temporary = folder / f".{name}.tmp"
        temporary.write_bytes(raw)
        temporary.replace(target)
    return {
        "file": name,
        "url": "/api/v1/file/" + quote(name) + "?workspace=" + quote(workspace, safe=""),
        "sha256": digest,
    }


def _decision(verdict: str, reason: str | None, answers: list[dict], retake: list[str]) -> dict:
    return {"verdict": verdict, "reason": reason, "answers": answers, "retake": retake}


def _unique_keys(shots: list) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for item in shots:
        key = _shot_key(item)
        if key not in seen:
            seen.add(key)
            keys.append(key)
    return keys


def _shot_key(item: object) -> str:
    key = item.get("key") if isinstance(item, dict) else None
    if isinstance(key, str) and key and key == key.strip() and len(key) <= 80 and "\x00" not in key:
        return key
    raise ReviewError("invalid_shots", "each shot needs a key.")


def _bad_relative(value: str) -> bool:
    if "\\" in value or "\x00" in value:
        return True
    for part in value.split("/"):
        if part in {"", ".", ".."}:
            return True
        if _control_char(part):
            return True
    return False


def _control_char(part: str) -> bool:
    for char in part:
        if ord(char) < 32 or ord(char) == 127:
            return True
    return False


def _inside(candidate: str, base: str) -> bool:
    if candidate == base:
        return False
    try:
        return os.path.commonpath((
            os.path.normcase(candidate),
            os.path.normcase(base),
        )) == os.path.normcase(base)
    except (TypeError, ValueError, OSError):
        return False


def _unquote_path(value: str) -> str:
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError as error:
        raise ReviewError("path_not_allowed", "Sheet path is not allowed.") from error


def _require_input(arguments: Any) -> dict:
    version_ok = isinstance(arguments, dict) and arguments.get("version") == 1
    payload = arguments.get("input") if isinstance(arguments, dict) else None
    if not version_ok or not isinstance(payload, dict):
        raise ReviewError("invalid_command", "Use version 1 and an input object.")
    return payload


def _workspace_name(payload: dict) -> str:
    workspace = payload.get("workspace")
    if not isinstance(workspace, str) or len(workspace) > 120 or _WORKSPACE.fullmatch(workspace) is None:
        raise ReviewError("invalid_workspace", "workspace is required.")
    return workspace


def _sheet_value(payload: dict) -> str:
    sheet = payload.get("sheet")
    if not isinstance(sheet, str) or not sheet or sheet != sheet.strip() or len(sheet) > 2000 or "\x00" in sheet:
        raise ReviewError("invalid_sheet", "sheet is required.")
    return sheet


_AUTO = object()


def review_production(state: Any, root: str | None = None, *, people: Any = _AUTO, embed: Any = None, sample: Any = None) -> dict:
    """Code review for production.status. Does not load a vision or embedding model."""
    from services.production_review_checks import load_people_detector, run_review

    detector = load_people_detector() if people is _AUTO else people
    return run_review(state, root, people=detector, embed=embed, sample=sample)
