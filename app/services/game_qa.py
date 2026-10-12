"""Style score and duplicate warnings for one image candidate.

Only stills are checked: character, sprite, item, icon, ui, tile and tileset.
A frame sheet (animation, vfx, an animated item) or one parallax layer of a
background would be judged by its layout, not by its look.

Vision stays on unless ``style.qa.vision`` is false; the duplicate check always
runs. ``analyze`` gets ``/api/v1/file`` URLs, a new ``request_id`` per call and
at most ``_TIMEOUT_S`` seconds. A timeout or a transport error pauses vision for
``_PAUSE_S`` seconds, so a hung analyzer costs one wait, not one per candidate.
Without a reference image there is nothing to compare, so no call is made.
A failed check adds ``style_check_unavailable`` and does not fail the batch.
"""
from __future__ import annotations

import functools
import json
import math
import re
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlencode

import numpy as np
from PIL import Image

from services.game_image_ops import dhash, hamming
from services.game_library import game_warning

_STILL_KINDS = frozenset({"character", "sprite", "item", "icon", "ui", "tile", "tileset"})
_SHEET_KEYS = ("atlas", "sheet")
_PROMPT = (
    "Rate 1-5 how well the LAST image matches the art style of the others "
    "(palette, line weight, shading, proportions). "
    'Reply JSON {"score":n,"reason":"short"}'
)
_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "reason": {"type": "string", "maxLength": 200},
    },
    "required": ["score", "reason"],
    "additionalProperties": False,
}
_UNAVAILABLE = "style_check_unavailable"
_MISMATCH = "style_mismatch"
_WARNING_TEXT = {
    "style_check_unavailable": "The style check could not run.",
    "style_mismatch": "The image does not match the style reference.",
}
_MISMATCH_MAX = 2
_DUPLICATE_BITS = 6
_FLAT_LEVELS = 4.0
_MAX_REFS = 3
_TIMEOUT_S = 120.0
_POLL_S = 0.5
_PAUSE_S = 300.0
_PAUSED = {"until": 0.0}


class _Caller:
    def __init__(self, loopback, workspace: str) -> None:
        self.loopback = loopback
        self.workspace = workspace


def note_style(loopback, root: str, workspace: str, game: dict, asset: dict, files: dict, metrics: dict, warnings: list,
               *, attempt_id: str = "", cancelled=None):
    """Add ``styleScore`` and warnings to one candidate. Returns new copies, or the inputs when it does not apply."""
    png = _still(root, asset, files)
    if png is None:
        return metrics, warnings
    metrics = dict(metrics or {})
    warnings = list(warnings or [])
    refs = _sources(root, workspace, _refs(game, asset), png) if _vision(game) else []
    if refs:
        candidate = _file_url(candidate_png(files), workspace)
        request_id = _request_id(game, asset, attempt_id)
        _stamp(metrics, warnings, style_check(_Caller(loopback, workspace), candidate, refs, request_id, cancelled))
    for other_id in _duplicate_codes(root, game, asset, png):
        _push(warnings, "duplicate_of", other_id)
    return metrics, warnings


def style_check(ctx, candidate_url: str, refs, request_id: str = "", cancelled=None) -> dict:
    """Ask ``analyze`` how well the candidate matches up to three references (canonical media URLs)."""
    if _paused() or (cancelled is not None and cancelled()):
        return _unavailable()
    media = [{"source": ref, "kind": "image"} for ref in _three(refs)]
    media.append({"source": candidate_url, "kind": "image"})
    arguments = {
        "request_id": request_id or f"game-style-{uuid.uuid4().hex}",
        "params": {
            "prompt": _PROMPT,
            "workspace": getattr(ctx, "workspace", ""),
            "media": media,
            "max_new_tokens": 256,
            "temperature": 0,
            "json_schema": _SCHEMA,
        },
    }
    state, result = _ask(lambda: ctx.loopback("analyze", arguments), cancelled)
    if state == "down":
        _PAUSED["until"] = time.monotonic() + _PAUSE_S
    if state != "ok":
        return _unavailable()
    return _checked_payload(result)


