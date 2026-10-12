"""audio.trim cuts an exact segment (start + length or end) of an audio file into a new file."""
from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest
from fastapi import HTTPException

from tests.media_tool_fixtures import Install, needs_ffmpeg, probe, tone


def _samples(path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-f", "s16le", "-ac", "1", "pipe:1"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.int16)


@needs_ffmpeg
def test_cut_is_exact_and_keeps_rate_and_channels(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    tone(folder / "steps.wav", seconds=8.0, rate=44100, channels=2)
    result = install.call("audio.trim", {"workspace": "ep", "source": "steps.wav", "start": 2.25, "length": 0.4,
                                         "output_name": "one-step"})["result"]
    assert result["file"] == "one-step.wav" and result["clipped"] is False
    assert (result["sample_rate"], result["channels"]) == (44100, 2)
    assert abs(result["seconds"] - 0.4) < 0.002 and result["start"] == 2.25
    made = probe(folder / "one-step.wav")
    assert abs(made["duration"] - 0.4) < 0.002 and made["codec"] == "pcm_s16le"
    samples = _samples(folder / "one-step.wav")
    assert len(samples) == round(0.4 * 44100)
    assert abs(int(samples[0])) < 200 and abs(int(samples[-1])) < 200  # faded, no click
    assert np.abs(samples[2000:3000]).max() > 2000  # the tone itself (lavfi sine, 1/8 scale) is kept
    meta = json.loads((folder / "one-step.meta.json").read_text())
    assert meta["origin"]["tool"] == "audio.trim" and meta["params"]["start"] == 2.25
    assert meta["lineage"]["parents"][0]["uri"] == "steps.wav"


@needs_ffmpeg
def test_end_past_the_file_is_clipped_and_keep_format(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=330:sample_rate=48000:duration=3",
                    "-c:a", "flac", str(folder / "bell.flac")], check=True, capture_output=True)
    result = install.call("audio.trim", {"workspace": "ep", "source": "bell.flac", "start": 2.0, "end": 9.0,
                                         "format": "keep", "fade_out": 0})["result"]
    assert result["file"].endswith(".flac") and result["clipped"] is True
    assert abs(result["seconds"] - 1.0) < 0.01 and (result["sample_rate"], result["channels"]) == (48000, 1)


@needs_ffmpeg
def test_bad_windows_are_refused(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    tone(folder / "steps.wav", seconds=1.0)
    cases = [
        ({"start": 1.5, "length": 0.2}, "start_past_end"),
        ({"start": 0.2}, "invalid_command"),
        ({"start": 0.2, "length": 0.1, "end": 0.5}, "invalid_command"),
        ({"start": 0.5, "end": 0.4}, "invalid_command"),
        ({"start": -1, "length": 0.1}, "invalid_command"),
        ({"start": 0, "length": 0.1, "format": "mp3"}, "invalid_command"),
    ]
    for window, code in cases:
        with pytest.raises(HTTPException) as error:
            install.call("audio.trim", {"workspace": "ep", "source": "steps.wav", **window})
        assert error.value.detail["code"] == code, window
    with pytest.raises(HTTPException) as other:
        install.call("audio.trim", {"workspace": "ep", "source": "/api/v1/file/steps.wav?workspace=other", "start": 0, "length": 0.1})
    assert other.value.detail["code"] == "path_not_allowed"
    assert sorted(path.name for path in folder.iterdir()) == ["steps.wav"]


@needs_ffmpeg
def test_a_videos_audio_can_be_cut_to_wav(tmp_path):
    install = Install(tmp_path)
    folder = install.folder("ep")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=32x32:d=2", "-f", "lavfi",
                    "-i", "sine=frequency=500:sample_rate=22050:duration=2", "-shortest", "-c:v", "libx264", "-c:a", "aac",
                    str(folder / "take.mp4")], check=True, capture_output=True)
    result = install.call("audio.trim", {"workspace": "ep", "source": "take.mp4", "start": 0.5, "length": 1.0})["result"]
    assert result["file"].endswith(".wav") and result["sample_rate"] == 22050 and abs(result["seconds"] - 1.0) < 0.01
    with pytest.raises(HTTPException) as keep:
        install.call("audio.trim", {"workspace": "ep", "source": "take.mp4", "start": 0, "length": 1, "format": "keep"})
    assert keep.value.detail["code"] == "invalid_command"
