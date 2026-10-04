"""The server renders every 2D shot of an episode: voices, scene, headless export, take."""
import time

import pytest

from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender, public_job, speech_params

KEVIN_ES = {"provider": "local", "model": "qwen3_tts_base", "voiceId": "reference", "name": "Kevin ES",
            "referenceAudio": "/api/v1/file/kevin-es.wav?workspace=cast", "transcript": "Hola.", "language": "spanish"}
GARY = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan"}


def library():
    character = lambda cid: {"id": cid, "name": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}}
    shot = lambda sid, order, method, beats, scene="scene_1": {
        "id": sid, "order": order, "sceneId": scene, "productionMethod": method, "framing": "plano general", "camera": "slow push-in",
        "visibleCharacterIds": ["kevin", "gary"], "locationId": "garage", "durationSeconds": 3,
        "dialogueBeats": [{"id": f"{sid}_d{i}", "characterId": who, "text": text} for i, (who, text) in enumerate(beats)]}
    episode = {"id": "ep1", "title": "Piloto", "shots": [
        shot("s01", 1, "animation_2d", [("kevin", "Vale, Gary."), ("gary", "Buenas noticias.")]),
        shot("s02", 2, "generated_video", [("kevin", "No.")]),
        shot("s03", 3, "animation_2d", [("gary", "Adiós.")], scene="scene_2"),
    ]}
    series = {"id": "uv", "title": "Valle", "spokenLanguage": "Español de España", "characters": [character("kevin"), character("gary")],
              "locations": [{"id": "garage", "referenceAssetIds": ["asset_bg"], "variants": []}],
              "assets": {"asset_bg": {"id": "asset_bg", "kind": "image", "uri": "assets/uv/bg.png"}}, "episodesById": {"ep1": episode}}
    return {"seriesById": {"uv": series}}


class Tools:
    def __init__(self, tmp_path, bad_first_take=False, fail_export_once=False, wait_errors=()):
        self.root, self.calls, self.jobs = tmp_path, [], 0
        self.bad_first_take, self.fail_export_once = bad_first_take, fail_export_once
        self.exports, self.wait_errors = {}, list(wait_errors)

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        data = arguments.get("input") or {}
        if tool == "generation.speech":
            self.jobs += 1
            name = f"{data['output_name']}.wav"
            (self.root / name).write_bytes(b"raw speech")
            return {"receipt": {"result": {"job_id": f"job-{self.jobs}"}}, "_name": name}
        if tool == "jobs.wait":
            if self.wait_errors:
                # As LocalMcp returns a tool error: no top-level status.
                return {"_is_error": True, "error": self.wait_errors.pop(0)}
            speech = [args for name, args in self.calls if name == "generation.speech"][-1]
            return {"status": "completed", "outputs": [{"path": f"{speech['input']['output_name']}.wav"}]}
        if tool == "qa.speech":
            takes = [name for name, _ in self.calls if name == "qa.speech"]
            return {"result": {"wer": 0.6 if self.bad_first_take and len(takes) == 1 else 0.05}}
        if tool == "audio.mouth_cues":
            return {"result": {"mouthCues": [{"start": 0, "end": 0.4, "value": "D"}], "recognizer": "wav2vec2-phoneme"}}
        if tool == "scenes.document.save":
            return {"result": {"name": f"{data['name']}.scene.json"}}
        if tool == "scenes.video2d.export":
            self.exports[arguments["intent_id"]] = 0
            return {"receipt": {"status": "queued"}}
        if tool == "scenes.video2d.export.receipt":
            intent = data["intent_id"]
            self.exports[intent] += 1
            if self.fail_export_once:
                self.fail_export_once = False
                return {"result": {"receipt": {"artifacts": []}, "task": {"status": "failed", "error": "browser crashed"}}}
            return {"result": {"receipt": {"artifacts": [{"name": f"{intent}.mp4"}]}, "task": {"status": "completed"}}}
        if tool == "series.asset.import":
            return {"result": {"attempt": {"id": f"attempt-{data['owner_id']}"}}}
        if tool == "series.take.approve":
            return {"result": {"shot": {"approvedAttemptId": data["attempt_id"]}}}
        raise AssertionError(tool)


