"""series.shot.update: edit one shot by id or number with script keys; only what changed is written."""
from __future__ import annotations

import asyncio
import copy

import pytest
from fastapi import HTTPException

from routers.series_shot_edit import ShotEdit, create_series_shot_edit_router
from services.series_library import normalize_series_library
from services.series_script import EpisodeScript
from services.series_shot_edit import (
    ShotEditError, apply_edit, build_patch, find_shot, merge_changes, take_still_fits, to_script,
)
from tests.test_series_script_produce import FILES, KITS, SCRIPT, project

FILES = {*FILES, "sfx-boom.wav", "prop-hat.png"}


def library():
    series = project()
    series["episodesById"].pop("ep1")  # a stub without scenes; this test edits episode 2
    built = EpisodeScript(series, SCRIPT, 2, KITS, FILES)
    built.check()
    shots = built.shots()
    shots[1].update(attempts=[{"id": "att-1", "status": "completed", "outputAssetIds": ["asset_t1"]}], approvedAttemptId="att-1")
    shots.append({"id": "e2s03", "order": 4, "sceneId": "e2_cold_open", "locationId": "garage", "productionMethod": "imported_video",
                  "durationSeconds": 6.0, "layout2d": {"sfx": [{"file": "sfx-pen.wav", "at": 1.0, "volume": 0.8}]},
                  "attempts": [{"id": "att-v", "status": "completed", "outputAssetIds": ["asset_v"]}], "approvedAttemptId": "att-v"})
    english = {**built.version("english"), "approvedAttemptIds": {"e2s01": "att-1", "e2s03": "att-v"}}
    series["episodesById"]["ep2"] = {"id": "ep2", "number": 2, "title": "El vecino", "script": built.scene_list(), "shots": shots,
                                     "languageVersions": {"english": english}}
    series["assets"] = {"asset_t1": {"id": "asset_t1", "kind": "video", "uri": "outputs/t1.mp4"},
                        "asset_v": {"id": "asset_v", "kind": "video", "uri": "outputs/v.mp4"}}
    return series


def edit(series, ref, changes=None, append=None):
    episode = series["episodesById"]["ep2"]
    shot, number = find_shot(episode, ref)
    merged, changed = merge_changes(to_script(series, episode, shot), changes, append)
    patch, texts = build_patch(series, episode, shot, merged, changed, KITS, FILES, None)
    updated, info = apply_edit(series, "ep2", shot["id"], patch, texts, changed, take_still_fits(shot, changed))
    return updated["episodesById"]["ep2"], next(item for item in updated["episodesById"]["ep2"]["shots"] if item["id"] == shot["id"]), info, changed


def test_a_shot_is_found_by_its_id_or_its_number_in_the_episode():
    episode = library()["episodesById"]["ep2"]
    assert find_shot(episode, 2)[0]["id"] == "e2s01" and find_shot(episode, "#2")[0]["id"] == "e2s01"
    assert find_shot(episode, "e2s02") == (find_shot(episode, 3)[0], 3)
    for missing in (9, 0, "e9s99"):
        with pytest.raises(ShotEditError) as error:
            find_shot(episode, missing)
        assert error.value.status == 404


def test_the_stored_shot_reads_back_as_its_script_with_every_language():
    series = library()
    script = to_script(series, series["episodesById"]["ep2"], find_shot(series["episodesById"]["ep2"], 2)[0])
    assert script["scene"] == "cold_open" and script["framing"] == "two" and script["camera"] == "push"
    assert script["lines"][1] == {"who": "gary", "spanish": "...No.", "english": "...No.", "pauseBefore": 1.2}
    assert script["cast"][0]["poseId"] == "panic" and script["fx"] == [{"kind": "confetti", "line": 1}]
    card = to_script(series, series["episodesById"]["ep2"], find_shot(series["episodesById"]["ep2"], 1)[0])
    assert card["card"] == {"kind": "title", "spanish": ["VALLE", "Episodio 3"], "english": ["VALLEY", "Episode 3"]}
    assert card["music"]["en"] == "mus-theme-en.wav" and card["duration"] == 6.0


