"""An episode from a compact bilingual script, then rendered and cut in every language with one call."""
import time

import pytest

from services.series_produce import ProduceDeps, ProduceError, SeriesProduce
from services.series_script import ScriptError, apply_script

FILES = {"mus-theme-es.wav", "mus-theme-en.wav", "sfx-pen.wav", "prop-key.png", "mars.world3d.scene.json"}


def project():
    character = lambda cid: {"id": cid, "name": cid.title(), "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}"}}}
    return {"id": "uv", "revision": 4, "spokenLanguage": "Español de España",
            "characters": [character("kevin"), character("gary"), character("elon"), {"id": "nokit"}],
            "locations": [{"id": "garage", "variants": [{"id": "night"}]}, {"id": "mars", "variants": []}],
            "episodesById": {"ep1": {"id": "ep1", "number": 1, "shots": [{"id": "e1s00"}]}}}


KITS = {"kit-kevin": {"poses": {"panic": {}}}, "kit-gary": {"poses": {}}, "kit-elon": {"poses": {"phone": {}}}}

SCRIPT = {
    "title": {"es": "El vecino", "en": "The Neighbour"}, "premise": {"es": "Llega Mark."},
    "scenes": [{"id": "cold_open", "location": "garage", "variant": "night", "purpose": "Kevin oye un camión"},
               {"id": "mars", "location": "mars"}],
    "shots": [
        {"scene": "cold_open", "framing": "title", "duration": 6, "music": {"file": "mus-theme-es.wav", "en": "mus-theme-en.wav", "volume": 0.9},
         "card": {"kind": "title", "es": ["VALLE", "Episodio 3"], "en": ["VALLEY", "Episode 3"]}},
        {"scene": "cold_open", "framing": "two", "camera": "push",
         "cast": [["kevin", "panic", 30, {"enterFrom": "left"}], {"characterId": "gary", "x": 70}],
         "lines": [{"who": "kevin", "es": "¿Oyes eso?", "en": "Hear that?"},
                   {"who": "gary", "es": "...No.", "en": "...No.", "pauseBefore": 1.2}],
         "sfx": [{"file": "sfx-pen.wav", "line": 1, "anchor": "end"}], "fx": [{"kind": "confetti", "line": 1}],
         "props": [{"file": "prop-key.png", "x": 12, "y": 74}], "timing": {"intro": 1.0}},
        {"scene": "mars", "kind": "3d", "framing": "medium", "lines": [{"who": "elon", "es": "Marte.", "en": "Mars."}],
         "scene3d": {"scene": "mars.world3d.scene.json", "cast": [{"characterId": "elon", "objectId": "elon", "poseId": "phone"}]}},
    ],
}


class Series:
    """The series tools as LocalMcp returns them, over an in-memory project."""

    def __init__(self):
        self.series, self.calls = project(), []

    def read(self):
        return self.series

    def __call__(self, tool, arguments):
        data = arguments["input"]
        self.calls.append((tool, data))
        if tool == "series.episode.create":
            self.series["episodesById"]["ep2"] = {"id": "ep2", "number": 2, "shots": [], **data["episode"]}
            self.series["revision"] += 1
            return {"version": 1, "status": "completed", "result": {"episode": {"id": "ep2"}}}
        if tool == "series.episode.update":
            assert data["base_revision"] == self.series["revision"]
            return {"result": {"episode": {"id": data["episode_id"]}}}
        if tool == "series.episode.language_version.set":
            return {"result": {"missingLines": []}}
        raise AssertionError(tool)


