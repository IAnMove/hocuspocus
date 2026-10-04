"""Simulated MCP and Wizard works reach the shared shot review without a GPU."""
from __future__ import annotations

import json
from pathlib import Path

from services.production_project_link import REVIEW_EVENT
from services.production_shot_actions import perform
from services.production_shot_view import shot_view
from services.production_work_commands import run_command


def _command(root: Path, operation: str, **data):
    body = {"workspace": "film"}
    body.update(data)
    return run_command(str(root), {"operation": operation, "version": 1, "input": body})


def test_mcp_and_wizard_reach_review_selection_and_montage(tmp_path: Path):
    root = tmp_path / "film"
    root.mkdir()
    mcp = _command(
        root, "production.works.resolve",
        origin="mcp", intent_id="clip-mcp", format="music_video", title="Night bus",
    )
    wizard = _command(
        root, "production.works.resolve",
        origin="wizard", intent_id="clip-wiz", format="trailer", title="Night bus",
    )
    assert mcp["applied"] is True and mcp["reused"] is False
    assert wizard["production_id"] != mcp["production_id"]
    assert mcp["review"]["event"] == REVIEW_EVENT
    listed = _command(root, "production.works.list")
    assert {item["production_id"] for item in listed["works"]} == {mcp["production_id"], wizard["production_id"]}
    opened = _command(root, "production.works.open", production_id=mcp["production_id"])
    assert opened["applied"] is False
    assert opened["work"]["review"]["workspace"] == "film"

    production_id = mcp["production_id"]
    (root / f"{production_id}.shots.json").write_text(json.dumps({
        "version": 1,
        "production_id": production_id,
        "montage": "cut.montage.json",
        "shots": [{
            "key": "s3",
            "lyric": "night bus",
            "clip": "take-a.mp4",
            "takes": [{"file": "take-a.mp4"}, {"file": "take-b.mp4"}],
        }],
    }), encoding="utf-8")
    (root / "cut.montage.json").write_text(json.dumps({
        "revision": 1,
        "clips": [{"id": "s3", "source": "old-export.mp4"}],
    }), encoding="utf-8")
    (root / "take-b.mp4").write_bytes(b"take-b")

    view = shot_view(str(root), "film", production_id)
    assert view is not None and view["shots"][0]["id"] == "s3"
    selected = perform(str(root), "film", production_id, "s3", {
        "action": "select", "take": "take-b.mp4", "expected_revision": 0,
    })
    reviewed = perform(str(root), "film", production_id, "s3", {
        "action": "review", "status": "approved",
    })
    montage = json.loads((root / "cut.montage.json").read_text(encoding="utf-8"))
    manifest = json.loads((root / f"{production_id}.shots.json").read_text(encoding="utf-8"))

    assert selected["applied"] is True
    assert reviewed["applied"] is True and reviewed.get("status") == "approved"
    assert manifest["shots"][0]["clip"] == "take-b.mp4"
    assert [item["file"] for item in manifest["shots"][0]["takes"]] == ["take-a.mp4", "take-b.mp4"]
    assert montage["clips"][0]["source"] == "old-export.mp4"
    assert montage["clips"][0]["video_stale"] is True
    assert (root / "take-b.mp4").read_bytes() == b"take-b"
    kept = _command(
        root, "production.works.resolve",
        origin="mcp", intent_id="clip-mcp", format="music_video", title="Night bus",
    )
    assert kept["reused"] is True and kept["production_id"] == production_id
