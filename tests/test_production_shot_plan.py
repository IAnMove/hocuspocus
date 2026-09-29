"""shots: "auto" builds a spec that validate_spec accepts."""
from __future__ import annotations

from services.music_production import segments, shot_windows, validate_spec
from services.production_shot_plan import plan_shots
from services.song_analysis import lyric_lines


def _lyrics() -> str:
    verse = "\n".join(f"verse line {i}" for i in range(4))
    chorus = "\n".join(f"chorus line {i}" for i in range(4))
    verse_b = "\n".join(f"second verse {i}" for i in range(2))
    chorus_b = "\n".join(f"second chorus {i}" for i in range(2))
    return f"[Intro]\n[Verse]\n{verse}\n[Chorus]\n{chorus}\n[Verse]\n{verse_b}\n[Chorus]\n{chorus_b}\n[Outro]\n"


def _spec(**extra) -> dict:
    spec = {
        "title": "Night Bus",
        "song": {"lyrics": _lyrics(), "caption": "bright pop, 120 BPM", "duration": 48, "bpm": 120},
        "style": {"image": "painterly", "video": "painterly motion"},
        "cast": [{"id": "singer", "sheet_prompt": "character sheet of a singer, front and side"}],
        "shots": "auto",
    }
    spec.update(extra)
    return spec


def _score(texts: list[str], duration: float, bpm: int) -> dict:
    """One bar of intro, then one bar per line. At 120 BPM a bar is 2 seconds."""
    bar = 4 * 60 / bpm
    lines = [{"i": i, "text": text, "t0": bar * (i + 1), "t1": bar * (i + 1) + bar * 0.8} for i, text in enumerate(texts)]
    return {"duration": duration, "bpm": bpm, "beat": 60 / bpm, "lines": lines}


def _covered(shots: list[dict], count: int) -> set[int]:
    covered = set()
    for shot in shots:
        if not isinstance(shot.get("line"), int):
            continue
        span = shot.get("span", 1)
        covered.update(i for i in range(shot["line"], shot["line"] + span) if 0 <= i < count)
    return covered


def _start_gaps(windows: list[dict], duration: float) -> list[float]:
    starts = sorted({round(point, 3) for point in (0.0, *(w["t0"] for w in windows), duration)})
    return [right - left for left, right in zip(starts, starts[1:])]


def test_auto_shots_cover_twelve_lines_without_a_two_bar_gap():
    raw = _spec()
    planned = validate_spec(raw)
    assert raw["shots"] == "auto"
    lines = lyric_lines(raw["song"]["lyrics"])
    assert len(lines) == 12
    shots = planned["shots"]
    assert _covered(shots, 12) == set(range(12))
    assert not any(str(shot.get("key") or "").startswith("fill") for shot in shots)
    score = _score(lines, raw["song"]["duration"], raw["song"]["bpm"])
    windows = shot_windows(planned, score)
    bar = 2.0
    assert all(gap <= 2 * bar + 1e-3 for gap in _start_gaps(windows, score["duration"]))
    assert any(shot["key"].startswith("fill") for shot in windows)
    assert all(shot["kind"] == "clip" for shot in windows if shot["key"].startswith("fill"))
    intro, outro = shots[0], next(shot for shot in shots if shot["key"] == "outro")
    assert intro["title"]["template"] == "end-card" and outro["title"]["template"] == "end-card"
    verse = [shot for shot in shots if shot["key"][0] in "vs" and shot.get("line", 99) < 4]
    # no stills and no desktop look: the non-sung shots are short H3 clips of the protagonist, never a terminal
    assert [shot["kind"] for shot in verse] == ["h3", "h3", "h3", "h3"]
    assert [bool(shot.get("sing")) for shot in verse] == [True, False, True, False]
    assert all(shot["action"].strip() and shot["frame"] and shot["cast"] == ["singer"] for shot in verse)
    assert not any(shot["kind"] == "screen" for shot in shots)
    assert planned["fill"] == [{"kind": "clip", "clip": "v0"}]
    assert [shot["line"] for shot in shots if shot.get("span") == 2] == [4, 6, 10]
    assert all(shot.get("cast") == ["singer"] for shot in shots if shot["kind"] == "h3")


