"""Contract tests for Story Lab smart asset analysis."""

from __future__ import annotations

import pytest

from app.services.story_asset_import import asset_import_schema, validate_asset_import_result


def _asset(index: int, kind: str = "location") -> dict:
    return {
        "index": index,
        "kind": kind,
        "targetId": "new-location:harbor",
        "name": f"Asset {index}",
        "description": "Visible stone harbor at dusk.",
        "visualPrompt": "A stone harbor at dusk, empty quay, amber lamps.",
        "confidence": 0.9,
        "reason": "The same waterfront appears in both references.",
    }


def test_schema_requires_exact_batch_size_and_closed_items():
    schema = asset_import_schema(3)
    assets = schema["properties"]["assets"]
    assert assets["minItems"] == assets["maxItems"] == 3
    assert assets["items"]["additionalProperties"] is False


def test_validation_orders_results_by_image_index():
    result = validate_asset_import_result({"assets": [_asset(1), _asset(0)]}, 2)
    assert [item["index"] for item in result] == [0, 1]
    assert result[0]["confidence"] == 0.9


def test_validation_rejects_missing_or_duplicate_images():
    with pytest.raises(ValueError, match="1 items; 2 were required"):
        validate_asset_import_result({"assets": [_asset(0)]}, 2)
    with pytest.raises(ValueError, match="duplicate/out-of-range"):
        validate_asset_import_result({"assets": [_asset(0), _asset(0)]}, 2)
