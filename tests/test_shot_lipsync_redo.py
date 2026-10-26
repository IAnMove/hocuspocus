"""shot.lipsync.redo keeps the original take, scores qa.lipsync, and shows disk size when weights are missing."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from services.lipsync_qa import verdict
from services.production_media_commands import command_catalog, command_handlers
from services.series_library import create_series_episode, create_series_project, read_series_library, write_series_library
from services.shot_lipsync_catalog import files_for, stack_bytes
import services.shot_lipsync_redo as redo
import services.studio_generate as studio


def _handlers(tmp_path):
    return command_handlers(lambda name: str(tmp_path / name), lambda: str(tmp_path / "uploads"))


def _call(tmp_path, payload):
    return asyncio.run(_handlers(tmp_path)["shot.lipsync.redo"]({"version": 1, "input": payload}))


def _production(folder, shot="o05"):
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "gorthak.mp4").write_bytes(b"original-video")
    (folder / "song.wav").write_bytes(b"original-audio")
    (folder / "mv.shots.json").write_text(json.dumps({
        "version": 1, "production_id": "mv",
        "shots": [{"key": shot, "start": 1, "end": 4, "clip": "gorthak.mp4",
                   "takes": [{"file": "gorthak.mp4", "take": 1}]}],
    }), encoding="utf-8")
    (folder / "mv.production.json").write_text(json.dumps({
        "song": {"file": "song.wav"},
        "clips": {shot: {"file": "gorthak.mp4"}},
        "takes": {shot: [{"file": "gorthak.mp4", "take": 1}]},
    }), encoding="utf-8")


def _plant(root, engine, skip=()):
    for item in files_for(engine):
        if item["path"] in skip:
            continue
        path = root / item["path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"w")


def _bind(monkeypatch, tmp_path, engine="infinitetalk", measure=None):
    weights = tmp_path / "weights"
    weights.mkdir()
    _plant(weights, engine)
    monkeypatch.setattr(redo, "weights_root", lambda: weights)
    monkeypatch.setattr(redo, "measure_lips", measure or (lambda *_a, **_k: {"verdict": "ok", "best_r": 0.8}))
    seen = []

    def _worker(body, folder):
        seen.append(body)
        path = os.path.join(folder, body["output_name"])
        with open(path, "wb") as handle:
            handle.write(b"new-lips")
        return path

    monkeypatch.setattr(redo, "worker", _worker)
    return seen


def test_missing_weights_report_disk_size_and_leave_other_tools_alone(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    monkeypatch.setattr(redo, "weights_root", lambda: tmp_path / "empty")
    started = []
    monkeypatch.setattr(redo, "start_download", lambda model: started.append(model))
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    detail = denied.value.detail
    assert denied.value.status_code == 409 and detail["code"] == "model_unavailable"
    assert detail["bytes"] == stack_bytes("infinitetalk") and detail["license"] == "Apache-2.0"
    assert detail["model_type"] == "infinitetalk" and started == []
    assert (folder / "gorthak.mp4").read_bytes() == b"original-video"
    assert not list(folder.glob("lipsync*"))
    names = [entry["name"] for entry in command_catalog()]
    assert names[:4] == ["media.frame", "media.compose", "audio.trim", "assets.import_from_workspace"]
    with pytest.raises(HTTPException) as framed:
        asyncio.run(_handlers(tmp_path)["media.frame"]({"version": 1, "input": {"workspace": "film"}}))
    assert set(framed.value.detail) == {"code", "message", "retryable"}


def test_a_file_that_is_present_drops_out_of_the_size_and_a_bare_bin_does_not(tmp_path):
    root = tmp_path / "weights"
    present = "Wan2.1_VAE_bf16.safetensors"
    skip = {item["path"] for item in files_for("longcat_avatar") if item["path"] != present}
    _plant(root, "longcat_avatar", skip=skip)
    (root / "pytorch_model.bin").write_bytes(b"other")
    from services.shot_lipsync_catalog import missing_files
    gap = missing_files("longcat_avatar", root)
    paths = {item["path"] for item in gap}
    assert "Wan2.1_VAE_bf16.safetensors" not in paths
    assert "chinese-wav2vec2-base/pytorch_model.bin" in paths
    assert next(item["license"] for item in gap if str(item["path"]).startswith("longcat_avatar")) == "MIT"
    assert sum(int(item["bytes"]) for item in gap) == stack_bytes("longcat_avatar") - 253_808_213


def test_confirm_download_starts_the_existing_download_and_does_not_wait(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    monkeypatch.setattr(redo, "weights_root", lambda: tmp_path / "empty")
    seen = []
    monkeypatch.setattr(redo, "start_download", lambda model: seen.append(model) or {"status": "downloading", "model_type": model})
    result = _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05",
                               "confirm_download": True})["result"]
    assert result["status"] == "downloading" and result["bytes"] == stack_bytes("infinitetalk")
    assert seen == ["infinitetalk"] and not list(folder.glob("lipsync*"))
    shots = json.loads((folder / "mv.shots.json").read_text())
    assert shots["shots"][0]["clip"] == "gorthak.mp4" and len(shots["shots"][0]["takes"]) == 1


def test_an_unbound_generation_server_does_not_invent_a_take(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    weights = tmp_path / "weights"
    _plant(weights, "infinitetalk")
    monkeypatch.setattr(redo, "weights_root", lambda: weights)
    monkeypatch.setattr(redo, "worker", None)
    monkeypatch.setattr(redo, "trim_span", lambda audio, folder, start, end: audio)
    monkeypatch.setattr(studio, "_new_generation_job", None)
    monkeypatch.setattr(studio, "_jobs", None)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    assert denied.value.status_code == 503 and denied.value.detail["code"] == "generation_unavailable"
    assert set(denied.value.detail) == {"code", "message", "retryable"}
    assert not list(folder.glob("lipsync*"))


@pytest.mark.parametrize("engine,steps,guide,strength", [
    ("infinitetalk", 20, "GUV", 0.7),
])
def test_a_production_shot_gains_a_take_and_keeps_the_original(tmp_path, monkeypatch, engine, steps, guide, strength):
    folder = tmp_path / "film"
    _production(folder)
    scored = {}

    def measure(video, audio, offset, span):
        scored.update(video=video, audio=audio, offset=offset, span=span)
        return {"verdict": "retake", "best_r": 0.1}

    seen = _bind(monkeypatch, tmp_path, engine, measure)

    def trim(audio, dest, start, end):
        scored["span_cut"] = (start, end, audio)
        path = os.path.join(dest, "span.wav")
        with open(path, "wb") as handle:
            handle.write(b"span")
        return path
    monkeypatch.setattr(redo, "trim_span", trim)
    result = _call(tmp_path, {"workspace": "film", "engine": engine, "production_id": "mv", "shot": "o05"})["result"]
    body = seen[0]
    assert os.path.basename(body["video_guide"]) == "gorthak.mp4" and os.path.basename(body["audio_guide"]) == "span.wav"
    assert os.path.isabs(body["video_guide"]) and os.path.isabs(body["audio_guide"])
    assert body["audio_prompt_type"] == "A" and body["video_prompt_type"] == guide
    assert body["resolution"] == "832x480" and body["num_inference_steps"] == steps
    assert body["model_type"] == engine
    if strength is None:
        assert "denoising_strength" not in body
    else:
        assert body["denoising_strength"] == strength
    assert result["verdict"] == "retake" and result["kept_original"] == "gorthak.mp4"
    assert result["file"].startswith(f"lipsync-o05-{engine}")
    assert (folder / "gorthak.mp4").read_bytes() == b"original-video"
    assert scored["span"] == (1.0, 4.0) and scored["audio"].endswith("song.wav")
    shots = json.loads((folder / "mv.shots.json").read_text())["shots"][0]
    state = json.loads((folder / "mv.production.json").read_text())
    assert shots["clip"] == "gorthak.mp4"
    assert [item["file"] for item in shots["takes"]] == ["gorthak.mp4", result["file"]]
    assert state["clips"]["o05"]["file"] == "gorthak.mp4"
    assert state["takes"]["o05"][-1]["file"] == result["file"]
    assert (folder / result["file"]).with_suffix(".meta.json").is_file()


def test_a_locked_shot_is_refused_before_any_take(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    (folder / "mv.review.json").write_text(json.dumps({
        "version": 1, "production_id": "mv", "shots": {"o05": {"locked": True}},
    }), encoding="utf-8")
    _bind(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    assert denied.value.detail["code"] == "shot_locked"
    assert not list(folder.glob("lipsync*"))


def test_a_bare_clip_keeps_a_list_of_the_original_and_the_new_take(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _movie(folder, "closeup.mp4", 1)
    original = (folder / "closeup.mp4").read_bytes()
    (folder / "voice.wav").write_bytes(b"wav")
    _bind(monkeypatch, tmp_path)
    result = _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "closeup.mp4", "audio": "voice.wav"})["result"]
    listed = json.loads((folder / "closeup.lipsync-takes.json").read_text())
    assert listed["original"] == "closeup.mp4"
    assert [item["file"] for item in listed["takes"]] == ["closeup.mp4", result["file"]]
    assert (folder / "closeup.mp4").read_bytes() == original
    assert result["verdict"] == "ok"


def test_a_series_shot_appends_a_take_and_keeps_the_approval(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    folder.mkdir()
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series_id, episode_id = series["id"], episode["id"]
    relative = f"assets/{series_id}/original.mp4"
    _movie((folder / relative).parent, "original.mp4", 1)
    approved = (folder / relative).read_bytes()
    (folder / "voice.wav").write_bytes(b"wav")
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{
        "id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
        "durationSeconds": 8, "prompt": "Gorthak sings", "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"], "model": "infinitetalk"}],
    }]
    series["episodesById"][episode_id] = episode
    series["assets"] = {"asset-1": {
        "id": "asset-1", "workspaceId": "film", "kind": "video", "uri": relative,
        "ownerType": "attempt", "ownerId": "attempt-1", "isDerivedThumbnail": False, "metadata": {},
    }}
    write_series_library(str(folder), {"workspaceId": "film", "seriesById": {series_id: series}, "seriesOrder": [series_id]}, "film")
    _bind(monkeypatch, tmp_path)
    result = _call(tmp_path, {
        "workspace": "film", "engine": "infinitetalk", "series_id": series_id, "episode_id": episode_id,
        "shot": "s1", "audio": "voice.wav",
    })["result"]
    saved = read_series_library(str(folder), "film")["seriesById"][series_id]
    shot = saved["episodesById"][episode_id]["shots"][0]
    assert shot["approvedAttemptId"] == "attempt-1"
    assert len(shot["attempts"]) == 2 and shot["attempts"][1]["status"] == "completed"
    assert shot["attempts"][1]["id"] == result["attempt_id"]
    assert (folder / relative).read_bytes() == approved
    assert (folder / result["asset"]).is_file()
    assert result["verdict"] == "ok" and result["kept_original"] == "original.mp4"


def test_bad_input_is_refused(tmp_path):
    folder = tmp_path / "film"
    _production(folder)
    with pytest.raises(HTTPException) as engine:
        _call(tmp_path, {"workspace": "film", "engine": "rhubarb", "production_id": "mv", "shot": "o05"})
    assert engine.value.detail["code"] == "invalid_command"
    with pytest.raises(HTTPException) as both:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05", "clip": "gorthak.mp4"})
    assert both.value.detail["code"] == "invalid_command"
    with pytest.raises(HTTPException) as span:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "gorthak.mp4", "audio": "song.wav", "span": [4, 1]})
    assert "span" in span.value.detail["message"]


def test_a_qa_failure_still_keeps_the_take_and_says_unreliable(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _movie(folder, "closeup.mp4", 1)
    original = (folder / "closeup.mp4").read_bytes()
    (folder / "voice.wav").write_bytes(b"wav")
    _bind(monkeypatch, tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("pose model missing")

    monkeypatch.setattr(redo, "measure_lips", explode)
    result = _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "closeup.mp4", "audio": "voice.wav"})["result"]
    assert result["verdict"] == "unreliable" and result["qa"]["reason"] == "qa_unavailable"
    assert (folder / result["file"]).is_file() and (folder / "closeup.mp4").read_bytes() == original


def test_lipsync_verdict_thresholds():
    assert verdict(0.9, 0.5, 0.0) == "ok"
    assert verdict(0.9, 0.1, 0.0) == "retake"
    assert verdict(0.1, 0.9, 0.0) == "unreliable"


def _generate_video_params() -> set[str]:
    import ast
    tree = ast.parse((Path(__file__).resolve().parents[1] / "app" / "wgp.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "generate_video":
            return {arg.arg for arg in node.args.args} | {arg.arg for arg in node.args.kwonlyargs}
    raise AssertionError("generate_video is missing")


def _movie(folder, name: str, seconds: float) -> None:
    import subprocess
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s=32x32:r=25:d={seconds}",
         "-f", "lavfi", "-i", "anullsrc=r=16000:cl=mono", "-t", f"{seconds}",
         "-c:v", "mpeg4", "-c:a", "pcm_s16le", str(folder / name)],
        check=True, capture_output=True,
    )


def test_a_clip_without_a_span_lasts_as_long_as_the_source(tmp_path, monkeypatch):
    """video_length(span=None) is the sliding window, whatever the take lasts."""
    folder = tmp_path / "film"
    _movie(folder, "closeup.mp4", 4)
    (folder / "voice.wav").write_bytes(b"wav")
    seen = _bind(monkeypatch, tmp_path)
    _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "closeup.mp4", "audio": "voice.wav"})
    assert seen[0]["video_length"] == 100


def test_a_series_shot_without_a_span_lasts_as_long_as_the_source(tmp_path, monkeypatch):
    """A series shot with no span also stays on the sliding window."""
    folder = tmp_path / "film"
    folder.mkdir()
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series_id, episode_id = series["id"], episode["id"]
    relative = f"assets/{series_id}/original.mp4"
    _movie((folder / relative).parent, "original.mp4", 4)
    (folder / "voice.wav").write_bytes(b"wav")
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{
        "id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
        "durationSeconds": 8, "prompt": "Gorthak sings", "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"], "model": "infinitetalk"}],
    }]
    series["episodesById"][episode_id] = episode
    series["assets"] = {"asset-1": {
        "id": "asset-1", "workspaceId": "film", "kind": "video", "uri": relative,
        "ownerType": "attempt", "ownerId": "attempt-1", "isDerivedThumbnail": False, "metadata": {},
    }}
    write_series_library(str(folder), {"workspaceId": "film", "seriesById": {series_id: series}, "seriesOrder": [series_id]}, "film")
    seen = _bind(monkeypatch, tmp_path)
    _call(tmp_path, {
        "workspace": "film", "engine": "infinitetalk", "series_id": series_id, "episode_id": episode_id,
        "shot": "s1", "audio": "voice.wav",
    })
    assert seen[0]["video_length"] == 100


def test_a_span_that_starts_late_is_scored_from_that_start(tmp_path, monkeypatch):
    """The take is the span, so frame 0 is span start. offset 0 scores the song from the beginning."""
    folder = tmp_path / "film"
    _production(folder)
    shots = json.loads((folder / "mv.shots.json").read_text())
    shots["shots"][0]["start"], shots["shots"][0]["end"] = 45, 50
    (folder / "mv.shots.json").write_text(json.dumps(shots), encoding="utf-8")
    scored = {}

    def measure(_video, _audio, offset, span):
        scored.update(offset=offset, span=span)
        return {"verdict": "ok", "best_r": 0.8}

    _bind(monkeypatch, tmp_path, measure=measure)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    from services.lipsync_qa import _frame_bounds
    i0, i1 = _frame_bounds(80, 25.0, scored["offset"], scored["span"])
    assert scored["offset"] == 45.0 and scored["span"] == (45.0, 50.0)
    assert i0 == 0 and i1 > i0
    described = redo.catalog()["inputSchema"]["properties"]["input"]["properties"]["offset"]["description"]
    assert "span" in described


def test_infinitetalk_sends_force_fps_and_counts_the_span_at_that_rate(tmp_path, monkeypatch):
    """generate_video has force_fps and no fps. A 5 s span at 16 fps is clamped to the 81-frame window."""
    folder = tmp_path / "film"
    folder.mkdir()
    (folder / "closeup.mp4").write_bytes(b"orig")
    (folder / "voice.wav").write_bytes(b"wav")
    seen = _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "closeup.mp4", "audio": "voice.wav", "span": [0, 5]})
    body = seen[0]
    accepted = _generate_video_params()
    assert "force_fps" in accepted and "fps" not in accepted and body.get("fps") not in accepted
    filtered = {key: value for key, value in body.items() if key in accepted}
    assert filtered["force_fps"] == "25"
    assert body["video_length"] == 125


def test_longcat_avatar_is_not_a_redo_engine(tmp_path, monkeypatch):
    """LongCat generate() declares input_frames and never reads it, so video_prompt_type V does not follow the shot."""
    folder = tmp_path / "film"
    _production(folder)
    _bind(monkeypatch, tmp_path, "longcat_avatar")
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "longcat_avatar", "production_id": "mv", "shot": "o05"})
    assert denied.value.detail["code"] == "invalid_command"
    assert "longcat_avatar" in denied.value.detail["message"]
    assert not list(folder.glob("lipsync*"))
    assert any(item["path"].startswith("longcat_avatar") for item in files_for("longcat_avatar"))


def test_guides_stay_files_after_the_real_infinitetalk_prepare(tmp_path, monkeypatch):
    """Relative names never reach a model that is not wangp_1272: prepare leaves them, and the worker looks in cwd."""
    folder = tmp_path / "film"
    _production(folder)
    seen = _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    body = dict(seen[0])
    model = json.loads((Path(__file__).resolve().parents[1] / "app" / "defaults" / "infinitetalk.json").read_text())["model"]
    assert not model.get("wangp_1272")
    from services.wangp_submission import prepare_generation_inputs
    prepare_generation_inputs(body, model, "film", uploads_dir=str(tmp_path / "uploads"), workspace_dir=str(folder))
    assert os.path.isabs(body["video_guide"]) and os.path.isfile(body["video_guide"])
    assert os.path.isabs(body["audio_guide"]) and os.path.isfile(body["audio_guide"])


def _tone(folder, name: str, seconds: float) -> None:
    import subprocess
    folder.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=frequency=440:duration={seconds}",
         "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(folder / name)],
        check=True, capture_output=True,
    )


def _rms(path: str, start: float, dur: float) -> float:
    import struct
    import wave
    with wave.open(path) as handle:
        handle.setpos(int(start * handle.getframerate()))
        raw = handle.readframes(int(dur * handle.getframerate()))
    samples = struct.unpack("<" + "h" * (len(raw) // 2), raw)
    return (sum(value * value for value in samples) / len(samples)) ** 0.5


def test_a_series_shot_uses_the_recorded_line_not_the_score(tmp_path, monkeypatch):
    """The score cue is background music from t=0. The mouth follows the line, delayed by its intro."""
    folder = tmp_path / "film"
    folder.mkdir()
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series_id, episode_id = series["id"], episode["id"]
    relative = f"assets/{series_id}/original.mp4"
    _movie((folder / relative).parent, "original.mp4", 4)
    _tone(folder, "mus-theme.wav", 1)
    _tone(folder, f"ln-{episode_id}-b0-k.wav", 1)
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{
        "id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
        "durationSeconds": 8, "prompt": "Gorthak speaks", "approvedAttemptId": "attempt-1",
        "dialogueBeats": [{"id": "b0", "characterId": "gorthak", "text": "Hello."}],
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"], "model": "infinitetalk"}],
    }]
    episode["score"] = [{"fromShotId": "s1", "toShotId": "s1", "file": "mus-theme.wav", "volume": 0.18}]
    series["characters"] = [{"id": "gorthak", "name": "Gorthak"}]
    series["episodesById"][episode_id] = episode
    series["assets"] = {"asset-1": {
        "id": "asset-1", "workspaceId": "film", "kind": "video", "uri": relative,
        "ownerType": "attempt", "ownerId": "attempt-1", "isDerivedThumbnail": False, "metadata": {},
    }}
    write_series_library(str(folder), {"workspaceId": "film", "seriesById": {series_id: series}, "seriesOrder": [series_id]}, "film")
    seen = _bind(monkeypatch, tmp_path)
    _call(tmp_path, {
        "workspace": "film", "engine": "infinitetalk", "series_id": series_id, "episode_id": episode_id, "shot": "s1",
    })
    guide = seen[0]["audio_guide"]
    assert os.path.basename(guide) != "mus-theme.wav"
    assert _rms(guide, 0.0, 0.2) < 200
    assert _rms(guide, 0.5, 0.2) > 1000


def test_a_series_shot_without_a_line_asks_for_audio(tmp_path, monkeypatch):
    """No recorded line: do not drive the mouth with the score cue."""
    folder = tmp_path / "film"
    folder.mkdir()
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series_id, episode_id = series["id"], episode["id"]
    relative = f"assets/{series_id}/original.mp4"
    _movie((folder / relative).parent, "original.mp4", 1)
    _tone(folder, "mus-theme.wav", 1)
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{
        "id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
        "durationSeconds": 8, "prompt": "Gorthak speaks", "approvedAttemptId": "attempt-1",
        "dialogueBeats": [{"id": "b0", "characterId": "gorthak", "text": "Hello."}],
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"], "model": "infinitetalk"}],
    }]
    episode["score"] = [{"fromShotId": "s1", "toShotId": "s1", "file": "mus-theme.wav", "volume": 0.18}]
    series["characters"] = [{"id": "gorthak", "name": "Gorthak"}]
    series["episodesById"][episode_id] = episode
    series["assets"] = {"asset-1": {
        "id": "asset-1", "workspaceId": "film", "kind": "video", "uri": relative,
        "ownerType": "attempt", "ownerId": "attempt-1", "isDerivedThumbnail": False, "metadata": {},
    }}
    write_series_library(str(folder), {"workspaceId": "film", "seriesById": {series_id: series}, "seriesOrder": [series_id]}, "film")
    _bind(monkeypatch, tmp_path)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {
            "workspace": "film", "engine": "infinitetalk", "series_id": series_id, "episode_id": episode_id, "shot": "s1",
        })
    assert denied.value.detail["code"] == "audio_required"


def test_a_second_redo_of_the_same_take_is_already_running(tmp_path, monkeypatch):
    """A second click while the first generation is in flight must not queue another 14B job."""
    import threading
    folder = tmp_path / "film"
    _production(folder)
    started = threading.Event()
    entered = []

    def _worker(body, dest):
        entered.append(body["output_name"])
        started.set()
        threading.Event().wait(0.3)
        path = os.path.join(dest, body["output_name"])
        with open(path, "wb") as handle:
            handle.write(b"new-lips")
        return path

    _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(redo, "worker", _worker)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    payload = {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05", "source": "gorthak.mp4"}
    first = threading.Thread(target=lambda: _call(tmp_path, payload))
    first.start()
    assert started.wait(5)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, payload)
    assert denied.value.status_code == 409 and denied.value.detail["code"] == "already_running"
    first.join(5)
    assert len(entered) == 1


def _series_film(folder):
    folder.mkdir(parents=True, exist_ok=True)
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series_id, episode_id = series["id"], episode["id"]
    relative = f"assets/{series_id}/original.mp4"
    (folder / relative).parent.mkdir(parents=True, exist_ok=True)
    (folder / relative).write_bytes(b"approved-take")
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{
        "id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
        "durationSeconds": 8, "prompt": "Gorthak sings", "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"], "model": "infinitetalk"}],
    }]
    series["episodesById"][episode_id] = episode
    series["assets"] = {"asset-1": {
        "id": "asset-1", "workspaceId": "film", "kind": "video", "uri": relative,
        "ownerType": "attempt", "ownerId": "attempt-1", "isDerivedThumbnail": False, "metadata": {},
    }}
    write_series_library(str(folder), {"workspaceId": "film", "seriesById": {series_id: series}, "seriesOrder": [series_id]}, "film")
    return series_id, episode_id


def test_a_running_production_is_not_rewritten(tmp_path, monkeypatch):
    """Music and Director occupy the edit slot. A lip redo must not write shots.json over them."""
    folder = tmp_path / "film"
    _production(folder)
    _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    monkeypatch.setattr("services.director.pipeline_locks.director_holds_production", lambda _production_id: True)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    assert denied.value.detail["code"] == "already_running"
    shots = json.loads((folder / "mv.shots.json").read_text())
    assert len(shots["shots"][0]["takes"]) == 1 and "revision" not in shots


def test_a_stale_shot_revision_is_refused(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05", "expected_revision": 4})
    assert denied.value.detail["code"] == "stale_revision"


def test_a_saved_take_bumps_the_shot_revision(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    _bind(monkeypatch, tmp_path)
    monkeypatch.setattr(redo, "trim_span", lambda audio, _dest, _start, _end: audio)
    _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "production_id": "mv", "shot": "o05"})
    assert json.loads((folder / "mv.shots.json").read_text())["revision"] == 1


def test_a_missing_series_shot_is_refused_before_the_copy(tmp_path):
    folder = tmp_path / "film"
    series_id, episode_id = _series_film(folder)
    (folder / "out.mp4").write_bytes(b"new")
    before = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
    from services.production_media_common import MediaToolError
    from services.shot_lipsync_save import save_series
    with pytest.raises(MediaToolError) as denied:
        save_series(str(folder), "film", {
            "series_id": series_id, "episode_id": episode_id, "shot": "missing", "original_name": "original.mp4",
        }, str(folder / "out.mp4"), {"verdict": "ok"}, "infinitetalk")
    assert denied.value.code == "shot_not_found"
    after = {path.relative_to(folder).as_posix() for path in folder.rglob("*") if path.is_file()}
    assert after == before


def test_a_series_save_uses_the_library_lock(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    series_id, episode_id = _series_film(folder)
    (folder / "out.mp4").write_bytes(b"new")
    held = []

    class _Lock:
        def __enter__(self):
            held.append(True)
            return self

        def __exit__(self, *_args):
            return False

    from routers import series_library as routes
    monkeypatch.setattr(routes, "_library_lock", _Lock(), raising=False)
    from services.shot_lipsync_save import save_series
    save_series(str(folder), "film", {
        "series_id": series_id, "episode_id": episode_id, "shot": "s1", "original_name": "original.mp4", "video": "original.mp4",
    }, str(folder / "out.mp4"), {"verdict": "ok"}, "infinitetalk")
    assert held == [True]


def test_a_failed_generation_names_the_job_error(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    folder.mkdir()
    jobs = {"job-1": {"status": "failed", "error": "weights missing"}}

    async def generate(_request):
        return {"job_id": "job-1"}

    monkeypatch.setattr(studio, "generate", generate)
    monkeypatch.setattr(studio, "_new_generation_job", object())
    monkeypatch.setattr(studio, "_jobs", jobs)
    monkeypatch.setattr(redo.time, "sleep", lambda _seconds: None)
    from services.production_media_common import MediaToolError
    with pytest.raises(MediaToolError) as denied:
        redo._server_queue({"model_type": "infinitetalk"}, str(folder))
    assert "weights missing" in denied.value.message
