"""Official MiniMax H3 prompt-dialect regression tests."""

from app.services.director.minimax_h3_prompting import (
    FIRST_FRAME_REFERENCE,
    adapt_clip_plans_for_h3,
    format_minimax_h3_prompt,
    is_structured_h3_prompt,
)
from app.services.director.prompt_polish import get_video_guide
from app.services.enhance_guides import get_enhance_guide


def _shot():
    return {
        "subjects_on_screen": [{
            "visual_description": "a copper service robot with one amber eye",
            "speaker_name": "Erio",
        }],
        "environment": "a crystal desert at blue dawn",
        "visual_style": "cinematic retrofuturism",
        "lighting": "cold sky with warm amber rim light",
        "camera_plan": {
            "framing": "medium shot",
            "movement": "slow dolly in",
            "movement_intensity": "subtle",
        },
        "audio_plan": {
            "mode": "dialogue_driven",
            "ambience": "a low desert wind",
            "effects": ["quiet servo movement"],
            "lip_sync_critical": True,
        },
        "dialogue_beats": [{
            "speaker_name": "Erio",
            "spoken_text": "¿Dónde está la semilla?",
            "delivery": "softly",
        }],
        "ending_beat": "the amber eye reflected in the seed",
    }


def test_first_frame_prompt_uses_official_field_order_and_dialogue_tags():
    prompt = format_minimax_h3_prompt(
        _shot(),
        "The robot kneels, opens one hand, and reveals the seed.",
        reference_mode="first_frame",
    )

    assert prompt.startswith(FIRST_FRAME_REFERENCE)
    assert is_structured_h3_prompt(prompt, "first_frame")
    assert prompt.index("integrated_multimodal_description:") < prompt.index("overall_soundscape:")
    assert prompt.index("overall_soundscape:") < prompt.index("non_diegetic_music:")
    assert "(S1) Erio says <d>[Spanish] ¿Dónde está la semilla?</d>" in prompt
    assert "slow dolly in" in prompt
    assert "Audio:" not in prompt


def test_reference_prompt_uses_six_field_contract_without_first_frame_claim():
    prompt = format_minimax_h3_prompt(
        _shot(),
        "The robot crosses the desert and stops beside a luminous tree.",
        reference_mode="references",
    )

    assert is_structured_h3_prompt(prompt, "references")
    assert prompt.startswith("subject_definitions:")
    assert "summary: [reference generation]" in prompt
    assert "retention_analysis:" in prompt
    assert "detailed_description:" in prompt
    assert "at 0.00 seconds" not in prompt


def test_clip_adapter_preserves_image_prompt_and_adapts_every_video_mode():
    clips = [{"image_prompt": "static robot portrait", "video_prompt": "The robot looks up."}]
    adapted = adapt_clip_plans_for_h3(clips, [_shot()])

    assert adapted[0]["image_prompt"] == "static robot portrait"
    assert is_structured_h3_prompt(adapted[0]["video_prompt"], "first_frame")


def test_h3_guides_resolve_for_enhance_and_director_polish():
    assert "integrated_multimodal_description" in get_enhance_guide("minimax_h3", "video", True)
    assert "integrated_multimodal_description" in get_video_guide("minimax_h3", "light")
    assert "subject_definitions" in get_video_guide("minimax_h3_ref2va", "light")
