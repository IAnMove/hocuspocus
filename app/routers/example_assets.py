"""Preserve saved /examples/ URLs without shipping media in every installation."""
from pathlib import Path
import mimetypes

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response

from services.example_assets import ExampleAssets, ExampleUnavailable, example_assets


def create_example_assets_router(assets: ExampleAssets = example_assets) -> APIRouter:
    router = APIRouter(tags=["optional-examples"])

    @router.get("/examples/{asset_path:path}")
    @router.head("/examples/{asset_path:path}", include_in_schema=False)
    def get_example(asset_path: str, request: Request):
        name = asset_path + "index.html" if asset_path.endswith("/") or not asset_path else asset_path
        try:
            entry = assets.entry(name)
        except KeyError:
            if asset_path and not asset_path.endswith("/") and asset_path + "/index.html" in assets.files:
                return RedirectResponse(request.url.path + "/")
            raise HTTPException(404, "Unknown example") from None
        media_type = {".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
                      ".html": "text/html", ".glb": "model/gltf-binary"}.get(Path(name).suffix)
        media_type = media_type or mimetypes.guess_type(name)[0] or "application/octet-stream"
        headers = {"Cache-Control": "public, max-age=3600", "X-Content-Type-Options": "nosniff"}
        # HEAD must not turn metadata probes into downloads.
        if request.method == "HEAD":
            return Response(media_type=media_type, headers={**headers, "Content-Length": str(entry["size"])})
        try:
            path = assets.resolve(name)
        except ExampleUnavailable as error:
            raise HTTPException(503, str(error), headers={"Cache-Control": "no-store", "Retry-After": "30"}) from error
        return FileResponse(path, media_type=media_type, headers=headers)

    return router
