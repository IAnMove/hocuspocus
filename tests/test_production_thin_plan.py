"""The quality gate says in plain words what is wrong, and ``allow_thin`` is the explicit way past the thin checks.

Checks 1–3 (one still in three or more shots, too much still runtime, a full-frame title over a moving shot) only make
the video look static: by default production.run refuses them, with ``allow_thin: true`` they come back as warnings.
Checks 4–5 (a clip a model will not have, a camera that does not exist) would fail after the GPU work and are always
refused. The dry run reports the same problems and the same warnings the run would.
"""
import asyncio
import json

import pytest
from fastapi import HTTPException

from services.music_production import command_catalog, command_handlers
from services.production_dry_run import dry_run
from services.production_quality_gate import LISTED_CLIPS, THIN_CODES, blocking_problems, refuse_thin_plan

SONG = {"lyrics": "[Verse]\nla luz se queda", "caption": "lullaby", "duration": 40, "bpm": 96}
MODELS = {"lia": {"prompt": "a girl", "rig": "humanoid", "animations": ["idle", "cheer"]}}


def still(key, t0, name="card-base", **extra):
    return {"key": key, "kind": "still", "still": name, "t0": t0, **extra}


def h3(key, t0, **extra):
    return {"key": key, "kind": "h3", "t0": t0, "frame": "a lighthouse", "action": "the beam sweeps", **extra}


def scene3d(key, t0, clip):
    return {"key": key, "kind": "scene3d", "t0": t0,
            "scene3d": {"template": "cine-medium-shot", "cast": {"subject_1": {"source": "lia", "clip": clip}}}}


def thin_spec():
    """Checks 1–3 only: the card in three shots, 70 % of the song on stills, a title card over an H3 clip."""
    shots = [still("v1", 0), h3("h1", 6), still("v2", 10), still("v3", 20),
             h3("h2", 32, title={"template": "title-card", "fields": {"title": "Faro"}})]
    return {"title": "Faro", "song": SONG, "style": {}, "shots": shots}


def broken_spec():
    """Checks 1–3 plus 4–5: Lia asked to wave, and a camera that does not exist."""
    spec = thin_spec()
    spec["models"] = MODELS
    spec["shots"] += [scene3d("d1", 36, "wave"), h3("h3", 38, camera="camera-orbit")]
    return spec


def by_code(problems):
    return {item["code"]: item for item in problems}


def test_each_check_says_which_shots_what_and_the_limit_in_plain_words():
    found = by_code(blocking_problems(broken_spec()))
    assert list(found) == ["still_reused", "too_static", "clip_not_baked", "unknown_camera", "title_card_hides_shot"]
    assert found["still_reused"]["message"].startswith(
        'Shots "v1", "v2" and "v3" all show the same still picture "card-base". Give each one its own picture')
    assert 'allow: ["still"]' in found["still_reused"]["message"]
    static = found["too_static"]
    assert static["shots"] == ["v1", "v2", "v3"]
    assert static["message"].startswith('Still pictures fill 70% of the song (28 s of 40 s, in shots "v1", "v2" and "v3"), '
                                        'and quality "standard" (the default) allows at most 35%.')
    assert found["title_card_hides_shot"]["message"].startswith(
        'A full-frame title hides the moving picture under it: "title-card" on shot "h2". Use a title that leaves the picture visible')
    assert found["clip_not_baked"]["message"].startswith(
        'Shot "d1" (subject_1) asks model "lia" for the clip "wave", but "lia" only has: idle, cheer. The 3D export would fail')
    assert found["unknown_camera"]["message"].startswith(
        'Shot "h3" asks for the camera "camera-orbit". That camera does not exist, so the scene edit would fail')
    assert "camera-push-in" in found["unknown_camera"]["message"]
    assert "would look thin" not in json.dumps(found)


def test_the_limit_named_is_the_one_the_spec_chose_and_long_clip_lists_are_cut():
    spec = {**thin_spec(), "quality": "max"}
    assert 'quality "max" allows at most 15%' in by_code(blocking_problems(spec))["too_static"]["message"]
    spec = {"song": SONG, "shots": [scene3d("d1", 0, "wave")],
            "models": {"lia": {"prompt": "a girl", "rig": "humanoid", "animations": [f"clip{i}" for i in range(20)]}}}
    message = by_code(blocking_problems(spec))["clip_not_baked"]["message"]
    assert f"clip{LISTED_CLIPS - 1} and {20 - LISTED_CLIPS} more." in message and f"clip{LISTED_CLIPS}," not in message
    spec["models"] = {"lia": {"prompt": "a ghost", "rig": "none"}}
    assert 'but "lia" has no clips.' in by_code(blocking_problems(spec))["clip_not_baked"]["message"]


def test_two_title_templates_are_named_with_their_shots_in_shot_order():
    shots = [h3("a", 0, title={"template": "trailer-slam", "fields": {"lines": "uno|dos"}}),
             h3("b", 10, title={"template": "title-card", "fields": {"title": "x"}}),
             h3("c", 20, title={"template": "trailer-slam", "fields": {"lines": "tres|cuatro"}})]
    problem = by_code(blocking_problems({"song": SONG, "shots": shots}))["title_card_hides_shot"]
    assert problem["shots"] == ["a", "b", "c"]
    assert problem["message"].startswith('Full-frame titles hide the moving picture under them: "trailer-slam" on shots "a" '
                                         'and "c"; "title-card" on shot "b".')


