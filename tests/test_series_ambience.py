"""Episode ambience: one continuous bed per run of shots in a location, laid by the assembly instead of every shot."""
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from services.episode_finishing import finish_episode, finishing_note, join_spans, lay_ambience
from services.mix_concat import hold_crossfade_output_seconds
from services.series_ambience import (
    Bed,
    bed_filter,
    check_sound_design,
    clip_ambience,
    plan_beds,
    shot_sound_design,
)
from services.series_library import normalize_series_project
from services.series_shot_plan import sound_tracks
from services.series_take_inputs import render_inputs

HAS_FFMPEG = shutil.which("ffmpeg") is not None and shutil.which("ffprobe") is not None
STREET = {"locationId": "street", "file": "sfx-street.wav", "volume": 0.3}
PARK = {"locationId": "park", "file": "sfx-park.wav", "volume": 0.2}
VOID = {"locationId": "void"}


def cuts(*seconds):
    """Hard-cut spans for clips of these lengths."""
    spans, start = [], 0.0
    for length in seconds:
        spans.append((start, start + length))
        start += length
    return spans


def test_a_run_of_shots_in_one_location_gets_one_bed_faded_inside_its_edges():
    beds = plan_beds([STREET, STREET, VOID], cuts(2, 3, 2))
    assert beds == [Bed("sfx-street.wav", 0.0, 5.0, 0.3, 0.8, 0.8, 0.0, 1)], "the dark title card gets nothing"


def test_adjacent_locations_crossfade_centred_on_the_cut():
    street, park = plan_beds([STREET, PARK, PARK], cuts(4, 2, 3))
    assert street == Bed("sfx-street.wav", 0.0, 4.4, 0.3, 0.8, 0.8)
    assert park == Bed("sfx-park.wav", 3.6, 9.0, 0.2, 0.8, 0.8)


def test_a_dissolve_puts_the_cut_in_the_middle_of_the_overlap():
    durations = [2.0, 2.0, 2.0]
    spans, join = join_spans(durations, hold_crossfade_output_seconds(durations))
    assert join == "dissolve" and spans[1] == pytest.approx((2.1, 4.6)), "a clip plays on into its held tail"
    street, park = plan_beds([STREET, PARK, PARK], spans)
    assert (street.start, street.end) == (0.0, 2.7) and (park.start, park.end) == (1.9, 6.7), "cut at 2.3 s, mid-dissolve"
    assert join_spans(durations, 6.02) == ([(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)], "cut"), "the hard-concat fallback"


def test_a_file_shorter_than_its_bed_loops_with_a_crossfaded_seam():
    shots, spans = [STREET, STREET], cuts(4, 6)
    assert plan_beds(shots, spans, {"sfx-street.wav": 6.0})[0][6:] == (1.0, 2), "1 s seams, 5 s of new sound a pass"
    assert plan_beds(shots, spans, {"sfx-street.wav": 3.0})[0][6:] == (0.75, 5), "a short file keeps a quarter for the seam"
    assert plan_beds(shots, spans, {"sfx-street.wav": 10.0})[0][6:] == (0.0, 1)
    assert plan_beds(shots, spans, {})[0][6:] == (0.0, 1), "an unknown length plays once"


def test_short_and_single_shot_runs_keep_their_fades_inside_the_bed():
    first, park, second = plan_beds([STREET, PARK, STREET], cuts(4, 0.5, 4.5))
    assert park == Bed("sfx-park.wav", 3.75, 4.75, 0.2, 0.5, 0.5), "a crossfade is never longer than either run"
    assert (first.end, first.fade_out, second.start, second.fade_in) == (4.25, 0.5, 4.25, 0.5)
    assert (first.fade_in, second.fade_out) == (0.8, 0.8), "a location seen again is a new run"
    assert plan_beds([STREET], cuts(1.0)) == [Bed("sfx-street.wav", 0.0, 1.0, 0.3, 0.5, 0.5)]


