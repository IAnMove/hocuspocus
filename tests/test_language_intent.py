"""Language intent remains canonical at backend persistence boundaries."""

from pathlib import Path

from services.language_intent import normalize_language_intent
from services.series_library import create_series_project, normalize_series_project
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
    assert created["languageIntent"]["technicalPromptLanguage"] == "en"
    created["languageIntent"] = {
        "content_language": "Deutsch",
        "spoken_language": "Español",
        "verbatim_segments": [{"kind": "dialogue", "text": "hola", "language": "es"}],
    }
    normalized = normalize_series_project(created, created["id"], "default")
    assert normalized["languageIntent"]["contentLanguage"] == "Deutsch"
    assert normalized["languageIntent"]["verbatimSegments"][0]["text"] == "hola"


def test_series_save_treats_language_intent_as_a_canon_input():
    launch = Path(__file__).resolve().parents[1] / "app" / "_launch_runtime.py"
    source = launch.read_text(encoding="utf-8")
    endpoint = source.split("def put_series_project_endpoint", 1)[1]
    canon_inputs = endpoint.split("canon_inputs = (", 1)[1].split(")", 1)[0]
    assert '"languageIntent"' in canon_inputs
