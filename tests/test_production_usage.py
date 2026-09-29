"""production.status reports MCP calls, response bytes, and H3 takes."""
from __future__ import annotations

import json

from services.music_production import Production, status_summary


def test_each_mcp_reply_is_counted_and_saved(tmp_path):
    replies = [{"ok": True, "n": 1}, {"ok": True, "n": 2}]

    def mcp(tool, arguments):
        return replies.pop(0)

    production = Production("ws", "p", workspace_dir=lambda _: str(tmp_path), uploads_dir=lambda: str(tmp_path), mcp=mcp)
    production.state["clip_takes"] = {"verse": 2, "chorus": 1}
    assert production.mcp("generation.image", {})["n"] == 1
    assert production.mcp("generate", {})["n"] == 2
    saved = json.loads((tmp_path / "p.production.json").read_text())
    status = status_summary(saved, "ws")
    assert status["usage"]["mcp_calls"] == 2
    assert status["usage"]["response_bytes"] == len(json.dumps({"ok": True, "n": 1}, ensure_ascii=False).encode()) + len(json.dumps({"ok": True, "n": 2}, ensure_ascii=False).encode())
    assert status["usage"]["h3_takes"] == 3


def test_a_run_with_no_calls_reports_zeros():
    assert status_summary({"status": "running"}, "ws")["usage"] == {"mcp_calls": 0, "response_bytes": 0, "h3_takes": 0}
