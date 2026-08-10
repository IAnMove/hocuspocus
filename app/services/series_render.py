"""Pure Series Lab shot-to-generation adapter for the MiniMax H3 path."""

from __future__ import annotations

import copy
from typing import Any


H3_RESOLUTIONS = {
    ("landscape", "480p"): "864x480",
    ("portrait", "480p"): "480x864",
    ("landscape", "720p"): "1280x704",
    ("portrait", "720p"): "704x1280",
    ("landscape", "540p"): "960x544",
    ("portrait", "540p"): "544x960",
    ("landscape", "768p"): "1344x768",
    ("portrait", "768p"): "768x1344",
}


def normalize_series_resolution(
    value: Any,
    orientation: Any = "landscape",
    requested_model: Any = "minimax_h3",
) -> tuple[str, str]:
    raw_orientation = str(orientation or "landscape").strip().lower()
    normalized_orientation = "portrait" if raw_orientation in {"portrait", "vertical", "9:16"} else "landscape"
    legacy = str(requested_model or "") == "minimax_h3_legacy"
    raw = str(value or ("540p" if legacy else "480p")).strip().lower()
    if legacy:
        quality = "768p" if raw in {
            "720", "720p", "768", "768p", "1280x704", "1344x768", "768x1344",
        } else "540p"
    else:
        quality = "720p" if raw in {
            "540", "540p", "720", "720p", "768", "768p", "1280x720",
            "1280x704", "720x1280", "704x1280", "1344x768", "768x1344",
        } else "480p"
    return H3_RESOLUTIONS[(normalized_orientation, quality)], normalized_orientation


def quantize_h3_frames(duration_seconds: Any, *, reference_mode: bool) -> int:
    try:
        requested = round(max(1.0, float(duration_seconds)) * 24)
    except (TypeError, ValueError):
        requested = 124
    # H3 pixel frames use 17*n+5. FL2VA can continue through sliding windows;
    # Omni is one native request and therefore caps at its 345-frame window.
    requested = min(requested, 345) if reference_mode else requested
    return max(107, round((requested - 5) / 17) * 17 + 5)


def shot_generation_prompt(series: dict, shot: dict) -> str:
    character_names = {
        str(item.get("id")): str(item.get("name") or item.get("id"))
        for item in series.get("characters", []) if isinstance(item, dict) and item.get("id")
    }
    dialogue_parts = []
    for beat in shot.get("dialogueBeats", []) if isinstance(shot.get("dialogueBeats"), list) else []:
        if not isinstance(beat, dict) or not str(beat.get("text") or "").strip():
            continue
        speaker = character_names.get(str(beat.get("characterId") or ""), str(beat.get("characterId") or "Speaker"))
        emotion = str(beat.get("emotion") or "natural").strip()
        delivery = str(beat.get("delivery") or "natural delivery").strip()
        dialogue_parts.append(
            f'{speaker} says exactly, "{str(beat.get("text")).strip()}" '
            f"with {emotion} emotion and {delivery}."
        )
    prompt_parts = []
    if series.get("sourceMode") in {"known_universe_experimental", "hybrid"}:
        master = str(series.get("masterUniversePrompt") or "").strip()
        if master:
            prompt_parts.append(master)
    for value in (
        series.get("visualStyle"),
        f"Every visible character follows this rendering contract: {series.get('characterVisualStyle')}"
        if series.get("characterVisualStyle") else "",
        shot.get("prompt"),
        f"Action: {shot.get('action')}" if shot.get("action") else "",
        f"Camera: {shot.get('framing')}; {shot.get('camera')}" if shot.get("framing") or shot.get("camera") else "",
        *dialogue_parts,
        f"Ambience and foley only: {shot.get('audioDirection')}" if shot.get("audioDirection") else "",
    ):
        text = str(value or "").strip()
        if text:
            prompt_parts.append(text)
    if not series.get("allowClipText"):
        prompt_parts.append("No captions, subtitles, signs, interface text, or floating words appear in the image.")
    return "\n".join(prompt_parts)


def model_for_manifest(requested_model: str, manifest: dict) -> str:
    if str(requested_model or "") == "minimax_h3_legacy":
        return "minimax_h3_legacy"
    strategy = str(manifest.get("strategy") or "direct")
    full = str(requested_model or "").endswith("_full")
    if strategy == "references":
        return "minimax_h3_ref2va_full" if full else "minimax_h3_ref2va"
    return "minimax_h3_full" if full else "minimax_h3"


