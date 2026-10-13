"""
Content guidance for LLM system prompts — the minors rule and mature mode.

Always:                 injects the hard rule about minors
                        (minors_hard_rule.md), with mature mode on or off.
When mature mode is ON:  also injects clinically-worded mature-content guidance.
                        Each block is SELF-GATING — it tells the model to apply
                        it ONLY when the scene is actually sexual and to write
                        normally otherwise — so it can be injected whenever
                        mature mode is on without harming clean scenes.
When mature mode is OFF: injects no other content rules.

Mature mode is a *permission* (adult generation is allowed), not an *obligation*
(every prompt should be explicit). The mature-mode toggle also filters models
and LoRAs; that filtering lives elsewhere and does not change here.

Architecture (after the Director migration):
  - The mature-mode guidance — director/nsfw_{screenplay,video,image}_rules.md
    for the planners, plus enhance/nsfw_shared.md for the refine path — is
    VERSION-CONTROLLED and clinically worded. It ships with every install, so
    Director mature mode works with no supplement pack and no download.
    Explicit *specifics* come from the uncensored model weights, not from text
    committed to the repo.
  - The minors rule is version-controlled too. llm_service also adds it to every
    request (services/minors_rule.py), so callers that never call this module
    still carry it.
  - The old optional "content supplement pack" (a separately-downloaded zip)
    has been fully retired — nothing reads it anymore.
"""

from ..minors_rule import minors_hard_rule
from .guide_loader import load_guide


# ── Guidance text loaders ────────────────────────────────────────────
# All mature-content guides are version-controlled and clinically worded
# (director/nsfw_{screenplay,video,image}_rules.md + enhance/nsfw_shared.md);
# load_guide reads them from the repo, so they ship with every install. Each
# block is self-gating — it applies only when the scene is actually sexual.


def get_nsfw_video_guidance() -> str:
    """Mature-content guidance block for video prompt generation.

    Loaded from the VERSION-CONTROLLED, clinically-worded guide under
    llm_guides/director/ (migrated off the optional supplement pack in the
    Director migration), so it ships with every install — Director mature mode
    needs no pack and no download.
    """
    return load_guide("nsfw_video_rules.md")


def get_nsfw_image_guidance() -> str:
    """Mature-content guidance block for image prompt generation (version-controlled)."""
    return load_guide("nsfw_image_rules.md")


def get_nsfw_screenplay_guidance() -> str:
    """Mature-content guidance for screenplay writing — narrative voice (version-controlled)."""
    return load_guide("nsfw_screenplay_rules.md")


def get_nsfw_enhance_guidance() -> str:
    """Mature-content guidance for the enhance / refine path (Director Pass-3 polish).

    Reuses the SAME clinical, version-controlled push as Studio mode's enhancer
    (llm_guides/enhance/nsfw_shared.md), so the two refine paths stay in sync and
    there is a single mature-enhance guide to maintain.
    """
    from services.guide_loader import load_guide as _load_shared
    return _load_shared("enhance", "nsfw_shared")


def _mature_guidance(mode: str) -> str:
    """Mature-content guidance for one prompt mode ("" when the guide is missing)."""
    if mode == "both":
        return get_nsfw_video_guidance() + "\n\n" + get_nsfw_image_guidance()
    guidance = {
        "video": get_nsfw_video_guidance,
        "image": get_nsfw_image_guidance,
        "enhance": get_nsfw_enhance_guidance,
        "screenplay": get_nsfw_screenplay_guidance,
    }
    return guidance.get(mode, guidance["video"])()


def _content_block(system_prompt: str, nsfw: bool, mode: str) -> str:
    """The mature guidance (mature mode only) followed by the minors rule."""
    blocks = []
    if nsfw:
        mature = _mature_guidance(mode)
        if mature.strip():
            print(
                f"[NSFW] inject_content_guidance(mode={mode!r}): "
                f"injected {len(mature)} chars of mature-content guidance"
            )
            blocks.append(mature)
        else:
            print(
                f"[NSFW] inject_content_guidance(mode={mode!r}): "
                "no mature guidance to inject (guide file missing or empty)"
            )
    rule = minors_hard_rule()
    if rule not in system_prompt:
        blocks.append(rule)
    return "\n\n".join(blocks)


def inject_content_guidance(system_prompt: str, nsfw: bool, mode: str = "video") -> str:
    """Inject content guidance into a system prompt.

    Always:          injects the hard rule about minors, with nsfw on or off.
    When nsfw=True:  also injects mature-content guidance (version-controlled
                     guides under llm_guides/), placed before the rule so the
                     rule reads last. A missing guide adds nothing.
    When nsfw=False: no other content rules.

    For video/image/screenplay modes: injects NEAR THE TOP (after the first
    paragraph) so the LLM sees the directive before absorbing other rules.
    For enhance mode:      appends at the end (shorter prompt, less risk
                           of burying).
    """
    content_block = _content_block(system_prompt, nsfw, mode)
    if not content_block:
        return system_prompt

    if mode == "enhance":
        return f"{system_prompt}\n\n{content_block}"

    # For video/image: inject after the first paragraph (role line) so the
    # LLM sees the directive early, before all the formatting/style rules.
    lines = system_prompt.split("\n\n", 1)
    if len(lines) == 2:
        return f"{lines[0]}\n\n{content_block}\n\n{lines[1]}"
    else:
        return f"{content_block}\n\n{system_prompt}"


# Backwards compatibility alias
def inject_nsfw_if_enabled(system_prompt: str, nsfw: bool, mode: str = "video") -> str:
    """Deprecated alias — use inject_content_guidance() instead."""
    return inject_content_guidance(system_prompt, nsfw, mode)
