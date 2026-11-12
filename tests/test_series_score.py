"""The episode score: music cues over runs of shots, laid by the assembly and lowered while someone speaks."""
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from services.episode_finishing import finish_episode, finishing_note, join_spans, lay_score, speech_spans
from services.mix_concat import hold_crossfade_output_seconds
from services.series_ambience import Bed, ambience_duck_db, bed_filter, check_sound_design, clip_ambience, shot_sound_design
from services.series_library import SeriesConflictError, normalize_series_project, update_series_episode
from services.series_score import (
    DUCK_ATTACK,
    DUCK_DB,
    DUCK_RELEASE,
    Dip,
    bed_dips,
    clip_score,
    envelope,
    gain_at,
    merge_spans,
    normalize_score,
    own_music,
    plan_cues,
)
from services.series_take_inputs import render_inputs, stale_shot_ids

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
DUCKED = 10 ** (-DUCK_DB / 20)
THEME = {"file": "mus-theme.wav", "volume": 0.18, "fadeIn": 1.5, "fadeOut": 2.0, "duck": True}


def cuts(*seconds):
    """Hard-cut spans for clips of these lengths."""
    spans, start = [], 0.0
    for length in seconds:
        spans.append((start, start + length))
        start += length
    return spans


def _shots():
    return [{"id": "s1", "order": 1, "sceneId": "e1_open"}, {"id": "s2", "order": 2, "sceneId": "e1_open"},
            {"id": "s4", "order": 4, "sceneId": "e1_bar", "layout2d": {"music": {"file": "mus-song.wav", "volume": 0.5}}},
            {"id": "s3", "order": 3, "sceneId": "e1_bar"}]


# The cues -----------------------------------------------------------------------------------------------------------

def test_cues_get_their_defaults_and_a_scene_or_a_run_of_shots():
    assert normalize_score([{"sceneId": "e1_open", "file": " mus-theme.wav "}], _shots()) == [
        {"sceneId": "e1_open", "file": "mus-theme.wav", "volume": 0.18, "fadeIn": 1.5, "fadeOut": 2.0, "duck": True}]
    assert normalize_score([{"fromShotId": "s3", "file": "x.wav", "volume": 0, "fadeIn": 0, "duck": False}], _shots()) == [
        {"fromShotId": "s3", "toShotId": "s3", "file": "x.wav", "volume": 0.0, "fadeIn": 0.0, "fadeOut": 2.0, "duck": False}]
    assert normalize_score(None, _shots()) == [] and normalize_score([], []) == []


@pytest.mark.parametrize(("cue", "message"), [
    ("theme", r"score\[0\] must be an object"),
    ({"sceneId": "e1_open"}, r"score\[0\]\.file must name"),
    ({"sceneId": "e1_open", "file": "  "}, r"\.file must name"),
    ({"file": "x.wav"}, "needs fromShotId"),
    ({"toShotId": "s2", "file": "x.wav"}, "needs fromShotId"),
    ({"sceneId": "e1_open", "fromShotId": "s1", "file": "x.wav"}, "not both"),
    ({"fromShotId": 3, "file": "x.wav"}, r"fromShotId must be a shot"),
    ({"sceneId": "e1_open", "file": "x.wav", "volume": 2.5}, r"volume must be a number from 0 to 2"),
    ({"sceneId": "e1_open", "file": "x.wav", "volume": True}, "volume must be a number"),
    ({"sceneId": "e1_open", "file": "x.wav", "fadeOut": -1}, "fadeOut must be a number from 0 to 30"),
    ({"sceneId": "e1_open", "file": "x.wav", "duck": "yes"}, "duck must be true or false"),
    ({"sceneId": "e1_open", "file": "x.wav", "fade_in": 2}, "unknown fields: fade_in"),
])
def test_a_malformed_cue_is_refused(cue, message):
    with pytest.raises(ValueError, match=message):
        normalize_score([cue], _shots())


