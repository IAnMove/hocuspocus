"""series.shot.card.apply: a Video 2D card on a Series shot, as a new take, in one operation (UI, MCP and Wizard share it).

The real compile (and the opt-in render smoke) run the UI builders through tsx, so they need ui/node_modules: this file sits in the CI shard that installs it.
"""
import asyncio
import base64
import copy
import io
import json
import os
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import functools
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.series_shot_card import create_series_shot_card_router
from routers.series_shot_edit import create_series_shot_edit_router
from services import series_shot_card_bind as bind
from services import video2d_compile
from services.series_library import approve_shot_render_attempt
from services.series_native_render import SeriesNativeRender
from services.series_shot_card import APPROVE_OFF, CardApplyError, CardDeps, SeriesShotCard

SHEET = "/api/v1/file/walk-sheet.png?workspace=cast"
BG = "/api/v1/file/assets/uv/bg.png?workspace=cast"
VOICE = {"provider": "local", "model": "qwen3_tts_customvoice", "voiceId": "ryan"}


def animation(state="approved", count=4, fps=4, facing="right", loop="loop"):
    return {"sheet": {"source": SHEET, "width": 100 * count, "height": 200, "count": count, "columns": count, "rows": 1,
                      "cell": {"width": 100, "height": 200}}, "frames": [], "fps": fps, "loop": loop, "facing": facing, "reviewState": state}


def kits(walk="approved", wave="pending"):
    picture = lambda name: {"source": f"/api/v1/file/{name}.png?workspace=cast", "width": 400, "height": 800}
    gloria = {"id": "kit-gloria", "name": "Gloria", "base": picture("gloria-base"), "poses": {"wave": picture("gloria-wave")}, "voice": VOICE,
              "animations": {"walk": animation(walk), "wave": animation(wave, count=2)}}
    kevin = {"id": "kit-kevin", "name": "Kevin", "base": picture("kevin-base"), "poses": {}, "voice": VOICE}
    return {"kit-gloria": gloria, "kit-kevin": kevin}


def library():
    character = lambda cid: {"id": cid, "name": cid, "voiceProfile": {"characterKitRef": {"id": f"kit-{cid}", "workspace": "cast"}}}
    shot = lambda sid, order, seconds, beats=(), cast=(), **extra: {
        "id": sid, "order": order, "sceneId": "scene_1", "productionMethod": "animation_2d", "locationId": "hall", "durationSeconds": seconds,
        "layout2d": {"framing": "wide", "cast": [{"characterId": who, "poseId": pose} for who, pose in cast]}, "attempts": [],
        "dialogueBeats": [{"id": f"{sid}_d{i}", "characterId": who, "text": text} for i, (who, text) in enumerate(beats)], **extra}
    episode = {"id": "ep1", "title": "Piloto", "shots": [
        shot("s01", 1, 5, cast=[("gloria", "base")]),
        shot("s02", 2, 3, beats=[("kevin", "Hola, Gloria.")], cast=[("gloria", "wave"), ("kevin", "base")]),
        shot("s03", 3, 20, cast=[("gloria", "base")]),
        shot("s04", 4, 4, cast=[("gloria", "base")], productionMethod="generated_video")]}
    series = {"id": "uv", "title": "Valle", "allowedProductionMethods": ["animation_2d", "generated_video"], "spokenLanguage": "Español de España", "characters": [character("gloria"), character("kevin")],
              "locations": [{"id": "hall", "referenceAssetIds": ["asset_bg"], "variants": []}],
              "assets": {"asset_bg": {"id": "asset_bg", "kind": "image", "uri": "assets/uv/bg.png"}}, "episodesById": {"ep1": episode}}
    return series


