"""Trailer structure: five beats on time, quick cuts that re-frame, designed silence, riser and impact."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from services.music_production import Production, ProductionError, validate_spec
from services.production_dry_run import dry_run
from services.production_plan import plan_brief
from services.production_shot_plan import plan_shots
from services.production_structure import BEAT_SHARE, MIN_H3_S, beat_plan, cut_lengths, require_structure
from services.production_trailer_audio import (attach, audio_cues, beat_starts, design, impact_command, plan_digest, render, riser_command,
                                               soundtrack_command)


def _spec(**extra) -> dict:
    spec = {"title": "THE CURTAIN", "structure": "trailer", "cta": "Coming soon", "song": {"lyrics": "", "caption": "trailer score", "duration": 60, "bpm": 120},
            "style": {}, "cast": [{"id": "hero", "sheet_prompt": "a hero"}], "shots": "auto"}
    spec.update(extra)
    return spec


def test_the_beats_share_the_duration_and_land_on_bars():
    beats = beat_plan(60, 120)
    assert [b["beat"] for b in beats] == list(BEAT_SHARE) and beats[0]["start"] == 0 and beats[-1]["end"] == 60
    assert all(abs(b["start"] % 2.0) < 1e-6 for b in beats)                     # 120 BPM: a bar is 2 s
    assert all(left["end"] == right["start"] for left, right in zip(beats, beats[1:]))
    assert abs(sum(b["end"] - b["start"] for b in beats) - 60) < 1e-6
    assert beat_plan(8, 0)[-1]["end"] == 8                                      # degenerate input still covers the song


def test_quick_cuts_accelerate_and_add_up():
    cuts = cut_lengths(18.0, 7)
    assert abs(sum(cuts) - 18.0) < 0.01 and cuts == sorted(cuts, reverse=True) and cuts[0] > 2 * cuts[-1] * 0.9


def test_a_trailer_is_planned_on_time_with_generated_shots_held_and_quick_cuts_reframing_them():
    planned = plan_shots(_spec(treatment={"arc": "a", "moments": [{"at": "reveal", "event": "the curtain rises", "id": "rise"}]}))
    shots = planned["shots"]
    assert [s["t0"] for s in shots] == sorted(s["t0"] for s in shots) and shots[0]["t0"] == 0
    assert {s["beat"] for s in shots} == set(BEAT_SHARE) and not any(s.get("sing") for s in shots) and planned["auto_pads"] is False
    assert [s["key"] for s in shots if s["beat"] == "presentation"] == ["open"] and shots[-1]["key"] == "close"
    cuts = [s for s in shots if s["beat"] == "escalation"]
    generated = {s["key"] for s in shots if s["kind"] == "h3"}
    assert len(cuts) >= 3 and all(s["kind"] == "clip" and s["clip"] in generated for s in cuts)       # a clip a minute, not thirty
    assert len({s["camera"] for s in cuts}) >= 4                                # every re-framing has its own camera
    reveal = next(s for s in shots if s["key"] == "reveal")
    assert reveal["moment"] == "rise" and "the curtain rises" in reveal["action"]
    assert shots[0]["title"]["fields"]["title"] == "THE CURTAIN" and shots[-1]["title"]["fields"]["cta"] == "Coming soon"


def test_generated_shots_of_a_trailer_are_long_enough_to_be_worth_a_clip():
    shots = plan_shots(_spec())["shots"]
    by_key = {s["key"]: s for s in shots}
    order = [s["key"] for s in shots] + [None]
    for index, key in enumerate(order[:-1]):
        if by_key[key]["kind"] == "h3":
            end = by_key[order[index + 1]]["t0"] if order[index + 1] else 60.0
            assert end - by_key[key]["t0"] >= MIN_H3_S - 1e-6, key


def test_a_trailer_in_other_looks_reframes_with_its_own_kind():
    screens = plan_shots(_spec(style={"theme": "tokyo-night"}))["shots"]
    assert {s["kind"] for s in screens} == {"screen"} and len({s["desktop"]["layout"] for s in screens if s["beat"] == "escalation"}) >= 2
    stills = plan_shots(_spec(stills={"art": "/api/v1/uploads/a.png"}))["shots"]
    assert {s["kind"] for s in stills} == {"still"} and len({tuple(s["zoom"]) for s in stills if s["beat"] == "escalation"}) >= 2


def test_the_clip_structure_is_untouched_and_a_bad_structure_is_refused():
    clip = plan_shots(_spec(structure="clip", song={"lyrics": "[Verse]\na\nb\n[Chorus]\nc\nd", "caption": "p", "duration": 30, "bpm": 120}))
    assert clip["auto_pads"] is True and not any("beat" in s for s in clip["shots"])
    with pytest.raises(ProductionError):
        require_structure({"structure": "documentary"})
    assert validate_spec(_spec())["structure"] == "trailer"


def test_moments_can_name_a_beat_in_a_trailer_and_the_dry_run_checks_them():
    spec = _spec(treatment={"arc": "a", "moments": [{"at": "reveal", "event": "e", "id": "r"}, {"at": "tension", "event": "f", "id": "t"}]})
    report = dry_run(spec)
    assert not [w for w in report["warnings"] if w["code"].startswith("moment")]
    assert {row["kind"] for row in report["windows"]} >= {"h3", "clip"}


def test_a_trailer_brief_may_be_instrumental_and_carries_its_treatment():
    brief = {"tema": "The curtain", "publico": "all", "duracion": "60 s", "musica": "dark score 100 BPM", "estilo": "anime", "protagonista": "a hero",
             "cta": "Coming soon", "limites": "none", "estructura": "trailer", "tratamiento": {"arc": "a door opens", "moments": [{"at": "reveal", "event": "light"}]}}
    spec = plan_brief(brief)
    assert spec["structure"] == "trailer" and spec["song"]["lyrics"] == "" and spec["treatment"]["arc"] == "a door opens"
    assert {s["beat"] for s in spec["shots"]} == set(BEAT_SHARE)
    with pytest.raises(Exception):
        plan_brief({k: v for k, v in brief.items() if k != "estructura"})            # a clip without lyrics is still refused


# ---------------------------------------------------------------- sound
def test_the_sound_design_follows_the_planned_beats():
    shots = plan_shots(_spec())["shots"]
    starts = beat_starts(shots)
    plan = design(shots, 120)
    bar = 2.0
    assert plan["impacts"][0] == {"at": starts["reveal"], "volume": 1.0} and plan["impacts"][-1]["at"] == starts["close"]
    assert plan["silences"] == [[starts["reveal"] - bar, starts["reveal"]]]
    assert plan["risers"][0] == {"end": starts["reveal"], "duration": 4.0} and plan["risers"][1]["end"] == starts["escalation"]
    assert design([{"beat": "presentation", "t0": 0}], 120) == {"silences": [], "risers": [], "impacts": [], "late_entry": 0.0}
    assert plan_digest(plan, "a.wav") != plan_digest(plan, "b.wav")


def test_the_commands_name_the_silence_the_delay_and_the_fades(tmp_path):
    song = soundtrack_command(Path("s.wav"), Path("o.wav"), [[18.0, 20.0]], 3.0)
    graph = song[song.index("-af") + 1]
    assert "between(t,18.000,20.000)" in graph and "adelay=3000|3000" in graph and "/0.02" in graph
    assert "anull" in soundtrack_command(Path("s.wav"), Path("o.wav"), [], 0)
    assert "aevalsrc" in " ".join(riser_command(Path("r.wav"), 4.0)) and "d=1.6" in " ".join(impact_command(Path("i.wav")))


def _volume(path, start: float, length: float) -> float:
    out = subprocess.run(["ffmpeg", "-v", "info", "-ss", str(start), "-t", str(length), "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True).stderr
    return float(re.search(r"mean_volume: (-?[\d.]+|-inf) dB", out).group(1).replace("-inf", "-99"))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_ffmpeg_really_leaves_the_silence_and_makes_the_hit(tmp_path):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=220:duration=30", "-ar", "48000", "-ac", "2", str(tmp_path / "song.wav")], check=True)
    plan = design([{"beat": "escalation", "t0": 10.0}, {"beat": "reveal", "t0": 20.0}, {"beat": "close", "t0": 26.0}], 120)
    names = render(tmp_path, "p", plan, "song.wav")
    assert names and (tmp_path / names["soundtrack"]).is_file()
    assert _volume(tmp_path / names["soundtrack"], 18.2, 1.5) < -60           # the bar before the reveal is silent
    assert _volume(tmp_path / names["soundtrack"], 10.0, 4.0) > -30            # the song is there before it
    assert _volume(tmp_path / "p-trailer-impact.wav", 0, 1.0) > -25            # the hit has weight
    first, last = _volume(tmp_path / "p-trailer-riser-1.wav", 0, 1.0), _volume(tmp_path / "p-trailer-riser-1.wav", 3.0, 1.0)
    assert last > first + 6                                                     # the riser climbs
    cues = audio_cues(names, "my ws")
    assert [c["start"] for c in cues] == sorted(c["start"] for c in cues) and cues[0]["source"].endswith("workspace=my%20ws")
    assert any(c["name"] == "impact" and c["start"] == 20.0 for c in cues)


def test_montage_gets_the_processed_soundtrack_and_the_cues_only_for_a_trailer(tmp_path, monkeypatch):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *a: {})
    production.state["song"] = {"file": "song.wav"}
    spec = validate_spec(_spec())
    montage = {"soundtrack": {"source": "/api/v1/file/song.wav?workspace=ws", "volume": 1.0}, "audioCues": []}
    monkeypatch.setattr("services.production_trailer_audio.render", lambda root, prefix, plan, song: {
        "soundtrack": "p-trailer-soundtrack.wav", "risers": [{"end": 40.0, "duration": 4.0, "file": "r.wav"}], "impacts": [{"at": 44.0, "volume": 1.0, "file": "i.wav"}]})
    result = attach(production, spec, {**montage, "soundtrack": dict(montage["soundtrack"])})
    assert result["soundtrack"]["source"].startswith("/api/v1/file/p-trailer-soundtrack.wav") and [c["id"] for c in result["audioCues"]] == ["riser-1", "impact-1"]
    assert production.state["trailer_audio"]["digest"]
    untouched = attach(production, {**spec, "structure": "clip"}, {**montage})
    assert untouched == montage                                                  # a clip's montage is exactly what it was


def test_when_the_sound_cannot_be_made_the_song_stays_as_it_is(tmp_path, monkeypatch):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *a: {})
    production.state["song"] = {"file": "missing.wav"}
    spec = validate_spec(_spec())
    montage = {"soundtrack": {"source": "s", "volume": 1.0}, "audioCues": []}
    assert attach(production, spec, dict(montage)) == montage
    assert any("could not render" in line for line in production.state["log"])
