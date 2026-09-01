"""Studio recipe cards HTTP surface.

The launcher injects workspace, NSFW policy and model-def lookup so this
module never imports WanGP or the launch runtime.
"""
from __future__ import annotations

import json
import os
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from services import recipes as recipes_service


def _recipe_loras_from_params(params: dict) -> list[dict]:
    """Turn a generation's activated_loras + multipliers into recipe LoRA
    pointers, enriching with source URL / size from the url cache when we
    have it (so recipes re-fetch on other machines)."""
    activated = params.get("activated_loras", []) or []
    mults = (params.get("loras_multipliers", "") or "").split()
    url_cache = {}
    try:
        cache_path = os.path.join(os.getcwd(), "loras_url_cache.json")
        if os.path.isfile(cache_path):
            with open(cache_path, "r", encoding="utf-8") as handle:
                url_cache = json.load(handle) or {}
    except Exception:
        url_cache = {}
    out = []
    for index, fname in enumerate(activated):
        base = os.path.basename(str(fname))
        entry = {"filename": base, "multiplier": mults[index] if index < len(mults) else "1.0"}
        info = url_cache.get(base) or url_cache.get(fname)
        if isinstance(info, dict):
            if info.get("download_url"):
                entry["source_url"] = info["download_url"]
            if info.get("size_mb"):
                entry["size_mb"] = info["size_mb"]
        out.append(entry)
    return out


def create_recipes_router(
    *,
    workspace_dir: Callable[..., str],
    nsfw_allowed: Callable[[], bool],
    get_model_def: Callable[[str], Any],
    safe_join: Callable[..., str | None],
) -> APIRouter:
    router = APIRouter()

    @router.get("/api/v1/recipes")
    def list_recipes_route():
        """List recipe cards (bundled + user). NSFW recipes hidden unless mature."""
        return {"recipes": recipes_service.list_recipes(nsfw_allowed=nsfw_allowed())}

    @router.get("/api/v1/recipes/{rid}")
    def get_recipe_route(rid: str):
        recipe = recipes_service.get_recipe(rid)
        if not recipe:
            raise HTTPException(status_code=404, detail="Recipe not found")
        if recipe.get("nsfw") and not nsfw_allowed():
            raise HTTPException(status_code=404, detail="Recipe not found")
        return recipe

    @router.get("/api/v1/recipes/{rid}/thumbnail")
    def get_recipe_thumbnail_route(rid: str):
        path = recipes_service.get_recipe_thumbnail_path(rid)
        if not path:
            raise HTTPException(status_code=404, detail="No thumbnail")
        return FileResponse(path, media_type="image/jpeg")

    @router.post("/api/v1/recipes/save-from-output")
    async def save_recipe_from_output_route(request: Request):
        """Create a user recipe from an existing gallery output.

        Body: { output_name, name, description, nsfw? }. The output's sidecar
        supplies model + LoRAs + settings; the media file supplies the
        thumbnail. LoRA source URLs are recovered from the loras_url_cache so
        the recipe can re-fetch them on another machine.
        """
        body = await request.json()
        output_name = body.get("output_name", "")
        name = (body.get("name") or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="Recipe name is required")

        out_dir = workspace_dir()
        media_path = safe_join(out_dir, output_name) if output_name else None
        if not media_path or not os.path.isfile(media_path):
            raise HTTPException(status_code=400, detail="Output file not found")

        meta_path = os.path.join(out_dir, os.path.splitext(output_name)[0] + ".meta.json")
        params: dict = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as handle:
                    params = (json.load(handle) or {}).get("params", {}) or {}
            except Exception:
                params = {}
        if not params:
            raise HTTPException(status_code=400, detail="No settings metadata for this output")

        model_type = params.get("model_type", "")
        mode = "video"
        try:
            md = get_model_def(model_type) or {}
            family = (md.get("family") or "").lower()
            if md.get("image_outputs") or family in ("flux", "qwen", "z_image", "hidream"):
                mode = "image"
            elif md.get("audio_only") or family in ("ace_step", "tts"):
                mode = "audio"
        except Exception:
            pass

        loras = _recipe_loras_from_params(params)
        prompt_example = params.get("_tts_original_prompt") or params.get("prompt", "") or ""
        return recipes_service.save_recipe_from_params(
            name=name,
            description=body.get("description", ""),
            params=params,
            mode=mode,
            loras=loras,
            prompt_example=prompt_example,
            source_media=media_path,
            nsfw=bool(body.get("nsfw", False)),
        )

    @router.post("/api/v1/recipes/import")
    async def import_recipe_route(request: Request):
        body = await request.json()
        try:
            return recipes_service.import_recipe(body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("/api/v1/recipes/{rid}")
    def delete_recipe_route(rid: str):
        if not recipes_service.delete_recipe(rid):
            raise HTTPException(status_code=400, detail="Recipe not found or is a built-in (can't delete)")
        return {"status": "deleted"}

    return router
