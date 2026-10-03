"""Treatment: what happens in the video. Validation, where moments land, and the variation of returning choruses."""
from __future__ import annotations

import pytest

from services.music_production import ProductionError, validate_spec
from services.production_dry_run import dry_run
from services.production_shot_plan import plan_shots
from services.production_treatment import (annotate_moments, lyric_sections, moments_of, resolve_at, treatment_warnings, validate_treatment,
                                           variation_warnings, VARIATIONS)

LYRICS = "[Intro]\nhush\n[Verse 1]\na1\na2\n[Pre-Chorus]\nb1\n[Chorus]\nc1\nc2\n[Verse 2]\nd1\nd2\n[Chorus]\nc1\nc2\n[Bridge]\ne1\n[Final Chorus]\nc1\nc2\n[Outro]\nfin"


def _spec(**extra) -> dict:
    spec = {"title": "t", "song": {"lyrics": LYRICS, "caption": "pop", "duration": 60, "bpm": 120}, "style": {}, "shots": "auto",
            "cast": [{"id": "hero", "sheet_prompt": "a hero"}]}
    spec.update(extra)
    return spec


def test_a_treatment_is_checked_and_normalised():
    ok = validate_treatment({"arc": "chaos becomes order", "want": "a calm desk", "moments": [{"at": "chorus2", "event": "the city appears"}], "motifs": ["keys"]})
    assert ok["moments"] == [{"id": "m1", "at": "chorus2", "event": "the city appears"}] and ok["motifs"] == ["keys"]
    assert validate_treatment(None) is None
    for bad in ("text", {"arc": ""}, {"arc": "x", "extra": 1}, {"moments": [{"at": "chorus", "event": ""}]}, {"arc": "x", "moments": [{"at": "", "event": "e"}]},
                {"arc": "x", "moments": [{"at": "chorus", "event": "e", "id": "bad id!"}]},
                {"arc": "x", "moments": [{"at": "chorus", "event": "e", "id": "a"}, {"at": "verse", "event": "f", "id": "a"}]},
                {"arc": "x", "motifs": ["m"] * 7}, {"moments": []}):
        with pytest.raises(ValueError):
            validate_treatment(bad)
    with pytest.raises(ProductionError) as error:
        validate_spec({**_spec(), "treatment": {"arc": ""}})
    assert error.value.code == "invalid_spec"


def test_moments_land_on_sections_by_name_number_or_line():
    sections = lyric_sections(LYRICS)
    assert [(s["role"], s["nth"]) for s in sections] == [("intro", 1), ("verse", 1), ("pre-chorus", 1), ("chorus", 1), ("verse", 2), ("chorus", 2),
                                                          ("bridge", 1), ("chorus", 3), ("outro", 1)]
    assert resolve_at("chorus", sections) == (4, 5) and resolve_at("chorus3", sections) == (11, 12) and resolve_at("final-chorus", sections) is None
    assert resolve_at("bridge", sections) == (10, 10) and resolve_at("pre-chorus", sections) == (3, 3) and resolve_at("line:7", sections) == (7, 7)
    assert resolve_at(2, sections) == (2, 2) and resolve_at("chorus9", sections) is None and resolve_at("tension", sections) is None
    assert resolve_at("tension", sections, "trailer") == "tension"


def test_auto_shots_carry_the_moment_into_the_action_of_the_shot_that_covers_it():
    planned = plan_shots(_spec(treatment={"arc": "a", "moments": [{"at": "bridge", "event": "the curtain rises", "id": "rise"}]}))
    covered = [shot for shot in planned["shots"] if shot.get("moment") == "rise"]
    assert len(covered) == 1 and covered[0]["line"] == 10 and "Key moment: the curtain rises" in covered[0]["action"]
    assert not any("Key moment" in shot.get("action", "") for shot in planned["shots"] if shot is not covered[0])


def test_a_returning_chorus_is_varied_by_the_planner_and_passes_its_own_check():
    planned = plan_shots(_spec())
    first = [s for s in planned["shots"] if s.get("line") in (4, 5)]
    second = [s for s in planned["shots"] if s.get("line") in (8, 9)]
    third = [s for s in planned["shots"] if s.get("line") in (11, 12)]
    assert first and second and third
    assert not any(v in s["action"] for s in first for v in VARIATIONS)                 # the first chorus is the plain one
    assert any(v in s["action"] for s in second for v in VARIATIONS) and any(v in s["action"] for s in third for v in VARIATIONS)
    assert {s["action"] for s in second} != {s["action"] for s in first}
    assert variation_warnings(_spec(), planned["shots"]) == []


def test_identical_choruses_are_reported_before_any_gpu_work():
    shots = [{"key": "c1", "kind": "h3", "line": 4, "span": 2, "frame": "hero sings", "action": "hero sings loudly", "cast": ["hero"]},
             {"key": "c2", "kind": "h3", "line": 8, "span": 2, "frame": "hero sings", "action": "hero sings loudly", "cast": ["hero"]},
             {"key": "c3", "kind": "h3", "line": 11, "frame": "hero sings", "action": "hero sings loudly, and a consequence: the stage is on fire", "cast": ["hero"]}]
    found = variation_warnings(_spec(), shots)
    assert [w["sections"] for w in found] == [["chorus1", "chorus2"]] and found[0]["code"] == "chorus_repeats_identical"
    assert found[0]["shots"] == ["c1", "c2", "c1", "c2"] or set(found[0]["shots"]) == {"c1", "c2"}


def test_a_moment_with_no_shot_and_a_missing_treatment_are_named_in_the_dry_run():
    spec = _spec(shots=[{"key": "a", "kind": "h3", "line": 1, "span": 2, "frame": "f", "action": "a"}],
                 treatment={"arc": "x", "moments": [{"at": "bridge", "event": "the reveal", "id": "reveal"}, {"at": "outro9", "event": "x", "id": "lost"}]})
    codes = {(w["code"], w.get("moment")) for w in dry_run(spec)["warnings"]}
    assert ("moment_without_shot", "reveal") in codes and ("moment_unresolved", "lost") in codes
    bare = {w["code"] for w in dry_run(_spec(shots=spec["shots"], quality="max"))["warnings"]}
    assert "treatment_missing" in bare
    assert "treatment_missing" not in {w["code"] for w in dry_run(_spec(shots=spec["shots"]))["warnings"]}           # only at quality max
    assert {w["code"] for w in dry_run(_spec(shots=spec["shots"], treatment={"arc": ""}))["warnings"]} >= {"treatment_invalid"}


def test_a_moment_that_has_a_shot_is_not_reported():
    spec = _spec(shots=[{"key": "a", "kind": "h3", "line": 10, "frame": "f", "action": "a"}], treatment={"arc": "x", "moments": [{"at": "bridge", "event": "e"}]})
    assert treatment_warnings(spec, spec["shots"]) == []
    assert moments_of(spec)[0]["lines"] == (10, 10)


def test_pads_do_not_repeat_the_same_picture():
    planned = plan_shots(_spec(stills={"art": "/api/v1/uploads/a.png"}))
    from services.production_shot_plan import place_pads
    windows = [{"key": "s", "kind": "still", "i": 0, "t0": 0.0, "t1": 4.0, "still": "art"}]
    pads = [w for w in place_pads(windows, planned, 60.0, 120.0) if str(w["key"]).startswith("fill")]
    assert len(pads) >= 3 and len({p["camera"] for p in pads}) >= 3
