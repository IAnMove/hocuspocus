"""Scripted H3 shots: the video object, the produce step, and a simulated generation."""
import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
from PIL import Image

from services.series_library import (
    EPISODE_EDITOR_FIELDS, SHOT_CONTENT_FIELDS, SHOT_EDITOR_FIELDS, _merge_episode_shot_patch, normalize_series_project,
    update_series_episode,
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
    assert result["shots"] == ["e2s00"] and not result.get("warnings")
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
    # The grouped shape of the other script warnings; it survives finish_check beside them.
    assert checked["warnings"] == [{"code": "video_budget", "subject": "videoBudget", "shots": ["e2s00"], "maxShots": 0,
                                    "message": "videoBudget: 1 video shot is over maxShots 0 and not generated (shots e2s00)"}]
    assert tools.calls == []
    written = apply_script(tools, tools.read, KITS, FILES, "cast", {**_script(), "videoBudget": {"maxShots": 2}})
    assert not written.get("warnings") and tools.calls[1][1]["episode"]["videoBudget"] == {"maxShots": 2}


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
    assert len(sent) == 1 and sent[0]["intent_id"].startswith("series-ep1-s00-video-") and sent[0]["intent_id"].endswith("-1")
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
    assert done["steps"][0]["warnings"] == [{"code": "video_budget", "subject": "videoBudget", "shots": ["s01"], "maxShots": 1,
                                             "message": "videoBudget: 1 video shot is over maxShots 1 and not generated (shots s01)"}]


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


class _Server(_Tools):
    """The tools with the server's intent rules (``task_command_admission``, ``production_media_common.run_once``).

    The same intent with the same input replays the first answer, so a failed job stays failed; the same intent
    with other input is a 409 ``intent_conflict``. ``outcomes`` is the status of each new clip in order
    (``running`` lasts until ``jobs.cancel``); after them every clip completes. Composed plates are real files."""

    def __init__(self, root, clip, outcomes=()):
        super().__init__("", clip)
        self.root, self.outcomes, self.intents, self.clips = Path(root), list(outcomes), {}, {}

    def __call__(self, tool, arguments):
        intent = arguments.get("intent_id")
        if intent is None:
            return self._answer(tool, arguments)
        sent = json.dumps(arguments["input"], sort_keys=True)
        if (tool, intent) in self.intents:
            self.calls.append((tool, arguments))
            first, reply = self.intents[(tool, intent)]
            if first != sent:
                return {"_is_error": True, "error": {"code": "intent_conflict", "status": 409,
                                                     "message": "intent_id was already used with different parameters"}}
            return reply
        reply = self._answer(tool, arguments)
        self.intents[(tool, intent)] = (sent, reply)
        return reply

    def _answer(self, tool, arguments):
        data = arguments["input"]
        if tool == "media.compose":
            self.calls.append((tool, arguments))
            name = f"{data['output_name']} ({len(self.intents)}).png"
            Image.new("RGB", tuple(data["size"]), (196, 180, 154)).save(self.root / name)
            return {"result": {"file": name}}
        if tool == "generation.video":
            self.calls.append((tool, arguments))
            job_id = f"vid-{len(self.clips) + 1}"
            self.clips[job_id] = self.outcomes.pop(0) if self.outcomes else "completed"
            return {"result": {"job_id": job_id}}
        if tool == "jobs.wait":
            self.calls.append((tool, arguments))
            status = self.clips[data["job_id"]]
            if status == "running":
                time.sleep(0.01)
                return {"result": {"status": "running", "timed_out": True}}
            if status != "completed":
                return {"result": {"status": status, "error": f"{data['job_id']} {status}"}}
            return {"result": {"status": "completed", "output_files": [self.take]}}
        if tool == "jobs.cancel":
            self.calls.append((tool, arguments))
            if self.clips.get(data["job_id"]) != "running":
                return {"_is_error": True, "error": {"code": "already_finished", "status": 409}}
            self.clips[data["job_id"]] = "cancelled"
            return {"result": {"job_id": data["job_id"], "status": "cancelled"}}
        return super().__call__(tool, arguments)

    def waited(self, job_id):
        return [arguments for tool, arguments in self.calls if tool == "jobs.wait" and arguments["input"]["job_id"] == job_id]


def _intents(tools):
    return [arguments["intent_id"] for arguments in _video_calls(tools, "generation.video")]


def _conflicts(tools):
    return [reply for (_tool, _intent), (_sent, reply) in tools.intents.items() if reply.get("_is_error")]


def test_a_failed_take_is_retried_under_a_new_intent_and_resume_does_not_replay_it(tmp_path):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip, outcomes=["failed"])
    library, _episode_body = _episode(_request())
    service = _produce(tmp_path, tools, library)
    failed = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert failed["status"] == "failed" and tools.imports == []
    first = _intents(tools)
    assert len(first) == 1 and first[0].endswith("-1")
    assert failed["steps"][0]["failedTakes"]["s00"]["takes"] == [1]
    done = finished(service, service.resume("cast", failed["jobId"])["jobId"])
    assert done["status"] == "completed", done
    second = _intents(tools)[1:]
    assert len(second) == 1 and second[0].endswith("-2") and second[0][:-2] == first[0][:-2]
    assert len(tools.waited("vid-1")) == 1, "the failed job is never waited on again"
    assert tools.imports[0]["metadata"]["intentId"] == second[0]
    # In one run, a failure uses the next take of maxTakes.
    again = _Server(tmp_path, clip, outcomes=["failed"])
    library, _episode_body = _episode(_request(maxTakes=2))
    service = _produce(tmp_path, again, library)
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    assert [intent[-2:] for intent in _intents(again)] == ["-1", "-2"] and len(again.imports) == 1


