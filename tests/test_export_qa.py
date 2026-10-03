"""Synthetic-media probes for qa.export. Warnings never block."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from services.export_qa import command_handlers, probe
from services.export_receipts import project_export_receipt

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
FPS = 25
FRAME = 1 / FPS


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60)


def _video(path: Path, *graphs: str, audio: str | None = None) -> None:
    command = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for graph in graphs:
        command.extend(["-f", "lavfi", "-i", graph])
    if audio:
        command.extend(["-f", "lavfi", "-i", audio])
    count = len(graphs)
    if count > 1:
        command.extend(["-filter_complex", "".join(f"[{index}:v]" for index in range(count)) + f"concat=n={count}:v=1:a=0[v]", "-map", "[v]"])
    if audio:
        if count == 1:
            command.extend(["-map", "0:v", "-map", "1:a"])
        else:
            command.extend(["-map", f"{count}:a"])
        command.extend(["-c:a", "aac", "-b:a", "160k", "-shortest"])
    else:
        command.append("-an")
    command.extend(["-c:v", "libx264", "-pix_fmt", "yuv420p", "-r", str(FPS), str(path)])
    _run(command)


def _tone(path: Path, volume: str) -> None:
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", f"sine=frequency=1000:sample_rate=48000:duration=3,volume={volume}",
        "-c:a", "pcm_s16le", str(path),
    ])


def _codes(path: Path, **kwargs: object) -> list[str]:
    return [item["code"] for item in probe(str(path), **kwargs)["warnings"]]


def test_one_second_of_black_is_within_one_frame(tmp_path: Path):
    path = tmp_path / "black.mp4"
    _video(
        path,
        f"color=c=black:s=320x180:r={FPS}:d=1",
        f"testsrc2=s=320x180:r={FPS}:d=1",
    )
    report = probe(str(path))
    black = next(item for item in report["warnings"] if item["code"] == "black")
    assert abs(black["t"] - 0) <= FRAME
    assert abs(black["evidence"]["end"] - 1) <= FRAME
    assert report["verdict"] == "fail"
    assert probe(str(path))["warnings"] == report["warnings"]


def test_two_second_freeze_is_dropped_when_the_shot_allows_still(tmp_path: Path):
    path = tmp_path / "freeze.mp4"
    _video(
        path,
        f"testsrc2=s=320x180:r={FPS}:d=1",
        f"color=c=0x406080:s=320x180:r={FPS}:d=2",
        f"testsrc2=s=320x180:r={FPS}:d=1",
    )
    assert "frozen" in _codes(path)
    allowed = _codes(path, shots=[{"start": 0.9, "end": 3.1, "allow": ["still"]}])
    assert "frozen" not in allowed


def test_full_scale_sine_is_clipping_and_quiet_sine_is_too_quiet(tmp_path: Path):
    hot = tmp_path / "hot.wav"
    quiet = tmp_path / "quiet.wav"
    _tone(hot, "18dB")
    _tone(quiet, "-9dB")
    hot_report = probe(str(hot))
    assert "clipping" in _codes(hot)
    assert hot_report["measured"]["peak_db"] >= -0.5
    quiet_report = probe(str(quiet), target_lufs=-14)
    assert "too_quiet" in _codes(quiet, target_lufs=-14)
    assert quiet_report["measured"]["lufs"] <= -30
    assert "fps" not in quiet_report["measured"]


def test_hard_cut_inside_one_shot_is_a_camera_jump(tmp_path: Path):
    path = tmp_path / "cut.mp4"
    _video(path, f"testsrc2=s=320x180:r={FPS}:d=1", f"testsrc=s=320x180:r={FPS}:d=1")
    inside = probe(str(path), shots=[{"start": 0, "end": 2, "slot": "wide"}])
    jump = next(item for item in inside["warnings"] if item["code"] == "camera_jump")
    assert jump["slot"] == "wide"
    assert abs(jump["t"] - 1) <= 2 * FRAME
    split = _codes(path, shots=[{"start": 0, "end": 1}, {"start": 1, "end": 2}])
    assert "camera_jump" not in split


def test_three_clean_references_have_no_warnings(tmp_path: Path):
    sources = [
        (f"testsrc2=s=320x180:r={FPS}:d=2", "sine=frequency=440:sample_rate=48000:duration=2,volume=7dB"),
        (f"testsrc=s=320x180:r={FPS}:d=2", "sine=frequency=660:sample_rate=48000:duration=2,volume=7dB"),
        (f"color=c=0x4080c0:s=320x180:r={FPS}:d=2,hue=h=n*12", "sine=frequency=880:sample_rate=48000:duration=2,volume=7dB"),
    ]
    for index, (picture, audio) in enumerate(sources):
        path = tmp_path / f"clean-{index}.mp4"
        _video(path, picture, audio=audio)
        report = probe(str(path), target_lufs=-14)
        assert report["warnings"] == [], report
        assert report["verdict"] == "ok"


def test_duration_and_fps_drift_follow_the_recording_tolerance(tmp_path: Path):
    path = tmp_path / "timed.mp4"
    _video(path, f"testsrc2=s=320x180:r={FPS}:d=2", audio="sine=frequency=440:sample_rate=48000:duration=2,volume=7dB")
    drifted = _codes(path, expected_duration=10, expected_fps=60)
    assert "duration_drift" in drifted
    assert "fps_drift" in drifted


def test_receipt_copies_qa_and_the_command_can_store_it(tmp_path: Path):
    stored = {"version": 1, "status": "queued", "artifacts": [], "result": {"status": "queued"}}
    task = {"status": "completed", "workspace": "promo", "metadata": {"qa": {"verdict": "ok", "warnings": []}}}
    projected = project_export_receipt(stored, task)
    assert projected["qa"]["verdict"] == "ok"
    assert "qa" not in stored
    assert "qa" not in project_export_receipt(stored, {"status": "completed", "metadata": {}})

    path = tmp_path / "clip.wav"
    _tone(path, "18dB")
    saved: list[dict] = []

    def workspace_dir(_name: str) -> str:
        return str(tmp_path)

    def record(_workspace: str, intent_id: str, report: dict) -> None:
        saved.append({"intent_id": intent_id, "verdict": report["verdict"]})

    import asyncio
    handler = command_handlers(workspace_dir, record)["qa.export"]
    result = asyncio.run(handler({
        "version": 1,
        "input": {"workspace": "promo", "file": "clip.wav", "intent_id": "intent-1"},
    }))
    assert result["operation"] == "qa.export"
    assert result["result"]["verdict"] == "fail"
    assert saved == [{"intent_id": "intent-1", "verdict": "fail"}]
