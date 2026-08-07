import json

import pytest

from app.services.video_extra_info import (
    build_saved_video_context,
    generate_video_extra_info,
    normalize_generated_copy,
    normalize_language,
)


def test_context_uses_saved_prompt_without_unrelated_settings():
    metadata = {
        "params": {
            "prompt": "A red kite crosses a stormy coastal sky.",
            "negative_prompt": "blurry, low quality",
            "model_type": "minimax_h3",
        }
    }

    context = build_saved_video_context(metadata)

    assert "red kite" in context["text"]
    assert "blurry" not in context["text"]
    assert context["prompt_count"] == 1
    assert context["director_context"] is False
    assert len(context["source_fingerprint"]) == 64


def test_context_adds_director_brief_and_deduplicated_final_shots():
    pipeline = {
        "scene_description": "A musician searches for home across a flooded city.",
        "clip_plans": [
            {
                "video_prompt": "She rows between neon rooftops.",
                "h3_segment_prompts": ["verbose provider syntax that must stay out"],
            },
            {"video_prompt": "She rows between neon rooftops."},
            {"video_prompt": "At sunrise, she reaches a rooftop garden."},
        ],
        "_params_snapshot": {
            "visual_style": "Handmade stop motion with paper textures.",
            "character_visual_style": "All people are folded paper puppets.",
        },
        "video_model": "minimax_h3",
        "pipeline_type": "music_video",
    }

    context = build_saved_video_context({}, pipeline)

    assert "flooded city" in context["text"]
    assert "Handmade stop motion" in context["text"]
    assert "folded paper puppets" in context["text"]
    assert context["text"].count("She rows between neon rooftops") == 1
    assert "verbose provider syntax" not in context["text"]
    assert context["prompt_count"] == 2
    assert context["director_context"] is True


def test_generation_requests_structured_copy_and_enforces_platform_limits():
    captured = {}

    def fake_generate(**kwargs):
        captured.update(kwargs)
        return json.dumps({
            "overview": "A concise overview.",
            "youtube": {
                "title": "T" * 140,
                "description": "A useful YouTube description.\n\n#Video #Story #Music",
            },
            "x": {"post": "X" * 340},
        })

    result = generate_video_extra_info(
        {
            "text": "PRIMARY GENERATION PROMPT:\nA dancer crosses an empty theatre.",
            "source_fingerprint": "abc",
            "prompt_count": 1,
            "director_context": False,
        },
        "es-ES",
        fake_generate,
    )

    assert result["language"] == "es"
    assert result["language_label"] == "Spanish"
    assert len(result["youtube"]["title"]) == 100
    assert len(result["x"]["post"]) == 280
    assert "image_paths" not in captured
    assert captured["json_schema"]["required"] == ["overview", "youtube", "x"]
    assert captured["enable_thinking"] is False
    assert "<production_notes>" in captured["prompt"]


def test_fenced_json_is_accepted_and_missing_fields_are_rejected():
    valid = """```json
{"overview":"One.","youtube":{"title":"Title","description":"Description"},"x":{"post":"Post"}}
```"""
    assert normalize_generated_copy(valid)["youtube"]["title"] == "Title"

    with pytest.raises(ValueError, match="omitted"):
        normalize_generated_copy('{"overview":"Only one field"}')


def test_language_allowlist_rejects_unknown_codes():
    assert normalize_language("pt-BR") == ("pt", "Portuguese")
    with pytest.raises(ValueError, match="Unsupported language"):
        normalize_language("xx")
