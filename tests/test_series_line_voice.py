"""One line's voice, recorded now with the render's own speech path (Series Lab's shot inspector, series.shot.voice)."""
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_shot_inspector import create_series_shot_inspector_router
from services.series_line_voice import LineVoiceError, SeriesLineVoice, find_line
from services.series_native_render import NativeRenderError
from tests.test_series_native_render import Tools, _takes, finished, library, service


def setup(tmp_path, tools=None, take_at=None, **deps):
    """The native render's test series; with ``take_at`` shot s03 has a completed take finished then."""
    tools = tools or Tools(tmp_path)
    render = service(tmp_path, tools, [], probe=lambda _path: 1.25, **deps)

    def read_library(_workspace):
        value = library()
        if take_at:
            shot = value["seriesById"]["uv"]["episodesById"]["ep1"]["shots"][2]
            shot["attempts"] = [{"id": "take-1", "status": "completed", "completedAt": take_at, "outputAssetIds": []}]
        return value
    return tools, render, SeriesLineVoice(render, read_library, render.deps.read_kits)


def wait(voices, job_id):
    for _ in range(300):
        job = voices.status("cast", job_id)
        if job["status"] not in ("queued", "running"):
            return job
        time.sleep(0.02)
    raise AssertionError(job)


def speech_calls(tools):
    return [args for tool, args in tools.calls if tool == "generation.speech"]


def test_one_line_is_recorded_where_the_next_render_of_its_shot_reuses_it(tmp_path):
    tools, render, voices = setup(tmp_path)
    listed = voices.voices("cast", "uv", "ep1", 1)
    assert [(line["number"], line["beatId"], line["recorded"]) for line in listed["lines"]] == [(1, "s01_d0", False), (2, "s01_d1", False)]
    filename = listed["lines"][1]["filename"]
    assert filename.startswith("ln-ep1-s01_d1-") and filename.endswith(".wav")
    job = voices.start("cast", "uv", "ep1", 1, 2)
    assert (job["shotId"], job["beatId"], job["language"], job["text"]) == ("s01", "s01_d1", "spanish", "Buenas noticias.")
    done = wait(voices, job["jobId"])
    assert done["status"] == "completed", done
    assert done["result"]["filename"] == filename and done["result"]["url"] == f"/api/v1/file/{filename}?workspace=cast"
    assert done["result"]["cueCount"] == 1 and done["result"]["wer"] == 0.05
    assert [args["input"]["params"]["prompt"] for args in speech_calls(tools)] == ["Buenas noticias."]
    after = voices.voices("cast", "uv", "ep1", "s01")["lines"]
    assert [line["recorded"] for line in after] == [False, True] and after[1]["url"].endswith("?workspace=cast")
    # The shot's render records only the other line: same text, same voice, same file.
    rendered = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s01"])["jobId"], tmp_path)
    assert rendered["status"] == "completed"
    assert len(speech_calls(tools)) == 2 and rendered["items"][0]["lines"]["s01_d1"]["reused"] is True


def test_a_recorded_line_is_kept_and_a_retake_replaces_it_only_once_it_is_good(tmp_path):
    tools, render, voices = setup(tmp_path)
    first = wait(voices, voices.start("cast", "uv", "ep1", "s03", "s03_d0")["jobId"])
    recording = tmp_path / first["result"]["filename"]
    recording.write_bytes(b"first take")
    kept = wait(voices, voices.start("cast", "uv", "ep1", "s03", 1)["jobId"])
    assert kept["result"]["reused"] is True and len(speech_calls(tools)) == 1 and recording.read_bytes() == b"first take"
    retake = wait(voices, voices.start("cast", "uv", "ep1", "s03", 1, retake=True)["jobId"])
    assert retake["status"] == "completed" and retake["result"]["retake"] is True
    assert retake["result"]["filename"] == recording.name and recording.read_bytes() == b"raw speech"
    asked = speech_calls(tools)
    assert len(asked) == 2 and asked[0]["input"]["params"]["seed"] != asked[1]["input"]["params"]["seed"]
    assert asked[0]["intent_id"] != asked[1]["intent_id"], "a retake is a new generation, not a replay"
    assert not [path for path in tmp_path.iterdir() if "-take" in path.name], "the take's own files are gone"
    # A retake that never speaks leaves the recording as it was.
    recording.write_bytes(b"good take")
    render.deps.trim = _takes(tmp_path, [None, 0.05, None])
    failed = wait(voices, voices.start("cast", "uv", "ep1", "s03", 1, retake=True)["jobId"])
    assert failed["status"] == "failed" and "gave no speech" in failed["error"] and failed["errorCode"] == "speech_empty"
    assert recording.read_bytes() == b"good take"


def test_a_recording_newer_than_the_shots_take_says_so(tmp_path):
    _tools, _render, voices = setup(tmp_path, take_at="2020-01-01T00:00:00Z")
    wait(voices, voices.start("cast", "uv", "ep1", "s03", 1)["jobId"])
    line = voices.voices("cast", "uv", "ep1", "s03")["lines"][0]
    assert line["recorded"] and line["newerThanTake"] is True and line["recordedAt"] > 1.6e9


