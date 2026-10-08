"""Scripted H3 shots: the video object, the produce step, and a simulated generation."""
import os
import shutil
import subprocess

import pytest
from PIL import Image

from services.series_library import (
    EPISODE_EDITOR_FIELDS, SHOT_CONTENT_FIELDS, SHOT_EDITOR_FIELDS, _merge_episode_shot_patch,
)
from services.series_produce import ProduceDeps, SeriesProduce
from services.series_review import content_digest
from services.series_script import ScriptError, apply_script
from services.series_video_shots import (
    STYLE_DRIFT_THRESHOLD, import_generated_take, style_distance,
)
from tests.test_series_script_produce import FILES, KITS, Series, finished

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None


def _script(**video):
    request = {"prompt": "Ana waves once", "end": "same"}
    request.update(video)
    return {"scenes": [{"id": "cold_open", "location": "garage"}],
            "shots": [{"scene": "cold_open", "kind": "video", "duration": 5, "video": request}]}


def _shot(tools):
    return tools.calls[1][1]["episode"]["shots"][0]


def test_a_video_object_is_stored_and_drops_the_model_audio():
    tools = Series()
    result = apply_script(tools, tools.read, KITS, FILES, "cast", _script())
    shot = _shot(tools)
    assert result["shots"] == ["e2s00"] and "warnings" not in result
    assert shot["productionMethod"] == "imported_video"
    assert shot["video"] == {"prompt": "Ana waves once", "start": "plan", "end": "same", "frames": 124,
                             "model": "minimax_h3", "maxTakes": 2, "keepAudio": False}
    assert shot["layout2d"]["clipAudio"] == "drop"


def test_keep_audio_and_a_plain_imported_take_leave_the_clip_alone():
    tools = Series()
    apply_script(tools, tools.read, KITS, FILES, "cast", _script(keepAudio=True))
    assert "clipAudio" not in _shot(tools)["layout2d"] and _shot(tools)["video"]["keepAudio"] is True
    tools = Series()
    apply_script(tools, tools.read, KITS, FILES, "cast",
                 {"scenes": [{"id": "cold_open", "location": "garage"}],
                  "shots": [{"scene": "cold_open", "kind": "video", "duration": 4}]})
    plain = _shot(tools)
    assert plain["productionMethod"] == "imported_video" and "video" not in plain and "clipAudio" not in plain["layout2d"]


def test_a_bad_video_is_a_script_error_and_a_budget_only_warns():
    tools = Series()
    with pytest.raises(ScriptError) as raised:
        apply_script(tools, tools.read, KITS, FILES, "cast", _script(prompt="  "))
    assert any("video.prompt is required" in item for item in raised.value.problems) and tools.calls == []
    tools = Series()
    with pytest.raises(ScriptError) as raised:
        apply_script(tools, tools.read, KITS, FILES, "cast", {**_script(), "videoBudget": {"maxShots": "many"}})
    assert any("whole number" in item for item in raised.value.problems) and tools.calls == []
    tools = Series()
    with pytest.raises(ScriptError) as raised:
        apply_script(tools, tools.read, KITS, FILES, "cast", _script(frames=100))
    assert any("H3 length" in item for item in raised.value.problems)
    over = {**_script(), "videoBudget": {"maxShots": 0}}
    checked = apply_script(tools, tools.read, KITS, FILES, "cast", over, check_only=True)
    assert checked["warnings"] == [{"code": "video_budget", "maxShots": 0, "shots": 1}] and tools.calls == []
    written = apply_script(tools, tools.read, KITS, FILES, "cast", {**_script(), "videoBudget": {"maxShots": 2}})
    assert "warnings" not in written and tools.calls[1][1]["episode"]["videoBudget"] == {"maxShots": 2}


def test_the_video_field_survives_an_episode_update_and_does_not_change_a_shot_that_omits_it():
    assert "video" in SHOT_EDITOR_FIELDS and "video" in SHOT_CONTENT_FIELDS and "videoBudget" in EPISODE_EDITOR_FIELDS
    merged = _merge_episode_shot_patch([], [{"id": "s00", "video": {"prompt": "hi"}, "hat": True}], replace=True)
    assert merged[0]["video"] == {"prompt": "hi"} and "hat" not in merged[0]
    base = {"productionMethod": "imported_video", "dialogueBeats": [{"id": "b", "text": "hi"}],
            "layout2d": {"framing": "wide", "clipAudio": "drop"}}
    kept = {**base, "layout2d": {"framing": "wide", "clipAudio": "keep"}}
    assert content_digest(base) == content_digest(kept) == content_digest({**base, "video": None})
    assert content_digest(base) != content_digest({**base, "video": {"prompt": "x"}})


