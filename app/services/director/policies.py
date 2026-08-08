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


# Direct-video prompts intentionally use the compact grammar that has proved
# reliable for text-only MiniMax H3 generations.  These labels are also stable
# parsing boundaries: long music-video shots can be split into several H3
# requests while repeating the complete world/style contract in every request.
DIRECT_VIDEO_SCENE_MARKER = "Scene overview:"
DIRECT_VIDEO_SHOT_MARKER = "Shot 1:"
DIRECT_VIDEO_SOUND_MARKER = "overall_soundscape:"
DIRECT_VIDEO_MUSIC_MARKER = "non_diegetic_music:"


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

def build_character_rules_block(
    has_reference: bool,
    characters: Optional[list[CharacterProfile]] = None,
    *,
    preserve_names: bool = False,
) -> str:
    """Build the character-related rules block for LLM system prompts."""
    if preserve_names:
        base = (
            "H3 CHARACTER RULES:\n"
            "- Preserve every user-supplied proper character/person name and "
            "series, film, or franchise in video prompts exactly as written.\n"
            "- Keep the proper name together with useful visible traits; never "
            "collapse a named identity to a generic man, woman, or character.\n"
            "- Do not invent names that the user or screenplay did not supply."
        )
    else:
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
        lines.append(
            "- Character reference (retain each supplied name/label with its visual description):"
            if preserve_names
            else "- Character reference (use ONLY the visual descriptions below, never names):"
        )
        for c in characters:
            desc = describe_character(c)
            if preserve_names and c.display_name:
                lines.append(f"  * {c.id} / {c.display_name}: {desc}")
            else:
                # Do NOT include display_name in image-driven workflows —
                # image models need visible descriptions, not bare names.
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


def build_character_visual_style_contract(
    character_visual_style: str,
    *,
    preserve: bool = True,
) -> str:
    """Build the planner instruction for a dedicated character medium."""
    style = compact_visual_style(character_visual_style)
    if not preserve or not style:
        return ""
    return "\n".join((
        "CHARACTER RENDERING CONTRACT — STRICT:",
        f"- Canonical character rendering/material: {style}.",
        "- Repeat this contract in every image and video prompt. Every visible person or "
        "character must use this exact material, proportions, surface treatment and design language.",
        "- Lighting, pose, wardrobe and camera may change; the character rendering medium may not.",
    ))


def build_visible_text_contract(allow_clip_text: bool = False) -> str:
    """Tell planners whether readable lettering may exist inside generated shots."""
    if allow_clip_text:
        return (
            "VISIBLE TEXT POLICY: Readable lettering is allowed only when the user explicitly "
            "authors it for a shot. Never add unrequested captions or subtitles."
        )
    return (
        "VISIBLE TEXT POLICY — STRICT: No readable text may appear in any generated image or "
        "video. Lyrics and dialogue are audio/performance context only. Never quote, copy, "
        "display or materialize them as captions, subtitles, title cards, signs, labels, UI, "
        "logos or floating words. Express meaning through action and imagery. Screens, code "
        "and signage must remain abstract and unreadable."
    )


_VISIBLE_TEXT_MARKER = "NO VISIBLE TEXT LOCK:"
_VISIBLE_TEXT_DIRECTIVE = re.compile(
    r"\b(?:"
    r"text.{0,100}(?::|appears?|materializ\w*|overlay\w*|display\w*|form\w*|float\w*)|"
    r"(?:captions?|subtitles?|lettering|title\s+cards?)\s*(?::|appears?|materializ\w*|overlay\w*|display\w*)|"
    r"readable\s+(?:words?|letters?|code)|processing\s+text|floating\s+words?|"
    r"(?:question|lyrics?|words?|lines?\s+of\s+code).{0,100}(?:appear|materializ|overlay|display|form|float)"
    r")",
    flags=re.I,
)


def strip_visible_text_directions(prompt: str) -> str:
    """Remove explicit visual-lettering instructions while preserving shot action.

    Spoken dialogue is intentionally not removed. This targets directions such as
    ``Text overlays: 'lyric'`` or ``the question materializes as corrupted text``.
    """
    text = str(prompt or "").strip()
    if not text or _VISIBLE_TEXT_MARKER.casefold() in text.casefold():
        return text
    pieces = re.split(r"(?<=[.;])\s+|\n+", text)
    kept: list[str] = []
    for piece in pieces:
        segment = piece.strip()
        if not segment:
            continue
        match = _VISIBLE_TEXT_DIRECTIVE.search(segment)
        if not match:
            kept.append(segment)
            continue
        prefix = re.sub(
            r"(?:\b(?:and|then|while|as)\b\s*)?$",
            "",
            segment[:match.start()].rstrip(" ,;:-"),
            flags=re.I,
        ).strip()
        # Keep meaningful action that precedes a trailing lettering request.
        if len(prefix) >= 12 and not prefix.endswith(":"):
            kept.append(prefix.rstrip(" .") + ".")
    return " ".join(kept).strip()


