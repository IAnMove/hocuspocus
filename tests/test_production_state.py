"""Log lines coalesce on disk. A direct save still writes at once."""
from __future__ import annotations

import json

from services.music_production import Production


def _production(tmp_path, monkeypatch, clock):
    monkeypatch.setattr("services.production_state.time.monotonic", lambda: clock["t"])
    return Production(
        "ws", "p",
        workspace_dir=lambda _: str(tmp_path),
        uploads_dir=lambda: str(tmp_path),
        mcp=lambda tool, arguments: {},
    )


def test_five_hundred_logs_write_once_and_the_file_stays_json(tmp_path, monkeypatch):
    clock = {"t": 1000.0}
    production = _production(tmp_path, monkeypatch, clock)
    production.log("first")
    for index in range(499):
        production.log(f"line {index:03d}")
    on_disk = json.loads(production.path.read_text(encoding="utf-8"))
    assert on_disk["log"] == ["first"]
    assert not production.path.with_suffix(".tmp").exists()
    assert len(production.state["log"]) == 60
    production.save()
    flushed = json.loads(production.path.read_text(encoding="utf-8"))
    assert flushed["log"][0] == "line 439"
    assert flushed["log"][-1] == "line 498"
    assert len(flushed["log"]) == 60


def test_a_direct_save_inside_the_window_still_writes(tmp_path, monkeypatch):
    clock = {"t": 50.0}
    production = _production(tmp_path, monkeypatch, clock)
    production.log("kept")
    production.state["status"] = "running"
    production.save()
    body = json.loads(production.path.read_text(encoding="utf-8"))
    assert body["status"] == "running"
    assert body["log"] == ["kept"]


def test_a_log_after_two_seconds_writes_again(tmp_path, monkeypatch):
    clock = {"t": 10.0}
    production = _production(tmp_path, monkeypatch, clock)
    production.log("one")
    clock["t"] += 2.0
    production.log("two")
    assert json.loads(production.path.read_text(encoding="utf-8"))["log"] == ["one", "two"]