def _h3_reference(item: dict, path: str) -> dict:
    media_type = str(item.get("mediaType") or "image")
    role = str(item.get("referenceRole") or "visual reference").replace("_", " ")
    entity = str(item.get("entityId") or "subject")
    result = {
        "type": media_type,
        "path": path,
        "role": f"{role} for {entity}",
    }
    if media_type == "image":
        result["image_intent"] = (
            "composition" if item.get("referenceRole") == "composed_start_frame"
            else "scene" if item.get("entityType") == "location"
            else "identity"
        )
    elif media_type == "audio":
        result["audio_intent"] = "voice" if item.get("entityType") == "character" else "guide"
    elif media_type == "video":
        result["video_intent"] = "motion"
    return result


def build_h3_generation_params(
    series: dict,
    shot: dict,
    attempt: dict,
    resolved_references: dict[str, str],
) -> dict:
    manifest = attempt.get("referenceManifest") if isinstance(attempt.get("referenceManifest"), dict) else {}
    strategy = str(manifest.get("strategy") or "direct")
    settings = copy.deepcopy(attempt.get("settings")) if isinstance(attempt.get("settings"), dict) else {}
    requested_model = str(attempt.get("model") or "minimax_h3")
    resolution, orientation = normalize_series_resolution(
        settings.get("resolution"), settings.get("orientation"), requested_model,
    )
    model = model_for_manifest(requested_model, manifest)
    params = {
        "model_type": model,
        "prompt": str(attempt.get("prompt") or shot_generation_prompt(series, shot)),
        "negative_prompt": str(attempt.get("negativePrompt") or ""),
        "image_mode": 0,
        "image_prompt_type": "",
        "num_inference_steps": max(1, min(50, int(settings.get("numInferenceSteps") or 20))),
        "guidance_scale": float(settings.get("guidanceScale") or 1),
        "resolution": resolution,
        "video_length": int(settings.get("videoLengthFrames"))
        if settings.get("videoLengthFrames") is not None else quantize_h3_frames(
            shot.get("durationSeconds"), reference_mode=strategy == "references",
        ),
        "seed": int(attempt.get("seed")) if attempt.get("seed") is not None else -1,
        "settings_version": 2.52,
        "generation_mode": "video",
        "repeat_generation": 1,
        "flow_shift": float(settings.get("flowShift") or 12),
        "h3_audio_shift": float(settings.get("audioShift") or 3),
        "h3_model_profile": str(settings.get("modelProfile") or "quality"),
        "_series_context": {
            "seriesId": series.get("id"), "shotId": shot.get("id"),
            "attemptId": attempt.get("id"), "referenceManifest": copy.deepcopy(manifest),
            "orientation": orientation,
        },
    }
    if model == "minimax_h3_legacy":
        params.update({
            "num_inference_steps": 20,
            "flow_shift": 12.0,
            "h3_audio_shift": 3.0,
            "h3_model_profile": "quality",
            "minimax_h3_turbo_mode": False,
            "activated_loras": [],
            "loras_multipliers": "",
            "video_length": max(124, int(params["video_length"])),
        })
    selected = manifest.get("selected") if isinstance(manifest.get("selected"), list) else []
    reference_pairs = [
        (item, _h3_reference(item, resolved_references[str(item.get("assetId"))]))
        for item in selected if isinstance(item, dict) and str(item.get("assetId")) in resolved_references
    ]
    references = [reference for _manifest_item, reference in reference_pairs]
    if strategy == "direct":
        references = []
    elif strategy == "references":
        if not references:
            raise ValueError("Ref2VA cannot start without routed references")
        if model == "minimax_h3_legacy":
            params["h3_reference_mode"] = "references"
            params["image_refs"] = [
                reference["path"] for reference in references
                if reference.get("type") == "image"
            ]
            params["h3_ref_videos"] = [
                reference["path"] for reference in references
                if reference.get("type") == "video"
            ]
            params["h3_ref_audios"] = [
                reference["path"] for reference in references
                if reference.get("type") == "audio"
            ]
        else:
            params["minimax_h3_references"] = references
            params["minimax_h3_reference_detail"] = "match"
    else:
        first_image = next((
            reference["path"] for manifest_item, reference in reference_pairs
            if reference.get("type") == "image"
            and manifest_item.get("referenceRole") == "composed_start_frame"
        ), "")
        if not first_image:
            raise ValueError("First-frame generation requires one routed exact start image")
        params["image_start"] = first_image
        params["image_prompt_type"] = "S"
        if strategy == "first_last":
            last_image = next((
                reference["path"] for manifest_item, reference in reference_pairs
                if reference.get("type") == "image"
                and manifest_item.get("referenceRole") == "composed_end_frame"
            ), "")
            if not last_image:
                raise ValueError("First-and-last generation requires one routed exact end image")
            params["image_end"] = last_image
            params["image_prompt_type"] = "SE"
        params["sliding_window_size"] = 345
        params["sliding_window_overlap"] = 1
        params["sliding_window_discard_last_frames"] = 0
    return params