def test_cues_may_not_overlap_or_run_backwards():
    with pytest.raises(ValueError, match=r"score\[0\] and episode.score\[1\] overlap at shot s3"):
        normalize_score([{"fromShotId": "s1", "toShotId": "s3", **THEME}, {"sceneId": "e1_bar", **THEME}], _shots())
    with pytest.raises(ValueError, match=r"score\[1\] and episode.score\[0\] overlap at shot s2"):
        normalize_score([{"fromShotId": "s2", "toShotId": "s4", **THEME}, {"sceneId": "e1_open", **THEME}], _shots())
    with pytest.raises(ValueError, match=r"score\[0\] ends at shot s2, before it starts at shot s3"):
        normalize_score([{"fromShotId": "s3", "toShotId": "s2", **THEME}], _shots())
    with pytest.raises(ValueError, match="a list"):
        normalize_score({"sceneId": "e1_open"}, _shots())
    side_by_side = [{"sceneId": "e1_bar", **THEME}, {"sceneId": "e1_open", **THEME}]
    assert normalize_score(side_by_side, _shots()) == side_by_side, "cues that meet at a cut do not overlap"


def test_a_cue_left_behind_by_a_rewrite_is_kept_but_a_new_one_must_name_real_shots():
    gone = [{"fromShotId": "s1", "toShotId": "s9", **THEME}, {"sceneId": "e1_cold_open", **THEME}]
    assert normalize_score(gone, _shots()) == gone, "a rewritten script does not lose the score; the cut skips it"
    with pytest.raises(ValueError, match=r"score\[0\]: the episode has no shot s9"):
        normalize_score(gone, _shots(), strict=True)
    with pytest.raises(ValueError, match="scene e1_cold_open has no shots"):
        normalize_score(gone[1:], _shots(), strict=True)


def _project(score=None):
    episode = {"id": "e1", "script": [{"id": "e1_open"}, {"id": "e1_bar"}], "shots": _shots(),
               **({"score": score} if score is not None else {})}
    return normalize_series_project({"id": "show", "episodesById": {"e1": episode}}, "show", "default")


def test_the_library_stores_the_score_with_the_episode_and_refuses_a_bad_one():
    assert _project([{"sceneId": "e1_bar", "file": "mus-theme.wav"}])["episodesById"]["e1"]["score"] == [
        {"sceneId": "e1_bar", "file": "mus-theme.wav", "volume": 0.18, "fadeIn": 1.5, "fadeOut": 2.0, "duck": True}]
    assert "score" not in _project([])["episodesById"]["e1"], "an empty score clears it"
    assert "score" not in _project()["episodesById"]["e1"]
    with pytest.raises(ValueError, match="overlap"):
        _project([{"sceneId": "e1_bar", **THEME}, {"fromShotId": "s4", **THEME}])


def test_an_episode_update_sets_the_score_and_checks_its_shots():
    series = _project()
    updated = normalize_series_project(update_series_episode(
        series, "e1", {"score": [{"sceneId": "e1_open", "file": "mus-theme.wav"}]}, base_series_revision=1), "show", "default")
    stored = updated["episodesById"]["e1"]["score"]
    assert stored[0]["sceneId"] == "e1_open" and stored[0]["volume"] == 0.18
    with pytest.raises(ValueError, match="the episode has no shot s9"):
        update_series_episode(series, "e1", {"score": [{"fromShotId": "s9", **THEME}]}, base_series_revision=1)
    with pytest.raises(ValueError, match="must be an object"):
        update_series_episode(series, "e1", {"score": [1]}, base_series_revision=1)
    with pytest.raises(SeriesConflictError):
        update_series_episode(series, "e1", {"score": []}, base_series_revision=7)
    rewritten = normalize_series_project(update_series_episode(
        updated, "e1", {"shots": [{"id": "s9", "order": 1, "sceneId": "e1_bar"}], "replaceShots": True},
        base_series_revision=updated["revision"]), "show", "default")
    assert rewritten["episodesById"]["e1"]["score"] == stored, "a rewrite that drops the scene keeps the cue; the cut skips it"
    episode = rewritten["episodesById"]["e1"]
    resent = update_series_episode(rewritten, "e1", {**episode, "title": "Renamed"}, base_series_revision=rewritten["revision"])
    assert resent["episodesById"]["e1"]["title"] == "Renamed", "an editor sending the whole episode back still saves"
    with pytest.raises(ValueError, match="scene e1_open has no shots"):
        update_series_episode(rewritten, "e1", {"score": [{**stored[0], "volume": 0.3}]}, base_series_revision=rewritten["revision"])


