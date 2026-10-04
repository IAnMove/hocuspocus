"""One episode, two languages: same shots, own lines, voices, takes and cut."""
import copy
import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_language_versions import create_series_language_versions_router
from services.series_language_versions import (
    localized_view, missing_lines, normalize_language_versions, translation_request, version_from_translation,
)


def episode():
    return {"id": "ep1", "title": "Piloto", "shots": [
        {"id": "s0", "layout2d": {"card": {"kind": "title", "title": "VALLE", "body": "Episodio 1"}}, "dialogueBeats": [],
         "attempts": [{"id": "a0"}], "approvedAttemptId": "a0"},
        {"id": "s1", "dialogueBeats": [{"id": "b1", "characterId": "kevin", "text": "Vale, Gary."}, {"id": "b2", "characterId": "gary", "text": "¡Hola!"}],
         "attempts": [{"id": "a1"}, {"id": "a1en"}], "approvedAttemptId": "a1"},
    ]}


def series(versions=None):
    value = {"id": "uv", "title": "Valle", "spokenLanguage": "Español de España", "episodesById": {"ep1": episode()}}
    if versions is not None:
        value["episodesById"]["ep1"]["languageVersions"] = versions
    return value


ENGLISH = {"title": "Pilot", "dialogue": {"b1": "Okay, Gary.", "b2": "Hi!"}, "cards": {"s0": {"title": "VALLEY", "body": ""}},
           "approvedAttemptIds": {"s1": "a1en"}, "assemblyAssetIds": ["cut-en"], "latestAssemblyAssetId": "cut-en"}


def test_versions_keep_known_languages_lines_shots_and_takes():
    raw = {"english": {**ENGLISH, "dialogue": {**ENGLISH["dialogue"], "ghost": "x", "b2": "  "}, "approvedAttemptIds": {"s1": "a1en", "s0": "nope"},
                       "cards": {"s0": ENGLISH["cards"]["s0"], "s9": {"title": "x"}}, "latestAssemblyAssetId": "other"},
           "spanish": {"title": "original"}, "klingon": {"title": "x"}}
    versions = normalize_language_versions(raw, episode()["shots"], "spanish")
    assert set(versions) == {"english"}
    english = versions["english"]
    assert english["dialogue"] == {"b1": "Okay, Gary."} and english["approvedAttemptIds"] == {"s1": "a1en"}
    assert set(english["cards"]) == {"s0"} and "latestAssemblyAssetId" not in english


def test_a_localized_view_switches_lines_cards_takes_and_language():
    original = series({"english": ENGLISH})
    same = localized_view(original, original["episodesById"]["ep1"], "spanish")
    assert same[0] is original
    view_series, view_episode = localized_view(original, original["episodesById"]["ep1"], "english")
    assert view_series["spokenLanguage"] == "English" and view_episode["title"] == "Pilot"
    assert [beat["text"] for beat in view_episode["shots"][1]["dialogueBeats"]] == ["Okay, Gary.", "Hi!"]
    assert view_episode["shots"][0]["layout2d"]["card"] == {"kind": "title", "title": "VALLEY", "body": "Episodio 1"}
    assert view_episode["shots"][1]["approvedAttemptId"] == "a1en" and "approvedAttemptId" not in view_episode["shots"][0]
    assert original["episodesById"]["ep1"]["shots"][1]["dialogueBeats"][0]["text"] == "Vale, Gary.", "the original is not touched"
    with pytest.raises(ValueError):
        localized_view(original, original["episodesById"]["ep1"], "french")


def test_translation_asks_for_every_line_and_card_and_ignores_unknown_ids():
    prompt, system, schema = translation_request(series(), episode(), "english")
    assert "b1" in prompt and "b2" in prompt and "s0" in prompt and "English" in prompt and "dubbing" in system
    assert schema["required"] == ["title", "lines", "cards"]
    version = version_from_translation({"title": "Pilot", "lines": [{"id": "b1", "text": "Okay, Gary."}, {"id": "zz", "text": "no"}],
                                        "cards": [{"shotId": "s0", "title": "VALLEY", "body": "Episode 1"}]}, episode())
    assert version["dialogue"] == {"b1": "Okay, Gary."} and version["cards"]["s0"]["body"] == "Episode 1"
    assert missing_lines({**episode(), "languageVersions": {"english": version}}, "english") == ["b2"]


def test_the_series_library_keeps_a_version():
    from services.series_library import normalize_series_project
    project = normalize_series_project({"id": "uv", "title": "Valle", "spokenLanguage": "Español",
                                        "characters": [{"id": "kevin"}, {"id": "gary"}], "episodesById": {
        "ep1": {**episode(), "script": [{"id": "scene_1", "dialogue": []}],
                "shots": [{**shot, "productionMethod": "animation_2d", "sceneId": "scene_1"} for shot in episode()["shots"]],
                "languageVersions": {"english": ENGLISH, "spanish": ENGLISH}}}}, "uv", "cast")
    assert set(project["episodesById"]["ep1"]["languageVersions"]) == {"english"}