def apply_character_visual_style_lock(
    prompt: str,
    character_visual_style: str,
    *,
    mode: str,
    preserve: bool = True,
) -> str:
    """Prepend a dedicated, idempotent character-rendering lock."""
    text = str(prompt or "").strip()
    style = compact_visual_style(character_visual_style)
    if not preserve or not style or "character style lock:" in text.casefold():
        return text
    lock = (
        f"CHARACTER STYLE LOCK: {style}. Every visible person or character must keep this "
        "exact rendering medium, material, proportions and surface treatment throughout."
    )
    combined = f"{lock} {text}".strip()
    if mode in {"image", "image_gen", "keyframe"} and len(combined) > 1450:
        remaining = max(0, 1449 - len(lock))
        shortened = text[:remaining].rsplit(" ", 1)[0].rstrip(" .;,")
        combined = f"{lock} {shortened}".strip()
    return combined


def apply_no_visible_text_lock(prompt: str, *, mode: str) -> str:
    """Strip visible-lettering directions and prepend the final render guard."""
    text = str(prompt or "").strip()
    if not text or _VISIBLE_TEXT_MARKER.casefold() in text.casefold():
        return text
    text = strip_visible_text_directions(text)
    lock = (
        f"{_VISIBLE_TEXT_MARKER} Render no readable words, letters, numbers, captions, "
        "subtitles, title cards, labels, signs, UI, logos or watermarks. Lyrics and dialogue "
        "remain audio/performance only; any screens or code are abstract and unreadable."
    )
    combined = f"{lock} {text}".strip()
    if mode in {"image", "image_gen", "keyframe"} and len(combined) > 1450:
        remaining = max(0, 1449 - len(lock))
        shortened = text[:remaining].rsplit(" ", 1)[0].rstrip(" .;,")
        combined = f"{lock} {shortened}".strip()
    return combined


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
    character_visual_style: str = "",
    allow_clip_text: bool = True,
) -> list[dict]:
    """Apply final style, character-medium and visible-text locks."""
    has_global_style = preserve and bool(compact_visual_style(visual_style))
    has_character_style = preserve and bool(compact_visual_style(character_visual_style))
    if not has_global_style and not has_character_style and allow_clip_text:
        return clip_plans

    def enforce(value: object, mode: str) -> str:
        prompt = str(value or "").strip()
        if not prompt:
            return prompt
        if has_global_style:
            prompt = apply_visual_style_lock(
                prompt,
                visual_style,
                mode=mode,
                preserve=True,
                has_reference=has_reference,
            )
        if has_character_style:
            prompt = apply_character_visual_style_lock(
                prompt,
                character_visual_style,
                mode=mode,
                preserve=True,
            )
        if not allow_clip_text:
            prompt = apply_no_visible_text_lock(prompt, mode=mode)
        return prompt

    for plan in clip_plans or []:
        if not isinstance(plan, dict):
            continue
        metadata = plan.get("metadata")
        motion_only_prompt = bool(
            isinstance(metadata, dict)
            and metadata.get("motion_only_prompt")
        )
        if str(plan.get("image_prompt") or "").strip():
            plan["image_prompt"] = enforce(plan["image_prompt"], "image")
        if (
            not motion_only_prompt
            and str(plan.get("video_prompt") or "").strip()
        ):
            plan["video_prompt"] = enforce(plan["video_prompt"], "video")
        for field, mode in (
            ("window_prompts", "video"),
            ("keyframe_prompts", "image"),
            ("h3_segment_prompts", "video"),
        ):
            if motion_only_prompt and mode == "video":
                continue
            values = plan.get(field)
            if not isinstance(values, list):
                continue
            plan[field] = [
                enforce(
                    value.get("prompt", value.get("text", ""))
                    if isinstance(value, dict) else value,
                    mode,
                )
                for value in values
            ]
    return clip_plans


def direct_video_situation(prompt: object) -> str:
    """Extract only the variable shot situation from a composed direct prompt.

    The operation is deliberately tolerant of a prompt that has already passed
    through the FL2VA/Ref2VA adapter.  Direct mode must never retain those
    image-reference claims when it is converted back to pure text-to-video.
    """
    text = str(prompt or "").strip()
    if not text:
        return ""
    if DIRECT_VIDEO_SHOT_MARKER.casefold() in text.casefold():
        text = re.split(
            re.escape(DIRECT_VIDEO_SHOT_MARKER),
            text,
            maxsplit=1,
            flags=re.I,
        )[1]
    elif "integrated_multimodal_description:" in text.casefold():
        text = re.split(
            r"integrated_multimodal_description:",
            text,
            maxsplit=1,
            flags=re.I,
        )[1]
    elif "detailed_description:" in text.casefold():
        text = re.split(
            r"detailed_description:",
            text,
            maxsplit=1,
            flags=re.I,
        )[1]
    text = re.split(
        rf"{re.escape(DIRECT_VIDEO_SOUND_MARKER)}|{re.escape(DIRECT_VIDEO_MUSIC_MARKER)}",
        text,
        maxsplit=1,
        flags=re.I,
    )[0]
    text = re.sub(
        r"^The referenced picture is the exact opening frame\.[^.]*"
        r"authoritative[^.]*\.\s*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(
        r"^For the target video, at 0\.00 seconds[^.]*fully referenced\.\s*",
        "",
        text,
        flags=re.I,
    )
    return " ".join(text.split()).strip(" .")


