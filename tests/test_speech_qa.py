"""A spoken take is measured against its text: transcript, error rate, pitch, pace and silence."""
import asyncio
import io
import re
import wave

import numpy as np
import pytest
from fastapi import HTTPException

from services.qa_accent import command_catalog as accent_catalog, command_handlers as accent_handlers, score_accent, tag_sites
from services.speech_qa import command_catalog, command_handlers, measure_speech, word_error_rate, words
from services.speech_text_es import dictionary_map, merge_names, phonetic_es, pronounce, token_error_rate, wer_threshold
from services.voice_pitch import inferred_range, pitch_notice, range_for, voice_checks


def test_numbers_accents_and_punctuation_do_not_count_as_errors():
    assert word_error_rate("Tenemos un 97% de éxito.", "tenemos un noventa y siete por ciento de exito", "es") == 0
    assert word_error_rate("We raised $40 million!", "we raised forty million", "en") == 0
    assert words("Self-driving, 2 cars", "en") == ["self", "driving", "two", "cars"]
    assert word_error_rate("one two three four", "one three four five", "en") == 0.5


def _stub_audio(seconds=4.0, lead=0.3, trail=0.2, rate=16000):
    audio = np.zeros(int(seconds * rate), dtype=np.float32)
    audio[int(lead * rate):int((seconds - trail) * rate)] = 0.2
    return audio, rate


def test_a_take_is_measured_and_warned_about_without_blocking():
    clean = measure_speech("take.wav", "This is fine, we have a product.", "English",
                           load=lambda _path: _stub_audio(), transcribe=lambda _audio, code: "This is fine. We have a product.",
                           pitch=lambda _audio, _rate: 120.0, pitch_range=[85, 165])
    assert clean["wer"] == 0 and clean["warnings"] == []
    assert (clean["leadSilence"], clean["trailSilence"], clean["duration"]) == (0.3, 0.2, 4.0)
    assert clean["wordsPerSecond"] == pytest.approx(7 / 3.5, abs=0.01)

    seen = {}
    off = measure_speech("take.wav", "This is fine, we have a product.", "Español de España",
                         load=lambda _path: _stub_audio(lead=1.0), transcribe=lambda _audio, code: seen.setdefault("code", code) and "This is",
                         pitch=lambda _audio, _rate: 230.0, pitch_range=[85, 165])
    assert seen["code"] == "es"
    assert len(off["warnings"]) == 3 and off["wer"] > 0.5
    assert any("230 Hz" in warning for warning in off["warnings"])


def test_the_mcp_tool_reads_workspace_files_only(tmp_path, monkeypatch):
    (tmp_path / "ws").mkdir()
    (tmp_path / "ws" / "take.wav").write_bytes(b"not decoded in this test")
    (tmp_path / "secret.wav").write_bytes(b"x")
    monkeypatch.setattr("services.speech_qa.measure_speech",
                        lambda path, text, language, pitch_range=None, names=None: {
                            "path": path, "text": text, "language": language, "range": pitch_range, "names": names})
    handle = command_handlers(lambda name: str(tmp_path / name))["qa.speech"]
    result = asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "/api/v1/file/take.wav?workspace=ws",
                                                         "text": "Hola.", "language": "es", "pitch_range": [80, 170]}}))
    assert result["result"]["path"].endswith("take.wav") and result["result"]["range"] == [80, 170]
    with pytest.raises(HTTPException) as error:
        asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "../secret.wav", "text": "x"}}))
    assert error.value.status_code == 404
    assert command_catalog()[0]["mutation"] is False
    named = asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "take.wav", "text": "Hola.", "names": ["Bilbao"]}}))
    assert named["result"]["names"] == ["Bilbao"]
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "take.wav", "text": "Hola.", "names": "Bilbao"}}))
    assert rejected.value.status_code == 422


