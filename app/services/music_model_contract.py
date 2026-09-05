"""Declarative music model contract: catalog, availability, compile.

Does not import FastAPI, WanGP or launch. Does not download weights or call
providers. Remote MiniMax's 300-character prompt cap is applied only when
compiling that backend, never when freezing a local caption.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from .lyrics_language import repair_lyrics_language, validate_lyrics_language
from .minimax_music_service import ALLOWED_MODELS, COVER_MODELS


GUIDE_REVISION = "music-model-contract-v1"
SCHEMA_NAME = "hocuspocus.music-generation-spec"

ACE_DEFAULT = "ace_step_v1_5_xl_sft_lm_4b"
MUSIC3_LOCAL = "minimax_music3"
REMOTE_DEFAULT = "music-3.0"

ACE_PROMPT_LIMIT = 8000
ACE_LYRICS_LIMIT = 8000
MUSIC3_PROMPT_LIMIT = 8000
MUSIC3_LYRICS_LIMIT = 8000
REMOTE_PROMPT_LIMIT = 300
REMOTE_LYRICS_LIMIT = 3500
DURATION_MIN = 20
ACE_DURATION_MAX = 360
MUSIC3_DURATION_MAX = 300
REMOTE_DURATION_MAX = 240
REMOTE_COUNT_MAX = 3

COMMUNITY_MODELS = (
    "minimax_music3_gguf",
    "minimax_music3_mlx",
    "minimax_music3_webgpu",
)


class MusicModelError(ValueError):
    def __init__(self, message: str, status_code: int = 400, details: Mapping[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.details = dict(details or {})


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _ace_profile(model_id: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "family": "ace_step",
        "route": "local",
        "downloadable": True,
        "community": False,
        "prompt_limit": ACE_PROMPT_LIMIT,
        "lyrics_limit": ACE_LYRICS_LIMIT,
        "duration_min": DURATION_MIN,
        "duration_max": ACE_DURATION_MAX,
        "count_max": 1,
        "modes": ("original", "instrumental"),
        "caption_format": "ace_style_prose",
        "lyrics_format": "section_tags",
        "backend": "generateMusic",
    }


def _music3_profile() -> dict[str, Any]:
    return {
        "id": MUSIC3_LOCAL,
        "family": "minimax_music3",
        "route": "local",
        "downloadable": True,
        "community": False,
        "prompt_limit": MUSIC3_PROMPT_LIMIT,
        "lyrics_limit": MUSIC3_LYRICS_LIMIT,
        "duration_min": DURATION_MIN,
        "duration_max": MUSIC3_DURATION_MAX,
        "count_max": 1,
        "modes": ("original", "instrumental"),
        "caption_format": "structured_metadata",
        "lyrics_format": "section_tags",
        "backend": "generateMusic",
    }


def _remote_profile(model_id: str) -> dict[str, Any]:
    cover = model_id in COVER_MODELS
    return {
        "id": model_id,
        "family": "minimax_remote",
        "route": "remote_minimax",
        "downloadable": False,
        "community": False,
        "prompt_limit": REMOTE_PROMPT_LIMIT,
        "lyrics_limit": REMOTE_LYRICS_LIMIT,
        "duration_min": DURATION_MIN,
        "duration_max": REMOTE_DURATION_MAX,
        "count_max": REMOTE_COUNT_MAX,
        "modes": ("cover",) if cover else ("original", "instrumental"),
        "caption_format": "minimax_style_prompt",
        "lyrics_format": "section_tags",
        "backend": "minimax_api",
        "cover": cover,
    }


def _community_profile(model_id: str) -> dict[str, Any]:
    return {
        "id": model_id,
        "family": "community",
        "route": "unavailable",
        "downloadable": False,
        "community": True,
        "prompt_limit": MUSIC3_PROMPT_LIMIT,
        "lyrics_limit": MUSIC3_LYRICS_LIMIT,
        "duration_min": DURATION_MIN,
        "duration_max": MUSIC3_DURATION_MAX,
        "count_max": 1,
        "modes": ("original",),
        "caption_format": "structured_metadata",
        "lyrics_format": "section_tags",
        "backend": None,
    }


def catalog_entry(model: str | None) -> dict[str, Any] | None:
    token = _clean(model)
    if not token:
        return None
    if token == MUSIC3_LOCAL:
        return _music3_profile()
    if token in COMMUNITY_MODELS:
        return _community_profile(token)
    if token in ALLOWED_MODELS:
        return _remote_profile(token)
    if token.startswith("ace_step") or token == "ace-step":
        return _ace_profile(ACE_DEFAULT if token == "ace-step" else token)
    return None


def require_catalog_entry(model: str | None) -> dict[str, Any]:
    entry = catalog_entry(model)
    if entry is None:
        raise MusicModelError(f"Unknown music model: {_clean(model) or '(empty)'}")
    if entry["community"] or entry["route"] == "unavailable":
        raise MusicModelError(
            f"Music model {entry['id']!r} needs a validated adapter before it can run",
            details={"known": True, "compatible": False, "available": False},
        )
    return entry


def inspect_music_model(
    model: str | None,
    *,
    installed: bool = False,
    enabled: bool = True,
    configured: bool = False,
    compatible: bool | None = None,
) -> dict[str, Any]:
    """Classify known/downloadable/incomplete/installed/compatible/configured/available.

    Callers pass inventory flags. This does not scan disk or download assets.
    """
    token = _clean(model)
    entry = catalog_entry(token)
    reasons: list[str] = []
    if entry is None:
        return {
            "model": token,
            "known": False,
            "downloadable": False,
            "incomplete": False,
            "installed": False,
            "compatible": False,
            "configured": False,
            "enabled": bool(enabled),
            "available": False,
            "route": None,
            "unavailable_reasons": ["Unknown music model."],
        }
    community = bool(entry["community"])
    downloadable = bool(entry["downloadable"])
    local = entry["route"] == "local"
    if compatible is None:
        compatible = not community
    configured_flag = True if local else bool(configured)
    installed_flag = bool(installed) if local and downloadable else False
    incomplete = downloadable and local and not installed_flag
    if community:
        reasons.append("Needs a validated adapter; not compatible with the bundled backend.")
    if not enabled:
        reasons.append("The model is disabled.")
    if not compatible:
        reasons.append("The model is not compatible with this runtime.")
    if local and downloadable and not installed_flag:
        reasons.append("Required assets are not installed.")
    if not local and not configured_flag:
        reasons.append("The remote provider is not configured.")
    available = (
        not community
        and bool(enabled)
        and bool(compatible)
        and configured_flag
        and (installed_flag if local else True)
    )
    return {
        "model": entry["id"],
        "known": True,
        "downloadable": downloadable,
        "incomplete": incomplete,
        "installed": installed_flag,
        "compatible": bool(compatible),
        "configured": configured_flag,
        "enabled": bool(enabled),
        "available": available,
        "route": entry["route"],
        "unavailable_reasons": reasons,
    }


def mode_for(entry: Mapping[str, Any], *, instrumental: bool, cover: bool) -> str:
    if cover or entry.get("cover"):
        return "cover"
    if instrumental:
        return "instrumental"
    return "original"


def compile_backend_request(
    entry: Mapping[str, Any],
    *,
    caption: str,
    lyrics: str,
    instrumental: bool,
    duration_seconds: int,
    count: int,
    reference_audio_filename: str | None = None,
) -> dict[str, Any]:
    prompt_limit = int(entry["prompt_limit"])
    lyrics_limit = int(entry["lyrics_limit"])
    compiled_prompt = caption[:prompt_limit]
    compiled_lyrics = "" if instrumental else lyrics[:lyrics_limit]
    payload = {
        "backend": entry["backend"],
        "model": entry["id"],
        "route": entry["route"],
        "prompt": compiled_prompt,
        "lyrics": compiled_lyrics,
        "instrumental": bool(instrumental),
        "duration_seconds": duration_seconds,
        "count": count,
        "truncated_prompt": len(caption) > prompt_limit,
        "truncated_lyrics": (not instrumental) and len(lyrics) > lyrics_limit,
    }
    if reference_audio_filename:
        payload["reference_audio_filename"] = reference_audio_filename
    return payload


def _language_guard(
    lyrics: str,
    lyrics_language: str,
    *,
    instrumental: bool,
    protected_segments: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    report = validate_lyrics_language(
        lyrics,
        lyrics_language,
        protected_segments=protected_segments,
        instrumental=instrumental,
    )
    return {
        "ok": bool(report.get("ok")),
        "verdict": report.get("verdict"),
        "reasons": list(report.get("reasons") or []),
        "language_mismatch": bool(report.get("language_mismatch")),
    }


def _count_for(request: Mapping[str, Any], entry: Mapping[str, Any]) -> int:
    default = 2 if entry["route"] == "remote_minimax" else 1
    try:
        return _clamp(_int(request.get("count"), default), 1, int(entry["count_max"]))
    except (TypeError, ValueError, OverflowError) as exc:
        raise MusicModelError("Music candidate count must be an integer") from exc


def _lyrics_language_for(request: Mapping[str, Any]) -> str:
    intent = request.get("language_intent") if isinstance(request.get("language_intent"), Mapping) else {}
    return _clean(
        request.get("lyrics_language")
        or request.get("content_language")
        or intent.get("spokenLanguage")
        or intent.get("spoken_language")
        or intent.get("contentLanguage")
        or intent.get("content_language")
    )


def _protected_segments(request: Mapping[str, Any]) -> Sequence[Mapping[str, Any]] | None:
    protected = request.get("protected_segments")
    if not isinstance(protected, Sequence) or isinstance(protected, (str, bytes)):
        return None
    return protected


def freeze_music_spec(request: Mapping[str, Any]) -> dict[str, Any]:
    """Durable spec. Local captions are not sliced to the remote 300-char cap."""
    provenance = request.get("provenance") if isinstance(request.get("provenance"), Mapping) else {}
    model = _clean(request.get("model")) or REMOTE_DEFAULT
    entry = require_catalog_entry(model)
    caption = _clean(request.get("prompt") or request.get("caption"))
    lyrics = str(request.get("lyrics") or "").strip()
    instrumental = bool(request.get("instrumental"))
    duration = _clamp(
        _int(request.get("duration_seconds"), 90),
        int(entry["duration_min"]),
        int(entry["duration_max"]),
    )
    count = _count_for(request, entry)
    reference = _clean(request.get("reference_audio_filename")) or None
    compiled = compile_backend_request(
        entry,
        caption=caption,
        lyrics=lyrics,
        instrumental=instrumental,
        duration_seconds=duration,
        count=count,
        reference_audio_filename=reference,
    )
    lyrics_language = _lyrics_language_for(request)
    guard = _language_guard(
        lyrics, lyrics_language,
        instrumental=instrumental,
        protected_segments=_protected_segments(request),
    )
    return {
        "schema": SCHEMA_NAME,
        "guide_revision": GUIDE_REVISION,
        "model": entry["id"],
        "route": entry["route"],
        "mode": mode_for(entry, instrumental=instrumental, cover=bool(entry.get("cover"))),
        "prompt": caption,
        "lyrics": lyrics,
        "instrumental": instrumental,
        "count": count,
        "duration_seconds": duration,
        "lyrics_language": lyrics_language or None,
        "languages": {
            "lyrics": lyrics_language or None,
            "conversation": _clean(request.get("conversation_language")) or None,
            "technical_prompt": _clean(request.get("technical_prompt_language")) or "en",
        },
        "language_guard": guard,
        "compiled": compiled,
        "project_id": _clean(request.get("project_id") or provenance.get("project_id")) or None,
        "cue_id": _clean(request.get("cue_id") or provenance.get("cue_id")) or None,
        "candidate_id": _clean(request.get("candidate_id") or provenance.get("candidate_id")) or None,
        "output_folder": None,
        "workspace_id": _clean(request.get("workspace_id")) or None,
        "library_revision": request.get("library_revision", request.get("expectedVersion")),
        "reference_audio_filename": reference,
        "intent": None,
    }


def assert_enqueue_guard(spec: Mapping[str, Any]) -> None:
    """Block invalid lyrics. Unevaluable is recorded, not treated as ok."""
    guard = spec.get("language_guard") if isinstance(spec.get("language_guard"), Mapping) else {}
    if guard.get("verdict") != "invalid":
        return
    lyrics = str(spec.get("lyrics") or "")
    repaired = repair_lyrics_language(
        lyrics,
        str(spec.get("lyrics_language") or ""),
        instrumental=bool(spec.get("instrumental")),
    )
    raise MusicModelError(
        "La letra no respeta el idioma solicitado: " + " ".join(str(item) for item in (guard.get("reasons") or [])),
        details={
            "language_guard": dict(guard),
            "proposal": repaired.get("proposal"),
            "proposal_diffs": repaired.get("proposal_diffs") or [],
            "lyrics": lyrics,
        },
    )
