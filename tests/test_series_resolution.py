"""Series video resolution: 480p by default; a series and a shot can choose 540p, 720p or 768p.

The pinned digests were computed with the code before sizes were selectable (development 3e3ddf50). A shot or a
take stored then must keep every digest it had, so nothing already made is made again or reads as out of date.
"""
import copy
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

import pytest

from services.series_library import (
    SHOT_CONTENT_FIELDS, SHOT_EDITOR_FIELDS, create_series_project, import_story_project, normalize_series_project,
    update_series_episode,
)
from services.series_render import (
    SERIES_RESOLUTIONS, build_h3_generation_params, normalize_series_resolution, shot_render_settings,
)
from services.series_review import content_digest
from services.series_script import ScriptError, apply_script
from services.series_shot_edit import ShotEditError
from services.series_take_inputs import render_inputs
from services.series_video_shots import (
    _request_digest, _take_digest, _take_matches, digest_request, normalize_video, video_preset, video_resolution,
)
from tests.test_series_render import inputs
from tests.test_series_script_produce import FILES, KITS, Series, finished
from tests.test_series_shot_edit import edit, library
from tests.test_series_video_shots import _episode, _produce, _request, _Server, _video_calls, _png

# Digests of the fixtures below before this change.
OLD_VIDEO_REQUEST = "5d0a932a4a79774a"
OLD_CONTENT = "68cc99a516f4a69f"
OLD_TAKE = "0a57e6ccafd0"
OLD_PLATE = "2473f6c7d39e"
OLD_2D_INPUTS = "ae52bcc55179975d"
OLD_2D_CONTENT = "c1a6b46b3799ab16"
OLD_DEFAULT_SERIES = {"provider": {"videoModel": "minimax_h3_legacy",
                                   "videoSettings": {"resolution": "540p", "orientation": "landscape"}}}


def _stored_video_shot():
    return {"id": "s00", "productionMethod": "imported_video", "video": _request()["video"],
            "layout2d": {"clipAudio": "drop"}, "dialogueBeats": [], "visibleCharacterIds": [], "locationId": "garage",
            "framing": "wide", "camera": "static"}


def _video_digest(series, shot):
    return _request_digest(digest_request(normalize_video(shot["video"]), video_preset(series, shot)))


def test_a_stored_shot_keeps_every_digest_it_had():
    shot = _stored_video_shot()
    assert content_digest(shot) == OLD_CONTENT
    for series in ({}, OLD_DEFAULT_SERIES, {"videoShotResolution": "480p"}):
        assert _video_digest(series, shot) == OLD_VIDEO_REQUEST
        assert video_resolution(series, shot) == "864x480"
    params = {"prompt": "A quiet room", "model_type": "minimax_h3", "resolution": "864x480", "video_length": 124,
              "image_start": "/x", "image_end": "/x"}
    assert _take_digest(params, "/no/such/start.png") == OLD_TAKE
    plate = {"workspace": "cast", "size": [864, 480], "background": "#c4b49a",
             "layers": [{"file": "series-video/s00-plate.png", "x": 50, "y": 50}], "output_name": "s00-video-start"}
    assert hashlib.sha1(json.dumps(plate, sort_keys=True).encode()).hexdigest()[:12] == OLD_PLATE
    two_d = {"id": "s01", "productionMethod": "animation_2d", "layout2d": {"framing": "wide", "camera": "static"},
             "dialogueBeats": [], "durationSeconds": 5}
    assert render_inputs({"characters": [], "locations": []}, two_d, {}) == OLD_2D_INPUTS
    assert content_digest(two_d) == OLD_2D_CONTENT
    # A shot's own size is not what it shows: review decisions and native render inputs never count it.
    assert "resolution" in SHOT_EDITOR_FIELDS and "resolution" not in SHOT_CONTENT_FIELDS
    assert content_digest({**shot, "resolution": "720p"}) == OLD_CONTENT


def test_a_480p_choice_is_the_old_digest_and_any_other_size_is_a_new_request():
    shot = _stored_video_shot()
    assert _video_digest({}, {**shot, "resolution": "480p"}) == OLD_VIDEO_REQUEST
    sized = {_video_digest({}, {**shot, "resolution": preset}) for preset in ("540p", "720p", "768p")}
    assert len(sized) == 3 and OLD_VIDEO_REQUEST not in sized
    # The series' choice and the shot's own name the same request when they name the same size.
    assert _video_digest({"videoShotResolution": "720p"}, shot) == _video_digest({}, {**shot, "resolution": "720p"})