def test_a_script_becomes_an_episode_with_its_ids_layout_and_language_versions():
    tools = Series()
    result = apply_script(tools, tools.read, KITS, FILES, "cast", SCRIPT)
    assert result["episodeId"] == "ep2" and result["shots"] == ["e2s00", "e2s01", "e2s02"]
    assert result["languages"] == ["spanish", "english"] and result["missingLines"] == {"english": []}
    created = tools.calls[0][1]["episode"]
    assert created == {"title": "El vecino", "premise": "Llega Mark."}
    episode = tools.calls[1][1]["episode"]
    assert [scene["id"] for scene in episode["script"]] == ["e2_cold_open", "e2_mars"]
    assert episode["script"][0]["participatingCharacterIds"] == ["gary", "kevin"]
    card, talk, mars = episode["shots"]
    assert card["durationSeconds"] == 6.0 and card["locationVariantId"] == "night"
    assert card["layout2d"]["card"] == {"kind": "title", "title": "VALLE", "body": "Episodio 3"}
    assert card["layout2d"]["music"] == {"file": "mus-theme-es.wav", "volume": 0.9, "start": 0}
    assert talk["layout2d"]["cast"][0] == {"characterId": "kevin", "poseId": "panic", "x": 30, "enterFrom": "left"}
    assert talk["dialogueBeats"][1] == {"id": "e2s01_b1", "characterId": "gary", "emotion": "", "delivery": "", "text": "...No.", "pauseBefore": 1.2}
    assert talk["speakingCharacterIds"] == ["gary", "kevin"] and "durationSeconds" not in talk, "a spoken shot takes its take's length"
    assert talk["layout2d"]["timing"] == {"intro": 1.0} and talk["layout2d"]["fx"] == [{"kind": "confetti", "line": 1}]
    assert mars["productionMethod"] == "animation_3d" and mars["scene3d"]["cast"][0]["objectId"] == "elon"
    english = tools.calls[2][1]
    assert english["language"] == "english" and english["title"] == "The Neighbour"
    assert english["dialogue"] == {"e2s01_b0": "Hear that?", "e2s01_b1": "...No.", "e2s02_b0": "Mars."}
    assert english["cards"] == {"e2s00": {"title": "VALLEY", "body": "Episode 3"}} and english["music"] == {"e2s00": "mus-theme-en.wav"}


def test_every_problem_is_listed_before_anything_is_written():
    tools = Series()
    bad = {"scenes": [{"id": "a", "location": "garage", "variant": "dawn"}], "shots": [
        {"scene": "a", "framing": "dutch", "cast": [["kevin", "dance"], ["nokit"], ["ghost"]],
         "lines": [{"who": "kevin", "en": "Only English."}, {"who": "ghost", "es": "Bu."}],
         "music": {"file": "missing.wav"}, "sfx": [{"file": "nope.wav"}], "fx": [{"kind": "sparkle-unicorn"}],
         "card": {"kind": "poster"}},
        {"scene": "b", "kind": "3d", "scene3d": {"template": "user-mars"}},
        {"scene": "a", "kind": "3d", "scene3d": {"scene": "gone.world3d.scene.json"}}]}
    with pytest.raises(ScriptError) as raised:
        apply_script(tools, tools.read, KITS, FILES, "cast", bad)
    problems = raised.value.problems
    expected = ["location garage has no variant dawn", "framing must be one of", "kevin has no pose dance (poses: base, panic)",
                "nokit has no Character Kit", "unknown character ghost", "line 0 has no spanish text", "line 1 has an unknown speaker ghost",
                "file missing.wav is not in the workspace", "file nope.wav is not in the workspace", "unknown effect sparkle-unicorn",
                "card kind must be one of", "shot 1 (e2s01): unknown scene b", "file gone.world3d.scene.json is not in the workspace"]
    for text in expected:
        assert any(text in problem for problem in problems), (text, problems)
    assert tools.calls == [], "nothing is written while the script has problems"


def test_check_only_and_rewriting_an_existing_episode():
    tools = Series()
    checked = apply_script(tools, tools.read, KITS, FILES, "cast", SCRIPT, check_only=True)
    assert checked == {"checked": True, "number": 2, "shots": ["e2s00", "e2s01", "e2s02"], "original": "spanish",
                       "languages": ["spanish", "english"]} and tools.calls == []
    rewritten = apply_script(tools, tools.read, KITS, FILES, "cast", {**SCRIPT, "shots": SCRIPT["shots"][:1]}, episode_id="ep1")
    assert rewritten["shots"] == ["e1s00"] and [tool for tool, _ in tools.calls][0] == "series.episode.update"
    with pytest.raises(ScriptError):
        apply_script(tools, tools.read, KITS, FILES, "cast", SCRIPT, episode_id="ep9")