def compose_direct_video_prompt(
    master_prompt: object,
    situation_prompt: object,
    *,
    plan: Optional[dict] = None,
    audio_direction: object = "",
    allow_clip_text: bool = True,
) -> str:
    """Compose one self-contained text-only video prompt.

    ``master_prompt`` is copied verbatim at the front of every generated clip.
    The LLM is only responsible for ``situation_prompt``.  No first-frame or
    reference terminology is introduced here because direct mode has no image
    conditioning at any stage.
    """
    master = " ".join(str(master_prompt or "").split()).strip()
    situation = direct_video_situation(situation_prompt)
    shot = plan if isinstance(plan, dict) else {}

    # A previously composed prompt contains its master before Scene overview.
    # Remove that prefix before rebuilding so retries and manual edits remain
    # idempotent even when the user changes the master prompt.
    if DIRECT_VIDEO_SCENE_MARKER.casefold() in situation.casefold():
        situation = re.split(
            re.escape(DIRECT_VIDEO_SCENE_MARKER),
            situation,
            maxsplit=1,
            flags=re.I,
        )[-1]

    overview_parts: list[str] = []
    for value in (shot.get("scene_goal"), shot.get("environment")):
        clean = " ".join(str(value or "").split()).strip(" .")
        if clean and clean.casefold() not in {item.casefold() for item in overview_parts}:
            overview_parts.append(clean)
    overview = ". ".join(overview_parts) or "One concrete continuous moment in the established world"
    situation = situation or "The scene unfolds as one concrete, visually executable continuous shot"
    if not allow_clip_text:
        situation = apply_no_visible_text_lock(situation, mode="video")

    audio = shot.get("audio_plan") if isinstance(shot.get("audio_plan"), dict) else {}
    sound_parts: list[str] = []
    ambience = " ".join(str(audio.get("ambience") or "").split()).strip(" .")
    if ambience:
        sound_parts.append(ambience)
    effects = audio.get("effects")
    if isinstance(effects, list):
        clean_effects = [" ".join(str(item).split()).strip(" .") for item in effects]
        clean_effects = [item for item in clean_effects if item]
        if clean_effects:
            sound_parts.append("Synchronized effects: " + ", ".join(clean_effects))
    direction = " ".join(str(audio_direction or "").split()).strip(" .")
    if direction:
        sound_parts.append(direction)
    if not sound_parts:
        sound_parts.append("Natural synchronized ambience and effects matching the visible action")

    return "\n".join((
        master,
        f"{DIRECT_VIDEO_SCENE_MARKER} {overview}.",
        f"{DIRECT_VIDEO_SHOT_MARKER} {situation}.",
        f"{DIRECT_VIDEO_SOUND_MARKER} {'; '.join(sound_parts)}.",
        f"{DIRECT_VIDEO_MUSIC_MARKER} none",
    )).strip()


def enforce_direct_video_on_clip_plans(
    clip_plans: list[dict],
    master_prompt: object,
    *,
    audio_direction: object = "",
    allow_clip_text: bool = True,
) -> list[dict]:
    """Make every video prompt self-contained and remove all image stages."""
    master = " ".join(str(master_prompt or "").split()).strip()
    if not master:
        raise ValueError("Direct video mode requires a master video prompt.")

    for plan in clip_plans or []:
        if not isinstance(plan, dict):
            continue
        plan["video_prompt"] = compose_direct_video_prompt(
            master,
            plan.get("video_prompt"),
            plan=plan,
            audio_direction=audio_direction,
            allow_clip_text=allow_clip_text,
        )
        windows = plan.get("window_prompts")
        if isinstance(windows, list):
            plan["window_prompts"] = [
                compose_direct_video_prompt(
                    master,
                    value.get("prompt", value.get("text", ""))
                    if isinstance(value, dict) else value,
                    plan=plan,
                    audio_direction=audio_direction,
                    allow_clip_text=allow_clip_text,
                )
                for value in windows
                if str(
                    value.get("prompt", value.get("text", ""))
                    if isinstance(value, dict) else value
                ).strip()
            ]
        plan["image_prompt"] = ""
        plan["image_source"] = "none"
        plan["keyframe_prompts"] = []
        plan["h3_segment_prompts"] = []
        metadata = plan.setdefault("metadata", {})
        if isinstance(metadata, dict):
            metadata["generation_mode"] = "direct_video"
            metadata["direct_video_master_prompt"] = master
    return clip_plans
