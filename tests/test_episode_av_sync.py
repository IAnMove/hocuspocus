import shutil
import subprocess

import numpy as np
import pytest

from services import episode_av_sync as sync
from services.episode_finishing import finishing_note, join_spans
from services.mix_concat import concat_with_tail_hold_and_crossfade, probe_duration_seconds


def _bursts(seconds: float, seed: int) -> np.ndarray:
    """An envelope with syllable-like bursts at irregular places, as a take's speech has."""
    rng = np.random.default_rng(seed)
    env = np.zeros(int(seconds / sync.HOP))
    for start in rng.choice(len(env) - 30, size=max(3, len(env) // 40), replace=False):
        env[start:start + rng.integers(8, 30)] = rng.uniform(0.5, 1.5)
    return env


def test_take_lag_finds_where_the_sound_really_is():
    take = _bursts(3.0, 1)
    episode = np.zeros(int(20 / sync.HOP))
    at = int(round(7.12 / sync.HOP))
    episode[at:at + len(take)] += take
    lag, score = sync.take_lag(take, episode, 7.0)
    assert lag == pytest.approx(0.12, abs=sync.HOP) and score > 0.9


def test_take_lag_follows_a_drift_larger_than_its_search():
    take = _bursts(2.0, 2)
    episode = np.zeros(int(30 / sync.HOP))
    at = int(round(12.4 / sync.HOP))
    episode[at:at + len(take)] += take
    found = sync.take_lag(take, episode, 10.0)
    assert found is None or abs(found[0] - 2.4) > sync.HOP  # out of reach from the plan alone
    lag, _score = sync.take_lag(take, episode, 10.0, around=2.3)
    assert lag == pytest.approx(2.4, abs=sync.HOP)


def test_silent_or_short_takes_are_not_placed():
    episode = _bursts(10.0, 3)
    assert sync.take_lag(np.zeros(400), episode, 1.0) is None
    assert sync.take_lag(_bursts(0.2, 4), episode, 1.0) is None


def test_correlations_are_pearson_per_stretch():
    rng = np.random.default_rng(5)
    window, probe = rng.random(300), rng.random(40)
    expected = [np.corrcoef(window[i:i + 40], probe)[0, 1] for i in range(261)]
    assert np.allclose(sync._correlations(window, probe), expected)


def test_the_assembly_message_says_whether_the_sound_is_in_sync():
    base = {"loudness": {"applied": False, "reason": "x"}, "subtitles": {"written": False, "reason": "y"}}
    ok = {"checked": True, "inSync": True, "placed": 12, "maxLagMs": 8, "late": []}
    late = {"checked": True, "inSync": False, "placed": 12, "maxLagMs": 640,
            "late": [{"index": 4, "lagMs": 60}, {"index": 11, "lagMs": 640}]}
    assert "Sound in sync on 12 clips (worst 8 ms)." in finishing_note({**base, "sync": ok})
    assert "Sound out of sync on 2 of 12 clips, from clip 5 (worst 640 ms)." in finishing_note({**base, "sync": late})
    assert "sync" not in finishing_note(base).lower()
    longer = {"checked": True, "inSync": False, "placed": 0, "maxLagMs": 0, "late": [], "lengthGapMs": 2000}
    assert finishing_note({**base, "sync": longer}).endswith("The sound runs 2000 ms longer than the pictures.")


def _talking_clip(path, seconds: float, index: int) -> None:
    # Bursts of tone at irregular moments, different in every clip: a take's lines, as far as an envelope can tell.
    gate = f"gt(sin(2*PI*{1.3 + 0.37 * index}*t)+sin(2*PI*{2.9 + 0.21 * index}*t),0.6)"
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=gray:s=160x120:r=24:d={seconds}",
           "-f", "lavfi", "-i", f"aevalsrc=exprs='0.5*sin(2*PI*{300 + 40 * index}*t)*{gate}':s=48000:d={seconds}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", f"{seconds}", str(path)]
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
def test_a_joined_episode_is_in_sync_and_a_drifting_one_is_caught(tmp_path):
    lengths = [2.3, 1.9, 2.7, 2.1, 2.5, 1.8, 2.4, 2.2]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"take{index}.mp4"
        _talking_clip(path, seconds, index)
        clips.append(str(path))
    joined = tmp_path / "episode.mp4"
    assert concat_with_tail_hold_and_crossfade(clips, str(joined)) is True
    spans, _join = join_spans([probe_duration_seconds(clip) for clip in clips], probe_duration_seconds(str(joined)))
    starts = [start for start, _end in spans]

    report = sync.check_sync(str(joined), clips, starts, ffmpeg="ffmpeg")
    assert report["checked"] and report["inSync"], report
    assert report["placed"] >= 6 and report["maxLagMs"] <= 20

    # Pictures planned 40 ms later at every join, as a drifting join plays them: the sound runs ahead more and more.
    drifting = [start + 0.04 * index for index, start in enumerate(starts)]
    caught = sync.check_sync(str(joined), clips, drifting, ffmpeg="ffmpeg")
    assert not caught["inSync"]
    late = {item["index"]: item["lagMs"] for item in caught["late"]}
    assert 7 in late and late[7] == pytest.approx(-280, abs=20)


def _flash_clip(path, seconds: float, index: int, flash: bool = True) -> None:
    """A coloured shot with a white flash at the first frames and a beep pattern of its own."""
    colors = ("0x2244aa", "0xaa4422", "0x228844", "0x442288", "0x888822", "0x228888")
    gate = f"gt(sin(2*PI*{1.3 + 0.37 * index}*t)+sin(2*PI*{2.9 + 0.21 * index}*t),0.4)"
    graph = f"color=c={colors[index]}:s=160x120:r=24:d={seconds}"
    graph += ",fade=t=in:st=0:d=0.08:color=white" if flash else ""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", graph,
           "-f", "lavfi", "-i", f"aevalsrc=exprs='0.6*sin(2*PI*{440 + 70 * index}*t)*{gate}':s=48000:d={seconds}",
           "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)]
    assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0, path


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
def test_a_dissolve_keeps_each_beep_with_its_flash(tmp_path):
    """Five shots, one of each join: the fades do not overlap and each dissolve shortens the cut, and the sound stays."""
    from services.core_series_assembly import concatenate_clips
    from services.episode_finishing import check_episode_sync
    from services.series_transitions import output_seconds

    lengths = [2.0, 2.0, 2.0, 2.0, 2.0]
    transitions = [None, {"kind": "fade_black", "seconds": 0.4}, {"kind": "dissolve", "seconds": 0.5},
                   {"kind": "dip_white", "seconds": 0.4}, {"kind": "dissolve", "seconds": 0.5}]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"take{index}.mp4"
        _flash_clip(path, seconds, index)
        clips.append(str(path))
    joined = tmp_path / "episode.mp4"
    assert concatenate_clips(clips, str(joined), transitions=transitions) is True
    probed = [probe_duration_seconds(clip) for clip in clips]
    assert probe_duration_seconds(str(joined)) == pytest.approx(output_seconds(probed, transitions), abs=0.15)
    report = check_episode_sync(str(joined), clips, ffmpeg="ffmpeg", transitions=transitions)
    assert report["checked"] and report["inSync"], report
    assert report["placed"] == 5 and report["maxLagMs"] <= 45


FRAME = 1 / 24


def _frame_colors(path) -> np.ndarray:
    """Each frame's mean colour (24 fps)."""
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", "scale=4:4", "-f", "rawvideo",
                          "-pix_fmt", "rgb24", "-"], capture_output=True, timeout=60).stdout
    return np.frombuffer(raw, dtype=np.uint8).reshape(-1, 16, 3).mean(axis=1)