def test_a_stored_series_reads_back_unchanged():
    stored = {"id": "uv", "provider": copy.deepcopy(OLD_DEFAULT_SERIES["provider"]),
              "allowedProductionMethods": ["imported_video"], "locations": [{"id": "garage"}],
              "episodesById": {"ep1": {"id": "ep1", "number": 1, "script": [{"id": "scene_1"}],
                                       "shots": [{**_stored_video_shot(), "sceneId": "scene_1"}]}}}
    normalized = normalize_series_project(stored, "uv", "cast")
    assert normalized["provider"]["videoSettings"]["resolution"] == "540p", "a saved Series Lab size is kept"
    assert "videoShotResolution" not in normalized
    shot = normalized["episodesById"]["ep1"]["shots"][0]
    assert "resolution" not in shot and shot["video"] == _request()["video"]
    assert content_digest(shot) == OLD_CONTENT


def _made_before(library):
    """The episode's shot with a completed take made before sizes were selectable."""
    series = library["seriesById"]["uv"]
    shot = series["episodesById"]["ep1"]["shots"][0]
    shot["attempts"] = [{"id": "att-old", "status": "completed", "outputAssetIds": ["asset_old"]}]
    shot["approvedAttemptId"] = "att-old"
    series["assets"] = {"asset_old": {"id": "asset_old", "kind": "video", "uri": "outputs/old.mp4",
                                      "metadata": {"videoRequest": OLD_VIDEO_REQUEST}}}
    return series, shot


def test_a_take_made_before_sizes_existed_is_not_made_again(tmp_path):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip)
    library, _episode_body = _episode(_request())
    series, shot = _made_before(library)
    series["provider"] = copy.deepcopy(OLD_DEFAULT_SERIES["provider"])
    assert _take_matches(series, shot)
    service = _produce(tmp_path, tools, library)
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    assert _video_calls(tools, "generation.video") == [] and tools.imports == []
    # Choosing another size for that shot is a new request: its take is made again, at that size.
    shot["resolution"] = "720p"
    assert not _take_matches(series, shot)
    done = finished(service, service.start("cast", "uv", "ep1")["jobId"])
    assert done["status"] == "completed", done
    params = _video_calls(tools, "generation.video")[0]["input"]["params"]
    assert params["resolution"] == "1280x704"
    assert tools.imports[0]["metadata"]["videoRequest"] == _video_digest(series, shot) != OLD_VIDEO_REQUEST
    shot["resolution"] = "480p"
    assert _take_matches(series, shot), "back to 480p, the old take fits again"


def test_a_480p_take_asks_for_the_same_clip_plate_and_intent_as_before(tmp_path):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip)
    library, _episode_body = _episode(_request())
    library["seriesById"]["uv"]["provider"] = copy.deepcopy(OLD_DEFAULT_SERIES["provider"])
    service = _produce(tmp_path, tools, library)
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    plate = _video_calls(tools, "media.compose")[0]
    assert plate["intent_id"] == f"series-ep1-s00-start-{OLD_PLATE}" and plate["input"]["size"] == [864, 480]
    composed = tools.intents[("media.compose", plate["intent_id"])][1]["result"]["file"]
    reference = f"/api/v1/file/{quote(composed)}?workspace=cast"
    sent = _video_calls(tools, "generation.video")[0]
    params = {"prompt": "A quiet room", "model_type": "minimax_h3", "resolution": "864x480", "video_length": 124,
              "image_start": reference, "image_end": reference}
    assert sent["input"]["params"] == params
    start = hashlib.sha1((tmp_path / composed).read_bytes()).hexdigest()
    take = hashlib.sha1(json.dumps({"params": params, "start": start}, sort_keys=True).encode()).hexdigest()[:12]
    assert sent["intent_id"] == f"series-ep1-s00-video-{take}-1"
    assert tools.imports[0]["metadata"]["videoRequest"] == OLD_VIDEO_REQUEST


