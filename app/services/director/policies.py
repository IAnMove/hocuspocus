"""
Shared Prompt Policies — centralized rules enforced across all skills and render modes.

Instead of duplicating long rule prose in every system prompt, policies are defined
here as structured data + helper functions that renderers and validators consume.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Optional

from .schema import ShotPlan, ProductionPlan, CharacterProfile


# ── Policy Configuration ─────────────────────────────────────────────

@dataclass
class PromptPolicy:
    """Toggleable policy flags — renderers and validators check these."""
    no_character_names_outside_dialogue: bool = True
    dialogue_in_quotes: bool = True
    chronological_action: bool = True
    single_paragraph: bool = True
    present_tense: bool = True
    no_montage_language: bool = True
    physical_emotion_only: bool = True
    explicit_camera_language: bool = True
    re_describe_characters_every_shot: bool = True
    no_meta_language_in_image_prompts: bool = True
    no_action_in_image_prompts: bool = True


# Default policy — all rules enabled
DEFAULT_POLICY = PromptPolicy()


# ── Anti-Pattern Definitions ─────────────────────────────────────────

# Words/phrases that should never appear in single-shot video prompts
MONTAGE_LANGUAGE = [
    "montage", "quick cuts", "cut to", "series of shots",
    "rapid cuts", "jump cut", "intercut", "cross-cut",
    "smash cut", "match cut", "dissolve to", "fade to",
    "transition to", "we see", "next we see",
]

# Meta-language that shouldn't appear in image prompts
IMAGE_META_LANGUAGE = [
    "preserve", "maintain", "keep unchanged", "keep the same",
    "don't change", "same as before", "as in the reference",
    "remain", "stays the same", "unaltered",
]

# Abstract emotion labels — prefer physical cues instead
ABSTRACT_EMOTIONS = [
    "feeling happy", "feeling sad", "feeling angry",
    "shows emotion", "emotional moment", "with emotion",
    "conveys sadness", "expresses joy",
]

# Vague camera language — prefer explicit terms
VAGUE_CAMERA = [
    "cinematic camera", "dramatic camera", "interesting angle",
    "cool shot", "nice framing", "creative camera",
    "camera does something", "dynamic camera work",
]

# Action verbs that don't belong in static image prompts
IMAGE_ACTION_VERBS = [
    "walks", "runs", "dances", "jumps", "turns",
    "raises hand", "waves", "throws", "catches",
    "speaks", "says", "whispers", "shouts",
    "moves toward", "steps", "reaches",
]


# ── Character Description Helpers ────────────────────────────────────

def describe_character(char: CharacterProfile, include_wardrobe: bool = True) -> str:
    """Build a visual description string for a character (no names)."""
    parts = [char.physical_description]
    if include_wardrobe and char.wardrobe:
        parts.append(char.wardrobe)
    return ", ".join(parts)


def resolve_subjects_text(shot: ShotPlan, plan: Optional[ProductionPlan] = None) -> str:
    """Build a text description of all subjects on screen for prompt injection."""
    if not shot.subjects_on_screen:
        return ""
    parts = []
    for subj in shot.subjects_on_screen:
        desc = subj.visual_description
        if subj.character_id and plan:
            char = plan.get_character(subj.character_id)
            if char:
                desc = describe_character(char)
        if subj.position_or_relation:
            desc += f", {subj.position_or_relation}"
        parts.append(desc)
    if len(parts) == 1:
        return parts[0]
    return " and ".join([", ".join(parts[:-1]), parts[-1]]) if len(parts) > 2 else " and ".join(parts)


# ── Dialogue Formatting ──────────────────────────────────────────────

def format_dialogue_for_video(shot: ShotPlan, plan: Optional[ProductionPlan] = None) -> str:
    """Format dialogue beats into prose suitable for video prompts.

    Returns text like: 'The woman in red says "Hello there" with a warm smile,
    then the man in the suit replies "Welcome back" while nodding.'
    """
    if not shot.dialogue_beats:
        return ""

    lines = []
    for beat in shot.dialogue_beats:
        # Build speaker description
        speaker_desc = "a person"
        if beat.speaker_id and plan:
            char = plan.get_character(beat.speaker_id)
            if char:
                speaker_desc = describe_character(char, include_wardrobe=False)

        # Build the line
        parts = [f'{speaker_desc} says "{beat.spoken_text}"']
        if beat.delivery:
            parts.append(f"{beat.delivery}")
        if beat.physical_cue:
            parts.append(f"{beat.physical_cue}")
        lines.append(", ".join(parts))

    return ". ".join(lines)


def format_dialogue_metadata(shot: ShotPlan) -> list[str]:
    """Format dialogue as metadata strings for clip plan output."""
    if not shot.dialogue_beats:
        return []
    return [
        f"{beat.speaker_id or 'unknown'}: \"{beat.spoken_text}\""
        for beat in shot.dialogue_beats
    ]


# ── Camera Description ───────────────────────────────────────────────

def format_camera_text(cam: "CameraPlan") -> str:
    """Build a natural camera description from CameraPlan fields."""
    parts = []

    # Framing first
    parts.append(cam.framing)

    # Angle
    if cam.angle:
        parts.append(cam.angle)

    # Movement
    if cam.movement:
        intensity_prefix = {
            "static": "steady",
            "subtle": "gentle",
            "moderate": "",
            "dynamic": "energetic",
        }.get(cam.movement_intensity, "")
        if intensity_prefix:
            parts.append(f"{intensity_prefix} {cam.movement}")
        else:
            parts.append(cam.movement)

    # Lens feel
    if cam.lens_feel:
        parts.append(cam.lens_feel)

    return ", ".join(parts)


# ── Action Beat Assembly ─────────────────────────────────────────────

def format_action_sequence(shot: ShotPlan) -> str:
    """Assemble action beats into chronological prose."""
    beats = list(shot.action_beats)
    if shot.performance_beats:
        beats.extend(shot.performance_beats)
    if not beats:
        return ""
    return ". ".join(beats)


# ── Environment & Style Block ────────────────────────────────────────

def format_scene_setting(shot: ShotPlan) -> str:
    """Build environment + lighting + mood + style text."""
    parts = []
    if shot.environment:
        parts.append(shot.environment)
    if shot.lighting:
        parts.append(shot.lighting)
    if shot.mood:
        parts.append(f"{shot.mood} atmosphere")
    if shot.visual_style:
        parts.append(shot.visual_style)
    return ", ".join(parts)


# ── Detection Helpers (used by validators) ───────────────────────────

def detect_anti_patterns(text: str, mode: str) -> list[str]:
    """Scan prompt text for policy violations. Returns list of warnings."""
    warnings = []
    text_lower = text.lower()

    # Check montage language (all video modes)
    if mode in ("t2v", "i2v", "a2v", "retake", "extend"):
        for phrase in MONTAGE_LANGUAGE:
            if phrase in text_lower:
                warnings.append(f"Montage language detected: '{phrase}' — single-shot prompts cannot use this")

    # Check image-specific anti-patterns
    if mode == "image_gen":
        for phrase in IMAGE_META_LANGUAGE:
            if phrase in text_lower:
                warnings.append(f"Meta-language in image prompt: '{phrase}' — use action verbs instead")
        for verb in IMAGE_ACTION_VERBS:
            if verb in text_lower:
                warnings.append(f"Action verb in image prompt: '{verb}' — image prompts describe static frames only")

    # Check vague camera language (all modes)
    for phrase in VAGUE_CAMERA:
        if phrase in text_lower:
            warnings.append(f"Vague camera language: '{phrase}' — use explicit camera terms")

    # Check abstract emotions
    for phrase in ABSTRACT_EMOTIONS:
        if phrase in text_lower:
            warnings.append(f"Abstract emotion: '{phrase}' — use visible physical cues instead")

    return warnings


def detect_character_names_in_prompt(text: str, characters: Optional[list[CharacterProfile]] = None) -> list[str]:
    """Check if character names appear outside of quoted dialogue."""
    if not characters:
        return []

    warnings = []
    # Remove quoted dialogue before checking
    text_without_dialogue = re.sub(r'"[^"]*"', '', text)
    text_without_dialogue = re.sub(r"'[^']*'", '', text_without_dialogue)

    for char in characters:
        if char.display_name and len(char.display_name) > 2:
            if char.display_name.lower() in text_without_dialogue.lower():
                warnings.append(
                    f"Character name '{char.display_name}' used outside dialogue — "
                    f"describe by appearance instead"
                )
    return warnings


# ── Prompt Compression Helpers ───────────────────────────────────────

_REDUNDANT_ADJECTIVE_PATTERNS = [
    (r'\b(very|really|extremely|incredibly|absolutely)\s+', ''),  # intensity modifiers
    (r'\b(beautiful|gorgeous|stunning)\s+(beautiful|gorgeous|stunning)\b', r'\1'),  # doubled
]

_FILLER_PHRASES = [
    "in this scene", "we can see", "the scene shows",
    "the viewer sees", "it appears that", "there is a",
    "we are shown", "the shot reveals", "it is clear that",
]


def compress_prompt_text(text: str) -> tuple[str, int]:
    """Remove redundancy and filler from prompt text.

    Returns (compressed_text, chars_removed).
    """
    original_len = len(text)
    result = text

    # Remove filler phrases
    for filler in _FILLER_PHRASES:
        result = re.sub(re.escape(filler), '', result, flags=re.IGNORECASE)

    # Remove redundant adjective patterns
    for pattern, replacement in _REDUNDANT_ADJECTIVE_PATTERNS:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

    # Collapse multiple spaces
    result = re.sub(r'  +', ' ', result).strip()

    # Collapse multiple commas/periods
    result = re.sub(r',\s*,', ',', result)
    result = re.sub(r'\.\s*\.', '.', result)

    return result, original_len - len(result)


# ── System Prompt Builders (compact rule blocks for LLM) ─────────────

def build_character_rules_block(has_reference: bool, characters: Optional[list[CharacterProfile]] = None) -> str:
    """Build the character-related rules block for LLM system prompts."""
    from .guide_loader import load_guide
    base = load_guide("character_identification_rules.md")
    if not base:
        base = "CHARACTER RULES:\n- Describe characters by appearance, not names."

    lines = [base]
    if has_reference:
        # IMPORTANT: this rule split is the fix for the "user uploads
        # selfie tagged 'man in black', screenplay turns him into a
        # knight, future shot prompts keep saying 'man in black' and
        # the image generator never renders armor" bug. The reference
        # image supplies IDENTITY (face, body type, gender). The
        # CURRENT shot's costume/role/state comes from the screenplay.
        # Telling the LLM to "base descriptions on the reference image"
        # without this distinction made it freeze the user's reference
        # outfit into every downstream prompt.
        lines.append(
            "- The visual reference supplies IDENTITY (face, build, gender, "
            "approximate age). It does NOT freeze the character's costume "
            "or role for the rest of the story."
        )
        lines.append(
            "- Describe each character's APPEARANCE in each shot based on "
            "what the SCREENPLAY says they look like in that scene — costume, "
            "armor, props, state (wet hair, torn clothing, etc.). The "
            "screenplay overrides the visual reference's costume."
        )
        lines.append(
            "- Example: reference image shows 'man in black t-shirt'. "
            "Screenplay says character is a knight. Shot descriptions: "
            "'tall man in gleaming silver plate armor' (NOT 'man in black')."
        )
    if characters:
        lines.append("- Character reference (use ONLY the visual descriptions below, never names):")
        for c in characters:
            desc = describe_character(c)
            # Do NOT include display_name — LLMs parrot names into prompts despite instructions
            lines.append(f"  * {c.id}: {desc}")
        lines.append(
            "- The descriptions above are VISUAL-REFERENCE descriptions. "
            "If the screenplay transforms a character (e.g. into a knight, "
            "wizard, vampire, queen), describe them as transformed in shot "
            "prompts. The reference image is for IDENTITY and visual-medium continuity."
        )
    return "\n".join(lines)


def build_video_rules_block() -> str:
    """Build the video prompt rules block for LLM system prompts."""
    from .guide_loader import load_guide
    return load_guide("video_prompt_rules.md") or "VIDEO PROMPT RULES:\n- One flowing paragraph, present tense."


def build_camera_style_block() -> str:
    """Build the adaptive camera style guidance."""
    from .guide_loader import load_guide
    return load_guide("camera_style_guidance.md") or "CAMERA STYLE:\n- Match complexity to content."


# ── Story visual-style continuity ─────────────────────────────────────

_ILLUSTRATED_STYLE_TERMS = (
    "anime", "manga", "comic", "illustrat", "cel shad", "cell shad",
    "2d", "line art", "inked", "graphic novel", "watercolor",
    "watercolour", "gouache", "painted", "cartoon", "moebius",
    "cómic", "ilustración", "acuarela", "dibujo", "animación",
)


def compact_visual_style(visual_style: str, max_chars: int = 360) -> str:
    """Normalize a Story visual bible into a prompt-sized style statement.

    Story world prompts can be intentionally rich, while some image providers
    reject prompts above a small hard limit.  Keep the canonical statement
    useful but bounded before it is repeated across every generated shot.
    """
    style = re.sub(r"\s+", " ", str(visual_style or "")).strip(" .;,")
    if len(style) <= max_chars:
        return style
    shortened = style[:max_chars].rsplit(" ", 1)[0].rstrip(" .;,")
    return shortened or style[:max_chars]


def is_illustrated_visual_style(visual_style: str) -> bool:
    """Return whether the authored style clearly describes non-live-action art."""
    lowered = compact_visual_style(visual_style).casefold()
    return any(term in lowered for term in _ILLUSTRATED_STYLE_TERMS)


def build_visual_style_contract(
    visual_style: str,
    *,
    preserve: bool = True,
    has_reference: bool = False,
) -> str:
    """Build the planner-facing, non-optional Story style contract."""
    style = compact_visual_style(visual_style)
    if not preserve or not style:
        return ""
    lines = [
        "VISUAL STYLE CONTRACT — STRICT:",
        f"- Canonical medium and rendering: {style}.",
        "- This contract is the source of truth for this adaptation and "
        "overrides any conflicting generic style wording in the story concept.",
        "- Apply this same medium, linework, palette, shading, character "
        "proportions and design language to every start frame, keyframe and "
        "video prompt.",
        "- Camera language, lighting, location and costume may change; the "
        "authored visual medium may not.",
    ]
    if has_reference:
        lines.append(
            "- Approved Story reference images are authoritative for both "
            "identity AND visual medium; do not reinterpret them in another medium."
        )
    if is_illustrated_visual_style(style):
        lines.append(
            "- This is illustrated artwork. Never recast it as live action, "
            "photorealistic people or skin, or 3D CGI."
        )
    return "\n".join(lines)


def apply_visual_style_lock(
    prompt: str,
    visual_style: str,
    *,
    mode: str,
    preserve: bool = True,
    has_reference: bool = False,
) -> str:
    """Deterministically anchor a final image/video prompt to Story style.

    This runs after LLM planning (and again after optional prompt polish), so
    providers cannot silently replace anime/comic artwork with live action.
    The marker makes the operation idempotent across resume/retry paths.
    """
    text = str(prompt or "").strip()
    style = compact_visual_style(visual_style)
    if not preserve or not style or "visual style lock:" in text.casefold():
        return text

    medium = (
        f"VISUAL STYLE LOCK: {style}. Match this authored medium, linework, "
        "palette, shading, proportions and character design"
    )
    if has_reference:
        medium += " and the approved Story reference artwork"
    medium += " exactly throughout."
    if is_illustrated_visual_style(style):
        medium += (
            " Illustrated rendering only; no live action, photorealistic "
            "people or skin, and no 3D CGI."
        )
    if mode in {"video", "i2v", "a2v", "t2v", "extend", "retake"}:
        medium += " Animate the artwork without changing its visual medium."
    combined = f"{medium} {text}".strip()
    # MiniMax Image currently rejects prompts at 1500 characters.  Story
    # prompts can be verbose, so reserve a small transport margin while
    # keeping the style lock at the front (the most important instruction).
    if mode in {"image", "image_gen", "keyframe"} and len(combined) > 1450:
        remaining = max(0, 1449 - len(medium))
        shortened = text[:remaining].rsplit(" ", 1)[0].rstrip(" .;,")
        combined = f"{medium} {shortened}".strip()
    return combined


def enforce_visual_style_on_clip_plans(
    clip_plans: list[dict],
    visual_style: str,
    *,
    preserve: bool = True,
    has_reference: bool = False,
) -> list[dict]:
    """Apply the final style lock to all still and moving prompt fields."""
    if not preserve or not compact_visual_style(visual_style):
        return clip_plans
    for plan in clip_plans or []:
        if not isinstance(plan, dict):
            continue
        if str(plan.get("image_prompt") or "").strip():
            plan["image_prompt"] = apply_visual_style_lock(
                plan["image_prompt"],
                visual_style,
                mode="image",
                preserve=preserve,
                has_reference=has_reference,
            )
        if str(plan.get("video_prompt") or "").strip():
            plan["video_prompt"] = apply_visual_style_lock(
                plan["video_prompt"],
                visual_style,
                mode="video",
                preserve=preserve,
                has_reference=has_reference,
            )
        for field, mode in (
            ("window_prompts", "video"),
            ("keyframe_prompts", "image"),
        ):
            values = plan.get(field)
            if not isinstance(values, list):
                continue
            plan[field] = [
                apply_visual_style_lock(
                    value.get("prompt", value.get("text", ""))
                    if isinstance(value, dict) else value,
                    visual_style,
                    mode=mode,
                    preserve=preserve,
                    has_reference=has_reference,
                )
                for value in values
            ]
    return clip_plans