def _seen_dissolves(colors: np.ndarray, spans) -> list[tuple[float, float]]:
    """Where each join's dissolve really runs in the pictures (seconds): the line through the frames that mix the
    outgoing clip's colour with the incoming one's, from where it leaves 0 to where it reaches 1."""
    pure = [colors[int((start + end) / 2 / FRAME)] for start, end in spans]
    seen = []
    for index in range(1, len(spans)):
        axis = pure[index] - pure[index - 1]
        mix = (colors - pure[index - 1]) @ axis / (axis @ axis)
        frames = [i for i in range(int((spans[index][0] - 0.3) / FRAME), int((spans[index - 1][1] + 0.3) / FRAME))
                  if 0.05 < mix[i] < 0.95]
        slope, start = np.polyfit(mix[frames], np.array(frames) * FRAME, 1)
        seen.append((start, start + slope))
    return seen


def _decoded_audio_seconds(path) -> float:
    return len(sync.decode(str(path), "ffmpeg")) / sync.RATE


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
def test_cuts_stay_soft_joins_beside_a_dissolve(tmp_path):
    """A cut, a dissolve and a cut: the pictures and the sound are where the finishing timeline puts them."""
    from services.core_series_assembly import concatenate_clips
    from services.episode_finishing import check_episode_sync, join_spans
    from services.series_transitions import output_seconds

    lengths = [2.0, 1.6, 2.4, 1.8]
    transitions = [None, None, {"kind": "dissolve", "seconds": 0.5}, {"kind": "cut"}]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"take{index}.mp4"
        _flash_clip(path, seconds, index, flash=False)
        clips.append(str(path))
    joined = tmp_path / "episode.mp4"
    assert concatenate_clips(clips, str(joined), transitions=transitions) is True
    probed = [probe_duration_seconds(clip) for clip in clips]
    spans, join = join_spans(probed, probe_duration_seconds(str(joined)), transitions)
    assert join == "transition"
    # Each cut holds the outgoing frame 0.5 s and dissolves 0.4 s, as without transitions; the dissolve overlaps 0.5 s.
    assert [value for span in spans for value in span] == pytest.approx(
        [0.0, 2.5, 2.1, 3.7, 3.2, 6.1, 5.7, 8.0], abs=0.03)
    colors = _frame_colors(joined)
    assert len(colors) * FRAME == pytest.approx(output_seconds(probed, transitions), abs=FRAME)
    assert _decoded_audio_seconds(joined) == pytest.approx(len(colors) * FRAME, abs=FRAME)
    for (start, end), (planned_start, _planned_end), (_before_start, before_end) in zip(
            _seen_dissolves(colors, spans), spans[1:], spans):
        assert start == pytest.approx(planned_start, abs=FRAME + 1e-6)
        assert end == pytest.approx(before_end, abs=FRAME + 1e-6)
    report = check_episode_sync(str(joined), clips, ffmpeg="ffmpeg", transitions=transitions)
    assert report["checked"] and report["inSync"], report
    assert report["placed"] == 4 and report["maxLagMs"] <= 42


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
def test_sound_longer_than_the_pictures_is_out_of_sync_even_when_no_take_can_be_placed(tmp_path):
    """Steady tones cannot be placed, so only the sound's length shows that a pass moved it."""
    clips = []
    for index in range(3):
        path = tmp_path / f"take{index}.mp4"
        cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=160x120:r=24:d=2", "-f", "lavfi",
               "-i", f"sine=f={300 + 40 * index}:sample_rate=48000:d=2", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", "-c:a", "aac", "-t", "2", str(path)]
        assert subprocess.run(cmd, capture_output=True, timeout=30).returncode == 0
        clips.append(str(path))
    joined = tmp_path / "episode.mp4"
    assert concat_with_tail_hold_and_crossfade(clips, str(joined)) is True
    spans, _join = join_spans([probe_duration_seconds(clip) for clip in clips], probe_duration_seconds(str(joined)))
    starts = [start for start, _end in spans]
    report = sync.check_sync(str(joined), clips, starts, ffmpeg="ffmpeg")
    assert report["inSync"] and report["placed"] == 0 and abs(report["lengthGapMs"]) <= 45, report
    padded = tmp_path / "padded.mp4"
    assert subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(joined), "-c:v", "copy", "-af", "apad=pad_dur=0.8",
                           "-c:a", "aac", str(padded)], capture_output=True, timeout=30).returncode == 0
    caught = sync.check_sync(str(padded), clips, starts, ffmpeg="ffmpeg")
    assert not caught["inSync"] and caught["placed"] == 0 and caught["lengthGapMs"] == pytest.approx(800, abs=45)
    assert sync.sync_note(caught).startswith("The sound runs 8")