def _png(path, color):
    Image.new("RGB", (64, 48), color).save(path)
    return str(path)


class _Tools:
    def __init__(self, start, take):
        self.calls, self.imports, self.jobs = [], [], {}
        self.start, self.take = start, take

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        data = arguments["input"]
        if tool == "media.compose":
            return {"result": {"file": self.start}}
        if tool == "generation.video":
            return {"result": {"job_id": "vid-1"}}
        if tool == "jobs.wait":
            return {"result": {"status": "completed", "output_files": [self.take]}}
        if tool == "series.episode.render_native":
            job_id = f"native-{data.get('language', 'spanish')}"
            self.jobs[job_id] = "completed"
            return {"result": {"job": {"jobId": job_id, "status": "queued"}}}
        if tool == "series.episode.render_native.status":
            return {"result": {"job": {"jobId": data["job_id"], "status": "completed", "items": [], "message": "completed"}}}
        if tool == "series.assembly.start":
            return {"result": {"job": {"jobId": f"cut-{data.get('language', 'spanish')}", "status": "queued"}}}
        if tool == "series.assembly.status":
            return {"result": {"job": {"status": "completed", "assetId": "asset-spanish", "filename": "spanish.mp4"}}}
        raise AssertionError(tool)


def _episode(*shots, budget=None, review=None, english=False):
    episode = {"id": "ep1", "number": 1, "shots": list(shots), "languageVersions": {"english": {}} if english else {}}
    if budget is not None:
        episode["videoBudget"] = budget
    if review is not None:
        episode["review"] = review
    series = {"id": "uv", "spokenLanguage": "Español de España", "allowedProductionMethods": ["imported_video"],
              "episodesById": {"ep1": episode}, "assets": {}}
    return {"seriesById": {"uv": series}}, episode


def _request(**extra):
    body = {"prompt": "A quiet room", "start": "plan", "end": "same", "frames": 124, "model": "minimax_h3",
            "maxTakes": 1, "keepAudio": False}
    body.update(extra)
    return {"id": extra.pop("id", None) or "s00", "productionMethod": "imported_video", "video": body, "layout2d": {}}


def _produce(tmp_path, tools, library):
    return SeriesProduce(ProduceDeps(
        call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: library,
        import_take=tools.imports.append, sleep=lambda _s: None, poll_seconds=0))


def _video_calls(tools, name):
    return [arguments for tool, arguments in tools.calls if tool == name]


def test_produce_puts_one_video_step_before_the_renders_and_loops_on_end_same(tmp_path):
    start = _png(tmp_path / "start.png", (196, 180, 154))
    tools = _Tools(start, start)
    library, _episode_body = _episode(_request(), english=True)
    service = _produce(tmp_path, tools, library)
    job = service.start("cast", "uv", "ep1")
    assert [(step["kind"], step["language"]) for step in job["steps"]] == [
        ("video", "spanish"), ("render", "spanish"), ("render", "english"), ("assemble", "spanish"), ("assemble", "english")]
    done = finished(service, job["jobId"])
    assert done["status"] == "completed", done
    sent = _video_calls(tools, "generation.video")
    assert len(sent) == 1 and sent[0]["intent_id"] == "series-ep1-s00-video-1"
    params = sent[0]["input"]["params"]
    assert params["image_end"] == params["image_start"] and params["resolution"] == "864x480"
    assert params["video_length"] == 124 and "operation" not in sent[0]
    assert _video_calls(tools, "jobs.wait")[0] == {"version": 1, "input": {"job_id": "vid-1", "timeout_s": 30}}
    assert tools.imports[0]["approve"] is True and tools.imports[0]["shotId"] == "s00"
    assert not any(tool == "series.asset.import" for tool, _ in tools.calls)