def service(tmp_path, tools, compiled, **deps):
    def trim(source, target):
        with open(source, "rb") as handle:
            data = handle.read()
        with open(target, "wb") as handle:
            handle.write(data)
        return 1.25

    def compile_shot(payload):
        compiled.append(payload)
        return {"version": 1, "duration": payload["shot"]["duration"], "layers": []}

    kits = {f"kit-{cid}": {"id": f"kit-{cid}", "name": cid, "base": {"source": "/api/v1/file/k.png", "width": 400, "height": 800},
                           "poses": {}, "voice": GARY, **({"voicesByLanguage": {"spanish": KEVIN_ES}} if cid == "kevin" else {})}
            for cid in ("kevin", "gary")}
    durations = tools.durations = []
    return SeriesNativeRender(NativeRenderDeps(call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: library(),
                                               read_kits=lambda _ws: kits, compile_shot=compile_shot, trim=trim, sleep=lambda _s: None, poll_seconds=0,
                                               set_shot_duration=lambda *args: durations.append(args), **deps))


def finished(render, job_id, tmp_path):
    for _ in range(200):
        job = render.status("cast", job_id)
        if job["status"] in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.02)
    raise AssertionError(render.status("cast", job_id))


def test_every_2d_shot_becomes_an_approved_take_with_each_voice_in_the_series_language(tmp_path):
    tools, compiled = Tools(tmp_path), []
    render = service(tmp_path, tools, compiled)
    job = render.start("cast", "uv", "ep1", approve=True)
    assert [item["shotId"] for item in job["items"]] == ["s01", "s03"], "generated video shots stay with the H3 render"
    done = finished(render, job["jobId"], tmp_path)
    assert done["status"] == "completed" and done["message"] == "2 of 2 shots rendered"
    speech = [args["input"]["params"] for tool, args in tools.calls if tool == "generation.speech"]
    assert speech[0]["model_type"] == "qwen3_tts_base" and speech[0]["audio_guide"].endswith("kevin-es.wav?workspace=cast")
    assert speech[0]["model_mode"] == "spanish" and speech[0]["alt_prompt"] == "Hola."
    assert speech[1]["model_type"] == "qwen3_tts_customvoice" and speech[1]["model_mode"] == "ryan", "Gary has no Spanish voice: default"
    cues = [args["input"] for tool, args in tools.calls if tool == "audio.mouth_cues"]
    assert cues[0]["language"] == "es" and cues[0]["engine"] == "phoneme"
    first = compiled[0]["shot"]
    assert first["framing"] == "wide" and first["camera"] == "push" and len(first["lines"]) == 2
    assert first["lines"][0]["cues"] and first["background"]["source"] == "/api/v1/file/assets/uv/bg.png?workspace=cast"
    imports = [args["input"] for tool, args in tools.calls if tool == "series.asset.import"]
    assert [(item["owner_id"], item["as_take"], item["metadata"]["sceneFilename"]) for item in imports] == [
        ("s01", True, "uv-ep1-s01.scene.json"), ("s03", True, "uv-ep1-s03.scene.json")]
    assert all(item["approved"] for item in done["items"])
    assert [(args[3], args[4] > 1.5) for args in tools.durations] == [("s01", True), ("s03", True)], "each shot takes its rendered length"
    assert all("cues" not in line for item in public_job(done)["items"] for line in item["lines"].values())


def test_a_drifting_take_is_spoken_again_and_the_best_one_kept(tmp_path):
    tools, compiled = Tools(tmp_path, bad_first_take=True), []
    render = service(tmp_path, tools, compiled)
    done = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    line = done["items"][0]["lines"]["s03_d0"]
    assert (line["attempt"], line["wer"]) == (1, 0.05)
    assert [tool for tool, _ in tools.calls].count("generation.speech") == 2
    assert (tmp_path / line["filename"]).is_file() and not list(tmp_path.glob("*.best.wav"))


