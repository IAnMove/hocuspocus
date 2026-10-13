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

from services.music_production import command_catalog, command_handlers, status_summary
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


def test_a_shot_without_a_key_is_named_by_its_place_and_a_missing_quality_is_the_default_bar():
    """Only the dry run sees a keyless shot (production.run refuses it first); "None" names nothing."""
    shots = [{"kind": "still", "still": "card-base", "t0": t0} for t0 in (0, 10, 20)] + [h3("h1", 30)]
    for quality in ({}, {"quality": None}, {"quality": "best"}):
        found = by_code(blocking_problems({"song": SONG, "shots": shots, **quality}))
        assert found["still_reused"]["shots"] == found["too_static"]["shots"] == ["shots[0]", "shots[1]", "shots[2]"]
        assert 'quality "standard" (the default) allows at most 35%' in found["too_static"]["message"], quality
        assert "None" not in json.dumps(found)


def test_by_default_the_thin_checks_still_refuse_and_the_message_offers_allow_thin():
    with pytest.raises(HTTPException) as refused:
        refuse_thin_plan(thin_spec(), None)
    detail = refused.value.detail
    assert refused.value.status_code == 422 and detail["code"] == "quality_gate" and detail["retryable"] is False
    assert [item["code"] for item in detail["problems"]] == list(THIN_CODES)
    lines = detail["message"].split("\n")
    assert lines[0] == "Nothing was started: fix the plan and send it again."
    assert "allow_thin: true next to spec (not inside it)" in lines[1]
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
    for spec, flags in ((thin_spec(), {}), (thin_spec(), {"allow_thin": False}), (thin_spec(), {"allow_thin": "true"}),
                        (thin_spec(), {"allow_thin": 1}), ({**thin_spec(), "allow_thin": True}, {})):
        with pytest.raises(HTTPException) as refused:
            _run(handlers, spec, **flags)
        assert refused.value.detail["code"] == "quality_gate", (flags, "allow_thin" in spec)
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


def test_with_allow_thin_the_dry_run_names_each_static_problem_once():
    """The dry run's lighter still_reused / too_static give way to the gate's, which name the shots."""
    spec = thin_spec()
    spec["shots"] += [still(f"x{index}", 34 + index, "deliberate", allow=["still"]) for index in range(3)]
    plain = [item["code"] for item in dry_run(spec)["warnings"]]
    assert plain.count("still_reused") == 2 and plain.count("too_static") == 1, "without the flag nothing changes"
    warnings = dry_run(spec, allow_thin=True)["warnings"]
    codes = [item["code"] for item in warnings]
    assert codes.count("too_static") == 1 and codes.count("still_reused") == 2
    reused = {item["still"]: item for item in warnings if item["code"] == "still_reused"}
    assert reused["card-base"]["allowed_by"] == "allow_thin" and reused["card-base"]["shots"] == ["v1", "v2", "v3"]
    assert reused["deliberate"] == {"code": "still_reused", "still": "deliberate", "shots": 3}, "the gate skips it, the warning stays"


def _status(path):
    """What production.status answers for that file (its handler runs this in a thread the fake Thread replaces)."""
    return status_summary(json.loads(path.read_text()), "w", str(path.parent), "faro")


def test_status_shows_what_allow_thin_let_through_for_the_spec_that_runs(tmp_path, monkeypatch):
    started = []
    handlers = _handlers(tmp_path, monkeypatch, started)
    _run(handlers, thin_spec(), allow_thin=True)
    record = started[-1].__self__.state["allow_thin"]
    assert record == [{"code": "still_reused", "shots": ["v1", "v2", "v3"]}, {"code": "too_static", "shots": ["v1", "v2", "v3"]},
                      {"code": "title_card_hides_shot", "shots": ["h2"]}]
    saved = tmp_path / "faro.production.json"
    saved.write_text(json.dumps({"spec": thin_spec(), "status": "failed", "allow_thin": record}))
    assert _status(saved)["allow_thin"] == record
    resumed = asyncio.run(handlers["production.run"]({"version": 1, "input": {"workspace": "w", "production_id": "faro"}}))
    assert "warnings" not in resumed["result"] and started[-1].__self__.state["allow_thin"] == record, "a resume keeps it"
    with pytest.raises(HTTPException) as refused:
        _run(handlers, {**thin_spec(), "title": "Faro 2"})
    assert refused.value.detail["code"] == "quality_gate", "the record is not permission for a changed spec"
    moving = {**thin_spec(), "shots": [h3("h1", 0), h3("h2", 20)]}
    _run(handlers, moving)
    assert "allow_thin" not in started[-1].__self__.state, "a new spec the gate passes drops the old record"
    saved.write_text(json.dumps({"spec": moving, "status": "failed"}))
    assert "allow_thin" not in _status(saved)


def test_the_mcp_schema_declares_the_flag_and_the_title_card_allowance():
    run = next(item for item in command_catalog() if item["name"] == "production.run")
    fields = run["inputSchema"]["properties"]["input"]["properties"]
    assert fields["allow_thin"]["type"] == "boolean" and "warnings" in fields["allow_thin"]["description"]
    assert "allow_thin" in run["description"]
    shot = fields["spec"]["properties"]["shots"]["anyOf"][1]["items"]["properties"]
    assert "title_card" in shot["allow"]["items"]["enum"]
