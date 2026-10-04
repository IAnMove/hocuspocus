"""Platform publish presets: encode args, warnings, and loudness."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.publish_presets import (
    collect_warnings, encode_args, integrated_lufs, loudness_report, loudness_target, loudness_warning,
    loudnorm_usable, publish_command, render_publish, measure_loudnorm,
)


def test_encode_args_follow_the_preset():
    x_args = encode_args("x")
    assert x_args[x_args.index("-profile:v") + 1] == "high"
    assert x_args[x_args.index("-b:a") + 1] == "128k"
    assert encode_args("youtube")[encode_args("youtube").index("-b:a") + 1] == "192k"
    assert encode_args("archive")[encode_args("archive").index("-crf") + 1] == "12"
    assert encode_args("shorts")[encode_args("shorts").index("-b:a") + 1] == "128k"
    assert encode_args("apple")[encode_args("apple").index("-b:a") + 1] == "192k"
    assert encode_args("broadcast")[encode_args("broadcast").index("-crf") + 1] == "18"


def test_warnings_cover_duration_aspect_and_safe_area():
    long_x = collect_warnings(preset="x", width=1920, height=1080, duration=150)
    assert long_x == [{"code": "duration", "limit": 140, "duration": 150}]
    premium = collect_warnings(preset="x", width=1920, height=1080, duration=150, premium=True)
    assert premium == []
    aspect = collect_warnings(preset="youtube", width=1080, height=1920, duration=10)
    assert aspect[0]["code"] == "aspect" and aspect[0]["expected"] == "16:9"
    shorts = collect_warnings(
        preset="shorts", width=1080, height=1920, duration=30,
        overlays=[{"id": "title", "y": 4, "width": 100}, {"id": "ok", "y": 40, "width": 80}],
    )
    assert shorts == [{"code": "safe_area", "ids": ["title"]}]
    assert collect_warnings(preset="archive", width=640, height=480, duration=9999) == []
    assert collect_warnings(preset="apple", width=1080, height=1920, duration=9999) == []
    assert collect_warnings(preset="broadcast", width=640, height=480, duration=10) == []


def _tone(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=3",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(path),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_two_pass_loudnorm_lands_near_minus_14_lufs(tmp_path: Path):
    source = tmp_path / "tone.mp4"
    destination = tmp_path / "tone_x.mp4"
    _tone(source)
    measured = measure_loudnorm(str(source))
    command = render_publish(str(source), str(destination), "x", loudnorm=measured)
    assert "loudnorm=I=-14:TP=-1" in " ".join(command)
    assert abs(integrated_lufs(str(destination)) - (-14.0)) <= 1.0
    report = loudness_report(str(destination), "x")
    assert report["warning"] is None
    assert report["true_peak"] <= -1.0
    preview = publish_command(str(source), str(destination), "x", loudnorm=measured)
    assert "-profile:v" in preview and "high" in preview


def test_publish_check_names_the_target_and_rejects_an_unknown_preset():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routers.publish_presets import create_publish_router

    app = FastAPI()
    app.include_router(create_publish_router(resolve_source=lambda name, _workspace: name, workspace_dir=lambda workspace: workspace))
    client = TestClient(app)
    body = {"width": 1920, "height": 1080, "duration": 8}
    apple = client.post("/api/v1/video-editor/publish-check", json={"preset": "apple", **body})
    assert apple.status_code == 200
    assert apple.json()["loudness"] == {"lufs": -16.0, "true_peak": -1.0}
    assert apple.json()["warnings"] == []
    archive = client.post("/api/v1/video-editor/publish-check", json={"preset": "archive", **body})
    assert archive.status_code == 200
    assert archive.json()["loudness"] is None
    unknown = client.post("/api/v1/video-editor/publish-check", json={"preset": "cinema", **body})
    assert unknown.status_code == 422


def test_archive_skips_loudness_and_a_miss_only_warns():
    assert loudness_target("archive") is None
    command = publish_command("in.mp4", "out.mp4", "archive", loudnorm={"input_i": "-20"})
    assert "-af" not in command
    assert loudness_warning({"lufs": -14.4, "true_peak": -1.2}, (-14.0, -1.0)) is None
    assert loudness_warning({"lufs": -18.0, "true_peak": -4.0}, (-14.0, -1.0))["code"] == "loudness"
    assert loudness_warning({"lufs": -14.0, "true_peak": -0.2}, (-14.0, -1.0))["code"] == "loudness"


def test_silent_loudnorm_measurement_is_not_applied():
    silent = {
        "input_i": "-inf",
        "input_tp": "-inf",
        "input_lra": "0.00",
        "input_thresh": "-70.00",
        "target_offset": "inf",
    }
    assert loudnorm_usable(silent) is False
    assert loudnorm_usable(None) is False
    assert "-af" not in publish_command("in.mp4", "out.mp4", "youtube", loudnorm=silent)
    warning = loudness_warning({"lufs": -70.0, "true_peak": float("-inf")}, (-14.0, -1.0))
    assert warning["code"] == "loudness"
    assert warning["lufs"] == -70.0
    assert warning["true_peak"] is None
    dumped = json.dumps({"loudness": warning}, allow_nan=False)
    assert "Infinity" not in dumped


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
@pytest.mark.parametrize("preset,target", [("youtube", -14.0), ("shorts", -14.0), ("apple", -16.0), ("broadcast", -23.0)])
def test_each_delivery_preset_hits_its_target(tmp_path: Path, preset: str, target: float):
    source = tmp_path / "tone.mp4"
    destination = tmp_path / f"{preset}.mp4"
    _tone(source)
    measured = measure_loudnorm(str(source), preset)
    command = render_publish(str(source), str(destination), preset, loudnorm=measured)
    joined = " ".join(command)
    assert f"loudnorm=I={target:g}:TP=-1" in joined
    report = loudness_report(str(destination), preset)
    assert report["warning"] is None, report
    assert abs(report["lufs"] - target) <= 1.0
    assert report["true_peak"] <= -1.0
    print(f"{preset} lufs={report['lufs']} true_peak={report['true_peak']} target={target}")


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_publish_receipt_stores_the_measured_loudness(tmp_path: Path):
    from routers.publish_presets import publish_file

    source = tmp_path / "tone.mp4"
    _tone(source)
    folder = tmp_path / "ws"
    result = publish_file(
        {"preset": "youtube", "source": source.name, "workspace": "ws", "width": 320, "height": 180, "duration": 3, "loudnorm": True},
        resolve_source=lambda _name, _workspace: str(source),
        workspace_dir=lambda _workspace: str(folder),
    )
    assert abs(result["loudness"]["lufs"] - (-14.0)) <= 1.0
    assert result["loudness"]["true_peak"] <= -1.0
    stored = json.loads((folder / result["sidecar"]).read_text(encoding="utf-8"))
    assert stored["loudness"] == result["loudness"]
    assert stored["warnings"] == []
    print("receipt", stored["loudness"])


def _silent(path: Path) -> None:
    subprocess.run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=black:s=320x180:r=24:d=3",
            "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
            "-shortest", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac",
            str(path),
        ],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=60,
    )


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg required")
def test_silent_editor_export_publishes_and_warns(tmp_path: Path):
    from routers.publish_presets import publish_file

    source = tmp_path / "silent.mp4"
    _silent(source)
    folder = tmp_path / "ws"
    measured = measure_loudnorm(str(source), "youtube")
    assert loudnorm_usable(measured) is False
    result = publish_file(
        {"preset": "youtube", "source": source.name, "workspace": "ws", "width": 320, "height": 180, "duration": 3, "loudnorm": True},
        resolve_source=lambda _name, _workspace: str(source),
        workspace_dir=lambda _workspace: str(folder),
    )
    assert (folder / result["file"]).is_file()
    assert any(item["code"] == "loudness" for item in result["warnings"])
    assert result["loudness"]["true_peak"] is None or result["loudness"]["lufs"] <= -60
    stored = json.loads((folder / result["sidecar"]).read_text(encoding="utf-8"))
    json.dumps(stored, allow_nan=False)
    print("silent receipt", stored["loudness"], stored["warnings"])