def test_spanish_phonetics_names_short_lines_and_the_spoken_dictionary():
    assert phonetic_es("Vilbao") == phonetic_es("Bilbao") == "bilbao"
    assert phonetic_es("Ávila") == phonetic_es("Abila") == "abila"
    assert phonetic_es("Zaragoza") == phonetic_es("Saragosa") == "saragosa"
    assert phonetic_es("acción") == "acsion" and phonetic_es("que") == "ke" and phonetic_es("noche") == "noche"
    assert phonetic_es("llave") == "yabe"
    names = ["San Sebastián"]
    assert token_error_rate(merge_names(words("San Sebastián", "es"), names),
                            merge_names(words("San Sebas Tián", "es"), names)) == 0
    short = measure_speech("take.wav", "norte claro", "es", pitch_range=[85, 165],
                           load=lambda _path: _stub_audio(seconds=1.2, lead=0.1, trail=0.1),
                           transcribe=lambda _audio, _code: "norte oscuro", pitch=lambda _audio, _rate: 120.0)
    assert (short["wer"], short["wer_raw"], short["wer_threshold"]) == (0.5, 0.5, 0.5)
    assert short["warnings"] == []
    spoken = measure_speech("take.wav", "El Pejó espera.", "es",
                            load=lambda _path: _stub_audio(seconds=2.0, lead=0.1, trail=0.1),
                            transcribe=lambda _audio, _code: "el pejo espera", pitch=lambda _audio, _rate: 120.0)
    assert spoken["wer"] == 0 and spoken["wer"] <= spoken["wer_threshold"]
    assert pronounce("El Peugeot espera.", {"Peugeot": "Pejó"}) == "El Pejó espera."
    assert pronounce("El Peugeot espera.", "Peugeot: Pejó") == "El Pejó espera."
    assert pronounce("Peugeots", {"Peugeot": "Pejó"}) == "Peugeots"
    assert dictionary_map("Peugeot=Pejó") == {"Peugeot": "Pejó"}


def _heard_es(text: str, transcript: str, names: list[str] | None = None) -> dict:
    seconds = 0.2 + len(words(text, "es")) / 2.5  # a normal pace, so only the words can warn
    return measure_speech("take.wav", text, "es", names=names, load=lambda _path: _stub_audio(seconds=seconds, lead=0.1, trail=0.1),
                          transcribe=lambda _audio, _code: transcript, pitch=lambda _audio, _rate: 120.0)


def test_a_short_name_is_not_matched_to_an_ordinary_word():
    names = ["Ana", "Sol", "San Sebastián"]
    misheard = _heard_es("Ana viene con Sol", "una viene con son", names)
    assert misheard["wer"] == 0.5 > misheard["wer_threshold"] and misheard["warnings"]
    assert _heard_es("Ana viene con Sol", "ana viene con sol", names)["wer"] == 0
    # A longer name still takes a near miss, and a short one still joins split words.
    assert merge_names(words("San Sebas Tián", "es"), names) == merge_names(words("San Sebastián", "es"), names)
    assert merge_names(["a", "na"], names) == ["ana"]
    assert merge_names(words("vilbao", "es"), ["Bilbao"]) == ["bilbao"]


def test_a_wrong_one_word_line_is_never_accepted():
    assert [wer_threshold(count, spanish=True) for count in (1, 2, 3, 4, 5)] == [0.5, 0.5, pytest.approx(1 / 3), 0.25, 0.15]
    wrong = _heard_es("Adiós.", "hola")
    assert (wrong["wer"], wrong["wer_threshold"]) == (1.0, 0.5) and wrong["warnings"]
    assert _heard_es("Adiós.", "adios")["warnings"] == []
    half = _heard_es("Buenas noticias.", "buenas novicias")
    assert (half["wer"], half["wer_threshold"], half["warnings"]) == (0.5, 0.5, [])


