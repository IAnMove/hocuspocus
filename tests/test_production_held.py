"""A failed H3 clip that plays its start frame is listed on production.status."""
from __future__ import annotations

from services.music_production import Production, status_summary


def test_failed_clip_is_held_and_a_successful_clip_is_not(tmp_path):
    (tmp_path / "s.score.json").write_text('{"duration": 8.0, "beat": 0.5, "lines": []}')
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"score": "s.score.json", "frames": {"bad": "bad.png", "good": "good.png"}, "log": []}
    production.upload = lambda name: (name, "/api/v1/uploads/" + name)
    production.clip_job = lambda spec, w, seed, take: "job"

    def wait(jobs):
        production.failures = {"bad": "out of GPU memory"}
        return {key: None if key == "bad" else "good.mp4" for key in jobs}

    production.wait = wait
    windows = [{"key": "bad", "kind": "h3", "i": 0, "t0": 0.0, "t1": 4.0},
               {"key": "good", "kind": "h3", "i": 1, "t0": 4.0, "t1": 8.0}]
    production.clips({"max_takes": 1}, windows, pause=0)
    clips, score = production.state["clips"], {"lines": []}
    failed = production.scene_ops(windows[0], 0, 4, 4, score, clips, {}, {})
    done = production.scene_ops(windows[1], 4, 8, 4, score, clips, {}, {})
    assert failed[0]["type"] == "image" and failed[0]["source"] == "/api/v1/uploads/bad.png"
    assert done[0]["type"] == "video" and done[0]["source"] == "/api/v1/uploads/good.mp4"
    assert status_summary(production.state, "ws")["held"] == ["bad"]