@pytest.mark.skipif(shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None, reason="ffmpeg is required")
@pytest.mark.parametrize("transitions", [None, [None, None, {"kind": "dissolve", "seconds": 0.5}, None,
                                                {"kind": "fade_black", "seconds": 0.4}, None]])
def test_hearing_keeps_each_takes_sound_on_its_pictures(tmp_path, transitions):
    """Six shots, one muffled and one ringing, through the real join and finishing: the hearing step cuts the joined
    sound at the clip starts, so the sound keeps its length and every take's sound starts with its pictures."""
    from services.core_series_assembly import concatenate_clips
    from services.episode_finishing import finish_episode

    lengths = [2.0, 1.6, 2.4, 1.8, 2.2, 1.9]
    clips = []
    for index, seconds in enumerate(lengths):
        path = tmp_path / f"take{index}.mp4"
        _flash_clip(path, seconds, index, flash=False)
        clips.append(str(path))
    joined = tmp_path / "episode.mp4"
    assert concatenate_clips(clips, str(joined), transitions=transitions) is True
    sound = _decoded_audio_seconds(joined)
    probed = [probe_duration_seconds(clip) for clip in clips]
    spans, _join = join_spans(probed, probe_duration_seconds(str(joined)), transitions)
    hearing = ["normal", "normal", "muffled", "normal", "ringing", "normal"]
    finished = finish_episode(str(joined), clips, [None] * len(clips), workspace_dir=str(tmp_path), hearing=hearing,
                              transitions=transitions)
    assert finished["hearing"]["applied"] is True, finished["hearing"]
    # The sound keeps its length (it grew 0.4 s a join when the clips' overlapping spans were cut and joined), which is
    # the pictures' to within their last frame on the 24 fps grid.
    assert _decoded_audio_seconds(joined) == pytest.approx(sound, abs=0.025)
    colors = _frame_colors(joined)
    assert _decoded_audio_seconds(joined) == pytest.approx(len(colors) * FRAME, abs=2 * FRAME)
    assert finished["sync"]["inSync"], finished["sync"]
    # Where each take's pictures really start: the dissolves' ramps, and the darkest frame of the fade to black.
    seen = [0.0, *(start for start, _end in _seen_dissolves(colors, spans))]
    if transitions:
        dip = spans[4][0]
        frames = range(int((dip - 0.3) / FRAME), int((dip + 0.3) / FRAME))
        assert min(frames, key=lambda index: colors[index].sum()) * FRAME == pytest.approx(dip, abs=FRAME)
        seen[4] = dip
    assert seen == pytest.approx([start for start, _end in spans], abs=FRAME)
    report = sync.check_sync(str(joined), clips, seen, ffmpeg="ffmpeg", tolerance=FRAME)
    assert report["placed"] == len(clips) and report["inSync"], report