class World:
    """The series library, the server's tools and the services config the service reads: all in memory."""

    def __init__(self, tmp_path, autonomy="review", ready=True):
        self.root, self.series, self.kits = tmp_path, library(), kits()
        self.autonomy, self.ready, self.calls, self.compiled = autonomy, ready, [], []
        self.exports: dict[str, int] = {}
        self.attempts = 0

    def read_library(self, _workspace):
        return {"seriesById": {"uv": copy.deepcopy(self.series)}}

    def change_series(self, _workspace, _series_id, change):
        change(self.series)
        return self.series

    def shot(self, shot_id="s01"):
        return next(item for item in self.series["episodesById"]["ep1"]["shots"] if item["id"] == shot_id)

    def tools(self, tool, arguments):
        self.calls.append((tool, arguments))
        data = arguments.get("input") or {}
        if tool == "scenes.video2d.export":
            self.exports.setdefault(arguments["intent_id"], 0)
            return {"receipt": {"status": "queued"}}
        if tool == "scenes.video2d.export.receipt":
            intent = data["intent_id"]
            self.exports[intent] += 1
            if not self.ready:
                return {"result": {"receipt": {"artifacts": []}, "task": {"status": "running"}}}
            return {"result": {"receipt": {"artifacts": [{"name": f"{intent}.mp4"}]}, "task": {"status": "completed"}}}
        if tool == "series.asset.import":
            return self._import(data)
        raise AssertionError(tool)

    def _import(self, data):
        self.attempts += 1
        shot, asset_id = self.shot(data["owner_id"]), f"asset_{self.attempts}"
        attempt = {"id": f"attempt-{self.attempts}", "status": "completed", "outputAssetIds": [asset_id]}
        shot["attempts"].append(attempt)
        self.series["assets"][asset_id] = {"id": asset_id, "kind": "video", "uri": f"assets/uv/{asset_id}.mp4",
                                           "metadata": {"name": data["name"], **data["metadata"]}}
        return {"result": {"attempt": attempt, "asset": self.series["assets"][asset_id]}}

    def compile(self, command, workspace_dir):
        self.compiled.append(command)
        controls = command["input"]["controls"]
        document = {"version": 1, "name": "card", "width": command["input"]["width"], "height": command["input"]["height"], "fps": 24,
                    "duration": controls.get("duration", 6), "layers": [{"id": "background", "name": json.dumps(controls, sort_keys=True), "type": "image", "source": command["input"]["assets"]["background"]}]}
        return {"version": 1, "status": "completed", "operation": command["operation"], "result": {"document": document, "warnings": []}}

    def service(self, **overrides):
        deps = dict(read_library=self.read_library, read_kits=lambda _ws: copy.deepcopy(self.kits), workspace_dir=lambda _ws: str(self.root),
                    call=self.tools, change_series=self.change_series, services=lambda: {"agent_autonomy": self.autonomy}, compile=self.compile,
                    probe=lambda _path: 1.5, room=lambda _root, name, _preset: name, sleep=lambda _s: None, wait_seconds=0, poll_seconds=0)
        return SeriesShotCard(CardDeps(**{**deps, **overrides}))

    def apply(self, shot="s01", card="walk-cycle-sheet", **options):
        return self.service().apply("cast", "uv", "ep1", shot, card, **options)

    def tool_names(self):
        return [name for name, _ in self.calls]


WALK = [{"slot": "subject_1", "characterId": "gloria", "animation": "walk"}]


def refused(world, **options):
    with pytest.raises(CardApplyError) as error:
        world.apply(**options)
    return error.value


# Binding the card to the kit ---------------------------------------------------------------

def test_a_walk_card_plays_the_approved_walk_sheet_on_the_shot_plate_with_the_sheets_controls(tmp_path):
    world = World(tmp_path)
    reply = world.apply(cast=WALK)
    sent = world.compiled[0]["input"]
    assert sent["templateId"] == "walk-cycle-sheet" and sent["full"] is True and (sent["width"], sent["height"], sent["fps"]) == (1920, 1080, 24)
    assert sent["assets"] == {"subject_1": SHEET, "background": BG}
    assert sent["controls"] == {"frames": 4, "columns": 4, "facing": "right", "step": 0.5, "duration": 5.0}, "the card is as long as the shot"
    assert reply["bindings"] == [{"slot": "subject_1", "characterId": "gloria", "animation": "walk"}]


def test_without_a_cast_the_shots_own_people_fill_the_slots_and_a_walk_card_walks_by_default(tmp_path):
    world = World(tmp_path)
    reply = world.apply()
    assert world.compiled[0]["input"]["assets"]["subject_1"] == SHEET and reply["bindings"][0]["animation"] == "walk"


def test_a_card_that_draws_a_pose_gets_the_shots_pose_of_that_character_or_the_one_asked(tmp_path):
    world = World(tmp_path)
    list(record(world))
    world.apply(shot="s02", card="walk-toward-camera", cast=[{"characterId": "gloria"}])
    assert world.compiled[0]["input"]["assets"]["subject_1"] == "/api/v1/file/gloria-wave.png?workspace=cast", "the pose the shot gives her"
    world.apply(shot="s02", card="walk-toward-camera", cast=[{"characterId": "gloria", "poseId": "base"}], controls={"travel": 0.7})
    assert world.compiled[1]["input"]["assets"]["subject_1"] == "/api/v1/file/gloria-base.png?workspace=cast"
    assert world.compiled[1]["input"]["controls"]["travel"] == 0.7


def test_a_pending_or_rejected_sheet_is_refused_with_the_words_of_the_script_check(tmp_path):
    world = World(tmp_path)
    error = refused(world, card="character-reaction", cast=[{"slot": "subject_1", "characterId": "gloria", "animation": "wave"}])
    assert error.code == "animation_not_approved" and error.status == 409
    assert "animation 'wave' of 'gloria' is pending approval: approve it in Characters › Animaciones" in str(error)
    world.kits["kit-gloria"]["animations"]["wave"]["reviewState"] = "rejected"
    assert "was rejected: make it again in Characters › Animaciones" in str(refused(world, card="character-reaction", cast=[{"characterId": "gloria", "animation": "wave"}]))
    assert "is not in its Character Kit" in str(refused(world, card="character-reaction", cast=[{"characterId": "gloria", "animation": "dance"}]))
    assert world.compiled == [] and world.tool_names() == [], "nothing was compiled, saved or exported"


