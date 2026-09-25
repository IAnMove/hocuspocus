"""Prompt-enhancer markdown guides used by Scenema and DramaBox."""
from __future__ import annotations

from services.guide_loader import load_guide


def test_dramabox_prompt_enhancer_guides_are_present():
    speech = load_guide("prompt_enhancer", "dramabox_speech_rules")
    dialogue = load_guide("prompt_enhancer", "dramabox_dialogue_rules")
    assert "double quotes" in speech.lower()
    assert "[delivery cue]" in speech or "[]" in speech
    assert speech.startswith("# DramaBox Speech")
    assert "Speaker N:" in dialogue or "Speaker 1:" in dialogue
    assert "[delivery cue]" in dialogue
    assert dialogue.startswith("# DramaBox Dialogue")


def test_scenema_prompt_enhancer_guides_are_present():
    speech = load_guide("prompt_enhancer", "scenema_speech_rules")
    dialogue = load_guide("prompt_enhancer", "scenema_dialogue_rules")
    assert speech.startswith("# Scenema Speech")
    assert dialogue.startswith("# Scenema Dialogue")
    assert "[delivery cue]" in speech
    assert "Speaker 1" in dialogue
