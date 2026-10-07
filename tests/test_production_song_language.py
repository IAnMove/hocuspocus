"""The production sings and transcribes in the song's language, and draws with Qwen Image 2.1 by default."""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from services import song_analysis
from services.lyrics_language import detect_language
from services.music_production import Production, ProductionError, validate_spec
from services.production_image_defaults import image_choice, model_image_steps
from services.production_song import song_language

SPANISH = "[Verse]\nSubió ligera al tejado\ncon su cometa de papel\n[Chorus]\nmientras quede una luz en la noche"
ENGLISH = "[Verse]\nI had a story stuck inside my head\n[Chorus]\nHocus pocus, make it move with the night"


def _sing(tmp_path: Path, monkeypatch, **song) -> tuple[list, list]:
    """Run the song stage with one seed; return the music params sent and the languages given to analysis."""
    calls, analyzed = [], []

    def mcp(tool: str, arguments: dict) -> dict:
        assert tool == "generation.music"
        calls.append(arguments["input"]["params"])
        return {"receipt": {"result": {"job_id": str(arguments["input"]["params"]["seed"])}}}

    def analyze(path, lyrics, out_dir=None, language=None):
        analyzed.append(language)
        return {"recall": 0.9, "tail_rms": 0.01, "score_file": Path(path).stem + ".score.json"}

    monkeypatch.setattr("services.production_song.audio_analysis.analyze", analyze)
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.wait = lambda jobs, poll=6: {key: f"song-{key}.wav" for key in jobs}
    production.song({"song": {"caption": "ballad", "duration": 30, "bpm": 72, "seeds": [11], **song}})
    return calls, analyzed


@pytest.mark.parametrize("declared", ["es", "Spanish", "español"])
def test_declared_spanish_reaches_the_music_model_and_the_transcription(tmp_path, monkeypatch, declared):
    calls, analyzed = _sing(tmp_path, monkeypatch, lyrics=SPANISH, language=declared)
    assert calls[0]["lyrics_language"] == "es"
    assert calls[0]["custom_settings"]["language"] == "es"
    assert analyzed == ["es"]


def test_spanish_lyrics_without_a_language_are_detected(tmp_path, monkeypatch):
    calls, analyzed = _sing(tmp_path, monkeypatch, lyrics=SPANISH)
    assert calls[0]["lyrics_language"] == "es"
    assert calls[0]["custom_settings"]["language"] == "es"
    assert analyzed == ["es"]


def test_english_lyrics_send_english(tmp_path, monkeypatch):
    calls, analyzed = _sing(tmp_path, monkeypatch, lyrics=ENGLISH)
    assert calls[0]["lyrics_language"] == "en"
    assert calls[0]["custom_settings"]["language"] == "en"
    assert analyzed == ["en"]


def test_lyrics_that_cannot_tell_sing_english_and_let_whisper_detect(tmp_path, monkeypatch):
    calls, analyzed = _sing(tmp_path, monkeypatch, lyrics="[Chorus]\nLa la la\nLa la la")
    assert calls[0]["lyrics_language"] == "en"
    assert analyzed == [None]


def test_minimax_music3_gets_the_language_and_no_ace_settings(tmp_path, monkeypatch):
    calls, _ = _sing(tmp_path, monkeypatch, lyrics=SPANISH, model="minimax_music3")
    assert calls[0]["lyrics_language"] == "es"
    assert "custom_settings" not in calls[0]       # the model declares none: any would be refused before the GPU


def test_an_unknown_language_name_is_an_invalid_spec():
    spec = {"title": "t", "song": {"lyrics": SPANISH, "caption": "c", "duration": 30, "bpm": 72, "language": "klingon"},
            "style": {}, "shots": [{"key": "s0", "kind": "still", "t0": 0, "still": "k"}]}
    with pytest.raises(ProductionError) as caught:
        validate_spec(spec)
    assert caught.value.code == "invalid_spec"
    spec["song"]["language"] = "Español"
    assert validate_spec(spec)["song"]["language"] == "Español"
    assert song_language(spec["song"]) == "es"


def test_detection_counts_distinct_words_and_spanish_marks():
    assert detect_language(SPANISH) == "es"
    assert detect_language(ENGLISH) == "en"
    assert detect_language("¿Dónde estás?") == "es"
    assert detect_language("la la la la la, the night is yours") == "en"
    assert detect_language("[Instrumental]") == ""
    assert detect_language("夜の歌 and the night") == ""


def test_spanish_language_reaches_the_whisper_call(tmp_path, monkeypatch):
    seen = {}

    class Model:
        def __init__(self, path, **kwargs):
            pass

        def transcribe(self, audio, **kwargs):
            seen.update(kwargs)
            word = SimpleNamespace(start=0.5, end=0.9, word=" Subió")
            return iter([SimpleNamespace(words=[word])]), None

    whisper = ModuleType("faster_whisper")
    whisper.WhisperModel = Model
    librosa = ModuleType("librosa")
    librosa.load = lambda path, sr=None, mono=True: (np.zeros(sr * 6, dtype=np.float32), sr)
    librosa.onset = SimpleNamespace(onset_strength=lambda y, sr, hop_length: np.zeros(64))
    librosa.times_like = lambda onset, sr, hop_length: np.linspace(0, 6, len(onset))
    monkeypatch.setitem(sys.modules, "faster_whisper", whisper)
    monkeypatch.setitem(sys.modules, "librosa", librosa)
    snapshot = tmp_path / "whisper" / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    monkeypatch.setattr(song_analysis, "CKPTS", tmp_path)
    monkeypatch.setattr(song_analysis, "tempo_grid", lambda *args, **kwargs: (72.0, 0.0))
    monkeypatch.setattr(song_analysis, "_separate_vocals", lambda song, out_dir: str(tmp_path / "song.vocals.wav"))

    score = song_analysis.analyze(str(tmp_path / "song.wav"), SPANISH, out_dir=str(tmp_path), language="es")
    assert seen["language"] == "es"
    assert score["lines"][0]["words"][0]["w"] == "Subió"
    song_analysis.analyze(str(tmp_path / "song.wav"), SPANISH, out_dir=str(tmp_path))
    assert seen["language"] is None                 # unknown: Whisper detects instead of hearing English


