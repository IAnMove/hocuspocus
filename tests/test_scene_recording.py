from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import scene_recording


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


def test_transcode_is_atomic(monkeypatch, tmp_path: Path):
    source = tmp_path / "capture.webm"
    destination = tmp_path / "scene.mp4"
    source.write_bytes(b"webm")

    def fake_run(command, **_kwargs):
        Path(command[-1]).write_bytes(b"mp4")
        assert not destination.exists()
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(scene_recording.subprocess, "run", fake_run)
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
