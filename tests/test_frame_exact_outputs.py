"""Frame-exact outputs of the ffmpeg passes that finish a generation.

A bare ``-shortest`` ends the output when the shortest stream ends. With a
re-encoded picture the encoder still holds frames at that moment, so an audio
track that ends a little before the picture silently cost the file its last 1-6
frames (validation finding edit-10, N4). The rule these tests pin: copied audio
never carries ``-shortest``; re-encoded source audio is padded first, so it can
bound a longer track but never cut the picture.

The tests run the real ffmpeg on tiny synthetic clips (they skip without it).
CI runs ffmpeg 6.1.1, a developer machine may run 8.x: both must agree.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg and ffprobe are required",
)

FPS = 25
FRAMES = 49  # 1.96 s of picture: one LTX 8n+1 clip


def _make_clip(path: Path, frames: int, *, audio_seconds: float | None = None, size: str = "320x240",
               source: str = "testsrc", rate: int = FPS) -> str:
    command = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"{source}=size={size}:rate={rate}"]
    if audio_seconds is not None:
        command += ["-f", "lavfi", "-t", f"{audio_seconds}", "-i", "sine=frequency=440:sample_rate=48000"]
    command += ["-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p"]
    if audio_seconds is not None:
        command += ["-c:a", "aac"]
    subprocess.run([*command, str(path)], check=True, capture_output=True)
    return str(path)


def _mask_clip(path: Path, frames: int, rate: int = FPS) -> str:
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=white:size=320x240:rate={rate}",
        "-vf", "drawbox=x=100:y=60:w=80:h=120:color=red:t=fill",
        "-frames:v", str(frames), "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path),
    ], check=True, capture_output=True)
    return str(path)


def _frames(path: str) -> int:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
         "stream=nb_read_frames", "-of", "json", path],
        check=True, capture_output=True, text=True,
    ).stdout
    return int(json.loads(out)["streams"][0]["nb_read_frames"])


def _audio_seconds(path: str) -> float | None:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=duration", "-of", "csv=p=0", path],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return float(out) if out and out != "N/A" else None


def _run(command: list[str]) -> None:
    done = subprocess.run(command, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr[-400:]


# -- Recast "Protect bystanders" ----------------------------------------------------------------------------------


@pytest.mark.parametrize("generated_audio, source_audio, label", [
    (1.95, 1.96, "the generated clip's own audio is copied and ends before the picture"),
    (None, 1.90, "the generated clip is silent and the source audio is shorter than the picture"),
    (None, 4.0, "the generated clip is silent and the source audio is longer than the picture"),
    (None, None, "nothing has audio"),
])
def test_recast_protection_keeps_every_generated_frame(tmp_path, generated_audio, source_audio, label):
    from services.recast_masks import _build_recast_mask_lock_command

    source = _make_clip(tmp_path / "source.mp4", FRAMES, audio_seconds=source_audio, source="testsrc2")
    mask = _mask_clip(tmp_path / "mask.mp4", FRAMES)
    generated = _make_clip(tmp_path / "generated.mp4", FRAMES, audio_seconds=generated_audio)
    protected = str(tmp_path / "generated.recast-protected.mp4")

    command = _build_recast_mask_lock_command(source, mask, generated, protected)
    _run(command)

    got = _frames(protected)
    assert got == FRAMES, f"{label}: {got} of {FRAMES} frames"
    picture = FRAMES / FPS
    if generated_audio is not None:
        # Copied audio keeps its own length; nothing pads or cuts it.
        assert _audio_seconds(protected) == pytest.approx(generated_audio, abs=0.05), label
    elif source_audio is not None:
        # Padded when shorter, bounded when longer: it ends with the picture.
        assert _audio_seconds(protected) == pytest.approx(picture, abs=0.1), label
    else:
        assert _audio_seconds(protected) is None


def test_recast_protection_command_uses_shortest_only_with_padded_source_audio(tmp_path):
    from services.recast_masks import _build_recast_mask_lock_command

    source = _make_clip(tmp_path / "source.mp4", 9, audio_seconds=1.0)
    mask = _mask_clip(tmp_path / "mask.mp4", 9)
    own_audio = _make_clip(tmp_path / "own.mp4", 9, audio_seconds=0.3)
    silent = _make_clip(tmp_path / "silent.mp4", 9)
    out = str(tmp_path / "out.mp4")

    copied = _build_recast_mask_lock_command(source, mask, own_audio, out)
    assert "-shortest" not in copied
    assert copied[copied.index("-c:a") + 1] == "copy"

    reencoded = _build_recast_mask_lock_command(source, mask, silent, out)
    assert reencoded[reencoded.index("-af") + 1] == "apad"
    assert reencoded.index("-af") < reencoded.index("-shortest")
    # The padded track is also cut just after the generated picture ends (9 frames at 25 fps: 0.360 s).
    assert reencoded[reencoded.index("-t") + 1] == "0.361"

    plain = _build_recast_mask_lock_command(
        _make_clip(tmp_path / "mute-source.mp4", 9), mask, silent, out,
    )
    assert "-shortest" not in plain and "-an" in plain


# -- Outpaint finishing pass --------------------------------------------------------------------------------------


def _outpaint_command(tmp_path, *, overlay=False, trim=None, audio=True, own_audio=1.95, source_audio=1.2):
    from services.generation_worker.finalize import _run_generation_outpaint_command

    generated = _make_clip(tmp_path / "generated.mp4", FRAMES, audio_seconds=own_audio)
    source = _make_clip(tmp_path / "source.mp4", FRAMES, audio_seconds=source_audio, size="160x120", source="testsrc2")
    muxed = str(tmp_path / "generated_post.mp4")
    raw_params = {}
    if overlay:
        raw_params.update({
            "_outpaint_overlay_w": 160, "_outpaint_overlay_h": 120, "_outpaint_overlay_x": 80,
            "_outpaint_overlay_y": 60, "_outpaint_canvas_w": 320, "_outpaint_canvas_h": 240,
        })
    boundary, count = trim or (0, 0)
    _did_overlay, command = _run_generation_outpaint_command(
        audio, overlay, trim is not None, boundary, count, muxed, generated, raw_params, audio, source, subprocess,
    )
    return command, muxed


@pytest.mark.parametrize("case, kwargs, expected_frames", [
    ("audio mux only, source audio shorter than the picture", {}, FRAMES),
    ("source-area overlay with source audio shorter than the picture", {"overlay": True}, FRAMES),
    ("smear trim with source audio shorter than the picture", {"trim": (10, 5)}, FRAMES - 5),
    ("overlay keeping the generated audio, which ends before the picture", {"overlay": True, "audio": False}, FRAMES),
    ("audio left alone, generated audio ends before the picture", {"audio": False}, FRAMES),
])
def test_outpaint_finishing_pass_keeps_every_frame(tmp_path, case, kwargs, expected_frames):
    command, muxed = _outpaint_command(tmp_path, **kwargs)
    _run(command)
    got = _frames(muxed)
    assert got == expected_frames, f"{case}: {got} of {expected_frames} frames"


def test_outpaint_finishing_pass_bounds_a_longer_source_audio_to_the_picture(tmp_path):
    command, muxed = _outpaint_command(tmp_path, source_audio=5.0)
    _run(command)
    assert _frames(muxed) == FRAMES
    assert _audio_seconds(muxed) == pytest.approx(FRAMES / FPS, abs=0.1)


def test_outpaint_finishing_pass_uses_shortest_only_with_padded_source_audio(tmp_path):
    for kwargs in ({}, {"overlay": True}, {"trim": (10, 5)}):
        command, _muxed = _outpaint_command(tmp_path, **kwargs)
        assert command[command.index("-af") + 1] == "apad"
        assert command.count("-shortest") == 1 and command.index("-af") < command.index("-shortest")
        # ... and cut just after the picture ends: 49 frames at 25 fps, minus the 5 trimmed frames in the trim case.
        expected = "1.761" if kwargs.get("trim") else "1.961"
        assert command[command.index("-t") + 1] == expected
    for kwargs in ({"audio": False}, {"overlay": True, "audio": False}):
        command, _muxed = _outpaint_command(tmp_path, **kwargs)
        assert "-shortest" not in command and "-af" not in command


@pytest.mark.parametrize("rate, frames", [(16, 81), (30, 100)])
def test_the_audio_bound_never_ends_before_the_last_frame(tmp_path, rate, frames):
    """81 frames at 16 fps last 5.0625 s and 100 frames at 30 fps 3.3333 s: not a whole millisecond.

    A ``-t`` rounded to the nearest millisecond (5.062, 3.333) ended the padded audio just before the last frame
    ended, and ``-shortest`` then dropped that frame (re-encoded picture) or the last four (copied picture).
    """
    from services.generation_worker.finalize import _run_generation_outpaint_command
    from services.recast_masks import _build_recast_mask_lock_command

    source = _make_clip(tmp_path / "source.mp4", frames, audio_seconds=frames / rate - 0.4, source="testsrc2",
                        rate=rate)
    generated = _make_clip(tmp_path / "generated.mp4", frames, rate=rate)
    protected = str(tmp_path / "protected.mp4")
    _run(_build_recast_mask_lock_command(source, _mask_clip(tmp_path / "mask.mp4", frames, rate), generated,
                                         protected))
    assert _frames(protected) == frames, "Recast protection with padded source audio"

    muxed = str(tmp_path / "generated_post.mp4")
    _did_overlay, command = _run_generation_outpaint_command(
        True, False, False, 0, 0, muxed, generated, {}, True, source, subprocess,
    )
    _run(command)
    assert _frames(muxed) == frames, "Outpaint audio mux (picture copied) with padded source audio"
    assert _audio_seconds(muxed) == pytest.approx(frames / rate, abs=0.1)


# -- Film grain and voice clone: the picture is copied, the audio replaced -----------------------------------------


def _wav(path: Path, seconds: float) -> str:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-t", f"{seconds}", "-i",
                    "sine=frequency=330:sample_rate=22050", str(path)], check=True, capture_output=True)
    return str(path)


def test_voice_clone_keeps_every_frame_when_the_cloned_audio_is_shorter(tmp_path):
    """The video is copied and the converted voice replaces the audio; ``-shortest`` cut the picture to it."""
    _ffmpeg_remux_audio = pytest.importorskip("postprocessing.voice_clone")._ffmpeg_remux_audio

    video = _make_clip(tmp_path / "clip.mp4", FRAMES, audio_seconds=FRAMES / FPS)
    assert _ffmpeg_remux_audio(video, _wav(tmp_path / "cloned.wav", 1.6))
    assert _frames(video) == FRAMES
    assert _audio_seconds(video) == pytest.approx(1.6, abs=0.05)


def test_film_grain_keeps_every_frame_when_the_clip_audio_ends_before_the_picture(tmp_path, monkeypatch):
    """Grain re-encodes the picture and puts the clip's own audio back; ``-shortest`` cut the picture to it."""
    torch = pytest.importorskip("torch")
    decord = pytest.importorskip("decord")
    save_video = pytest.importorskip("shared.utils.audio_video").save_video
    from services import generation_postprocess

    monkeypatch.setattr(generation_postprocess, "wgp", SimpleNamespace(server_config={}))
    video = _make_clip(tmp_path / "clip.mp4", FRAMES, audio_seconds=1.6)
    decord.bridge.set_bridge("torch")
    try:
        generation_postprocess._apply_film_grain_to_file_impl(
            video, 0.3, 0.5, torch=torch, decord=decord, add_film_grain=lambda frames, *_args: frames,
            save_video=save_video,
        )
    finally:
        decord.bridge.set_bridge("native")
    assert _frames(video) == FRAMES
    assert _audio_seconds(video) == pytest.approx(1.6, abs=0.05)