def test_a_reaction_names_its_animation_and_a_pose_card_plays_none(tmp_path):
    world = World(tmp_path)
    assert refused(world, card="character-reaction").code == "animation_required"
    assert refused(world, card="walk-toward-camera", cast=[{"characterId": "gloria", "animation": "walk"}]).code == "card_not_sheet"
    assert refused(world, cast=[{"characterId": "gloria", "poseId": "wave"}]).code == "card_plays_sheet"
    assert refused(world, card="walk-toward-camera", cast=[{"characterId": "gloria", "poseId": "dance"}]).code == "unknown_pose"
    assert refused(world, card="walk-toward-camera", cast=[{"characterId": "nobody"}]).code == "unknown_character"
    assert refused(world, cast=[{"slot": "subject_2", "characterId": "gloria"}]).code == "bad_slot"


def test_the_reaction_card_takes_its_fps_and_loop_from_the_sheet_and_the_callers_controls_win(tmp_path):
    world = World(tmp_path)
    world.kits["kit-gloria"]["animations"]["wave"]["reviewState"] = "approved"
    world.apply(card="character-reaction", cast=[{"characterId": "gloria", "animation": {"id": "wave"}}], controls={"loop": "loop"})
    assert world.compiled[0]["input"]["controls"] == {"frames": 2, "columns": 2, "fps": 4, "loop": "loop", "duration": 5.0}


def test_the_other_slots_come_from_assets_and_a_slot_nobody_fills_is_named(tmp_path):
    world = World(tmp_path)
    (tmp_path / "counter.png").write_bytes(b"png")
    error = refused(world, card="walk-behind-foreground", cast=[{"characterId": "gloria", "poseId": "base"}])
    assert error.code == "slot_missing" and "foreground" in str(error)
    world.apply(card="walk-behind-foreground", cast=[{"characterId": "gloria", "poseId": "base"}], assets={"foreground": "counter.png"})
    assert world.compiled[0]["input"]["assets"]["foreground"] == "/api/v1/file/counter.png?workspace=cast"
    assert refused(world, card="walk-behind-foreground", assets={"foreground": "missing.png"}).code == "bad_asset"
    assert refused(world, card="walk-behind-foreground", assets={"hat": "counter.png"}).code == "bad_slot"
    world.series["locations"][0]["referenceAssetIds"] = []
    assert "the shot's location has no plate" in str(refused(world, cast=WALK))


def test_an_unknown_card_shot_or_a_non_2d_shot_is_refused_before_any_work(tmp_path):
    world = World(tmp_path)
    assert refused(world, card="walk-nowhere").code == "template_unknown"
    error = refused(world, shot="e9s99")
    assert error.code == "shot_not_found" and error.status == 404
    assert refused(world, shot=77).code == "shot_not_found"
    assert refused(world, shot="s04").code == "shot_not_2d"
    assert world.tool_names() == [] and world.compiled == []


def test_a_shot_longer_than_the_card_is_refused_and_a_shorter_one_sets_the_cards_length(tmp_path):
    world = World(tmp_path)
    error = refused(world, shot="s03", cast=WALK)
    assert error.code == "card_shorter_than_shot" and "at most 12 s" in str(error)
    world.shot("s01")["durationSeconds"] = 1.5
    world.apply(cast=WALK)
    assert world.compiled[0]["input"]["controls"]["duration"] == 3.0, "never shorter than the card's minimum"


# The scene and the take ---------------------------------------------------------------------

def test_the_scene_is_saved_under_a_stable_name_and_attached_as_a_new_take(tmp_path):
    world = World(tmp_path)
    reply = world.apply(cast=WALK)
    name = "uv-ep1-s01-card-walk-cycle-sheet.scene.json"
    assert reply["status"] == "completed" and reply["scene"] == name and reply["sceneUrl"] == f"/api/v1/file/{name}?workspace=cast"
    saved = json.loads((tmp_path / name).read_text(encoding="utf-8"))
    assert saved["layers"][0]["source"] == BG and saved["duration"] == 5.0 and saved["name"].endswith("s01 · walk-cycle-sheet")
    assert world.tool_names() == ["scenes.video2d.export", "scenes.video2d.export.receipt", "series.asset.import"]
    exported = world.calls[0][1]
    assert exported["input"]["document"]["duration"] == 5.0 and exported["input"]["workspace"] == "cast"
    imported = world.calls[2][1]["input"]
    assert (imported["owner_type"], imported["owner_id"], imported["kind"], imported["as_take"]) == ("shot", "s01", "video", True)
    assert imported["file"].endswith(".mp4") and imported["name"] == "s01-card-walk-cycle-sheet"
    meta = imported["metadata"]
    assert meta["productionMethod"] == "animation_2d" and meta["sceneFilename"] == name and meta["cardId"] == "walk-cycle-sheet"
    assert meta["language"] == "spanish" and isinstance(meta["renderInputs"], str) and meta["renderInputsVersion"] == 4
    assert reply["take"] == {"attemptId": "attempt-1", "assetId": "asset_1", "reused": False, "superseded": [], "approved": False}
    shot = world.shot()
    assert shot["durationSeconds"] == 5.0 and len(shot["attempts"]) == 1 and not shot.get("approvedAttemptId"), "a candidate, not approved"


