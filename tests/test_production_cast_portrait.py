"""A one-person shot is referenced by a plain portrait, and a group is built from portraits."""
from __future__ import annotations

import pytest

from services.music_production import Production, ProductionError
from services.production_cast_portrait import PHRASE, frame_references, single_prompt
from services.production_stage_frames import forget_changed_cast, forget_shots_using_cast


def test_the_portrait_prompt_is_derived_and_an_explicit_one_is_kept():
    derived = single_prompt({"id": "hero", "sheet_prompt": "a singer in a red coat"}, "riso ink")
    assert derived == f"a singer in a red coat. {PHRASE} riso ink"
    assert single_prompt({"id": "hero", "sheet_prompt": "sheet", "single_prompt": "one person, grey backdrop"}) == "one person, grey backdrop"
    assert PHRASE in single_prompt({"id": "hero", "sheet_prompt": ""})


def test_a_one_person_frame_uses_the_portrait_and_still_says_one_subject(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    spec = {"style": {"image": "look"}, "cast": [{"id": "hero", "sheet_prompt": "a singer"}]}
    production.state = {"cast": {"hero": "/sheets/hero.png"}, "cast_single": {"hero": "/portraits/hero.png"}}
    window = {"frame": "at the mic", "cast": ["hero"]}
    assert frame_references(window, production.state["cast"], production.state["cast_single"]) == ["/portraits/hero.png"]
    assert frame_references({"cast": ["hero"]}, {"hero": "/sheets/hero.png"}, {}) == ["/sheets/hero.png"]
    assert "Exactly 1 distinct subject" in production.frame_prompt(spec, window)
    two = {"cast": ["hero", "pal"]}
    cast = {"hero": "/sheets/hero.png", "pal": "/sheets/pal.png"}
    singles = {"hero": "/portraits/hero.png", "pal": "/portraits/pal.png"}
    assert frame_references(two, cast, singles) == ["/portraits/hero.png", "/portraits/pal.png"]


def test_a_failed_sheet_keeps_its_reason_and_a_failed_portrait_keeps_the_sheet(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.image = lambda *args: "job"
    production.upload = lambda name: (name, "/u/" + name)

    def wait(jobs, poll=6):
        production.failures = {}
        out = {}
        for key in jobs:
            if key == "gone":
                out[key] = None
                production.failures[key] = "sheet refused"
            elif key in production.state.get("cast", {}):
                out[key] = None
                production.failures[key] = "portrait refused"
            else:
                out[key] = f"{key}.png"
        return out

    production.wait = wait
    spec = {"style": {}, "cast": [{"id": "solo", "sheet_prompt": "a singer"}, {"id": "gone", "sheet_prompt": "nobody"}]}
    with pytest.raises(ProductionError, match="sheet refused") as raised:
        production.cast(spec)
    assert raised.value.code == "cast_incomplete"
    assert production.state["cast"]["solo"] == "/u/solo.png"
    assert "solo" not in production.state.get("cast_single", {})


def _cast_production(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    requested = []
    production.image = lambda *args: requested.append(args) or "job"
    production.wait = lambda jobs: {key: f"{key}.png" for key in jobs}
    production.upload = lambda name: (name, "/u/" + name)
    return production, requested


def test_a_changed_cast_look_is_drawn_again_and_an_unchanged_one_is_kept(tmp_path):
    production, requested = _cast_production(tmp_path)
    spec = {"style": {"image": "riso"}, "cast": [{"id": "hero", "sheet_prompt": "young singer, denim jacket", "seed": 8}]}
    production.cast(spec)
    assert [call[0] for call in requested] == ["cast-hero", "cast-single-hero"]
    production.cast(spec)
    assert [call[0] for call in requested] == ["cast-hero", "cast-single-hero"], "a resume redoes nothing"
    production.cast({**spec, "cast": [{**spec["cast"][0], "sheet_prompt": "older singer, leather coat"}]})
    assert [call[0] for call in requested] == ["cast-hero", "cast-single-hero", "cast-hero", "cast-single-hero"]
    assert production.state["cast"]["hero"] == "/u/hero.png"
    assert production.state["cast_single"]["hero"] == "/u/hero.png"


def test_a_cast_made_before_its_source_was_recorded_is_kept(tmp_path):
    production, requested = _cast_production(tmp_path)
    production.state.update(cast={"hero": "/u/old-sheet.png"}, cast_single={"hero": "/u/old-portrait.png"})
    production.cast({"style": {"image": "riso"}, "cast": [{"id": "hero", "sheet_prompt": "a singer"}]})
    assert requested == []
    assert production.state["cast"]["hero"] == "/u/old-sheet.png"
    assert production.state["cast_single"]["hero"] == "/u/old-portrait.png"


def test_a_changed_cast_look_redraws_the_h3_shots_that_use_it(tmp_path):
    production, requested = _cast_production(tmp_path)
    spec = {"style": {"image": "look"}, "cast": [{"id": "hero", "sheet_prompt": "denim"}, {"id": "pal", "sheet_prompt": "suit"}]}
    production.cast(spec)
    production.state["frames"] = {"s0": "s0.png", "s1": "s1.png"}
    production.state["clips"] = {"s0": {"file": "s0.mp4"}, "s1": {"file": "s1.mp4"}}
    production.cast({**spec, "cast": [{**spec["cast"][0], "sheet_prompt": "leather"}, spec["cast"][1]]})
    forget_shots_using_cast(production, [
        {"key": "s0", "kind": "h3", "cast": ["hero"]},
        {"key": "s1", "kind": "h3", "cast": ["pal"]},
        {"key": "bg", "kind": "scene2d", "cast": ["hero"]},
    ])
    assert "s0" not in production.state["frames"] and production.state["frames"]["s1"] == "s1.png"
    assert production.state["clips"]["s0"]["obsolete"] and "obsolete" not in production.state["clips"]["s1"]


def test_frames_pass_redraws_after_a_cast_look_change(tmp_path):
    production, requested = _cast_production(tmp_path)
    spec = {"style": {"image": "look"}, "cast": [{"id": "hero", "sheet_prompt": "denim"}]}
    production.cast(spec)
    production.state["frames"] = {"s0": "old.png"}
    production.state["clips"] = {"s0": {"file": "old.mp4"}}
    changed = {**spec, "cast": [{**spec["cast"][0], "sheet_prompt": "leather"}]}
    production.cast(changed)
    production.wait = lambda jobs: {key: "new.png" for key in jobs}
    production.frames(changed, [{"key": "s0", "kind": "h3", "frame": "wide", "cast": ["hero"]}])
    assert production.state["frames"]["s0"] == "new.png"
    assert production.state["clips"]["s0"]["obsolete"]
    assert any(call[0] == "frame-s0" for call in requested)


def test_a_group_plate_is_composed_again_when_a_member_changes(tmp_path, monkeypatch):
    production, requested = _cast_production(tmp_path)
    (tmp_path / "uploads").mkdir()
    production.uploads = tmp_path / "uploads"
    composed = []
    monkeypatch.setattr("services.music_production.compose_group", lambda paths, out: composed.append(out.name) or True)
    spec = {"style": {}, "cast": [{"id": "a", "sheet_prompt": "red"}, {"id": "b", "sheet_prompt": "blue"},
                                  {"id": "duo", "group": ["a", "b"]}]}
    production.cast(spec)
    assert composed == ["p-group-duo.png"]
    changed = {**spec, "cast": [{**spec["cast"][0], "sheet_prompt": "green"}, spec["cast"][1], spec["cast"][2]]}
    production.cast(changed)
    assert composed == ["p-group-duo.png", "p-group-duo.png"]
    production.cast(changed)
    assert composed == ["p-group-duo.png", "p-group-duo.png"] and forget_changed_cast(production, changed) == set()


def test_a_cast_redraw_asks_for_a_new_job_not_the_journals_old_answer(tmp_path):
    """The journal answers a repeated intent id with the old job; a redraw must send a different one."""
    intents = []

    def mcp(tool, arguments):
        if tool == "generation.image":
            intents.append(arguments["intent_id"])
            return {"receipt": {"result": {"job_id": f"job-{len(intents)}"}}}
        return {}

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.wait = lambda jobs: {key: f"{key}.png" for key in jobs}
    production.upload = lambda name: (name, "/u/" + name)
    spec = {"style": {"image": "riso"}, "cast": [{"id": "hero", "sheet_prompt": "young singer", "seed": 8}]}
    production.cast(spec)
    first = list(intents)
    production.cast({**spec, "cast": [{**spec["cast"][0], "sheet_prompt": "older singer"}]})
    assert len(intents) == 4 and len(set(intents)) == 4, (first, intents)
