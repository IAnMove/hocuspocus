from services.director.h3_dialogue import compile_h3_official_prompt
from services.director.spoken_language import (
    apply_spoken_language_to_plans,
    append_spoken_language_contract,
    extract_spoken_language,
    h3_language_tag,
    infer_h3_spoken_language,
    spoken_language_contract,
)


def test_spain_spanish_contract_is_explicit_and_extractable():
    contract = spoken_language_contract("Español de España")
    assert "native Spain/Castilian accent" in contract
    assert "Italian" in contract
    assert extract_spoken_language(contract) == "Español de España"
    assert h3_language_tag("Español de España") == "Spanish"


def test_contract_append_is_idempotent():
    once = append_spoken_language_contract("A woman speaks.", "Español de España")
    twice = append_spoken_language_contract(once, "Español de España")
    assert once == twice
    assert twice.count("SPOKEN LANGUAGE CONTRACT") == 1


def test_h3_forces_broad_language_tag_but_keeps_regional_contract():
    prompt, _ = compile_h3_official_prompt(
        "A woman says hello.",
        [{"character_id": "ada", "speaker_name": "Ada"}],
        [{"speaker_id": "ada", "spoken_text": "Hola, qué alegría verte."}],
        project_context=spoken_language_contract("Español de España"),
        audio_plan={"spoken_language": "Español de España"},
    )
    assert "<d>[Spanish] Hola, qué alegría verte.</d>" in prompt
    assert "[English]" not in prompt


def test_h3_preserves_authored_spanish_tag_without_global_contract():
    prompt, _ = compile_h3_official_prompt(
        "Ada says: <d>[Spanish] Nadie volvió a verlo.</d>",
        [{"character_id": "ada", "speaker_name": "Ada"}],
        [{"speaker_id": "ada", "spoken_text": "Nadie volvió a verlo."}],
        duration_seconds=5.167,
    )
    assert "<d>[Spanish] Nadie volvió a verlo.</d>" in prompt
    assert "[English]" not in prompt


def test_h3_language_inference_uses_broad_tags_only_when_tag_is_missing():
    assert infer_h3_spoken_language("¿Dónde está la puerta?") == "Spanish"
    assert infer_h3_spoken_language("Je ne suis pas ici.") == "French"
    assert infer_h3_spoken_language("日本語です") == "Japanese"


def test_reapplying_language_does_not_wrap_an_already_compiled_h3_prompt():
    plan = {
        "video_prompt": "integrated_multimodal_description: compiled",
        "_director_h3_source_prompt": "Ada speaks.",
        "_director_h3_compiled_prompt": "integrated_multimodal_description: compiled",
        "_director_dialogue_beats": [{
            "speaker_id": "ada",
            "spoken_text": "Hola.",
        }],
    }
    apply_spoken_language_to_plans([plan], "Español de España")
    assert plan["video_prompt"] == "integrated_multimodal_description: compiled"
    assert plan["_director_h3_source_prompt"].startswith("SPOKEN LANGUAGE CONTRACT")


def test_silent_h3_clip_does_not_receive_a_spoken_language_contract():
    contract = spoken_language_contract("Español de España")
    plan = {
        "video_prompt": "integrated_multimodal_description: compiled",
        "_director_h3_source_prompt": f"{contract}\nA silent moonlit cave.",
        "_director_dialogue_beats": [],
        "_director_audio_plan": {"mode": "music_driven"},
    }
    apply_spoken_language_to_plans([plan], "Español de España")
    assert "SPOKEN LANGUAGE CONTRACT" not in plan["_director_h3_source_prompt"]
    assert plan["_director_h3_source_prompt"] == "A silent moonlit cave."
    assert "spoken_language" not in plan["_director_audio_plan"]