def test_the_take_keeps_the_shots_render_inputs_so_producing_does_not_render_it_again(tmp_path):
    from services.series_take_inputs import stale_shot_ids
    world = World(tmp_path)
    world.apply(cast=WALK)
    shot = world.shot()
    shot["approvedAttemptId"] = shot["attempts"][0]["id"]
    series = copy.deepcopy(world.series)
    assert "s01" not in stale_shot_ids(series, series["episodesById"]["ep1"], world.kits, str(tmp_path)), "its digest is the shot's own"
    shot["layout2d"]["framing"] = "close"
    assert "s01" in stale_shot_ids(world.series, world.series["episodesById"]["ep1"], world.kits, str(tmp_path)), "an edit of the shot makes it stale"


# Approval -----------------------------------------------------------------------------------

def test_approve_is_refused_in_review_mode_before_any_work(tmp_path):
    world = World(tmp_path)
    error = refused(world, cast=WALK, approve=True)
    assert (error.code, error.status) == ("agent_review_off", 403) and str(error) == APPROVE_OFF
    assert "Apruébala en Series Lab" in APPROVE_OFF and world.tool_names() == [] and world.compiled == []
    assert not world.shot()["attempts"]


def test_approve_in_one_shot_mode_approves_the_take_as_the_agent(tmp_path):
    world = World(tmp_path, autonomy="one_shot")
    reply = world.apply(cast=WALK, approve=True)
    assert reply["take"]["approved"] is True and "series.take.approve" not in world.tool_names(), "stamped by the agent, not as the server's own job"
    assert world.shot()["approvedAttemptId"] == "attempt-1" and world.shot()["attempts"][0]["approvedBy"] == "agent"
    wizard = World(tmp_path, autonomy="one_shot")
    wizard.service(actor=lambda: "wizard").apply("cast", "uv", "ep1", "s01", "walk-cycle-sheet", cast=WALK, approve=True)
    assert wizard.shot()["attempts"][0]["approvedBy"] == "wizard"


def test_a_take_a_person_approved_is_never_replaced_and_an_agents_can_be(tmp_path):
    world = World(tmp_path, autonomy="one_shot")
    world.apply(cast=WALK)
    shot = world.shot()
    shot.update(approve_shot_render_attempt(shot, "attempt-1", "user"))
    reply = world.apply(cast=WALK, controls={"step": 0.7}, approve=True)
    assert reply["take"]["approved"] is False and "A person approved another take" in reply["approvalNote"]
    assert world.shot()["approvedAttemptId"] == "attempt-1" and "series.take.approve" not in world.tool_names()
    world.shot()["attempts"][0]["approvedBy"] = "agent"
    assert world.apply(cast=WALK, controls={"step": 0.8}, approve=True)["take"]["approved"] is True
    assert world.shot()["approvedAttemptId"] == "attempt-3"


# Applying twice and the export that is not ready ----------------------------------------------

def test_applying_the_same_card_again_does_nothing_twice_and_other_inputs_replace_the_earlier_candidate(tmp_path):
    world = World(tmp_path)
    first = world.apply(cast=WALK)
    again = world.apply(cast=WALK)
    assert again["take"]["attemptId"] == first["take"]["attemptId"] and again["take"]["reused"] is True
    assert world.tool_names().count("series.asset.import") == 1 and len(world.shot()["attempts"]) == 1
    changed = world.apply(cast=WALK, controls={"step": 0.9})
    assert changed["scene"] == first["scene"], "the same scene file, replaced"
    assert changed["take"]["attemptId"] == "attempt-2" and changed["take"]["superseded"] == ["attempt-1"]
    attempts = {item["id"]: item.get("reviewDecision") for item in world.shot()["attempts"]}
    assert attempts == {"attempt-1": "rejected", "attempt-2": None}
    assert json.loads((tmp_path / first["scene"]).read_text(encoding="utf-8"))["layers"], "one scene file for the shot and the card"
    assert [path.name for path in tmp_path.glob("*.scene.json")] == [first["scene"]]


def test_an_approved_card_take_is_not_superseded(tmp_path):
    world = World(tmp_path, autonomy="one_shot")
    world.apply(cast=WALK, approve=True)
    reply = world.apply(cast=WALK, controls={"step": 0.9})
    assert reply["take"]["superseded"] == [] and world.shot()["approvedAttemptId"] == "attempt-1"