def test_section_actions_replace_the_fixed_phrase():
    planned = plan_shots(_spec(section_actions={"verse": "taps the desk", "chorus": "lifts both hands"}))
    verse = next(shot for shot in planned["shots"] if shot.get("line") == 0)
    chorus = next(shot for shot in planned["shots"] if shot.get("span") == 2)
    assert verse["action"].startswith("taps the desk") and chorus["action"].startswith("lifts both hands")


def test_listed_shots_stay_the_same_object():
    spec = {"title": "t", "song": {"lyrics": "a", "caption": "b", "duration": 30, "bpm": 120},
            "style": {}, "shots": [{"key": "s", "kind": "screen"}]}
    assert validate_spec(spec) is spec


def test_analyzed_lyric_times_keep_the_last_chorus_and_outro():
    """Pads follow the score. A 3-minute song must not drop the last sung shot."""
    raw = _spec()
    raw["song"]["duration"] = 180
    planned = validate_spec(raw)
    texts = lyric_lines(raw["song"]["lyrics"])
    start, end = 18.0, 165.0
    slot = (end - start) / len(texts)
    lines = [{"i": i, "text": text, "t0": start + i * slot, "t1": start + i * slot + slot * 0.7}
             for i, text in enumerate(texts)]
    score = {"duration": 180.0, "bpm": 120, "beat": 0.5, "lines": lines}
    windows = shot_windows(planned, score)
    t0s = [window["t0"] for window in windows]
    assert t0s == sorted(t0s)
    assert all(gap <= 4.0 + 1e-3 for gap in _start_gaps(windows, score["duration"]))
    segs = segments(windows, score, lambda key: True, planned.get("fill") or [])
    keys = [shot["key"] for shot, _, _ in segs]
    assert "c2" in keys
    assert "outro" in keys
    assert all(b > a for _, a, b in segs)


def test_outro_stays_on_the_timeline_when_the_last_lyric_ends_the_song():
    """Auto outro is `after` the last line. last.t1 + 0.3 past duration used to drop the end card."""
    raw = _spec()
    planned = validate_spec(raw)
    texts = lyric_lines(raw["song"]["lyrics"])
    duration = float(raw["song"]["duration"])
    slot = duration / len(texts)
    lines = [{"i": i, "text": text, "t0": i * slot, "t1": min(duration, (i + 1) * slot)}
             for i, text in enumerate(texts)]
    assert lines[-1]["t1"] == duration
    score = {"duration": duration, "bpm": 120, "beat": 0.5, "lines": lines}
    windows = shot_windows(planned, score)
    outro = next(window for window in windows if window["key"] == "outro")
    assert 0 <= outro["t0"] < duration
    segs = segments(windows, score, lambda key: True, planned.get("fill") or [])
    keys = [shot["key"] for shot, _, _ in segs]
    assert "outro" in keys
    start, end = next((a, b) for shot, a, b in segs if shot["key"] == "outro")
    assert 0 <= start < end
    assert start < duration
    assert abs(end - duration) < 1e-6
    assert all(b > a for _, a, b in segs)


def test_stills_give_still_shots_and_a_theme_gives_the_desktop():
    stills = validate_spec(_spec(stills={"art": "/api/v1/uploads/a.png"}))["shots"]
    assert [shot["kind"] for shot in stills if shot["key"][0] == "s"] == ["still", "still", "still"]
    desktop = validate_spec(_spec(style={"theme": "tokyo-night"}))
    assert {shot["kind"] for shot in desktop["shots"] if shot["key"][0] == "s"} == {"screen"}
    assert desktop["fill"][0]["kind"] == "screen"


def test_a_look_with_no_singer_plans_no_sung_shots():
    planned = validate_spec(_spec(style={"preset": "omarchy-desktop"}))
    assert not any(shot.get("sing") for shot in planned["shots"])
    assert {shot["kind"] for shot in planned["shots"]} == {"screen"}
    chorus = [shot for shot in planned["shots"] if shot.get("span") == 2]
    assert [shot["line"] for shot in chorus] == [4, 6, 10]


def test_a_shot_with_one_character_says_nobody_else_appears():
    from services.production_shot_plan import ALONE
    planned = plan_shots(_spec())
    sung = [shot for shot in planned["shots"] if shot.get("sing")]
    assert sung and all(shot["action"].endswith(ALONE) for shot in sung)
    two = plan_shots(_spec(cast=[{"id": "a", "sheet_prompt": "x"}, {"id": "b", "sheet_prompt": "y"}]))
    assert not any(ALONE in shot["action"] for shot in two["shots"] if shot["kind"] == "h3")