def test_an_agent_reading_the_episode_sees_its_score():
    from services.series_guide import compact_episode
    episode = _project([{"sceneId": "e1_bar", "file": "mus-theme.wav"}])["episodesById"]["e1"]
    assert compact_episode({}, episode)["score"] == episode["score"]
    assert "score" not in compact_episode({}, {**episode, "score": []})


def test_own_music_is_a_shot_music_file_that_is_heard():
    assert own_music({"layout2d": {"music": {"file": "mus-song.wav"}}})
    assert not own_music({"layout2d": {"music": {"file": "mus-song.wav", "volume": 0}}}), "volume 0 is silent"
    assert not own_music({"layout2d": {"music": {"volume": 0.5}}}) and not own_music({}) and not own_music({"layout2d": 3})


def test_clips_carry_each_cue_by_clip_and_which_clips_have_their_own_music():
    episode = {"shots": _shots(), "score": [{"sceneId": "e1_bar", **THEME}, {"fromShotId": "s1", **THEME, "duck": False},
                                            {"sceneId": "e1_gone", **THEME}, {"fromShotId": "s1", "toShotId": "s0", **THEME}]}
    clips = [{"shotId": shot} for shot in ("s1", "s2", "s3", "s4")]
    score = clip_score(episode, clips)
    assert score["cues"] == [{**THEME, "firstClip": 2, "lastClip": 3}, {**THEME, "duck": False, "firstClip": 0, "lastClip": 0}]
    assert score["music"] == [False, False, False, True]
    assert score["skipped"] == ["Score cue 3: scene e1_gone has no shots in the episode",
                                "Score cue 4: the episode has no shot s0"]
    assert clip_score({"shots": _shots()}, clips) is None and clip_score({"score": []}, clips) is None


# The timeline -------------------------------------------------------------------------------------------------------

def _cue(first, last, **sound):
    return {**THEME, **sound, "firstClip": first, "lastClip": last}


def test_a_cue_spans_from_the_cut_before_its_first_shot_to_the_cut_after_its_last():
    spans = cuts(2, 3, 4, 5)
    first, second = plan_cues([_cue(0, 1), _cue(2, 3, file="mus-b.wav", volume=0.3)], spans)
    assert first == Bed("mus-theme.wav", 0.0, 5.0, 0.18, 1.5, 2.0)
    assert second == Bed("mus-b.wav", 5.0, 14.0, 0.3, 1.5, 2.0)
    assert plan_cues([_cue(1, 1)], spans) == [Bed("mus-theme.wav", 2.0, 5.0, 0.18, 1.5, 1.5)], "a fade is at most half"
    durations = [2.0, 2.0, 2.0]
    dissolve, join = join_spans(durations, hold_crossfade_output_seconds(durations))
    assert join == "dissolve" and plan_cues([_cue(1, 2)], dissolve)[0][1:3] == (2.3, 6.7), "the cut is mid-dissolve"
    with pytest.raises(ValueError):
        plan_cues([_cue(2, 4)], spans)


def test_a_file_shorter_than_its_cue_loops():
    spans = cuts(4, 6)
    assert plan_cues([_cue(0, 1)], spans, {"mus-theme.wav": 6.0})[0][6:] == (1.0, 2)
    assert plan_cues([_cue(0, 1)], spans, {"mus-theme.wav": 12.0})[0][6:] == (0.0, 1)


def test_close_lines_share_one_dip():
    lines = [(1.0, 2.0), (2.22, 3.0), (4.4, 5.0), (8.0, 9.0), (8.5, 8.7), (10.0, 10.0)]
    assert merge_spans(lines) == [(1.0, 5.0), (8.0, 9.0)], "gaps under 1.5 s are held; a later, longer gap rises"
    assert merge_spans(lines, gap=0.1) == [(1.0, 2.0), (2.22, 3.0), (4.4, 5.0), (8.0, 9.0)]
    assert merge_spans([]) == []