def test_the_router_writes_translates_and_removes_versions():
    store = {"series": series()}

    def change(workspace, series_id, episode_id, apply):
        current = store["series"]
        apply(current, current["episodesById"][episode_id])
        current["revision"] = current.get("revision", 1) + 1
        return copy.deepcopy(current)

    def read(workspace, series_id, episode_id):
        return store["series"], store["series"]["episodesById"][episode_id]

    asked = []
    app = FastAPI()
    app.include_router(create_series_language_versions_router(change_episode=change, read_episode=read,
        translate=lambda prompt, system, schema: asked.append(prompt) or {"title": "Pilot", "lines": [{"id": "b1", "text": "Okay."}], "cards": []}))
    client = TestClient(app)
    path = "/api/v1/series/uv/episodes/ep1/language-versions/english"
    translated = client.post(f"{path}/translate", json={"workspace": "cast"})
    assert translated.status_code == 200, translated.text
    assert translated.json()["version"]["dialogue"] == {"b1": "Okay."} and translated.json()["missingLines"] == ["b2"] and asked
    written = client.put(path, json={"workspace": "cast", "version": {"dialogue": {"b2": "Hi!"}}}).json()
    assert written["missingLines"] == [] and written["version"]["dialogue"] == {"b1": "Okay.", "b2": "Hi!"}
    refused = client.put("/api/v1/series/uv/episodes/ep1/language-versions/spanish", json={"workspace": "cast", "version": {}})
    assert refused.status_code == 400 and refused.json()["detail"]["code"] == "original_language"
    assert client.request("DELETE", path, json={"workspace": "cast"}).json()["deleted"] is True
    assert "english" not in store["series"]["episodesById"]["ep1"]["languageVersions"]


def test_the_server_render_speaks_a_version_and_approves_its_own_takes(tmp_path):
    from tests.test_series_native_render import Tools, finished, library
    from services.series_native_render import NativeRenderDeps, NativeRenderError, SeriesNativeRender
    data = library()
    data["seriesById"]["uv"]["episodesById"]["ep1"]["languageVersions"] = {
        "english": {"dialogue": {"s01_d0": "Okay, Gary.", "s01_d1": "Good news."}, "cards": {}, "approvedAttemptIds": {}}}
    tools, approved, shot_lengths, version_lengths = Tools(tmp_path), [], [], []
    english = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "aiden"}
    kits = {f"kit-{cid}": {"id": f"kit-{cid}", "name": cid, "base": {"source": "/api/v1/file/k.png", "width": 400, "height": 800}, "poses": {},
                           "voice": {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan"},
                           "voicesByLanguage": {"english": english}} for cid in ("kevin", "gary")}

    def trim(source, target):
        open(target, "wb").write(open(source, "rb").read())
        return 1.0

    render = SeriesNativeRender(NativeRenderDeps(
        call=tools, workspace_dir=lambda _ws: str(tmp_path), read_library=lambda _ws: data, read_kits=lambda _ws: kits,
        compile_shot=lambda payload: {"duration": payload["shot"]["duration"], "lines": payload["shot"]["lines"]}, trim=trim,
        sleep=lambda _s: None, poll_seconds=0, set_shot_duration=lambda *args: shot_lengths.append(args),
        set_version_take=lambda *args: approved.append(args), set_version_duration=lambda *args: version_lengths.append(args)))
    with pytest.raises(NativeRenderError) as untranslated:
        render.start("cast", "uv", "ep1", language="english")
    assert untranslated.value.code == "untranslated", "s03 has no English line yet"
    assert untranslated.value.args[0].startswith("1 lines"), "only the 2D shots to render count"
    job = render.start("cast", "uv", "ep1", language="english", shot_ids=["s01"], approve=True)
    done = finished(render, job["jobId"], tmp_path)
    assert done["status"] == "completed" and done["language"] == "english" and done["original"] is False
    spoken = [args["input"]["params"] for tool, args in tools.calls if tool == "generation.speech"]
    assert [params["prompt"] for params in spoken] == ["Okay, Gary.", "Good news."]
    assert all(params["model_mode"] == "aiden" for params in spoken), "each character's English voice"
    saved = [args["input"]["name"] for tool, args in tools.calls if tool == "scenes.document.save"]
    assert saved == ["uv-ep1-s01-english"]
    assert approved == [("cast", "uv", "ep1", "english", "s01", "attempt-s01")]
    assert shot_lengths == [] and [args[:5] for args in version_lengths] == [("cast", "uv", "ep1", "english", "s01")], \
        "an English take sets the English length, not the shot's"

    assert not [tool for tool, _ in tools.calls if tool == "series.take.approve"], "the original approval is untouched"
    imported = [args["input"]["metadata"] for tool, args in tools.calls if tool == "series.asset.import"]
    assert imported[0]["language"] == "english"
