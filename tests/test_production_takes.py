"""Lip-sync take cap: flat correlation stops early, four recorded takes do not auto-shoot."""
from __future__ import annotations

from services.music_production import Production, status_summary
from services.production_takes import (
    RECORDED_CAP, another_take, note_seconds, pending_windows, recorded_takes, take_settled,
)

WINDOW = {"key": "a", "kind": "h3", "i": 0, "t0": 1.0, "t1": 4.0, "sing": True}


def test_take_settled_stops_when_r_does_not_beat_the_best():
    assert take_settled({"verdict": "retake", "best_r": 0.04}, None) is False
    assert take_settled({"verdict": "retake", "best_r": 0.17}, 0.04) is False
    assert take_settled({"verdict": "retake", "best_r": 0.06}, 0.17) is True
    assert take_settled({"verdict": "ok", "best_r": 0.5}, 0.17) is True
    assert take_settled({"verdict": "retake"}, 0.17) is False          # a failure to measure is not a flat r
    assert another_take(False, 3, 8, False) is True
    assert another_take(False, RECORDED_CAP, 8, False) is False
    assert another_take(False, RECORDED_CAP, 8, True) is True
    assert another_take(True, 1, 8, True) is False
    assert another_take(False, 2, 2, True) is False


def test_recorded_takes_prefer_the_counter_and_otherwise_count_the_log():
    assert recorded_takes({"clip_takes": {"a": 4}, "log": ["clip a take 1: x"]}, "a") == 4
    state = {"log": [f"clip a take {n}: failed (oom)" for n in range(1, 5)]}
    assert recorded_takes(state, "a") == 4
    windows = [WINDOW]
    assert pending_windows(windows, {"frames": {"a": "f.png"}, **state}, ()) == []
    assert pending_windows(windows, {"frames": {"a": "f.png"}, "clip_takes": {"a": 4}}, ("a",)) == windows


def test_note_seconds_accumulates_per_shot():
    state: dict = {}
    note_seconds(state, [WINDOW], 1.25)
    note_seconds(state, [WINDOW], 0.25)
    assert state["clip_seconds"] == {"a": 1.5}


def _measure(values):
    seen: list[float] = []
    stream = iter(values)

    def measure(*_args, **_kwargs):
        score = next(stream)
        seen.append(score)
        return {"verdict": "retake", "best_r": score}

    return measure, seen, stream


def _runner(tmp_path, monkeypatch, outputs, measure):
    (tmp_path / "s.score.json").write_text('{"lines": [], "vocals_file": "v.wav"}')
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"a": "f.png"}, "log": []}
    production.upload = lambda name: (name, "/u/" + name)
    calls: list[tuple] = []
    production.clip_job = lambda spec, window, seed, take: calls.append((seed, take)) or f"job-{seed}"
    files = iter(outputs)

    def wait(jobs):
        production.failures = {}
        return {key: next(files) for key in jobs}

    production.wait = wait
    monkeypatch.setattr("services.music_production.lipsync_qa.measure", measure)
    return production, calls, files


def _clock(monkeypatch):
    ticks = {"n": 0.0}

    def perf():
        ticks["n"] += 1.0
        return ticks["n"]

    monkeypatch.setattr("services.music_production.time.perf_counter", perf)
    return ticks


def test_flat_r_stops_after_the_third_take_and_keeps_the_best(tmp_path, monkeypatch):
    measure, seen, scores = _measure([0.04, 0.17, 0.06, 0.13])
    production, calls, files = _runner(tmp_path, monkeypatch, ["t1.mp4", "t2.mp4", "t3.mp4", "t4.mp4"], measure)
    _clock(monkeypatch)
    production.clips({"max_takes": 5}, [WINDOW], pause=0)
    assert seen == [0.04, 0.17, 0.06]
    assert next(scores) == 0.13                         # the fourth r is never consumed
    assert next(files) == "t4.mp4"
    assert len(calls) == 3
    kept = production.state["clips"]["a"]
    assert kept["file"] == "t2.mp4" and kept["qa"]["best_r"] == 0.17
    assert production.state["discarded"] == ["t1.mp4", "t3.mp4"]
    assert production.state["clip_takes"]["a"] == 3
    assert production.state["clip_seconds"]["a"] == 3.0
    assert "clip_seconds" not in status_summary(production.state, "ws")


def test_rising_r_may_reach_four_takes_and_then_the_cap_stops(tmp_path, monkeypatch):
    measure, seen, scores = _measure([0.10, 0.20, 0.30, 0.40, 0.50])
    production, calls, _files = _runner(tmp_path, monkeypatch, [f"t{i}.mp4" for i in range(1, 6)], measure)
    production.clips({"max_takes": 5}, [WINDOW], pause=0)
    assert seen == [0.10, 0.20, 0.30, 0.40]
    assert next(scores) == 0.50
    assert len(calls) == 4 and production.state["clip_takes"]["a"] == 4
    assert production.state["clips"]["a"]["qa"]["best_r"] == 0.40
    production.clips({"max_takes": 5}, [WINDOW], pause=0)
    assert seen == [0.10, 0.20, 0.30, 0.40]             # already at 4: not shot again