def test_the_dip_ramps_down_before_the_line_and_back_up_after_it():
    bed = Bed("mus-theme.wav", 2.0, 20.0, 0.18, 1.5, 2.0)
    factors = bed_dips(bed, [(5.0, 7.0)])
    assert factors == [Dip(round(1 - DUCKED, 4), 2.75, 5.6)], "times in the bed's own clock"
    gain = lambda moment: gain_at(factors, moment - bed.start)  # noqa: E731
    assert gain(4.0) == 1.0 and gain(5.0 - DUCK_ATTACK) == 1.0
    assert gain(5.0 - DUCK_ATTACK / 2) == pytest.approx((1 + DUCKED) / 2, abs=1e-3), "linear ramp"
    assert 20 * math.log10(gain(5.0)) == pytest.approx(-DUCK_DB, abs=0.01) and gain(7.0) == pytest.approx(gain(5.0))
    assert gain(7.0 + DUCK_RELEASE / 2) == pytest.approx((1 + DUCKED) / 2, abs=1e-3)
    assert gain(7.0 + DUCK_RELEASE) == pytest.approx(1.0) and gain(15.0) == 1.0
    assert bed_dips(bed, [(0.5, 1.0), (20.7, 22.0)]) == [], "lines whose ramps miss the bed"
    assert bed_dips(bed, [(5.0, 7.0)], duck_db=0) == [] and envelope([]) is None


def test_the_score_is_silent_under_a_shot_with_its_own_music_and_a_dip_there_stays_silent():
    bed = Bed("mus-theme.wav", 0.0, 20.0, 0.18, 1.5, 2.0)
    factors = bed_dips(bed, [(6.0, 7.0), (12.0, 13.0)], [(10.0, 14.0)])
    assert [factor.depth for factor in factors] == [round(1 - DUCKED, 4), round(1 - DUCKED, 4), 1.0]
    assert gain_at(factors, 9.0) == 1.0 and gain_at(factors, 10.0) == 0.0 and gain_at(factors, 12.5) == 0.0
    assert gain_at(factors, 10.0 - DUCK_ATTACK / 2) == pytest.approx(0.5) and gain_at(factors, 14.0 + DUCK_RELEASE) == 1.0


def test_the_envelope_is_one_ffmpeg_expression_of_the_beds_time():
    bed = Bed("mus-theme.wav", 2.0, 20.0, 0.18, 1.5, 2.0)
    expression = envelope(bed_dips(bed, [(2.1, 3.0)], [(10.0, 12.0)]))
    assert expression == ("(1-0.6452*clip((t+0.150)/0.250,0,1)*clip((1.600-t)/0.600,0,1))"
                          "*(1-1.0000*clip((t-7.750)/0.250,0,1)*clip((10.600-t)/0.600,0,1))")
    graph = bed_filter([bed], [2.0], has_audio=True, duration=20.0, envelopes=[expression])
    assert f"volume=0.3600,asetnsamples=n=240:p=0,volume='{expression}':eval=frame,adelay=2000|2000[bed1]" in graph
    level = bed_filter([bed._replace(fade_in=0.0)], [2.0], has_audio=True, duration=20.0, envelopes=[None])
    assert "afade=t=in" not in level and "eval=frame" not in level, "no fade-in, no envelope: nothing to add"


def test_speech_spans_are_the_subtitle_times_on_the_joined_timeline(tmp_path):
    lines = [[{"text": "Hello.", "start": 0.5, "end": 1.2}], None,
             [{"text": "Bye.", "start": 0.2, "end": 9.0}, {"text": "", "start": 0.0, "end": 0.1}]]
    spoken = speech_spans(cuts(2, 2, 2), [2, 2, 2], lines, workspace_dir=str(tmp_path))
    assert spoken == [pytest.approx((0.5, 1.2)), pytest.approx((4.2, 6.0))]


def test_the_note_counts_the_cues_or_says_why_there_are_none():
    base = {"loudness": {"applied": False, "reason": "x"}, "subtitles": {"written": False, "reason": "y"}}
    assert finishing_note({**base, "score": {"applied": True, "cues": [{}]}}).endswith("y. 1 score cue.")
    assert finishing_note({**base, "ambience": {"applied": True, "beds": [{}]},
                           "score": {"applied": False, "reason": "z"}}).endswith("y. 1 ambience bed. No score cues: z.")


