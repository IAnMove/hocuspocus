"""Light from the reference and clothes from references (wall 2): visible and overridable.

Maestro ended every image prompt with "Use lighting and color temp from
reference image" (also in the no-reference guide) and removed clothing words
from every Pass 2 image prompt. The light rule now follows the run's
``lighting_continuity`` (default ``auto``: only with the user's own reference
image); the clothing rule follows ``keep_reference_wardrobe`` (default on).
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from services.director import image_prompt_rules
from services.director.image_prompt_rules import get_image_prompt_rules, prepare_guide
from services.director.orchestrator import DirectorFlags, DirectorOrchestrator
from services.director.planners.base import BasePlanner
from services.director.planners.music_video import MusicVideoPlanner
from services.director.planners.short_film import ShortFilmPlanner
from services.director.prompt_cleanup import sanitize_pass2_image_prompts
from services.director.schema import ProductionPlan
from services.video_extra_info import build_saved_clip_info

LIGHT = "color temp from reference image"
GOWN = "The singer now in a red evening gown stands on the stage. She is running toward the crowd, lost in the moment. Soft light."
CLEANED = "The singer now in a red evening stands on the stage. Soft light."


class _Planner(BasePlanner):
    def plan(self, **_kwargs):  # pragma: no cover - not used
        return ProductionPlan(skill_type="test", shots=[])


def _options(*, user: bool, any_ref: bool, **attributes) -> dict:
    planner = _Planner()
    for name, value in attributes.items():
        setattr(planner, name, value)
    return planner._image_rule_options(has_user_reference=user, has_any_reference=any_ref)


# ── The light rule ────────────────────────────────────────────────────────

def test_the_text_to_image_rules_never_end_with_the_reference_light():
    # No reference exists when the plan is written with this guide.
    assert LIGHT not in get_image_prompt_rules(False)
    assert LIGHT not in get_image_prompt_rules(False, **_options(user=False, any_ref=False))
    guide = (Path(image_prompt_rules.__file__).parents[1] / "llm_guides" / "director" / "flux_image_generation.md")
    assert LIGHT not in guide.read_text(encoding="utf-8").lower()


@pytest.mark.parametrize("image_model", ["flux2_klein_9b", "qwen_image_21"])
def test_auto_light_copies_the_reference_only_with_the_users_reference_image(image_model):
    with_user = get_image_prompt_rules(True, image_model=image_model, **_options(user=True, any_ref=True))
    cast_only = get_image_prompt_rules(True, image_model=image_model, **_options(user=False, any_ref=True))
    assert LIGHT in with_user
    assert LIGHT not in cast_only
    # Only the separate rule carries it: the edit guides no longer do.
    assert LIGHT not in prepare_guide(image_prompt_rules.load_guide(image_prompt_rules._route_image_pass2_guide(image_model)))


def test_reference_and_per_shot_light_override_auto():
    assert _options(user=False, any_ref=True, lighting_continuity="reference")["lighting_from_reference"] is True
    assert _options(user=True, any_ref=True, lighting_continuity="per_shot")["lighting_from_reference"] is False
    rules = get_image_prompt_rules(True, image_model="qwen_image_21", **_options(
        user=True, any_ref=True, lighting_continuity="per_shot",
    ))
    assert LIGHT not in rules


def _story_prompts(**plan_kwargs) -> tuple[list[str], ProductionPlan]:
    """Plan a story with a provider that answers in prose; return its system prompts."""
    prompts: list[str] = []
    responses = iter([
        "INT. HARBOUR - DAWN\n\nMara waits on the pier.\n\nThe ferry arrives and she boards.",
        "Prose instead of shots.",
        "More prose.",
    ])

    def provider(**kwargs):
        prompts.append(str(kwargs.get("system_prompt") or ""))
        return next(responses)

    planner = ShortFilmPlanner(llm_generate=provider, llm_generate_streaming=provider)
    plan = planner.plan(
        story_description="Mara leaves the island.", target_duration=40, target_scenes=2,
        fps=24, frames_steps=8, frames_minimum=41, image_model="qwen_image_21", **plan_kwargs,
    )
    return prompts, plan


def test_a_story_with_character_references_only_no_longer_copies_the_anchors_light(tmp_path):
    portrait = tmp_path / "mara.png"
    portrait.write_bytes(b"image")
    prompts, _plan = _story_prompts(character_ref_paths=[str(portrait)], character_ref_labels=["Mara"])
    assert any("NEVER NAME GARMENTS" in prompt for prompt in prompts)  # the edit guide was used
    assert not any(LIGHT in prompt for prompt in prompts)
    prompts, _plan = _story_prompts(reference_image_path=str(portrait))
    assert any(LIGHT in prompt for prompt in prompts)


def test_the_music_video_aesthetic_block_follows_the_same_flag():
    def plan_prompts(lighting: str) -> str:
        prompts: list[str] = []

        def provider(**kwargs):
            prompts.append(str(kwargs.get("system_prompt") or ""))
            return json.dumps([])

        planner = MusicVideoPlanner(llm_generate=provider)
        planner.lighting_continuity = lighting
        with pytest.raises(RuntimeError):
            planner.plan(
                clips=[{"start": 0, "end": 4, "label": "intro", "beat_count": 8}],
                scene_description="A singer at a harbour.", bpm=120,
                reference_image_path="/uploads/singer.png", image_model="qwen_image_21",
            )
        return prompts[0]

    assert "VISUAL AESTHETIC" in plan_prompts("auto") and LIGHT in plan_prompts("auto")
    per_shot = plan_prompts("per_shot")
    assert "VISUAL AESTHETIC" not in per_shot and LIGHT not in per_shot


# ── With no reference of any kind ─────────────────────────────────────────

def test_shared_reference_off_and_no_refs_gives_the_reference_free_guide():
    options = _options(user=False, any_ref=False, reference_anchor="off")
    assert options["reference_free"] is True
    rules = get_image_prompt_rules(False, **options)
    assert "Nth image" not in rules and "attire from reference" not in rules and LIGHT not in rules
    assert "There is no reference image" in rules
    # The default still draws a shared reference, so the guide keeps the reference wording.
    assert "Nth image" in get_image_prompt_rules(False, **_options(user=False, any_ref=False))
    assert "<!--" not in rules


# ── Clothes from references ───────────────────────────────────────────────

@pytest.mark.parametrize("image_model", ["flux2_klein_9b", "qwen_image_21"])
def test_keep_wardrobe_off_drops_the_clothing_block(image_model):
    kept = get_image_prompt_rules(True, image_model=image_model)
    dropped = get_image_prompt_rules(True, image_model=image_model, keep_wardrobe=False)
    assert "NEVER NAME GARMENTS" in kept and "bikini, bra, lingerie" in kept
    assert "NEVER NAME GARMENTS" not in dropped and "bikini, bra, lingerie" not in dropped
    assert "<!--" not in kept and "<!--" not in dropped
    assert "Do NOT invent or describe clothing" not in get_image_prompt_rules(False, keep_wardrobe=False)


def test_the_pass2_cleanup_counts_what_it_removes():
    shots = [{"image_prompt": GOWN, "keyframe_prompts": [GOWN, 3]}, {"image_prompt": "A quiet room."}]
    sanitize_pass2_image_prompts(shots)
    assert shots[0]["image_prompt"] == CLEANED
    assert shots[0]["keyframe_prompts"] == [CLEANED, 3]
    assert shots[0]["_prompt_cleanup"] == {"garments": 2, "motion_sentences": 2, "fillers": 2}
    assert "_prompt_cleanup" not in shots[1]


def test_keep_wardrobe_off_keeps_clothing_words():
    shots = [{"image_prompt": GOWN}]
    sanitize_pass2_image_prompts(shots, keep_wardrobe=False)
    assert "red evening gown" in shots[0]["image_prompt"]
    assert shots[0]["_prompt_cleanup"] == {"garments": 0, "motion_sentences": 1, "fillers": 1}


def test_raw_prompts_leave_the_pass2_prompts_as_written():
    shots = [{"image_prompt": GOWN, "keyframe_prompts": [GOWN]}]
    sanitize_pass2_image_prompts(shots, raw_prompts=True)
    assert shots == [{"image_prompt": GOWN, "keyframe_prompts": [GOWN]}]


# ── The counts land in the shot metadata and Extra info ───────────────────

def _music_shot(image_prompt: str) -> dict:
    return {
        "clip_index": 1, "scene_goal": "The singer waits", "scene_type": "performance",
        "subjects_on_screen": [], "environment": "A stage", "visual_style": "anime",
        "lighting": "soft", "mood": "calm", "action_beats": ["She waits"],
        "camera_plan": {"framing": "medium shot", "movement": "slow push in", "movement_intensity": "subtle"},
        "ending_beat": "She smiles", "image_source": "original", "image_prompt": image_prompt,
        "visual_changes": [], "video_prompt": "The camera slowly pushes in while the singer smiles at the crowd.",
        "keyframe_prompts": [], "window_prompts": [],
    }


def _music_plan(**attributes) -> ProductionPlan:
    planner = MusicVideoPlanner(llm_generate=lambda **_kwargs: json.dumps([_music_shot(GOWN)]))
    for name, value in attributes.items():
        setattr(planner, name, value)
    return planner.plan(
        clips=[{"start": 0, "end": 4, "label": "verse", "beat_count": 8}],
        scene_description="A singer on a stage.", bpm=120,
    )


def test_the_counts_land_in_the_shot_metadata():
    shot = _music_plan().shots[0]
    assert shot.image_prompt == CLEANED
    assert shot.metadata["prompt_cleanup"] == {"garments": 1, "motion_sentences": 1, "fillers": 1}
    raw = _music_plan(raw_prompts=True).shots[0]
    assert raw.image_prompt == GOWN and "prompt_cleanup" not in raw.metadata
    kept = _music_plan(keep_reference_wardrobe=False).shots[0]
    assert "red evening gown" in kept.image_prompt


def test_extra_info_shows_what_was_removed_before_the_model():
    pipeline = {
        "clips": [{"index": 0, "video_filename": "take.mp4"}, {"index": 1, "video_filename": "other.mp4"}],
        "clip_plans": [
            {"metadata": {"prompt_cleanup": {"garments": 2, "motion_sentences": 1, "fillers": 0}}},
            {"metadata": {}},
        ],
    }
    clip = build_saved_clip_info("take.mp4", {"params": {}}, pipeline=pipeline)
    assert clip["prompt_cleanup"] == {"garments": 2, "motion_sentences": 1, "fillers": 0}
    assert build_saved_clip_info("other.mp4", {"params": {}}, pipeline=pipeline)["prompt_cleanup"] == {}
    assert build_saved_clip_info("take.mp4", {"params": {}})["prompt_cleanup"] == {}


# ── Request → Settings › Services → default, for the v2 plan endpoint too ──

def test_the_orchestrator_gives_planners_the_resolved_options():
    seen: list[tuple] = []

    class _Recorder:
        def __init__(self, **_kwargs):
            pass

        def plan(self, **_kwargs):
            seen.append((self.reference_anchor, self.lighting_continuity, self.keep_reference_wardrobe))
            return ProductionPlan(skill_type="music_video", shots=[])

    services = {"director_lighting_continuity": "per_shot", "director_keep_reference_wardrobe": False}
    wgp = SimpleNamespace(server_config={"services": services})
    flags = DirectorFlags.from_dict({"reference_anchor": "off"})  # a v2 plan request's director_flags
    from services.director import orchestrator as director_orchestrator
    with patch.dict("sys.modules", {"wgp": wgp}), \
            patch.dict(director_orchestrator._PLANNER_MAP, {"music_video": _Recorder}):
        DirectorOrchestrator(flags=flags).plan("music_video")
        DirectorOrchestrator().plan("music_video")
    assert seen == [("off", "per_shot", False), ("always", "per_shot", False)]
