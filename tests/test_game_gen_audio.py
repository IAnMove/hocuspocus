"""Audio generators with synthetic WAV files. No GPU; ``best_loop`` runs for real."""
from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from services.game_generators.audio import (
    JingleGenerator,
    MusicGenerator,
    SfxGenerator,
    VoiceGenerator,
    jingle_seconds,
    loop_warnings,
    music_seconds,
)
from services.game_generators.base import GenContext
from services.game_library import normalize_game
from services.game_produce import _candidates
from services.game_tools import GameToolError

NOW = "2026-10-07T12:00:00Z"


def _tone(path: Path, seconds: float = 2.0, sr: int = 22050, amplitude: float = 0.2) -> None:
    count = int(seconds * sr)
    t = np.linspace(0.0, seconds, count, endpoint=False)
    sf.write(path, (amplitude * np.sin(2.0 * math.pi * 440.0 * t)).astype(np.float32), sr, subtype="PCM_16")


def _song(path: Path, sr: int = 22050, bars: int = 8, bpm: float = 120.0) -> tuple[int, list[float]]:
    """A bed plus a chord per bar, cycling every four bars. Returns the bar length and downbeat times."""
    bar = int(round(240.0 / bpm * sr))
    t = np.arange(bar * bars, dtype=np.float64) / sr
    signal = 0.22 * np.sin(2.0 * np.pi * 90.0 * t)
    chords = ((262.0, 330.0, 392.0), (349.0, 440.0, 523.0), (196.0, 247.0, 294.0), (220.0, 277.0, 330.0))
    for index in range(bars):
        part = slice(index * bar, (index + 1) * bar)
        signal[part] += 0.04 * sum(np.sin(2.0 * np.pi * freq * t[part]) for freq in chords[index % 4])
    sf.write(path, signal.astype(np.float32), sr, subtype="PCM_16")
    return bar, [index * bar / sr for index in range(bars + 1)]


class _Calls:
    def __init__(self, wav: Path, name: str | None = None):
        self.wav = wav
        self.name = name
        self.calls = []

    def __call__(self, tool, args):
        self.calls.append((tool, args))
        if tool in {"generation.sfx", "generation.music", "generation.speech"}:
            return {"receipt": {"result": {"job_id": "job-audio"}}}
        if tool == "jobs.wait":
            return {"status": "completed", "output_files": [self.name or str(self.wav)]}
        raise AssertionError(tool)

    def params(self, tool):
        return [args["input"]["params"] for name, args in self.calls if name == tool]

    def intents(self, tool):
        return [args["intent_id"] for name, args in self.calls if name == tool]


def _ctx(tmp_path: Path, game: dict, asset: dict, fake: _Calls) -> GenContext:
    workspace = tmp_path / "ws"
    workspace.mkdir(exist_ok=True)
    return GenContext(
        workspace="bosque", game=game, asset=asset, attempt_id="a1", call=fake,
        loopback=lambda _tool, _args: {}, workspace_dir=lambda _name: str(workspace),
        cancelled=lambda: False, log=lambda _message: None,
    )


def _analysis(monkeypatch, beats=(), downbeats=()):
    report = {"beats": [{"time": float(item)} for item in beats], "downbeats": [float(item) for item in downbeats]}

    def analyze(_path, transcribe=False, **_kwargs):
        assert transcribe is False
        return report

    monkeypatch.setattr("services.audio_analysis.analyze", analyze)


def _peak_db(path: Path) -> float:
    data, _sr = sf.read(path, always_2d=False)
    peak = float(np.max(np.abs(data)))
    return 20.0 * math.log10(peak)


def _duration(path: Path) -> float:
    data, sr = sf.read(path, always_2d=False)
    return float(len(data)) / float(sr)


