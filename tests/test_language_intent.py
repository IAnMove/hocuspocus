"""Language intent remains canonical at backend persistence boundaries."""

import copy

from services.language_intent import normalize_language_intent
from services.series_library import (
    create_series_project,
    normalize_series_project,
    series_canon_inputs_changed,
)
from services.story_library import normalize_story_library


def test_normalizer_accepts_llm_and_persisted_shapes_without_ui_locale():
    llm = normalize_language_intent({
        "conversation_language": "fr",
        "content_language": "English",
        "spoken_language": "Español",
        "technical_prompt_language": "en",
        "verbatim_segments": [{
            "kind": "dialogue", "text": "¡Hola!", "language": "es", "speaker": "Ada"
        }],
    })
    assert llm == {
        "conversationLanguage": "fr",
        "contentLanguage": "English",
        "spokenLanguage": "Español",
        "technicalPromptLanguage": "en",
        "verbatimSegments": [{
            "kind": "dialogue", "text": "¡Hola!", "language": "es", "speaker": "Ada"
        }],
    }
    assert normalize_language_intent(llm) == llm
    assert "interfaceLanguage" not in llm


def test_normalizer_preserves_literal_spacing_character_for_character():
    normalized = normalize_language_intent({
        "verbatim_segments": [{
            "kind": "dialogue", "text": "  exact spacing  ", "language": "en",
        }],
    })
    assert normalized["verbatimSegments"][0]["text"] == "  exact spacing  "


def test_story_library_migrates_legacy_language_fields_durably():
    library = normalize_story_library({
        "revision": 0,
        "activeId": "story-1",
        "projects": {"story-1": {
            "id": "story-1", "language": "Italiano", "spokenLanguage": "Italiano"
        }},
    })
    intent = library["projects"]["story-1"]["languageIntent"]
    assert intent["contentLanguage"] == "Italiano"
    assert intent["spokenLanguage"] == "Italiano"
    assert intent["technicalPromptLanguage"] == "en"


def test_series_creation_and_normalization_always_return_language_intent():
    created = create_series_project()
    assert created["language"] == "English"
    assert created["spokenLanguage"] == "English"
    assert created["languageIntent"]["contentLanguage"] == "English"
    spanish = create_series_project(language="es")
    assert spanish["language"] == "Español"
    assert spanish["spokenLanguage"] == "Español de España"
    assert created["languageIntent"]["technicalPromptLanguage"] == "en"
    created["languageIntent"] = {
        "content_language": "Deutsch",
        "spoken_language": "Español",
        "verbatim_segments": [{"kind": "dialogue", "text": "hola", "language": "es"}],
    }
    normalized = normalize_series_project(created, created["id"], "default")
    assert normalized["languageIntent"]["contentLanguage"] == "Deutsch"
    assert normalized["languageIntent"]["verbatimSegments"][0]["text"] == "hola"
    kept = dict(created)
    kept["language"] = "Español"
    kept["spokenLanguage"] = "Español de España"
    kept_normalized = normalize_series_project(kept, kept["id"], "default")
    assert kept_normalized["language"] == "Español"
    assert kept_normalized["spokenLanguage"] == "Español de España"
    missing = dict(created)
    missing.pop("language")
    missing.pop("spokenLanguage")
    missing.pop("languageIntent")
    filled = normalize_series_project(missing, missing["id"], "default")
    assert filled["language"] == "English"
    assert filled["spokenLanguage"] == "English"
    from_intent = dict(created)
    from_intent.pop("language")
    from_intent.pop("spokenLanguage")
    from_intent["languageIntent"] = {"contentLanguage": "Español", "spokenLanguage": "Español de España"}
    recovered = normalize_series_project(from_intent, from_intent["id"], "default")
    assert recovered["language"] == "Español", "a saved intent is kept instead of flipping to English"
    assert recovered["spokenLanguage"] == "Español de España"
    assert recovered["languageIntent"]["contentLanguage"] == "Español"


def test_series_canon_tracks_production_language_but_not_chat_language():
    current = create_series_project()
    updated = copy.deepcopy(current)
    updated["languageIntent"]["conversationLanguage"] = "fr"
    assert series_canon_inputs_changed(current, updated) is False

    updated["languageIntent"]["verbatimSegments"] = [
        {"kind": "dialogue", "text": "¡Hola!", "language": "es"}
    ]
    assert series_canon_inputs_changed(current, updated) is True

    updated = copy.deepcopy(current)
    updated["languageIntent"]["technicalPromptLanguage"] = "auto"
    assert series_canon_inputs_changed(current, updated) is True
