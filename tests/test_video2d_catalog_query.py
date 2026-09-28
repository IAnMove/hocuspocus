"""Aggregated scenes.catalog query: one kind, filters, and the 200-entry cap."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.video2d_catalog import create_video2d_catalog_router
from services.video2d_catalogs import (
    CATALOGS,
    EFFECTS_CATALOG,
    KINDS,
    CatalogError,
    execute_query,
    query_catalog,
    query_operation,
)


def _ids(data):
    entries = data if isinstance(data, list) else data["entries"]
    return [item["id"] for item in entries]


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(create_video2d_catalog_router())
    return TestClient(app)


def test_omitted_kind_is_counts_only_and_kind_returns_that_catalog():
    summary = query_catalog({})
    assert summary["operation"] == "scenes.catalog"
    assert set(summary["result"]) == {"kinds"}
    rows = summary["result"]["kinds"]
    assert [row["kind"] for row in rows] == list(KINDS)
    assert all(set(row) == {"kind", "count"} for row in rows)
    fonts = query_catalog({"kind": "fonts"})["result"]
    assert fonts["kind"] == "fonts"
    assert [item["id"] for item in fonts["entries"]] == _ids(CATALOGS["scenes.fonts.catalog"])
    assert fonts["entries"] is not CATALOGS["scenes.fonts.catalog"]["entries"]
    assert fonts["total"] == rows[list(KINDS).index("fonts")]["count"]
    assert fonts["truncated"] is False
    effects = query_catalog({"kind": "effects"})["result"]
    assert [item["id"] for item in effects["entries"]] == _ids(EFFECTS_CATALOG)
    assert effects["total"] == rows[list(KINDS).index("effects")]["count"]


def test_family_filters_templates():
    narrowed = query_catalog({"kind": "templates", "family": "space"})["result"]
    assert narrowed["entries"]
    assert {item["family"] for item in narrowed["entries"]} == {"space"}
    assert narrowed["total"] == len(narrowed["entries"])
    everything = query_catalog({"kind": "templates"})["result"]
    assert narrowed["total"] < everything["total"]
    counted = query_catalog({"family": "space"})["result"]["kinds"]
    full = query_catalog({})["result"]["kinds"]
    assert counted[0]["count"] == narrowed["total"]
    assert counted[1]["count"] == full[1]["count"]
    with pytest.raises(CatalogError) as caught:
        query_catalog({"kind": "fonts", "family": "space"})
    assert caught.value.code == "catalog_bad_envelope"


def test_q_matches_id_and_name_case_insensitively(monkeypatch):
    found = query_catalog({"kind": "templates", "q": "ESTABLISHING"})["result"]
    assert [item["id"] for item in found["entries"]] == ["cinema-establishing"]
    monkeypatch.setitem(
        CATALOGS,
        "scenes.fonts.catalog",
        {"entries": [{"id": "sans", "name": "Grotesk"}, {"id": "serif", "name": "Old Style"}]},
    )
    named = query_catalog({"kind": "fonts", "q": "grotesk"})["result"]
    assert [item["id"] for item in named["entries"]] == ["sans"]
    with pytest.raises(CatalogError) as caught:
        query_catalog({"q": "x" * 81})
    assert caught.value.code == "catalog_bad_envelope"


def test_response_caps_at_200_entries(monkeypatch):
    fat = [{"id": f"n-{index:03d}", "name": "row"} for index in range(201)]
    monkeypatch.setitem(CATALOGS, "scenes.fonts.catalog", {"entries": fat})
    page = query_catalog({"kind": "fonts"})["result"]
    assert page["total"] == 201
    assert page["truncated"] is True
    assert len(page["entries"]) == 200
    assert page["entries"][0]["id"] == "n-000"
    assert page["entries"][-1]["id"] == "n-199"
    page["entries"][0]["id"] = "mutated"
    again = query_catalog({"kind": "fonts"})["result"]
    assert again["entries"][0]["id"] == "n-000"


def test_unknown_kind_uses_stable_code():
    with pytest.raises(CatalogError) as caught:
        query_catalog({"kind": "shaders"})
    assert caught.value.code == "catalog_unknown_kind"
    assert str(caught.value).startswith("catalog_unknown_kind:")
    operation = query_operation()
    assert operation["name"] == "scenes.catalog"
    assert operation["mutation"] is False
    reply = execute_query({"version": 1, "operation": "scenes.catalog", "input": {"kind": "finish"}})
    assert [item["id"] for item in reply["result"]["entries"]] == _ids(CATALOGS["scenes.finish.catalog"])


def test_http_catalog_uses_the_same_filters():
    client = _client()
    summary = client.get("/api/v1/scenes/catalog")
    assert summary.status_code == 200
    assert set(summary.json()["result"]) == {"kinds"}
    filtered = client.get("/api/v1/scenes/catalog", params={"kind": "templates", "family": "cinema", "q": "establishing"})
    assert filtered.status_code == 200
    body = filtered.json()["result"]
    assert [item["id"] for item in body["entries"]] == ["cinema-establishing"]
    unknown = client.get("/api/v1/scenes/catalog", params={"kind": "shaders"})
    assert unknown.status_code == 422
    assert unknown.json()["detail"]["code"] == "catalog_unknown_kind"
