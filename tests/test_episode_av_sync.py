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
