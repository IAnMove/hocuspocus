from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import scene_recording


def test_canonical_scene_fps_keeps_24_30_and_60():
    assert scene_recording.canonical_scene_fps(24) == 24
    assert scene_recording.canonical_scene_fps(30) == 30
    assert scene_recording.canonical_scene_fps(60) == 60
    assert scene_recording.canonical_scene_fps(25) == 30
    assert scene_recording.canonical_scene_fps("24") == 24
    assert scene_recording.canonical_scene_fps(None) == 30


def test_command_keeps_authored_24fps_instead_of_coercing_to_30():
    command = scene_recording.build_scene_recording_command(
        "capture.webm",
        "scene.mp4",
        fps=24,
        duration=10,
    )
    assert "fps=24,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1" in command
    assert command[command.index("-frames:v") + 1] == "240"


def test_command_finalizes_browser_webm_as_compatible_mp4():
    command = scene_recording.build_scene_recording_command(
        "capture.webm",
        "scene.mp4",
        fps=60,
    )

    assert command[:6] == ["ffmpeg", "-v", "error", "-y", "-i", "capture.webm"]
    assert "fps=60,scale=trunc(iw/2)*2:trunc(ih/2)*2,setsar=1" in command
    assert command[command.index("-c:v") + 1] == "libx264"
    assert command[command.index("-pix_fmt") + 1] == "yuv420p"
    assert command[command.index("-movflags") + 1] == "+faststart"
    assert command[-1] == "scene.mp4"


def test_command_mixes_scene_audio_without_shortening_the_video():
    command = scene_recording.build_scene_recording_command(
        "capture.webm", "scene.mp4", fps=30, duration=10,
        audio_tracks=[{"path": "voice.wav", "start_time": 2, "volume": 0.7}],
    )
    assert command.count("-i") == 2
    assert "[1:a]aresample=48000,adelay=2000|2000,volume=0.700[audio1]" in command[command.index("-filter_complex") + 1]
    assert "-c:a" in command and command[command.index("-c:a") + 1] == "aac"
    assert "-shortest" not in command
    assert command[command.index("-frames:v") + 1] == "300"


def test_embedded_voice_and_effects_are_explicitly_mixed_with_existing_tracks():
    command = scene_recording.build_scene_recording_command(
        'capture.mp4', 'scene.mp4', fps=30, duration=4, embedded_audio=True,
        audio_tracks=[{'path': 'music.wav', 'start_time': 0, 'volume': .3}],
    )
    graph = command[command.index('-filter_complex') + 1]
    assert '[0:a]aresample=48000[embedded_audio]' in graph
    assert '[embedded_audio][audio1]amix=inputs=2' in graph
    assert '-an' not in command
    assert 'atrim=0:4.000' in graph


def test_real_embedded_audio_survives_publication(tmp_path):
    import shutil
    import subprocess
    import array
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg is required for real audio publication verification')
    source = tmp_path / 'voiced.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=64x64:r=30:d=1',
                    '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=48000:duration=1',
                    '-c:v', 'libx264', '-threads', '1', '-c:a', 'aac', str(source)], check=True, capture_output=True)
    output = tmp_path / 'published.mp4'
    scene_recording.transcode_scene_recording(source, output, fps=30, duration=1, embedded_audio=True)
    decoded = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(output), '-map', '0:a:0', '-ac', '1',
                              '-f', 'f32le', 'pipe:1'], check=True, capture_output=True)
    samples = array.array('f', decoded.stdout)
    rms = (sum(value * value for value in samples) / len(samples)) ** .5
    assert .07 < rms < .1  # Original tone, not silence or a doubled track.


def test_validate_output_checks_h264_audio_and_target_duration(monkeypatch, tmp_path: Path):
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"mp4")
    monkeypatch.setattr(
        scene_recording,
        "probe_scene_recording_output",
        lambda _path: {
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "duration": "10.000"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
            "format": {"duration": "10.000"},
        },
    )
    metadata = scene_recording.validate_scene_recording_output(
        output, expected_duration=10, expected_fps=30
    )
    assert metadata["format"]["duration"] == "10.000"


def test_validate_output_rejects_duration_drift(monkeypatch, tmp_path: Path):
    output = tmp_path / "scene.mp4"
    output.write_bytes(b"mp4")
    monkeypatch.setattr(
        scene_recording,
        "probe_scene_recording_output",
        lambda _path: {
            "streams": [{"codec_type": "video", "codec_name": "h264", "duration": "9.800"}],
        },
    )
    with pytest.raises(scene_recording.SceneRecordingTranscodeError, match="differs from target"):
        scene_recording.validate_scene_recording_output(output, expected_duration=10)


def test_transcode_is_atomic(monkeypatch, tmp_path: Path):
    source = tmp_path / "capture.webm"
    destination = tmp_path / "scene.mp4"
    source.write_bytes(b"webm")

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"mp4")
        assert not destination.exists()
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(scene_recording.subprocess, "run", fake_run)
    monkeypatch.setattr(scene_recording, "validate_scene_recording_output", lambda *_args, **_kwargs: {})
    scene_recording.transcode_scene_recording(source, destination, fps=30)

    assert destination.read_bytes() == b"mp4"
    assert not list(tmp_path.glob("*.partial.mp4"))


def test_transcode_does_not_publish_failed_output(monkeypatch, tmp_path: Path):
    source = tmp_path / "capture.webm"
    destination = tmp_path / "scene.mp4"
    source.write_bytes(b"webm")

    monkeypatch.setattr(
        scene_recording.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stderr="bad input"),
    )

    with pytest.raises(scene_recording.SceneRecordingTranscodeError, match="bad input"):
        scene_recording.transcode_scene_recording(source, destination, fps=30)

    assert not destination.exists()
