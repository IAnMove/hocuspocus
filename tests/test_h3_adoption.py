"""Hocuspocus contracts for the Maestro H3 adoption, without models/providers."""
import json
from pathlib import Path

import pytest
from services.h3_story_contract import extract_locked_lines, reconcile_window_dialogue, enforce_single_dialogue, reference_window_prompt
from services.h3_prompt_policy import apply_h3_audio_policy, writing_contract
from services.h3_runtime_policy import turbo_option, normalize_h3_runtime_request, reference_context


def test_film_titles_and_visible_signs_are_not_spoken():
    source = 'Dwight from "The Office" reads a sign "EXIT". Alice says "Run!"'
    assert [x['text'] for x in extract_locked_lines(source)] == ['Run!']


@pytest.mark.parametrize('style,expected', [('faithful', ['Hello.']), ('creative', ['Hello.', 'Welcome.'])])
def test_owned_literal_dialogue_and_creative_extra(style, expected):
    plan = {'windows': [{'dialogue': [{'speaker': 'Bob', 'text': 'Hello.'}, {'speaker': 'Bob', 'text': 'Welcome.'}]}]}
    ledger = reconcile_window_dialogue(plan, 'Alice says "Hello."', style, [{'start_seconds': 0, 'end_seconds': 5}])
    assert [x['text'] for x in ledger] == expected
    assert ledger[0]['speaker'] == 'Alice'
    assert ledger[0]['locked']


def test_missing_words_recovered_without_truncation():
    plan = {'windows': [{'dialogue': []}]}
    ledger = reconcile_window_dialogue(plan, 'Alice dice "¡Ya vienen!"', 'faithful', [{'start_seconds': 0, 'end_seconds': 5}])
    assert ledger[0]['text'] == '¡Ya vienen!'
    with pytest.raises(ValueError, match='does not fit'):
        reconcile_window_dialogue(plan, 'Alice says "one two three four five six seven eight nine ten eleven"', 'faithful', [{'start_seconds': 0, 'end_seconds': 1}])


def test_silent_creative_and_single_faithful_are_enforced():
    output = 'Alice (S1): <d>[English] Hello.</d> Bob (S2): <d>[English] Extra.</d>'
    assert 'Extra.' not in enforce_single_dialogue(output, 'Alice says "Hello."', 'faithful')
    assert '<d>' not in enforce_single_dialogue(output, 'A silent scene.', 'creative')
    assert 'Extra.' in enforce_single_dialogue(output, 'Alice says "Hello."', 'creative')


def test_audio_policy_is_explicit_and_reversible():
    source = 'integrated_multimodal_description: [Shot 1] Alice walks.\noverall_soundscape: Footsteps and wind.\nnon_diegetic_music: N/A'
    assert 'Footsteps and wind' in apply_h3_audio_policy(source)
    assert 'Footsteps and wind' not in apply_h3_audio_policy(source, 'legacy')
    assert 'franchise' in writing_contract('faithful')


def test_reference_sequence_preserves_driver_intent():
    context = reference_context([{'type': 'image', 'role': 'Alice'}, {'type': 'audio', 'role': 'Alice', 'audio_intent': 'drive'}])
    compiled = reference_window_prompt('integrated_multimodal_description: [Shot 1] Alice sings.\noverall_soundscape: N/A\nnon_diegetic_music: N/A', context)
    assert '<Subject 1>' in compiled
    assert '<Audio 1>: fully_copy' in compiled
    assert 'at 0.00 seconds' not in compiled


def test_presets_filter_workflow_and_fused_recipe():
    for omni in (False, True):
        option = turbo_option({'architecture': 'minimax_h3', 'omni_reference': omni, 'minimax_h3_full_checkpoint': True})
        assert len(option['presets']) > 1
        assert all(p['workflow'] in ('all', 'ref2va' if omni else 'fl2va') for p in option['presets'])
    body = {'num_inference_steps': 4}
    normalize_h3_runtime_request(body, {'minimax_h3_fused_turbo': True})
    assert body['guidance_scale'] == 1
    assert body['override_attention'] == 'sla'
    assert body['activated_loras'] == []


def test_attention_override_is_model_scoped_and_models_discoverable():
    root = Path(__file__).resolve().parents[1]
    engine = (root / 'app/wgp.py').read_text()
    assert "resolve_model_attention(attn, model_def, attention_modes_supported)" in engine
    from services.h3_runtime_policy import resolve_model_attention
    assert resolve_model_attention("sol", {}, ["sol"]) == "sdpa"
    assert resolve_model_attention("sol", {"sol_attention": True}, ["sol"]) == "sol"
    for name in ('minimax_h3_fused_turbo', 'minimax_h3_ref2va_fused_turbo'):
        model = json.loads((root / f'app/defaults/{name}.json').read_text())
        assert model['model']['minimax_h3_fused_turbo']
        assert name in (root / 'ui/src/stores/modelVisibility.ts').read_text()


def test_native_generation_keeps_the_requested_multi_window_duration():
    from services.minimax_h3_duration import apply_h3_dialogue_duration
    params = {'prompt': 'Alice says <d>[English] Hello.</d>', 'video_length': 486}
    contract = apply_h3_dialogue_duration(params, preserve_requested=True)
    assert params['video_length'] == 486
    assert not contract['requires_split']


def test_llama_binary_release_excludes_marker_only_release():
    from services.llama_release_assets import has_binary_assets
    specs = [('llama-', 'bin-ubuntu-x64.tar.gz')]
    assert not has_binary_assets({'assets':[{'name':'nightly-tag.txt'}]}, specs)
    assert has_binary_assets({'assets':[{'name':'llama-b10819-bin-ubuntu-x64.tar.gz'}]}, specs)


def test_llama_build_parses_semantic_version_format(monkeypatch):
    import subprocess
    from types import SimpleNamespace
    from services.llm_service import _llama_server_build
    monkeypatch.setattr(subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout='version: 0.4.0-dev (build 10819, commit abc)', stderr=''))
    assert _llama_server_build('/unused') == 10819


def test_punctuation_repair_keeps_spanish_verbatim_and_named_speakers():
    from services.h3_story_contract import repair_literal_tags, tag_source_dialogue
    source = 'George Costanza, interpretado por Jason Alexander, dice: «He dejado el café para ahorrar». Jerry Seinfeld responde: «Ahora solo te falta dejar de comprar tazas». Diálogo en español de España.'
    tagged = tag_source_dialogue(source)
    assert 'George Costanza (S1)' in tagged
    assert 'Jerry Seinfeld (S2)' in tagged
    assert tagged.count('[Spanish]') == 2
    result = repair_literal_tags('<d>[English] He dejado el café para ahorrar.</d>', source)
    assert result == '<d>[Spanish] He dejado el café para ahorrar</d>'


def test_literal_speaker_binding_repairs_missing_llm_ids_without_discarding_scene():
    from services.h3_story_contract import repair_literal_tags
    source = 'Alice says "Hello." Bob replies "Welcome."'
    result = repair_literal_tags('A warmly lit room. <d>[English] Hello.</d> <d>[English] Welcome.</d>', source, bind_speakers=True)
    assert 'A warmly lit room.' in result
    assert 'Alice (S1) <d>' in result
    assert 'Bob (S2) <d>' in result
    assert repair_literal_tags(result, source, bind_speakers=True) == result
