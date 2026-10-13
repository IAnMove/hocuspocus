"""Series 2D finish, camera moves and episode format: visible, and chosen per series and per shot.

The pinned digests were computed with the code before these choices existed (development bc518b86). A series and a
shot stored then keep every digest they had: the plan approval (``content_digest``), the take fingerprint
(``render_inputs``) and the shot spec here, and the compiled Video 2D document the native render hashes in
``test_series_shot_plan`` (it compiles with the UI's tsx, so it runs in the python-b shard). Nothing already made
is made again or reads as out of date, and every 2D shot keeps the paper finish.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from pathlib import Path

import pytest

from services.series_finish import _PARTS, PAPER, TEXTURES, check_finish, fingerprint, shot_finish, store_look
from services.series_library import normalize_series_project
from services.series_review import content_digest
from services.series_script import EpisodeScript, ScriptError
from services.series_shot_edit import ShotEditError
from services.series_shot_instruction import SYSTEM
from services.series_shot_plan import CAMERA_CONTINUES, CAMERA_POSES, CAMERAS, build_shot_spec, normalize_layout2d
from services.series_take_inputs import render_inputs
from services.video2d_preset_catalog import finish_presets
from tests.test_series_script_produce import FILES, KITS as SCRIPT_KITS, SCRIPT, project
from tests.test_series_shot_edit import edit, library

ROOT = Path(__file__).resolve().parents[1]
STATES = ["closed", "small", "wide", "round", "pressed", "medium", "pucker", "bite", "tongue"]


def _asset(aid, kind="overlay"):
    return {"id": aid, "name": aid, "source": f"/api/v1/file/{aid}.png?workspace=cast", "kind": kind, "alphaStatus": "transparent",
            "reviewState": "approved", **({"width": 300, "height": 600} if kind == "image" else {})}


def _kit(kid):
    return {"version": 1, "id": kid, "name": kid, "style": "cutout", "base": _asset(f"{kid}-base", "image"), "poses": {},
            "mouth": {state: _asset(f"{kid}-m-{state}") for state in STATES}, "eyes": {}, "provenance": [],
            "mouthMapping": {"rest": "closed", "M": "pressed", "A": "wide", "E": "medium", "I": "small", "O": "round", "U": "pucker",
                             "F": "bite", "L": "tongue"},
            "anchors": {"base": {"mouth": {"offsetX": 0, "offsetY": -10, "scale": 0.1, "rotation": 0}}}}


KITS = {"kit-kevin": _kit("kit-kevin"), "kit-gary": _kit("kit-gary")}
BEATS = [{"id": "b1", "characterId": "kevin", "text": "Hola."}]
RECORDED = {"b1": {"filename": "l1.wav", "duration": 1.2, "cues": [{"start": 0, "end": 0.6, "value": "D"}], "driver": "wav2vec2-phoneme"}}
PORTRAIT = {"provider": {"videoSettings": {"orientation": "portrait"}}}


def series(**extra):
    character = lambda cid: {"id": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}}
    value = {"id": "uv", "title": "Valle", "spokenLanguage": "Español de España", "characters": [character("kevin"), character("gary")],
             "locations": [{"id": "garage", "referenceAssetIds": ["asset_day"], "layout2d": {"homes": {"kevin": 30, "gary": 70}}},
                           {"id": "bar", "referenceAssetIds": ["asset_day"], "layout2d": {"layers": [
                               {"file": "fg-plant.png", "depth": 0.9, "front": True, "x": 8, "y": 62, "scale": 0.9}]}}],
             "assets": {"asset_day": {"kind": "image", "uri": "outputs/day.png"}},
             "soundDesign": {"stinger": {"file": "sting.wav", "volume": 0.7}}}
    value.update(extra)
    return value


def _shot(sid, order, **fields):
    return {"id": sid, "order": order, "sceneId": "a", "productionMethod": "animation_2d", "dialogueBeats": BEATS, **fields}


# A shot as each path stored it: the script (static, push), the planner's free words (one of the stored shots whose
# words name a pan and rendered static), a layered set and a title card.
SHOTS = {
    "static": _shot("s1", 1, locationId="garage", framing="two", camera="static", visibleCharacterIds=["kevin", "gary"],
                    layout2d={"framing": "two", "camera": "static"}),
    "push": _shot("s2", 2, locationId="garage", framing="close", camera="push", visibleCharacterIds=["kevin"],
                  layout2d={"framing": "close", "camera": "push"}),
    "words": _shot("s3", 3, locationId="garage", framing="Plano medio", camera="Cámara fija con paneo suave", visibleCharacterIds=["kevin"]),
    "layered": _shot("s4", 4, sceneId="b", locationId="bar", framing="wide", camera="slow push-in", visibleCharacterIds=["kevin", "gary"]),
    "card": _shot("s5", 5, durationSeconds=6, dialogueBeats=[], layout2d={"card": {"kind": "title", "title": "VALLE", "body": "1x01"}}),
}
# name: (render_inputs, content_digest, spec digest, compiled document digest, planned camera) at bc518b86.
OLD = {
    "static": ("240630d8fd4203e5", "01354e48a848b4e3", "6f9ebeca6b98a6f8", "6ef9b8070517fd1e", "static"),
    "push": ("bb4e0f9b8a22ae73", "95613184b1840b8b", "f8c3ffaba41f9185", "0094ed8c88af36b7", "push"),
    "push-portrait": ("bb4e0f9b8a22ae73", "95613184b1840b8b", "d73d379f78d3459d", "829fd9104e4e5351", "push"),
    "words": ("e46596d01f8f33e2", "3d711bc688dc3b14", "44e562e20edaf759", "ec4613ab74620b14", "static"),
    "layered": ("74295f2f0d841a8a", "fdd4c2a9b533af08", "5d74edfbdc48be2d", "65d0e913cc8cc07f", "push"),
    "card": ("fec57c2caf78f28a", "e92061d0571e8615", "efc74264af885c22", "cb77c674b30759d4", "static"),
}


def digest(value):
    return hashlib.sha1(json.dumps(value, sort_keys=True).encode()).hexdigest()[:16]


def stored_cases():
    for name, expected in OLD.items():
        shot_name, _, portrait = name.partition("-")
        yield name, series(**(PORTRAIT if portrait else {})), SHOTS[shot_name], expected


def planned_spec(value, shot):
    return build_shot_spec(value, {"id": "ep1", "title": "Piloto"}, shot, workspace="cast",
                           recorded=RECORDED if shot.get("dialogueBeats") else {}, first_of_scene=True)


@pytest.mark.parametrize("name", list(OLD))
def test_a_stored_shot_keeps_every_digest_and_its_paper_finish(name):
    _name, value, shot, (inputs, content, spec_digest, _document, camera) = next(case for case in stored_cases() if case[0] == name)
    assert render_inputs(value, shot, KITS) == inputs
    assert content_digest(shot) == content
    spec = planned_spec(value, shot)
    assert digest(spec) == spec_digest and spec["camera"] == camera and spec["finish"] == PAPER
    # Choosing paper by name is the same picture: nothing renders again.
    assert render_inputs(series(look={"finish": "paper"}, **(PORTRAIT if "portrait" in name else {})), shot, KITS) == inputs


def test_any_other_finish_is_a_new_picture_and_renders_again():
    shot = SHOTS["static"]
    old = OLD["static"][0]
    clean = series(look={"finish": "none"})
    assert "finish" not in planned_spec(clean, shot) and render_inputs(clean, shot, KITS) != old
    film = series(look={"finish": "film"})
    assert planned_spec(film, shot)["finish"] == finish_presets()["film"] and render_inputs(film, shot, KITS) not in (old, render_inputs(clean, shot, KITS))
    # A Video 2D finish comes without its letterbox: a vertical frame would be three quarters bars.
    cinema = {key: value for key, value in finish_presets()["warmCinema"].items() if key != "letterbox"}
    assert "letterbox" in finish_presets()["warmCinema"] and cinema
    for value in (series(look={"finish": "warmCinema"}), series(look={"finish": "warmCinema"}, **PORTRAIT)):
        assert planned_spec(value, shot)["finish"] == cinema
    own = {"grain": {"amount": 0.2}, "vignette": {"amount": 0.4, "softness": 0.5}}
    stored = check_finish(own)
    assert stored == {"grain": {"amount": 0.2, "size": 1.2}, "vignette": {"amount": 0.4, "softness": 0.5}}
    assert planned_spec(series(look={"finish": stored}), shot)["finish"] == {**stored, "applyToTexts": False}
    # The paper amounts written out by hand are the paper finish: the same digest.
    by_hand = check_finish({key: value for key, value in PAPER.items() if key != "applyToTexts"})
    assert render_inputs(series(look={"finish": by_hand}), shot, KITS) == old


def test_a_shot_finish_wins_over_the_series_and_null_follows_it_again():
    own = {**SHOTS["static"], "layout2d": normalize_layout2d({"framing": "two", "camera": "static", "finish": "none"})}
    assert own["layout2d"]["finish"] == "none"
    film = series(look={"finish": "film"})
    assert shot_finish(film, own) is None and "finish" not in planned_spec(film, own)
    assert render_inputs(film, own, KITS) == render_inputs(series(), own, KITS), "the shot's own finish ignores the series'"
    assert normalize_layout2d({"framing": "two", "finish": None}) == {"framing": "two"}
    paper_shot = {**SHOTS["static"], "layout2d": {"framing": "two", "camera": "static", "finish": "paper"}}
    assert shot_finish(film, paper_shot) == PAPER and fingerprint(film, paper_shot) is None


def test_only_2d_takes_see_the_series_finish():
    three = {"id": "s9", "productionMethod": "animation_3d", "dialogueBeats": [], "durationSeconds": 5,
             "layout2d": {"framing": "wide"}, "scene3d": {"template": "x", "cast": []}}
    assert render_inputs(series(look={"finish": "none"}), three, KITS) == render_inputs(series(), three, KITS)


@pytest.mark.parametrize("value", ["paper", "none", "film", "noir", {"texture": {"kind": "scratches", "amount": 0.3}},
                                   {"vignette": {"amount": 1}}])
def test_a_finish_is_paper_none_a_video2d_finish_or_own_amounts(value):
    stored = check_finish(value)
    if isinstance(value, str):
        assert stored == value
    else:
        assert {part: found["amount"] for part, found in stored.items()} == {part: given["amount"] for part, given in value.items()}
    assert normalize_layout2d({"finish": value})["finish"] == stored


@pytest.mark.parametrize("value, message", [
    ("Paper", "must be paper, none"), ("noire", "must be paper, none"), ({}, "must be paper"), (3, "must be paper"),
    ({"grade": {"contrast": 1}}, "must be paper"), ({"texture": {"kind": "wood", "amount": 0.1}}, "kind must be one of"),
    ({"grain": {"amount": 2}}, "amount must be a number from 0 to 1"), ({"grain": {"size": 1}}, "amount must be a number"),
    ({"vignette": {"amount": 0.2, "kind": "paper"}}, "must be an object with amount, softness"), ({"vignette": True}, "must be an object"),
])
def test_an_unknown_finish_is_refused_with_what_it_may_be(value, message):
    with pytest.raises(ValueError, match=message):
        check_finish(value)
    with pytest.raises(ValueError, match="layout2d.finish"):
        normalize_layout2d({"finish": value})


def test_the_catalog_never_takes_the_names_of_the_series_choices():
    assert not {"paper", "none", "custom"} & set(finish_presets())
    named = SYSTEM.split("finish (2d shots):", 1)[1].split("\n- ", 1)[0]
    for preset in ("film", "noir", "sepia", "oldDoc", "flashback", "warm", "cold", "vhs"):
        assert preset in named and preset in finish_presets(), preset


# Every Video 2D finish when the choice became visible. A series may name any of them in look.finish or a shot's
# layout2d.finish, and an unknown name is refused when the workspace's series library is read.
PRESETS_2026_10_13 = ("warmCinema", "oldDoc", "nightNeon", "paperComic", "risoPress", "natural", "teal_orange", "bleach",
                      "noir", "sepia", "flashback", "dream", "giallo", "cold", "warm", "vhs", "film")


def test_a_finish_a_series_may_name_stays_in_the_catalog():
    missing = set(PRESETS_2026_10_13) - set(finish_presets())
    assert not missing, (f"{sorted(missing)} left app/shared/finish_presets.json: a series that chose one could no longer "
                         "be read. Keep the id, or map it to another in series_finish.check_finish, before removing it.")


def test_own_amounts_take_the_video2d_ranges():
    ranges = json.loads((ROOT / "app" / "shared" / "finish_presets.json").read_text(encoding="utf-8"))["ranges"]
    assert list(TEXTURES) == ranges["texture"]["kinds"]
    for part, keys in _PARTS.items():
        assert {key: [low, high] for key, low, high, _default in keys} == {key: value for key, value in ranges[part].items()
                                                                          if key != "kinds"}, part


def test_the_python_camera_poses_are_the_compiler_s():
    """series_shot_plan.CAMERA_POSES, where a camera that goes on from the shot before starts, are the compiler's poses."""
    source = (ROOT / "ui" / "scripts" / "seriesShot.ts").read_text(encoding="utf-8")
    block = source.split("export const CAMERA_MOVES", 1)[1].split("\n}\n", 1)[0]
    pose = r"\{ x: ([\d.]+), y: ([\d.]+), scale: ([\d.]+) \}"
    found = {name: tuple(tuple(float(n) for n in match) for match in re.findall(pose, poses))
             for name, poses in re.findall(r"^\s*'?([a-z-]+)'?: \[(.*)\],?$", block, re.M)}
    assert found == {name: tuple(tuple(float(n) for n in end) for end in ends) for name, ends in CAMERA_POSES.items()}
    assert {"static", *CAMERA_POSES} == set(CAMERAS) and set(CAMERA_CONTINUES) <= set(CAMERAS)