def test_an_export_that_is_not_ready_answers_exporting_and_the_same_call_finishes_it(tmp_path):
    world = World(tmp_path, ready=False)
    waiting = world.apply(cast=WALK)
    assert waiting["status"] == "exporting" and waiting["exportIntent"].startswith("card-s01-") and "again" in waiting["message"]
    assert "take" not in waiting and not world.shot()["attempts"] and (tmp_path / waiting["scene"]).is_file(), "the scene is saved and editable already"
    world.ready = True
    done = world.apply(cast=WALK)
    assert done["status"] == "completed" and done["take"]["attemptId"] == "attempt-1"
    assert {call[1]["intent_id"] for call in world.calls if call[0] == "scenes.video2d.export"} == {waiting["exportIntent"]}, "one export, found again"


def test_an_export_the_server_lost_is_asked_for_again_under_a_new_intent(tmp_path):
    world = World(tmp_path)
    tools = world.tools
    lost = {"done": False}

    def flaky(tool, arguments):
        if tool == "scenes.video2d.export.receipt" and not lost["done"]:
            lost["done"] = True
            return {"result": {"receipt": {"artifacts": []}, "task": {"status": "interrupted"}}}
        return tools(tool, arguments)
    reply = world.service(call=flaky).apply("cast", "uv", "ep1", "s01", "walk-cycle-sheet", cast=WALK)
    intents = [call[1]["intent_id"] for call in world.calls if call[0] == "scenes.video2d.export"]
    assert reply["status"] == "completed" and len(intents) == 2 and intents[1] == f"{intents[0]}-r1"


def test_a_failed_export_is_an_error_with_the_exporters_words(tmp_path):
    world = World(tmp_path)
    tools = world.tools
    failing = lambda tool, args: ({"result": {"receipt": {"artifacts": []}, "task": {"status": "failed", "error": "browser crashed"}}}
                                  if tool == "scenes.video2d.export.receipt" else tools(tool, args))
    with pytest.raises(CardApplyError, match="browser crashed") as error:
        world.service(call=failing).apply("cast", "uv", "ep1", "s01", "walk-cycle-sheet", cast=WALK)
    assert error.value.code == "export_failed" and not world.shot()["attempts"]


# Dialogue -------------------------------------------------------------------------------------

def record(world, shot_id="s02", language="spanish"):
    """The recording the shot's render would reuse for each of its lines."""
    series, episode, shot = world.series, world.series["episodesById"]["ep1"], world.shot(shot_id)
    for beat in shot["dialogueBeats"]:
        _text, _voice, key = SeriesNativeRender.line_voice(series, beat, world.kits, language)
        name = f"{SeriesNativeRender.recording_stem(episode['id'], beat['id'], key)}.wav"
        (world.root / name).write_bytes(b"speech")
        yield name


def test_a_shot_with_lines_needs_them_recorded_and_the_card_carries_their_speech_and_subtitles(tmp_path):
    world = World(tmp_path)
    error = refused(world, shot="s02", cast=[{"characterId": "gloria"}], card="walk-toward-camera")
    assert error.code == "lines_not_recorded" and "series.shot.voice" in str(error) and world.compiled == []
    (name,) = record(world)
    reply = world.apply(shot="s02", card="walk-toward-camera", cast=[{"characterId": "gloria"}])
    document = json.loads((tmp_path / reply["scene"]).read_text(encoding="utf-8"))
    assert document["audioTracks"] == [{"id": "ep1-s02_d0", "filename": name, "name": "kevin", "kind": "speech", "startTime": 0.35, "volume": 1,
                                        "prompt": "Hola, Gloria."}]
    assert document["dialogueBeats"] == [{"id": "ep1-s02_d0", "text": "Hola, Gloria.", "start": 0.35, "end": 1.85, "audioTrackId": "ep1-s02_d0",
                                          "mouthLayerIds": [], "confidence": "known-text"}]
    assert document["audioMix"] == {"duckDb": 10} and document["duration"] == 3.0, "1.5 s of speech between the intro and the tail, in the shot's 3 s"
    from services.episode_finishing import scene_beats
    from services.series_assembly import episode_assembly_plan
    shot = world.shot("s02")
    shot["approvedAttemptId"] = shot["attempts"][0]["id"]
    world.series["episodesById"]["ep1"]["shots"] = [shot]
    (item,) = episode_assembly_plan(world.series, world.series["episodesById"]["ep1"])
    assert item["sceneFilename"] == reply["scene"] and "dialogueBeats" not in item, "the assembly plan points at the scene, which holds the timing"
    assert [beat["text"] for beat in scene_beats(str(tmp_path), item["sceneFilename"])] == ["Hola, Gloria."], "the cut's subtitles read the scene"


