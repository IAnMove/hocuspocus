"""Pure Series Lab shot-to-generation adapter for the MiniMax H3 path."""

from __future__ import annotations

import copy
import re
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

SERIES_SHOT_DURATIONS = (5, 10, 15)


def normalize_series_shot_duration(value: Any) -> int:
    """Quantize Series clips to the supported 5/10/15-second contract."""
    try:
        requested = float(value)
    except (TypeError, ValueError):
        requested = 10.0
    return min(
        SERIES_SHOT_DURATIONS,
        key=lambda duration: (
            abs(float(duration) - requested),
            0 if duration == 10 else 1,
            duration,
        ),
    )


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
        # Keep all four H3 Legacy tiers distinct.  This function is called when
        # an attempt is frozen and again when its generation payload is built,
        # so exact model-aligned canvases must be idempotent: 1280x704 is the
        # 720p tier, not a signal to promote the job to the 1344x768 maximum.
        if raw in {"480", "480p", "864x480", "480x864"}:
            quality = "480p"
        elif raw in {"720", "720p", "1280x704", "704x1280"}:
            quality = "720p"
        elif raw in {"768", "768p", "1344x768", "768x1344"}:
            quality = "768p"
        else:
            quality = "540p"
    else:
        quality = "720p" if raw in {
            "540", "540p", "720", "720p", "768", "768p", "1280x720",
            "1280x704", "720x1280", "704x1280", "1344x768", "768x1344",
        } else "480p"
    return H3_RESOLUTIONS[(normalized_orientation, quality)], normalized_orientation


def quantize_h3_frames(duration_seconds: Any, *, reference_mode: bool) -> int:
    requested = round(normalize_series_shot_duration(duration_seconds) * 24)
    # H3 pixel frames use 17*n+5. FL2VA can continue through sliding windows;
    # Omni is one native request and therefore caps at its 345-frame window.
    # Apply the same ceiling to every Series path: the next lattice point is
    # 362 frames (15.08s at 24fps), which would violate the hard 15-second
    # per-video contract even though the requested duration was nominally 15.
    requested = min(requested, 345) if reference_mode else requested
    return min(345, max(107, round((requested - 5) / 17) * 17 + 5))


def _h3_spoken_language(series: dict) -> tuple[str, str]:
    from .director.spoken_language import h3_language_tag, normalize_spoken_language

    language = normalize_spoken_language(
        series.get("spokenLanguage") or series.get("language")
    )
    tag = h3_language_tag(language) or "English"
    folded = language.casefold()
    if tag == "Spanish":
        regional = (
            "Latin American Spanish."
            if any(token in folded for token in ("latino", "latin american", "latinoamericano"))
            else "Castilian Spanish."
        )
    else:
        regional = f"Native {language or tag}."
    return tag, regional


def _h3_scene_description(series: dict, shot: dict) -> str:
    parts = []
    if series.get("protagonistConsistency") and series.get("protagonistCharacterId"):
        protagonist = next((
            character for character in series.get("characters", [])
            if character.get("id") == series.get("protagonistCharacterId")
        ), None)
        if protagonist:
            parts.append(
                "Identity lock: "
                f"{protagonist.get('name') or 'the protagonist'} matches the approved primary "
                "character portrait exactly, preserving face, body design, hair, proportions, "
                "and canonical wardrobe"
            )
    authored_prompt = " ".join(str(shot.get("prompt") or "").split()).strip()
    action = " ".join(str(shot.get("action") or "").split()).strip()
    values = [authored_prompt]
    if action and action.casefold() not in authored_prompt.casefold():
        values.append(f"Action: {action}")
    values.append(
        f"Camera: {shot.get('framing')}; {shot.get('camera')}"
        if shot.get("framing") or shot.get("camera") else ""
    )
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text:
            parts.append(text)
    if not series.get("allowClipText"):
        parts.append(
            "No captions, subtitles, signs, interface text, or floating words are visible"
        )
    return ". ".join(part.rstrip(". ") for part in parts if part) + "."


