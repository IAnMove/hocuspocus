import asyncio
import copy

import pytest
from fastapi.testclient import TestClient
from fastapi import FastAPI
from services.set_molds import load_mold, resolve_mold, validate_mold, surface_sizes
from services.set_commands import command_handlers
from routers.set_catalog import create_set_catalog_router


def test_opening_and_mark_must_fit():
    mold = load_mold("despacho")
    for kind in ("openings", "marks"):
        bad = copy.deepcopy(mold)
        if kind == "openings":
            bad[kind][0]["width"] = 100
        else:
            bad[kind][0]["position"] = [100, 0, 0]
        with pytest.raises(ValueError, match="outside"):
            validate_mold(bad)


def test_resolve_scales_positions_blocks_cameras_and_surfaces():
    medium = resolve_mold("despacho")
    large = resolve_mold("despacho", "large")
    assert large["cameras"][0]["position"][0] == pytest.approx(medium["cameras"][0]["position"][0] * 1.5)
    assert large["blocks"][0]["box"][3] == pytest.approx(2.7)
    assert surface_sizes(large)["wall_back"] == [9, 3.4]
    assert large["propAnchors"][0]["position"][1] == pytest.approx(0.85)


def test_catalog_rest_and_mcp_match():
    app = FastAPI(); app.include_router(create_set_catalog_router())
    rest = TestClient(app).get("/api/v1/scene3d/sets/catalog").json()
    mcp = asyncio.run(command_handlers()["scene3d.sets.catalog"]({"version": 1, "input": {}}))
    assert rest == mcp["result"]
    assert {"despacho", "bar"} <= {m["id"] for m in rest["molds"]}
