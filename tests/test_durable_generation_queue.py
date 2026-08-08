from __future__ import annotations

import json
from pathlib import Path

from app.services.durable_generation_queue import DurableGenerationQueue


def _record(job_id: str, created_at: float, status: str = "queued") -> dict:
    return {
        "id": job_id,
        "status": status,
        "created_at": created_at,
        "workspace": "default",
        "params": {
            "model_type": "test-model",
            "generation_mode": "video",
            "prompt": f"line one for {job_id}\nline two",
        },
    }


def test_queue_survives_reinstantiation_and_preserves_order(tmp_path: Path):
    path = tmp_path / "outputs" / ".maestro_generation_queue.json"
    queue = DurableGenerationQueue(str(path))
    queue.upsert(_record("later", 20))
    queue.upsert(_record("earlier", 10, "running"))

    recovered = DurableGenerationQueue(str(path)).list()

    assert [job["id"] for job in recovered] == ["earlier", "later"]
    assert recovered[0]["status"] == "running"
    assert recovered[0]["params"]["prompt"].endswith("\nline two")
    assert json.loads(path.read_text(encoding="utf-8"))["version"] == 1
    assert not list(path.parent.glob("*.tmp"))


def test_upsert_replaces_state_and_remove_is_terminal(tmp_path: Path):
    path = tmp_path / "queue.json"
    queue = DurableGenerationQueue(str(path))
    queue.upsert(_record("job", 10))
    queue.upsert(_record("job", 10, "running"))

    assert len(queue.list()) == 1
    assert queue.list()[0]["status"] == "running"
    assert queue.remove("job") is True
    assert queue.remove("job") is False
    assert queue.list() == []


def test_discard_preserves_live_job_ids(tmp_path: Path):
    queue = DurableGenerationQueue(str(tmp_path / "queue.json"))
    queue.upsert(_record("live", 10, "running"))
    queue.upsert(_record("crashed", 20, "queued"))

    removed = queue.discard(exclude_ids={"live"})

    assert removed == 1
    assert [job["id"] for job in queue.list()] == ["live"]
