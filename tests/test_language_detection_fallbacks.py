"""Spanish text gets Spanish where code used to assume English; explicit languages still win."""
from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace

import numpy as np
import pytest

from services.game_generators.audio import line_voice  # before game_tools: the package import order avoids a cycle
from services import game_tools, phoneme_analysis, phoneme_runtime, scene3d_speech, speech_alignment, speech_qa
from services.director.h3_dialogue import h3_dialogue_tag
from services.director.spoken_language import spoken_language_of
from services.h3_window_planner import _dialogue_sentence
from tests.test_production_publication import call, publication  # noqa: F401  (pytest fixture)

SPANISH_LINE = "la vida es bella y no me importa"      # none of the H3 guess's own Spanish words


def test_shared_helper_tells_spanish_and_keeps_other_guesses():
    assert spoken_language_of(SPANISH_LINE) == "Spanish"
    assert spoken_language_of("¿Dónde estás?") == "Spanish"
    assert spoken_language_of("Clark, how did you do that?") == "English"
    assert spoken_language_of("Look out!") == "English"          # nothing tells: English stays the fallback
    assert spoken_language_of("io non sono qui") == "Italian"
    assert spoken_language_of("こんにちは") == "Japanese"


def test_untagged_h3_dialogue_is_tagged_in_its_own_language():
    assert h3_dialogue_tag(SPANISH_LINE) == f"<d>[Spanish] {SPANISH_LINE}</d>"
    assert h3_dialogue_tag("Clark, how did you do that?") == "<d>[English] Clark, how did you do that?</d>"
    assert h3_dialogue_tag(f"[French] {SPANISH_LINE}") == f"<d>[French] {SPANISH_LINE}</d>"
    assert h3_dialogue_tag(SPANISH_LINE, "Spanish (Spain)") == f"<d>[Spanish (Spain)] {SPANISH_LINE}</d>"


def test_window_planner_line_without_language_uses_its_words():
    sentence = _dialogue_sentence({"speaker": "Ana", "text": "No sé dónde está la salida"}, {})
    assert "<d>[Spanish] No sé dónde está la salida</d>" in sentence
    explicit = _dialogue_sentence({"speaker": "Ana", "text": "No sé dónde está la salida", "language": "English"}, {})
    assert "<d>[English]" in explicit


def test_game_voice_line_uses_the_kit_voice_of_its_language():
    english, spanish = {"model": "qwen3_tts_base", "referenceAudio": "en.wav"}, {"model": "qwen3_tts_base", "referenceAudio": "es.wav"}
    kit = {"voicesByLanguage": {"english": english, "spanish": spanish}}
    assert line_voice(kit, "¡Vamos, que se hace de noche!") == (spanish, "spanish")
    assert line_voice(kit, "Come on, the night is coming for you") == (english, "english")
    only_spanish = {"voicesByLanguage": {"spanish": spanish}}
    assert line_voice(only_spanish, "Vamos") == (spanish, "spanish")       # cannot tell: the kit's only language
    assert line_voice(only_spanish, "Come on, the night is coming for you") == (spanish, "english")
    assert line_voice({"voice": english}, "Hola") == (english, "english")


def test_game_music_with_spanish_lyrics_declares_spanish(monkeypatch):
    sent = []
    monkeypatch.setattr(game_tools, "_audio", lambda ctx, tool, step, params, name: sent.append(params) or name)
    game_tools.music(SimpleNamespace(asset={"id": "tema"}), "m", prompt="[Verse]\nSubió ligera al tejado con su cometa de papel",
                     alt_prompt="ballad", seconds=8, seed=1)
    game_tools.music(SimpleNamespace(asset={"id": "tema"}), "m", prompt="[Instrumental]", alt_prompt="loop", seconds=8, seed=1)
    assert sent[0]["lyrics_language"] == "es" and sent[0]["custom_settings"]["language"] == "es"
    assert sent[1]["lyrics_language"] == "en" and "language" not in sent[1]["custom_settings"]


def test_published_title_carries_the_song_language(publication):  # noqa: F811
    workspace, public, handler, arguments = publication
    import json
    state = json.loads((workspace / "test.production.json").read_text())
    state["spec"] = {"title": "La luna robada", "song": {"lyrics": "Subió ligera al tejado\ncon su cometa de papel"}}
    (workspace / "test.production.json").write_text(json.dumps(state))
    result = call(handler, {**arguments, "input": {**arguments["input"], "mode": "preview"}})
    page = next(public.glob("homage-*")).joinpath(result["page"].rsplit("/", 1)[-1]).read_text()
    assert '<html lang="en">' in page                       # the page chrome is English
    assert '<h1 lang="es">La luna robada</h1>' in page


def test_speech_alignment_without_a_language_aligns_spanish_dialogue_as_spanish(monkeypatch):
    from tests.test_scene3d_speech import wav

    @contextmanager
    def acquire(lane, **kwargs):
        yield

    seen = []
    monkeypatch.setattr(phoneme_runtime, "capabilities", lambda: {"installed": True})
    monkeypatch.setattr(speech_alignment.resource_scheduler.coordinator, "acquire", acquire)
    monkeypatch.setattr(scene3d_speech, "analyze_voice", lambda *a, **k: pytest.fail("Wrong engine"))
    monkeypatch.setattr(phoneme_analysis, "analyze_voice", lambda data, **options: seen.append(options["language"]) or {})
    speech_alignment.analyze_voice(wav(), dialogue="¿Dónde está la llave de la casa?")
    speech_alignment.analyze_voice(wav(), dialogue="¿Dónde está la llave?", language="English")
    assert seen == ["es", "en"]


def test_speech_qa_without_a_language_listens_for_the_text_language():
    heard = []
    result = speech_qa.measure_speech(
        "take.wav", "No sé dónde está la salida", "",
        load=lambda path: (np.zeros(16000, dtype=np.float32), 16000),
        transcribe=lambda audio, code: heard.append(code) or "no sé dónde está la salida",
        pitch=lambda audio, rate: None)
    assert heard == ["es"]
    assert result["wer"] == 0
