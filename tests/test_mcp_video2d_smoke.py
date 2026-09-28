"""Fast envelope check for the Video 2D MCP smoke. The painter run is opt-in."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.mcp_video2d_smoke import PLANNED, dry_problems, painter_reason, run_smoke


def test_smoke_imports_and_dry_envelopes_are_wired():
    source = Path(__file__).resolve().parents[1].joinpath("scripts/mcp_video2d_smoke.py").read_text(encoding="utf-8")
    assert "scenes.video2d.export" in PLANNED
    assert "scenes.video2d.edit" in PLANNED
    assert "montages.save" in PLANNED
    assert "not on this branch" not in source
    assert dry_problems() == []


@pytest.mark.skipif(os.environ.get("HOCUS_VIDEO2D_SMOKE") != "1", reason="set HOCUS_VIDEO2D_SMOKE=1 to run the painter smoke")
def test_video2d_mcp_smoke(tmp_path):
    reason = painter_reason()
    if reason:
        pytest.skip(reason)
    report = run_smoke(tmp_path, tmp_path / "contact.png")
    assert report["validate_errors"] == []
    assert Path(report["contact_sheet"]).is_file()
    assert report["scene_file"]
    assert report["montage_file"]
    assert report["mp4"] or report["mp4_reason"]
