"""shot.lipsync.redo keeps the original take, scores qa.lipsync, and shows disk size when weights are missing."""
from __future__ import annotations

import asyncio
import json
import os

import pytest
from fastapi import HTTPException

from services.lipsync_qa import verdict
from services.production_media_commands import command_catalog, command_handlers
from services.series_library import create_series_episode, create_series_project, read_series_library, write_series_library
from services.shot_lipsync_catalog import files_for, stack_bytes, video_length
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


def test_a_file_that_is_present_drops_out_of_the_size_and_a_bare_bin_does_not(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    _production(folder)
    root = tmp_path / "weights"
    present = "Wan2.1_VAE_bf16.safetensors"
    skip = {item["path"] for item in files_for("longcat_avatar") if item["path"] != present}
    _plant(root, "longcat_avatar", skip=skip)
    (root / "pytorch_model.bin").write_bytes(b"other")
    monkeypatch.setattr(redo, "weights_root", lambda: root)
    with pytest.raises(HTTPException) as denied:
        _call(tmp_path, {"workspace": "film", "engine": "longcat_avatar", "production_id": "mv", "shot": "o05"})
    paths = {item["path"] for item in denied.value.detail["files"]}
    assert "Wan2.1_VAE_bf16.safetensors" not in paths
    assert "chinese-wav2vec2-base/pytorch_model.bin" in paths
    assert denied.value.detail["license"] == "MIT"
    assert denied.value.detail["bytes"] == stack_bytes("longcat_avatar") - 253_808_213


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
    ("longcat_avatar", 30, "V", None),
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
    assert body["video_guide"] == "gorthak.mp4" and body["audio_guide"] == "span.wav"
    assert body["audio_prompt_type"] == "A" and body["video_prompt_type"] == guide
    assert body["resolution"] == "832x480" and body["num_inference_steps"] == steps
    assert body["model_type"] == engine
    assert body["video_length"] == video_length(engine, (1.0, 4.0))
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
    folder.mkdir()
    (folder / "closeup.mp4").write_bytes(b"orig")
    (folder / "voice.wav").write_bytes(b"wav")
    _bind(monkeypatch, tmp_path)
    result = _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "closeup.mp4", "audio": "voice.wav"})["result"]
    listed = json.loads((folder / "closeup.lipsync-takes.json").read_text())
    assert listed["original"] == "closeup.mp4"
    assert [item["file"] for item in listed["takes"]] == ["closeup.mp4", result["file"]]
    assert (folder / "closeup.mp4").read_bytes() == b"orig"
    assert result["verdict"] == "ok"


def test_a_series_shot_appends_a_take_and_keeps_the_approval(tmp_path, monkeypatch):
    folder = tmp_path / "film"
    folder.mkdir()
    series = create_series_project("film", title="Show")
    episode = create_series_episode(series)
    series_id, episode_id = series["id"], episode["id"]
    relative = f"assets/{series_id}/original.mp4"
    (folder / relative).parent.mkdir(parents=True)
    (folder / relative).write_bytes(b"approved-take")
    (folder / "voice.wav").write_bytes(b"wav")
    episode["script"] = [{"id": "scene1", "locationId": ""}]
    episode["shots"] = [{
        "id": "s1", "sceneId": "scene1", "productionMethod": "generated_video", "order": 1,
        "durationSeconds": 15, "prompt": "Gorthak sings", "approvedAttemptId": "attempt-1",
        "attempts": [{"id": "attempt-1", "status": "completed", "outputAssetIds": ["asset-1"], "model": "infinitetalk"}],
    }]
    series["episodesById"][episode_id] = episode
    series["assets"] = {"asset-1": {
        "id": "asset-1", "workspaceId": "film", "kind": "video", "uri": relative,
        "ownerType": "attempt", "ownerId": "attempt-1", "isDerivedThumbnail": False, "metadata": {},
    }}
    write_series_library(str(folder), {"workspaceId": "film", "seriesById": {series_id: series}, "seriesOrder": [series_id]}, "film")
    seen = _bind(monkeypatch, tmp_path, "longcat_avatar")
    result = _call(tmp_path, {
        "workspace": "film", "engine": "longcat_avatar", "series_id": series_id, "episode_id": episode_id,
        "shot": "s1", "audio": "voice.wav",
    })["result"]
    saved = read_series_library(str(folder), "film")["seriesById"][series_id]
    shot = saved["episodesById"][episode_id]["shots"][0]
    assert shot["approvedAttemptId"] == "attempt-1"
    assert len(shot["attempts"]) == 2 and shot["attempts"][1]["status"] == "completed"
    assert shot["attempts"][1]["id"] == result["attempt_id"]
    assert (folder / relative).read_bytes() == b"approved-take"
    assert (folder / result["asset"]).is_file()
    assert result["verdict"] == "ok" and result["kept_original"] == "original.mp4"
    assert shot["durationSeconds"] == 15
    assert seen[0]["video_length"] == video_length("longcat_avatar", None, 15)
    assert seen[0]["video_length"] == 240
    assert seen[0]["audio_guide"] == "voice.wav"


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
    folder.mkdir()
    (folder / "closeup.mp4").write_bytes(b"orig")
    (folder / "voice.wav").write_bytes(b"wav")
    _bind(monkeypatch, tmp_path)

    def explode(*_args, **_kwargs):
        raise RuntimeError("pose model missing")

    monkeypatch.setattr(redo, "measure_lips", explode)
    result = _call(tmp_path, {"workspace": "film", "engine": "infinitetalk", "clip": "closeup.mp4", "audio": "voice.wav"})["result"]
    assert result["verdict"] == "unreliable" and result["qa"]["reason"] == "qa_unavailable"
    assert (folder / result["file"]).is_file() and (folder / "closeup.mp4").read_bytes() == b"orig"


def test_lipsync_verdict_thresholds():
    assert verdict(0.9, 0.5, 0.0) == "ok"
    assert verdict(0.9, 0.1, 0.0) == "retake"
    assert verdict(0.1, 0.9, 0.0) == "unreliable"


def test_video_length_follows_a_series_shot_when_span_is_omitted():
    assert video_length("infinitetalk", None) == 81
    assert video_length("infinitetalk", None, 10) == 160
    assert video_length("infinitetalk", None, 15) == 240
    assert video_length("longcat_avatar", None, 8) == 128
    assert video_length("infinitetalk", (1.0, 4.0), 15) == 81
