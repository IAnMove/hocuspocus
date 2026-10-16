import shutil
import subprocess
from pathlib import Path

import pytest

from services.series_assembly import episode_assembly_plan
from services.series_take_range import apply_take_ranges


def _series():
    return {
        "assets": {
            "asset-1": {"id": "asset-1", "kind": "video", "uri": "outputs/one.mp4"},
            "asset-2": {"id": "asset-2", "kind": "video", "uri": "outputs/two.mp4"},
        },
    }


def test_episode_assembly_uses_approved_attempts_in_shot_order():
    episode = {"shots": [{
        "id": "shot-2", "order": 2, "approvedAttemptId": "attempt-2",
        "attempts": [{"id": "attempt-2", "status": "completed", "outputAssetIds": ["asset-2"]}],
    }, {
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-old", "status": "completed", "outputAssetIds": ["asset-2"]},
                     {"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"]}],
    }]}

    plan = episode_assembly_plan(_series(), episode)

    assert [item["shotId"] for item in plan] == ["shot-1", "shot-2"]
    assert [item["assetId"] for item in plan] == ["asset-1", "asset-2"]


def test_episode_assembly_requires_every_shot_to_be_approved():
    episode = {"shots": [{"id": "shot-1", "order": 1, "attempts": []}]}
    with pytest.raises(ValueError, match="Approve shot 1"):
        episode_assembly_plan(_series(), episode)


def test_episode_assembly_never_falls_back_to_a_rejected_or_newer_attempt():
    episode = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-approved",
        "attempts": [
            {"id": "attempt-approved", "status": "completed", "outputAssetIds": ["asset-1"]},
            {"id": "attempt-newer", "status": "completed", "reviewDecision": "rejected", "outputAssetIds": ["asset-2"]},
        ],
    }]}
    assert episode_assembly_plan(_series(), episode)[0]["attemptId"] == "attempt-approved"


def test_a_2d_take_brings_its_scene_document_for_subtitles():
    series = _series()
    series["assets"]["asset-1"]["metadata"] = {"sceneFilename": "s01.scene.json"}
    episode = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"]}],
    }, {
        "id": "shot-2", "order": 2, "approvedAttemptId": "attempt-2",
        "attempts": [{"id": "attempt-2", "status": "completed", "outputAssetIds": ["asset-2"]}],
    }]}
    plan = episode_assembly_plan(series, episode)
    assert plan[0]["sceneFilename"] == "s01.scene.json"
    assert "sceneFilename" not in plan[1]


def test_a_take_without_timing_brings_its_shot_lines_for_subtitles():
    """An H3 or imported take has no scene document and no recorded timing: the shot's lines are spread at finishing."""
    series = _series()
    episode = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "dialogueBeats": [{"id": "b0", "characterId": "kevin", "text": "¿Oyes eso?"}, {"id": "b1", "characterId": "gary", "text": " "}],
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"]}],
    }, {
        "id": "shot-2", "order": 2, "approvedAttemptId": "attempt-2",
        "attempts": [{"id": "attempt-2", "status": "completed", "outputAssetIds": ["asset-2"]}],
    }]}
    plan = episode_assembly_plan(series, episode)
    assert plan[0]["dialogueBeats"] == [{"text": "¿Oyes eso?"}], "text only: no timing to copy"
    assert "dialogueBeats" not in plan[1]
    series["assets"]["asset-1"]["metadata"] = {"sceneFilename": "s01.scene.json"}
    assert "dialogueBeats" not in episode_assembly_plan(series, episode)[0], "a scene document carries the real timing"


def test_the_assembly_plan_carries_a_shots_transition():
    episode = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "transitionIn": {"kind": "fade_black", "seconds": 0.5},
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"]}],
    }, {
        "id": "shot-2", "order": 2, "approvedAttemptId": "attempt-2", "transitionIn": {"kind": "cut"},
        "attempts": [{"id": "attempt-2", "status": "completed", "outputAssetIds": ["asset-2"]}],
    }]}
    plan = episode_assembly_plan(_series(), episode)
    assert plan[0]["transitionIn"] == {"kind": "fade_black", "seconds": 0.5}
    assert "transitionIn" not in plan[1]