def test_pitch_ranges_follow_the_gender_field_and_a_high_male_voice_warns():
    assert inferred_range("male") == (75.0, 175.0)
    assert inferred_range("Mujer") == (150.0, 320.0)
    assert inferred_range("A small boy") == (220.0, 400.0)
    assert inferred_range("chica joven") == (150.0, 320.0)
    assert inferred_range("a robot") is None
    # Bolívar was measured at 184 Hz and read as a man: that is outside 85–155 and only warns.
    assert pitch_notice(184, (85, 155)) == {"medianHz": 184.0, "range": [85.0, 155.0]}
    assert pitch_notice(120, (85, 155)) is None
    high = measure_speech("take.wav", "norte claro", "es", pitch_range=[85, 155],
                          load=lambda _path: _stub_audio(seconds=1.2, lead=0.1, trail=0.1),
                          transcribe=lambda _audio, _code: "norte claro", pitch=lambda _audio, _rate: 200.0)
    assert high["wer"] == 0
    assert high["pitch_out_of_range"] == {"medianHz": 200.0, "range": [85.0, 155.0]}
    assert any("200 Hz" in warning for warning in high["warnings"])


def test_the_character_description_does_not_choose_the_pitch_range():
    def checked(**character):
        series = {"characters": [{"id": "blas", **character}]}
        return voice_checks(series, {"characterId": "blas"}, {"voiceId": "ryan"}).get("pitchRange")

    # These words name someone else: a wife, a childhood.
    assert checked(voiceAndDialogue="Habla despacio", personality="Viudo, casado con una mujer de Cádiz") is None
    assert checked(personality="De niño rezaba.", voiceProfile={"accent": "castilian"}) is None
    assert checked(voiceProfile={"gender": "hombre"}, personality="casado con una mujer") == [75.0, 175.0]
    assert checked(voiceProfile={"gender": "mujer", "pitchRange": [140, 200]}) == [140.0, 200.0]
    assert range_for({"gender": "niña"}) == (220.0, 400.0) and range_for({}) is None


def test_a_200_hz_sine_is_outside_an_adult_mans_range(tmp_path):
    pytest.importorskip("librosa")
    import wave
    rate = 16000
    samples = (0.2 * np.sin(2 * np.pi * 200 * np.arange(rate) / rate) * 32767).astype(np.int16)
    path = tmp_path / "sine.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    heard = measure_speech(str(path), "norte claro", "es", pitch_range=[85, 155],
                           transcribe=lambda _audio, _code: "norte claro")
    notice = heard["pitch_out_of_range"]
    assert notice["range"] == [85.0, 155.0] and 180 <= notice["medianHz"] <= 220


def _heard(word: str, phoneme: str) -> dict:
    return {"phoneme": phoneme, "word": word}


def test_accent_counts_theta_and_is_unknown_below_three_positions(tmp_path):
    text = "Zaragoza, cerca y zapato."
    castilian = [_heard("Zaragoza", "θ"), _heard("cerca", "e"), _heard("cerca", "θ"), _heard("zapato", "θ")]
    assert score_accent(text, castilian) == {"thetaRate": 1.0, "positions": 3, "verdict": "castilian"}
    seseo = [_heard("Zaragoza", "s"), _heard("cerca", "s"), _heard("zapato", "s")]
    assert score_accent(text, seseo) == {"thetaRate": 0.0, "positions": 3, "verdict": "seseo"}
    assert score_accent("El zapato.", [_heard("zapato", "θ")])["verdict"] == "unknown"
    assert score_accent("El zapato.", [_heard("zapato", "θ")])["positions"] == 1
    (tmp_path / "ws").mkdir()
    write_wav(tmp_path / "ws" / "take.wav", rate=44100, channels=2)  # a render take is 44.1 kHz
    decoded = []

    def decode(data, _text):
        with wave.open(io.BytesIO(data)) as audio:
            decoded.append((audio.getnchannels(), audio.getframerate(), audio.getsampwidth()))
        return seseo

    handle = accent_handlers(lambda name: str(tmp_path / name), decode=decode)["qa.accent"]
    result = asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "take.wav", "text": text, "accent": "castilian"}}))
    assert result["result"]["verdict"] == "seseo" and accent_catalog()[0]["mutation"] is False
    assert decoded == [(1, 16000, 2)], "the phoneme model reads mono 16 kHz PCM only"
    with pytest.raises(HTTPException) as rejected:
        asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "take.wav", "text": text, "accent": "other"}}))
    assert rejected.value.status_code == 422
    (tmp_path / "ws" / "broken.wav").write_bytes(b"RIFFxxxx")
    with pytest.raises(HTTPException) as broken:
        asyncio.run(handle({"version": 1, "input": {"workspace": "ws", "file": "broken.wav", "text": text, "accent": "castilian"}}))
    assert broken.value.status_code == 422 and broken.value.detail["code"] == "accent_analysis_failed"