# Takes and the series sound design ----------------------------------------------------------------------------------

def test_takes_do_not_depend_on_the_score_or_the_ambience_ducking():
    series = {"id": "show", "spokenLanguage": "English", "locations": [{"id": "street"}], "assets": {},
              "soundDesign": {"ambienceMode": "episode", "ambienceByLocation": {"street": {"file": "sfx-street.wav"}}}}
    shot = {"id": "s1", "order": 1, "locationId": "street", "productionMethod": "animation_2d", "attempts": [],
            "dialogueBeats": [{"id": "b0", "characterId": "", "text": "Hi."}]}
    series["assets"]["take"] = {"metadata": {"renderInputs": render_inputs(series, shot, {})}}
    shot.update(attempts=[{"id": "a1", "outputAssetIds": ["take"]}], approvedAttemptId="a1")
    episode = {"shots": [shot]}
    assert stale_shot_ids(series, episode, {}) == []
    scored = {**episode, "score": [{"fromShotId": "s1", **THEME}]}
    assert stale_shot_ids(series, scored, {}) == [], "a score is laid at assembly: no take is out of date"
    ducked = {**series, "soundDesign": {**series["soundDesign"], "ambienceDuckDb": 6}}
    assert stale_shot_ids(ducked, scored, {}) == [], "nor is ducking the beds"
    assert shot_sound_design({"stinger": 1, "ambienceDuckDb": 6}) == {"stinger": 1}, "shot mode too"


def test_ambience_ducking_is_a_number_of_db_on_the_beds():
    check_sound_design({"ambienceDuckDb": 0})
    for value in (-1, 30, True, "6"):
        with pytest.raises(ValueError, match="ambienceDuckDb"):
            check_sound_design({"ambienceDuckDb": value})
    assert ambience_duck_db({"ambienceDuckDb": 6}) == 6.0 and ambience_duck_db(None) == 0.0
    series = {"soundDesign": {"ambienceMode": "episode", "ambienceDuckDb": 6, "ambienceByLocation": {"street": {"file": "a.wav"}}}}
    episode = {"shots": [{"id": "s1", "locationId": "street"}, {"id": "s2"}]}
    assert clip_ambience(series, episode, [{"shotId": "s1"}, {"shotId": "s2"}]) == [
        {"locationId": "street", "file": "a.wav", "volume": 0.22, "duckDb": 6.0}, {"locationId": ""}]


# ffmpeg -------------------------------------------------------------------------------------------------------------

def _clip(path: Path, seconds: float, line: tuple[float, float] | None = None) -> None:
    """A test card whose sound is a 1 kHz "line" between ``line`` seconds, and digital silence around it."""
    sound = f"0.3*sin(2*PI*1000*t)*between(t,{line[0]},{line[1]})" if line else "0"
    completed = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24",
        "-f", "lavfi", "-i", f"aevalsrc='{sound}':s=48000:c=stereo", "-t", f"{seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-400:]


def _music(path: Path, seconds: float) -> None:
    """A 300 Hz tone: the score, told apart from the line by its pitch."""
    completed = subprocess.run(["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
                                "-i", f"aevalsrc=0.3*sin(2*PI*300*t):s=48000:d={seconds}", str(path)],
                               capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-400:]


def _samples(path: Path) -> np.ndarray:
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(command, capture_output=True, timeout=60, check=True).stdout, dtype=np.float32)


def _tone(samples: np.ndarray, start: float, end: float, hertz: float = 300.0) -> float:
    """Amplitude of one pitch in a stretch of the mix."""
    window = samples[int(start * 48000):int(end * 48000)]
    weights = np.hanning(len(window))
    spectrum = np.abs(np.fft.rfft(window * weights))
    bin_ = round(hertz * len(window) / 48000)
    return float(2 * spectrum[bin_ - 2:bin_ + 3].max() / weights.sum())


