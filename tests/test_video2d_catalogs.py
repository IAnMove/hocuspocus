"""Shared Video 2D catalogs are read-only MCP operations over app/shared JSON."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.video2d_catalogs import (
    CATALOG_FILES,
    EFFECTS_CATALOG,
    CatalogError,
    command_catalog,
    execute,
    load_catalog,
)

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "app" / "shared"


def _ids(data):
    entries = data if isinstance(data, list) else data["entries"]
    return [item["id"] for item in entries]


def test_each_catalog_operation_returns_its_json_ids():
    published = command_catalog()
    assert [item["name"] for item in published] == list(CATALOG_FILES)
    assert all(item["mutation"] is False and item["name"].endswith(".catalog") for item in published)
    for operation, filename in CATALOG_FILES.items():
        payload = json.loads((SHARED / filename).read_text(encoding="utf-8"))
        result = execute({"version": 1, "operation": operation, "input": {}})
        assert result["status"] == "completed"
        assert result["result"] == payload
        assert _ids(result["result"]) == _ids(payload)
        assert filename in published[[item["name"] for item in published].index(operation)]["description"]


def test_catalog_results_are_copies_and_effects_json_loads():
    result = execute({"version": 1, "operation": "scenes.fonts.catalog", "input": {}})
    result["result"]["entries"][0]["id"] = "mutated"
    again = execute({"version": 1, "operation": "scenes.fonts.catalog", "input": {}})
    assert again["result"]["entries"][0]["id"] != "mutated"
    assert _ids(EFFECTS_CATALOG) == _ids(json.loads((SHARED / "scene_effects.json").read_text(encoding="utf-8")))


@pytest.mark.parametrize(
    ("command", "code"),
    [
        ({"version": 1, "input": {}}, "catalog_bad_envelope"),
        ({"version": True, "operation": "scenes.fonts.catalog", "input": {}}, "catalog_bad_envelope"),
        ({"version": 1, "operation": "scenes.fonts.catalog", "input": {"id": "sans"}}, "catalog_bad_envelope"),
        ({"version": 1, "operation": "scenes.missing.catalog", "input": {}}, "catalog_unknown_operation"),
    ],
)
def test_catalog_errors_use_stable_codes(command, code):
    with pytest.raises(CatalogError) as caught:
        execute(command)
    assert caught.value.code == code
    assert str(caught.value).startswith(f"{code}:")


def test_loader_rejects_missing_invalid_and_duplicate_files(tmp_path, monkeypatch):
    monkeypatch.setattr("services.video2d_catalogs.ROOT", tmp_path)
    with pytest.raises(CatalogError) as missing:
        load_catalog("scene_templates.json")
    assert missing.value.code == "catalog_missing"
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    with pytest.raises(CatalogError) as invalid:
        load_catalog("broken.json")
    assert invalid.value.code == "catalog_invalid"
    (tmp_path / "dup.json").write_text('[{"id": "a"}, {"id": "a"}]', encoding="utf-8")
    with pytest.raises(CatalogError) as duplicate:
        load_catalog("dup.json")
    assert duplicate.value.code == "catalog_duplicate_id"
    with pytest.raises(CatalogError) as escaped:
        load_catalog("../scene_templates.json")
    assert escaped.value.code == "catalog_missing"