def test_accented_words_still_match_what_whisper_wrote():
    lines, recall = song_analysis.align_lines(["Dormía la niña"], [[1.0, 1.4, "dormia"], [1.4, 1.6, "la"], [1.6, 2.0, "nina"]])
    assert recall == 1.0
    assert [word["t0"] for word in lines[0]["words"]] == [1.0, 1.4, 1.6]


def test_default_image_model_is_qwen_with_its_own_steps(monkeypatch):
    from services import production_image_defaults as defaults
    monkeypatch.setattr(defaults, "default_image_model", lambda: "qwen_image_21")
    spec = {"title": "t", "song": {"lyrics": ENGLISH, "caption": "c", "duration": 30, "bpm": 72},
            "style": {}, "shots": [{"key": "s0", "kind": "still", "t0": 0, "still": "k"}]}
    assert validate_spec(spec)["style"] == {"image_model": "qwen_image_21", "image_steps": 40}
    assert model_image_steps("qwen_image_21") == 40
    assert model_image_steps("flux2_klein_9b") == 4
    assert model_image_steps("qwen_image_21_viggle_turbo") == 6
    assert model_image_steps("../defaults/qwen_image_21") is None


def test_flux_stays_selectable_at_its_own_steps(monkeypatch):
    from services import production_image_defaults as defaults
    monkeypatch.setattr(defaults, "default_image_model", lambda: "qwen_image_21")
    spec = {"title": "t", "song": {"lyrics": ENGLISH, "caption": "c", "duration": 30, "bpm": 72},
            "style": {"preset": "riso-zine", "image_model": "flux2_klein_9b"},
            "shots": [{"key": "s0", "kind": "still", "t0": 0, "still": "k"}]}
    assert validate_spec(spec)["style"]["image_steps"] == 4          # not the Qwen preset's 40
    style = {"image_model": "qwen_image_21", "image_steps": 28}
    assert image_choice({}, style) == ("qwen_image_21", 28)
    assert image_choice({"image_model": "flux2_klein_9b"}, style) == ("flux2_klein_9b", None)
    assert image_choice({"image_model": "qwen_image_21"}, style) == ("qwen_image_21", 28)
    assert image_choice({}, {}) == ("qwen_image_21", None)


def test_unset_image_model_draws_with_qwen_at_forty_steps(tmp_path):
    sent = []
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path),
                            mcp=lambda tool, arguments: sent.append(arguments["input"]["params"]) or {})
    production.image("k", "a prompt", None, "1280x704", 1)
    production.image("f", "a prompt", None, "1280x704", 1, "flux2_klein_9b")
    assert (sent[0]["model_type"], sent[0]["num_inference_steps"]) == ("qwen_image_21", 40)
    assert (sent[1]["model_type"], sent[1]["num_inference_steps"]) == ("flux2_klein_9b", 4)


def test_preview_without_a_model_uses_the_run_default(tmp_path, monkeypatch):
    from services import production_stage_frames
    monkeypatch.setattr(production_stage_frames, "default_image_model", lambda: "qwen_image_21_gguf_q4_k")
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    models = []
    production.image = lambda key, prompt, refs, res, seed, model, steps=None, attempt=0: models.append((model, steps)) or key
    production.wait = lambda jobs: {key: f"{key}.png" for key in jobs}
    production.upload = lambda name: (name, "/u/" + name)
    production.preview({"prompts": ["one", "two", "three"]})
    assert models == [("qwen_image_21_gguf_q4_k", None)] * 3


def test_every_frame_is_drawn_before_the_first_clip(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    order = []
    production.song = lambda spec: order.append("song")
    production.analyze = lambda spec: order.append("analyze")
    production.cast = lambda spec: order.append("cast")
    production.frames = lambda spec, windows: order.extend(f"frame:{w['key']}" for w in windows if w["kind"] == "h3")
    production.clips = lambda spec, windows, retake=(): order.extend(f"clip:{w['key']}" for w in windows if w["kind"] == "h3")
    production.scenes = lambda spec, windows: order.append("scenes")
    production.package = lambda spec, windows: None
    production.montage = lambda spec: order.append("montage")
    production.score = lambda: {"duration": 30, "beat": 0.5, "lines": [{"t0": 1, "t1": 3}, {"t0": 10, "t1": 12}, {"t0": 20, "t1": 22}]}
    spec = {"title": "t", "song": {"lyrics": "a\nb\nc", "caption": "c", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": f"s{i}", "kind": "h3", "line": i, "frame": "f", "action": "a"} for i in range(3)]}
    production.run(spec)
    frames = [i for i, step in enumerate(order) if step.startswith(("cast", "frame:"))]
    clips = [i for i, step in enumerate(order) if step.startswith("clip:")]
    assert len(frames) == 4 and len(clips) == 3
    assert max(frames) < min(clips)