def test_a_changed_prompt_is_a_new_take_not_a_conflict(tmp_path):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip)
    library, episode = _episode(_request())
    service = _produce(tmp_path, tools, library)
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    episode["shots"][0]["video"]["prompt"] = "A loud room"
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    intents = _intents(tools)
    assert len(intents) == 2 and intents[0] != intents[1] and _conflicts(tools) == []
    assert [item["metadata"]["videoRequest"] for item in tools.imports][0] != tools.imports[1]["metadata"]["videoRequest"]
    # The same request again replays its take instead of paying for a second clip.
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    assert _intents(tools)[2] == intents[1] and len(tools.clips) == 2


def _editor_series(shot):
    series = normalize_series_project({
        "id": "uv", "spokenLanguage": "Español de España", "allowedProductionMethods": ["imported_video"],
        "episodesById": {"ep1": {"id": "ep1", "number": 1, "script": [{"id": "scene_1"}],
                                 "shots": [{"id": "s00", "sceneId": "scene_1", "productionMethod": "imported_video"}]}},
    }, "uv", "cast")
    edited = update_series_episode(series, "ep1", {"shots": [{"id": "s00", **shot}]}, base_series_revision=series["revision"])
    return normalize_series_project(edited, "uv", "cast")


def test_the_editor_path_stores_the_same_checked_video_as_the_script(tmp_path):
    series = _editor_series({"video": {"prompt": "  Ana waves once  ", "end": "same"}})
    shot = series["episodesById"]["ep1"]["shots"][0]
    tools = Series()
    apply_script(tools, tools.read, KITS, FILES, "cast", _script())
    assert shot["video"] == _shot(tools)["video"]
    assert shot["layout2d"]["clipAudio"] == "drop"
    kept = _editor_series({"video": {"prompt": "Ana waves", "keepAudio": False}, "layout2d": {"clipAudio": "keep"}})
    assert kept["episodesById"]["ep1"]["shots"][0]["layout2d"]["clipAudio"] == "keep"
    with pytest.raises(ValueError, match="video.prompt is required"):
        _editor_series({"video": {"prompt": " "}})
    with pytest.raises(ValueError, match="maxTakes"):
        _editor_series({"video": {"prompt": "x", "maxTakes": 9}})
    other = _editor_series({"productionMethod": "animation_2d", "video": {"prompt": "x"}})
    assert "video" not in other["episodesById"]["ep1"]["shots"][0]
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    server = _Server(tmp_path, clip)
    service = _produce(tmp_path, server, {"seriesById": {"uv": series}})
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    params = _video_calls(server, "generation.video")[0]["input"]["params"]
    assert params["video_length"] == 124 and params["model_type"] == "minimax_h3" and params["prompt"] == "Ana waves once"