def test_the_card_lasts_as_long_as_the_lines_need_and_never_less(tmp_path):
    world = World(tmp_path)
    list(record(world))
    world.shot("s02")["durationSeconds"] = 1
    world.apply(shot="s02", card="walk-toward-camera", cast=[{"characterId": "gloria"}])
    assert world.compiled[0]["input"]["controls"]["duration"] == 3.0, "intro, 1.5 s of speech and the tail: 2.3 s, held to the card's 3 s"
    longer = world.service(probe=lambda _path: 4.0)
    reply = longer.apply("cast", "uv", "ep1", "s02", "walk-toward-camera", cast=[{"characterId": "gloria"}])
    assert reply["duration"] == 4.792, "0.35 s + 4 s of speech + 0.45 s, on a frame"
    with pytest.raises(CardApplyError) as error:
        longer.apply("cast", "uv", "ep1", "s02", "walk-toward-camera", cast=[{"characterId": "gloria"}], controls={"duration": 4})
    assert error.value.code == "card_shorter_than_lines"
    assert "4.79" in str(error.value)


def test_a_language_version_uses_its_own_scene_voices_and_approval(tmp_path):
    world = World(tmp_path, autonomy="one_shot")
    world.series["episodesById"]["ep1"]["languageVersions"] = {"english": {"title": "Pilot", "dialogue": {"s02_d0": "Hi, Gloria."}, "cards": {}, "approvedAttemptIds": {},
                                                                           "durations": {"s01": 5.0, "s02": 3.0}}}
    reply = world.apply(language="english", cast=WALK, approve=True)
    assert reply["scene"] == "uv-ep1-s01-card-walk-cycle-sheet-english.scene.json"
    meta = world.series["assets"]["asset_1"]["metadata"]
    assert meta["language"] == "english"
    version = world.series["episodesById"]["ep1"]["languageVersions"]["english"]
    assert version["approvedAttemptIds"] == {"s01": "attempt-1"} and version["durations"]["s01"] == 5.0, "the version's own approval and length"
    assert not world.shot().get("approvedAttemptId") and world.shot()["attempts"][0]["approvedBy"] == "agent"
    assert refused(world, language="klingon", cast=WALK).code == "invalid_language"


def test_a_language_versions_own_approval_survives_a_second_apply_and_each_language_has_its_own_take(tmp_path):
    world = World(tmp_path, autonomy="one_shot")
    world.series["episodesById"]["ep1"]["languageVersions"] = {"english": {"title": "Pilot", "dialogue": {"s02_d0": "Hi, Gloria."}, "cards": {}, "approvedAttemptIds": {},
                                                                           "durations": {"s01": 5.0, "s02": 3.0}}}
    spanish = world.apply(cast=WALK)
    english = world.apply(language="english", cast=WALK)
    assert english["take"]["attemptId"] != spanish["take"]["attemptId"] and english["scene"] != spanish["scene"], "the language is part of the take's identity"
    assert len(world.shot()["attempts"]) == 2
    version = world.series["episodesById"]["ep1"]["languageVersions"]["english"]
    from services.series_language_versions import set_version_take
    set_version_take(world.series["episodesById"]["ep1"], "english", "s01", english["take"]["attemptId"], "user")
    again = world.apply(language="english", cast=WALK, controls={"step": 0.9}, approve=True)
    assert again["take"]["superseded"] == [] and again["take"]["approved"] is False and "A person approved another take" in again["approvalNote"]
    decisions = {item["id"]: item.get("reviewDecision") for item in world.shot()["attempts"]}
    assert decisions[english["take"]["attemptId"]] is None, "the take a person approved in English is not rejected"
    assert version["approvedAttemptIds"] == {"s01": english["take"]["attemptId"]} and decisions[spanish["take"]["attemptId"]] is None


def test_a_person_approved_original_take_survives_a_language_version_reapply(tmp_path):
    """Series Lab's Approve stamps shot.approvedAttemptId even when the take came from a version apply.
    A later English apply with other controls must not reject that take: reject_shot_render_attempt would
    clear the original approval and the episode would lose the take the person kept."""
    world = World(tmp_path)
    world.series["episodesById"]["ep1"]["languageVersions"] = {"english": {"title": "Pilot", "dialogue": {}, "cards": {}, "approvedAttemptIds": {},
                                                                           "durations": {"s01": 5.0, "s02": 3.0}}}
    english = world.apply(language="english", cast=WALK)
    shot = world.shot()
    shot.update(approve_shot_render_attempt(shot, english["take"]["attemptId"], "user"))
    assert world.shot()["approvedAttemptId"] == english["take"]["attemptId"]
    again = world.apply(language="english", cast=WALK, controls={"step": 0.9})
    assert again["take"]["superseded"] == []
    assert world.shot()["approvedAttemptId"] == english["take"]["attemptId"]
    decisions = {item["id"]: item.get("reviewDecision") for item in world.shot()["attempts"]}
    assert decisions[english["take"]["attemptId"]] == "approved"


# One operation, three doors ---------------------------------------------------------------------

