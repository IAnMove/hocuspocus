"""One mixer under every rendered scene: the same limiter for Video 2D and Video 3D, files anywhere in the workspace."""
from pathlib import Path

import pytest

from services import audio_mix
from services.audio_mix import AUDIO_FILTER_TAIL, _usable_tracks, mix_audio_tracks, mux_wav_audio, track_source


def test_tracks_may_live_in_a_subfolder_but_never_outside_the_workspace(tmp_path):
    (tmp_path / "music").mkdir()
    (tmp_path / "music" / "theme.wav").write_bytes(b"x")
    assert track_source(tmp_path, "music/theme.wav") == (tmp_path / "music" / "theme.wav").resolve()
    assert track_source(tmp_path, "music\\theme.wav") == (tmp_path / "music" / "theme.wav").resolve()
    for outside in ("../theme.wav", "music/../../theme.wav", "/etc/passwd", "", None):
        assert track_source(tmp_path, outside) is None
    usable = _usable_tracks([{"filename": "music/theme.wav", "startTime": 1, "volume": 0.4, "kind": "music"},
                             {"filename": "missing.wav", "startTime": 0}], tmp_path, 10.0)
    assert usable == [((tmp_path / "music" / "theme.wav").resolve(), 1.0, 0.4, False)]


def test_both_mixers_end_in_the_same_limiter(tmp_path, monkeypatch):
    commands = []

    def fake_run(command, **_kwargs):
        commands.append(command)
        Path(command[-1]).write_bytes(b"mp4")
        return type("R", (), {"returncode": 0, "stderr": ""})()

    monkeypatch.setattr(audio_mix.subprocess, "run", fake_run)
    video, wav = tmp_path / "v.mp4", tmp_path / "fx.wav"
    video.write_bytes(b"v"); wav.write_bytes(b"w")
    (tmp_path / "theme.wav").write_bytes(b"t")
    mux_wav_audio(video, wav, 3.0)
    mix_audio_tracks(video, [{"filename": "theme.wav", "startTime": 0, "volume": 0.5, "kind": "music"}], tmp_path, 3.0)
    filters = [command[command.index("-filter_complex") + 1] for command in commands]
    assert len(filters) == 2 and all(AUDIO_FILTER_TAIL in chain for chain in filters)
    assert "alimiter=limit=0.97" in AUDIO_FILTER_TAIL
    for chain in filters:
        assert chain.index("alimiter") < chain.index("apad"), "limit, then pad to length"


def test_a_failed_mix_names_its_label(tmp_path, monkeypatch):
    monkeypatch.setattr(audio_mix.subprocess, "run", lambda *a, **k: type("R", (), {"returncode": 1, "stderr": "boom"})())
    with pytest.raises(RuntimeError, match="World3D audio mix failed: boom"):
        mux_wav_audio(tmp_path / "v.mp4", tmp_path / "w.wav", 1.0, label="World3D audio mix")
