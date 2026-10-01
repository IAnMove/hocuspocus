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
