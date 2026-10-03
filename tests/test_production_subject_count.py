"""A declared group of four that is drawn as one person is recorded, and no count is invented without the model."""
from __future__ import annotations

from services.music_production import Production, status_summary
from services.production_subject_count import expected_subjects, judge_count, note_media
from services.qa_people import score_boxes


def _production(tmp_path):
    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=None)
    production.state = {"cast": {"band": "/u/band.png"}, "frames": {"s0": "f.png"}, "clips": {"s0": {"file": "c.mp4"}}, "log": []}
    (tmp_path / "f.png").write_bytes(b"png")
    (tmp_path / "c.mp4").write_bytes(b"mp4")
    return production


def _shot():
    return {"key": "s0", "kind": "h3", "cast": ["band"]}


def test_a_group_of_four_counted_as_one_is_a_mismatch_on_the_frame_and_the_clip(tmp_path, monkeypatch):
    monkeypatch.setattr("services.production_subject_count._open", lambda path, stage: b"image")
    production = _production(tmp_path)
    production.subject_detector = lambda _image: 1
    spec = {"cast": [{"id": "band", "sheet_prompt": "four players", "count": 4}]}
    frames = note_media(production, spec, [_shot()], "frame")
    clips = note_media(production, spec, [_shot()], "clip")
    assert frames[0]["verdict"] == "mismatch" and frames[0]["expected"] == 4 and frames[0]["detected"] == 1
    assert clips[0]["stage"] == "clip" and clips[0]["detected"] == 1
    assert status_summary(production.state, "ws")["subject_counts"] == [
        {"key": "s0", "stage": "frame", "expected": 4, "detected": 1},
        {"key": "s0", "stage": "clip", "expected": 4, "detected": 1},
    ]
    assert any("expected 4 detected 1" in line for line in production.state["log"])


def test_a_matching_count_stays_off_the_status_and_a_group_without_count_uses_its_members():
    assert judge_count("s0", "frame", 4, 4)["verdict"] == "ok"
    assert judge_count("s0", "frame", 4, None)["verdict"] == "unreliable"
    assert expected_subjects({"cast": [{"id": "band", "group": ["a", "b", "c", "d"]}]}, {"cast": ["band"]}) == 4
    assert expected_subjects({"cast": [{"id": "hero", "sheet_prompt": "x"}]}, {"cast": []}) is None
    assert status_summary({"status": "running", "subject_counts": [{"key": "s0", "stage": "frame", "verdict": "ok", "expected": 1, "detected": 1}]}, "ws").get("subject_counts") is None


def test_without_the_weights_no_count_is_invented(tmp_path, monkeypatch):
    monkeypatch.setattr("services.qa_people.find_weights", lambda: None)
    production = _production(tmp_path)
    rows = note_media(production, {"cast": [{"id": "band", "count": 4}]}, [_shot()], "frame")
    assert rows == [] and "subject_counts" not in production.state
    assert production.state["subject_count_detector"] == "missing: pose/yolox_l.onnx"
    assert any("no count invented" in line for line in production.state["log"])
    note_media(production, {"cast": [{"id": "band", "count": 4}]}, [_shot()], "clip")
    assert sum("no count invented" in line for line in production.state["log"]) == 1


def test_qa_people_retakes_when_four_people_are_counted_as_one():
    decision = score_boxes([1, 1, 1], expected=4)
    assert decision["verdict"] == "retake" and decision["max_people"] == 1 and decision["expected"] == 4