def _attempt(attempt_id, asset_id, **extra):
    return {"id": attempt_id, "status": "completed", "outputAssetIds": [asset_id], **extra}


def test_the_assembly_plan_keeps_a_named_take_range_and_rejects_a_bad_one():
    episode = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [_attempt("attempt-1", "asset-1", startTimeSeconds=0.5, endTimeSeconds=1.5)],
    }]}
    plan = episode_assembly_plan(_series(), episode)
    assert plan[0]["startTimeSeconds"] == 0.5 and plan[0]["endTimeSeconds"] == 1.5
    bare = episode_assembly_plan(_series(), {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [_attempt("attempt-1", "asset-1")],
    }]})
    assert "startTimeSeconds" not in bare[0] and "endTimeSeconds" not in bare[0]
    library_default = episode_assembly_plan(_series(), {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [_attempt("attempt-1", "asset-1", startTimeSeconds=0, endTimeSeconds=0)],
    }]})
    assert "startTimeSeconds" not in library_default[0], "0 and 0 is the stored default, not a cut"
    bad = {"shots": [{
        "id": "shot-1", "order": 1, "approvedAttemptId": "attempt-1",
        "attempts": [_attempt("attempt-1", "asset-1", startTimeSeconds=2, endTimeSeconds=1)],
    }]}
    with pytest.raises(ValueError, match="Invalid take range"):
        episode_assembly_plan(_series(), bad)


def _lavfi(path: Path, seconds: float, frequency: int) -> None:
    completed = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24",
        "-f", "lavfi", "-i", f"sine=frequency={frequency}:sample_rate=48000",
        "-t", f"{seconds:.3f}", "-r", "24",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le",
        str(path),
    ], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr[-300:]


def _frames(path: Path) -> tuple[int, float, float]:
    completed = subprocess.run([
        "ffprobe", "-v", "error", "-count_frames", "-show_entries",
        "stream=codec_type,nb_read_frames,duration", "-of", "json", str(path),
    ], capture_output=True, text=True, timeout=30)
    assert completed.returncode == 0, completed.stderr[-300:]
    import json
    streams = json.loads(completed.stdout)["streams"]
    video = next(item for item in streams if item["codec_type"] == "video")
    audio = next(item for item in streams if item["codec_type"] == "audio")
    return int(video["nb_read_frames"]), float(video["duration"]), float(audio["duration"])


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg required")
def test_a_trimmed_take_joins_as_its_range_and_a_bad_range_is_refused(tmp_path):
    """One approved take is cut to its range; a take with no range is the original file."""
    from services.core_series_assembly import _hard_concat_filter

    whole = tmp_path / "whole.mov"
    long = tmp_path / "long.mov"
    _lavfi(whole, 2.0, 440)
    _lavfi(long, 2.0, 660)
    original = whole.read_bytes()
    clips = [
        {"uri": "whole.mov"},
        {"uri": "long.mov", "startTimeSeconds": 0.5, "endTimeSeconds": 1.5},
    ]
    paths = apply_take_ranges([str(whole), str(long)], clips, str(tmp_path / "cuts"))
    assert paths[0] == str(whole) and whole.read_bytes() == original, "a take with no range is not re-encoded"
    covered = apply_take_ranges([str(whole)], [{"startTimeSeconds": 0, "endTimeSeconds": 2}], str(tmp_path / "same"))
    assert covered == [str(whole)], "a range that is the whole file is not re-encoded"
    output = tmp_path / "episode.mp4"
    assert _hard_concat_filter(paths, str(output)) is True
    frames, video, audio = _frames(output)
    assert frames == 72 and video == pytest.approx(3.0, abs=1 / 24)
    assert audio == pytest.approx(video, abs=0.05), "the cut keeps picture and sound together"
    with pytest.raises(ValueError, match="Invalid take range"):
        apply_take_ranges([str(long)], [{"startTimeSeconds": 0, "endTimeSeconds": 9}], str(tmp_path / "bad"))
