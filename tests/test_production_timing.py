"""Stage seconds on production.status: seven numbers, shot rows, and a small JSON."""
from __future__ import annotations

import json

from services.music_production import Production, status_summary
from services.production_timing import STAGES, timing_summary


def _spec(**extra):
    spec = {"title": "t", "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": "intro", "kind": "still", "t0": 0, "still": "k"},
                      {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"},
                      {"key": "s1", "kind": "still", "line": 1, "still": "k"}]}
    spec.update(extra)
    return spec


def _clock(monkeypatch):
    clock = {"t": 0.0}
    monkeypatch.setattr("services.production_timing.time.perf_counter", lambda: clock["t"])
    return clock


def _bump(clock, step, fn):
    def wrapped(*args, **kwargs):
        clock["t"] += step
        return fn(*args, **kwargs)
    return wrapped


def _production(tmp_path, clock):
    (tmp_path / "s.score.json").write_text(
        '{"duration": 30, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0, "text": "a"}, {"t0": 20.0, "t1": 22.0, "text": "b"}]}'
    )
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *_: {})
    production.song = _bump(clock, 4, lambda spec: production.state.update(song={"file": "s.wav"}))
    production.analyze = _bump(clock, 1, lambda spec: production.state.__setitem__("score", "s.score.json"))
    production.cast = _bump(clock, 2, lambda spec: None)
    production.frames = _bump(clock, 3, lambda spec, windows: production.state.__setitem__("frames", {w["key"]: "f.png" for w in windows if w["kind"] == "h3"}))
    production.clip_job = _bump(clock, 2, lambda spec, window, seed, take=0: "job")
    production.wait = _bump(clock, 30, lambda jobs, poll=6: {key: f"{key}.mp4" for key in jobs})
    production.upload = lambda name: (str(name), "/u/" + str(name))
    production.scenes = _bump(clock, 5, lambda spec, windows: None)
    production.montage = _bump(clock, 6, lambda spec: production.state.__setitem__("final", "v.mp4"))
    return production


def test_fake_run_records_seven_stages_and_a_shot(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    production = _production(tmp_path, clock)
    clip_job = production.clip_job
    production.run(_spec())
    timing = production.state["timing"]
    assert [timing[name] for name in STAGES] == [4, 1, 2, 3, 32, 5, 6]
    assert timing["shots"] == [{"key": "s0", "seconds": 32, "takes": 1}]
    assert production.clip_job is clip_job
    status = status_summary(production.state, "ws")
    assert [status["timing"][name] for name in STAGES] == [4, 1, 2, 3, 32, 5, 6]
    assert status["timing"]["shots"] == [{"key": "s0", "seconds": 32, "takes": 1}]
    assert len(json.dumps(status).encode()) < 1500
    assert "/" not in json.dumps(status["timing"])


def test_parallel_shots_split_the_wait_and_keep_their_takes(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    production = _production(tmp_path, clock)
    shots = [{"key": "a", "kind": "h3", "t0": 0, "frame": "f", "action": "a"},
             {"key": "b", "kind": "h3", "t0": 5, "frame": "f", "action": "a"}]
    production.run(_spec(shots=shots))
    timing = production.state["timing"]
    assert timing["clips"] == 34
    assert timing["shots"] == [{"key": "a", "seconds": 17, "takes": 1}, {"key": "b", "seconds": 17, "takes": 1}]


def test_stages_that_did_not_run_are_zero(tmp_path, monkeypatch):
    production = _production(tmp_path, _clock(monkeypatch))
    production.run(_spec(), through="frames")
    timing = status_summary(production.state, "ws")["timing"]
    assert [timing[name] for name in STAGES] == [4, 1, 2, 3, 0, 0, 0]
    assert timing["shots"] == []
    assert production.state["status"] == "frames_ready"


def test_a_failed_stage_keeps_its_seconds(tmp_path, monkeypatch):
    clock = _clock(monkeypatch)
    production = _production(tmp_path, clock)

    def song(spec):
        clock["t"] += 4
        raise RuntimeError("nope")

    production.song = song
    production.run(_spec())
    timing = production.state["timing"]
    assert production.state["status"] == "failed"
    assert timing["song"] == 4 and timing["analyze"] == 0 and timing["montage"] == 0
    assert status_summary(production.state, "ws")["timing"]["clips"] == 0


def test_status_without_a_run_is_zeros_and_a_normal_one_stays_small():
    blank = status_summary({"status": "running"}, "ws")["timing"]
    assert [blank[name] for name in STAGES] == [0, 0, 0, 0, 0, 0, 0]
    assert blank["shots"] == []
    shots = [{"key": f"s{i}", "seconds": 80 + i, "takes": 1 + (i % 3), "file": "f.png", "prompt": "x" * 400} for i in range(8)]
    state = {"status": "completed", "error": None, "song": {"file": "song.wav"},
             "clips": {f"s{i}": {"qa": {"verdict": "ok"}} for i in range(8)},
             "scenes": {f"s{i}": {"file": "scene.mp4"} for i in range(8)},
             "frames": {f"s{i}": "frame.png" for i in range(8)},
             "final": "video.mp4", "contact_sheet": "p-contact.jpg",
             "log": [f"clip s{i} take 1 (mix): ok r=0.42" for i in range(8)],
             "timing": {"song": 120, "analyze": 3, "cast": 40, "frames": 80, "clips": 700, "scenes": 90, "montage": 25, "shots": shots}}
    status = status_summary(state, "ws")
    encoded = json.dumps(status)
    # execution, technical, and artistic are always on the reply. Prompts stay out.
    # progress and the four usage second fields are on the reply too.
    assert len(encoded.encode()) < 1750
    assert status["timing"]["shots"][0] == {"key": "s0", "seconds": 80, "takes": 1}
    assert "frame.png" not in json.dumps(status["timing"]) and "prompt" not in json.dumps(status["timing"])
    assert timing_summary({"timing": {"song": -3, "shots": [{"key": "", "seconds": 1}]}})["song"] == 0


def test_short_stages_add_up_instead_of_rounding_to_zero_each_time():
    from services.production_timing import StageWatch
    now = {"t": 0.0}
    production = type("P", (), {"state": {}})()
    watch = StageWatch(production, clock=lambda: now["t"])
    for _ in range(3):
        watch.start("song")
        assert production.state["stage"] == "song"
        now["t"] += 0.4
        watch.stop()
    assert production.state["timing"]["song"] == 1.2
    assert timing_summary(production.state)["song"] == 1


def test_the_watch_reads_shot_rows_from_the_take_loop_and_wraps_nothing():
    from services.production_timing import StageWatch
    production = type("P", (), {"state": {"clip_seconds": {"a": 7.5, "b": 2.25}, "clip_takes": {"a": 2, "b": 1}}})()
    production.clip_job = production.wait = "untouched"
    watch = StageWatch(production, clock=lambda: 0.0)
    watch.call("clips", lambda: None)
    assert production.state["timing"]["shots"] == [{"key": "a", "seconds": 7.5, "takes": 2}, {"key": "b", "seconds": 2.25, "takes": 1}]
    assert (production.clip_job, production.wait) == ("untouched", "untouched")