def duplicates(game: dict, asset: dict, candidate: Path, root: str) -> list[str]:
    """Ids of other approved stills of the same kind within ``_DUPLICATE_BITS``."""
    current = file_dhash(candidate)
    if current is None:
        return []
    found = []
    for other in _approved_peers(game, asset):
        other_id = str(other.get("id") or "")
        other_hash = file_dhash(_inside(root, _approved_image(other)))
        if other_id and other_hash is not None and hamming(current, other_hash) <= _DUPLICATE_BITS:
            found.append(other_id)
    return found


def file_dhash(path: Path | None) -> int | None:
    """``game_image_ops.dhash`` of a file (over black).

    ``None`` when it cannot be read, or when it is flat: every flat image has
    the same hash, so two plain tiles of different colours would match.
    """
    if path is None:
        return None
    try:
        stat = path.stat()
    except OSError:
        return None
    return _cached_dhash(str(path), stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=2048)
def _cached_dhash(path: str, _mtime_ns: int, _size: int) -> int | None:
    """One decode per file version, however many candidates compare against it."""
    try:
        with Image.open(path) as image:
            rgba = np.asarray(image.convert("RGBA"))
    except Exception:  # a truncated, unsupported or oversized image is skipped
        return None
    if rgba.size == 0 or _flat(rgba):
        return None
    return dhash(rgba)


def _flat(rgba: np.ndarray) -> bool:
    over_black = rgba[..., :3].astype(np.float32) * (rgba[..., 3:4] / 255.0)
    gray = over_black.mean(axis=2)
    return float(gray.max() - gray.min()) < _FLAT_LEVELS


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


def _still(root: str, asset: dict, files: dict) -> Path | None:
    """The candidate's picture inside the workspace, or ``None`` when the check does not apply."""
    if not isinstance(asset, dict) or asset.get("kind") not in _STILL_KINDS or _is_sheet(files):
        return None
    return _inside(root, candidate_png(files))


def _is_sheet(files) -> bool:
    return isinstance(files, dict) and any(key in files for key in _SHEET_KEYS)


def _inside(root: str, relative: str) -> Path | None:
    """An existing file under ``root`` for a workspace-relative POSIX path; never an absolute or ``..`` path."""
    if not root or not isinstance(relative, str) or not relative:
        return None
    text = relative.replace("\\", "/")
    if text.startswith("/") or re.match(r"^[A-Za-z]:", text) or ".." in text.split("/"):
        return None
    base = Path(root).resolve()
    path = (base / text).resolve()
    if not path.is_relative_to(base) or not path.is_file():
        return None
    return path


def _file_url(relative: str, workspace: str) -> str:
    """The canonical URL ``analyze`` accepts, as ``game_tools.file_ref`` builds it."""
    rel = relative.replace("\\", "/").lstrip("/")
    return f"/api/v1/file/{quote(rel)}?{urlencode({'workspace': workspace})}"


def _request_id(game: dict, asset: dict, attempt_id: str) -> str:
    """Readable in the journal and new per call: a reused id would replay or refuse an older answer."""
    stem = f"game-{(game or {}).get('id')}-{asset.get('id')}-{attempt_id or 'candidate'}-style"
    return f"{stem[:140]}-{uuid.uuid4().hex[:12]}"


def _vision(game: dict) -> bool:
    style = game.get("style") if isinstance(game, dict) else None
    qa = style.get("qa") if isinstance(style, dict) else None
    if not isinstance(qa, dict):
        return True
    return qa.get("vision") is not False


def _refs(game: dict, asset: dict) -> list[str]:
    from services.game_prompts import refs_for
    found = refs_for(game, asset)
    return [item for item in found if isinstance(item, str)]


