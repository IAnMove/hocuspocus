"""A plan that would look thin is refused before GPU work; dry_run says why and warns about the rest."""
import asyncio
import json

import pytest
from fastapi import HTTPException

from services.music_production import command_handlers
from services.production_dry_run import dry_run
from services.production_quality_gate import blocking_problems, plan_warnings

SONG = {"lyrics": "[Verse]\nla luz se queda", "caption": "lullaby", "duration": 40, "bpm": 96}


def card(key, t0, **extra):
    return {"key": key, "kind": "still", "still": "card-base", "t0": t0, **extra}


def h3(key, t0, **extra):
    return {"key": key, "kind": "h3", "t0": t0, "frame": "a lighthouse", "action": "the beam sweeps", **extra}


def pattern_spec():
    """The Ocho luces v2 shape: the title card panned again and again between clips."""
    shots = [card("s00", 0, allow=["still", "dark"])]
    for index, t0 in enumerate((3, 9, 11, 17, 19, 25, 27), start=1):
        shots.append(h3(f"h{index}", t0) if index % 2 else card(f"c{index}", t0, plannedActed2D="a gull flies"))
    shots.append(card("s99", 37, allow=["still", "dark"]))
    return {"title": "Faro", "song": SONG, "style": {}, "shots": shots}


def test_one_picture_panned_across_many_shots_is_refused_but_title_cards_are_not():
    problems = blocking_problems(pattern_spec())
    assert [item["code"] for item in problems] == ["still_reused"]
    assert problems[0]["shots"] == ["c2", "c4", "c6"]
    spec = pattern_spec()
    spec["shots"] = [shot for shot in spec["shots"] if shot["key"] not in ("c4", "c6")]
    assert blocking_problems(spec) == []


def test_too_much_still_runtime_is_refused_at_the_quality_bar():
    shots = [card("a", 0), {**card("b", 10), "still": "other"}, h3("c", 20)]
    problems = blocking_problems({"song": SONG, "shots": shots})
    assert problems == [{"code": "too_static", "ratio": 0.5, "limit": 0.35, "hint": problems[0]["hint"]}]
    assert blocking_problems({"song": SONG, "shots": shots, "quality": "draft"}) == []


def test_dry_run_reports_blocking_and_the_warnings_that_explain_thin_plans(tmp_path):
    spec = pattern_spec()
    spec["shots"].append({"key": "r1", "kind": "clip", "clip": "h1", "t0": 38})
    spec["shots"].append({"key": "r2", "kind": "clip", "clip": "h1", "t0": 38.5})
    spec["cast"] = [{"id": "hero", "sheet_prompt": "a felt hero"}]
    report = dry_run(spec, root=tmp_path)
    assert [item["code"] for item in report["blocking"]] == ["still_reused"]
    codes = {item["code"]: item for item in report["warnings"]}
    assert codes["ignored_shot_field"]["field"] == "plannedActed2D"
    assert codes["clip_replayed"]["shots"] == ["r1", "r2"]
    assert codes["h3_without_cast"]["shots"] == ["h1", "h3", "h5", "h7"]


def test_boxes_unanimated_rigs_and_one_template_everywhere_are_warned(tmp_path):
    (tmp_path / "boat.glb").write_bytes(b"glb")
    (tmp_path / "boat.meta.json").write_text(json.dumps({"generation": {"model": {"id": "procedural-compose"}}}))
    shots = [{"key": f"d{i}", "kind": "scene3d", "t0": i * 4,
              "scene3d": {"template": "dance-stage", "cast": {"subject_1": "hero", "prop": "/api/v1/file/boat.glb?workspace=w"}}}
             for i in range(5)]
    spec = {"song": SONG, "cast": [{"id": "hero", "sheet_prompt": "x"}], "models": {"hero": {"from": "hero"}}, "shots": shots}
    codes = {item["code"]: item for item in plan_warnings(spec, tmp_path)}
    assert codes["procedural_model"]["model"] == "boat.glb" and len(codes["procedural_model"]["shots"]) == 5
    assert codes["model_not_animated"]["objects"][0] == "d0:subject_1"
    assert codes["template_reused"]["template"] == "dance-stage"
    shots[0]["scene3d"]["cast"]["subject_1"] = {"source": "hero", "clip": "dance_bounce"}
    assert "d0:subject_1" not in {item["code"]: item for item in plan_warnings(spec, tmp_path)}["model_not_animated"]["objects"]


def test_a_copied_structure_or_lyric_look_from_a_sibling_piece_is_warned(tmp_path):
    spec = {**pattern_spec(), "style": {"lyric_template": "social-caption", "lyric_style": {"box": {"kind": "solid"}}}}
    (tmp_path / "piece-1.production.json").write_text(json.dumps({"spec": spec}))
    codes = [item["code"] for item in plan_warnings(spec, tmp_path, "piece-2")]
    assert "same_shot_pattern" in codes and "same_lyric_look" in codes
    assert plan_warnings(spec, tmp_path, "piece-1") == [item for item in plan_warnings(spec, tmp_path, "piece-1")
                                                         if item["code"] not in ("same_shot_pattern", "same_lyric_look")]


def test_run_refuses_a_new_thin_plan_but_resumes_one_already_running(tmp_path, monkeypatch):
    started = []

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
    handlers = command_handlers(lambda _name: str(tmp_path), lambda: str(tmp_path), lambda: "http://127.0.0.1:9", lambda: "token")
    body = {"version": 1, "input": {"workspace": "w", "production_id": "faro", "spec": pattern_spec()}}
    with pytest.raises(HTTPException) as caught:
        asyncio.run(handlers["production.run"](body))
    assert caught.value.status_code == 422
    assert caught.value.detail["code"] == "quality_gate"
    assert caught.value.detail["problems"][0]["code"] == "still_reused"
    assert started == []
    (tmp_path / "faro.production.json").write_text(json.dumps({"spec": pattern_spec(), "status": "failed"}))
    assert asyncio.run(handlers["production.run"](body))["result"]["running"] is True
    assert len(started) == 1