def write_wav(path, *, rate: int, channels: int, seconds: float = 1.0) -> None:
    tone = (0.2 * np.sin(2 * np.pi * 180 * np.arange(int(rate * seconds)) / rate) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(channels)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(np.repeat(tone, channels).tobytes())


# Castilian eSpeak for each word, as the forced alignment labels it.
ESPEAK_ES = {"Zaragoza": "θ a ɾ a ɣ o θ a", "cerca": "θ e ɾ k a", "y": "i", "zapato": "θ a p a t o",
             "estación": "e s t a θ j o n", "sucesos": "s u θ e s o s", "presidencia": "p ɾ e s i ð ɛ n θ j a",
             "excepción": "e k s θ e p θ j o n"}


def spoken(text: str, theta: str = "θ", lag: float = 0.02) -> tuple[list, list]:
    """The forced phones of ``text`` (with words) and the phones heard (no words, a little later).

    Each phone lasts 0.1 s. The speaker says ``theta`` where eSpeak has θ: «s» for a seseo.
    """
    aligned, heard, clock = [], [], 0.0
    for word in re.findall(r"\w+", text):
        for phone in ESPEAK_ES[word].split():
            aligned.append({"phoneme": phone, "word": word, "start": round(clock, 2), "end": round(clock + 0.1, 2)})
            heard.append({"phoneme": theta if phone == "θ" else phone, "start": round(clock + lag, 2), "end": round(clock + 0.1 + lag, 2)})
            clock += 0.1
    return aligned, heard


def test_theta_is_taken_from_its_own_letter_not_from_an_s_in_the_same_word():
    text = "estación, sucesos, presidencia"
    aligned, heard = spoken(text)
    assert score_accent(text, tag_sites(text, heard, aligned)) == {"thetaRate": 1.0, "positions": 3, "verdict": "castilian"}
    aligned, heard = spoken(text, theta="s")
    assert score_accent(text, tag_sites(text, heard, aligned)) == {"thetaRate": 0.0, "positions": 3, "verdict": "seseo"}
    # x is k s, so «excepción» has an s before its two θ.
    aligned, heard = spoken("excepción")
    assert [site["phoneme"] for site in tag_sites("excepción", heard, aligned)] == ["θ", "θ"]


def test_theta_is_taken_from_the_word_that_spells_it_not_from_a_nearby_s():
    text = "Zaragoza, cerca y zapato."
    aligned, heard = spoken(text)
    cerca = next(index for index, phone in enumerate(aligned) if phone["word"] == "cerca")
    heard[cerca] = {**heard[cerca], "phoneme": "s"}  # «cerca» said with s
    y = next(phone for phone in aligned if phone["word"] == "y")
    heard.append({"phoneme": "s", "start": y["start"], "end": y["end"]})  # an s over «y», which spells no θ
    scored = score_accent(text, tag_sites(text, heard, aligned))
    assert scored == {"thetaRate": 0.75, "positions": 4, "verdict": "castilian"}


def test_a_word_whose_phones_do_not_line_up_with_its_letters_is_left_out():
    aligned, heard = spoken("estación sucesos zapato")
    without_s = [phone for phone in aligned if not (phone["word"] == "estación" and phone["phoneme"] == "s")]
    assert [site["word"] for site in tag_sites("estación sucesos zapato", heard, without_s)] == ["sucesos", "zapato"]