class Production:
    """render_native and assembly as the produce job sees them; the first English render fails a shot once."""

    def __init__(self, fail_english=1):
        self.calls, self.fail_english, self.jobs = [], fail_english, {}

    def __call__(self, tool, arguments):
        data = arguments["input"]
        self.calls.append((tool, data))
        if tool == "series.episode.render_native":
            job_id = f"native-{data.get('language', 'spanish')}"
            self.jobs[job_id] = "failed" if data.get("language") == "english" and self.fail_english else "completed"
            return {"result": {"job": {"jobId": job_id, "status": "queued"}}}
        if tool == "series.episode.render_native.status":
            status = self.jobs[data["job_id"]]
            items = [{"shotId": "e2s01", "status": "failed", "error": "export crashed"}] if status == "failed" else []
            return {"result": {"job": {"jobId": data["job_id"], "status": status, "items": items, "message": status}}}
        if tool == "series.episode.render_native.resume":
            self.fail_english -= 1
            self.jobs[data["job_id"]] = "failed" if self.fail_english else "completed"
            return {"result": {"job": {"status": "queued"}}}
        if tool == "series.assembly.start":
            return {"result": {"job": {"jobId": f"cut-{data.get('language', 'spanish')}", "status": "queued"}}}
        if tool == "series.assembly.status":
            language = data["job_id"].split("-", 1)[1]
            return {"result": {"job": {"status": "completed", "assetId": f"asset-{language}", "filename": f"{language}.mp4"}}}
        raise AssertionError(tool)


def producer(tmp_path, tools):
    series = project()
    series["episodesById"]["ep2"] = {"id": "ep2", "languageVersions": {"english": {}}}
    series["assets"] = {"asset-spanish": {"metadata": {"subtitles": {"file": "spanish.subtitled.mp4", "srt": "spanish.srt"},
                                                       "loudness": {"after": {"lufs": -16.0}}}}}
    return SeriesProduce(ProduceDeps(call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: {"seriesById": {"uv": series}},
                                     sleep=lambda _s: None, poll_seconds=0))


def finished(service, job_id):
    for _ in range(200):
        job = service.status("cast", job_id)
        if job["status"] not in ("queued", "running", "cancelling"):
            return job
        time.sleep(0.02)
    raise AssertionError(service.status("cast", job_id))


def test_produce_renders_every_language_then_cuts_each_one(tmp_path):
    tools = Production()
    service = producer(tmp_path, tools)
    job = service.start("cast", "uv", "ep2")
    assert [(step["kind"], step["language"]) for step in job["steps"]] == [
        ("render", "spanish"), ("render", "english"), ("assemble", "spanish"), ("assemble", "english")]
    done = finished(service, job["jobId"])
    assert done["status"] == "completed", done
    renders = [data for tool, data in tools.calls if tool == "series.episode.render_native"]
    assert renders[0] == {"workspace": "cast", "series_id": "uv", "episode_id": "ep2", "approve": True}
    assert renders[1]["language"] == "english"
    assert [tool for tool, _ in tools.calls].count("series.episode.render_native.resume") == 1, "a failed shot is retried once"
    cuts = [data for tool, data in tools.calls if tool == "series.assembly.start"]
    assert cuts[0]["burn_subtitles"] is True and "language" not in cuts[0] and cuts[1]["language"] == "english"
    assert done["chapters"]["spanish"] == {"assetId": "asset-spanish", "file": "spanish.mp4", "subtitledFile": "spanish.subtitled.mp4",
                                           "srt": "spanish.srt", "loudness": {"lufs": -16.0}}
    assert done["chapters"]["english"]["file"] == "english.mp4"


def test_a_render_that_keeps_failing_stops_before_cutting_and_resumes(tmp_path):
    tools = Production(fail_english=3)
    service = producer(tmp_path, tools)
    failed = finished(service, service.start("cast", "uv", "ep2")["jobId"])
    assert failed["status"] == "failed" and "e2s01: export crashed" in failed["steps"][1]["error"]
    assert not any(tool == "series.assembly.start" for tool, _ in tools.calls)
    tools.fail_english = 1
    resumed = finished(service, service.resume("cast", failed["jobId"])["jobId"])
    assert resumed["status"] == "completed" and sorted(resumed["chapters"]) == ["english", "spanish"]
    assert [tool for tool, _ in tools.calls].count("series.episode.render_native") == 2, "resume reuses the render job"


def test_produce_refuses_a_language_without_a_version(tmp_path):
    service = producer(tmp_path, Production())
    with pytest.raises(ProduceError) as raised:
        service.start("cast", "uv", "ep2", languages=["spanish", "french"])
    assert raised.value.code == "no_version"
    with pytest.raises(ProduceError):
        service.start("cast", "uv", "nope")
