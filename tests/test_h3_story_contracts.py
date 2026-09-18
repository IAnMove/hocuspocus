"""H3 story-video prompt contracts stay on the pipeline facade."""
from __future__ import annotations

from app.services import director_pipeline
from services.director import h3_story_contracts


def test_h3_story_contract_helpers_are_reexported():
    assert director_pipeline._h3_apply_reference_contract is h3_story_contracts._h3_apply_reference_contract
    assert director_pipeline._h3_apply_identity_contract is h3_story_contracts._h3_apply_identity_contract
    assert director_pipeline._h3_apply_portrait_composition_contract is h3_story_contracts._h3_apply_portrait_composition_contract
    assert director_pipeline._h3_preserve_audio_contract is h3_story_contracts._h3_preserve_audio_contract
    assert director_pipeline._h3_format_audio_policy is h3_story_contracts._h3_format_audio_policy


def test_reference_contract_switches_first_frame_to_reference_set():
    first = director_pipeline._h3_apply_reference_contract(
        "Use the supplied image as the exact first frame. Alice walks.",
        "first_frame",
    )
    refs = director_pipeline._h3_apply_reference_contract(first, "references")
    assert "exact first frame" in first.casefold()
    assert "compose a new opening frame" in refs.casefold()
    assert "exact first frame" not in refs.casefold()


def test_identity_contract_stays_before_audio_and_is_idempotent():
    prompt = director_pipeline._h3_apply_identity_contract(
        "She turns toward camera.\nAudio: quiet wind."
    )
    again = director_pipeline._h3_apply_identity_contract(prompt)
    assert prompt.index("Same faces and wardrobe throughout") < prompt.index("Audio:")
    assert prompt.endswith("Audio: quiet wind.")
    assert again == prompt


def test_portrait_lock_sits_before_soundscape_and_skips_landscape():
    locked = director_pipeline._h3_apply_portrait_composition_contract(
        "Alice nods.\n\noverall_soundscape: room tone\nnon_diegetic_music: N/A",
        "768x1280",
    )
    assert "PORTRAIT COMPOSITION LOCK:" in locked
    assert locked.index("PORTRAIT COMPOSITION LOCK:") < locked.index("overall_soundscape:")
    wide = director_pipeline._h3_apply_portrait_composition_contract("Alice nods.", "1280x768")
    assert "PORTRAIT COMPOSITION LOCK:" not in wide


def test_preserve_audio_keeps_draft_soundscape_and_quoted_speech_is_untouched():
    draft = (
        'Alice walks. <d>[English] Hello.</d>\n'
        "overall_soundscape: Quiet room.\nnon_diegetic_music: N/A"
    )
    candidate = (
        "Alice sprints. <d>[English] Hello.</d>\n"
        "overall_soundscape: LOUD TRAFFIC.\nnon_diegetic_music: drums"
    )
    kept = director_pipeline._h3_preserve_audio_contract(candidate, draft)
    assert "Quiet room." in kept
    assert "LOUD TRAFFIC" not in kept
    assert "<d>[English] Hello.</d>" in kept
    assert director_pipeline._h3_format_audio_policy(
        {"minimax_h3_audio_policy": "legacy"},
    ) == "legacy"