def test_lines_are_refused_while_the_episode_renders_without_a_voice_or_when_unknown(tmp_path, monkeypatch):
    _tools, render, voices = setup(tmp_path)
    with pytest.raises(LineVoiceError) as missing:
        voices.start("cast", "uv", "ep1", "s03", 4)
    assert (missing.value.code, missing.value.status) == ("line_not_found", 404)
    with pytest.raises(LineVoiceError) as shot:
        voices.start("cast", "uv", "ep1", "s99", 1)
    assert (shot.value.code, shot.value.status) == ("shot_not_found", 404)
    monkeypatch.setattr(render, "jobs", lambda _workspace: [{"jobId": "native-1", "episodeId": "ep1", "status": "running"}])
    with pytest.raises(LineVoiceError) as busy:
        voices.start("cast", "uv", "ep1", "s03", 1)
    assert (busy.value.code, busy.value.status) == ("render_running", 409)
    monkeypatch.undo()
    kits = render.deps.read_kits("cast")
    for kit in kits.values():
        kit.pop("voice")
        kit.pop("voicesByLanguage", None)
    render.deps.read_kits = lambda _workspace: kits
    voices.read_kits = render.deps.read_kits
    with pytest.raises(NativeRenderError, match="gary has no voice for spanish"):
        voices.start("cast", "uv", "ep1", "s03", 1)
    listed = voices.voices("cast", "uv", "ep1", "s03")["lines"][0]
    assert listed["voice"] is False and "no voice" in listed["problem"]
    with pytest.raises(LineVoiceError, match="no english version"):
        voices.voices("cast", "uv", "ep1", "s03", "english")


def test_a_line_is_found_by_its_beat_id_or_its_number_among_spoken_lines():
    shot = {"id": "s1", "dialogueBeats": [{"id": "b0", "text": " "}, {"id": "b1", "text": "Hola"}, {"id": "b2", "text": "Adiós"}]}
    assert find_line(shot, "b2")["id"] == "b2" and find_line(shot, 1)["id"] == "b1" and find_line(shot, "2")["id"] == "b2"
    with pytest.raises(LineVoiceError):
        find_line(shot, "b0")


def test_the_routes_list_record_and_follow_a_line(tmp_path):
    _tools, _render, voices = setup(tmp_path)
    app = FastAPI()
    app.include_router(create_series_shot_inspector_router(
        voices=voices, read_library=lambda _ws: library(), workspace_dir=lambda _ws: str(tmp_path),
        call=lambda *_args: {}, bind_loop=lambda _loop: None))
    client = TestClient(app)
    listed = client.get("/api/v1/series/uv/episodes/ep1/shots/3/voices", params={"workspace": "cast"})
    assert listed.status_code == 200 and listed.json()["shotId"] == "s03" and listed.json()["recording"] == []
    started = client.post("/api/v1/series/uv/episodes/ep1/shots/s03/voices", json={"workspace": "cast", "line": 1})
    assert started.status_code == 200, started.text
    job_id = started.json()["jobId"]
    wait(voices, job_id)
    followed = client.get(f"/api/v1/series/voice-jobs/{job_id}", params={"workspace": "cast"})
    assert followed.json()["status"] == "completed" and followed.json()["result"]["filename"].startswith("ln-ep1-s03_d0-")
    assert client.post("/api/v1/series/uv/episodes/ep1/shots/s03/voices", json={"workspace": "cast", "line": 9}).status_code == 404
    assert client.get("/api/v1/series/voice-jobs/nope", params={"workspace": "cast"}).status_code == 404
    assert client.post("/api/v1/series/uv/episodes/ep1/shots/s03/voices", json={"workspace": "cast", "line": 1, "x": 1}).status_code == 422


def test_the_voice_tools_call_the_routes_over_mcp(tmp_path):
    from tests.test_series_commands import call, harness
    handlers, calls, _, _ = harness(tmp_path, [{"shotId": "e1s04", "lines": []}, {"jobId": "voice-1", "status": "queued"},
                                               {"jobId": "voice-1", "status": "completed"}])
    call(handlers, "series.shot.voices", {"workspace": "series", "series_id": "uv", "episode_id": "ep1", "shot": 5, "language": "english"})
    assert calls[0][:2] == ("GET", "http://127.0.0.1:9/api/v1/series/uv/episodes/ep1/shots/5/voices?workspace=series&language=english")
    started = call(handlers, "series.shot.voice", {"workspace": "series", "series_id": "uv", "episode_id": "ep1", "shot": "e1s04",
                                                   "line": 2, "retake": True})
    assert calls[1] == ("POST", "http://127.0.0.1:9/api/v1/series/uv/episodes/ep1/shots/e1s04/voices",
                        {"workspace": "series", "line": 2, "retake": True})
    assert started["result"]["job"]["jobId"] == "voice-1"
    followed = call(handlers, "series.shot.voice.status", {"workspace": "series", "job_id": "voice-1"})
    assert calls[2][:2] == ("GET", "http://127.0.0.1:9/api/v1/series/voice-jobs/voice-1?workspace=series")
    assert followed["result"]["job"]["status"] == "completed"


def test_a_job_cut_by_a_restart_reads_as_interrupted(tmp_path):
    _tools, render, voices = setup(tmp_path)
    voices._store("cast").save({"jobId": "voice-old", "status": "running", "episodeId": "ep1", "beatId": "s03_d0"})
    fresh = SeriesLineVoice(render, voices.read_library, voices.read_kits)
    assert fresh.status("cast", "voice-old")["status"] == "interrupted"
