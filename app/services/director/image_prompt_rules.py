"""
Shared image prompt rules for all Director planners.

Centralized so music video, short film, podcast, and viral video planners
all produce consistent image prompts. Rules loaded from .md guide files
and routed by the selected image model so each model gets dialect-aware
guidance instead of one-size-fits-all Qwen-flavored rules.

Routing table (image model prefix → Pass 2 guide file):
  flux*, z_image*       → flux_image_edit_pass2.md   (Flux.2 Klein and friends)
  qwen_image_edit*      → qwen_image_edit_reference.md
  qwen_image_layered*   → qwen_image_edit_reference.md
  qwen_image*           → qwen_image_edit_reference.md
  (no model match)      → qwen_image_edit_reference.md (legacy fallback)

For text-to-image (no reference photo), all models share the
flux_image_generation.md guide since pure t2i pipelines align
on similar prompting principles.

Guide sections between ``<!-- NAME -->`` and ``<!-- /NAME -->`` lines are
kept or dropped per run (``prepare_guide``):
  CLOTHING      the "never name garments" rules; dropped when Settings ›
                Services › Keep clothes from references is off.
  REFERENCE     text-to-image wording that points at a reference image.
  NO_REFERENCE  its replacement when the run has no reference image, no
                character or location references and no shared reference.
The "Use lighting and color temp from reference image" rule lives in
reference_lighting_rule.md and is appended only when the run copies the
reference's light (``lighting_from_reference``).
"""

import re
from typing import Optional

from .guide_loader import load_guide


# Image model architecture → Pass 2 guide file
_IMAGE_PASS2_GUIDE_MAP = {
    # Flux family — Flux.2 Klein 9b is the certified path
    "flux": "flux_image_edit_pass2.md",
    "z_image": "flux_image_edit_pass2.md",
    # Qwen image-edit family — was the only path until Flux routing landed
    "qwen_image_edit": "qwen_image_edit_reference.md",
    "qwen_image_layered": "qwen_image_edit_reference.md",
    "qwen_image": "qwen_image_edit_reference.md",
}


# qwen_image_edit_reference.md teaches "show the starting state" with
# undressing examples. They are sexual examples, so only mature (NSFW) mode
# sees them; otherwise the same lessons use a letter that is opened. A test
# checks that every mature example is still in the guide.
_MATURE_EXAMPLE_SWAPS = (
    (
        "If the scene involves a woman removing her top → the image shows her WEARING the top.",
        "If the scene involves a woman opening a letter → the image shows the letter still SEALED.",
    ),
    (
        "(woman already topless, man already at door)",
        "(letter already open, man already at door)",
    ),
    (
        "Scene where woman removes dress → IMAGE shows: \"create new scene, bedroom. "
        "The woman from the reference image is now standing by the bed.",
        "Scene where woman opens a letter → IMAGE shows: \"create new scene, hallway. "
        "The woman from the reference image is now standing by the door, holding a sealed envelope.",
    ),
    ("(NOT already undressed)", "(NOT already reading it)"),
    (
        "\"the woman is now topless on the bed\" when the scene is ABOUT her undressing.",
        "\"the woman is now reading the open letter\" when the scene is ABOUT her opening it.",
    ),
)


def _without_mature_examples(guide: str) -> str:
    """The guide with its sexual examples replaced by non-sexual ones."""
    for mature, plain in _MATURE_EXAMPLE_SWAPS:
        guide = guide.replace(mature, plain)
    return guide


_GUIDE_SECTIONS = ("CLOTHING", "REFERENCE", "NO_REFERENCE")
_SECTION_MARKER = re.compile(r"^<!-- /?[A-Z_]+ -->\n?", re.MULTILINE)


def _section(name: str) -> "re.Pattern[str]":
    return re.compile(
        rf"^<!-- {name} -->\n(.*?)^<!-- /{name} -->\n?",
        re.MULTILINE | re.DOTALL,
    )


def prepare_guide(guide: str, *, keep_wardrobe: bool = True, reference_free: bool = False) -> str:
    """The guide text for this run: optional sections kept or dropped, markers removed."""
    keep = {
        "CLOTHING": keep_wardrobe,
        "REFERENCE": not reference_free,
        "NO_REFERENCE": reference_free,
    }
    for name in _GUIDE_SECTIONS:
        guide = _section(name).sub(
            (lambda match: match.group(1)) if keep[name] else "",
            guide,
        )
    return _SECTION_MARKER.sub("", guide).strip()