def _h3_dialogue_timing_hint(word_count: int, duration_seconds: float) -> str:
    """Anchor sparse speech so H3 does not treat the whole clip as vocal time."""
    duration = max(0.0, float(duration_seconds or 0))
    spoken_duration = max(0.8, word_count / 2.1)
    if not word_count or duration <= 0 or spoken_duration >= duration * 0.6:
        return ""
    start = min(1.0, max(0.0, duration * 0.1))
    end = min(duration - 0.25, start + spoken_duration)
    return f"From {start:.2f} to {end:.2f} seconds,"


def _h3_dialogue_description(series: dict, shot: dict, character_names: dict[str, str]) -> str:
    language_tag, accent_direction = _h3_spoken_language(series)
    beats = [
        beat for beat in (
            shot.get("dialogueBeats", []) if isinstance(shot.get("dialogueBeats"), list) else []
        )
        if isinstance(beat, dict) and str(beat.get("text") or "").strip()
    ]
    if not beats:
        return ""

    duration = normalize_series_shot_duration(shot.get("durationSeconds"))
    word_count = sum(
        len(re.findall(r"\b[\w’'-]+\b", str(beat.get("text") or ""), flags=re.UNICODE))
        for beat in beats
    )
    timing_hint = _h3_dialogue_timing_hint(word_count, duration)
    speaker_ids: dict[str, str] = {}
    lines = [accent_direction]
    if timing_hint:
        lines.append(timing_hint)
    for beat in beats:
        character_id = str(beat.get("characterId") or beat.get("speaker") or "Speaker")
        speaker_ids.setdefault(character_id, f"S{len(speaker_ids) + 1}")
        speaker = character_names.get(character_id, str(beat.get("speaker") or character_id))
        emotion = " ".join(str(beat.get("emotion") or "natural").split())
        delivery = " ".join(str(beat.get("delivery") or "natural delivery").split())
        dialogue = str(beat.get("text") or "").strip()
        lines.append(
            f"{speaker} ({speaker_ids[character_id]}), {emotion}, {delivery}: "
            f"<d>[{language_tag}] {dialogue}</d>"
        )
    return " ".join(lines)


def series_dialogue_preflight_issues(shot: dict) -> list[str]:
    """Return deterministic issues that would make native H3 speech unreliable."""
    beats = [
        beat for beat in (
            shot.get("dialogueBeats", []) if isinstance(shot.get("dialogueBeats"), list) else []
        )
        if isinstance(beat, dict) and str(beat.get("text") or "").strip()
    ]
    issues: list[str] = []
    words = 0
    for beat in beats:
        dialogue = str(beat.get("text") or "").strip()
        if re.search(r"</?d(?:\s|>)", dialogue, flags=re.IGNORECASE):
            issues.append("dialogue contains the reserved <d> control tag")
        words += len(re.findall(r"\b[\w’'-]+\b", dialogue, flags=re.UNICODE))
    duration = normalize_series_shot_duration(shot.get("durationSeconds"))
    budget = duration * 2
    if words > budget:
        issues.append(
            f"dialogue has {words} words but a {duration}s H3 shot supports about {budget}"
        )
    return issues


def _h3_reference_sections(manifest: dict, character_names: dict[str, str]) -> tuple[str, str, str]:
    selected = manifest.get("selected") if isinstance(manifest.get("selected"), list) else []
    definitions = []
    retention = []
    picture_index = 0
    video_index = 0
    audio_index = 0
    for subject_index, item in enumerate((item for item in selected if isinstance(item, dict)), start=1):
        media_type = str(item.get("mediaType") or "image")
        if media_type == "video":
            paired_audio = ""
            if item.get("includeAudio") is True:
                audio_index += 1
                paired_audio = f" and its synchronized <Audio {audio_index}> soundtrack"
            video_index += 1
            source = f"<Video {video_index}>"
        elif media_type == "audio":
            audio_index += 1
            source = f"<Audio {audio_index}>"
        else:
            picture_index += 1
            source = f"<Picture {picture_index}>"
        entity_id = str(item.get("entityId") or "subject")
        entity = character_names.get(entity_id, entity_id)
        role = str(item.get("referenceRole") or "visual reference").replace("_", " ")
        definitions.append(
            f"<Subject {subject_index}> is the {role} for {entity}, sourced from {source}"
            f"{paired_audio if media_type == 'video' else ''}."
        )
        retention.append(
            f"<Subject {subject_index}> (appears in [Shot 1]): fully_preserved - preserve only "
            f"the supplied {role} traits while following the requested action."
        )
    return "\n".join(definitions), "\n".join(retention), "[reference generation] Create the requested shot using only the explicitly routed references."


