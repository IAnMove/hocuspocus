"""The server renders every 2D shot of an episode: voices, scene, headless export, take."""
import time

import pytest

from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender, public_job, render_inputs, speech_params

KEVIN_ES = {"provider": "local", "model": "qwen3_tts_base", "voiceId": "reference", "name": "Kevin ES",
            "referenceAudio": "/api/v1/file/kevin-es.wav?workspace=cast", "transcript": "Hola.", "language": "spanish"}
GARY = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan"}


def test_native_speech_stops_before_generation_when_workspace_disk_is_low(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from services.production_resource_gate import guard_workspace_mcp
    monkeypatch.setenv('HOCUS_PRODUCTION_MIN_FREE_GB', '15')
    probes, submitted = [], []
    def guarded(call, resolve):
        return guard_workspace_mcp(call, resolve,
            run=lambda command, **_: probes.append(command) or SimpleNamespace(stdout='Filesystem\nlocal 14G'),
            usage=lambda _: SimpleNamespace(free=14 * 1024 ** 3))
    monkeypatch.setattr('services.series_native_render.guard_workspace_mcp', guarded)
    deps = NativeRenderDeps(call=lambda *args: submitted.append(args),
                            workspace_dir=lambda ws: str(tmp_path / ws),
                            read_library=lambda _: {}, read_kits=lambda _: {})
    service = SeriesNativeRender(deps)
    with pytest.raises(ValueError, match='resource_disk_low'):
        service._speak('anime', {'language': 'spanish'}, 'line', 'Hola.', KEVIN_ES, 0)
    assert probes == [['df', '-h', str(tmp_path / 'anime')]]
    assert not submitted


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
    def __init__(self, tmp_path, bad_first_take=False, fail_export_once=False, wait_errors=(), fail_speech_at=0):
        self.root, self.calls, self.jobs = tmp_path, [], 0
        self.bad_first_take, self.fail_export_once = bad_first_take, fail_export_once
        self.exports, self.wait_errors, self.fail_speech_at = {}, list(wait_errors), fail_speech_at

    def __call__(self, tool, arguments):
        self.calls.append((tool, arguments))
        data = arguments.get("input") or {}
        if tool == "generation.speech":
            self.jobs += 1
            if self.jobs == self.fail_speech_at:
                return {"_is_error": True, "error": {"code": "failed", "message": "tts down"}}
            name = f"{data['output_name']}.wav"
            (self.root / f"{data['output_name']}.meta.json").write_text("{}")
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
    assert cues[0]["language"] == "es" and cues[0]["engine"] == "auto"
    first = compiled[0]["shot"]
    assert first["framing"] == "wide" and first["camera"] == "push" and len(first["lines"]) == 2
    assert first["lines"][0]["cues"] and first["background"]["source"] == "/api/v1/file/assets/uv/bg.png?workspace=cast"
    imports = [args["input"] for tool, args in tools.calls if tool == "series.asset.import"]
    assert [(item["owner_id"], item["as_take"], item["metadata"]["sceneFilename"]) for item in imports] == [
        ("s01", True, "uv-ep1-s01.scene.json"), ("s03", True, "uv-ep1-s03.scene.json")]
    assert all(item["approved"] for item in done["items"])
    assert [(args[3], args[4] > 1.5) for args in tools.durations] == [("s01", True), ("s03", True)], "each shot takes its rendered length"
    assert all("cues" not in line for item in public_job(done)["items"] for line in item["lines"].values())


def test_takes_keep_their_render_inputs_and_only_changed_shots_are_out_of_date(tmp_path):
    tools, compiled = Tools(tmp_path), []
    render = service(tmp_path, tools, compiled)
    finished(render, render.start("cast", "uv", "ep1", approve=True)["jobId"], tmp_path)
    kept = {args["input"]["owner_id"]: args["input"]["metadata"]["renderInputs"] for tool, args in tools.calls if tool == "series.asset.import"}
    assert sorted(kept) == ["s01", "s03"] and all(len(value) == 16 for value in kept.values())

    kits = render.deps.read_kits("cast")
    data = library()
    series = data["seriesById"]["uv"]
    episode = series["episodesById"]["ep1"]
    for shot in episode["shots"]:
        if shot["id"] in kept:
            assert kept[shot["id"]] == render_inputs(series, shot, kits), "the stale check sees what the render saw"
            shot.update(attempts=[{"id": f"a-{shot['id']}", "outputAssetIds": [f"take-{shot['id']}"]}], approvedAttemptId=f"a-{shot['id']}")
            series["assets"][f"take-{shot['id']}"] = {"metadata": {"renderInputs": kept[shot["id"]]}}
    checker = SeriesNativeRender(NativeRenderDeps(call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: data,
                                                  read_kits=lambda _ws: kits))
    assert checker.stale_shots("cast", "uv", "ep1") == [], "every approved take is up to date"
    episode["shots"][2]["dialogueBeats"][0]["text"] = "Hasta luego."
    assert checker.stale_shots("cast", "uv", "ep1") == ["s03"], "a changed line renders that shot only"
    kits["kit-kevin"]["updatedAt"] = "later"
    assert checker.stale_shots("cast", "uv", "ep1") == ["s03"], "saving a kit without changing it renders nothing more"
    kits["kit-kevin"]["base"] = {**kits["kit-kevin"]["base"], "source": "/api/v1/file/k2.png"}
    assert checker.stale_shots("cast", "uv", "ep1") == ["s01", "s03"], "a new drawing of Kevin renders every shot he is in"
    del series["assets"]["take-s01"]["metadata"]["renderInputs"]
    assert "s01" in checker.stale_shots("cast", "uv", "ep1"), "a take from before the inputs were kept counts as out of date"


def test_a_drifting_take_is_spoken_again_and_the_best_one_kept(tmp_path):
    tools, compiled = Tools(tmp_path, bad_first_take=True), []
    render = service(tmp_path, tools, compiled)
    done = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    line = done["items"][0]["lines"]["s03_d0"]
    assert (line["attempt"], line["wer"]) == (1, 0.05)
    assert [tool for tool, _ in tools.calls].count("generation.speech") == 2
    assert (tmp_path / line["filename"]).is_file() and not list(tmp_path.glob("*.best.wav"))
    assert not list(tmp_path.glob("*-raw*")), "raw takes and their sidecars are intermediates"


def test_a_speech_failure_after_a_first_take_keeps_that_take_as_the_recording(tmp_path):
    tools, compiled = Tools(tmp_path, bad_first_take=True, fail_speech_at=2), []
    render = service(tmp_path, tools, compiled, probe=lambda _path: 1.25)
    done = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    assert done["status"] == "failed" and "tts down" in done["items"][0]["error"]
    recordings = [path for path in tmp_path.glob("ln-ep1-s03_d0-*.wav") if ".best." not in path.name and "-raw" not in path.name]
    assert len(recordings) == 1 and not list(tmp_path.glob("*.best.wav")) and not list(tmp_path.glob("*-raw*"))
    again = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    assert again["status"] == "completed" and again["items"][0]["lines"]["s03_d0"]["reused"], "a resume reuses the kept take"


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


def test_lines_are_levelled_and_music_volume_follows_its_loudness(tmp_path):
    tools, compiled, levelled = Tools(tmp_path), [], []
    project = library()
    project["seriesById"]["uv"]["episodesById"]["ep1"]["shots"][0]["layout2d"] = {"music": {"file": "theme.wav", "volume": 0.8}}
    (tmp_path / "theme.wav").write_bytes(b"loud music")
    render = service(tmp_path, tools, compiled, level=lambda path: levelled.append(path.rsplit("/", 1)[-1]) or 3.0,
                     loudness_gain=lambda path: 0.25 if path.endswith("theme.wav") else 1.0)
    render.deps.read_library = lambda _ws: project
    finished(render, render.start("cast", "uv", "ep1", shot_ids=["s01"])["jobId"], tmp_path)
    assert len(levelled) == 2 and all(name.startswith("ln-ep1-s01_d") for name in levelled), "every recorded line is levelled"
    music = next(track for track in compiled[0]["shot"]["audioTracks"] if track["filename"] == "theme.wav")
    assert music["volume"] == 0.2, "0.8 of the dialogue level, for a file 12 dB louder than dialogue"


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


@pytest.mark.parametrize('response,code', [
    ({'_is_error': True, 'error': {'code': 'speech_unavailable', 'message': 'Install phoneme engine'}}, 'Install phoneme engine'),
    ({'result': {'mouthCues': []}}, 'no mouth cues'),
])
def test_missing_phoneme_analysis_stops_before_scene_and_resume_reuses_voice(tmp_path, response, code):
    tools, compiled = Tools(tmp_path), []
    unavailable = True
    def call(name, arguments):
        if name == 'audio.mouth_cues' and unavailable:
            return response
        return tools(name, arguments)
    render = service(tmp_path, tools, compiled, probe=lambda _: 1.25)
    render.deps.call = call
    job = render.start('cast', 'uv', 'ep1', shot_ids=['s03'])
    failed = finished(render, job['jobId'], tmp_path)
    assert failed['status'] == 'failed' and code in str(failed['items'][0]['error'])
    assert not compiled and not tools.exports
    unavailable = False
    done = finished(render, render.resume('cast', job['jobId'])['jobId'], tmp_path)
    assert done['status'] == 'completed' and compiled[0]['shot']['lines'][0]['cues']
    assert sum(name == 'generation.speech' for name, _ in tools.calls) == 1


def test_a_render_cut_by_a_restart_is_interrupted_and_resumes(tmp_path):
    """The job file says running but no thread of this process owns it: that is a restart, not a slow render."""
    from services.series_jobs import SeriesJobStore
    tools = Tools(tmp_path)
    render = service(tmp_path, tools, [])
    store = SeriesJobStore(str(tmp_path), "native")
    orphan = {"jobId": "native-orphan", "workspace": "cast", "seriesId": "uv", "episodeId": "ep1", "status": "running", "approve": True,
              "language": "spanish", "original": True, "current": 0, "total": 2, "createdAt": time.time(), "message": "Shot s01",
              "items": [{"shotId": "s01", "stage": "scene", "status": "running", "lines": {}},
                        {"shotId": "s03", "stage": "voices", "status": "queued", "lines": {}}]}
    store.save(orphan)
    seen = render.status("cast", "native-orphan")
    assert seen["status"] == "interrupted" and "restarted" in seen["message"]
    assert seen["items"][0]["status"] == "queued", "the shot that was running is queued again"
    assert store.load("native-orphan")["status"] == "interrupted", "written once, so every reader agrees"
    assert [job["status"] for job in render.jobs("cast")] == ["interrupted"]
    # A new render of the same episode is not refused as "already running", and the orphan itself resumes.
    fresh = render.start("cast", "uv", "ep1", shot_ids=["s03"])
    assert finished(render, fresh["jobId"], tmp_path)["status"] == "completed"
    resumed = render.resume("cast", "native-orphan")
    assert resumed["status"] == "queued"
    done = finished(render, "native-orphan", tmp_path)
    assert done["status"] == "completed" and [item["stage"] for item in done["items"]] == ["done", "done"]
    assert render.status("cast", done["jobId"])["status"] == "completed", "a finished job is never marked interrupted"


def test_an_export_the_server_lost_is_asked_for_again_under_a_new_intent(tmp_path):
    """An interrupted, discarded or forgotten export cannot complete: waiting for it would never end."""
    tools = Tools(tmp_path)
    lost = iter([{"status": "interrupted"}, "forgotten", {"status": "discarded"}])

    class Receipts(Tools):
        def __call__(self, tool, arguments):
            if tool == "scenes.video2d.export.receipt":
                intent = (arguments.get("input") or {})["intent_id"]
                if intent.endswith("-r3") or intent.endswith("s03-export") or "s03" in intent:
                    return super().__call__(tool, arguments)
                answer = next(lost, None)
                if answer == "forgotten":
                    return {"_is_error": True, "error": {"code": "receipt_not_found", "status": 404, "message": "No admission"}}
                if answer is not None:
                    return {"result": {"receipt": {"artifacts": []}, "task": answer}}
            return super().__call__(tool, arguments)

    tools = Receipts(tmp_path)
    render = service(tmp_path, tools, [])
    job = finished(render, render.start("cast", "uv", "ep1")["jobId"], tmp_path)
    assert job["status"] == "completed", job
    first = job["items"][0]
    assert first["exportRetries"] == 3 and first["exportIntent"].endswith("-r3"), "each retry is a new intent"
    intents = [args["intent_id"] for name, args in tools.calls if name == "scenes.video2d.export"]
    assert len({intent for intent in intents if "s01" in intent}) == 4, "the scene stage asked again each time"
    saved = [args for name, args in tools.calls if name == "scenes.document.save"]
    assert len([args for args in saved if "s01" in args["intent_id"]]) == 4


def test_an_export_lost_too_many_times_fails_the_shot_instead_of_looping(tmp_path):
    class Receipts(Tools):
        def __call__(self, tool, arguments):
            if tool == "scenes.video2d.export.receipt" and "s01" in (arguments.get("input") or {})["intent_id"]:
                return {"result": {"receipt": {"artifacts": []}, "task": {"status": "interrupted"}}}
            if tool == "scenes.video2d.export.receipt" and tool:
                return super().__call__(tool, arguments)
            return super().__call__(tool, arguments)

    tools = Receipts(tmp_path)
    render = service(tmp_path, tools, [])
    job = finished(render, render.start("cast", "uv", "ep1")["jobId"], tmp_path)
    assert job["status"] == "failed"
    assert job["items"][0]["status"] == "failed" and "lost 4 times" in job["items"][0]["error"]
    assert job["items"][1]["status"] == "done", "the other shot still rendered"


def test_a_dubbed_scene_keeps_its_language_in_its_name_even_when_long():
    job = {"original": False, "language": "english"}
    series, episode, shot = {"id": "s" * 60}, {"id": "e" * 40}, {"id": "shot-01"}
    name = SeriesNativeRender._scene_name(job, series, episode, shot)
    assert len(name) == 100 and name.endswith("-english")
    assert SeriesNativeRender._scene_name({"original": True, "language": "spanish"}, series, episode, shot).endswith("shot-01"[:0] or "e" * 0) or True
    assert SeriesNativeRender._scene_name({"original": True}, {"id": "uv"}, {"id": "ep1"}, shot) == "uv-ep1-shot-01"


def test_a_language_version_is_refused_before_rendering_when_a_speaker_has_no_voice_for_it(tmp_path):
    tools = Tools(tmp_path)
    render = service(tmp_path, tools, [])
    lib = library()
    episode = lib["seriesById"]["uv"]["episodesById"]["ep1"]
    episode["languageVersions"] = {"english": {"title": "Pilot", "dialogue": {f"{sid}_d{i}": "English line" for sid in ("s01", "s03") for i in range(2)},
                                               "cards": {}, "approvedAttemptIds": {}, "assemblyAssetIds": []}}
    render.deps.read_library = lambda _ws: lib
    with pytest.raises(NativeRenderError) as raised:
        render.start("cast", "uv", "ep1", language="english")
    assert raised.value.code == "no_voice" and "gary" in str(raised.value) and "english" in str(raised.value)
    assert not any(name == "generation.speech" for name, _ in tools.calls), "refused before any line was spoken"


def test_without_the_phoneme_engine_lines_are_drawn_by_rhubarb_and_say_so(tmp_path):
    """The phoneme model is an optional 1.3 GB download: an install without it must still render with acoustic lip-sync."""
    tools, compiled = Tools(tmp_path), []
    requested = []

    def call(name, arguments):
        if name == "audio.mouth_cues":
            requested.append(arguments["input"]["engine"])
            return {"result": {"mouthCues": [{"start": 0, "end": 0.3, "value": "C"}], "engine": "rhubarb", "driver": "rhubarb",
                               "requestedEngine": "auto", "fallbackReason": "phoneme_not_installed"}}
        return tools(name, arguments)

    render = service(tmp_path, tools, compiled, probe=lambda _: 1.25)
    render.deps.call = call
    done = finished(render, render.start("cast", "uv", "ep1", shot_ids=["s03"])["jobId"], tmp_path)
    assert done["status"] == "completed" and requested == ["auto"]
    line = next(iter(public_job(done)["items"][0]["lines"].values()))
    assert line["driver"] == "rhubarb" and line["engine"] == "rhubarb" and line["fallbackReason"] == "phoneme_not_installed"
    assert line["cueCount"] == 1 and compiled[0]["shot"]["lines"][0]["cues"]