def test_the_route_the_mcp_tool_and_the_wizard_post_to_runs_this_operation(tmp_path):
    world = World(tmp_path, autonomy="one_shot")
    app = FastAPI()
    app.include_router(create_series_shot_card_router(world.service(), lambda loop: None))
    client = TestClient(app)
    body = {"workspace": "cast", "card": "walk-cycle-sheet", "cast": [{"slot": "subject_1", "characterId": "gloria", "animation": "walk"}], "approve": True}
    reply = client.post("/api/v1/series/uv/episodes/ep1/shots/1/card", json=body)
    assert reply.status_code == 200 and reply.json()["take"]["approved"] is True and reply.json()["shotId"] == "s01", "a number names the shot"
    refused_reply = client.post("/api/v1/series/uv/episodes/ep1/shots/nine/card", json={"workspace": "cast", "card": "walk-cycle-sheet"})
    assert refused_reply.status_code == 404 and refused_reply.json()["detail"]["code"] == "shot_not_found"
    assert client.post("/api/v1/series/uv/episodes/ep1/shots/1/card", json={**body, "colour": "red"}).status_code == 422, "no unknown fields"


def test_review_mode_answers_403_with_the_way_to_approve_by_hand(tmp_path):
    world = World(tmp_path)
    app = FastAPI()
    app.include_router(create_series_shot_card_router(world.service(), lambda loop: None))
    reply = TestClient(app).post("/api/v1/series/uv/episodes/ep1/shots/s01/card", json={"workspace": "cast", "card": "walk-cycle-sheet", "approve": True})
    assert reply.status_code == 403 and reply.json()["detail"] == {"code": "agent_review_off", "message": APPROVE_OFF}


def test_the_shot_edit_router_mounts_the_card_route_when_it_can_read_the_autonomy():
    def mounted(**extra):
        app = FastAPI()
        app.include_router(create_series_shot_edit_router(
            change_series=lambda *_a: {}, read_library=lambda _w: {}, read_kits=lambda _w: {}, workspace_dir=lambda w: w, call=lambda *_a: {},
            bind_loop=lambda _loop: None, **extra))
        return set(app.openapi()["paths"])
    card = "/api/v1/series/{series_id}/episodes/{episode_id}/shots/{shot}/card"
    assert card not in mounted() and card in mounted(services=lambda: {})


def test_the_mcp_tool_posts_the_same_body_as_the_wizard():
    from services.series_card_commands import OPERATIONS, RUNNERS
    seen = []
    request = lambda method, path, body=None, query=None: seen.append((method, path, body)) or {"status": "completed"}
    RUNNERS["series.shot.card.apply"](
        {"workspace": "w", "series_id": "uv", "episode_id": "ep1", "shot": 3, "card": "walk-cycle-sheet", "cast": WALK, "approve": False}, request)
    assert seen == [("POST", "/api/v1/series/uv/episodes/ep1/shots/3/card",
                     {"workspace": "w", "card": "walk-cycle-sheet", "cast": WALK, "approve": False})]
    properties, required, mutation, description = OPERATIONS["series.shot.card.apply"]
    assert mutation is True and required == ["workspace", "series_id", "episode_id", "shot", "card"]
    assert "Example" in description and "agent_autonomy" in description and len(description) < 2600
    from services.mcp_profiles import SERIES_TOOLS
    from services.series_commands import OPERATIONS as ALL
    assert "series.shot.card.apply" in SERIES_TOOLS and "series.shot.card.apply" in ALL


# The real compiler --------------------------------------------------------------------------------

