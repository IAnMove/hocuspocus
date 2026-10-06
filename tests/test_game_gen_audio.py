"""Audio generators with synthetic WAV files. No GPU and no librosa."""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import soundfile as sf

from services.game_generators.audio import (
    JingleGenerator,
    MusicGenerator,
    SfxGenerator,
    VoiceGenerator,
    loop_warnings,
    music_seconds,
)
from services.game_generators.base import GenContext
from services.game_library import normalize_game

NOW = "2026-10-07T12:00:00Z"


def _tone(path: Path, seconds: float = 2.0, sr: int = 22050, amplitude: float = 0.2) -> None:
    count = int(seconds * sr)
    t = np.linspace(0.0, seconds, count, endpoint=False)
    sf.write(path, (amplitude * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32), sr, subtype="PCM_16")


class _Calls:
    def __init__(self, wav: Path):
        self.wav = wav
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool in {"generation.sfx", "generation.music", "generation.speech"}:
            return {"receipt": {"result": {"job_id": "job-audio"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [str(self.wav)]}
        raise AssertionError(tool)


def _ctx(tmp_path: Path, game: dict, asset: dict, fake: _Calls) -> GenContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )


def _peak_db(path: Path) -> float:
    data, _sr = sf.read(path, always_2d=False)
    peak = float(np.max(np.abs(data)))
    return 20.0 * math.log10(peak)


def _duration(path: Path) -> float:
    data, sr = sf.read(path, always_2d=False)
    return float(len(data)) / float(sr)


def test_loop_warning_thresholds():
    assert loop_warnings(0.05, 2.0) == []
    assert loop_warnings(0.05, -2.0) == []
    assert loop_warnings(0.06, 0.0) == ["loop_seam"]
    assert loop_warnings(0.0, 2.01) == ["loop_seam"]
    assert music_seconds(60, 120) == 76


def test_sfx_variants_stay_under_a_second_and_near_minus_one(tmp_path):
    source = tmp_path / "raw.wav"
    _tone(source)
    game = {"id": "bosque", "style": {"audio": {"genre": "chiptune", "sfxPeakDb": -1, "sampleRate": 48000}}, "assets": []}
    asset = {"id": "salto", "kind": "sfx", "description": "a short jump", "spec": {"variants": 3, "seconds": 0.5, "engine": "mmaudio"}}
    fake = _Calls(source)
    result = SfxGenerator().run(_ctx(tmp_path, game, asset, fake))
    folder = tmp_path / "ws"
    names = []
    for index in range(1, 4):
        path = folder / result.files[str(index)]
        names.append(path.name)
        assert path.name == f"salto-{index}.wav"
        assert _duration(path) <= 0.5
        assert abs(_peak_db(path) - (-1.0)) <= 0.1
    assert names == ["salto-1.wav", "salto-2.wav", "salto-3.wav"]
    params = [args["input"]["params"] for tool, args in fake.calls if tool == "generation.sfx"]
    assert len(params) == 3
    assert params[0]["duration_seconds"] == 1
    assert "chiptune" in params[0]["prompt"]
    assert "a short jump" in params[0]["prompt"]


def test_retro_sfx_does_not_call_a_tool(tmp_path):
    fake = _Calls(tmp_path / "unused.wav")
    game = {"id": "bosque", "style": {"audio": {"sampleRate": 48000, "sfxPeakDb": -1}}, "assets": []}
    asset = {"id": "salto", "kind": "sfx", "spec": {"variants": 1, "seconds": 0.4, "engine": "retro", "retroPreset": "jump"}}
    result = SfxGenerator().run(_ctx(tmp_path, game, asset, fake))
    assert fake.calls == []
    path = tmp_path / "ws" / result.files["1"]
    assert path.name == "salto-1.wav"
    assert _duration(path) <= 0.4
    assert abs(_peak_db(path) - (-1.0)) <= 0.1


def test_music_writes_a_loop_with_smpl_metadata(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    _tone(source, seconds=3.0, sr=44100)

    def analyze(_path, transcribe=False, **_kwargs):
        assert transcribe is False
        return {"beats": [{"time": 0.0}, {"time": 0.5}, {"time": 1.0}], "downbeats": [0.0, 1.0, 2.0]}

    def best_loop(y, _sr, _beats, _downbeats, _target, xf_beats=1):
        return 1000, int(len(y)) - 1, 0.8

    monkeypatch.setattr("services.audio_analysis.analyze", analyze)
    monkeypatch.setattr("services.game_audio.best_loop", best_loop)
    game = {"id": "bosque", "style": {"audio": {"genre": "chiptune", "instruments": "square", "bpm": [90, 140], "musicLufs": -16}}, "assets": []}
    asset = {"id": "tema", "kind": "music", "description": "forest", "spec": {"loopSeconds": 60, "bpm": 120, "mood": "calm"}}
    fake = _Calls(source)
    result = MusicGenerator().run(_ctx(tmp_path, game, asset, fake))
    wav = tmp_path / "ws" / result.files["wav"]
    assert b"smpl" in wav.read_bytes()
    assert result.metrics["loopStart"] == 0
    assert result.metrics["loopEnd"] > 0
    params = next(args["input"]["params"] for tool, args in fake.calls if tool == "generation.music")
    assert params["prompt"] == "[Instrumental]"
    assert params["duration_seconds"] == 76
    assert "seamless loopable game background music, no intro, no ending" in params["alt_prompt"]
    assert "chiptune" in params["alt_prompt"]
    assert "square" in params["alt_prompt"]
    assert "calm" in params["alt_prompt"]
    assert "forest" in params["alt_prompt"]


def test_jingle_asks_for_a_short_ending(tmp_path, monkeypatch):
    source = tmp_path / "jingle.wav"
    _tone(source, seconds=2.0, sr=44100)
    monkeypatch.setattr("services.audio_analysis.analyze", lambda *_args, **_kwargs: {"downbeats": [0.0, 1.0]})
    game = {"id": "bosque", "style": {"audio": {"musicLufs": -16}}, "assets": []}
    asset = {"id": "fanfarria", "kind": "jingle", "spec": {"seconds": 4, "mood": "victory"}}
    fake = _Calls(source)
    result = JingleGenerator().run(_ctx(tmp_path, game, asset, fake))
    params = next(args["input"]["params"] for tool, args in fake.calls if tool == "generation.music")
    assert params["prompt"] == "short victory game jingle, ends clearly"
    assert params["duration_seconds"] == 10
    assert (tmp_path / "ws" / result.files["wav"]).is_file()


def test_voice_without_a_kit_uses_voice_design(tmp_path):
    source = tmp_path / "line.wav"
    _tone(source, seconds=0.4, sr=24000, amplitude=0.1)
    raw = {
        "id": "bosque", "title": "Bosque",
        "assets": [
            {"id": "heroe", "kind": "character"},
            {"id": "voz", "kind": "voice", "spec": {"character": "heroe", "lines": ["vamos", "otra"], "traits": "young scout"}},
        ],
    }
    game = normalize_game(raw, now=NOW)
    asset = next(item for item in game["assets"] if item["id"] == "voz")
    fake = _Calls(source)
    result = VoiceGenerator().run(_ctx(tmp_path, game, asset, fake))
    params = [args["input"]["params"] for tool, args in fake.calls if tool == "generation.speech"]
    assert [item["prompt"] for item in params] == ["vamos", "otra"]
    assert params[0]["model_type"] == "qwen3_tts_voicedesign"
    assert params[0]["alt_prompt"] == "young scout"
    assert (tmp_path / "ws" / result.files["1"]).name == "voz-1.wav"
    assert (tmp_path / "ws" / result.files["2"]).name == "voz-2.wav"
    assert result.metrics["voicedesign"] is True