def _sources(root: str, workspace: str, refs: list[str], candidate: Path) -> list[str]:
    """Up to three reference URLs whose files exist, never the candidate itself."""
    found: list[str] = []
    for ref in refs:
        path = _inside(root, ref)
        if path is None or path == candidate:
            continue
        url = _file_url(ref, workspace)
        if url not in found:
            found.append(url)
    return found[:_MAX_REFS]


def _three(refs) -> list[str]:
    return [ref for ref in list(refs or []) if isinstance(ref, str) and ref][:_MAX_REFS]


def _paused() -> bool:
    return time.monotonic() < _PAUSED["until"]


def _ask(call, cancelled) -> tuple[str, object]:
    """``("ok", result)``, ``("down", None)`` on a timeout or an exception, ``("cancelled", None)``."""
    box: dict = {}

    def run() -> None:
        try:
            box["result"] = call()
        except Exception as error:  # reported as "down" below
            box["error"] = error

    worker = threading.Thread(target=run, name="game-style-check", daemon=True)
    worker.start()
    deadline = time.monotonic() + _TIMEOUT_S
    while worker.is_alive() and time.monotonic() < deadline:
        if cancelled is not None and cancelled():
            return "cancelled", None
        worker.join(min(_POLL_S, max(0.0, deadline - time.monotonic())))
    if worker.is_alive() or "error" in box:
        return "down", None
    return "ok", box.get("result")


def _unavailable() -> dict:
    return {"score": None, "reason": _UNAVAILABLE}


def _checked_payload(result) -> dict:
    payload = _payload(result)
    score = _score(payload)
    if score is None:
        return _unavailable()
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
    return _json_object(text[:8000])


def _json_object(text: str) -> dict | None:
    """The first JSON object in ``text`` that has a ``score``; prose or a second object around it is ignored."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        try:
            found, _end = decoder.raw_decode(text, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(found, dict) and "score" in found:
            return found
    return None


def _score(payload) -> int | None:
    """A finite number from 1 to 5, rounded half up. Anything else is no score."""
    if not isinstance(payload, dict):
        return None
    raw = payload.get("score")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw):
        return None
    if raw < 1 or raw > 5:
        return None
    return int(math.floor(raw + 0.5))


def _stamp(metrics: dict, warnings: list, checked: dict) -> None:
    score = checked.get("score")
    if score is None:
        _push(warnings, _UNAVAILABLE)
        return
    metrics["styleScore"] = score
    if score <= _MISMATCH_MAX:
        _push(warnings, _MISMATCH)


def _duplicate_codes(root: str, game: dict, asset: dict, png: Path) -> list[str]:
    try:
        return duplicates(game, asset, png, root)
    except Exception:  # duplicates are advisory; the candidate is still saved
        return []


def _approved_peers(game: dict, asset: dict) -> list[dict]:
    """Other approved assets of the same kind. The asset itself and its own candidates never count."""
    return [
        other for other in (game or {}).get("assets") or []
        if isinstance(other, dict) and other.get("id") != asset.get("id")
        and other.get("kind") == asset.get("kind") and other.get("status") == "approved"
    ]


def _approved_image(asset: dict) -> str:
    approved = asset.get("approvedAttemptId")
    for attempt in asset.get("attempts") or []:
        if approved and isinstance(attempt, dict) and attempt.get("id") == approved:
            files = attempt.get("files")
            return "" if _is_sheet(files) else candidate_png(files or {})
    return ""


def _same_warning(item, code: str, ref: str | None) -> bool:
    if isinstance(item, str):
        head, _, tail = item.partition(":")
        return head == code and (ref is None or tail == ref)
    if not isinstance(item, dict):
        return False
    return item.get("code") == code and (ref is None or item.get("ref") == ref)


def _push(warnings: list, code: str, ref: str | None = None) -> None:
    if not code or any(_same_warning(item, code, ref) for item in warnings):
        return
    if code == "duplicate_of":
        warnings.append(game_warning(code, f"Same picture as {ref}.", ref=ref))
        return
    warnings.append(game_warning(code, _WARNING_TEXT.get(code, code)))