def test_appending_an_effect_writes_only_the_effects_and_resets_the_approvals():
    series = library()
    before = copy.deepcopy(find_shot(series["episodesById"]["ep2"], 2)[0])
    episode, shot, info, changed = edit(series, 2, append={"fx": [{"kind": "manga_impact", "line": 0, "x": 70}]})
    assert changed == ["fx"]
    assert [item["kind"] for item in shot["layout2d"]["fx"]] == ["confetti", "manga_impact"]
    assert {key: value for key, value in shot["layout2d"].items() if key != "fx"} == \
        {key: value for key, value in before["layout2d"].items() if key != "fx"}
    assert shot["dialogueBeats"] == before["dialogueBeats"] and shot["attempts"][0]["id"] == "att-1", "the take is kept"
    assert "approvedAttemptId" not in shot and info["approvalReset"] is True
    assert "e2s01" not in episode["languageVersions"]["english"]["approvedAttemptIds"]
    assert episode["languageVersions"]["english"]["approvedAttemptIds"]["e2s03"] == "att-v", "other shots keep theirs"


def test_new_lines_rewrite_the_beats_and_each_language_versions_text():
    series = library()
    episode, shot, info, _ = edit(series, "e2s01", changes={"lines": [
        {"who": "kevin", "es": "¿Y el sombrero?", "en": "And the hat?"}, {"who": "gary", "es": "Lo llevo yo."}]},
        append={"props": [{"file": "prop-hat.png", "x": 70, "y": 20, "scale": 0.1}]})
    assert [beat["text"] for beat in shot["dialogueBeats"]] == ["¿Y el sombrero?", "Lo llevo yo."]
    assert shot["speakingCharacterIds"] == ["gary", "kevin"] and len(shot["layout2d"]["props"]) == 2
    dialogue = episode["languageVersions"]["english"]["dialogue"]
    assert dialogue["e2s01_b0"] == "And the hat?" and "e2s01_b1" not in dialogue and dialogue["e2s02_b0"] == "Mars."
    assert info["missingLines"] == {"english": ["e2s01_b1"]}


def test_an_edit_is_checked_like_a_script_shot_before_anything_is_written():
    series = library()
    with pytest.raises(ShotEditError) as bad:
        edit(series, 2, changes={"cast": [["kevin", "dance", 30]], "sfx": [{"file": "nope.wav"}], "fx": [{"kind": "unicorn"}]})
    assert any("kevin has no pose dance" in item for item in bad.value.problems)
    assert any("nope.wav" in item for item in bad.value.problems) and any("unicorn" in item for item in bad.value.problems)
    with pytest.raises(ShotEditError, match="Unknown shot keys: hat"):
        edit(series, 2, changes={"hat": True})
    with pytest.raises(ShotEditError, match="Send changes or append"):
        edit(series, 2)


def test_a_video_take_keeps_its_approval_when_only_its_cut_sound_changes():
    series = library()
    _episode, shot, info, changed = edit(series, 4, changes={"clipAudio": "drop", "foley": {"prompt": "waves", "volume": 0.4}},
                                         append={"sfx": [{"file": "sfx-boom.wav", "at": 2.0, "in": 0.5, "length": 0.4}]})
    assert sorted(changed) == ["clipAudio", "foley", "sfx"] and info["approvalReset"] is False
    assert shot["approvedAttemptId"] == "att-v" and shot["layout2d"]["clipAudio"] == "drop"
    assert shot["layout2d"]["sfx"][1] == {"file": "sfx-boom.wav", "at": 2.0, "in": 0.5, "length": 0.4}
    assert shot["foley"] == {"prompt": "waves", "volume": 0.4} and shot["productionMethod"] == "imported_video"
    _episode, moved, info, _ = edit(series, 4, changes={"kind": None})
    assert moved["productionMethod"] == "animation_2d" and info["approvalReset"] is True


class Library:
    def __init__(self):
        self.series, self.calls = library(), []

    def read(self, _workspace):
        return {"seriesById": {"uv": copy.deepcopy(self.series)}}

    def change(self, _workspace, series_id, change):
        working = copy.deepcopy(self.series)
        change(working)
        working["revision"] = int(working.get("revision") or 1) + 1
        # As the library writes it: normalized (layout2d values get their defaults).
        self.series = normalize_series_library({"seriesById": {series_id: working}}, "cast")["seriesById"][series_id]
        return copy.deepcopy(self.series)

    def call(self, name, arguments):
        self.calls.append((name, arguments["input"]))
        return {"result": {"job": {"jobId": f"{name}-1", "status": "queued"}}}


def _router(tmp_path, store, plan_changes=None):
    for name in FILES:
        (tmp_path / name).write_bytes(b"x")
    router = create_series_shot_edit_router(change_series=store.change, read_library=store.read, read_kits=lambda _ws: KITS,
                                            workspace_dir=lambda _ws: str(tmp_path), call=store.call, bind_loop=lambda _loop: None,
                                            plan_changes=plan_changes)
    return {(route.path, tuple(route.methods)[0]): route.endpoint for route in router.routes}


