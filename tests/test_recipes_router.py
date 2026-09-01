"""ASGI contracts for the extracted /api/v1/recipes router."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routers.recipes import create_recipes_router
from services import recipes as recipes_service


def _safe_join(base: str, *parts: str) -> str | None:
    joined = str(Path(base).joinpath(*parts).resolve())
    base_real = str(Path(base).resolve())
    if not joined.startswith(base_real):
        return None
    return joined


def _app(tmp_path: Path, *, nsfw=False, model_defs=None):
    out_dir = tmp_path / "outputs"
    out_dir.mkdir(exist_ok=True)
    defs = model_defs or {}
    app = FastAPI()
    app.include_router(create_recipes_router(
        workspace_dir=lambda workspace=None: str(out_dir),
        nsfw_allowed=lambda: nsfw,
        get_model_def=lambda model_type: defs.get(model_type),
        safe_join=_safe_join,
    ))
    return TestClient(app), out_dir


@pytest.fixture
def recipe_dirs(tmp_path, monkeypatch):
    bundled = tmp_path / "bundled"
    user = tmp_path / "user"
    bundled.mkdir()
    user.mkdir()
    monkeypatch.setattr(recipes_service, "BUNDLED_DIR", str(bundled))
    monkeypatch.setattr(recipes_service, "USER_DIR", str(user))
    return bundled, user


def _write_recipe(directory: Path, rid: str, **fields):
    payload = {
        "name": fields.get("name", rid),
        "description": fields.get("description", ""),
        "mode": fields.get("mode", "video"),
        "model_type": fields.get("model_type", "ltx2"),
        "loras": [],
        "params": {},
        "prompt_example": "",
        "nsfw": bool(fields.get("nsfw", False)),
    }
    (directory / f"{rid}.json").write_text(json.dumps(payload), encoding="utf-8")


def test_list_hides_nsfw_recipes_until_mature_mode(tmp_path, recipe_dirs):
    bundled, user = recipe_dirs
    _write_recipe(bundled, "safe", name="Safe")
    _write_recipe(user, "adult", name="Adult", nsfw=True)
    client, _ = _app(tmp_path, nsfw=False)
    listed = client.get("/api/v1/recipes").json()["recipes"]
    assert [item["id"] for item in listed] == ["safe"]

    mature, _ = _app(tmp_path, nsfw=True)
    listed = mature.get("/api/v1/recipes").json()["recipes"]
    assert {item["id"] for item in listed} == {"safe", "adult"}


def test_get_missing_and_nsfw_recipe_are_404(tmp_path, recipe_dirs):
    _write_recipe(recipe_dirs[1], "adult", name="Adult", nsfw=True)
    client, _ = _app(tmp_path, nsfw=False)
    assert client.get("/api/v1/recipes/missing").status_code == 404
    assert client.get("/api/v1/recipes/adult").status_code == 404
    mature, _ = _app(tmp_path, nsfw=True)
    body = mature.get("/api/v1/recipes/adult")
    assert body.status_code == 200
    assert body.json()["name"] == "Adult"


def test_thumbnail_missing_is_404(tmp_path, recipe_dirs):
    _write_recipe(recipe_dirs[0], "safe", name="Safe")
    client, _ = _app(tmp_path)
    assert client.get("/api/v1/recipes/safe/thumbnail").status_code == 404


def test_save_from_output_validates_name_file_and_sidecar(tmp_path, recipe_dirs):
    client, out_dir = _app(tmp_path)
    assert client.post("/api/v1/recipes/save-from-output", json={
        "output_name": "clip.mp4", "name": "",
    }).status_code == 400
    assert client.post("/api/v1/recipes/save-from-output", json={
        "output_name": "clip.mp4", "name": "Look",
    }).json()["detail"] == "Output file not found"

    (out_dir / "clip.mp4").write_bytes(b"media")
    assert client.post("/api/v1/recipes/save-from-output", json={
        "output_name": "clip.mp4", "name": "Look",
    }).json()["detail"] == "No settings metadata for this output"


def test_save_from_output_picks_mode_from_model_def(tmp_path, recipe_dirs):
    client, out_dir = _app(
        tmp_path,
        model_defs={"flux2": {"family": "flux", "image_outputs": True}},
    )
    (out_dir / "still.png").write_bytes(b"img")
    (out_dir / "still.meta.json").write_text(json.dumps({
        "params": {
            "model_type": "flux2",
            "prompt": "portrait",
            "resolution": "1024x1024",
            "activated_loras": ["look.safetensors"],
            "loras_multipliers": "0.8",
        },
    }), encoding="utf-8")
    card = client.post("/api/v1/recipes/save-from-output", json={
        "output_name": "still.png",
        "name": "Portrait look",
        "description": "from gallery",
    }).json()
    assert card["mode"] == "image"
    assert card["source"] == "user"
    stored = json.loads((recipe_dirs[1] / f"{card['id']}.json").read_text(encoding="utf-8"))
    assert stored["params"]["resolution"] == "1024x1024"
    assert stored["loras"][0]["filename"] == "look.safetensors"
    assert stored["loras"][0]["multiplier"] == "0.8"


def test_import_requires_name_and_delete_rejects_bundled(tmp_path, recipe_dirs):
    _write_recipe(recipe_dirs[0], "builtin", name="Builtin")
    client, _ = _app(tmp_path)
    assert client.post("/api/v1/recipes/import", json={}).json()["detail"] == "Invalid recipe: missing name"
    imported = client.post("/api/v1/recipes/import", json={"name": "Imported look"}).json()
    assert imported["source"] == "user"
    assert client.delete("/api/v1/recipes/builtin").status_code == 400
    assert client.delete(f"/api/v1/recipes/{imported['id']}").json() == {"status": "deleted"}
