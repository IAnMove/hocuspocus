"""Timed overlays and audio cues for the Video Editor export (montages)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.video_editor_layers import (
    LayerValidationError,
    apply_layers,
    build_layer_filter,
    clean_audio_cues,
    clean_export_layers,
    clean_overlays,
    resolve_export_layers,
)

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


def _overlay(**overrides):
    item = {"id": "cap", "source": "cap.png", "start": 0.5, "end": 1.5, "x": 50, "y": 80, "width": 50,
            "fade_in": 0.2, "fade_out": 0.2}
    item.update(overrides)
    return item


def test_clean_rejects_inverted_times_and_bad_ranges():
    with pytest.raises(LayerValidationError, match="end after"):
        clean_overlays([_overlay(start=2, end=1)])
    with pytest.raises(LayerValidationError, match="width"):
        clean_overlays([_overlay(width=0)])
    with pytest.raises(LayerValidationError, match="volume"):
        clean_audio_cues([{"source": "vo.wav", "start": 1, "volume": 3}])
    with pytest.raises(LayerValidationError, match="source"):
        clean_audio_cues([{"start": 1}])


def test_export_layers_are_optional_and_defaults_are_explicit():
    assert clean_export_layers({}) is None
    layers = clean_export_layers({"audio_cues": [{"source": "vo.wav", "start": 2}], "duck": 0.5})
    assert layers["overlays"] == []
    assert layers["audio_cues"][0] == {"id": "cue-1", "name": "", "source": "vo.wav", "start": 2.0, "volume": 1.0,
                                       "trim_start": 0.0, "trim_end": 0.0}
    assert layers["duck"] == 0.5


def test_resolution_enforces_media_types(tmp_path):
    (tmp_path / "cap.png").write_bytes(b"png")
    (tmp_path / "vo.txt").write_text("not audio")

    def resolve(source, workspace):
        return str(tmp_path / source)

    layers = clean_export_layers({"overlays": [_overlay()], "audio_cues": [{"source": "vo.txt", "start": 0}]})
    with pytest.raises(LayerValidationError, match="unsupported audio"):
        resolve_export_layers(layers, "ws", resolve_path=resolve)


def test_filter_graph_places_overlays_and_ducks_music():
    overlays = [dict(_overlay(), resolved_path="/tmp/cap.png", name="", opacity=1)]
    cues = [{"id": "vo", "source": "vo.wav", "resolved_path": "/tmp/vo.wav", "start": 1.25, "volume": 1.5,
             "trim_start": 0, "trim_end": 0}]
    inputs, graph, maps_video, maps_audio = build_layer_filter(
        overlays, cues, width=1920, height=1080, fps=24, duration=3, duck=0.5)
    assert maps_video and maps_audio
    assert inputs[inputs.index("-i") + 1] == "/tmp/cap.png"
    assert "scale=960:-2" in graph and "setpts=PTS+0.5000/TB" in graph
    assert "fade=t=out:st=0.8000:d=0.2000:alpha=1" in graph
    assert "adelay=1250|1250" in graph and "volume=1.5000" in graph
    assert "sidechaincompress" in graph and "ratio=5.500" in graph
    # Cues starting after the end of the video are dropped, not appended.
    _, late_graph, _, late_audio = build_layer_filter([], [dict(cues[0], start=9)], width=64, height=64, fps=24,
                                                      duration=3, duck=0)
    assert not late_audio and late_graph == ""


@pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")
def test_apply_layers_burns_overlay_and_mixes_cue(tmp_path):
    base = tmp_path / "base.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=black:s=160x90:r=24:d=2",
                    "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-t", "2", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", str(base)], check=True)
    image = tmp_path / "cap.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=white:s=80x20", "-frames:v", "1", str(image)], check=True)
    voice = tmp_path / "vo.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5", str(voice)], check=True)
    out = tmp_path / "out.mp4"
    assert apply_layers(str(base), str(out), width=160, height=90, fps=24, duration=2.0, duck=0.4,
                        overlays=[dict(_overlay(start=0, end=2, x=50, y=50, width=50, fade_in=0, fade_out=0),
                                       resolved_path=str(image), name="", opacity=1)],
                        audio_cues=[{"id": "vo", "source": "vo.wav", "resolved_path": str(voice), "start": 0.5, "volume": 1,
                                     "trim_start": 0, "trim_end": 0}])
    probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(out)],
                                      capture_output=True, text=True, check=True).stdout)
    assert {stream["codec_type"] for stream in probe["streams"]} == {"video", "audio"}
    assert abs(float(probe["format"]["duration"]) - 2.0) < 0.1
    # The centre pixel is white where the overlay sits and the corner stays black.
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", "1", "-i", str(out), "-frames:v", "1", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    assert raw[45 * 160 + 80] > 200 and raw[2 * 160 + 2] < 40
    loud = subprocess.run(["ffmpeg", "-v", "info", "-ss", "0.6", "-t", "0.3", "-i", str(out), "-af", "volumedetect",
                           "-f", "null", "-"], capture_output=True, text=True).stderr
    assert "mean_volume" in loud and "-91" not in loud.split("mean_volume:")[1][:8]