def _route_image_pass2_guide(image_model: str) -> str:
    """Pick the Pass 2 image guide filename for the given model."""
    if not image_model:
        return "qwen_image_edit_reference.md"  # legacy fallback
    model_lower = image_model.lower()
    best_match: str | None = None
    best_len = 0
    for prefix, guide_file in _IMAGE_PASS2_GUIDE_MAP.items():
        if model_lower.startswith(prefix) and len(prefix) > best_len:
            best_match = guide_file
            best_len = len(prefix)
    return best_match or "qwen_image_edit_reference.md"


def get_image_prompt_rules(
    has_reference: bool,
    num_character_refs: int = 0,
    num_location_refs: int = 0,
    character_ref_labels: list[str] | None = None,
    location_ref_labels: list[str] | None = None,
    seamless: bool = True,
    image_model: str = "",
    nsfw: bool = False,
    *,
    lighting_from_reference: Optional[bool] = None,
    keep_wardrobe: bool = True,
    reference_free: bool = False,
) -> str:
    """Return the image prompt instruction block for LLM system prompts.

    `image_model` selects between dialect-aware Pass 2 guides (e.g.,
    Flux.2 Klein vs. Qwen Image Edit). Pass an empty string to keep
    the historical Qwen-flavored default. The guide's sexual examples
    appear only when `nsfw` (mature mode) is on.

    ``lighting_from_reference`` appends the "Use lighting and color temp from
    reference image" rule (None: only with a reference-edit guide).
    ``keep_wardrobe`` keeps the "never name garments" sections.
    ``reference_free`` (no reference of any kind) gives the text-to-image
    guide without "from the Nth image", reference attire or lighting.
    """
    if lighting_from_reference is None:
        lighting_from_reference = has_reference
    lighting_block = (
        "\n\n" + load_guide("reference_lighting_rule.md")
        if lighting_from_reference and not (reference_free and not has_reference)
        else ""
    )

    # Seamless mode hint — kept minimal so it doesn't overwhelm scene planning
    seamless_block = ""
    if seamless:
        seamless_block = """
SEAMLESS MODE: Each scene's start image is also used as the end frame of the previous scene.
Keep consecutive scenes visually compatible — avoid jarring pose or location jumps between scenes.
"""

    # Additional refs section (appended when character/location refs provided)
    extra_refs_block = ""
    if num_character_refs > 0 or num_location_refs > 0:
        lines = []
        if num_character_refs > 0:
            lines.append(f"{num_character_refs} CHARACTER REFERENCE image(s):")
            for i in range(num_character_refs):
                label = (character_ref_labels[i] if character_ref_labels and i < len(character_ref_labels) else "") or f"(unlabeled character {i+1})"
                lines.append(f"  - Character ref {i+1}: {label}")
        if num_location_refs > 0:
            lines.append(f"{num_location_refs} LOCATION REFERENCE image(s):")
            for i in range(num_location_refs):
                label = (location_ref_labels[i] if location_ref_labels and i < len(location_ref_labels) else "") or f"(unlabeled location {i+1})"
                lines.append(f"  - Location ref {i+1}: {label}")
        extra_refs_block = f"""
REFERENCE IMAGES AVAILABLE TO THE PLANNER:
The image model receives the main scene image, the character references, and
only the ONE location reference selected for the current shot:
{chr(10).join(lines)}

Set location_ref_label to the exact label of the location visible in each shot.
Never put multiple location labels in one shot. Use the labels to map characters/locations to references.
Add "use images as reference" at the end of prompts for strong identity matching.
When featuring a specific character, mention them by their label description so the model
matches them to the correct reference image.
"""

    if has_reference:
        guide_file = _route_image_pass2_guide(image_model)
        guide = prepare_guide(load_guide(guide_file), keep_wardrobe=keep_wardrobe)
        if not nsfw:
            guide = _without_mature_examples(guide)
        if guide:
            print(f"[ImagePromptRules] Loaded {guide_file} for image_model={image_model or '(unset)'}")
            return f"{seamless_block}{extra_refs_block}\n{guide}{lighting_block}"
        return f"{seamless_block}{extra_refs_block}{lighting_block}"
    else:
        # Text-to-image: all models share the Flux generation guide.
        base = prepare_guide(
            load_guide("flux_image_generation.md"),
            keep_wardrobe=keep_wardrobe,
            reference_free=reference_free,
        ) or "Describe one static frame with full scene details."
        return f"{seamless_block}{base}{lighting_block}"