def test_a_shot_without_a_video_object_keeps_the_old_step_order(tmp_path):
    tools = _Tools("a", "b")
    library, _episode_body = _episode({"id": "s00", "productionMethod": "imported_video"})
    job = _produce(tmp_path, tools, library).start("cast", "uv", "ep1")
    assert [step["kind"] for step in job["steps"]] == ["render", "assemble"]


def test_plan_mode_does_not_spend_until_the_plan_is_approved(tmp_path):
    start = _png(tmp_path / "start.png", (196, 180, 154))
    tools = _Tools(start, start)
    library, episode = _episode(_request(), review={"mode": "plan", "shots": {"s00": {"plan": "pending"}}})
    service = _produce(tmp_path, tools, library)
    waiting = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert waiting["status"] == "waiting" and waiting["waiting"] == [{"shotId": "s00", "reason": "plan"}]
    assert _video_calls(tools, "generation.video") == [] and tools.imports == []
    episode["review"]["shots"]["s00"]["plan"] = "approved"
    done = finished(service, service.resume("cast", waiting["jobId"])["jobId"])
    assert done["status"] == "completed", done
    assert len(_video_calls(tools, "generation.video")) == 1 and tools.imports[0]["approve"] is True


def test_preview_spends_once_and_leaves_the_take_unapproved(tmp_path):
    start = _png(tmp_path / "start.png", (196, 180, 154))
    tools = _Tools(start, start)
    library, _episode_body = _episode(_request(), review={"mode": "preview", "shots": {"s00": {"plan": "approved"}}})
    service = _produce(tmp_path, tools, library)
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    assert len(_video_calls(tools, "generation.video")) == 1 and tools.imports[0]["approve"] is False
    assert tools.imports[0]["metadata"]["reviewStage"] == "preview"


def test_produce_stops_at_the_shot_budget(tmp_path):
    start = _png(tmp_path / "start.png", (196, 180, 154))
    tools = _Tools(start, start)
    second = _request()
    second["id"] = "s01"
    library, _episode_body = _episode(_request(), second, budget={"maxShots": 1})
    service = _produce(tmp_path, tools, library)
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    assert [item["shotId"] for item in tools.imports] == ["s00"]
    assert done["steps"][0]["warnings"] == [{"code": "video_budget", "maxShots": 1, "shots": 2}]


def test_a_different_palette_warns_and_the_same_plate_stays_under_the_threshold(tmp_path):
    plate = Image.new("RGB", (64, 48), (196, 180, 154))
    other = Image.new("RGB", (80, 40), (0, 0, 255))
    assert style_distance(plate, plate.copy()) < STYLE_DRIFT_THRESHOLD
    assert style_distance(plate, other) > STYLE_DRIFT_THRESHOLD
    start = _png(tmp_path / "start.png", (196, 180, 154))
    drifted = _png(tmp_path / "blue.png", (0, 0, 255))
    tools = _Tools(start, drifted)
    library, _episode_body = _episode(_request(maxTakes=2))
    service = _produce(tmp_path, tools, library)
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    warning = done["steps"][0]["warnings"][0]
    assert warning["code"] == "style_drift" and warning["shotId"] == "s00" and warning["distance"] > STYLE_DRIFT_THRESHOLD
    assert len(_video_calls(tools, "generation.video")) == 2 and len(tools.imports) == 1
    same = _Tools(start, start)
    quiet, _body = _episode(_request(maxTakes=2))
    service = _produce(tmp_path, same, quiet)
    calm = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert calm["steps"][0]["warnings"] == [] and len(_video_calls(same, "generation.video")) == 1


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_import_generated_take_approves_without_an_mcp_import(tmp_path):
    clip = tmp_path / "take.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=c=red:s=160x120:d=0.4",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    series = {"id": "uv", "allowedProductionMethods": ["imported_video"], "assets": {},
              "episodesById": {"ep1": {"id": "ep1", "shots": [{"id": "s00", "productionMethod": "imported_video", "attempts": []}]}}}
    attempt = import_generated_take(series, "cast", str(tmp_path), "s00", str(clip), {"videoRequest": "abc"}, approve=True)
    shot = series["episodesById"]["ep1"]["shots"][0]
    assert shot["approvedAttemptId"] == attempt
    stored = series["assets"][next(iter(series["assets"]))]
    assert stored["metadata"]["videoRequest"] == "abc" and os.path.isfile(os.path.join(str(tmp_path), stored["uri"]))
