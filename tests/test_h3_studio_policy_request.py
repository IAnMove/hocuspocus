"""Studio H3 policy on the effective generation request."""
from __future__ import annotations

from services.h3_runtime_policy import normalize_h3_runtime_request, normalize_studio_h3_policy
from services.director.minimax_h3_prompting import h3_audio_policy_from_payload
from services.h3_prompt_policy import apply_h3_audio_policy, writing_contract


SPOKEN = 'Alice (S1): «Buenos días»\nBob whispers "keep this line".'


def test_each_studio_entry_reaches_the_effective_backend_policy():
    body = {
        "model_type": "minimax_h3",
        "prompt": SPOKEN,
        "minimax_h3_planning_style": "creative",
        "minimax_h3_audio_policy": "legacy",
    }
    normalize_studio_h3_policy(body)
    assert body["minimax_h3_planning_style"] == "creative"
    assert body["minimax_h3_audio_policy"] == "legacy"
    assert body["prompt"] == SPOKEN
    assert h3_audio_policy_from_payload(body) == "legacy"
    assert "CREATIVE" in writing_contract(body["minimax_h3_planning_style"])
    assert "Buenos días" in body["prompt"]
    assert 'keep this line' in body["prompt"]
    assert "Buenos días" in apply_h3_audio_policy(body["prompt"], body["minimax_h3_audio_policy"])


def test_invalid_studio_policy_values_fall_back_without_rewriting_speech():
    body = {
        "model_type": "minimax_h3",
        "prompt": SPOKEN,
        "minimax_h3_planning_style": "wild",
        "minimax_h3_audio_policy": "maybe",
        "minimax_h3_semantic_bridge_alpha": "nope",
    }
    normalize_studio_h3_policy(body)
    assert body["minimax_h3_planning_style"] == "faithful"
    assert body["minimax_h3_audio_policy"] == "native"
    assert body["minimax_h3_semantic_bridge_alpha"] == 0.0
    assert body["prompt"] == SPOKEN
    assert h3_audio_policy_from_payload(body) == "native"


def test_semantic_bridge_stays_off_by_default_on_supported_and_unsupported_models():
    supported = {"model_type": "minimax_h3", "prompt": SPOKEN}
    normalize_studio_h3_policy(supported)
    assert supported["minimax_h3_semantic_bridge_alpha"] == 0.0
    legacy = {"model_type": "minimax_h3_legacy", "minimax_h3_semantic_bridge_alpha": 0.8}
    normalize_studio_h3_policy(legacy)
    assert legacy["minimax_h3_semantic_bridge_alpha"] == 0.0


def test_runtime_normalize_applies_studio_policy_before_turbo():
    body = {
        "model_type": "minimax_h3",
        "prompt": SPOKEN,
        "minimax_h3_planning_style": "bogus",
        "minimax_h3_audio_policy": "legacy",
    }
    normalize_h3_runtime_request(body, {"architecture": "minimax_h3"})
    assert body["minimax_h3_planning_style"] == "faithful"
    assert body["minimax_h3_audio_policy"] == "legacy"
    assert body["prompt"] == SPOKEN
