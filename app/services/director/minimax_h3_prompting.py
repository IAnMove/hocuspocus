"""MiniMax H3 prompt dialect adapter used by every Director workflow.

Director planners deliberately produce model-neutral shot plans.  This module
is the single boundary where those plans become the structured FL2VA/Ref2VA
prompts documented by the MiniMax H3 team.  Keeping the adapter deterministic
means music videos, short films, quick videos and comic movies all speak the
same dialect even when an LLM prompt-polish pass is disabled.
"""

from __future__ import annotations

import re
from typing import Any

from .spoken_language import spoken_language_of
from ..h3_prompt_finalization import finalize_h3_prompt
from ..h3_prompt_policy import audio_policy, h3_field_labels, tagged_dialogue


FIRST_FRAME_REFERENCE = (
    "For the target video, at 0.00 seconds into the target video, <Picture 1> "
    "(from [Shot 1]) is fully referenced."
)


def normalize_reference_mode(value: str | None) -> str:
    mode = str(value or "first_frame").strip().lower()
    mode = {
        "fl2va": "first_frame",
        "text": "direct",
        "text_to_video": "direct",
        "t2v": "direct",
        "ref2va": "references",
        "reference": "references",
    }.get(mode, mode)
    return mode if mode in {"direct", "first_frame", "references"} else "first_frame"


def is_structured_h3_prompt(prompt: str, reference_mode: str | None = None) -> bool:
    text = str(prompt or "")
    mode = normalize_reference_mode(reference_mode)
    fields = h3_field_labels("references" if mode == "references" else "context")
    if mode == "first_frame" and FIRST_FRAME_REFERENCE not in text:
        return False
    if mode == "direct" and FIRST_FRAME_REFERENCE in text:
        return False
    return all(field in text for field in fields)