@pytest.mark.parametrize(("series_size", "shot_size", "portrait", "canvas"), [
    ("720p", None, False, "1280x704"),
    ("720p", "540p", False, "960x544"),
    (None, "768p", True, "768x1344"),
    ("768p", "480p", False, "864x480"),
])
def test_the_series_and_the_shot_choose_the_clip_size(tmp_path, series_size, shot_size, portrait, canvas):
    clip = _png(tmp_path / "clip.png", (196, 180, 154))
    tools = _Server(tmp_path, clip)
    request = _request()
    if shot_size:
        request["resolution"] = shot_size
    library, _episode_body = _episode(request)
    series = library["seriesById"]["uv"]
    if series_size:
        series["videoShotResolution"] = series_size
    if portrait:
        series["provider"] = {"videoSettings": {"orientation": "portrait"}}
    service = _produce(tmp_path, tools, library)
    assert finished(service, service.start("cast", "uv", "ep1")["jobId"])["status"] == "completed"
    size = [int(part) for part in canvas.split("x")]
    assert _video_calls(tools, "generation.video")[0]["input"]["params"]["resolution"] == canvas
    assert _video_calls(tools, "media.compose")[0]["input"]["size"] == size


def test_both_h3_models_keep_every_tier_and_a_canvas_maps_back_to_it():
    canvases = {"480p": ("864x480", "480x864"), "540p": ("960x544", "544x960"),
                "720p": ("1280x704", "704x1280"), "768p": ("1344x768", "768x1344")}
    assert tuple(canvases) == SERIES_RESOLUTIONS
    for model in ("minimax_h3", "minimax_h3_legacy", "minimax_h3_ref2va"):
        for preset, (landscape, portrait) in canvases.items():
            assert normalize_series_resolution(preset, "landscape", model) == (landscape, "landscape")
            assert normalize_series_resolution(preset, "portrait", model) == (portrait, "portrait")
            assert normalize_series_resolution(landscape, "landscape", model) == (landscape, "landscape")
            assert normalize_series_resolution(portrait, "portrait", model) == (portrait, "portrait")
        for empty in (None, "", "1080p", "auto"):
            assert normalize_series_resolution(empty, "landscape", model) == ("864x480", "landscape")
    assert normalize_series_resolution("1280x720", "landscape", "minimax_h3_legacy") == ("1280x704", "landscape")


@pytest.mark.parametrize(("model", "canvas"), [
    ("minimax_h3_legacy", "960x544"), ("minimax_h3_legacy", "1280x704"), ("minimax_h3_legacy", "864x480"),
    ("minimax-h3", "1280x704"), ("minimax-h3", "864x480"), ("minimax-h3", "704x1280"),
])
def test_a_queued_attempt_builds_the_size_it_was_frozen_with(model, canvas):
    series, shot, attempt = inputs("direct")
    attempt["model"] = model
    attempt["settings"] = {**attempt["settings"], "resolution": canvas,
                           "orientation": "portrait" if canvas == "704x1280" else "landscape"}
    assert build_h3_generation_params(series, shot, attempt, {})["resolution"] == canvas


def test_a_series_lab_render_takes_the_shots_own_size():
    settings = {"resolution": "960x544", "orientation": "portrait", "numInferenceSteps": 20}
    assert shot_render_settings(settings, {"id": "s1"}) == settings
    assert shot_render_settings(settings, {"id": "s1", "resolution": "720p"}) == {**settings, "resolution": "704x1280"}
    assert settings["resolution"] == "960x544", "the series' settings are not changed"


def test_the_series_lab_render_start_freezes_each_shots_own_size():
    text = (Path(__file__).resolve().parents[1] / "app" / "routers" / "series_render.py").read_text(encoding="utf-8")
    body = text.split("def start_series_episode_render", 1)[1].split("\ndef ", 1)[0]
    assert "**shot_render_settings(settings, shot)," in body
    assert body.index("normalize_series_resolution(") < body.index("shot_render_settings(settings, shot)")


def test_new_series_are_480p_and_a_series_choice_is_checked():
    assert create_series_project("cast")["provider"]["videoSettings"]["resolution"] == "480p"
    imported = import_story_project({"id": "story_1", "title": "Story"}, "cast")
    assert imported["provider"]["videoSettings"]["resolution"] == "480p"
    bare = normalize_series_project({"id": "uv", "provider": {"videoSettings": {}}}, "uv", "cast")
    assert bare["provider"]["videoSettings"]["resolution"] == "480p"
    chosen = normalize_series_project({"id": "uv", "videoShotResolution": "720"}, "uv", "cast")
    assert chosen["videoShotResolution"] == "720p"
    cleared = normalize_series_project({"id": "uv", "videoShotResolution": ""}, "uv", "cast")
    assert "videoShotResolution" not in cleared
    with pytest.raises(ValueError, match="videoShotResolution must be one of 480p, 540p, 720p, 768p"):
        normalize_series_project({"id": "uv", "videoShotResolution": "4k"}, "uv", "cast")


