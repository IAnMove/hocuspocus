"""A character can speak each language with its own voice; lip sync gets language codes, not labels."""
import pytest

from app.services.character_kit_library import patch_character_kit, read_character_kit_library
from app.services.character_speech_definition import normalize_character_voices_by_language
from app.services.speech_language import speech_language_code


def reference(language, name="Kevin"):
    return {"provider": "local", "model": "qwen3_tts_base", "voiceId": "reference", "name": name,
            "referenceAudio": "/api/v1/file/kevin.wav?workspace=series", "transcript": "Vale, vale.", "language": language}


PRESET = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan", "instructions": "Nervous"}


def kit(**extra):
    return {"version": 1, "id": "kevin", "name": "Kevin", "style": "cutout", "poses": {}, "mouth": {}, "eyes": {},
            "anchors": {}, "provenance": [], "voice": PRESET, **extra}


def test_language_voices_survive_a_library_round_trip(tmp_path):
    voices = {"english": PRESET, "spanish": reference("spanish")}
    patch_character_kit(str(tmp_path), "kevin", kit(voicesByLanguage=voices), base_revision=0)
    saved = read_character_kit_library(str(tmp_path))["kits"]["kevin"]
    assert saved["voice"] == PRESET
    assert saved["voicesByLanguage"] == voices


def test_an_empty_language_map_is_not_stored(tmp_path):
    patch_character_kit(str(tmp_path), "kevin", kit(voicesByLanguage={}), base_revision=0)
    assert "voicesByLanguage" not in read_character_kit_library(str(tmp_path))["kits"]["kevin"]


def test_a_reference_voice_may_be_automatic_or_match_its_language():
    voices = {"spanish": reference("auto"), "english": reference("english")}
    assert normalize_character_voices_by_language(voices) == voices


@pytest.mark.parametrize("voices", [
    {"klingon": PRESET},
    {"auto": PRESET},
    {"spanish": reference("english")},
    {"spanish": {**PRESET, "apiKey": "never"}},
    ["spanish"],
])
def test_unknown_languages_and_mismatched_references_are_rejected(voices):
    with pytest.raises(ValueError):
        normalize_character_voices_by_language(voices)


@pytest.mark.parametrize("label, code", [
    ("Español", "es"), ("Español de España", "es"), ("castellano", "es"), ("English", "en"), ("English (US)", "en"),
    ("spanish", "es"), ("Français", "fr"), ("chino", "cmn"), ("es", "es"), ("en-gb", "en-gb"), ("pt-BR", "pt-BR"),
    ("", ""), ("Klingon", "Klingon"),
])
def test_language_labels_become_analysis_codes(label, code):
    assert speech_language_code(label) == code


def test_shared_analysis_hands_espeak_a_code_for_a_series_label(monkeypatch):
    from contextlib import contextmanager
    from services import phoneme_analysis, phoneme_runtime, speech_alignment
    from tests.test_scene3d_speech import wav

    @contextmanager
    def acquire(lane, **kwargs):
        yield

    seen = []
    monkeypatch.setattr(phoneme_runtime, "capabilities", lambda: {"installed": True})
    monkeypatch.setattr(speech_alignment.resource_scheduler.coordinator, "acquire", acquire)
    monkeypatch.setattr(phoneme_analysis, "analyze_voice", lambda *a, **k: seen.append(k["language"]) or {"mouthCues": []})
    speech_alignment.analyze_voice(wav(), language="Español")
    assert seen == ["es"]
