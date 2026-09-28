"""scenes.catalog kind graphics lists parameterized drawings, not custom code."""

from __future__ import annotations

import json

from services.video2d_catalogs import GRAPHICS_CATALOG, query_catalog

IDS = ["chart", "odometer", "orbit", "silhouette", "shatter", "countdown"]
PARAM_TYPES = {"number", "color", "enum"}


def test_graphics_catalog_lists_the_six_drawings():
    listed = query_catalog({"kind": "graphics"})["result"]
    assert [item["id"] for item in listed["entries"]] == IDS
    assert listed["total"] == 6
    assert listed["truncated"] is False
    detail = query_catalog({"kind": "graphics", "detail": True})["result"]
    assert detail["entries"] == GRAPHICS_CATALOG["entries"]
    summary = query_catalog({})["result"]["kinds"]
    assert summary[-1] == {"kind": "graphics", "count": 6}
    for entry in detail["entries"]:
        params = entry["params"]
        assert 3 <= len(params) <= 6
        assert "thumbnail" not in entry
        assert all(isinstance(value, (int, float)) and value > 0 for value in entry["beats"].values())
        for param in params:
            assert param["type"] in PARAM_TYPES
            assert isinstance(param["key"], str) and param["key"]
            assert "default" in param
            if param["type"] == "enum":
                assert param["default"] in param["values"]
        blob = json.dumps(entry)
        assert "function" not in blob
        assert "=>" not in blob
