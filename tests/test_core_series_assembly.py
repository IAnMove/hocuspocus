import shutil
import subprocess
from pathlib import Path

import pytest

from services.core_series_assembly import asset_local_path, concatenate_clips
from services.series_asset_path import series_asset_local_path
from services.mix_concat import probe_duration_seconds, probe_has_audio


def test_a_missing_series_asset_can_fail_closed_or_be_skipped(tmp_path):
    """Both policies stay available. Callers choose; this test does not pick a default for them."""
    asset = {"id": "shot-1", "uri": "missing.mp4"}
    kwargs = {"workspace_dir": lambda _workspace: str(tmp_path), "remote_purpose": "assembly"}
    with pytest.raises(ValueError, match="Series reference file is missing: missing.mp4"):
        series_asset_local_path("default", asset, on_missing="raise", **kwargs)
    assert series_asset_local_path("default", asset, on_missing="skip", **kwargs) == ""


def test_remote_series_asset_keeps_the_caller_purpose(tmp_path):
    asset = {"id": "remote-1", "uri": "https://example.invalid/clip.mp4"}
    folder = lambda _workspace: str(tmp_path)
    with pytest.raises(ValueError, match="before assembly$"):
        series_asset_local_path("default", asset, workspace_dir=folder, remote_purpose="assembly")
    with pytest.raises(ValueError, match="before local H3 rendering$"):
        series_asset_local_path(
            "default", asset, workspace_dir=folder, remote_purpose="local H3 rendering",
        )


def test_core_asset_path_still_fails_closed_and_stays_inside_the_workspace(tmp_path, monkeypatch):
    folder = tmp_path / "outputs"
    folder.mkdir()
    clip = folder / "take.mp4"
    clip.write_bytes(b"clip")
    monkeypatch.setattr(
        "services.core_series_assembly.core.workspace_dir",
        lambda _workspace=None: str(folder),
    )
    assert asset_local_path("default", {"id": "take", "uri": "take.mp4"}) == str(clip.resolve())
    with pytest.raises(ValueError, match="Series reference file is missing: gone.mp4"):
        asset_local_path("default", {"id": "gone", "uri": "gone.mp4"})
    with pytest.raises(ValueError, match="leaves its workspace"):
        asset_local_path("default", {"id": "out", "uri": "../secret.mp4"})


def test_core_assembly_does_not_use_concat_demuxer():
    source = Path(__file__).resolve().parents[1] / "app" / "services" / "core_series_assembly.py"
    text = source.read_text(encoding="utf-8")
    assert '"-f", "concat"' not in text
    assert '"-c", "copy"' not in text
    assert "build_hard_concat_filter" in text
    assert "concat_with_tail_hold_and_crossfade" in text


def test_concatenate_clips_fails_closed_when_a_planned_file_is_missing(tmp_path):
    first = tmp_path / "one.mp4"
    first.write_bytes(b"clip")
    output = tmp_path / "joined.mp4"
    assert concatenate_clips([str(first), str(tmp_path / "missing.mp4")], str(output)) is False
    assert not output.exists()


def test_concatenate_clips_fails_closed_when_a_planned_file_is_empty(tmp_path):
    first = tmp_path / "one.mp4"
    empty = tmp_path / "empty.mp4"
    first.write_bytes(b"clip")
    empty.write_bytes(b"")
    output = tmp_path / "joined.mp4"
    assert concatenate_clips([str(first), str(empty)], str(output)) is False
    assert not output.exists()


def _write_clip(path: Path, *, with_audio: bool, duration: float, fps: int, timescale: int) -> None:
    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"testsrc=size=320x240:rate={fps}",
    ]
    if with_audio:
        cmd += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={duration}"]
        cmd += ["-c:a", "aac"]
    cmd += [
        "-t", f"{duration:.3f}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
        "-video_track_timescale", str(timescale),
        str(path),
    ]
    completed = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr[-400:]


def _probe_duration(path: Path) -> float:
    value = probe_duration_seconds(str(path))
    assert value is not None
    return value


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe required",
)
def test_concatenate_clips_keeps_both_shots_when_timebase_and_audio_differ(tmp_path):
    """Dialogue + video-only bumper used to be remuxed by concat+copy.

    ffmpeg returned 0, published a ~2.0s file, and dropped the bumper's 1.5s
    (non-monotonic DTS, audio only from clip 0). The concat filter keeps both.
    """
    talk = tmp_path / "talk.mp4"
    bumper = tmp_path / "bumper.mp4"
    output = tmp_path / "episode.mp4"
    _write_clip(talk, with_audio=True, duration=1.0, fps=30, timescale=15360)
    _write_clip(bumper, with_audio=False, duration=1.5, fps=24, timescale=12288)
    assert concatenate_clips([str(talk), str(bumper)], str(output)) is True
    duration = _probe_duration(output)
    # Soft join adds a short freeze-tail; both source clips must still be there.
    assert duration >= 2.4, duration
    assert probe_has_audio(str(output)) is True