def _stored(**fields):
    return {"id": "uv", "title": "Valle", "locations": [{"id": "garage"}], "episodesById": {}, **fields}


def test_a_stored_series_reads_back_without_new_fields():
    normalized = normalize_series_project(_stored(), "uv", "cast")
    assert "look" not in normalized and "episodeFormat" not in normalized
    for empty in ({"look": None, "episodeFormat": None}, {"look": {}, "episodeFormat": ""}, {"look": {"finish": None}, "episodeFormat": "  \n"}):
        cleared = normalize_series_project(_stored(**empty), "uv", "cast")
        assert "look" not in cleared and "episodeFormat" not in cleared, empty


def test_a_series_keeps_its_finish_and_episode_format_as_written():
    text = "Cold open, three acts and a tag: 2 minutes, 12 shots. "
    kept = normalize_series_project(_stored(look={"finish": "none", "palette": "ochre"}, episodeFormat=text), "uv", "cast")
    assert kept["look"] == {"finish": "none", "palette": "ochre"} and kept["episodeFormat"] == text
    own = normalize_series_project(_stored(look={"finish": {"grain": {"amount": 0.1, "size": 2}}}), "uv", "cast")
    assert own["look"]["finish"] == {"grain": {"amount": 0.1, "size": 2.0}}
    assert normalize_series_project(_stored(episodeFormat="x" * 2000), "uv", "cast")["episodeFormat"] == "x" * 2000
    for bad, message in (({"episodeFormat": "x" * 2001}, "at most 2000"), ({"episodeFormat": ["acts"]}, "must be text"),
                         ({"look": "noir"}, "look must be an object"), ({"look": {"finish": "sepia tone"}}, "look.finish must be")):
        with pytest.raises(ValueError, match=message):
            normalize_series_project(_stored(**bad), "uv", "cast")
    record = {"look": {"finish": "paper"}}
    store_look(record)
    assert record == {"look": {"finish": "paper"}}, "paper by name is kept: the user chose it"


