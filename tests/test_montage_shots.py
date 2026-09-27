"""Shot board: provenance from generation sidecars, regeneration as takes, take selection."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from services.montage_commands import MontageCommands, command_catalog
from services.montage_documents import MontageError, MontageStore, normalize_montage
from services.montage_shots import ShotBoard, _atempo, timeline_slots

WS = "x-song"
FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")
pytestmark = pytest.mark.skipif(not FFMPEG, reason="ffmpeg is required")


def _video(path: Path, seconds: float, *, audio: bool = False) -> None:
    command = ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=blue:s=64x36:r=24:d={seconds}"]
    if audio:
        command += ["-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}", "-c:a", "aac"]
    command += ["-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)]
    subprocess.run(command, check=True)


def _sidecar(root: Path, video: str, *, job: str, prompt: str = "Rockets ignite", seed: int = 8906) -> None:
    (root / "start.png").write_bytes(b"png")
    meta = {"schema": "hocuspocus.asset-manifest", "schema_version": 1, "output_filename": video,
            "asset": {"filename": video}, "origin": {"capability": "generate", "tool": "external_agent"},
            "execution": {"job_id": job, "status": "completed"},
            "generation": {"model": {"id": "minimax_h3_fused_turbo"}, "prompts": {"effective": prompt},
                           "parameters": {"_execution_mode": "real", "provider": "local", "model_type": "minimax_h3_fused_turbo",
                                          "prompt": prompt, "seed": seed, "image_start": str(root / "start.png"),
                                          "resolution": "1280x720", "video_length": 97, "generation_mode": "video"}}}
    (root / Path(video).with_suffix(".meta.json").name).write_text(json.dumps(meta))


@pytest.fixture()
def board(tmp_path):
    root = tmp_path / WS
    root.mkdir()
    _video(root / "shot1.mp4", 2)
    _video(root / "shot2.mp4", 1)
    _video(root / "shot2_retimed2.00x.mp4", 2)
    _sidecar(root, "shot1.mp4", job="job-1")
    _sidecar(root, "shot2.mp4", job="job-2", prompt="Birds fly")
    store = MontageStore(lambda name: str(tmp_path / name))
    montage = {"version": 1, "name": "Bird", "width": 320, "height": 240, "fps": 24, "clips": [
        {"id": "s1", "source": "shot1.mp4", "trimEnd": 2, "transition": "crossfade", "transitionDuration": 0.5,
         "origin": {"kind": "generation"}},
        {"id": "s2", "source": "shot2_retimed2.00x.mp4", "trimEnd": 1.5,
         "origin": {"kind": "render", "note": "shot2.mp4 slowed 2.00x to cover its slot"}},
    ]}
    store.save(WS, montage)
    submitted = []

    async def submit(params):
        submitted.append(params)
        return {"job_id": "job-new"}

    shots = ShotBoard(store, workspace_dir=lambda name: str(tmp_path / name), submit=submit, job_status=lambda job: None)
    return shots, store, root, submitted


def test_contract_keeps_takes_and_extended_origin():
    doc = normalize_montage({"version": 1, "name": "x", "clips": [{"source": "a.mp4", "lyric": "la la",
        "origin": {"kind": "production", "productionId": "p1", "shotId": "3", "takeId": "t", "meta": "a.meta.json"},
        "takes": [{"id": "t1", "source": "b.mp4"}, {"id": "t2", "pending": {"jobId": "j", "intentId": "i"}}]}]})
    clip = doc["clips"][0]
    assert clip["origin"]["productionId"] == "p1" and clip["lyric"] == "la la"
    assert clip["takes"][1] == {"id": "t2", "pending": {"jobId": "j", "intentId": "i"}}
    with pytest.raises(MontageError):
        normalize_montage({"version": 1, "name": "x", "clips": [{"source": "a.mp4", "takes": [{"id": "t", "source": "blob:x"}]}]})
    with pytest.raises(MontageError):
        normalize_montage({"version": 1, "name": "x", "clips": [{"source": "a.mp4", "takes": [{"id": "t", "source": "a"}] * 2}]})


def test_timeline_slots_overlap_crossfades():
    clips = [{"trimEnd": 2, "transition": "crossfade", "transitionDuration": 0.5}, {"trimEnd": 1.5}]
    assert timeline_slots(clips, lambda clip: 0) == [(0, 2), (1.5, 3)]


def test_shots_read_provenance_from_sidecars(board):
    shots, *_ = board
    view = shots.shots(WS, "Bird.montage.json")
    first, second = view["shots"]
    assert (first["start"], first["end"], second["start"], second["end"]) == (0, 2, 1.5, 3.0)
    assert first["provenance"]["prompt"] == "Rockets ignite" and first["provenance"]["seed"] == 8906
    assert first["provenance"]["startImage"]["name"] == "start.png" and first["provenance"]["canRegenerate"]
    # A slowed copy points back at the generated clip and its parameters.
    assert second["provenance"]["generatedFrom"] == "shot2.mp4" and second["provenance"]["prompt"] == "Birds fly"


def test_regenerate_queues_a_pending_take_with_original_parameters(board):
    shots, store, root, submitted = board
    result = asyncio.run(shots.regenerate(WS, "Bird.montage.json", "s1", intent_id="regen-1", expected_revision=1,
                                          prompt="Rockets ignite at night"))
    params = submitted[0]
    assert params["prompt"] == "Rockets ignite at night" and params["seed"] != 8906 and params["workspace"] == WS
    assert "_execution_mode" not in params and "provider" not in params and params["image_start"].endswith("start.png")
    assert params["provenance"]["command"]["command_id"] == "regen-1"
    assert result["revision"] == 2 and result["take"]["pending"]["jobId"] == "job-new"
    with pytest.raises(MontageError) as stale:
        asyncio.run(shots.regenerate(WS, "Bird.montage.json", "s1", intent_id="regen-2", expected_revision=1))
    assert stale.value.code == "revision_conflict"
    # Once the generation writes its output and sidecar, the take resolves.
    _video(root / "shot1b.mp4", 1)
    _sidecar(root, "shot1b.mp4", job="job-new", prompt="Rockets ignite at night")
    take = shots.shots(WS, "Bird.montage.json")["shots"][0]["takes"][0]
    assert take["status"] == "completed" and take["source"] == "shot1b.mp4"


def test_regenerate_needs_parameters_and_inputs(board):
    shots, store, root, _ = board
    (root / "shot1.meta.json").unlink()
    with pytest.raises(MontageError) as missing:
        asyncio.run(shots.regenerate(WS, "Bird.montage.json", "s1", intent_id="r", expected_revision=1))
    assert missing.value.code == "not_regenerable"
    (root / "start.png").unlink()
    with pytest.raises(MontageError) as gone:
        asyncio.run(shots.regenerate(WS, "Bird.montage.json", "s2", intent_id="r", expected_revision=1))
    assert gone.value.code == "missing_input"


def test_select_swaps_media_keeps_history_and_retimes_short_takes(board):
    shots, store, root, _ = board
    asyncio.run(shots.regenerate(WS, "Bird.montage.json", "s1", intent_id="regen-1", expected_revision=1))
    with pytest.raises(MontageError) as pending:
        shots.select(WS, "Bird.montage.json", "s1", "take-job-new", expected_revision=2)
    assert pending.value.code == "take_pending"
    _video(root / "shot1b.mp4", 1)
    _sidecar(root, "shot1b.mp4", job="job-new")
    result = shots.select(WS, "Bird.montage.json", "s1", "take-job-new", expected_revision=2)
    clip = store.get(WS, "Bird.montage.json")["montage"]["clips"][0]
    assert result["revision"] == 3 and clip["source"].startswith("shot1b_retimed") and clip["trimEnd"] == 2
    assert clip["origin"] == {"kind": "render", "derivedFrom": "shot1b.mp4", "note": clip["origin"]["note"]}
    assert clip["takes"][0]["source"] == "shot1.mp4" and clip["takes"][0]["note"] == "previous selection"
    assert (root / clip["source"]).is_file()


def test_select_keeps_audio_when_a_short_take_is_slowed(board):
    shots, store, root, _ = board
    asyncio.run(shots.regenerate(WS, "Bird.montage.json", "s1", intent_id="regen-1", expected_revision=1))
    _video(root / "shot1b.mp4", 1, audio=True)
    _sidecar(root, "shot1b.mp4", job="job-new")
    shots.select(WS, "Bird.montage.json", "s1", "take-job-new", expected_revision=2)
    clip = store.get(WS, "Bird.montage.json")["montage"]["clips"][0]
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(root / clip["source"])],
        capture_output=True, text=True, check=True,
    )
    assert probe.stdout.strip()
    loud = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(root / clip["source"]), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    mean = loud.split("mean_volume:")[1][:12]
    assert "mean_volume" in loud and "-inf" not in mean and "-91" not in mean


def test_atempo_stays_inside_ffmpeg_limits():
    assert _atempo(1.0) == "atempo=1.000000"
    assert _atempo(0.45) == "atempo=0.5,atempo=0.900000"
    assert _atempo(0.02).startswith("atempo=0.5")
    assert all(0.5 <= float(part.split("=")[1]) <= 2.0 for part in _atempo(0.02).split(","))


def test_commands_expose_the_board():
    names = {item["name"] for item in command_catalog()}
    assert {"montages.shots.get", "montages.shot.regenerate", "montages.shot.select"} <= names


def test_regenerate_runs_through_async_commands(board):
    shots, store, *_ = board
    commands = MontageCommands(store, start_export=lambda body: {}, get_export=lambda job: {}, shots=shots)
    out = asyncio.run(commands.execute_async("montages.shot.regenerate", {"version": 1, "input": {
        "workspace": WS, "file": "Bird.montage.json", "clip_id": "s1", "intent_id": "i-1", "expected_revision": 1}}))
    assert out["result"]["jobId"] == "job-new"
    listed = asyncio.run(commands.execute_async("montages.shots.get", {"version": 1, "input": {"workspace": WS, "file": "Bird.montage.json"}}))
    assert listed["result"]["shots"][0]["takes"][0]["status"] == "queued"