def test_four_recorded_takes_shoot_only_from_an_explicit_retake(tmp_path, monkeypatch):
    measure, seen, scores = _measure([0.05, 0.99])
    production, calls, _files = _runner(tmp_path, monkeypatch, ["new.mp4", "newer.mp4"], measure)
    production.state["clip_takes"] = {"a": 4}
    production.state["clips"] = {"a": {"file": "old.mp4", "qa": {"verdict": "retake", "best_r": 0.17}, "url": "/u/old.mp4"}}
    production.clips({"max_takes": 5}, [WINDOW], pause=0)
    assert calls == [] and seen == []
    production.state.pop("clips")
    production.clips({"max_takes": 5}, [WINDOW], pause=0)
    assert calls == []                                  # four takes and no kept clip: still not automatic
    production.state["clips"] = {"a": {"file": "old.mp4", "qa": {"verdict": "retake", "best_r": 0.17}, "url": "/u/old.mp4"}}
    production.clips({"max_takes": 5}, [WINDOW], retake=("a",), pause=0)
    assert seen == [0.05] and next(scores) == 0.99
    assert production.state["clips"]["a"]["file"] == "old.mp4"
    assert production.state["clips"]["a"]["qa"]["best_r"] == 0.17
    assert production.state["discarded"] == ["new.mp4"]
    assert production.state["clip_takes"]["a"] == 5


def test_logged_takes_count_when_the_counter_was_not_saved(tmp_path, monkeypatch):
    measure, seen, _scores = _measure([0.4])
    production, calls, _files = _runner(tmp_path, monkeypatch, ["again.mp4"], measure)
    production.state["log"] = [f"clip a take {n}: failed (oom)" for n in range(1, 5)]
    production.clips({"max_takes": 3}, [WINDOW], pause=0)
    assert calls == [] and seen == []


def test_a_failed_round_waits_on_the_injected_pause(tmp_path, monkeypatch):
    slept: list[float] = []
    monkeypatch.setattr("services.music_production.time.sleep", slept.append)
    measure, seen, _scores = _measure([0.5])
    production, calls, files = _runner(tmp_path, monkeypatch, [None, None, "unused.mp4"], measure)
    production.clips({"max_takes": 2}, [WINDOW], pause=60)
    assert len(calls) == 2 and seen == []               # failures are not measured
    assert slept == [60]                                # the test does not actually sleep
    assert next(files) == "unused.mp4"
    assert production.state["clip_takes"]["a"] == 2
    assert production.state["clip_seconds"]["a"] >= 0
    assert "clip a take 1: failed (no output)" in production.state["log"]


def test_a_job_lost_to_a_queue_restart_is_shot_again_and_is_not_a_take(tmp_path, monkeypatch):
    measure, seen, _scores = _measure([0.5])
    production, calls, _files = _runner(tmp_path, monkeypatch, [None, "good.mp4"], measure)
    rounds = iter([{"a": None}, {"a": "good.mp4"}])

    def wait(jobs, poll=6):
        production.failures = {}
        result = next(rounds)
        production.lost = {"a"} if result["a"] is None else set()
        return result

    production.wait = wait
    production.clips({"max_takes": 1}, [WINDOW], pause=0)
    assert len(calls) == 2 and seen == [0.5]
    assert production.state["clip_takes"]["a"] == 1               # the vanished job did not use the single take
    assert production.state["clip_lost"]["a"] == 1
    assert any("job lost" in line for line in production.state["log"])
    assert production.state["clips"]["a"]["file"] == "good.mp4"


def test_a_shot_whose_jobs_keep_vanishing_counts_them_after_three_losses(tmp_path, monkeypatch):
    measure, _seen, _scores = _measure([])
    production, calls, _files = _runner(tmp_path, monkeypatch, [], measure)

    def wait(jobs, poll=6):
        production.failures = {}
        production.lost = set(jobs)
        return {key: None for key in jobs}

    production.wait = wait
    production.clips({"max_takes": 1}, [WINDOW], pause=0)
    assert len(calls) == 4                                       # three losses, then the fourth counts as the take
    assert production.state["clip_takes"]["a"] == 1
    assert production.state["clip_lost"]["a"] == 3


def test_each_clip_is_recorded_when_it_lands_not_when_the_round_ends(tmp_path, monkeypatch):
    measure, seen, _scores = _measure([0.5, 0.5])
    production, calls, _files = _runner(tmp_path, monkeypatch, [], measure)
    windows = [{**WINDOW, "key": "a", "i": 0}, {**WINDOW, "key": "b", "i": 1}]
    production.state["frames"]["b"] = "f.png"
    recorded_when_b_lands = {}

    def wait(jobs, poll=6):
        production.failures = {}
        production.on_landed("a", "a.mp4")                    # the wait reports a first...
        recorded_when_b_lands.update(dict(production.state["clips"]))     # ...and it is already saved before b exists
        production.on_landed("b", "b.mp4")
        return {"a": "a.mp4", "b": "b.mp4"}

    production.wait = wait
    production.clips({"max_takes": 1}, windows, pause=0)
    assert list(recorded_when_b_lands) == ["a"] and set(production.state["clips"]) == {"a", "b"}
    assert production.state["clip_takes"] == {"a": 1, "b": 1} and production.on_landed is None


def test_an_unreliable_take_does_not_push_out_one_that_measured_ok():
    from services.production_takes import better_take
    ok, unreliable, retake = {"verdict": "ok", "best_r": 0.3}, {"verdict": "unreliable", "best_r": 0.9}, {"verdict": "retake", "best_r": 0.1}
    assert not better_take(unreliable, ok) and better_take(ok, unreliable) and better_take(ok, retake)
    assert better_take({"verdict": "ok", "best_r": 0.4}, ok) and not better_take({"verdict": "ok", "best_r": 0.2}, ok)
    assert better_take({"verdict": "ok"}, {"verdict": "ok"})                       # non-sung shots: the newest ok take wins