def _smpl_loops(path: Path) -> list[tuple[int, int]]:
    blob = path.read_bytes()
    loops, pos = [], 12
    while pos + 8 <= len(blob):
        size = struct.unpack_from("<I", blob, pos + 4)[0]
        if blob[pos : pos + 4] == b"smpl":
            loops.append(struct.unpack_from("<II", blob, pos + 8 + 44))
        pos += 8 + size + (size & 1)
    return loops


GAME = {"id": "bosque", "style": {"audio": {"genre": "chiptune", "instruments": "square", "sfxPeakDb": -1, "sampleRate": 48000, "musicLufs": -16}}, "assets": []}


def test_loop_warning_thresholds():
    assert loop_warnings(0.05, 2.0) == []
    assert loop_warnings(0.05, -2.0) == []
    assert loop_warnings(0.06, 0.0) == ["loop_seam"]
    assert loop_warnings(0.0, 2.01) == ["loop_seam"]
    assert music_seconds(60, 120) == 76
    assert jingle_seconds(4) == 10
    assert jingle_seconds(14) == 20


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
    params = fake.params("generation.sfx")
    assert len(params) == 3
    assert params[0]["duration_seconds"] == 1
    assert "chiptune" in params[0]["prompt"]
    assert "a short jump" in params[0]["prompt"]


def test_sfx_reads_tool_outputs_named_relative_to_the_workspace(tmp_path):
    (tmp_path / "ws").mkdir()
    _tone(tmp_path / "ws" / "salto-v1.wav")
    asset = {"id": "salto", "kind": "sfx", "spec": {"variants": 1, "seconds": 0.5, "engine": "mmaudio"}}
    result = SfxGenerator().run(_ctx(tmp_path, GAME, asset, _Calls(tmp_path / "unused.wav", name="salto-v1.wav")))
    assert _duration(tmp_path / "ws" / result.files["1"]) <= 0.5


def test_seed_zero_is_a_seed(tmp_path):
    source = tmp_path / "raw.wav"
    _tone(source)
    asset = {"id": "salto", "kind": "sfx", "spec": {"variants": 3, "seconds": 0.5, "engine": "mmaudio", "seed": 0}}
    fake = _Calls(source)
    SfxGenerator().run(_ctx(tmp_path, GAME, asset, fake))
    assert [item["seed"] for item in fake.params("generation.sfx")] == [0, 1, 2]


def test_sfx_peak_above_zero_dbfs_does_not_clip(tmp_path):
    source = tmp_path / "raw.wav"
    _tone(source)
    game = {"id": "bosque", "style": {"audio": {"sfxPeakDb": 3, "sampleRate": 48000}}, "assets": []}
    asset = {"id": "salto", "kind": "sfx", "spec": {"variants": 1, "seconds": 0.5, "engine": "mmaudio"}}
    result = SfxGenerator().run(_ctx(tmp_path, game, asset, _Calls(source)))
    data, _sr = sf.read(tmp_path / "ws" / result.files["1"], always_2d=False)
    # A sine sits at full scale for a few percent of its samples; clipped, for a third or more.
    assert float(np.mean(np.abs(data) >= 0.999)) < 0.1


def test_retro_sfx_does_not_call_a_tool(tmp_path):
    fake = _Calls(tmp_path / "unused.wav")
    game = {"id": "bosque", "style": {"audio": {"sampleRate": 48000, "sfxPeakDb": -1}}, "assets": []}
    asset = {"id": "salto", "kind": "sfx", "spec": {"variants": 1, "seconds": 0.4, "engine": "retro", "retroPreset": "jump"}}
    result = SfxGenerator().run(_ctx(tmp_path, game, asset, fake))
    assert fake.calls == []
    assert SfxGenerator().estimate(game, asset) == {}
    path = tmp_path / "ws" / result.files["1"]
    assert path.name == "salto-1.wav"
    assert _duration(path) <= 0.4
    assert abs(_peak_db(path) - (-1.0)) <= 0.1