def _edited(shot):
    series = normalize_series_project({
        "id": "uv", "allowedProductionMethods": ["imported_video", "animation_2d"],
        "episodesById": {"ep1": {"id": "ep1", "number": 1, "script": [{"id": "scene_1"}],
                                 "shots": [{"id": "s00", "sceneId": "scene_1", "productionMethod": "imported_video"}]}},
    }, "uv", "cast")
    edited = update_series_episode(series, "ep1", {"shots": [{"id": "s00", **shot}]}, base_series_revision=series["revision"])
    return normalize_series_project(edited, "uv", "cast")["episodesById"]["ep1"]["shots"][0]


def test_the_episode_editor_stores_a_video_shots_size_only():
    assert _edited({"resolution": "1344x768"})["resolution"] == "768p"
    assert "resolution" not in _edited({"resolution": None})
    assert "resolution" not in _edited({"productionMethod": "animation_2d", "resolution": "720p"})
    with pytest.raises(ValueError, match="Shot resolution must be one of"):
        _edited({"resolution": "4k"})


def _script(shot):
    return {"scenes": [{"id": "cold_open", "location": "garage"}], "shots": [{"scene": "cold_open", "duration": 5, **shot}]}


def test_the_script_sizes_a_video_shot_and_refuses_a_size_elsewhere():
    tools = Series()
    apply_script(tools, tools.read, KITS, FILES, "cast",
                 _script({"kind": "video", "resolution": "720", "video": {"prompt": "Ana waves once"}}))
    assert tools.calls[1][1]["episode"]["shots"][0]["resolution"] == "720p"
    tools = Series()
    apply_script(tools, tools.read, KITS, FILES, "cast", _script({"kind": "generated"}))
    assert tools.calls[1][1]["episode"]["shots"][0]["resolution"] is None, "a rewrite without it clears it"
    for shot, problem in (({"resolution": "720p"}, "resolution is only for kind video or generated"),
                          ({"kind": "video", "resolution": "4k"}, "resolution must be one of 480p, 540p, 720p, 768p")):
        tools = Series()
        with pytest.raises(ScriptError) as raised:
            apply_script(tools, tools.read, KITS, FILES, "cast", _script(shot))
        assert any(problem in item for item in raised.value.problems) and tools.calls == []


def test_series_shot_update_sets_a_size_clears_only_the_take_and_null_removes_it():
    series = library()
    episode = series["episodesById"]["ep2"]
    stored = next(item for item in episode["shots"] if item["id"] == "e2s03")
    episode["review"] = {"mode": "plan", "shots": {"e2s03": {"plan": "approved", "planDigest": content_digest(stored)}}}
    episode, shot, info, changed = edit(series, 4, changes={"resolution": "720p"})
    assert changed == ["resolution"] and shot["resolution"] == "720p"
    assert shot["attempts"][0]["id"] == "att-v" and "approvedAttemptId" not in shot
    assert info["reset"] == ["take"], "the plan still shows what it showed"
    assert episode["review"]["shots"]["e2s03"]["plan"] == "approved"
    series["episodesById"]["ep2"] = episode
    episode, shot, info, changed = edit(series, 4, changes={"resolution": None})
    assert changed == ["resolution"] and shot.get("resolution") is None
    series["episodesById"]["ep2"] = episode
    stored = normalize_series_project(series, series["id"], "cast")["episodesById"]["ep2"]["shots"]
    assert "resolution" not in next(item for item in stored if item["id"] == "e2s03"), "the write drops the empty size"
    with pytest.raises(ShotEditError) as raised:
        edit(library(), 2, changes={"resolution": "720p"})
    assert any("resolution is only for kind video or generated" in item for item in raised.value.problems)


def test_a_sized_video_shot_can_become_2d_and_a_size_alias_is_no_change():
    series = library()
    episode, _shot, _info, _changed = edit(series, 4, changes={"resolution": "720p"})
    series["episodesById"]["ep2"] = episode
    _episode, _shot, info, changed = edit(series, 4, changes={"resolution": "1280x704"})
    assert changed == [] and info["reset"] == [], "720p by another name is the same size"
    episode, shot, _info, changed = edit(series, 4, changes={"kind": "2d"})
    assert changed == ["kind", "resolution"] and shot["productionMethod"] == "animation_2d" and shot.get("resolution") is None
    with pytest.raises(ShotEditError) as raised:
        edit(series, 4, changes={"kind": "3d", "resolution": "720p"})
    assert any("resolution is only for kind video or generated" in item for item in raised.value.problems)
