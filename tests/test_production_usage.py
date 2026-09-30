"""production.status reports MCP calls, response bytes, and H3 takes."""
from __future__ import annotations

import json

from services.music_production import Production, status_summary


def test_each_mcp_reply_is_counted_and_saves_are_debounced(tmp_path):
    replies = [{"ok": True, "n": 1}, {"ok": True, "n": 2}]

    def mcp(tool, arguments):
        return replies.pop(0)

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.state["clip_takes"] = {"verse": 2, "chorus": 1}
    assert production.mcp("generation.image", {})["n"] == 1
    assert production.mcp("generate", {})["n"] == 2
    status = status_summary(production.state, "ws")
    assert status["usage"]["mcp_calls"] == 2
    assert json.loads((tmp_path / "p.production.json").read_text())["usage"]["mcp_calls"] == 1   # the second reply rides on the next save
    assert status["usage"]["response_bytes"] == len(json.dumps({"ok": True, "n": 1}, ensure_ascii=False).encode()) + len(json.dumps({"ok": True, "n": 2}, ensure_ascii=False).encode())
    assert status["usage"]["h3_takes"] == 3


def test_a_run_with_no_calls_reports_zeros():
    assert status_summary({"status": "running"}, "ws")["usage"] == {
        "mcp_calls": 0, "response_bytes": 0, "h3_takes": 0,
        "gpu_seconds": 0, "cpu_seconds": 0, "retry_seconds": 0, "reused_seconds": 0,
    }


def test_polling_does_not_rewrite_the_state_file_on_every_call():
    from services.production_usage import SAVE_EVERY_S, attach_usage
    now = {"t": 100.0}
    saves = []
    state: dict = {}
    call = attach_usage(lambda tool, arguments: {"ok": True}, state, lambda: saves.append(1), clock=lambda: now["t"])
    for _ in range(40):                  # forty status polls inside one window
        call("status", {})
        now["t"] += 0.1
    assert len(saves) == 1 and state["usage"]["mcp_calls"] == 40
    now["t"] += SAVE_EVERY_S
    call("status", {})
    assert len(saves) == 2


def test_response_bytes_stay_bytes():
    from services.production_usage import usage_summary
    usage = usage_summary({"usage": {"mcp_calls": 1, "response_bytes": 8}})
    assert usage["response_bytes"] == 8
    assert "tokens" not in usage
    assert usage["gpu_seconds"] == usage["cpu_seconds"] == usage["retry_seconds"] == usage["reused_seconds"] == 0


def test_gpu_and_cpu_seconds_split_stages_and_ignore_package():
    from services.production_usage import usage_summary
    usage = usage_summary({"timing": {"song": 4, "analyze": 9, "cast": 8, "frames": 3, "clips": 32, "scenes": 5, "montage": 6, "package": 100}})
    assert usage["gpu_seconds"] == 39
    assert usage["cpu_seconds"] == 11
    assert usage["retry_seconds"] == 0
    bare = usage_summary({"runs": [{"timing": {"song": 4, "frames": 1, "clips": 2, "scenes": 3, "montage": 4, "analyze": 9}}]})
    assert bare["gpu_seconds"] == 7
    assert bare["cpu_seconds"] == 7


def test_retake_overrides_the_shot_fraction_and_fingerprints_count_as_reused():
    from services.production_usage import usage_summary
    fraction = usage_summary({"timing": {"shots": [{"key": "a", "seconds": 30, "takes": 3}]}})
    assert fraction["retry_seconds"] == 20
    overridden = usage_summary({
        "timing": {"shots": [{"key": "a", "seconds": 30, "takes": 3}], "frames": 3, "clips": 32},
        "runs": [{"retake": ["a"], "timing": {"frames": 1, "clips": 9}}],
    })
    assert overridden["retry_seconds"] == 10
    assert overridden["gpu_seconds"] == 35
    reused = usage_summary({
        "scenes": {
            "a": {"fingerprint": "x", "prior_fingerprint": "x", "seconds": 7},
            "b": {"fingerprint": "x", "prior_fingerprint": "y", "seconds": 9},
            "c": {"fingerprint_unchanged": True, "seconds": 4},
            "d": {"fingerprint_unchanged": True},
        },
        "runs": [{"reused_seconds": 2, "retake": "again", "timing": {"clips": 9}}],
    })
    assert reused["reused_seconds"] == 13
    assert reused["retry_seconds"] == 0


def test_note_run_appends_a_row_and_records_a_completed_workspace(tmp_path):
    import json
    from services.production_usage import note_run
    state = {"status": "completed", "started": 1.0, "finished": 2.0, "timing": {"song": 4, "clips": 2, "package": 9}}
    note_run(state, ("s0",), tmp_path)
    assert state["runs"] == [{
        "started": 1.0, "finished": 2.0, "retake": ["s0"], "timing": {"song": 4, "clips": 2},
    }]
    stored = json.loads((tmp_path / ".production-timings.json").read_text())
    assert stored["n"] == 1


def test_the_runner_records_a_run(tmp_path, monkeypatch):
    import json
    from services.production_usage import usage_summary
    clock = {"t": 0.0}
    monkeypatch.setattr("services.production_timing.time.perf_counter", lambda: clock["t"])

    def bump(step, fn):
        def wrapped(*args, **kwargs):
            clock["t"] += step
            return fn(*args, **kwargs)
        return wrapped

    (tmp_path / "s.score.json").write_text(
        '{"duration": 30, "beat": 0.5, "lines": [{"t0": 1.0, "t1": 3.0, "text": "a"}, {"t0": 20.0, "t1": 22.0, "text": "b"}]}'
    )
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=lambda *_: {})
    production.song = bump(4, lambda spec: production.state.update(song={"file": "s.wav"}))
    production.analyze = bump(1, lambda spec: production.state.__setitem__("score", "s.score.json"))
    production.cast = bump(2, lambda spec: None)
    production.frames = bump(3, lambda spec, windows: production.state.__setitem__("frames", {w["key"]: "f.png" for w in windows if w["kind"] == "h3"}))
    production.clip_job = bump(2, lambda spec, window, seed, take=0: "job")
    production.wait = bump(30, lambda jobs, poll=6: {key: f"{key}.mp4" for key in jobs})
    production.upload = lambda name: (str(name), "/u/" + str(name))
    production.scenes = bump(5, lambda spec, windows: None)
    production.montage = bump(6, lambda spec: production.state.__setitem__("final", "v.mp4"))
    spec = {"title": "t", "song": {"lyrics": "a\nb", "caption": "pop", "duration": 30, "bpm": 120}, "style": {},
            "shots": [{"key": "intro", "kind": "still", "t0": 0, "still": "k"},
                      {"key": "s0", "kind": "h3", "line": 0, "frame": "f", "action": "a"},
                      {"key": "s1", "kind": "still", "line": 1, "still": "k"}]}
    production.run(spec)
    assert production.state["status"] == "completed"
    assert production.state["runs"][-1]["retake"] == []
    assert set(production.state["runs"][-1]) == {"started", "finished", "retake", "timing"}
    usage = usage_summary(production.state)
    assert usage["gpu_seconds"] == 39
    assert usage["cpu_seconds"] == 11
    assert usage["retry_seconds"] == 0
    assert "tokens" not in usage
    stored = json.loads((tmp_path / ".production-timings.json").read_text())
    assert stored["n"] == 1