def test_by_default_the_thin_checks_still_refuse_and_the_message_offers_allow_thin():
    with pytest.raises(HTTPException) as refused:
        refuse_thin_plan(thin_spec(), None)
    detail = refused.value.detail
    assert refused.value.status_code == 422 and detail["code"] == "quality_gate" and detail["retryable"] is False
    assert [item["code"] for item in detail["problems"]] == list(THIN_CODES)
    lines = detail["message"].split("\n")
    assert lines[0] == "Nothing was started: fix the plan and send it again."
    assert "allow_thin: true" in lines[1]
    assert lines[2:] == [f"- {item['message']}" for item in detail["problems"]]


def test_allow_thin_turns_checks_one_to_three_into_warnings():
    allowed = refuse_thin_plan(thin_spec(), None, allow_thin=True)
    assert [item["code"] for item in allowed] == list(THIN_CODES)
    assert all(item["allowed_by"] == "allow_thin" and item["message"] for item in allowed)
    assert refuse_thin_plan(thin_spec(), thin_spec(), allow_thin=True) == [], "a resume is never checked"


def test_unknown_clips_and_cameras_refuse_even_with_allow_thin():
    with pytest.raises(HTTPException) as refused:
        refuse_thin_plan(broken_spec(), None, allow_thin=True)
    detail = refused.value.detail
    assert [item["code"] for item in detail["problems"]] == ["clip_not_baked", "unknown_camera"]
    assert "allow_thin does not skip them" in detail["message"]
    assert "look static" not in detail["message"], "the thin checks it let through are not in the refusal"


def _handlers(tmp_path, monkeypatch, started):
    class _Thread:
        def __init__(self, target, args, name, daemon):
            self.target = target

        def start(self):
            started.append(self.target)

        def is_alive(self):
            return False

    monkeypatch.setattr("services.music_production.threading.Thread", _Thread)
    monkeypatch.setattr("services.music_production.validate_spec", lambda spec: spec)
    monkeypatch.setattr("services.music_production.require_free_disk", lambda _root: None)
    return command_handlers(lambda _name: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1:9", lambda: "token")


def _run(handlers, spec, **flags):
    body = {"version": 1, "input": {"workspace": "w", "production_id": "faro", "spec": spec, **flags}}
    return asyncio.run(handlers["production.run"](body))


def test_production_run_needs_the_explicit_flag_and_then_returns_the_warnings(tmp_path, monkeypatch):
    started = []
    handlers = _handlers(tmp_path, monkeypatch, started)
    for flags in ({}, {"allow_thin": False}, {"allow_thin": "true"}):
        with pytest.raises(HTTPException) as refused:
            _run(handlers, thin_spec(), **flags)
        assert refused.value.detail["code"] == "quality_gate", flags
    assert started == []
    result = _run(handlers, thin_spec(), allow_thin=True)["result"]
    assert result["running"] is True and len(started) == 1
    assert [item["code"] for item in result["warnings"]] == list(THIN_CODES)
    with pytest.raises(HTTPException) as refused:
        _run(handlers, broken_spec(), allow_thin=True)
    assert [item["code"] for item in refused.value.detail["problems"]] == ["clip_not_baked", "unknown_camera"]
    assert len(started) == 1


def test_dry_run_reports_what_the_run_would_refuse_and_return(tmp_path, monkeypatch):
    handlers = _handlers(tmp_path, monkeypatch, [])
    for spec in (thin_spec(), broken_spec()):
        with pytest.raises(HTTPException) as refused:
            _run(handlers, spec)
        assert _run(handlers, spec, dry_run=True)["result"]["blocking"] == refused.value.detail["problems"]
    report = _run(handlers, thin_spec(), dry_run=True, allow_thin=True)["result"]
    ran = _run(handlers, thin_spec(), allow_thin=True)["result"]
    assert report["blocking"] == []
    assert [item for item in report["warnings"] if item.get("allowed_by") == "allow_thin"] == ran["warnings"]
    with pytest.raises(HTTPException) as refused:
        _run(handlers, broken_spec(), allow_thin=True)
    report = dry_run(broken_spec(), root=tmp_path, allow_thin=True)
    assert report["blocking"] == refused.value.detail["problems"]
    assert [item["code"] for item in report["warnings"] if item.get("allowed_by")] == list(THIN_CODES)


def test_the_mcp_schema_declares_the_flag_and_the_title_card_allowance():
    run = next(item for item in command_catalog() if item["name"] == "production.run")
    fields = run["inputSchema"]["properties"]["input"]["properties"]
    assert fields["allow_thin"]["type"] == "boolean" and "warnings" in fields["allow_thin"]["description"]
    assert "allow_thin" in run["description"]
    shot = fields["spec"]["properties"]["shots"]["anyOf"][1]["items"]["properties"]
    assert "title_card" in shot["allow"]["items"]["enum"]
