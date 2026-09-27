"""Immutable H3 story-video prompt contracts (reference, identity, portrait, audio).

These strings are the Director/H3 authority for first-frame vs references,
recurring faces, tall-canvas composition and authored audio. The pipeline
re-exports the same names.
"""
from __future__ import annotations

import json
import re


def _h3_apply_reference_contract(prompt: str, reference_mode: str) -> str:
    text = str(prompt or "").strip()
    exact = "Use the supplied image as the exact first frame."
    exact_pattern = r"use the supplied images? as the exact first frame\."
    if reference_mode == "references":
        replacement = (
            "Use the supplied images as visual references for identity, wardrobe, "
            "environment and style. Compose a new opening frame from that reference set."
        )
        text, replacements = re.subn(exact_pattern, replacement, text, flags=re.I)
        if not replacements and "compose a new opening frame" not in text.casefold():
            text = f"{replacement} {text}".strip()
        return text
    authority = (
        "The visible wardrobe and environment in that first frame are authoritative; "
        "ignore later wording that conflicts with their colors or design."
    )
    if "visible wardrobe and environment" not in text.casefold():
        remainder = re.sub(exact_pattern, "", text, flags=re.I).strip()
        text = f"{exact} {authority} {remainder}".strip()
    return text


def _h3_apply_identity_contract(prompt: str) -> str:
    """Keep recurring faces stable when H3 has to reveal them after occlusion."""
    text = str(prompt or "").strip()
    marker = "Same faces and wardrobe throughout"
    if marker.casefold() in text.casefold():
        return text
    identity = "Same faces and wardrobe throughout."
    parts = re.split(r"\bAudio\s*:", text, maxsplit=1, flags=re.I)
    if len(parts) == 2:
        return f"{parts[0].strip()} {identity}\nAudio: {parts[1].strip()}".strip()
    return f"{text} {identity}".strip()


def _h3_apply_portrait_composition_contract(prompt: str, resolution: str) -> str:
    """Tell H3 to compose for the actual tall canvas instead of letterboxing."""
    text = str(prompt or "").strip()
    try:
        width, height = (
            int(value) for value in str(resolution or "").lower().split("x", 1)
        )
    except (TypeError, ValueError):
        return text
    marker = "PORTRAIT COMPOSITION LOCK:"
    if height <= width or marker.casefold() in text.casefold():
        return text
    contract = (
        f"{marker} Compose natively for the full {width}x{height} vertical portrait "
        "canvas. Stage subjects and camera movement for the tall frame; never place "
        "a horizontal landscape frame, letterbox bars, rotated image, or sideways "
        "composition inside it."
    )
    parts = re.split(
        r"(?im)^\s*overall_soundscape\s*:", text, maxsplit=1,
    )
    if len(parts) == 2:
        return (
            f"{parts[0].rstrip()} {contract}\n\n"
            f"overall_soundscape: {parts[1].lstrip()}"
        )
    return f"{text} {contract}".strip()


def _h3_format_audio_policy(*sources) -> str:
    for source in sources:
        if not isinstance(source, dict):
            continue
        value = source.get("h3_audio_policy") or source.get("minimax_h3_audio_policy")
        if value:
            return str(value)
    return "native"


def _h3_parse_optimized_prompts(response: str) -> list[dict]:
    """Parse the grammar-constrained H3 validator response defensively."""
    text = re.sub(r"```(?:json)?\s*|```", "", str(response or ""), flags=re.I).strip()
    try:
        parsed = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        match = re.search(r"\[[\s\S]*\]", text)
        if not match:
            return []
        try:
            parsed = json.loads(match.group(0))
        except json.JSONDecodeError:
            return []
    if isinstance(parsed, dict):
        parsed = parsed.get("segments") or []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def _h3_validated_candidate(candidate: str, draft: str, reference_mode: str) -> str:
    """Reject optimizer drift and reapply contracts the LLM is not allowed to alter."""
    candidate = _h3_preserve_audio_contract(str(candidate or ""), draft)
    if "overall_soundscape:" not in draft:
        candidate = _h3_apply_reference_contract(candidate, reference_mode)
        if len(candidate) < max(40, len(draft) // 3) or len(candidate) > max(6000, len(draft) * 2):
            return ""
        if "audio:" not in candidate.casefold():
            return ""
        for quoted in re.findall(r'"([^"\n]+)"', draft):
            if quoted not in candidate:
                return ""
        if reference_mode == "references" and "exact first frame" in candidate.casefold():
            return ""
        if reference_mode == "first_frame" and "exact first frame" not in candidate.casefold():
            return ""
        return candidate
    if len(candidate) < max(40, len(draft) // 3) or len(candidate) > max(6000, len(draft) * 2):
        return ""
    try:
        from services.director.minimax_h3_prompting import is_structured_h3_prompt
    except ImportError:
        from app.services.director.minimax_h3_prompting import is_structured_h3_prompt
    if not is_structured_h3_prompt(candidate, reference_mode):
        return ""
    if "visual style lock:" in draft.casefold() and "visual style lock:" not in candidate.casefold():
        return ""
    for spoken in re.findall(r"<d>\[[^\]]+\]\s*([^<]+)</d>", draft):
        if spoken not in candidate:
            return ""
    if reference_mode == "references" and "fully referenced" in candidate.casefold():
        return ""
    if reference_mode == "first_frame" and "at 0.00 seconds" not in candidate.casefold():
        return ""
    return candidate


def _h3_preserve_audio_contract(candidate: str, draft: str) -> str:
    """Accept visual phrasing from the validator while keeping authored audio verbatim."""
    if "overall_soundscape:" in draft and "non_diegetic_music:" in draft:
        draft_audio = draft.split("overall_soundscape:", 1)[1]
        candidate_visual = candidate.split("overall_soundscape:", 1)[0].rstrip()
        return f"{candidate_visual}\noverall_soundscape:{draft_audio}".strip()
    draft_parts = re.split(r"\bAudio\s*:", draft, maxsplit=1, flags=re.I)
    if len(draft_parts) != 2:
        return candidate.strip()
    visual = re.split(r"\bAudio\s*:", candidate, maxsplit=1, flags=re.I)[0].strip()
    return f"{visual}\nAudio: {draft_parts[1].strip()}".strip()
