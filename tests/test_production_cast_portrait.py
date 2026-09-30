"""A one-person shot is referenced by a plain portrait, and a group is built from portraits."""
from __future__ import annotations

import pytest

from services.music_production import Production, ProductionError
from services.production_cast_portrait import PHRASE, frame_references, single_prompt, subject_count


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
    band = {"id": "band", "sheet_prompt": "four players", "count": 4}
    assert subject_count(band) == 4
    leftover = {"band": "/portraits/band.png"}
    sheets = {"band": "/sheets/band.png"}
    assert frame_references({"cast": ["band"]}, sheets, leftover, {"cast": [band]}) == ["/sheets/band.png"]


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


def test_a_multi_subject_sheet_keeps_its_reference_and_skips_the_portrait(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    requested = []
    production.image = lambda *args: requested.append(args) or "job"
    production.wait = lambda jobs: {key: f"{key}.png" for key in jobs}
    production.upload = lambda name: (name, "/u/" + name)
    spec = {"style": {}, "cast": [{"id": "band", "sheet_prompt": "four players", "count": 4}]}
    production.cast(spec)
    assert [item[0] for item in requested] == ["cast-band"]
    assert "band" not in production.state.get("cast_single", {})
    production.state["cast_single"] = {"band": "/u/stale-portrait.png"}
    production.frames(spec, [{"key": "s0", "kind": "h3", "frame": "on stage", "cast": ["band"]}])
    assert requested[-1][2] == ["/u/band.png"]
