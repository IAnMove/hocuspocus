"""Style score and duplicate warnings for one image candidate.

Vision stays on unless ``style.qa.vision`` is false. A missing analyzer adds
``style_check_unavailable`` and does not fail the batch.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from PIL import Image

_IMAGE_KINDS = frozenset({
    "character", "sprite", "item", "icon", "ui", "tile", "tileset", "background", "animation", "vfx",
})
_PROMPT = (
    "Rate 1-5 how well the LAST image matches the art style of the others "
    "(palette, line weight, shading, proportions). "
    'Reply JSON {"score":n,"reason":"short"}'
)
_UNAVAILABLE = "style_check_unavailable"


class _Caller:
    def __init__(self, loopback, workspace: str) -> None:
        self.loopback = loopback
        self.workspace = workspace


def note_style(loopback, root: str, workspace: str, game: dict, asset: dict, files: dict, metrics: dict, warnings: list):
    """Add ``styleScore`` and warnings. Returns the same pair when vision is off."""
    if not _applies(game, asset, files):
        return metrics, warnings
    metrics = dict(metrics)
    warnings = list(warnings or [])
    relative = candidate_png(files)
    _stamp(metrics, warnings, _checked(loopback, workspace, game, asset, relative))
    for code in _duplicate_codes(root, game, asset, _resolve(root, relative)):
        _push(warnings, code)
    return metrics, warnings


def style_check(ctx, candidate_png: str, refs) -> dict:
    """Ask ``analyze`` how well the candidate matches up to three references."""
    media = [{"source": ref, "kind": "image"} for ref in _three(refs)]
    media.append({"source": candidate_png, "kind": "image"})
    try:
        result = ctx.loopback("analyze", {
            "request_id": "game-style",
            "params": {
                "prompt": _PROMPT,
                "workspace": getattr(ctx, "workspace", ""),
                "media": media,
                "max_new_tokens": 512,
            },
        })
    except Exception:
        return {"score": None, "reason": _UNAVAILABLE}
    return _checked_payload(result)


def duplicates(game: dict, asset: dict, candidate_png: str, root: str = "") -> list[str]:
    """dHash distance of 6 or less against an approved asset of the same kind."""
    current = dhash(candidate_png)
    if current is None:
        return []
    found = []
    for other in game.get("assets") or []:
        code = _duplicate_of(other, asset, current, root)
        if code:
            found.append(code)
    return found


def dhash(path: str) -> int | None:
    """64-bit difference hash. ``None`` when the file cannot be read."""
    try:
        image = Image.open(path).convert("L").resize((9, 8), Image.Resampling.BOX)
    except (OSError, ValueError):
        return None
    pixels = np.asarray(image, dtype=np.int16)
    bits = 0
    for value in (pixels[:, 1:] > pixels[:, :-1]).flatten():
        bits = (bits << 1) | int(bool(value))
    return bits


def candidate_png(files: dict) -> str:
    if not isinstance(files, dict):
        return ""
    for key in ("main", "preview", "sheet"):
        value = files.get(key)
        if isinstance(value, str) and value.lower().endswith(".png"):
            return value
    for key, value in files.items():
        if str(key).startswith("layer") and isinstance(value, str) and value.lower().endswith(".png"):
            return value
    return ""


def _applies(game: dict, asset: dict, files: dict) -> bool:
    if not isinstance(asset, dict) or asset.get("kind") not in _IMAGE_KINDS:
        return False
    if not _vision(game):
        return False
    return bool(candidate_png(files))


def _vision(game: dict) -> bool:
    style = game.get("style") if isinstance(game, dict) else None
    qa = style.get("qa") if isinstance(style, dict) else None
    if not isinstance(qa, dict):
        return True
    return qa.get("vision") is not False


def _checked(loopback, workspace: str, game: dict, asset: dict, relative: str) -> dict:
    try:
        return style_check(_Caller(loopback, workspace), relative, _refs(game, asset))
    except Exception:
        return {"score": None, "reason": _UNAVAILABLE}


def _refs(game: dict, asset: dict) -> list[str]:
    from services.game_prompts import refs_for
    found = refs_for(game, asset)
    return [item for item in found if isinstance(item, str)]


def _three(refs) -> list[str]:
    return [ref for ref in list(refs or []) if isinstance(ref, str) and ref][:3]


def _checked_payload(result) -> dict:
    payload = _payload(result)
    score = _score(payload)
    if payload is None or score is None:
        return {"score": None, "reason": _UNAVAILABLE}
    reason = payload.get("reason")
    return {"score": score, "reason": reason if isinstance(reason, str) and reason else "ok"}


def _payload(result) -> dict | None:
    if not isinstance(result, dict) or result.get("error") or result.get("_is_error"):
        return None
    if "score" in result:
        return result
    text = result.get("text")
    if not isinstance(text, str):
        return None
    return _json_object(text)


def _json_object(text: str) -> dict | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        found = json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None
    return found if isinstance(found, dict) else None


def _score(payload) -> int | None:
    if not isinstance(payload, dict):
        return None
    raw = payload.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    number = int(raw)
    if number < 1 or number > 5:
        return None
    return number


def _stamp(metrics: dict, warnings: list, checked: dict) -> None:
    score = checked.get("score")
    if score is None:
        _push(warnings, _UNAVAILABLE)
        return
    metrics["styleScore"] = score
    if score <= 2:
        _push(warnings, "style_mismatch")


def _duplicate_codes(root: str, game: dict, asset: dict, png: str) -> list[str]:
    try:
        return duplicates(game, asset, png, root)
    except Exception:
        return []


def _duplicate_of(other: dict, asset: dict, current: int, root: str) -> str:
    if not isinstance(other, dict) or other.get("id") == asset.get("id"):
        return ""
    if other.get("kind") != asset.get("kind") or other.get("status") != "approved":
        return ""
    path = _approved_image(other)
    if not path:
        return ""
    other_hash = dhash(_resolve(root, path))
    if other_hash is None or _distance(current, other_hash) > 6:
        return ""
    return f"duplicate_of:{other.get('id')}"


def _approved_image(asset: dict) -> str:
    chosen = None
    for attempt in asset.get("attempts") or []:
        if isinstance(attempt, dict) and attempt.get("id") == asset.get("approvedAttemptId"):
            chosen = attempt
    files = (chosen or {}).get("files") if isinstance(chosen, dict) else None
    return candidate_png(files or {})


def _resolve(root: str, relative: str) -> str:
    path = Path(relative)
    if path.is_absolute() or not root:
        return str(path)
    return str(Path(root) / relative)


def _distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()


def _push(warnings: list, code: str) -> None:
    if code and code not in warnings:
        warnings.append(code)