def test_unknown_retro_preset_is_a_tool_error(tmp_path):
    asset = {"id": "salto", "kind": "sfx", "spec": {"variants": 1, "seconds": 0.4, "engine": "retro", "retroPreset": "coin"}}
    with pytest.raises(GameToolError) as caught:
        SfxGenerator().run(_ctx(tmp_path, GAME, asset, _Calls(tmp_path / "unused.wav")))
    assert caught.value.code == "unknown_preset"


def test_music_writes_a_loop_with_smpl_metadata(tmp_path, monkeypatch):
    pytest.importorskip("librosa")  # the downbeat path scores seams with chroma and MFCCs
    source = tmp_path / "song.wav"
    _tone(source, seconds=3.0, sr=44100)
    # best_loop is not replaced: a fake with the old three-value return hid a crash.
    _analysis(monkeypatch, beats=[0.0, 0.5, 1.0], downbeats=[0.0, 1.0, 2.0])
    game = {"id": "bosque", "style": {"audio": {"genre": "chiptune", "instruments": "square", "bpm": [90, 140], "musicLufs": -16}}, "assets": []}
    asset = {"id": "tema", "kind": "music", "description": "forest", "spec": {"loopSeconds": 60, "bpm": 120, "mood": "calm"}}
    fake = _Calls(source)
    result = MusicGenerator().run(_ctx(tmp_path, game, asset, fake))
    wav = tmp_path / "ws" / result.files["wav"]
    assert b"smpl" in wav.read_bytes()
    assert result.metrics["loopStart"] == 0
    assert result.metrics["loopEnd"] > 0
    params = fake.params("generation.music")[0]
    assert params["prompt"] == "[Instrumental]"
    assert params["duration_seconds"] == 76
    assert "seamless loopable game background music, no intro, no ending" in params["alt_prompt"]
    assert "chiptune" in params["alt_prompt"]
    assert "square" in params["alt_prompt"]
    assert "calm" in params["alt_prompt"]
    assert "forest" in params["alt_prompt"]


def test_music_cuts_a_four_bar_loop_with_the_real_best_loop(tmp_path, monkeypatch):
    pytest.importorskip("librosa")
    source = tmp_path / "song.wav"
    bar, downbeats = _song(source)
    _analysis(monkeypatch, beats=[index * bar / 4 / 22050 for index in range(33)], downbeats=downbeats)
    asset = {"id": "tema", "kind": "music", "spec": {"loopSeconds": 8, "bpm": 120}}
    result = MusicGenerator().run(_ctx(tmp_path, GAME, asset, _Calls(source)))
    wav = tmp_path / "ws" / result.files["wav"]
    frames = sf.info(str(wav)).frames
    assert frames == 4 * bar
    assert _smpl_loops(wav) == [(0, frames - 1)]
    assert result.metrics["loopEnd"] == frames - 1
    assert "loop_seam" not in result.warnings
    assert abs(result.metrics["lufs"] - (-16)) <= 1.0
    ogg = tmp_path / "ws" / result.files["ogg"]
    assert sf.info(str(ogg)).frames == frames