def test_shots_without_ambience_or_location_leave_a_gap_the_beds_fade_out_into():
    beds = plan_beds([STREET, VOID, {"locationId": ""}, {}, STREET], cuts(3, 2, 1, 1, 3))
    assert [(bed.start, bed.end, bed.fade_in, bed.fade_out) for bed in beds] == [(0.0, 3.0, 0.8, 0.8), (7.0, 10.0, 0.8, 0.8)]
    assert plan_beds([VOID, {}], cuts(2, 2)) == []
    assert plan_beds([], []) == []
    with pytest.raises(ValueError):
        plan_beds([STREET], [])


def _series(**design):
    return {"id": "show", "spokenLanguage": "English",
            "locations": [{"id": "street", "name": "Street"}, {"id": "void", "name": "Void"}],
            "characters": [{"id": "ana", "voiceProfile": {"characterKitRef": {"id": "kit-ana", "workspace": "ws"}}}],
            "soundDesign": {"stinger": {"file": "sfx-sting.wav", "volume": 0.6},
                            "ambienceByLocation": {"street": {"file": "sfx-street.wav", "volume": 0.3}}, **design}}


SHOT = {"id": "s1", "order": 1, "locationId": "street", "productionMethod": "animation_2d", "visibleCharacterIds": ["ana"],
        "dialogueBeats": [{"id": "s1_b0", "characterId": "ana", "text": "Hi."}], "layout2d": {"framing": "medium"}}
KITS = {"kit-ana": {"id": "kit-ana", "voice": {"model": "qwen3_tts_customvoice", "voiceId": "ryan"}, "updatedAt": "x"}}


def test_clips_carry_their_location_and_bed_in_episode_mode_only():
    episode = {"shots": [{"id": "s1", "locationId": "street"}, {"id": "s2", "locationId": "void"}, {"id": "s3"},
                         {"id": "s4", "locationId": "loud"}, {"id": "s5", "locationId": "bare"}]}
    clips = [{"shotId": f"s{index}"} for index in (2, 1, 3, 4, 5)]
    assert clip_ambience(_series(), episode, clips) is None, "shot mode: the shots mix it"
    series = _series(ambienceMode="episode")
    series["soundDesign"]["ambienceByLocation"].update(loud={"file": " sfx-loud.wav ", "volume": 9}, bare={"volume": 0.5})
    assert clip_ambience(series, episode, clips) == [
        {"locationId": "void"}, {"locationId": "street", "file": "sfx-street.wav", "volume": 0.3}, {"locationId": ""},
        {"locationId": "loud", "file": "sfx-loud.wav", "volume": 2.0}, {"locationId": "bare"}]
    series["soundDesign"]["ambienceByLocation"]["street"] = {"file": "sfx-street.wav", "volume": True}
    assert clip_ambience(series, episode, clips)[1]["volume"] == 0.22


def test_episode_mode_shots_mix_no_ambience_but_keep_the_stinger_and_music():
    shot = {"locationId": "street", "layout2d": {"music": {"file": "mus-theme.wav"}}}
    assert [track["id"] for track in sound_tracks(_series(), shot, True)] == ["ambience", "stinger", "music"]
    assert [track["id"] for track in sound_tracks(_series(ambienceMode="shot"), shot, True)] == ["ambience", "stinger", "music"]
    assert [track["id"] for track in sound_tracks(_series(ambienceMode="episode"), shot, True)] == ["stinger", "music"]


def test_shot_mode_takes_keep_the_digest_they_were_rendered_with():
    # Digests of takes rendered before ambienceMode existed: a series that does not opt in renders nothing again.
    assert render_inputs(_series(), SHOT, KITS) == "f2279a220a972210"
    assert render_inputs(_series(ambienceMode="shot"), SHOT, KITS) == "f2279a220a972210"
    bare = _series()
    del bare["soundDesign"]
    assert render_inputs(bare, SHOT, KITS) == "624d477c11e50c19"
    louder = _series()
    louder["soundDesign"]["ambienceByLocation"]["street"]["volume"] = 0.5
    assert render_inputs(louder, SHOT, KITS) != render_inputs(_series(), SHOT, KITS), "shot mode: a level is in every take"