def shot_generation_prompt(series: dict, shot: dict, manifest: dict | None = None) -> str:

    character_names = {
        str(item.get("id")): str(item.get("name") or item.get("id"))
        for item in series.get("characters", []) if isinstance(item, dict) and item.get("id")
    }
    manifest = manifest if isinstance(manifest, dict) else {}
    strategy = str(manifest.get("strategy") or "direct")
    scene = _h3_scene_description(series, shot)
    dialogue = _h3_dialogue_description(series, shot, character_names)
    ambience = " ".join(str(shot.get("audioDirection") or "").split()).strip()
    soundscape = (
        f"{ambience}. " if ambience else "Natural room tone and synchronized physical action sounds. "
    ).rstrip()

    alignment = ""
    duration = quantize_h3_frames(
        shot.get("durationSeconds"), reference_mode=False,
    ) / 24.0
    if strategy == "first_frame":
        alignment = (
            "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced.\n\n"
        )
    elif strategy == "first_last":
        alignment = (
            "For the target video, at 0.00 seconds into the target video, "
            "<Picture 1> (from [Shot 1]) is fully referenced. At "
            f"{duration:.2f} seconds, <Picture 2> is the fully referenced final frame of [Shot 1].\n\n"
        )

    if strategy == "references":
        definitions, retention, summary = _h3_reference_sections(manifest, character_names)
        if not dialogue:
            return (
                f"subject_definitions:\n{definitions}\n\n"
                f"summary:\n{summary}\n\n"
                f"retention_analysis:\n{retention}\n\n"
                f"detailed_description:\n[Shot 1] {scene}"
            )
        return (
            f"subject_definitions:\n{definitions}\n\n"
            f"summary:\n{summary}\n\n"
            f"retention_analysis:\n{retention}\n\n"
            f"detailed_description:\n[Shot 1] {scene} {dialogue}\n\n"
            f"overall_soundscape: {soundscape}\n\n"
            "non_diegetic_music: N/A"
        )
    visual = f"{alignment}integrated_multimodal_description: [Shot 1] {scene}"
    if not dialogue:
        return visual
    return (
        f"{visual} {dialogue}\n\n"
        f"overall_soundscape: {soundscape}\n\n"
        "non_diegetic_music: N/A"
    )


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
        intent = str(item.get("audioIntent") or "").strip().lower()
        result["audio_intent"] = intent if intent in {"voice", "drive", "style"} else (
            "voice" if item.get("entityType") == "character" else "style"
        )
    elif media_type == "video":
        result["video_intent"] = "motion"
        result["include_audio"] = item.get("includeAudio") is True
        if result["include_audio"]:
            result["has_audio"] = True
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
        "prompt": str(attempt.get("prompt") or shot_generation_prompt(series, shot, manifest)),
        "negative_prompt": str(attempt.get("negativePrompt") or ""),
        "image_mode": 0,
        "image_prompt_type": "",
        "num_inference_steps": max(1, min(50, int(settings.get("numInferenceSteps") or 20))),
        "guidance_scale": float(settings.get("guidanceScale") or 1),
        "resolution": resolution,
        "video_length": min(
            int(settings.get("videoLengthFrames")),
            quantize_h3_frames(15, reference_mode=strategy == "references"),
        ) if settings.get("videoLengthFrames") is not None else quantize_h3_frames(
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
