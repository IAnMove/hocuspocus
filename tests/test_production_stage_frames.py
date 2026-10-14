"""Start-frame resume: a changed spec drops the kept picture or marks the clip obsolete."""
from __future__ import annotations

from services.production_stage_frames import forget_changed_shots


class _Production:
    def __init__(self):
        self.state = {"log": []}
        self.logs = []

    def frame_prompt(self, spec, window):
        return f"{(spec.get('style') or {}).get('image', '')} {window['frame']}".strip()

    def log(self, line):
        self.logs.append(line)
        self.state["log"].append(line)


def _shot(**overrides):
    window = {"key": "a", "kind": "h3", "frame": "wide shot", "action": "waves", "camera": "camera-dolly", "cast": []}
    window.update(overrides)
    return window


def test_a_clip_resolution_change_keeps_the_frame_and_marks_the_take_obsolete():
    production = _Production()
    spec = {"style": {"image": "look"}, "resolution": {"frames": "1280x704", "clips": "1280x704"}}
    forget_changed_shots(production, spec, [_shot()])
    production.state["frames"] = {"a": "a.png"}
    production.state["clips"] = {"a": {"file": "a.mp4"}}
    forget_changed_shots(production, {**spec, "resolution": {"frames": "1280x704", "clips": "1024x576"}}, [_shot()])
    assert production.state["frames"] == {"a": "a.png"}
    assert production.state["clips"]["a"]["obsolete"] is True
    assert any("clip a:" in line for line in production.logs)


def test_a_frame_resolution_change_drops_the_start_frame():
    production = _Production()
    spec = {"style": {"image": "look"}, "resolution": {"frames": "1280x704", "clips": "1280x704"}}
    forget_changed_shots(production, spec, [_shot()])
    production.state["frames"] = {"a": "a.png"}
    production.state["clips"] = {"a": {"file": "a.mp4"}}
    forget_changed_shots(production, {**spec, "resolution": {"frames": "1536x1024", "clips": "1280x704"}}, [_shot()])
    assert "a" not in production.state["frames"]
    assert production.state["clips"]["a"]["obsolete"] is True
    assert any("frame a:" in line for line in production.logs)


def test_the_same_resolution_keeps_the_frame_and_the_clip():
    production = _Production()
    spec = {"style": {"image": "look"}, "resolution": {"frames": "1280x704", "clips": "1280x704"}}
    forget_changed_shots(production, spec, [_shot()])
    production.state["frames"] = {"a": "a.png"}
    production.state["clips"] = {"a": {"file": "a.mp4"}}
    forget_changed_shots(production, spec, [_shot()])
    assert production.state["frames"] == {"a": "a.png"}
    assert "obsolete" not in production.state["clips"]["a"]