def _sheet_png():
    """Four cells of colour blocks with alpha: a synthetic walk sheet."""
    from PIL import Image, ImageDraw
    image = Image.new("RGBA", (400, 200), (0, 0, 0, 0))
    pen = ImageDraw.Draw(image)
    for cell in range(4):
        pen.rectangle((cell * 100 + 10, 20, cell * 100 + 90, 192), fill=(220, 40 + 60 * cell, 40, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    return "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()


def real_world(tmp_path):
    world = World(tmp_path)
    world.kits["kit-gloria"]["animations"]["walk"]["sheet"]["source"] = _sheet_png()
    world.series["assets"]["asset_bg"]["uri"] = "bg.png"
    (tmp_path / "bg.png").write_bytes(b"not read by the compiler")
    return world


@pytest.mark.skipif(not video2d_compile.TSX.is_file(), reason="the UI builders run through tsx (ui/node_modules)")
def test_a_real_cpu_compile_of_a_walk_card_with_a_synthetic_sheet_makes_a_valid_scene_with_the_sheet_and_the_speech(tmp_path):
    from services.scene2d_export import validated_document
    world = real_world(tmp_path)
    (name,) = record(world)
    service = world.service(compile=video2d_compile.execute)
    reply = service.apply("cast", "uv", "ep1", "s02", "walk-cycle-sheet", cast=WALK)
    document = json.loads((tmp_path / reply["scene"]).read_text(encoding="utf-8"))
    sheet = next(layer for layer in document["layers"] if (layer.get("sequence") or {}).get("kind") == "sheet")
    assert sheet["sequence"]["source"].startswith("data:image/png") and (sheet["sequence"]["count"], sheet["sequence"]["columns"]) == (4, 4)
    assert (document["width"], document["height"], document["fps"], document["duration"]) == (1920, 1080, 24, 3.0)
    assert document["dialogueBeats"][0]["text"] == "Hola, Gloria." and document["audioTracks"][0]["filename"] == name
    checked = validated_document(document)
    assert checked["layers"] and checked["dialogueBeats"] and checked["audioTracks"], "the exporter accepts the scene with its speech"
    again = service.apply("cast", "uv", "ep1", "s02", "walk-cycle-sheet", cast=WALK)
    assert again["take"]["reused"] is True, "the compile is deterministic, so a second apply finds the first one's take"
    with pytest.raises(CardApplyError) as error:
        service.apply("cast", "uv", "ep1", "s02", "walk-cycle-sheet", cast=WALK, controls={"duration": 99})
    assert error.value.code == "template_bad_control"


@pytest.mark.skipif(os.environ.get("RUN_SERIES_SHEET_RENDER_SMOKE") != "1", reason="explicit built-UI Chromium smoke (ui/dist, Node, Playwright Chromium)")
def test_a_card_scene_renders_its_walker_in_a_real_cpu_export(tmp_path, monkeypatch):
    """RUN_SERIES_SHEET_RENDER_SMOKE=1 pytest -q tests/test_series_shot_card.py -k real_cpu_export (needs ``vite build`` in ui/)."""
    from PIL import Image
    from services.scene2d_export import validated_document
    from services.world3d_export import export_plan, playwright_module, run_owned_browser
    monkeypatch.setenv("HOCUS_SCENE_RENDER_DEVICE", "cpu")
    dist = Path(__file__).resolve().parents[1] / "ui" / "dist"
    assert (dist / "scene2d-render.html").is_file(), "Build the UI first (cd ui && npx vite build)"
    world = real_world(tmp_path)
    world.shot("s01")["durationSeconds"] = 3
    out = io.BytesIO()
    Image.new("RGB", (64, 36), (90, 90, 90)).save(out, format="PNG")
    plate = "data:image/png;base64," + base64.b64encode(out.getvalue()).decode()  # inline media: the smoke serves only ui/dist
    reply = world.service(compile=video2d_compile.execute).apply("cast", "uv", "ep1", "s01", "walk-cycle-sheet", cast=WALK, assets={"background": plate})
    document = validated_document(json.loads((tmp_path / reply["scene"]).read_text(encoding="utf-8")))
    times = [0.4, 1.4, 2.6]
    handler = functools.partial(type("Quiet", (SimpleHTTPRequestHandler,), {"log_message": lambda *_args: None}), directory=str(dist))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        module = playwright_module()
        assert module is not None, "Playwright is not installed"
        snapshot = {"document": document, "plan": {**export_plan(document), "times": times}, "workspace": "cast", "refs": []}
        (tmp_path / "snapshot.json").write_text(json.dumps(snapshot), encoding="utf-8")
        frames = run_owned_browser(snapshot, tmp_path, lambda: False, app_url=f"http://127.0.0.1:{server.server_port}", module=module,
                                   page="/scene2d-render.html", bridge="__scene2dExport")
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)
    assert len(frames) == len(times) and len({frame.read_bytes() for frame in frames}) == len(times), "the walker moves: three different pictures"


def test_a_reaction_card_over_its_own_voice_warns_and_a_listeners_does_not(tmp_path):
    """A card plays its sheet from the first second and cannot be moved, so the card says the character speaks over its own face."""
    world = World(tmp_path)
    world.kits["kit-kevin"]["animations"] = {"angry": animation(count=4, loop="once")}
    world.kits["kit-gloria"]["animations"]["angry"] = animation(count=4, loop="once")
    list(record(world))
    own = world.apply(shot="s02", card="character-reaction", cast=[{"characterId": "kevin", "animation": "angry"}])
    assert [text for text in own["warnings"] if text.startswith("expression_during_speech")] == [
        "expression_during_speech: kevin speaks while its 'angry' expression plays; a card plays its sheet from the start of the shot and "
        "cannot be moved: use the shot's own cast animation (at, duration) or apply the card to a shot where kevin is silent"]
    listening = world.apply(shot="s02", card="character-reaction", cast=[{"characterId": "gloria", "animation": "angry"}])
    assert not any(text.startswith("expression_during_speech") for text in listening["warnings"])
    cycle = world.apply(shot="s02", card="walk-cycle-sheet", cast=[{"characterId": "gloria", "animation": "walk"}])
    assert not any(text.startswith("expression_during_speech") for text in cycle["warnings"]), "a cycle is not an expression"