def test_music_without_downbeats_loops_four_bars_near_the_target(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    _tone(source, seconds=20.0, sr=22050)
    _analysis(monkeypatch)
    asset = {"id": "tema", "kind": "music", "spec": {"loopSeconds": 8, "bpm": 120}}
    result = MusicGenerator().run(_ctx(tmp_path, GAME, asset, _Calls(source)))
    assert result.metrics["duration"] == 8.0
    assert "loop_no_downbeats" in result.warnings
    assert "loop_seam" not in result.warnings


def test_jingle_asks_for_an_instrumental_that_reaches_its_length(tmp_path, monkeypatch):
    source = tmp_path / "jingle.wav"
    _tone(source, seconds=20.0, sr=22050)
    _analysis(monkeypatch, downbeats=[0.0, 4.0, 8.0, 12.0, 16.0])
    asset = {"id": "fanfarria", "kind": "jingle", "description": "coins", "spec": {"seconds": 12, "mood": "victory"}}
    fake = _Calls(source)
    result = JingleGenerator().run(_ctx(tmp_path, GAME, asset, fake))
    params = fake.params("generation.music")[0]
    # ACE-Step sings ``prompt``; the jingle description belongs in ``alt_prompt``.
    assert params["prompt"] == "[Instrumental]"
    assert "short victory game jingle, ends clearly" in params["alt_prompt"]
    assert "chiptune" in params["alt_prompt"] and "coins" in params["alt_prompt"]
    assert params["duration_seconds"] == 18
    assert result.metrics["duration"] == 12.0


def test_a_missed_loudness_target_is_reported(tmp_path, monkeypatch):
    source = tmp_path / "jingle.wav"
    _tone(source, seconds=10.0, sr=22050, amplitude=0.01)
    _analysis(monkeypatch, downbeats=[0.0, 2.0, 4.0, 6.0])
    # As when ffmpeg fails: lufs_normalize returns 0 dB and leaves the file alone.
    monkeypatch.setattr("services.game_generators.audio.lufs_normalize", lambda _path, _target: 0.0)
    asset = {"id": "fanfarria", "kind": "jingle", "spec": {"seconds": 4, "mood": "victory"}}
    result = JingleGenerator().run(_ctx(tmp_path, GAME, asset, _Calls(source)))
    assert "loudness_off_target" in result.warnings


def test_music_jingle_and_voice_make_every_candidate_they_estimate(tmp_path, monkeypatch):
    source = tmp_path / "song.wav"
    _tone(source, seconds=20.0, sr=22050)
    _analysis(monkeypatch)  # no downbeats: the real best_loop falls back without librosa, as on CI
    cases = [
        (MusicGenerator(), "generation.music", {"id": "tema", "kind": "music", "candidates": 2, "spec": {"loopSeconds": 8, "bpm": 120, "seed": 5}}),
        (JingleGenerator(), "generation.music", {"id": "fanfarria", "kind": "jingle", "candidates": 2, "spec": {"seconds": 4, "seed": 5}}),
        (VoiceGenerator(), "generation.speech", {"id": "voz", "kind": "voice", "candidates": 2, "spec": {"character": "heroe", "lines": ["uno", "dos"], "seed": 5}}),
    ]
    for generator, tool, asset in cases:
        fake = _Calls(source)
        result = generator.run(_ctx(tmp_path, GAME, asset, fake))
        assert sum(generator.estimate(GAME, asset).values()) == len(fake.params(tool))
        intents = fake.intents(tool)
        assert len(set(intents)) == len(intents)
        assert sorted(item["seed"] for item in fake.params(tool)) == list(range(5, 5 + len(intents)))
        stored = _candidates(result, "a1")
        assert [item[0] for item in stored] == ["a1-a1", "a1-a2"]
        for attempt_id, files, _metrics, _own in stored:
            assert files and all(f"/a1/{attempt_id[-2:]}/" in value for value in files.values())


def test_voice_without_lines_fails(tmp_path):
    asset = {"id": "voz", "kind": "voice", "spec": {"character": "heroe", "lines": []}}
    with pytest.raises(GameToolError) as caught:
        VoiceGenerator().run(_ctx(tmp_path, GAME, asset, _Calls(tmp_path / "unused.wav")))
    assert caught.value.code == "no_lines"


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
    params = fake.params("generation.speech")
    assert [item["prompt"] for item in params] == ["vamos", "otra"]
    assert params[0]["model_type"] == "qwen3_tts_voicedesign"
    assert params[0]["alt_prompt"] == "young scout"
    assert (tmp_path / "ws" / result.files["1"]).name == "voz-1.wav"
    assert (tmp_path / "ws" / result.files["2"]).name == "voz-2.wav"
    assert result.metrics["voicedesign"] is True