def test_a_failed_export_resumes_at_that_shot_and_reuses_its_recordings(tmp_path):
    tools, compiled = Tools(tmp_path, fail_export_once=True), []
    render = service(tmp_path, tools, compiled)
    job = render.start("cast", "uv", "ep1")
    done = finished(render, job["jobId"], tmp_path)
    assert done["status"] == "failed" and done["items"][0]["error"].endswith("browser crashed")
    assert done["items"][1]["status"] == "done", "the next shot still rendered"
    spoken = [tool for tool, _ in tools.calls].count("generation.speech")
    render.resume("cast", job["jobId"])
    again = finished(render, job["jobId"], tmp_path)
    assert again["status"] == "completed"
    assert [tool for tool, _ in tools.calls].count("generation.speech") == spoken, "recordings are reused"
    exports = [args["intent_id"] for tool, args in tools.calls if tool == "scenes.video2d.export"]
    assert exports[0] == exports[-1] and len(exports) == 3, "the failed shot's export is submitted again with its intent"


def test_a_new_render_reuses_the_recordings_of_an_earlier_one(tmp_path):
    tools, compiled = Tools(tmp_path), []
    render = service(tmp_path, tools, compiled, probe=lambda _path: 1.25)
    finished(render, render.start("cast", "uv", "ep1", shot_ids=["s01"])["jobId"], tmp_path)
    spoken = [tool for tool, _ in tools.calls].count("generation.speech")
    again = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s01"])["jobId"], tmp_path)
    assert again["status"] == "completed" and spoken == 2
    assert [tool for tool, _ in tools.calls].count("generation.speech") == spoken, "same text, same voice: same file"
    line = again["items"][0]["lines"]["s01_d0"]
    assert line["reused"] and line["duration"] == 1.25 and line["cues"], "a reused line still gets its mouth cues"


def test_a_speech_job_lost_in_a_restart_is_asked_for_again_and_other_wait_errors_fail(tmp_path):
    tools, compiled = Tools(tmp_path, wait_errors=[{"code": "invalid_command", "message": "Job not found", "status": 404}]), []
    render = service(tmp_path, tools, compiled)
    done = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    assert done["status"] == "completed"
    intents = [args["intent_id"] for tool, args in tools.calls if tool == "generation.speech"]
    assert len(intents) == 2 and intents[1].startswith(intents[0] + "-"), "a fresh intent, not the replayed one"
    tools = Tools(tmp_path / "x", wait_errors=[{"code": "failed", "message": "queue offline", "status": 503}])
    (tmp_path / "x").mkdir()
    broken = service(tmp_path / "x", tools, [])
    failed = finished(broken, broken.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    assert failed["status"] == "failed" and "queue offline" in failed["items"][0]["error"], "an error is not waited on forever"


def test_refusals_and_speech_params():
    with pytest.raises(NativeRenderError):
        SeriesNativeRender(NativeRenderDeps(call=lambda *_: {}, workspace_dir=lambda _: "/tmp", read_library=lambda _: library(),
                                            read_kits=lambda _: {})).start("cast", "uv", "ep1", shot_ids=["s02"])
    with pytest.raises(NativeRenderError) as no_kits:
        SeriesNativeRender(NativeRenderDeps(call=lambda *_: {}, workspace_dir=lambda _: "/tmp", read_library=lambda _: library(),
                                            read_kits=lambda _: {"kit-kevin": {}})).start("cast", "uv", "ep1")
    assert no_kits.value.code == "missing_kits" and "gary" in str(no_kits.value) and "kevin" not in str(no_kits.value)
    preset = speech_params(GARY, "one two three", "english", 7)
    assert preset["model_mode"] == "ryan" and preset["priority"] == 10 and preset["duration_seconds"] == 5
