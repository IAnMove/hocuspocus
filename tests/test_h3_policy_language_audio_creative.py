"""H-A policy/language, H-B audio trace, H-C creative extra-line contracts.

Shows the final prompt that would be sent, not only helper return values.
Does not write weights, outputs, or real generations.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from models.minimax_h3.ref2va import ensure_ref2va_prompt_relationships
from models.minimax_h3.spoken_language import language_for_quoted_speech
from services.director.minimax_h3_prompting import (
    adapt_clip_plans_for_h3,
    h3_audio_policy_from_payload,
)
from services.h3_prompt_policy import apply_h3_audio_policy, writing_contract
from services.h3_story_contract import (
    extract_locked_lines,
    requests_only_supplied_lines,
    requests_silence,
)
from services import llm_service


ROOT = Path(__file__).resolve().parents[1]
LAUNCH = ROOT / "app" / "_launch_runtime.py"
DIRECTOR = ROOT / "app" / "routers" / "director.py"
REF2VA = ROOT / "app" / "models" / "minimax_h3" / "ref2va.py"
MODELS_LANGUAGE = ROOT / "app" / "models" / "minimax_h3" / "spoken_language.py"
LLM_SERVICE = ROOT / "app" / "services" / "llm_service.py"

STRUCTURED_NATIVE = (
    "integrated_multimodal_description: [Shot 1] Alice (S1) "
    "<d>[English] Hello.</d> nods.\n"
    "overall_soundscape: Quiet room tone and distant traffic.\n"
    "non_diegetic_music: N/A"
)


def _ref2va_refs():
    return [{"type": "image", "path": "alice.png", "role": "Alice"}]


def _adapt_kwargs(node: ast.Call) -> set[str]:
    return {keyword.arg for keyword in node.keywords if keyword.arg}


def test_models_language_helper_does_not_import_services():
    source = MODELS_LANGUAGE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("services")
            assert not module.startswith("app.services")
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("services")


def test_ref2va_quote_path_does_not_import_services():
    source = REF2VA.read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert not module.startswith("services")
            assert not module.startswith("app.services")


def _module_function(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )


def test_runtime_adapt_clip_plans_pass_explicit_policy():
    functions = {
        "director_plan_prompts_and_images": _module_function(
            DIRECTOR, "director_plan_prompts_and_images",
        ),
        "director_plan_short_film_prompts": _module_function(
            DIRECTOR, "director_plan_short_film_prompts",
        ),
        "_director_v2_plan_body": _module_function(LAUNCH, "_director_v2_plan_body"),
    }
    assert set(functions) == {
        "director_plan_prompts_and_images",
        "director_plan_short_film_prompts",
        "_director_v2_plan_body",
    }
    calls = []
    for function in functions.values():
        for node in ast.walk(function):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "adapt_clip_plans_for_h3":
                    calls.append((function.name, node))
    assert len(calls) == 3
    for name, node in calls:
        assert "h3_audio_policy" in _adapt_kwargs(node), name


def test_payload_policy_defaults_native_without_replacing_old_projects():
    assert h3_audio_policy_from_payload({}) == "native"
    assert h3_audio_policy_from_payload({"h3_audio_policy": ""}) == "native"
    assert h3_audio_policy_from_payload({"h3_audio_policy": "legacy"}) == "legacy"
    assert h3_audio_policy_from_payload({"minimax_h3_audio_policy": "legacy"}) == "legacy"
    assert h3_audio_policy_from_payload({"h3_audio_policy": "bogus"}) == "native"


def test_plan_versus_send_records_policy_and_final_prompt():
    planned = [{"video_prompt": STRUCTURED_NATIVE, "image_prompt": "still"}]
    native = adapt_clip_plans_for_h3(
        [dict(planned[0])],
        h3_audio_policy="native",
        reference_mode="direct",
    )
    legacy = adapt_clip_plans_for_h3(
        [dict(planned[0])],
        h3_audio_policy="legacy",
        reference_mode="direct",
    )
    assert native[0]["image_prompt"] == "still"
    assert native[0]["_director_h3_source_prompt"] == STRUCTURED_NATIVE
    assert native[0]["_director_h3_compiled_prompt"] == native[0]["video_prompt"]
    assert native[0]["_director_audio_plan"]["h3_audio_policy"] == "native"
    assert "Quiet room tone" in native[0]["video_prompt"]
    assert legacy[0]["_director_h3_source_prompt"] == STRUCTURED_NATIVE
    assert legacy[0]["_director_audio_plan"]["h3_audio_policy"] == "legacy"
    assert "Quiet room tone" not in legacy[0]["video_prompt"]
    assert "overall_soundscape: N/A" in legacy[0]["video_prompt"]
    assert native[0]["video_prompt"] != legacy[0]["video_prompt"]


def test_window_prompts_use_the_same_audio_policy():
    clips = [{
        "video_prompt": STRUCTURED_NATIVE,
        "window_prompts": [{"prompt": STRUCTURED_NATIVE}],
    }]
    adapted = adapt_clip_plans_for_h3(
        clips, h3_audio_policy="legacy", reference_mode="direct",
    )
    window = adapted[0]["window_prompts"][0]["prompt"]
    assert "Quiet room tone" not in window
    assert "overall_soundscape: N/A" in window


def test_quoted_language_matrix_on_final_ref2va_prompt():
    cases = [
        ('Alice says "Hello there."', "English", "Hello there."),
        ('Ana dice "Qué silencio."', "Spanish", "Qué silencio."),
        ('Ada says: <d>[Spanish] Nadie volvió.</d> then "Ya están aquí."', "Spanish", "Ya están aquí."),
        ('Jean dit "Je ne suis pas ici."', "French", "Je ne suis pas ici."),
        ('A speaker says "Ok."', "English", "Ok."),
        ('Alice says "Hello." Bob replies "We leave at dawn."', "English", "We leave at dawn."),
    ]
    for source, language, words in cases:
        prompt = ensure_ref2va_prompt_relationships(source, _ref2va_refs(), duration_seconds=8)
        assert f"<d>[{language}] {words}</d>" in prompt, source
        assert '"%s"' % words not in prompt
    silent = ensure_ref2va_prompt_relationships(
        "A moonlit cave. Nobody speaks.",
        _ref2va_refs(),
    )
    assert "<d>" not in silent
    sign = ensure_ref2va_prompt_relationships(
        'Dwight reads a sign "EXIT". Alice says "Run!"',
        _ref2va_refs(),
    )
    assert '"EXIT"' in sign
    assert "<d>[English] EXIT</d>" not in sign
    assert "<d>[English] Run!</d>" in sign


def test_language_for_quoted_speech_keeps_explicit_intent():
    assert language_for_quoted_speech("Qué silencio.") == "Spanish"
    assert language_for_quoted_speech("Hello there.") == "English"
    assert language_for_quoted_speech("Ok.") == "English"
    assert language_for_quoted_speech(
        "Hola.",
        "SPOKEN LANGUAGE CONTRACT: Every generated spoken word must be only in Español de España.",
    ) == "Spanish"


def test_que_silencio_is_dialogue_not_a_mute_order():
    source = 'Ana dice "Qué silencio."'
    assert not requests_silence(source)
    locked = extract_locked_lines(source)
    assert locked[0]["text"] == "Qué silencio."
    assert locked[0]["language"] == "Spanish"
    tagged = (
        "integrated_multimodal_description: [Shot 1] Ana (S1) "
        "<d>[Spanish] Qué silencio.</d> looks at the empty hall.\n"
        "overall_soundscape: Quiet hall.\n"
        "non_diegetic_music: N/A"
    )
    native = apply_h3_audio_policy(tagged, "native")
    legacy = apply_h3_audio_policy(tagged, "legacy")
    assert "<d>[Spanish] Qué silencio.</d>" in native
    assert "<d>[Spanish] Qué silencio.</d>" in legacy
    mute = "A silent moonlit cave. Nadie habla."
    assert requests_silence(mute)
    assert extract_locked_lines(mute) == []


def test_incompatible_mute_order_does_not_erase_quoted_dialogue():
    source = 'Ana dice "Qué silencio." Nadie habla.'
    locked = extract_locked_lines(source)
    assert locked[0]["text"] == "Qué silencio."
    assert requests_silence(source)
    # Quoted speech stays the authority; mute prose is not a script.
    assert locked


def test_creative_transport_keeps_llm_extra_line_not_a_canned_sentence():
    user = 'Alice says "Hello." Add a short reply from Bob.'
    extra = "Wait for me at the door."
    assert extra not in LLM_SERVICE.read_text(encoding="utf-8")
    assert extra not in writing_contract("creative")

    def fake_generate(prompt="", system_prompt="", **kwargs):
        if "additional spoken line" in str(system_prompt):
            return f"Bob (S2): <d>[English] {extra}</d>"
        return (
            "integrated_multimodal_description: [Shot 1] Alice (S1) "
            "<d>[English] Hello.</d> nods.\n"
            "overall_soundscape: Quiet room.\n"
            "non_diegetic_music: N/A"
        )

    with patch.object(llm_service, "generate", side_effect=fake_generate):
        creative = llm_service.enhance_prompt(
            user,
            mode="video",
            model_type="minimax_h3",
            planning_style="creative",
            h3_audio_policy="native",
            duration_seconds=10,
        )
        faithful = llm_service.enhance_prompt(
            user,
            mode="video",
            model_type="minimax_h3",
            planning_style="faithful",
            h3_audio_policy="native",
            duration_seconds=10,
        )
        only_these = llm_service.enhance_prompt(
            'Alice says "Hello." Only these lines.',
            mode="video",
            model_type="minimax_h3",
            planning_style="creative",
            h3_audio_policy="native",
            duration_seconds=10,
        )
    assert "<d>[English] Hello.</d>" in creative
    assert extra in creative
    assert "Bob (S2)" in creative
    assert extra not in faithful
    assert extra not in only_these
    assert requests_only_supplied_lines('Alice says "Hello." Only these lines.')


def test_creative_does_not_invent_an_extra_line_when_llm_returns_none():
    user = 'Alice says "Hello." Add a short reply from Bob.'

    def fake_generate(prompt="", system_prompt="", **kwargs):
        return (
            "integrated_multimodal_description: [Shot 1] Alice (S1) "
            "<d>[English] Hello.</d> nods.\n"
            "overall_soundscape: Quiet room.\n"
            "non_diegetic_music: N/A"
        )

    with patch.object(llm_service, "generate", side_effect=fake_generate):
        result = llm_service.enhance_prompt(
            user,
            mode="video",
            model_type="minimax_h3",
            planning_style="creative",
            h3_audio_policy="native",
            duration_seconds=10,
        )
    assert "<d>[English] Hello.</d>" in result
    assert result.count("<d>") == 1


@pytest.mark.skipif(not os.environ.get("HOCUS_LIVE_LLM"), reason="optional live LLM check")
def test_live_llm_creative_extra_line_is_not_the_simulated_transport():
    user = 'Alice says "Hello." Add a short reply from Bob.'
    result = llm_service.enhance_prompt(
        user,
        mode="video",
        model_type="minimax_h3",
        planning_style="creative",
        h3_audio_policy="native",
        duration_seconds=10,
    )
    blocks = llm_service._extract_h3_dialogue_blocks(result)
    assert "Hello." in blocks
    assert any(block != "Hello." for block in blocks)