def _clean(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _items(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value in (None, ""):
        return []
    return [value]


def _strip_legacy_contracts(prompt: str) -> str:
    """Remove Maestro's old wrappers while preserving the authored action."""
    raw = str(prompt or "").strip()
    if "integrated_multimodal_description:" in raw:
        raw = raw.split("integrated_multimodal_description:", 1)[1]
        raw = raw.split("overall_soundscape:", 1)[0]
    elif "detailed_description:" in raw:
        raw = raw.split("detailed_description:", 1)[1]
        raw = raw.split("overall_soundscape:", 1)[0]
    text = _clean(raw)
    text = re.sub(
        r"^the referenced picture is the exact opening frame\.[^.]*authoritative[^.]*\.\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^use the supplied images? as (?:the exact first frame|visual references[^.]*\.)\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^the visible wardrobe and environment in that first frame are authoritative;[^.]*\.\s*",
        "",
        text,
        flags=re.I,
    )
    # Audio is represented by the official soundscape fields below.
    text = re.sub(r"\s*\bAudio\s*:.*$", "", text, flags=re.I | re.S).strip()
    return text


def _subject_definitions(plan: dict) -> tuple[list[str], list[str]]:
    definitions: list[str] = []
    subject_ids: list[str] = []
    for index, raw in enumerate(_items(plan.get("subjects_on_screen")), start=1):
        subject = raw if isinstance(raw, dict) else {"visual_description": raw}
        description = _clean(
            subject.get("visual_description")
            or subject.get("description")
            or subject.get("speaker_name")
            or subject.get("character_id")
        )
        if not description:
            continue
        subject_id = f"S{index}"
        relation = _clean(subject.get("position_or_relation"))
        if relation:
            description = f"{description}; positioned {relation}"
        definitions.append(f"({subject_id}) {description}")
        subject_ids.append(subject_id)
    return definitions, subject_ids


def _camera_sentence(plan: dict) -> str:
    camera = plan.get("camera_plan") if isinstance(plan.get("camera_plan"), dict) else {}
    framing = _clean(camera.get("framing"))
    angle = _clean(camera.get("angle"))
    movement = _clean(camera.get("movement"))
    intensity = _clean(camera.get("movement_intensity"))
    lens = _clean(camera.get("lens_feel"))
    parts: list[str] = []
    if framing:
        parts.append(f"The shot holds a {framing}")
    if angle:
        parts.append(f"from a {angle} angle")
    if movement and movement.lower() not in {"none", "static"}:
        qualifier = f"{intensity} " if intensity and intensity != "static" else ""
        parts.append(f"with one coherent {qualifier}{movement} camera move")
    elif movement or intensity == "static":
        parts.append("with a locked-off camera")
    if lens:
        parts.append(f"and a {lens} lens feel")
    if not parts:
        return "The camera uses one continuous, physically coherent take."
    return ", ".join(parts).rstrip(".") + "."


def _dialogue_sentences(plan: dict, subject_ids: list[str]) -> list[str]:
    sentences: list[str] = []
    for index, raw in enumerate(_items(plan.get("dialogue_beats"))):
        if not isinstance(raw, dict):
            continue
        spoken = _clean(raw.get("spoken_text") or raw.get("text"))
        if not spoken:
            continue
        speaker = _clean(raw.get("speaker_name") or raw.get("speaker_id"))
        speaker_id = subject_ids[min(index, len(subject_ids) - 1)] if subject_ids else "S1"
        cue = f"({speaker_id})"
        if speaker:
            cue += f" {speaker}"
        cue += f" says {tagged_dialogue(spoken_language_of(spoken), spoken)}"
        sentences.append(cue + ".")
    return sentences


def _integrated_description(plan: dict, prompt: str) -> str:
    try:
        from .policies import strip_visible_text_directions
    except ImportError:  # pragma: no cover - compatibility import path
        from services.director.policies import strip_visible_text_directions

    no_visible_text = "no visible text lock:" in str(prompt or "").casefold()
    clean_visual_field = (
        strip_visible_text_directions if no_visible_text else lambda value: str(value or "")
    )
    definitions, subject_ids = _subject_definitions(plan)
    action = _strip_legacy_contracts(prompt)
    action_beats = [_clean(item) for item in _items(plan.get("action_beats")) if _clean(item)]
    if (not action or len(action) > 700) and action_beats:
        action = " Then ".join(action_beats)
    if not action:
        action = _clean(plan.get("scene_goal")) or "The staged action unfolds naturally."

    parts: list[str] = []
    if definitions:
        parts.append("Visible subjects: " + "; ".join(definitions) + ".")
    environment = _clean(clean_visual_field(plan.get("environment") or plan.get("spatial_setup")))
    if environment:
        parts.append(f"Environment: {environment}.")
    style = _clean(clean_visual_field(plan.get("visual_style")))
    lighting = _clean(clean_visual_field(plan.get("lighting")))
    if style:
        parts.append(f"Visual treatment: {style}.")
    if lighting:
        parts.append(f"Lighting: {lighting}.")
    parts.append("Chronological action: " + action.rstrip(".") + ".")
    parts.extend(_dialogue_sentences(plan, subject_ids))
    parts.append(_camera_sentence(plan))
    ending = _clean(clean_visual_field(plan.get("ending_beat")))
    if ending and ending.casefold() not in action.casefold():
        parts.append(f"The shot ends on {ending.rstrip('.')}.")
    parts.append("Same faces and wardrobe throughout.")
    return " ".join(parts)


def _sound_fields(plan: dict, audio_direction: str) -> tuple[str, str]:
    audio = plan.get("audio_plan") if isinstance(plan.get("audio_plan"), dict) else {}
    ambience = _clean(audio.get("ambience"))
    effects = [_clean(item) for item in _items(audio.get("effects")) if _clean(item)]
    soundscape_parts: list[str] = []
    if ambience:
        soundscape_parts.append(ambience)
    if effects:
        soundscape_parts.append("Synchronized effects: " + ", ".join(effects))
    # Dialogue, language, delivery and lip sync belong beside the exact <d>
    # block in integrated_multimodal_description. Keeping a generic voice cue
    # in the full-clip soundscape can make H3 extend a short line with invented
    # speech before or after the authored words.
    direction = _clean(audio_direction)
    # The global UI audio preference can contain meta instructions such as
    # "include dialogue or music" or "only explicitly described sounds".
    # Those are not diegetic ambience and H3 treats them as audible events.
    if (
        direction
        and not re.search(
            r"\b(?:dialogue|voice|voices|speech|vocal|lyrics?|singing|music|song|"
            r"explicitly described|remain silent)\b",
            direction,
            flags=re.I,
        )
    ):
        soundscape_parts.append(direction)
    # Temporary: never describe ambience, effects, silence, or music. H3
    # treats those sentences as audible events. Dialogue lives only in <d>.
    return ". ".join(soundscape_parts) or "N/A", _clean(audio.get("music")) or "N/A"


def format_minimax_h3_prompt(
    plan: dict | None,
    prompt: str,
    *,
    reference_mode: str = "first_frame",
    audio_direction: str = "",
    h3_audio_policy: str = "native",
    duration_seconds: float = 0,
) -> str:
    """Format one final segment prompt for FL2VA or Ref2VA.

    Already-structured prompts are kept intact.  This lets users edit the
    visible final prompt without a later generation step silently rewriting it.
    """
    mode = normalize_reference_mode(reference_mode)
    text = str(prompt or "").strip()
    if is_structured_h3_prompt(text, mode):
        return finalize_h3_prompt(
            text, policy=h3_audio_policy, duration_seconds=duration_seconds,
        )

    shot = dict(plan or {})
    description = _integrated_description(shot, text)
    soundscape, music = _sound_fields(shot, audio_direction)

    if mode == "references":
        definitions, _ = _subject_definitions(shot)
        defined = "; ".join(definitions) if definitions else (
            "(S1) the principal subject from the supplied references; "
            "(E1) the referenced environment and its stable visual design"
        )
        compiled = "\n".join((
            f"subject_definitions: {defined}",
            "summary: [reference generation] Compose one new continuous shot from the supplied references.",
            (
                "retention_analysis: Preserve each referenced subject's identity, proportions, wardrobe, "
                "materials and distinguishing features; preserve the referenced location's architecture, "
                "palette and spatial logic. Do not copy an arbitrary reference frame as the opening frame."
            ),
            f"detailed_description: {description}",
            f"overall_soundscape: {soundscape}.",
            f"non_diegetic_music: {music}",
        ))
        return finalize_h3_prompt(
            compiled, policy=h3_audio_policy, duration_seconds=duration_seconds,
        )

    integrated = (
        description
        if mode == "direct"
        else (
            "The referenced picture is the exact opening frame. Its visible composition, "
            "identity, wardrobe, environment, colors and proportions are authoritative and "
            f"must not be stretched or redesigned. {description}"
        )
    )
    fields = (
        f"integrated_multimodal_description: {integrated}",
        f"overall_soundscape: {soundscape}.",
        f"non_diegetic_music: {music}",
    )
    compiled = "\n".join(fields) if mode == "direct" else "\n".join((
        FIRST_FRAME_REFERENCE,
        *fields,
    ))
    return finalize_h3_prompt(
        compiled, policy=h3_audio_policy, duration_seconds=duration_seconds,
    )


def h3_audio_policy_from_payload(payload: dict | None) -> str:
    """Read the effective audio policy; omitted or invalid values stay native."""
    data = payload or {}
    raw = data.get("h3_audio_policy")
    if raw in (None, ""):
        raw = data.get("minimax_h3_audio_policy")
    if raw in (None, ""):
        return "native"
    try:
        return audio_policy(raw)
    except ValueError:
        return "native"


def _format_adapted_prompt(
    shot: dict,
    text: str,
    *,
    reference_mode: str,
    audio_direction: str,
    h3_audio_policy: str,
    duration_seconds: float,
) -> str:
    return format_minimax_h3_prompt(
        shot,
        text,
        reference_mode=reference_mode,
        audio_direction=audio_direction,
        h3_audio_policy=h3_audio_policy,
        duration_seconds=duration_seconds,
    )


def _record_h3_prompt_trace(clip: dict, source: str, final: str, policy: str) -> None:
    """Keep plan vs send on existing Director provenance fields."""
    if not clip.get("_director_h3_source_prompt"):
        clip["_director_h3_source_prompt"] = source
    clip["_director_h3_compiled_prompt"] = final
    audio_plan = dict(clip.get("_director_audio_plan") or {})
    audio_plan["h3_audio_policy"] = policy
    clip["_director_audio_plan"] = audio_plan


def adapt_clip_plans_for_h3(
    clip_plans: list[dict],
    shots: list[dict] | None = None,
    *,
    reference_mode: str = "first_frame",
    audio_direction: str = "",
    h3_audio_policy: str = "native",
    duration_seconds: float = 0,
) -> list[dict]:
    """Adapt all rendered Director plans without changing image prompts."""
    shots = shots or []
    policy = h3_audio_policy_from_payload({"h3_audio_policy": h3_audio_policy})
    for index, clip in enumerate(clip_plans):
        shot = shots[index] if index < len(shots) and isinstance(shots[index], dict) else clip
        source = str(clip.get("video_prompt") or "")
        final = _format_adapted_prompt(
            shot,
            source,
            reference_mode=reference_mode,
            audio_direction=audio_direction,
            h3_audio_policy=policy,
            duration_seconds=duration_seconds,
        )
        clip["video_prompt"] = final
        _record_h3_prompt_trace(clip, source, final, policy)
        windows = clip.get("window_prompts")
        if isinstance(windows, list):
            adapted: list[Any] = []
            for window in windows:
                if isinstance(window, dict):
                    updated = dict(window)
                    key = "prompt" if "prompt" in updated else "text"
                    updated[key] = _format_adapted_prompt(
                        shot,
                        str(updated.get(key) or ""),
                        reference_mode=reference_mode,
                        audio_direction=audio_direction,
                        h3_audio_policy=policy,
                        duration_seconds=duration_seconds,
                    )
                    adapted.append(updated)
                else:
                    adapted.append(_format_adapted_prompt(
                        shot,
                        str(window),
                        reference_mode=reference_mode,
                        audio_direction=audio_direction,
                        h3_audio_policy=policy,
                        duration_seconds=duration_seconds,
                    ))
            clip["window_prompts"] = adapted
    return clip_plans