def _db(value: float, reference: float) -> float:
    return 20 * math.log10(max(value, 1e-9) / reference)


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_the_score_dips_under_a_line_and_comes_back_after_it(tmp_path):
    clip = tmp_path / "s0.mp4"
    _clip(clip, 6.0, line=(2.0, 3.0))
    _music(tmp_path / "mus-theme.wav", 8.0)
    score = {"cues": [_cue(0, 0, fadeIn=0.1, fadeOut=0.1, volume=1.0)], "music": [False]}
    lines = [[{"text": "A line.", "start": 2.0, "end": 3.0}]]
    spoken = _tone(_samples(clip), 2.05, 2.95, 1000)

    laid = lay_score(str(clip), [str(clip)], lines, score, workspace_dir=str(tmp_path), ffmpeg="ffmpeg", level=lambda _path: 1.0)

    assert laid["applied"] and laid["cues"][0]["dips"] == 1 and laid["cues"][0]["silences"] == 0, laid
    samples = _samples(clip)
    level = _tone(samples, 0.5, 1.6)
    assert level == pytest.approx(0.3, rel=0.1), "the music at its level before the line"
    assert _db(_tone(samples, 2.05, 2.95), level) == pytest.approx(-DUCK_DB, abs=0.75), "9 dB under the line"
    assert _tone(samples, 2.05, 2.95, 1000) == pytest.approx(spoken, rel=0.05), "the line itself is untouched"
    assert abs(_db(_tone(samples, 3.7, 5.7), level)) < 0.5, "back once the line is over"
    assert not list(tmp_path.glob("*-tmp*"))
    undocked = {"cues": [_cue(0, 0, fadeIn=0.1, fadeOut=0.1, volume=1.0, duck=False)], "music": [False]}
    _clip(clip, 6.0, line=(2.0, 3.0))
    assert lay_score(str(clip), [str(clip)], lines, undocked, workspace_dir=str(tmp_path), ffmpeg="ffmpeg",
                     level=lambda _path: 1.0)["cues"][0]["dips"] == 0
    assert abs(_db(_tone(_samples(clip), 2.05, 2.95), level)) < 0.5, "duck: false plays level"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_the_assembly_lays_a_looping_score_silent_under_a_shot_with_its_own_music(tmp_path):
    from services.core_series_assembly import concatenate_clips

    clips = [tmp_path / "s0.mp4", tmp_path / "s1.mp4"]
    _clip(clips[0], 3.0, line=(1.0, 2.0))
    _clip(clips[1], 3.0)
    # 3.2 s loops with 0.8 s seams (a whole number of cycles apart, so in phase), at 1.6-2.4 and 4.0-4.8 s.
    _music(tmp_path / "mus-theme.wav", 3.2)
    joined = tmp_path / "episode.mp4"
    assert concatenate_clips([str(clip) for clip in clips], str(joined))
    episode = {"shots": [{"id": "s0", "order": 1, "sceneId": "x"},
                         {"id": "s1", "order": 2, "sceneId": "x", "layout2d": {"music": {"file": "mus-own.wav"}}}],
               "score": [{"sceneId": "x", **THEME, "volume": 0.5, "fadeIn": 0.1, "fadeOut": 0.1}]}
    score = clip_score(episode, [{"shotId": "s0"}, {"shotId": "s1"}])

    finished = finish_episode(str(joined), [str(clip) for clip in clips],
                              [[{"text": "A line.", "start": 1.0, "end": 2.0}], []], workspace_dir=str(tmp_path), score=score)

    laid = finished["score"]
    assert laid["applied"] and laid["join"] == "dissolve", laid
    cue = laid["cues"][0]
    assert (cue["start"], cue["dips"], cue["silences"]) == (0.0, 1, 1) and cue["end"] == pytest.approx(6.6, abs=0.05), cue
    assert (cue["seam"], cue["passes"]) == (0.8, 3), "a 3.2 s file loops under a 6.6 s cue"
    assert finished["loudness"]["applied"], "the score is laid before the loudness pass"
    assert "1 score cue." in finishing_note(finished)
    samples = _samples(joined)
    level = _tone(samples, 0.2, 0.9)
    assert level > 0.01
    assert _db(_tone(samples, 1.05, 1.55), level) == pytest.approx(-DUCK_DB, abs=1.0), "under the line"
    assert abs(_db(_tone(samples, 2.62, 2.84), level)) < 1.0, "back between the line and the next shot"
    assert _tone(samples, 3.15, 6.5) < level / 300, "silent under the shot with its own music (the clip span)"