def test_the_script_gives_a_2d_shot_its_finish_and_refuses_it_elsewhere():
    script = copy.deepcopy(SCRIPT)
    script["shots"][1]["finish"] = "oldDoc"
    built = EpisodeScript(project(), script, 2, SCRIPT_KITS, FILES)
    built.check()
    assert built.shots()[1]["layout2d"]["finish"] == "oldDoc" and "finish" not in built.shots()[0]["layout2d"]
    for where, finish, problem in ((2, "none", "finish is only for 2d shots"), (1, "sepia tone", "finish must be paper, none")):
        wrong = copy.deepcopy(SCRIPT)
        wrong["shots"][where]["finish"] = finish
        with pytest.raises(ScriptError) as error:
            EpisodeScript(project(), wrong, 2, SCRIPT_KITS, FILES).check()
        assert any(problem in item for item in error.value.problems), problem


def test_series_shot_update_sets_a_finish_and_null_follows_the_series_again():
    episode, shot, info, changed = edit(library(), 2, {"finish": "none"})
    assert changed == ["finish"] and shot["layout2d"]["finish"] == "none" and info["reset"] == ["take"]
    assert "approvedAttemptId" not in shot, "a new picture: the take renders again"
    series_value = library()
    series_value["episodesById"]["ep2"] = episode
    _episode, cleared, _info, changed = edit(series_value, 2, {"finish": None})
    assert changed == ["finish"] and "finish" not in cleared["layout2d"]
    with pytest.raises(ShotEditError, match="finish must be paper, none"):
        edit(library(), 2, {"finish": "sepia tone"})
