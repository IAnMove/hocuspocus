"""Director repair plans are deterministic from files on disk."""
from __future__ import annotations

from pathlib import Path

from services import director_pipeline
from services.director import pipeline_repair_plan


def test_repair_plan_helpers_are_reexported():
    assert director_pipeline._plan_pipeline_repair is pipeline_repair_plan._plan_pipeline_repair
    assert director_pipeline._repair_queue_message is pipeline_repair_plan._repair_queue_message
    assert director_pipeline._repair_start_result is pipeline_repair_plan._repair_start_result


def test_repair_plan_queues_stale_video_and_join(tmp_path: Path, monkeypatch):
    pid = "repair-1"
    state_path = tmp_path / f"_director_pipeline_{pid}.json"
    state_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(director_pipeline, "_find_pipeline_file", lambda *_a, **_k: str(state_path))
    monkeypatch.setattr(director_pipeline, "_saved_pipeline_shot_image_policy", lambda _state: "generate")
    monkeypatch.setattr(
        director_pipeline,
        "_invalid_saved_media_numbers",
        lambda files, count, *_a, **_k: (
            [1] if files and files[0] is None and "png" in str(files) else (
                [1] if any(name and str(name).endswith(".mp4") for name in files) else []
            )
        ),
    )

    def invalid(files, count, folder, kind):
        if kind == "image":
            return []
        return [2]

    monkeypatch.setattr(director_pipeline, "_invalid_saved_media_numbers", invalid)
    state = {
        "clips": [
            {"image_prompt": "a", "video_prompt": "walk", "start_image_filename": "1.png", "video_filename": "1.mp4"},
            {"image_prompt": "b", "video_prompt": "run", "start_image_filename": "2.png", "video_filename": None, "video_stale": True},
        ]
    }
    plan = director_pipeline._plan_pipeline_repair(str(tmp_path), pid, state)
    assert plan["image_indices"] == []
    assert plan["video_indices"] == [1]
    assert plan["should_rejoin"] is True
    assert plan["total"] == 2
    assert "video" in director_pipeline._repair_queue_message(plan)
    assert "final join" in director_pipeline._repair_queue_message(plan)


def test_repair_start_result_waits_and_raises_start_error():
    class Ready:
        def wait(self):
            return True

    ok = director_pipeline._repair_start_result("p1", {"ready_event": Ready(), "snapshot": {"status": "queued"}})
    assert ok == {"pipeline_id": "p1", "repair": {"status": "queued"}}
    try:
        director_pipeline._repair_start_result("p1", {"ready_event": Ready(), "start_error": ValueError("boom")})
        raise AssertionError("expected start_error")
    except ValueError as exc:
        assert "boom" in str(exc)