def test_the_route_edits_the_fifth_shot_and_renders_just_that_shot(tmp_path):
    store = Library()
    routes = _router(tmp_path, store)
    post = routes[("/api/v1/series/{series_id}/episodes/{episode_id}/shots/edit", "POST")]
    checked = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, changes={"camera": "static"}, check=True)))
    assert checked["checked"] is True and checked["patch"]["camera"] == "static" and store.calls == []
    assert store.series["episodesById"]["ep2"]["shots"][1]["layout2d"]["camera"] == "push", "check writes nothing"
    reply = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, append={"fx": [{"kind": "confetti", "at": 0.5}]},
                                                   render=True)))
    assert reply["shotId"] == "e2s01" and reply["number"] == 2 and reply["approvalReset"] is True
    assert reply["shot"]["script"]["fx"][-1] == {"kind": "confetti", "at": 0.5, "duration": 1.0}
    assert store.calls == [("series.episode.render_native", {"workspace": "cast", "series_id": "uv", "episode_id": "ep2",
                                                             "shot_ids": ["e2s01"], "approve": True})]
    assert reply["render"]["jobId"] == "series.episode.render_native-1"
    video = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot="e2s03", changes={"clipVolume": 0.5}, render=True)))
    assert "laid at the cut" in video["note"] and len(store.calls) == 1
    produced = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=3, changes={"foley": {"prompt": "wind"}}, produce=True)))
    assert produced["produce"]["jobId"] == "series.episode.produce-1"
    with pytest.raises(HTTPException) as missing:
        asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=12, changes={"camera": "push"})))
    assert missing.value.status_code == 404 and missing.value.detail["code"] == "shot_not_found"
    get = routes[("/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot}", "GET")]
    view = asyncio.run(get("uv", "ep2", "4", "cast"))
    assert view["shotId"] == "e2s03" and view["script"]["kind"] == "video" and view["takes"][0]["approved"] is True


def test_the_wizard_says_edit_the_fifth_shot_and_put_a_hat_on_him_and_the_llm_writes_the_edit(tmp_path):
    """An instruction without changes: the model sees the shot, the cast's poses and the files, writes the edit; a refused
    edit goes back once with its problems."""
    asked = []

    def model(prompt, system, schema):
        asked.append(prompt)
        if len(asked) == 1:
            return {"append": {"props": [{"file": "prop-sombrero.png", "x": 30, "y": 20}]}, "summary": "Sombrero"}
        return {"append": {"props": [{"file": "prop-hat.png", "x": 30, "y": 20, "scale": 0.1}]}, "changes": {"framing": "close"},
                "summary": "Le pongo el sombrero a Kevin en un primer plano"}

    store = Library()
    store.series["episodesById"]["ep2"]["shots"][1]["order"] = 5  # the fifth shot of the episode
    post = _router(tmp_path, store, model)[("/api/v1/series/{series_id}/episodes/{episode_id}/shots/edit", "POST")]
    reply = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=5, instruction="ponle el sombrero a Kevin")))
    assert reply["shotId"] == "e2s01" and sorted(reply["changed"]) == ["framing", "props"]
    assert reply["instruction"]["summary"].startswith("Le pongo") and len(asked) == 2
    assert '"prop-hat.png"' in asked[0] and '"panic"' in asked[0] and "ponle el sombrero" in asked[0]
    assert "prop-sombrero.png is not in the workspace" in asked[1], "the refusal goes back to the model"
    shot = next(item for item in store.series["episodesById"]["ep2"]["shots"] if item["id"] == "e2s01")
    assert shot["layout2d"]["props"][-1]["file"] == "prop-hat.png" and shot["layout2d"]["framing"] == "close"
    assert shot["framing"] == "close" and "approvedAttemptId" not in shot


def test_an_instruction_without_an_llm_and_a_render_without_changes(tmp_path):
    store = Library()
    post = _router(tmp_path, store)[("/api/v1/series/{series_id}/episodes/{episode_id}/shots/edit", "POST")]
    with pytest.raises(HTTPException) as unavailable:
        asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, instruction="más dramático")))
    assert unavailable.value.status_code == 503 and unavailable.value.detail["code"] == "llm_unavailable"
    rendered = asyncio.run(post("uv", "ep2", ShotEdit(workspace="cast", shot=2, render=True, approve=False)))
    assert rendered["changed"] == [] and store.calls[-1][1]["shot_ids"] == ["e2s01"] and store.calls[-1][1]["approve"] is False