def test_episode_mode_takes_do_not_depend_on_the_beds():
    episode = render_inputs(_series(ambienceMode="episode"), SHOT, KITS)
    assert episode != render_inputs(_series(), SHOT, KITS), "switching mode renders every shot once"
    tuned = _series(ambienceMode="episode")
    tuned["soundDesign"]["ambienceByLocation"] = {"street": {"file": "sfx-rain.wav", "volume": 0.1}, "void": {"file": "x.wav"}}
    assert render_inputs(tuned, SHOT, KITS) == episode, "new beds or levels need only a new cut"
    del tuned["soundDesign"]["ambienceByLocation"]
    assert render_inputs(tuned, SHOT, KITS) == episode
    tuned["soundDesign"]["stinger"]["volume"] = 0.9
    assert render_inputs(tuned, SHOT, KITS) != episode, "the stinger is still in the shot"
    assert shot_sound_design({"ambienceMode": "episode", "stinger": 1, "ambienceByLocation": {}}) == {"stinger": 1}
    assert shot_sound_design(None) is None


def test_the_mode_is_shot_or_episode():
    check_sound_design({"ambienceMode": "episode"})
    check_sound_design(None)
    with pytest.raises(ValueError, match="ambienceMode"):
        check_sound_design({"ambienceMode": "scene"})
    with pytest.raises(ValueError, match="ambienceMode"):
        normalize_series_project({"id": "show", "soundDesign": {"ambienceMode": "Episode"}}, "show", "default")
    saved = normalize_series_project({"id": "show", "soundDesign": {"ambienceMode": "episode"}}, "show", "default")
    assert saved["soundDesign"] == {"ambienceMode": "episode"}


def test_the_filter_loops_fades_and_places_each_bed():
    beds = [Bed("a.wav", 1.5, 6.5, 0.3, 0.8, 0.4, 1.0, 2), Bed("b.wav", 6.1, 9.0, 1.5, 0.4, 0.8)]
    graph = bed_filter(beds, [0.5, 4.0], has_audio=True, duration=9.0)
    looped, straight = graph.split(";[bed1]")[0], graph.split("[2:a]", 1)[1]
    assert "atrim=start=1.000" in looped and "acrossfade=d=1.000:c1=qsin:c2=qsin,aloop=loop=-1" in looped
    assert "atrim=end=5.000,afade=t=in:d=0.800:curve=qsin,afade=t=out:st=4.600:d=0.400" in looped
    assert "volume=0.1500,adelay=1500|1500[bed1]" in graph
    assert "aloop" not in straight and "volume=2.0000,adelay=6100|6100[bed2]" in straight, "a balanced level stays under 2"
    assert graph.startswith("[0:a]") and "[main][bed1][bed2]amix=inputs=3:normalize=0:duration=first,alimiter" in graph
    silent = bed_filter(beds[1:], [1.0], has_audio=False, duration=9.0)
    assert silent.startswith("anullsrc=channel_layout=stereo:sample_rate=48000:d=9.000"), "a mute cut still gets its beds"


def test_the_note_counts_the_beds_or_says_why_there_are_none():
    base = {"loudness": {"applied": False, "reason": "x"}, "subtitles": {"written": False, "reason": "y"}}
    assert finishing_note(base) == "Loudness unchanged: x. No subtitles: y."
    assert finishing_note({**base, "ambience": {"applied": True, "beds": [{}, {}]}}).endswith("y. 2 ambience beds.")
    assert finishing_note({**base, "ambience": {"applied": False, "reason": "z"}}).endswith("y. No ambience beds: z.")


def _clip(path: Path, seconds: float) -> None:
    """A test card with digital silence, so only the bed is heard."""
    completed = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=24",
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000", "-t", f"{seconds}",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-400:]


def _chirp(path: Path, seconds: float) -> None:
    """A sweep from 200 Hz rising 200 Hz a second: where in the file a moment comes from shows in its pitch."""
    completed = subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-f", "lavfi",
        "-i", f"aevalsrc=0.3*sin(2*PI*(200*t+100*t*t)):s=48000:d={seconds}", str(path),
    ], capture_output=True, text=True, timeout=60)
    assert completed.returncode == 0, completed.stderr[-400:]