def test_a_raw_stored_video_fails_the_step_with_its_problem_not_a_key_error(tmp_path):
    tools = _Server(tmp_path, "clip.png")
    library, _episode_body = _episode({"id": "s00", "productionMethod": "imported_video", "video": {"prompt": "hi", "frames": 7}})
    service = _produce(tmp_path, tools, library)
    failed = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert failed["status"] == "failed" and "H3 length" in failed["steps"][0]["error"]
    assert "KeyError" not in failed["steps"][0]["error"] and _video_calls(tools, "generation.video") == []


def test_a_portrait_series_gets_a_portrait_clip_and_plate(tmp_path):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip)
    library, _episode_body = _episode(_request())
    series = library["seriesById"]["uv"]
    service = _produce(tmp_path, tools, library)
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    series["provider"] = {"videoSettings": {"orientation": "portrait"}}
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    landscape, portrait = (arguments["input"]["params"] for arguments in _video_calls(tools, "generation.video"))
    assert landscape["resolution"] == "864x480" and portrait["resolution"] == "480x864"
    plates = _video_calls(tools, "media.compose")
    assert [plate["input"]["size"] for plate in plates] == [[864, 480], [480, 864]] and _conflicts(tools) == []
    with Image.open(tmp_path / tools.intents[("media.compose", plates[1]["intent_id"])][1]["result"]["file"]) as plate:
        assert plate.size == (480, 864)


def test_cancel_stops_the_clip_already_sent_and_resume_asks_for_a_new_one(tmp_path):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip, outcomes=["running"])
    library, _episode_body = _episode(_request())
    service = _produce(tmp_path, tools, library)
    job_id = service.start("cast", "uv", "ep1")["jobId"]
    for _ in range(300):
        if service.status("cast", job_id)["steps"][0].get("jobId") == "vid-1":
            break
        time.sleep(0.01)
    assert service.status("cast", job_id)["steps"][0]["jobId"] == "vid-1"
    service.cancel("cast", job_id)
    stopped = finished(service, job_id)
    assert stopped["status"] == "cancelled" and tools.clips["vid-1"] == "cancelled"
    assert {"version": 1, "input": {"job_id": "vid-1"}} in _video_calls(tools, "jobs.cancel")
    assert stopped["steps"][0]["failedTakes"]["s00"]["takes"] == [1] and "jobId" not in stopped["steps"][0]
    waits = len(tools.waited("vid-1"))
    done = finished(service, service.resume("cast", job_id)["jobId"])
    assert done["status"] == "completed", done
    assert _intents(tools)[1].endswith("-2") and len(tools.waited("vid-1")) == waits and len(tools.imports) == 1


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_drift_is_measured_on_later_frames_not_the_first(tmp_path):
    clip = tmp_path / "take.mp4"
    subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0xC4B49A:s=96x54:r=24:d=0.5", "-f", "lavfi", "-i", "color=c=blue:s=96x54:r=24:d=5",
                    "-filter_complex", "[0][1]concat=n=2:v=1:a=0", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)], check=True)
    tools = _Server(tmp_path, str(clip))
    library, _episode_body = _episode(_request())
    service = _produce(tmp_path, tools, library)
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    warning = done["steps"][0]["warnings"][0]
    assert warning["code"] == "style_drift" and warning["distance"] > STYLE_DRIFT_THRESHOLD


def test_a_resume_right_after_a_failure_starts_a_new_run_once_the_old_thread_ends(tmp_path):
    """The failed run saves its status a moment before its thread returns; a resume in that moment must not be lost."""
    import threading
    service = SeriesProduce(ProduceDeps(call=lambda *_: {}, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: {}))
    ran = []
    service._run = lambda workspace, job_id: ran.append(job_id)
    closing = threading.Thread(target=time.sleep, args=(0.3,))
    closing.start()
    service._threads["job-1"] = closing
    service._launch("ws", {"jobId": "job-1", "workspace": "ws", "status": "queued", "steps": []})
    service._threads["job-1"].join(5)
    assert ran == ["job-1"] and not closing.is_alive()