def _samples(path: Path) -> np.ndarray:
    command = ["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", "48000", "-f", "f32le", "-"]
    raw = subprocess.run(command, capture_output=True, timeout=60, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def _rms(samples: np.ndarray, start: float, end: float) -> float:
    return float(np.sqrt(np.mean(samples[int(start * 48000):int(end * 48000)] ** 2)))


def _pitch(samples: np.ndarray, start: float, end: float) -> float:
    window = samples[int(start * 48000):int(end * 48000)]
    spectrum = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    return float(np.argmax(spectrum) * 48000 / len(window))


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_the_bed_plays_on_across_a_dissolve_and_stops_before_a_shot_without_ambience(tmp_path):
    from services.core_series_assembly import concatenate_clips

    clips = [tmp_path / f"s{index}.mp4" for index in range(3)]
    for clip in clips:
        _clip(clip, 2.0)
    _chirp(tmp_path / "sfx-street.wav", 10.0)
    joined = tmp_path / "episode.mp4"
    assert concatenate_clips([str(clip) for clip in clips], str(joined))
    street = {"locationId": "street", "file": "sfx-street.wav", "volume": 0.5}

    finished = finish_episode(str(joined), [str(clip) for clip in clips], [None] * 3, workspace_dir=str(tmp_path),
                              ambience=[street, street, VOID])

    ambience = finished["ambience"]
    assert ambience["applied"] and ambience["join"] == "dissolve", ambience
    assert [(bed["start"], bed["end"]) for bed in ambience["beds"]] == [(0.0, 4.4)], "s0 and s1 are one run; s2 is dark"
    assert finished["loudness"]["applied"], "the beds are laid before the loudness pass"
    samples = _samples(joined)
    assert len(samples) / 48000 == pytest.approx(hold_crossfade_output_seconds([2.0] * 3), abs=0.05)
    # The cut is at 2.3 s. A bed that restarted there would drop back towards 200 Hz.
    assert _pitch(samples, 2.0, 2.2) == pytest.approx(200 + 200 * 2.1, abs=30)
    assert _pitch(samples, 2.4, 2.6) == pytest.approx(200 + 200 * 2.5, abs=30)
    level = np.median([_rms(samples, at, at + 0.1) for at in np.arange(1.0, 3.5, 0.1)])
    assert all(abs(20 * math.log10(_rms(samples, at, at + 0.1) / level)) < 1.0 for at in np.arange(1.0, 3.5, 0.1)), "no dip"
    assert _rms(samples, 4.6, 6.6) < 1e-3, "the shot without ambience gets nothing"
    assert not list(tmp_path.glob("*ambience-tmp*"))


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg/ffprobe required")
def test_a_short_file_loops_without_a_gap_and_a_missing_one_is_reported(tmp_path):
    clip = tmp_path / "s0.mp4"
    _clip(clip, 6.0)
    _chirp(tmp_path / "sfx-short.wav", 1.5)
    short = {"locationId": "street", "file": "sfx-short.wav", "volume": 1.0}

    laid = lay_ambience(str(clip), [str(clip)], [short], workspace_dir=str(tmp_path), ffmpeg="ffmpeg", level=lambda _path: 1.0)

    assert laid["applied"] and laid["beds"][0]["seam"] == 0.375 and laid["beds"][0]["passes"] == 6, laid
    samples = _samples(clip)
    levels = [_rms(samples, at, at + 0.1) for at in np.arange(1.0, 5.0, 0.1)]
    assert min(levels) > 0.7 * float(np.median(levels)), "the seams are crossfaded, never silent"
    assert _rms(samples, 1.0, 5.0) == pytest.approx(0.3 / math.sqrt(2), rel=0.15)
    missing = lay_ambience(str(clip), [str(clip)], [{"locationId": "park", "file": "sfx-gone.wav", "volume": 0.2}],
                           workspace_dir=str(tmp_path), ffmpeg="ffmpeg")
    assert missing == {"applied": False, "reason": "Ambience files not found in the workspace: sfx-gone.wav",
                       "mode": "episode", "missing": ["sfx-gone.wav"]}
